"""Deterministic policy decisions for proposed actions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Protocol
from urllib.parse import urlparse

from .actions import Action, ActionKind, RiskLevel


class Decision(str, Enum):
    """A policy decision made before an action reaches an executor."""

    ALLOW = "allow"
    CONFIRM = "confirm"
    DENY = "deny"


@dataclass(frozen=True)
class PolicyOutcome:
    decision: Decision
    reason: str
    policy: str


class Policy(Protocol):
    """A small, composable policy contract."""

    def evaluate(self, action: Action) -> PolicyOutcome | None:
        """Return an outcome when the policy applies, otherwise ``None``."""


class RiskPolicy:
    """Require confirmation for actions with external or critical effects."""

    def __init__(self, confirm_at: RiskLevel = RiskLevel.EXTERNAL) -> None:
        self.confirm_at = confirm_at

    def evaluate(self, action: Action) -> PolicyOutcome | None:
        if action.risk >= self.confirm_at:
            return PolicyOutcome(
                Decision.CONFIRM,
                f"risk level {int(action.risk)} requires human confirmation",
                type(self).__name__,
            )
        return None


class DomainAllowlistPolicy:
    """Restrict navigation actions to an explicit set of HTTP(S) hosts."""

    def __init__(self, allowed_domains: Iterable[str]) -> None:
        self.allowed_domains = {
            domain.lower().strip().lstrip(".")
            for domain in allowed_domains
            if domain.strip()
        }

    def evaluate(self, action: Action) -> PolicyOutcome | None:
        if action.kind is not ActionKind.NAVIGATE:
            return None

        url = str(action.params.get("url", ""))
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme not in {"http", "https"} or not host:
            return PolicyOutcome(
                Decision.DENY,
                "navigation requires a valid HTTP(S) URL",
                type(self).__name__,
            )

        allowed = any(
            host == domain or host.endswith(f".{domain}")
            for domain in self.allowed_domains
        )
        if not allowed:
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
        self.terms = tuple(term.lower() for term in terms)

    def evaluate(self, action: Action) -> PolicyOutcome | None:
        if action.kind is not ActionKind.TYPE:
            return None
        target = str(action.params.get("target", "")).lower()
        if any(term in target for term in self.terms):
            return PolicyOutcome(
                Decision.CONFIRM,
                "typing target may contain sensitive or consequential data",
                type(self).__name__,
            )
        return None


class PolicyEngine:
    """Combine policies using deny-over-confirm-over-allow precedence."""

    def __init__(self, policies: Iterable[Policy] = ()) -> None:
        self.policies = tuple(policies)

    @classmethod
    def standard(
        cls, allowed_domains: Iterable[str] | None = None
    ) -> "PolicyEngine":
        policies: list[Policy] = [RiskPolicy(), SensitiveTargetPolicy()]
        if allowed_domains is not None:
            policies.append(DomainAllowlistPolicy(allowed_domains))
        return cls(policies)

    def evaluate(self, action: Action) -> PolicyOutcome:
        outcomes = [
            outcome
            for policy in self.policies
            if (outcome := policy.evaluate(action)) is not None
        ]
        if not outcomes:
            return PolicyOutcome(Decision.ALLOW, "no policy blocked the action", "default")
        for decision in (Decision.DENY, Decision.CONFIRM):
            if match := next((item for item in outcomes if item.decision is decision), None):
                return match
        return outcomes[0]
