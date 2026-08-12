import unittest

from actionanything import Action, ActionKind, RiskLevel


class ActionTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        action = Action(
            ActionKind.CLICK,
            {"selector": "#submit"},
            RiskLevel.REVERSIBLE,
            id="action-1",
            metadata={"source": "test"},
        )

        self.assertEqual(Action.from_dict(action.to_dict()), action)

    def test_missing_kind_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires 'kind'"):
            Action.from_dict({"params": {}})

    def test_unknown_kind_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            Action.from_dict({"kind": "launch_missile"})

    def test_params_are_copied(self) -> None:
        params = {"selector": "button"}
        action = Action(ActionKind.CLICK, params)
        params["selector"] = "a"
        self.assertEqual(action.params["selector"], "button")


if __name__ == "__main__":
    unittest.main()

