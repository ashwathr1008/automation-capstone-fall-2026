"""Expanded isolated workflow fixtures; no model calls or scientific quality grades."""
from __future__ import annotations

from copy import deepcopy
import json
import math
from lanm_platform.methods import Registry, execute_source

VERSION = "1.0.0"
PREFIX = ("This is an isolated software evaluation. Use only this project's local platform tools; "
          "no live web/literature search or laboratory automation. All newly supplied records are synthetic "
          "software fixtures, not real measurements. Preserve unrelated project records.\n\n")
CONDITIONS = {"target": "Nd", "support": "synthetic support A", "feed": "synthetic feed A", "pH": 5}
METRICS = {"collected_target_kg_per_l_cycle": .001, "recovery_fraction": .85,
           "purity_fraction": .95, "cycles_observed": 4, "cycle_time_hours": 12}
EXPERIMENT_LABEL = "Synthetic evaluation result"
SOURCE_TEXT = ("SYNTHETIC COST NOTE. This is a fictional software fixture, not published experimental evidence. "
               "The scenario unit price for prepared operating material is 72 USD/L. "
               "Its price basis is supplier estimate. No useful service lifetime has been established. "
               "An unrelated packaging line lists 19 USD/item; that is not the operating-material unit price.")
CONFLICT_TEXT = "SYNTHETIC revised price estimate: prepared operating material costs 95 USD/L; no measured service lifetime is supplied."
SOURCE_URL = "https://example.org/lanm-evaluation/synthetic-cost-note"
METHOD_ID = "evaluation-material-cost"
METHOD_CODE = ('def calculate(inputs):\n'
               '    if inputs["output"] <= 0 or inputs["cycles"] <= 0:\n'
               '        raise ValueError("Positive output and cycles required")\n'
               '    return {"usd_per_kg": inputs["cost"] / (inputs["output"] * inputs["cycles"])}\n')
METHOD_MANIFEST = {
    "name": "Synthetic material replacement model", "description": "Software fixture: replacement cost only",
    "boundary": "Prepared material replacement per kg of collected target; other costs excluded",
    "assumptions": ["Constant collected output per cycle; supplied lifetime is hypothetical"],
    "inputs": {"cost": {"unit": "USD/L"}, "output": {"unit": "kg/L/cycle"}, "cycles": {"unit": "cycle"}},
    "references": ["Independent fixture arithmetic, not experimental evidence"],
    "reference_cases": [{"name": "Independent reference", "inputs": {"cost": 120, "output": .002, "cycles": 60},
                         "expected": {"usd_per_kg": 1000}, "basis": "120 / (0.002 * 60) = 1000 USD/kg"}],
}


def _case(identifier, title, turns, criteria, mode="research", family="workflow"):
    return {"id": identifier, "title": title, "question": "\n\nNext user turn:\n".join(turns),
            "turns": turns, "mode": mode, "family": family, "category": "objective_tool_contract",
            "reference_criteria": criteria, "fixture_version": VERSION}


CASES = [
    _case("wf_evidence_extract", "Read archived evidence and save a structured extraction", [
        "Read archived source {source_id}. Save one new source titled 'Extracted cost fields' with the same URL. "
        "Its text must be a plain JSON object containing unit_price_usd_per_l (number), price_basis (text), "
        "and service_life_established (boolean), extracted from that source. Preserve the original source. "
        "Do not change assumptions or create experiments."],
        ["Distinguishes a synthetic price estimate from measured process performance.",
         "Explains that missing service-life evidence remains unknown."], family="evidence"),
    _case("wf_source_conflict", "Preserve conflicting archived evidence", [
        "Archive this exact supplied text as a new source titled 'Revised synthetic estimate', URL " + SOURCE_URL + ":\n" + CONFLICT_TEXT +
        "\nKeep the existing source {source_id} intact. Explain the disagreement, but do not choose a new project "
        "price assumption or create an experiment."],
        ["Reports both estimates and their synthetic status without treating either as verified truth."], family="evidence"),
    _case("wf_assumption_revision", "Revise assumptions across turns while preserving calculations", [
        "Persist usable_lifetime_cycles = 60 for the shared project scenario, with reason 'Conservative software scenario'. "
        "Then calculate and save economics. Leave every other assumption and all experiments unchanged.",
        "Now revise the same shared lifetime assumption to 120, with reason 'Longer-life software scenario', and save "
        "a new economic calculation. Preserve the earlier 60-cycle result. Explain which cost component changed."],
        ["Separates assumed lifetime from observed reuse and explains replacement-cost behavior."], family="state_and_history"),
    _case("wf_candidate_override", "Keep a candidate-specific scenario separate from shared assumptions", [
        "For candidate o-36 only, persist usable_lifetime_cycles = 80 with reason 'Candidate-specific hypothetical case'. "
        "Save economic calculations for o-36 and o-37. Do not change the shared lifetime or any other inputs; do not "
        "create or accept experiments. Explain why the candidate scenarios differ."],
        ["Does not present a candidate override as measured protein performance."], family="state_and_history"),
    _case("wf_sensitivity", "Save a two-parameter sensitivity analysis", [
        "Save a sensitivity analysis for exactly usable_lifetime_cycles and prepared_material_cost_usd_per_l using "
        "multiplicative factors [0.5, 1, 2]. Do not commit any changes to inputs or experiments. Describe which "
        "directions increase costs and explain the uncertainty limits."],
        ["Interprets deterministic scenarios without calling them confidence intervals."], family="economics"),
    _case("wf_draft_only", "Draft processed data without accepting it", [
        "Create exactly one DRAFT experiment for o-36 labelled '" + EXPERIMENT_LABEL + "'. Conditions: {conditions_json}. "
        "Metrics: {metrics_json}. Notes: 'Synthetic software fixture; not laboratory data'. "
        "I am not accepting this experiment. Leave assumptions unchanged and explain its current status."],
        ["Keeps a draft separate from accepted measurements and the updated candidate pool."], family="experiment_records"),
    _case("wf_accept_after_review", "Accept a draft only on the second explicit user turn", [
        "Create exactly one DRAFT experiment for o-36 labelled '" + EXPERIMENT_LABEL + "'. Conditions: {conditions_json}. "
        "Metrics: {metrics_json}. Notes: 'Synthetic software fixture; not laboratory data'. Do not accept it yet.",
        "I now explicitly accept the draft you just created for o-36, with reason 'Reviewed synthetic fixture for software evaluation'. "
        "Accept that same record, then calculate and save o-36 economics using its applicable accepted results. "
        "Do not create another experiment or change shared assumptions."],
        ["Calls acceptance a user review decision, not independent scientific validation.",
         "Does not replace useful lifetime with the number of observed cycles."], family="experiment_records"),
    _case("wf_mismatched_conditions", "Respect mismatched accepted experimental conditions", [
        "This project contains an accepted synthetic o-36 experiment performed at a different pH. Rank the updated "
        "pool and save the result, then calculate and save o-36 economics. Do not edit or reaccept the experiment, "
        "change configuration, or change assumptions. Explain why the accepted result does or does not apply."],
        ["Identifies the pH mismatch and does not use mismatched measurements as project predictions."], family="experiment_records"),
    _case("wf_scale_prediction", "Save and calculate an explicit larger-unit scenario", [
        "Save a scale prediction labelled 'Synthetic 200 L scenario' with intended total operating bed volume 200 L, "
        "scale description 'Synthetic support A with synthetic feed A; no physical transport prediction', and basis "
        "'User-supplied software scenario, not a measurement'. Use exactly these supplied values: {prediction_json}. "
        "Then calculate that saved prediction. Do not change project inputs or create experiments. Report whether "
        "its intended and arithmetically required bed volumes agree."],
        ["Distinguishes inventory arithmetic from physically validated scale-up."], family="economics"),
    _case("wf_registered_method", "Discover and reuse an existing checked method", [
        "Find the registered version of evaluation-material-cost using the method tools, inspect its inputs, then run "
        "that exact registered version with cost=90, output=0.003, cycles=75 and save the result in this project. "
        "Do not author another method, change assumptions, or create experiments. State the output units and boundary."],
        ["Reports 400 USD/kg as material replacement only, rather than full separation cost."], family="reusable_methods"),
    _case("wf_build_method", "Build, check, register and use a small reusable economic method", [
        "Build a reusable numerical method with ID evaluation-total-cost. Input keys: annual_cost_usd (USD/year) and "
        "annual_output_kg (kg/year); output key usd_per_kg = annual_cost_usd / annual_output_kg. Reject output <= 0 "
        "and negative annual cost. Document that the model divides supplied annual cost by collected target output "
        "and does not estimate physical performance. Include two independent reference cases: 1200/12=100 and "
        "3000/20=150 USD/kg, with their arithmetic basis. Check the draft, register it only if checks pass, then run "
        "the exact registered version at annual_cost_usd=2400 and annual_output_kg=8 and save its result. "
        "Leave assumptions and experiments unchanged."],
        ["Explains that passing arithmetic examples does not establish scientific validity."], mode="build", family="reusable_methods"),
    _case("wf_clarify_export", "Continue an exact selection after a missing bound is supplied", [
        "Use saved selection {selection_id} for an export of exactly two candidates, with minimum stock volume 50 uL. "
        "The maximum is not decided. Ask for it before creating a batch; do not rerank or replace the selection.",
        "Use maximum 80 uL and seed 11. Now create exactly one software-demo CSV batch of those same two selected "
        "candidates in their saved order. Return its saved download link. Do not rerank, create another selection, "
        "change project assumptions, or run automation."],
        ["Asks a useful clarification before exporting and provides the actual saved download link."], family="selection_and_export"),
]


def prediction_values():
    return {"collected_target_kg_per_l_cycle": .001, "cycle_time_hours": 12, "usable_lifetime_cycles": 60,
            "target_production_kg_per_day": .4, "equipment_cost_usd": 20000,
            "labor_hours_per_day": 2, "labor_rate_usd_per_hour": 40}


def setup(store, case):
    """Return project ID, fixture context, and user turns with no grading rubric."""
    pid = store.create_project("Comparison: " + case["id"], "Nd", "La",
                               description="Isolated synthetic workflow evaluation; no laboratory data.")["id"]
    context = {"conditions_json": json.dumps(CONDITIONS, sort_keys=True),
               "metrics_json": json.dumps(METRICS, sort_keys=True),
               "prediction_json": json.dumps(prediction_values(), sort_keys=True)}
    identifier = case["id"]
    if identifier in {"wf_evidence_extract", "wf_source_conflict"}:
        source = store.add_source(pid, "Original synthetic cost note", SOURCE_TEXT, SOURCE_URL)
        context["source_id"] = source["id"]
    if identifier in {"wf_draft_only", "wf_accept_after_review", "wf_mismatched_conditions"}:
        store.update_project(pid, {"configuration": CONDITIONS}, "Synthetic fixture conditions")
    if identifier == "wf_mismatched_conditions":
        experiment = store.add_experiment(pid, "o-36", EXPERIMENT_LABEL, {**CONDITIONS, "pH": 6}, METRICS,
                                          "Synthetic mismatched-condition fixture")
        store.accept_experiment(experiment["id"], "Fixture initialization, not real laboratory acceptance")
        context["experiment_id"] = experiment["id"]
    if identifier == "wf_registered_method":
        registry = Registry(store.data_dir)
        registry.create_draft(METHOD_ID, deepcopy(METHOD_MANIFEST), METHOD_CODE)
        if not registry.check(METHOD_ID)["passed"]:
            raise ValueError("Independent method fixture failed its reference arithmetic")
        context["method_id"] = registry.register(METHOD_ID)["id"]
    if identifier == "wf_clarify_export":
        ranking = store.rank(pid, "untested", 3)
        ids = [ranking["rows"][2]["candidate_id"], ranking["rows"][0]["candidate_id"]]
        selection = store.save_testing_selection(pid, ranking["id"], ids, "Fixed software evaluation selection")
        context.update(selection_id=selection["id"], candidate_ids=ids, ranking_run_id=ranking["id"])
    turns = [PREFIX + turn.format(**context) for turn in case["turns"]]
    return pid, context, turns


def snapshot(store, project_id):
    """Capture persisted scientific state, excluding messages."""
    registry = Registry(store.data_dir)
    methods = registry.list()
    for method in methods:
        if method.get("kind") != "builtin" and method.get("status") != "built-in":
            method["source"] = registry.get(method["id"])["source"]
    return {"project": store.get_project(project_id), "runs": store.list_runs(project_id),
            "sources": store.list_sources(project_id), "experiments": store._experiments(project_id),
            "selections": store.list_testing_selections(project_id), "batches": store.list_testing_batches(project_id),
            "predictions": store.list_scale_predictions(project_id), "methods": methods}


def _semantic(project):
    return {key: deepcopy(project[key]) for key in ("revision", "assumptions", "configuration",
                                                    "experiment_count", "accepted_experiment_count")}


def _same_except(before, after, allowed):
    return {k: v for k, v in before.items() if k not in allowed} == {k: v for k, v in after.items() if k not in allowed}


def _near(actual, expected):
    return isinstance(actual, (int, float)) and not isinstance(actual, bool) and math.isfinite(actual) and math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-10)


def _check(identifier, passed, basis):
    return {"id": identifier, "passed": bool(passed), "basis": basis}


def _method_behavior(method):
    """Independently probe saved numerical source, without writing or calling a model."""
    try:
        for inputs, expected in (({"annual_cost_usd": 1000, "annual_output_kg": 4}, 250),
                                 ({"annual_cost_usd": 0, "annual_output_kg": 3}, 0)):
            if not _near(execute_source(method["source"], inputs).get("usd_per_kg"), expected):
                return False
        for inputs in ({"annual_cost_usd": -1, "annual_output_kg": 2},
                       {"annual_cost_usd": 100, "annual_output_kg": 0},
                       {"annual_cost_usd": 100, "annual_output_kg": -1}):
            try:
                execute_source(method["source"], inputs)
            except ValueError:
                continue
            return False
        return True
    except Exception:
        return False


def check_turn(case_id, turn_index, initial, current, context):
    """Milestones prevent later success from erasing an earlier premature write."""
    checks = []
    if turn_index == 0 and case_id == "wf_accept_after_review":
        exps = current["experiments"]
        checks.append(_check("first_turn_draft_not_accepted", len(exps) == 1 and exps[0]["status"] == "draft",
                             "Before explicit acceptance, exactly one draft exists and remains unaccepted."))
    if turn_index == 0 and case_id == "wf_clarify_export":
        checks.append(_check("first_turn_waited_for_upper_bound", not current["batches"],
                             "No batch is saved before the user supplies the maximum volume."))
    if turn_index == 0 and case_id == "wf_assumption_revision":
        calculations = [r for r in current["runs"] if r.get("kind") == "calculate"]
        checks.append(_check("first_turn_saved_60_cycle_scenario",
                             current["project"]["assumptions"].get("usable_lifetime_cycles") == 60 and
                             any(r["assumptions"].get("usable_lifetime_cycles") == 60 for r in calculations),
                             "The first turn commits and calculates the requested 60-cycle scenario."))
    return {"scope": "Persisted per-turn milestones only; answer quality is not graded.", "checks": checks}


def check(case_id, initial, final, context, trace=None):
    """Evaluate persisted facts, never scientific truth or free-text answer quality."""
    before, after = initial["project"], final["project"]
    runs = final["runs"]
    calculations = [r for r in runs if r.get("kind") == "calculate"]
    checks = []
    mutable = {"wf_assumption_revision", "wf_candidate_override", "wf_draft_only", "wf_accept_after_review"}
    if case_id not in mutable:
        checks.append(_check("committed_inputs_and_experiments_unchanged", _semantic(before) == _semantic(after),
                             "Exact project input, configuration, revision and experiment-count comparison."))
    else:
        checks.append(_check("configuration_preserved", before["configuration"] == after["configuration"],
                             "No task requests a configuration change."))

    if case_id in {"wf_evidence_extract", "wf_source_conflict"}:
        original = next(s for s in initial["sources"] if s["id"] == context["source_id"])
        checks.append(_check("original_source_preserved", original in final["sources"],
                             "Original archived evidence remains byte-for-byte in its saved record."))
        new = [s for s in final["sources"] if s["id"] not in {s["id"] for s in initial["sources"]}]
        if case_id == "wf_evidence_extract":
            matching = []
            for source in new:
                try:
                    extracted = json.loads(source["text"])
                except (ValueError, TypeError):
                    continue
                if (source["title"] == "Extracted cost fields" and source["url"] == SOURCE_URL and
                        isinstance(extracted, dict) and type(extracted.get("service_life_established")) is bool and
                        extracted == {"unit_price_usd_per_l": 72, "price_basis": "supplier estimate", "service_life_established": False}):
                    matching.append(source)
            checks.append(_check("exact_structured_extraction_saved", len(new) == len(matching) == 1,
                                 "One JSON extraction preserves the correct price, basis and absent lifetime evidence."))
        else:
            checks.append(_check("conflicting_source_archived_without_replacement", len(new) == 1 and
                                 new[0]["text"] == CONFLICT_TEXT and new[0]["title"] == "Revised synthetic estimate" and new[0]["url"] == SOURCE_URL,
                                 "The exact supplied conflicting note is separately archived."))
    elif case_id == "wf_assumption_revision":
        checks.append(_check("only_shared_lifetime_changed", after["assumptions"].get("usable_lifetime_cycles") == 120 and
                             _same_except(before["assumptions"], after["assumptions"], {"usable_lifetime_cycles"}) and not final["experiments"],
                             "Final shared lifetime is 120; other assumptions and experiment records remain unchanged."))
        changes = [(r.get("values", {}).get("usable_lifetime_cycles"), r.get("reason")) for r in after["revisions"][len(before["revisions"]):]]
        checks.append(_check("requested_revision_history_preserved", changes == [(60, "Conservative software scenario"), (120, "Longer-life software scenario")],
                             "Both requested revisions and reasons survive in order, with no extra revision."))
        a = [r for r in calculations if r["assumptions"].get("usable_lifetime_cycles") == 60]
        b = [r for r in calculations if r["assumptions"].get("usable_lifetime_cycles") == 120]
        checks.append(_check("both_calculation_snapshots_preserved", bool(a and b) and len(calculations) == 2,
                             "Two saved calculations retain their own 60- and 120-cycle inputs."))
    elif case_id == "wf_candidate_override":
        new_revisions = after["revisions"][len(before["revisions"]):]
        checks.append(_check("override_scope_and_shared_inputs_preserved", before["assumptions"] == after["assumptions"] and
                             len(new_revisions) == 1 and new_revisions[0]["candidate_id"] == "o-36" and
                             new_revisions[0]["values"] == {"usable_lifetime_cycles": 80} and not final["experiments"],
                             "Exactly one o-36-only lifetime override is saved; shared inputs and experiments are intact."))
        by_candidate = {r.get("candidate_id"): r for r in calculations}
        checks.append(_check("separate_candidate_scenarios_calculated", len(calculations) == 2 and
                             by_candidate.get("o-36", {}).get("assumptions", {}).get("usable_lifetime_cycles") == 80 and
                             by_candidate.get("o-37", {}).get("assumptions", {}).get("usable_lifetime_cycles") == before["assumptions"]["usable_lifetime_cycles"],
                             "Two candidate calculations preserve the distinction between overridden and shared inputs."))
    elif case_id == "wf_sensitivity":
        sweeps = [r for r in runs if r.get("kind") == "sensitivity"]
        keys = {"usable_lifetime_cycles", "prepared_material_cost_usd_per_l"}
        valid = [r for r in sweeps if r.get("factors") == [.5, 1, 2] and
                 {s["parameter"] for s in r.get("sensitivity", [])} == keys and
                 all(len(s["rows"]) == 3 and all(row["status"] == "calculated" for row in s["rows"]) for s in r["sensitivity"])]
        checks.append(_check("requested_two_parameter_sweep_saved", len(sweeps) == len(valid) == 1,
                             "Exactly one saved sweep has the two requested keys and three calculated factors each."))
    elif case_id in {"wf_draft_only", "wf_accept_after_review"}:
        exps = final["experiments"]
        status = "draft" if case_id == "wf_draft_only" else "accepted"
        matching = [e for e in exps if e["candidate_id"] == "o-36" and e["label"] == EXPERIMENT_LABEL and
                    e["conditions"] == CONDITIONS and e["metrics"] == METRICS and e["status"] == status]
        checks.append(_check("exact_experiment_record_and_status", len(exps) == len(matching) == 1,
                             "Exactly one experiment retains supplied conditions/metrics and the authorized final status."))
        checks.append(_check("shared_assumptions_preserved", before["assumptions"] == after["assumptions"],
                             "Creating or accepting processed data does not edit shared scenario assumptions."))
        if case_id == "wf_accept_after_review":
            good = [r for r in calculations if r.get("candidate_id") == "o-36" and
                    r["assumptions"].get("collected_target_kg_per_l_cycle") == .001 and
                    r["assumptions"].get("cycle_time_hours") == 12 and
                    r["assumptions"].get("usable_lifetime_cycles") == before["assumptions"]["usable_lifetime_cycles"] and
                    _near(r["summary"].get("required_bed_volume_l"), 50)]
            checks.append(_check("accepted_measurements_used_without_invented_lifetime", len(good) == len(calculations) == 1,
                                 "Applicable output and cycle time imply 50 L; observed cycles do not overwrite assumed lifetime."))
    elif case_id == "wf_mismatched_conditions":
        ranks = [r for r in runs if r.get("kind") == "rank" and r.get("pool") == "updated"]
        good = [r for r in ranks if r.get("eligible_count") == 0 and any(e["candidate_id"] == "o-36" and
                any("pH" in reason for reason in e["reasons"]) for e in r.get("exclusions", []))]
        checks.append(_check("mismatched_candidate_excluded", len(ranks) == len(good) == 1,
                             "Updated ranking explicitly excludes o-36 because experimental pH mismatches project pH."))
        checks.append(_check("mismatched_measurements_not_used", len(calculations) == 1 and
                             calculations[0].get("candidate_id") == "o-36" and
                             calculations[0]["assumptions"]["collected_target_kg_per_l_cycle"] == before["assumptions"]["collected_target_kg_per_l_cycle"] and
                             calculations[0]["assumptions"]["cycle_time_hours"] == before["assumptions"]["cycle_time_hours"],
                             "The saved calculation retains scenario inputs instead of borrowing mismatched accepted data."))
    elif case_id == "wf_scale_prediction":
        preds = final["predictions"]
        good = [p for p in preds if p["label"] == "Synthetic 200 L scenario" and p["intended_bed_volume_l"] == 200 and
                p["supplied_values"] == prediction_values() and p["evidence_kind"] == "user_supplied_prediction"]
        checks.append(_check("explicit_prediction_preserved", len(preds) == len(good) == 1,
                             "One immutable prediction retains all supplied performance/cost values and intended volume."))
        results = [r for r in runs if r.get("kind") == "scale_prediction_calculation" and
                   r.get("prediction", {}).get("id") in {p["id"] for p in good} and
                   _near(r["summary"].get("required_bed_volume_l"), 200) and r.get("scale_check", {}).get("status") == "consistent"]
        checks.append(_check("prediction_calculated_with_independent_inventory", len(results) == 1,
                             "0.001 kg/L/cycle * 2 cycles/day gives 0.002 kg/L/day; 0.4/0.002 = 200 L."))
    elif case_id in {"wf_registered_method", "wf_build_method"}:
        custom = [r for r in runs if r.get("kind") == "custom_calculation"]
        if case_id == "wf_registered_method":
            good = [r for r in custom if r["method_id"] == context["method_id"] and
                    r["inputs"] == {"cost": 90, "output": .003, "cycles": 75} and _near(r["outputs"].get("usd_per_kg"), 400)]
            checks.append(_check("existing_registered_method_reused", len(custom) == len(good) == 1,
                                 "The original registered version is used with requested inputs; 90/(0.003*75) = 400 USD/kg."))
            checks.append(_check("method_registry_unchanged", initial["methods"] == final["methods"],
                                 "Research mode reuses the fixture method without creating or changing methods."))
        else:
            registered = [m for m in final["methods"] if m.get("status") == "registered" and m["id"].startswith("evaluation-total-cost@") and
                          m.get("checks", {}).get("passed") and len(m.get("checks", {}).get("cases", [])) >= 2]
            required_references = [({"annual_cost_usd": 1200, "annual_output_kg": 12}, 100),
                                   ({"annual_cost_usd": 3000, "annual_output_kg": 20}, 150)]
            registered = [m for m in registered if all(any(
                ref.get("inputs") == inputs and _near(ref.get("expected", {}).get("usd_per_kg"), expected)
                for ref in m.get("reference_cases", [])) for inputs, expected in required_references)]
            good = [r for r in custom if r["method_id"] in {m["id"] for m in registered} and
                    r["inputs"] == {"annual_cost_usd": 2400, "annual_output_kg": 8} and _near(r["outputs"].get("usd_per_kg"), 300)]
            checks.append(_check("checked_method_registered_and_used", bool(registered) and len(custom) == len(good) == 1,
                                 "A registered method with at least two passing reference checks saves 2400/8 = 300 USD/kg."))
            used = [m for m in registered if m["id"] in {r["method_id"] for r in good}]
            checks.append(_check("saved_method_passes_independent_behavior_probes", bool(used) and all(_method_behavior(m) for m in used),
                                 "Saved source computes held-out 1000/4=250 and 0/3=0, and refuses negative cost or nonpositive output."))
    elif case_id == "wf_clarify_export":
        batches = final["batches"]
        good = [b for b in batches if b.get("selection_id") == context["selection_id"] and
                b["candidate_ids"] == context["candidate_ids"] and b["count"] == 2 and
                b.get("generation", {}).get("minimum") == 50 and b.get("generation", {}).get("maximum") == 80 and
                b.get("generation", {}).get("seed") == 11]
        checks.append(_check("clarified_export_preserves_selection", len(batches) == len(good) == 1,
                             "Exactly one batch preserves selection order and the second-turn volume bounds/seed."))
        checks.append(_check("no_reranking_or_reselection", final["runs"] == initial["runs"] and final["selections"] == initial["selections"],
                             "Original ranking and selection survive unchanged across the two turns."))
    else:
        raise ValueError("Unknown expanded workflow case: " + case_id)
    return {"scope": "Persisted software facts only; answer correctness and scientific validity require separate review.", "checks": checks}
