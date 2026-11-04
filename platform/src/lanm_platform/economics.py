"""Independent, transparent separation-unit economics; standard library only.

This is a prospective annual-equivalent cost model, not a fitted column model or
plant cashflow simulator. Collected target output is an input, never a function
of a normalized protein screening score.
"""
from __future__ import annotations

import math
from copy import deepcopy

METHOD_ID = "separation_unit_tea"
METHOD_VERSION = "1.0.0"

# Values are illustrative scenario estimates, not properties of any candidate.
PARAMETERS = {
    "prepared_material_cost_usd_per_l": (100.0, "USD/L", "Prepared operating material"),
    "collected_target_kg_per_l_cycle": (0.0005, "kg/L/cycle", "Collected target per operating cycle"),
    "usable_lifetime_cycles": (100.0, "cycle", "Assumed service life"),
    "cycle_time_hours": (8.0, "h/cycle", "Complete load/wash/elute/regenerate cycle"),
    "target_production_kg_per_day": (0.1, "kg/day", "Target production on operating days"),
    "operating_days_per_year": (330.0, "day/year", "Operating days"),
    "regeneration_cost_usd_per_l_cycle": (0.1, "USD/L/cycle", "Recurring chemicals and regeneration"),
    "electricity_kwh_per_l_cycle": (0.02, "kWh/L/cycle", "Pumping and other electricity"),
    "electricity_price_usd_per_kwh": (0.12, "USD/kWh", "Electricity tariff"),
    "labor_hours_per_day": (1.0, "h/day", "Allocated operator time"),
    "labor_rate_usd_per_hour": (35.0, "USD/h", "Loaded labor rate"),
    "equipment_cost_usd": (10000.0, "USD", "Installed equipment at the evaluated size"),
    "equipment_life_years": (10.0, "year", "Equipment economic life"),
    "discount_rate": (0.08, "fraction", "Annual capital recovery rate"),
    "maintenance_fraction_per_year": (0.03, "1/year", "Annual maintenance fraction of equipment cost"),
    "product_price_usd_per_kg": (0.0, "USD/kg", "Optional value per kg of target in the specified product"),
    "cost_ceiling_usd_per_kg": (250.0, "USD/kg", "Declared cost allowance"),
    "minimum_purity_fraction": (0.9, "fraction", "Declared minimum product purity"),
    "minimum_recovery_fraction": (0.8, "fraction", "Declared minimum target recovery"),
}
OPTIONAL_PARAMETERS = {
    "product_purity_fraction": "fraction",
    "target_recovery_fraction": "fraction",
    "feed_target_kg_per_l": "kg/L",
    "feed_volume_l_per_l_cycle": "L/L/cycle",
}
UNITS = {key: item[1] for key, item in PARAMETERS.items()} | OPTIONAL_PARAMETERS
DEFAULTS = {key: item[0] for key, item in PARAMETERS.items()}
POSITIVE = {"collected_target_kg_per_l_cycle", "usable_lifetime_cycles", "cycle_time_hours",
            "target_production_kg_per_day", "operating_days_per_year", "equipment_life_years"}
FRACTIONS = {"discount_rate", "maintenance_fraction_per_year", "minimum_purity_fraction",
             "minimum_recovery_fraction", "product_purity_fraction", "target_recovery_fraction"}
BOUNDARY = {
    "name": "Annual-equivalent operating separation-unit cost",
    "inlet": "A pretreated aqueous feed with suitable chemical conditions",
    "outlet": "A collected enriched solution; product specification is declared separately",
    "denominator": "kg of elemental target actually collected, not total REE or oxide mass",
    "included": ["Operating material replacement", "Recurring chemicals/regeneration", "Electricity",
                 "Allocated labor", "Annualized installed equipment", "Equipment maintenance"],
    "excluded": ["Upstream mining/leaching/pretreatment", "Downstream product finishing and refining",
                 "Waste treatment unless included in a declared input", "Taxes, financing, startup and working capital",
                 "Protein manufacturing process design", "Column transport/hydrodynamics and scale-dependent performance"],
    "assumptions": ["Constant collected output and cycle duration during service life",
                    "Sufficient suitable feed and 24 hours of operation per operating day",
                    "Linear material inventory calculation; no claim that larger columns preserve performance",
                    "Continuous replacement allocation; initial material inventory is reported separately",
                    "Equipment input is already installed cost for this evaluated configuration; no automatic size scaling"],
}


def validate_values(values: dict, *, partial: bool = True) -> dict:
    if not isinstance(values, dict):
        raise ValueError("Assumptions must be an object mapping parameter names to numeric values")
    unknown = set(values) - set(UNITS)
    if unknown:
        raise ValueError("Unsupported assumption(s): " + ", ".join(sorted(unknown)))
    output = {}
    for key, value in values.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"{key} must be a finite number")
        value = float(value)
        if value < 0 or (key in POSITIVE and value <= 0):
            raise ValueError(f"{key} must be {'positive' if key in POSITIVE else 'nonnegative'}")
        if key in FRACTIONS and value > 1:
            raise ValueError(f"{key} is a fraction and cannot exceed 1")
        if key == "operating_days_per_year" and value > 366:
            raise ValueError("operating_days_per_year cannot exceed 366")
        output[key] = value
    if not partial and set(PARAMETERS) - set(output):
        raise ValueError("Missing model inputs: " + ", ".join(sorted(set(PARAMETERS) - set(output))))
    return output


def _evaluate(values: dict) -> dict:
    """Evaluate an explicit complete scenario without mutating it."""
    x = validate_values(values, partial=False)
    q, n, hours = (x[k] for k in ("collected_target_kg_per_l_cycle", "usable_lifetime_cycles", "cycle_time_hours"))
    cycles_per_day = 24.0 / hours
    annual_cycles = cycles_per_day * x["operating_days_per_year"]
    productivity = q * cycles_per_day
    bed = x["target_production_kg_per_day"] / productivity
    annual_target = x["target_production_kg_per_day"] * x["operating_days_per_year"]
    material = x["prepared_material_cost_usd_per_l"] * bed * annual_cycles / n
    chemicals = x["regeneration_cost_usd_per_l_cycle"] * bed * annual_cycles
    electricity = x["electricity_kwh_per_l_cycle"] * bed * annual_cycles * x["electricity_price_usd_per_kwh"]
    labor = x["labor_hours_per_day"] * x["labor_rate_usd_per_hour"] * x["operating_days_per_year"]
    rate, life = x["discount_rate"], x["equipment_life_years"]
    # Algebraically stable capital recovery factor for large lifetimes.
    crf = 1.0 / life if rate == 0 else rate / (-math.expm1(-life * math.log1p(rate)))
    capital = x["equipment_cost_usd"] * crf
    maintenance = x["equipment_cost_usd"] * x["maintenance_fraction_per_year"]
    components = [("Material replacement", material), ("Chemicals and regeneration", chemicals),
                  ("Electricity", electricity), ("Labor", labor), ("Annualized equipment", capital),
                  ("Maintenance", maintenance)]
    total = sum(cost for _, cost in components)
    summary = {"cost_usd_per_kg": total / annual_target, "annual_target_kg": annual_target,
               "annual_cost_usd": total, "required_bed_volume_l": bed,
               "productivity_kg_per_l_day": productivity, "cycles_per_year": annual_cycles,
               "initial_material_inventory_cost_usd": x["prepared_material_cost_usd_per_l"] * bed,
               "capital_recovery_factor": crf, "calendar_service_life_years": n / annual_cycles,
               "nonmaterial_cost_usd_per_kg": (total - material) / annual_target}
    if not all(math.isfinite(v) for v in summary.values()):
        raise ValueError("Scenario exceeds supported finite numeric range")
    if x["product_price_usd_per_kg"] > 0:
        summary["assumed_product_value_usd_per_year"] = x["product_price_usd_per_kg"] * annual_target
        summary["conditional_separation_margin_usd_per_year"] = summary["assumed_product_value_usd_per_year"] - total
    uncertainties = ["All unmeasured inputs are explicit scenario estimates; default values are illustrative, not literature-derived.",
                     "Capacity, recovery, purity and service life are not inferred from screening profiles.",
                     "Observed reuse cycles do not establish maximum usable lifetime.",
                     "No probability distribution is assigned; parameter sweeps are scenarios, not confidence intervals.",
                     "This separation-unit result is not full plant TEA, profitability, or demonstrated scale-up."]
    checks = []
    for key, threshold in (("product_purity_fraction", "minimum_purity_fraction"),
                           ("target_recovery_fraction", "minimum_recovery_fraction")):
        checks.append({"parameter": key, "status": "unknown" if key not in x else "meets" if x[key] >= x[threshold] else "below",
                       "value": x.get(key), "threshold": x[threshold]})
    feed_keys = {"feed_target_kg_per_l", "feed_volume_l_per_l_cycle"}
    if feed_keys <= set(x):
        offered = x["feed_target_kg_per_l"] * x["feed_volume_l_per_l_cycle"]
        possible = offered * x.get("target_recovery_fraction", 1.0)
        if q > possible * (1 + 1e-10):
            raise ValueError("Collected target per cycle exceeds declared target feed and recovery; reconcile the mass balance")
        summary["target_feed_kg_per_l_cycle"] = offered
    elif feed_keys & set(x):
        uncertainties.append("Only part of the feed specification is available; feed mass balance was not checked.")
    return {"method_id": METHOD_ID, "method_version": METHOD_VERSION, "summary": summary,
            "cost_breakdown": [{"name": name, "annual_cost_usd": cost, "cost_usd_per_kg": cost / annual_target} for name, cost in components],
            "assumptions": deepcopy(x), "units": dict(UNITS), "boundary": deepcopy(BOUNDARY),
            "uncertainties": uncertainties, "specification_checks": checks,
            "formulas": {"bed_volume": "target_kg_per_day / (collected_kg_per_l_cycle * 24 / cycle_hours)",
                         "annual_material_replacement": "material_USD_per_L * bed_L * cycles_per_year / usable_cycles",
                         "unit_cost": "sum(annual cost components) / annual_collected_target_kg"},
            "break_even_lifetime": break_even_lifetime(x, summary=summary)}


def evaluate(values: dict) -> dict:
    try:
        return _evaluate(values)
    except (ArithmeticError, OverflowError) as error:
        raise ValueError("Scenario arithmetic exceeds the supported finite numeric range") from error


def break_even_lifetime(values: dict, ceiling: float | None = None, *, summary=None) -> dict:
    x = validate_values(values, partial=False)
    ceiling = x["cost_ceiling_usd_per_kg"] if ceiling is None else validate_values({"cost_ceiling_usd_per_kg": ceiling})["cost_ceiling_usd_per_kg"]
    if summary is None:
        summary = evaluate(x)["summary"]
    remaining = ceiling - summary["nonmaterial_cost_usd_per_kg"]
    if remaining <= 0:
        return {"status": "unattainable_by_reuse_alone", "required_cycles": None, "ceiling_usd_per_kg": ceiling,
                "reason": "Other separation-unit costs already meet or exceed the allowance."}
    ratio = x["prepared_material_cost_usd_per_l"] / (x["collected_target_kg_per_l_cycle"] * remaining)
    nearest = round(ratio)
    if math.isclose(ratio, nearest, rel_tol=1e-12, abs_tol=1e-12):
        ratio = nearest
    cycles = max(1, math.ceil(ratio))
    return {"status": "conditional", "required_cycles": cycles, "ceiling_usd_per_kg": ceiling,
            "reason": "Required under unchanged per-cycle output and all other cost assumptions; not observed service life."}


def sensitivity(values: dict, parameter: str, trial_values: list[float]) -> dict:
    if parameter not in UNITS or not isinstance(trial_values, list) or not 1 <= len(trial_values) <= 100:
        raise ValueError("Supply a supported parameter and between 1 and 100 trial values")
    base = validate_values(values, partial=False)
    rows = []
    for value in trial_values:
        trial = {**base, **validate_values({parameter: value})}
        result = evaluate(trial)
        rows.append({"value": value, "cost_usd_per_kg": result["summary"]["cost_usd_per_kg"],
                     "required_bed_volume_l": result["summary"]["required_bed_volume_l"]})
    return {"parameter": parameter, "unit": UNITS[parameter], "rows": rows,
            "interpretation": "Explicit hypothetical scenarios; other inputs held constant; not a statistical confidence interval."}


def manifest() -> dict:
    return {"id": METHOD_ID, "name": "Separation-unit economics", "version": METHOD_VERSION,
            "status": "registered", "kind": "builtin", "description": BOUNDARY["name"],
            "scientific_status": "Independent transparent scenario model; not validated against an operating LanM plant",
            "input_schema": {key: {"type": "number", "unit": unit, "default": DEFAULTS.get(key),
                                   "required": key in PARAMETERS} for key, unit in UNITS.items()},
            "boundary": deepcopy(BOUNDARY)}
