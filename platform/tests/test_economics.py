import math
import unittest

from lanm_platform import economics


class EconomicsTests(unittest.TestCase):
    def case(self):
        return {**economics.DEFAULTS, "prepared_material_cost_usd_per_l": 20,
                "collected_target_kg_per_l_cycle": .01, "usable_lifetime_cycles": 10,
                "cycle_time_hours": 24, "target_production_kg_per_day": 1,
                "operating_days_per_year": 100, "regeneration_cost_usd_per_l_cycle": .1,
                "electricity_kwh_per_l_cycle": .5, "electricity_price_usd_per_kwh": .2,
                "labor_hours_per_day": 2, "labor_rate_usd_per_hour": 5,
                "equipment_cost_usd": 1000, "equipment_life_years": 10,
                "discount_rate": 0, "maintenance_fraction_per_year": .01}

    def test_independent_hand_calculated_cost_and_units(self):
        result = economics.evaluate(self.case())
        summary = result["summary"]
        self.assertAlmostEqual(summary["required_bed_volume_l"], 100)
        self.assertAlmostEqual(summary["annual_target_kg"], 100)
        self.assertAlmostEqual(summary["annual_cost_usd"], 23110)
        self.assertAlmostEqual(summary["cost_usd_per_kg"], 231.1)
        self.assertEqual([r["annual_cost_usd"] for r in result["cost_breakdown"]], [20000, 1000, 1000, 1000, 100, 10])
        self.assertAlmostEqual(sum(r["cost_usd_per_kg"] for r in result["cost_breakdown"]), summary["cost_usd_per_kg"])

    def test_lifetime_affects_only_replacement(self):
        base = self.case()
        one = economics.evaluate(base)
        two = economics.evaluate({**base, "usable_lifetime_cycles": 20})
        self.assertEqual(one["cost_breakdown"][1:], two["cost_breakdown"][1:])
        self.assertAlmostEqual(two["cost_breakdown"][0]["annual_cost_usd"], 10000)

    def test_no_double_count_of_recovery(self):
        one = economics.evaluate(self.case())
        two = economics.evaluate({**self.case(), "target_recovery_fraction": .4})
        self.assertEqual(one["summary"], two["summary"])
        self.assertEqual(two["specification_checks"][1]["status"], "below")

    def test_declared_feed_mass_balance(self):
        with self.assertRaisesRegex(ValueError, "exceeds declared target feed"):
            economics.evaluate({**self.case(), "feed_target_kg_per_l": .01,
                                "feed_volume_l_per_l_cycle": 1, "target_recovery_fraction": .8})

    def test_capital_recovery_nonzero_discount(self):
        result = economics.evaluate({**self.case(), "discount_rate": .1})
        self.assertAlmostEqual(result["summary"]["capital_recovery_factor"], .1 * 1.1**10 / (1.1**10 - 1))

    def test_break_even_required_cycles(self):
        result = economics.break_even_lifetime(self.case(), ceiling=240)
        self.assertEqual(result["required_cycles"], 10)
        self.assertLessEqual(economics.evaluate({**self.case(), "usable_lifetime_cycles": 10})["summary"]["cost_usd_per_kg"], 240)
        self.assertGreater(economics.evaluate({**self.case(), "usable_lifetime_cycles": 9})["summary"]["cost_usd_per_kg"], 240)
        self.assertEqual(economics.break_even_lifetime(self.case(), ceiling=30)["status"], "unattainable_by_reuse_alone")
        self.assertEqual(economics.break_even_lifetime(self.case(), ceiling=231.1)["required_cycles"], 10)

    def test_sensitivity_is_pure_and_not_confidence_interval(self):
        values = self.case()
        result = economics.sensitivity(values, "usable_lifetime_cycles", [10, 20])
        self.assertEqual(values["usable_lifetime_cycles"], 10)
        self.assertGreater(result["rows"][0]["cost_usd_per_kg"], result["rows"][1]["cost_usd_per_kg"])
        self.assertIn("not a statistical", result["interpretation"])

    def test_validation_rejects_unphysical_and_unknown_inputs(self):
        for change in ({"cycle_time_hours": 0}, {"usable_lifetime_cycles": -1}, {"product_purity_fraction": 95},
                       {"equipment_cost_usd": math.inf}, {"discount_rate": True}, {"screen_score_as_capacity": 1},
                       {"collected_target_kg_per_l_cycle": 5e-324, "cycle_time_hours": 1e308}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                economics.evaluate({**self.case(), **change})


if __name__ == "__main__":
    unittest.main()
