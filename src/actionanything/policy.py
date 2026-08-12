"""Deterministic, fail-closed policy decisions for canonical actions."""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Protocol
from urllib.parse import urlsplit

from .actions import Action, ActionKind, RiskLevel


_DECIMAL_IPV4_PART = re.compile(r"^[0-9]+$")
_HEXADECIMAL_IPV4_PART = re.compile(r"^0[xX][0-9a-fA-F]+$")


def _normalize_hostname(host: str) -> str | None:
    """Return an ASCII hostname suitable for security comparisons.

    Browsers apply IDNA processing before navigation.  Applying the same
    normalization here prevents a Unicode spelling of ``localhost`` from
    bypassing the literal-host checks below.
    """

    if not isinstance(host, str):
        return None
    try:
        normalized = host.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError:
        return None
    return normalized or None


def _legacy_ipv4_part_value(part: str) -> int | None:
    """Parse one URL-standard legacy IPv4 number component when unambiguous."""

    if _HEXADECIMAL_IPV4_PART.fullmatch(part):
        return int(part[2:], 16)
    if not _DECIMAL_IPV4_PART.fullmatch(part):
        return None
    # A leading zero is interpreted as octal by browser URL parsers when the
    # digits allow it.  Treat an 8/9-containing component as decimal for the
    # purpose of conservative legacy-form detection: either representation is
    # a numeric-looking hostname that should not reach a browser unchecked.
    if (
        len(part) > 1
        and part.startswith("0")
        and all(digit in "01234567" for digit in part)
    ):
        return int(part, 8)
    return int(part, 10)


def _is_noncanonical_numeric_ipv4(host: str) -> bool:
    """Return whether ``host`` is a browser-accepted legacy IPv4 spelling.

    ``ipaddress`` correctly handles canonical dotted IPv4 but intentionally
    rejects browser forms such as ``2130706433``, ``0177.0.0.1`` and
    ``0x7f.1``.  Only recognize actual numeric components here; a broad
    hexadecimal character class would incorrectly classify normal DNS names
    such as ``bad.cafe`` and ``dead.beef`` as IP-like.
    """

    try:
        ipaddress.IPv4Address(host)
    except ValueError:
        pass
    else:
        return False

    parts = host.split(".")
    if not 1 <= len(parts) <= 4:
        return False
    values = [_legacy_ipv4_part_value(part) for part in parts]
    if any(value is None for value in values):
        return False

    # URL IPv4 parsing permits one to four components.  All but the final
    # component occupy one byte; the final component fills the remaining
    # bytes.  Reject only forms that can actually be interpreted as IPv4.
    maximums = {
        1: (0xFFFFFFFF,),
        2: (0xFF, 0xFFFFFF),
        3: (0xFF, 0xFF, 0xFFFF),
        4: (0xFF, 0xFF, 0xFF, 0xFF),
    }[len(parts)]
    return all(value <= maximum for value, maximum in zip(values, maximums))


def _is_valid_dns_hostname(host: str) -> bool:
    """Return whether an ASCII hostname has unambiguous DNS label syntax."""

    if len(host) > 253:
        return False
    labels = host.split(".")
    return all(
        label
        and len(label) <= 63
        and not label.startswith("-")
        and not label.endswith("-")
        and all(character.isascii() and (character.isalnum() or character == "-") for character in label)
        for label in labels
    )


def _public_http_hostname(url: str) -> str | None:
    """Return a public, normalized HTTP(S) hostname or ``None``.

    Accessing ``ParseResult.port`` is deliberate: Python defers malformed port
    validation until that property is read.  Policy evaluation must fail
    closed rather than treating ``https://example.com:not-a-port`` as safe.
    """

    if not isinstance(url, str):
        return None
    try:
        parsed = urlsplit(url)
        if parsed.scheme.lower() not in {"http", "https"}:
            return None
        if parsed.username is not None or parsed.password is not None:
            return None
        host = _normalize_hostname(parsed.hostname or "")
        # Force validation of malformed, out-of-range, and otherwise invalid
        # ports. Port zero is not a usable remote HTTP endpoint, so reject it
        # rather than leaving interpretation to a browser.
        port = parsed.port
    except (TypeError, UnicodeError, ValueError):
        return None

    if host is None or "%" in host:
        # Percent-encoded host separators can be decoded by URL consumers;
        # IPv6 zone identifiers are local-link syntax.  Neither is public.
        return None
    if port is not None and not 1 <= port <= 65_535:
        return None
    if host == "localhost" or host.endswith(".localhost"):
        return None
    if _is_noncanonical_numeric_ipv4(host):
        return None
    try:
        return host if ipaddress.ip_address(host).is_global else None
    except ValueError:
        # A hostname that is not an IP literal remains unresolved by design.
        # DNS rebinding is an executor-isolation concern, documented at the
        # public helper below.
        return host if _is_valid_dns_hostname(host) else None


class Decision(str, Enum):
    """A policy decision made before an action reaches an executor."""

    ALLOW = "allow"
    CONFIRM = "confirm"
    DENY = "deny"


@dataclass(frozen=True)
class PolicyOutcome:
    """A validated decision returned by a policy."""

    decision: Decision
    reason: str
    policy: str

    def __post_init__(self) -> None:
        try:
            decision = Decision(self.decision)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"unsupported policy decision: {self.decision!r}") from exc
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("policy reason must be a non-empty string")
        if not isinstance(self.policy, str) or not self.policy.strip():
            raise ValueError("policy name must be a non-empty string")
        object.__setattr__(self, "decision", decision)


class Policy(Protocol):
    """A small, composable policy contract."""

    def evaluate(self, action: Action) -> PolicyOutcome | None:
        """Return an outcome when the policy applies, otherwise ``None``."""


def is_public_http_url(url: str) -> bool:
    """Return whether a URL is HTTP(S) and does not name a local literal host.

    This check intentionally does not resolve DNS.  An executor still needs
    network-level isolation because a public-looking hostname can resolve to a
    private address (for example through DNS rebinding).
    """

    return _public_http_hostname(url) is not None


def normalize_allowed_domains(domains: Iterable[str]) -> frozenset[str]:
    """Normalize hostname allowlist entries and reject ambiguous values."""

    normalized: set[str] = set()
    for value in domains:
        if not isinstance(value, str):
            raise ValueError("allowed domains must be strings")
        domain = value.strip().rstrip(".").lstrip(".")
        if not domain or any(character.isspace() for character in domain):
            raise ValueError("allowed domains must be non-empty hostnames")
        if any(character in domain for character in ":/@?#"):
            raise ValueError("allowed domains must be hostnames, not URLs")
        try:
            domain = domain.encode("idna").decode("ascii").lower()
        except UnicodeError as exc:
            raise ValueError(f"invalid allowed domain: {value!r}") from exc
        if _is_noncanonical_numeric_ipv4(domain):
            raise ValueError("allowed domains must not use numeric IP-like host forms")
        try:
            ipaddress.ip_address(domain)
        except ValueError:
            pass
        else:
            raise ValueError("allowed domains must not be IP addresses")
        labels = domain.split(".")
        if any(
            not label
            or len(label) > 63
            or label.startswith("-")
            or label.endswith("-")
            or not all(character.isalnum() or character == "-" for character in label)
            for label in labels
        ):
            raise ValueError(f"invalid allowed domain: {value!r}")
        normalized.add(domain)
    return frozenset(normalized)


def host_is_allowed(host: str, allowed_domains: Iterable[str]) -> bool:
    """Return whether a hostname equals or is a subdomain of an allowlist item."""

    candidate = _normalize_hostname(host)
    if candidate is None:
        return False
    return any(
        candidate == domain or candidate.endswith(f".{domain}")
        for domain in allowed_domains
    )


class RiskPolicy:
    """Require confirmation at or above a chosen trusted risk floor.

    Canonical ``CLICK`` and ``TYPE`` actions have the ``REVERSIBLE`` floor.
    Requiring confirmation at that floor makes the standard engine conservative
    even when an untrusted plan omits risk or claims that an effect is harmless.
    Applications can use a more permissive custom policy only after they have a
    trusted source classification and an explicit product-level safety review.
    """

    def __init__(self, confirm_at: RiskLevel = RiskLevel.REVERSIBLE) -> None:
        try:
            self.confirm_at = RiskLevel(confirm_at)
        except (TypeError, ValueError) as exc:
            raise ValueError("confirm_at must be a RiskLevel") from exc

    def evaluate(self, action: Action) -> PolicyOutcome | None:
        if action.risk >= self.confirm_at:
            return PolicyOutcome(
                Decision.CONFIRM,
                f"risk level {int(action.risk)} requires human confirmation",
                type(self).__name__,
            )
        return None


class SafeNavigationPolicy:
    """Reject non-public or credential-bearing navigation targets."""

    def evaluate(self, action: Action) -> PolicyOutcome | None:
        if action.kind is not ActionKind.NAVIGATE:
            return None
        url = str(action.params["url"])
        if not is_public_http_url(url):
            return PolicyOutcome(
                Decision.DENY,
                "navigation requires a public HTTP(S) URL without credentials",
                type(self).__name__,
            )
        return None


class DomainAllowlistPolicy:
    """Restrict navigation actions to explicit HTTP(S) hosts.

    This policy only makes a decision about the proposed navigation. Browser
    executors should also enforce the same allowlist for redirects, click-driven
    navigation, popups, and subresources.
    """

    def __init__(self, allowed_domains: Iterable[str]) -> None:
        self.allowed_domains = normalize_allowed_domains(allowed_domains)

    def evaluate(self, action: Action) -> PolicyOutcome | None:
        if action.kind is not ActionKind.NAVIGATE:
            return None

        url = str(action.params["url"])
        host = _public_http_hostname(url)
        if host is None:
            return PolicyOutcome(
                Decision.DENY,
                "navigation requires a public HTTP(S) URL without credentials",
                type(self).__name__,
            )
        if not self.allowed_domains:
            return PolicyOutcome(
                Decision.DENY,
                "navigation requires an explicit domain allowlist",
                type(self).__name__,
            )

        if not host_is_allowed(host, self.allowed_domains):
            return PolicyOutcome(
                Decision.DENY,
                f"domain '{host}' is outside the allowlist",
                type(self).__name__,
            )
        return None


class SensitiveTargetPolicy:
    """Ask for confirmation before typing into sensitive-looking fields."""

    DEFAULT_TERMS = ("password", "payment", "card", "checkout", "delete")

    def __init__(self, terms: Iterable[str] = DEFAULT_TERMS) -> None:
        self.terms = tuple(term.lower() for term in terms if term)

    def evaluate(self, action: Action) -> PolicyOutcome | None:
        if action.kind is not ActionKind.TYPE:
            return None
        target = str(action.params.get("selector", "")).lower()
        if any(term in target for term in self.terms):
            return PolicyOutcome(
                Decision.CONFIRM,
                "typing target may contain sensitive or consequential data",
                type(self).__name__,
            )
        return None


class PolicyEngine:
    """Combine policies using deny-over-confirm-over-allow precedence.

    Invalid custom policy output and policy exceptions fail closed. A safety
    control that cannot evaluate must never become an implicit allow. Each
    policy receives its own canonical action snapshot, so policies communicate
    only through returned ``PolicyOutcome`` values, never by mutating an
    action object that a later policy will inspect.
    """

    def __init__(self, policies: Iterable[Policy] = ()) -> None:
        self.policies = tuple(policies)

    @classmethod
    def standard(
        cls, allowed_domains: Iterable[str] | None = None
    ) -> "PolicyEngine":
        return cls(
            [
                SafeNavigationPolicy(),
                DomainAllowlistPolicy(allowed_domains or ()),
                RiskPolicy(),
                SensitiveTargetPolicy(),
            ]
        )

    def evaluate(self, action: Action) -> PolicyOutcome:
        outcomes: list[PolicyOutcome] = []
        for policy in self.policies:
            name = type(policy).__name__
            try:
                # ``Action`` is frozen, but in-process extensions can still
                # use object internals to mutate it. Rehydrate a distinct
                # canonical value for every policy so one extension cannot
                # downgrade the input that another safety policy evaluates.
                policy_action = Action(
                    id=action.id,
                    kind=action.kind,
                    params=action.params,
                    risk=action.risk,
                    metadata=action.metadata,
                )
                outcome = policy.evaluate(policy_action)
            except Exception:
                outcomes.append(
                    PolicyOutcome(
                        Decision.DENY,
                        "policy evaluation failed; action denied",
                        name,
                    )
                )
                continue
            if outcome is None:
                continue
            if not isinstance(outcome, PolicyOutcome):
                outcomes.append(
                    PolicyOutcome(
                        Decision.DENY,
                        "policy returned an invalid outcome; action denied",
                        name,
                    )
                )
                continue
            outcomes.append(outcome)

        if not outcomes:
            return PolicyOutcome(Decision.ALLOW, "no policy blocked the action", "default")
        for decision in (Decision.DENY, Decision.CONFIRM):
            match = next((item for item in outcomes if item.decision is decision), None)
            if match is not None:
                return match
        return outcomes[0]
