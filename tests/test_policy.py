import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from tempfile import TemporaryDirectory

from actionanything import (
    Action,
    ActionKind,
    ActionRuntime,
    Decision,
    DryRunExecutor,
    PolicyEngine,
    ResultStatus,
    RiskLevel,
    TraceRecorder,
    read_trace,
)
from actionanything.policy import (
    DomainAllowlistPolicy,
    PolicyOutcome,
    RiskPolicy,
    SelectorAllowlistPolicy,
    host_is_allowed,
    is_public_http_url,
    normalize_allowed_domains,
    normalize_allowed_selectors,
)


class BrokenPolicy:
    def evaluate(self, action):
        raise RuntimeError("broken")


class InvalidPolicy:
    def evaluate(self, action):
        return "allow"


class RecordingExecutor:
    is_dry_run = True

    def __init__(self) -> None:
        self.actions = []

    def execute(self, action):
        self.actions.append(action)
        return {}


class RiskDowngradingPolicy:
    def evaluate(self, action):
        object.__setattr__(action, "risk", RiskLevel.NONE)
        return None


class DivergentText(str):
    def __str__(self) -> str:
        return "https://example.com/"


class PolicyTests(unittest.TestCase):
    def test_standard_policy_confirms_untrusted_click_and_type_actions(self) -> None:
        for action in (
            Action(ActionKind.CLICK, {"selector": "#safe"}),
            Action(ActionKind.TYPE, {"text": "untrusted input"}),
        ):
            with self.subTest(kind=action.kind):
                outcome = PolicyEngine.standard().evaluate(action)
                self.assertIs(outcome.decision, Decision.CONFIRM)

    def test_standard_policy_allows_non_effecting_actions(self) -> None:
        for action in (
            Action(ActionKind.SCROLL, {"delta_y": 100}),
            Action(ActionKind.WAIT, {"milliseconds": 1}),
        ):
            with self.subTest(kind=action.kind):
                outcome = PolicyEngine.standard().evaluate(action)
                self.assertIs(outcome.decision, Decision.ALLOW)

    def test_external_action_requires_confirmation(self) -> None:
        action = Action(
            ActionKind.CLICK,
            {"selector": "#submit"},
            risk=RiskLevel.EXTERNAL,
        )
        outcome = PolicyEngine.standard().evaluate(action)
        self.assertIs(outcome.decision, Decision.CONFIRM)

    def test_navigation_requires_explicit_allowlist(self) -> None:
        action = Action(ActionKind.NAVIGATE, {"url": "https://example.com"})
        self.assertIs(PolicyEngine.standard().evaluate(action).decision, Decision.DENY)

    def test_allowlist_accepts_domain_and_subdomain(self) -> None:
        engine = PolicyEngine.standard(["example.com"])
        for url in ("https://example.com", "https://docs.example.com/page"):
            with self.subTest(url=url):
                action = Action(ActionKind.NAVIGATE, {"url": url})
                self.assertIs(engine.evaluate(action).decision, Decision.ALLOW)

    def test_allowlist_denies_unlisted_domain(self) -> None:
        engine = PolicyEngine.standard(["example.com"])
        action = Action(ActionKind.NAVIGATE, {"url": "https://example.org"})
        self.assertIs(engine.evaluate(action).decision, Decision.DENY)

    def test_default_navigation_policy_denies_private_targets(self) -> None:
        for url in (
            "http://localhost:3000",
            "http://127.0.0.1",
            "http://10.0.0.1",
            "http://[::1]",
            "http://169.254.169.254/latest/meta-data",
        ):
            with self.subTest(url=url):
                action = Action(ActionKind.NAVIGATE, {"url": url})
                self.assertIs(PolicyEngine.standard(["example.com"]).evaluate(action).decision, Decision.DENY)
                self.assertFalse(is_public_http_url(url))

    def test_navigation_rejects_legacy_numeric_ipv4_forms(self) -> None:
        # These are browser-recognized IPv4 spellings that ipaddress does not
        # parse as canonical literals. Several resolve to 127.0.0.1.
        for url in (
            "http://2130706433/",
            "http://0x7f000001/",
            "http://0177.0.0.1/",
            "http://127.1/",
            "http://0x7f.1/",
            "http://.127.0.0.1/",
            "http://127..1/",
        ):
            with self.subTest(url=url):
                self.assertFalse(is_public_http_url(url))

    def test_policy_observes_the_base_value_of_a_string_subclass(self) -> None:
        action = Action(
            ActionKind.NAVIGATE,
            {"url": DivergentText("http://127.0.0.1/")},
        )

        self.assertIs(
            PolicyEngine.standard(["example.com"]).evaluate(action).decision,
            Decision.DENY,
        )

    def test_navigation_keeps_public_and_hex_looking_domain_names_distinct(self) -> None:
        self.assertTrue(is_public_http_url("https://8.8.8.8/"))
        engine = PolicyEngine.standard(["bad.cafe", "dead.beef"])
        for url in ("https://bad.cafe/", "https://api.dead.beef/path"):
            with self.subTest(url=url):
                self.assertIs(
                    engine.evaluate(Action(ActionKind.NAVIGATE, {"url": url})).decision,
                    Decision.ALLOW,
                )

    def test_navigation_rejects_unicode_hostnames_to_avoid_idna_mismatch(self) -> None:
        for url in (
            "https://faß.de/",
            "https://ｅxample.com/",
            "https://example。com/",
            "http://ⓛocalhost/",
        ):
            with self.subTest(url=url):
                self.assertFalse(is_public_http_url(url))
                action = Action(ActionKind.NAVIGATE, {"url": url})
                self.assertIs(
                    PolicyEngine.standard(["example.com"]).evaluate(action).decision,
                    Decision.DENY,
                )

        collision_action = Action(ActionKind.NAVIGATE, {"url": "https://faß.de/"})
        self.assertIs(
            PolicyEngine.standard(["fass.de"]).evaluate(collision_action).decision,
            Decision.DENY,
        )

    def test_allowlist_requires_explicit_ascii_punycode_for_internationalized_domains(self) -> None:
        for domain in ("faß.de", "例子.测试", "ｅxample.com", "example。com"):
            with self.subTest(domain=domain):
                with self.assertRaisesRegex(ValueError, "ASCII hostnames"):
                    normalize_allowed_domains([domain])

        allowlist = normalize_allowed_domains(["XN--FA-HIA.DE."])
        self.assertEqual(allowlist, frozenset({"xn--fa-hia.de"}))
        self.assertTrue(host_is_allowed("xn--fa-hia.de", allowlist))
        self.assertTrue(host_is_allowed("www.xn--fa-hia.de", allowlist))
        self.assertFalse(host_is_allowed("faß.de", allowlist))
        engine = PolicyEngine.standard(allowlist)
        self.assertIs(
            engine.evaluate(
                Action(ActionKind.NAVIGATE, {"url": "https://xn--fa-hia.de/"})
            ).decision,
            Decision.ALLOW,
        )

    def test_navigation_rejects_malformed_ports_fail_closed(self) -> None:
        for url in (
            "https://example.com:not-a-port/",
            "https://example.com:0/",
            "https://example.com:65536/",
            "https://[::1",
        ):
            with self.subTest(url=url):
                self.assertFalse(is_public_http_url(url))

    def test_sensitive_target_requires_confirmation(self) -> None:
        engine = PolicyEngine.standard()
        action = Action(
            ActionKind.TYPE,
            {"selector": "input[name=password]", "text": "not-a-real-secret"},
        )
        self.assertIs(engine.evaluate(action).decision, Decision.CONFIRM)

    def test_selector_allowlist_requires_exact_selector_and_still_confirms(self) -> None:
        policy = SelectorAllowlistPolicy({"#compose", "input[name=email]"})
        for action in (
            Action(ActionKind.CLICK, {"selector": "#compose"}),
            Action(
                ActionKind.TYPE,
                {
                    "selector": "input[name=email]",
                    "text": "test@example.com",
                    "press_enter": True,
                },
            ),
        ):
            with self.subTest(action=action):
                outcome = policy.evaluate(action)
                self.assertIsNotNone(outcome)
                self.assertIs(outcome.decision, Decision.CONFIRM)
        self.assertIsNone(
            policy.evaluate(Action(ActionKind.WAIT, {"milliseconds": 1}))
        )

    def test_selector_allowlist_denies_non_matching_and_unaddressable_targets(self) -> None:
        secret = "untrusted-selector-token"
        policy = SelectorAllowlistPolicy({"#allowed"})
        for action in (
            Action(ActionKind.CLICK, {"selector": "#allowed-extra"}),
            Action(ActionKind.CLICK, {"selector": " #allowed"}),
            Action(ActionKind.CLICK, {"selector": "#allowed, #other"}),
            Action(ActionKind.CLICK, {"selector": "xpath=//button"}),
            Action(ActionKind.CLICK, {"x": 1, "y": 2}),
            Action(ActionKind.TYPE, {"text": "focused input"}),
            Action(ActionKind.TYPE, {"selector": secret, "text": "value"}),
        ):
            with self.subTest(action=action):
                outcome = policy.evaluate(action)
                self.assertIsNotNone(outcome)
                self.assertIs(outcome.decision, Decision.DENY)
                self.assertNotIn(secret, outcome.reason)

    def test_selector_allowlist_is_immutable_and_strictly_validated(self) -> None:
        source = ["#allowed"]
        policy = SelectorAllowlistPolicy(source)
        source.append("#later")
        self.assertEqual(policy.allowed_selectors, frozenset({"#allowed"}))
        with self.assertRaises(FrozenInstanceError):
            policy.allowed_selectors = frozenset({"#replacement"})  # type: ignore[misc]
        for invalid in (
            "#not-an-iterable",
            b"#not-an-iterable",
            1,
            {"#allowed": True},
            [""],
            ["   "],
            [" #allowed"],
            ["#allowed\n"],
            [None],
            ["x" * 4_097],
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    SelectorAllowlistPolicy(invalid)
        self.assertEqual(normalize_allowed_selectors(()), frozenset())

    def test_selector_allowlist_policy_blocks_executor_for_coordinate_and_focused_actions(self) -> None:
        executor = RecordingExecutor()
        confirmations = []
        runtime = ActionRuntime(
            executor,
            policy=PolicyEngine.standard(allowed_selectors={"#allowed"}),
            confirm=lambda *args: confirmations.append(args) or True,
        )
        for action in (
            Action(ActionKind.CLICK, {"x": 1, "y": 2}),
            Action(ActionKind.TYPE, {"text": "focused input"}),
        ):
            with self.subTest(action=action):
                result = runtime.execute(action)
                self.assertIs(result.status, ResultStatus.DENIED)
        self.assertEqual(executor.actions, [])
        self.assertEqual(confirmations, [])

    def test_standard_selector_configuration_is_opt_in_and_empty_fails_closed(self) -> None:
        default_outcome = PolicyEngine.standard().evaluate(
            Action(ActionKind.CLICK, {"selector": "#unlisted"})
        )
        empty_outcome = PolicyEngine.standard(allowed_selectors=()).evaluate(
            Action(ActionKind.CLICK, {"selector": "#unlisted"})
        )
        allowed_outcome = PolicyEngine.standard(allowed_selectors={"#allowed"}).evaluate(
            Action(ActionKind.CLICK, {"selector": "#allowed"})
        )
        self.assertIs(default_outcome.decision, Decision.CONFIRM)
        self.assertIs(empty_outcome.decision, Decision.DENY)
        self.assertIs(allowed_outcome.decision, Decision.CONFIRM)

    def test_standard_selector_match_is_the_confirmation_and_trace_provenance(self) -> None:
        with TemporaryDirectory() as directory:
            trace = Path(directory) / "trace.jsonl"
            action = Action(ActionKind.CLICK, {"selector": "#approved"})
            policy = PolicyEngine.standard(allowed_selectors={"#approved"})
            outcome = policy.evaluate(action)
            result = ActionRuntime(
                DryRunExecutor(),
                policy=policy,
                recorder=TraceRecorder(trace, redact=False),
                confirm=lambda *_: True,
            ).execute(action)
            event = next(read_trace(trace))

        self.assertIs(outcome.decision, Decision.CONFIRM)
        self.assertEqual(outcome.policy, SelectorAllowlistPolicy.__name__)
        self.assertIs(result.status, ResultStatus.DRY_RUN)
        self.assertEqual(event["policy"]["name"], SelectorAllowlistPolicy.__name__)

    def test_deny_takes_precedence_over_confirmation(self) -> None:
        engine = PolicyEngine(
            [RiskPolicy(), DomainAllowlistPolicy(["example.com"])]
        )
        action = Action(
            ActionKind.NAVIGATE,
            {"url": "https://blocked.example.org"},
            risk=RiskLevel.EXTERNAL,
        )
        self.assertIs(engine.evaluate(action).decision, Decision.DENY)

    def test_policy_failures_fail_closed(self) -> None:
        action = Action(ActionKind.CLICK, {"selector": "#safe"})
        for policy in (BrokenPolicy(), InvalidPolicy()):
            with self.subTest(policy=type(policy).__name__):
                outcome = PolicyEngine([policy]).evaluate(action)
                self.assertIs(outcome.decision, Decision.DENY)

    def test_policies_receive_isolated_action_snapshots(self) -> None:
        action = Action(ActionKind.CLICK, {"selector": "#send"})

        outcome = PolicyEngine(
            [RiskDowngradingPolicy(), RiskPolicy()]
        ).evaluate(action)

        self.assertIs(outcome.decision, Decision.CONFIRM)
        self.assertEqual(outcome.policy, "RiskPolicy")
        self.assertIs(action.risk, RiskLevel.REVERSIBLE)

    def test_policy_outcome_normalizes_decision(self) -> None:
        outcome = PolicyOutcome("deny", "reason", "test")
        self.assertIs(outcome.decision, Decision.DENY)


if __name__ == "__main__":
    unittest.main()
