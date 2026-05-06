import unittest

from src.simulation.payoff_rules import build_payoff_rules, stage_finish_value, transfer_buy_fee


class PayoffRulesTest(unittest.TestCase):
    def test_core_payoffs_are_encoded(self):
        rules = build_payoff_rules()

        self.assertEqual(stage_finish_value(1, rules), 200_000)
        self.assertEqual(stage_finish_value(15, rules), 15_000)
        self.assertEqual(stage_finish_value(16, rules), 0)
        self.assertEqual(rules["stage_depth_bonus"][8], 400_000)
        self.assertEqual(rules["status_penalties"]["dns_per_remaining_stage"], -100_000)

    def test_transfer_fee_is_buy_price_only(self):
        self.assertEqual(transfer_buy_fee(10_000_000), 100_000)


if __name__ == "__main__":
    unittest.main()

