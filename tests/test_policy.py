import unittest

from actionanything import Action, ActionKind, Decision, PolicyEngine, RiskLevel
from actionanything.policy import DomainAllowlistPolicy, RiskPolicy


class PolicyTests(unittest.TestCase):
    def test_standard_policy_allows_low_risk_action(self) -> None:
        outcome = PolicyEngine.standard().evaluate(Action(ActionKind.CLICK))
        self.assertIs(outcome.decision, Decision.ALLOW)

    def test_external_action_requires_confirmation(self) -> None:
        action = Action(ActionKind.CLICK, risk=RiskLevel.EXTERNAL)
        outcome = PolicyEngine.standard().evaluate(action)
        self.assertIs(outcome.decision, Decision.CONFIRM)

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

    def test_allowlist_denies_non_http_url(self) -> None:
        policy = DomainAllowlistPolicy(["example.com"])
        action = Action(ActionKind.NAVIGATE, {"url": "file:///etc/passwd"})
        self.assertIs(policy.evaluate(action).decision, Decision.DENY)

    def test_sensitive_target_requires_confirmation(self) -> None:
        engine = PolicyEngine.standard()
        action = Action(
            ActionKind.TYPE,
            {"selector": "input[name=password]", "text": "not-a-real-secret"},
        )
        self.assertIs(engine.evaluate(action).decision, Decision.CONFIRM)

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


if __name__ == "__main__":
    unittest.main()

