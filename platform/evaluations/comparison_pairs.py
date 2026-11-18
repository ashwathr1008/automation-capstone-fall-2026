"""Descriptive matched workflow/repetition transitions; no independence claims."""
from __future__ import annotations
from collections import Counter
import math

PAIR_SPECS = [
    ("training_4b_off", "training", "4B", "off", "qwen-local", "qwen-4b-trained"),
    ("training_4b_on", "training", "4B", "on", "qwen-4b-thinking", "qwen-4b-trained-thinking"),
    ("training_9b_off", "training", "9B", "off", "qwen-9b-local", "qwen-9b-trained"),
    ("training_9b_on", "training", "9B", "on", "qwen-9b-thinking", "qwen-9b-trained-thinking"),
    ("thinking_4b_base", "thinking", "4B", "base", "qwen-local", "qwen-4b-thinking"),
    ("thinking_4b_trained", "thinking", "4B", "trained", "qwen-4b-trained", "qwen-4b-trained-thinking"),
    ("thinking_9b_base", "thinking", "9B", "base", "qwen-9b-local", "qwen-9b-thinking"),
    ("thinking_9b_trained", "thinking", "9B", "trained", "qwen-9b-trained", "qwen-9b-trained-thinking"),
]


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def _aggregate(rows):
    matched = [row for row in rows if row["transition"] != "missing"]
    before, after = sum(row["before_passed"] for row in matched), sum(row["after_passed"] for row in matched)
    return {"matched_attempt_pairs": len(matched), "missing_pairs": len(rows) - len(matched),
            "before_passed": before, "after_passed": after, "net_pass_change": after - before,
            "pass_rate_difference_percentage_points": 100 * (after - before) / len(matched) if matched else None,
            "transition_counts": dict(sorted(Counter(row["transition"] for row in rows).items())),
            "before_tool_calls": sum(row["before_tool_calls"] for row in matched),
            "after_tool_calls": sum(row["after_tool_calls"] for row in matched),
            "before_tool_failures": sum(row["before_tool_failures"] for row in matched),
            "after_tool_failures": sum(row["after_tool_failures"] for row in matched)}


def _evidence(row):
    if not row:
        return None
    return row.get("evidence_origin") or {"source_report": row.get("source_report"), "source_result_index": row.get("source_result_index")}


def paired_comparisons(summary, specs=PAIR_SPECS):
    index = {}
    for row in summary.get("case_results", []):
        key = (row["profile_id"], row["id"], row["repetition"])
        if key in index:
            raise ValueError(f"Duplicate attempt in paired comparison: {key}")
        index[key] = row
    all_pairs, task_rows, contrasts = [], [], []
    for identifier, kind, size, fixed_condition, before_id, after_id in specs:
        metadata = {"contrast_id": identifier, "factor_changed": kind, "size": size,
                    "fixed_condition": fixed_condition, "before_profile_id": before_id, "after_profile_id": after_id}
        task_repeats = sorted({(case, rep) for profile, case, rep in index if profile in {before_id, after_id}})
        rows = []
        for case, repetition in task_repeats:
            before, after = index.get((before_id, case, repetition)), index.get((after_id, case, repetition))
            bp, ap = before.get("objective_task_passed") if before else None, after.get("objective_task_passed") if after else None
            if not isinstance(bp, bool) or not isinstance(ap, bool):
                transition = "missing"
            else:
                transition = "both_pass" if bp and ap else "improved" if ap else "regressed" if bp else "both_fail"
            timed = bool(before and after and before.get("status") == after.get("status") == "completed"
                         and _finite(before.get("elapsed_seconds")) and _finite(after.get("elapsed_seconds")))
            row = {**metadata, "case_id": case, "repetition": repetition, "transition": transition,
                   "before_passed": bp, "after_passed": ap,
                   "before_status": before.get("status") if before else None, "after_status": after.get("status") if after else None,
                   "before_tool_calls": before.get("tool_calls", 0) if before else None,
                   "after_tool_calls": after.get("tool_calls", 0) if after else None,
                   "before_tool_failures": before.get("tool_failures", 0) if before else None,
                   "after_tool_failures": after.get("tool_failures", 0) if after else None,
                   "both_completed_with_timing": timed,
                   "elapsed_seconds_change": after["elapsed_seconds"] - before["elapsed_seconds"] if timed else None,
                   "before_evidence": _evidence(before), "after_evidence": _evidence(after)}
            rows.append(row)
        all_pairs.extend(rows)
        for case in sorted({row["case_id"] for row in rows}):
            task_rows.append({**metadata, "case_id": case, **_aggregate([row for row in rows if row["case_id"] == case])})
        contrasts.append({**metadata, **_aggregate(rows)})
    return {"schema_version": "1.0", "contrasts": contrasts, "per_task": task_rows, "attempt_pairs": all_pairs,
            "interpretation": [
                "Pairs match workflow ID and repetition label; projects are fresh. This is descriptive matching, not randomized independent replication.",
                "There are 16 workflow templates with 3 repeated attempts per configuration. Models and repeats do not multiply distinct tasks.",
                "No confidence interval, significance test, or general scientific-accuracy score is inferred.",
                "Read tool-call totals and failures with task completion; fewer calls can also mean an early stop.",
                "Elapsed changes require both matched attempts to complete and both timings to be recorded.",
            ]}
