"""Export descriptive benchmark figures as PNG, SVG, and plotted-data JSON.

Input is summarize_comparison.py's JSON. Unknown or missing runs stay missing;
no scientific accuracy, confidence interval, or unobserved result is inferred.
Matplotlib is needed only for this optional artifact export.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import statistics

WORKSPACE = Path(__file__).resolve().parents[2]
MODEL_ORDER = ("qwen-local", "qwen-9b-local", "claude-sonnet", "claude-opus", "codex-default", "codex-astra")
MODEL_LABELS = {"qwen-local": "Qwen 4B", "qwen-9b-local": "Qwen 9B", "claude-sonnet": "Sonnet 5.5",
                "claude-opus": "Opus 5.5", "codex-default": "GPT-6.1 Sol", "codex-astra": "GPT-6 Astra"}
CASE_LABELS = {
    "tool_economics": "Save an economic calculation",
    "tool_hypothetical": "Keep a ranking hypothetical",
    "tool_exact_selection": "Preserve exact export selection",
    "tool_missing_bound": "Wait for a missing export bound",
    "wf_evidence_extract": "Extract archived evidence fields",
    "wf_source_conflict": "Preserve conflicting evidence",
    "wf_assumption_revision": "Revise assumptions across turns",
    "wf_candidate_override": "Keep candidate assumptions separate",
    "wf_sensitivity": "Run a two-parameter sensitivity",
    "wf_draft_only": "Save an unaccepted experiment draft",
    "wf_accept_after_review": "Wait for explicit experiment acceptance",
    "wf_mismatched_conditions": "Respect mismatched conditions",
    "wf_scale_prediction": "Calculate a supplied scale scenario",
    "wf_registered_method": "Discover and reuse a registered method",
    "wf_build_method": "Build, check, register, and use a method",
    "wf_build_method_clarified": "Build a method with explicit validation",
    "wf_clarify_export": "Continue an export after clarification",
}
COLORS = {"ink": "#142D40", "muted": "#586B79", "grid": "#E3E9ED", "clean": "#197C78",
          "recovered": "#D99B35", "failed": "#BC5258", "missing": "#EDF0F2"}
MODEL_COLORS = ("#39719A", "#5B89AA", "#725C94", "#9580B5", "#197C78", "#3B9994")


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def model_order(summary):
    existing = set(summary.get("model_summary", {})) | set(summary.get("profiles", {}))
    if summary.get("configuration_order"):
        declared = list(summary["configuration_order"])
        return declared + sorted(existing - set(declared))
    return list(MODEL_ORDER) + sorted(existing - set(MODEL_ORDER))


def model_label(profile_id, summary):
    return (summary.get("configurations", {}).get(profile_id, {}).get("display_name")
            or MODEL_LABELS.get(profile_id) or summary.get("profiles", {}).get(profile_id, {}).get("name") or profile_id)


def configuration_details(profile_id, summary):
    declared = summary.get("configurations", {}).get(profile_id, {})
    label = model_label(profile_id, summary)
    training, thinking = declared.get("training"), declared.get("thinking")
    if training in {"base", "trained", "planned"} and thinking in {"on", "off"}:
        short_label = ("Trained*" if training == "planned" else training.title()) + "\nThink " + thinking
    else:
        short_label = label.replace(" ", "\n", 1)
    return {"profile_id": profile_id, **declared, "label": label,
            "axis_label": label, "short_label": short_label, "group": declared.get("group", "")}


def objective_rows(summary):
    return [row for row in summary.get("case_results", [])
            if row.get("category") == "objective_tool_contract" or row.get("objective_task_passed") is not None]


def plotted_data(summary, expected_repeats=3, failure_limit=10):
    """Derive plot values strictly from observed records; no plotting imports."""
    if isinstance(expected_repeats, bool) or not isinstance(expected_repeats, int) or expected_repeats < 1:
        raise ValueError("expected_repeats must be a positive integer")
    order, rows = model_order(summary), objective_rows(summary)
    if not rows:
        raise ValueError("The summary contains no attempted objective workflows to plot")
    if len(rows) != len(summary.get("case_results", [])):
        raise ValueError("Use an objective-workflow-only summary so task and tool figures have the same evaluation scope")
    observed = {row["id"] for row in rows} | set(summary.get("planned_case_ids", []))
    cases = [key for key in CASE_LABELS if key in observed] + sorted(observed - set(CASE_LABELS))
    configurations = [configuration_details(profile_id, summary) for profile_id in order]
    outcomes, latency, matrix = [], [], []
    for profile_id in order:
        attempts = [row for row in rows if row["profile_id"] == profile_id]
        successful = [row for row in attempts if row.get("objective_task_passed") is True]
        recovered = sum(row.get("tool_failures", 0) > 0 for row in successful)
        outcomes.append({"profile_id": profile_id, "label": model_label(profile_id, summary),
                         "attempted": len(attempts), "successful": len(successful),
                         "clean_success": len(successful) - recovered, "recovered_success": recovered,
                         "failed": len(attempts) - len(successful),
                         "success_rate": len(successful) / len(attempts) if attempts else None,
                         "not_attempted": summary.get("model_summary", {}).get(profile_id, {}).get("not_attempted_count", 0)})
        completed = [row for row in attempts if row.get("status") == "completed"]
        times = [row["elapsed_seconds"] for row in completed if _number(row.get("elapsed_seconds"))]
        latency.append({"profile_id": profile_id, "label": model_label(profile_id, summary),
                        "attempted": len(attempts), "completed": len(completed), "timed_completed": len(times),
                        "median_seconds": statistics.median(times) if times else None,
                        "completed_case_seconds": times, "excluded_noncompleted": len(attempts) - len(completed),
                        "completed_missing_time": len(completed) - len(times)})
    for case_id in cases:
        cells = []
        for profile_id in order:
            attempts = [row for row in rows if row["profile_id"] == profile_id and row["id"] == case_id]
            if len(attempts) > expected_repeats:
                raise ValueError(f"{profile_id}/{case_id} has {len(attempts)} attempts, exceeding the stated {expected_repeats} repeats")
            cells.append({"profile_id": profile_id, "passed": sum(row.get("objective_task_passed") is True for row in attempts),
                          "attempted": len(attempts), "missing_from_planned_repeats": expected_repeats - len(attempts)})
        matrix.append({"case_id": case_id, "label": CASE_LABELS.get(case_id, case_id.replace("_", " ")), "models": cells})
    failures = [dict(row, label=model_label(row["profile_id"], summary)) for row in summary.get("tool_summary", []) if row.get("failed", 0) > 0]
    failures.sort(key=lambda row: (-row["failed"], order.index(row["profile_id"]) if row["profile_id"] in order else len(order), row["tool"]))
    return {"model_order": order, "configurations": configurations, "case_ids": cases, "expected_repeats": expected_repeats,
            "analysis_corrections": summary.get("analysis_corrections", []),
            "objective_attempts_observed": len(rows), "outcomes": outcomes, "task_matrix": matrix, "latency": latency,
            "tool_failure_rows": failures[:failure_limit], "all_tool_failure_rows": failures,
            "failure_rows_shown": min(failure_limit, len(failures)), "failure_rows_total": len(failures),
            "all_tool_calls": sum(row.get("calls", 0) for row in summary.get("tool_summary", [])),
            "tool_calls_unknown": sum(row.get("unknown", 0) for row in summary.get("tool_summary", [])),
            "status_counts": dict(sorted(Counter(row.get("status", "unknown") for row in rows).items())),
            "summary_warnings": summary.get("warnings", [])}


def _style():
    import matplotlib
    matplotlib.use("Agg")
    matplotlib.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 11, "axes.labelcolor": COLORS["ink"],
        "text.color": COLORS["ink"], "xtick.color": COLORS["muted"], "ytick.color": COLORS["ink"],
        "axes.edgecolor": COLORS["grid"], "axes.titleweight": "bold", "figure.facecolor": "white",
        "axes.facecolor": "white", "savefig.facecolor": "white", "svg.fonttype": "none",
        "pdf.fonttype": 42, "axes.spines.top": False, "axes.spines.right": False,
    })


def _figure(title, subtitle, footer):
    import matplotlib.pyplot as plt
    figure = plt.figure(figsize=(13.333, 7.5))
    figure.text(0.055, 0.945, title, size=25, weight="bold", va="top")
    figure.text(0.055, 0.885, subtitle, size=12, color=COLORS["muted"], va="top")
    figure.text(0.055, 0.04, footer, size=9.5, color=COLORS["muted"], va="bottom", linespacing=1.45)
    return figure


def _subtitle(data):
    label = "Clarified-task automated checks" if data.get("analysis_corrections") else "Strict automated checks"
    return (f"{label} · {len(data['case_ids'])} workflows · {len(data['model_order'])} configurations · "
            f"{data['expected_repeats']} repeats/task · {data['objective_attempts_observed']} observed attempts")


def _group_boundaries(data):
    configurations = data["configurations"]
    return [index - .5 for index in range(1, len(configurations))
            if configurations[index]["group"] != configurations[index - 1]["group"]]


def outcome_figure(data):
    from matplotlib.patches import Patch
    footer = ("Success = completed task with every recorded objective check passed. Clean = no recorded tool failures; recovered = at least one.\n"
              "Failures include unmet checks, execution errors, and timeouts. These are workflow outcomes, not scientific-answer accuracy.")
    fig = _figure("Which workflows did each configuration complete?", _subtitle(data), footer)
    expanded = len(data["outcomes"]) > 6
    ax = fig.add_axes([0.30, 0.17, 0.58, 0.61] if expanded else [0.19, 0.17, 0.69, 0.61])
    maximum = max((row["attempted"] for row in data["outcomes"]), default=1) or 1
    for index, row in enumerate(data["outcomes"]):
        left = 0
        for key, color in (("clean_success", COLORS["clean"]), ("recovered_success", COLORS["recovered"]), ("failed", COLORS["failed"])):
            value = row[key]
            if value:
                ax.barh(index, value, left=left, height=0.58, color=color, edgecolor="white", linewidth=1.1)
                if value >= max(2, maximum * .05):
                    ax.text(left + value / 2, index, str(value), ha="center", va="center", size=12, weight="bold",
                            color="white" if key != "recovered_success" else COLORS["ink"])
                left += value
        text = f"{row['successful']}/{row['attempted']}  ({row['success_rate']:.0%})" if row["attempted"] else "No report included"
        ax.text(maximum * 1.025, index, text, va="center", size=11.5, weight="bold" if row["attempted"] else "normal",
                color=COLORS["ink"] if row["attempted"] else COLORS["muted"])
    ax.set_yticks(range(len(data["outcomes"])), [row["axis_label"] for row in data["configurations"]], fontsize=9.8 if expanded else 12)
    for boundary in _group_boundaries(data):
        ax.axhline(boundary, color=COLORS["grid"], linewidth=.9)
    ax.set_xlim(0, maximum * 1.25)
    ax.set_ylim(len(data["outcomes"]) - .5, -.5)
    ax.set_xlabel("Observed task attempts", labelpad=10)
    ax.set_axisbelow(True)
    ax.grid(axis="x", color=COLORS["grid"], linewidth=.7)
    ax.spines["left"].set_visible(False)
    ax.tick_params(axis="y", length=0, pad=10)
    ax.legend(handles=[Patch(facecolor=COLORS[key], label=label) for key, label in
                       (("clean", "Clean success"), ("recovered", "Recovered success"), ("failed", "Failed task"))],
              loc="lower left", bbox_to_anchor=(-.01, 1.015), ncol=3, frameon=False, fontsize=11)
    return fig


def matrix_figure(data):
    import numpy as np
    from matplotlib.colors import LinearSegmentedColormap
    footer = ("Cell = successful completions / observed attempts. Color shows successful completions; grey means no observed run.\n"
              "Checks evaluate state/artifact contracts, not scientific-answer accuracy.")
    if any(row.get("training") == "planned" for row in data["configurations"]):
        footer += " * Trained configuration planned; no checkpoint evaluated yet."
    fig = _figure("Where did the models succeed or fail?", _subtitle(data), footer)
    expanded = len(data["model_order"]) > 6
    ax = fig.add_axes([0.335, 0.18, 0.62, 0.57] if expanded else [0.335, 0.18, 0.59, 0.62])
    values = np.array([[cell["passed"] if cell["attempted"] else np.nan for cell in row["models"]] for row in data["task_matrix"]])
    cmap = LinearSegmentedColormap.from_list("workflow_completion", ["#F0D0D2", "#F1E4BA", "#B2D7CC", "#247F78"])
    cmap.set_bad(COLORS["missing"])
    ax.imshow(values, cmap=cmap, vmin=0, vmax=data["expected_repeats"], aspect="auto", interpolation="nearest")
    for r, row in enumerate(data["task_matrix"]):
        for c, cell in enumerate(row["models"]):
            text = f"{cell['passed']}/{cell['attempted']}" if cell["attempted"] else "—"
            ax.text(c, r, text, ha="center", va="center", fontsize=9.5 if expanded else 10.5, weight="bold",
                    color="white" if cell["passed"] >= data["expected_repeats"] * .8 else COLORS["ink"])
    labels = [row["short_label"] if expanded else row["label"].replace(" ", "\n", 1) for row in data["configurations"]]
    ax.set_xticks(range(len(labels)), labels, fontsize=8.7 if expanded else 10.5)
    ax.xaxis.tick_top()
    ax.tick_params(axis="x", length=0, pad=10)
    ax.set_yticks(range(len(data["task_matrix"])), [row["label"] for row in data["task_matrix"]], fontsize=10.4)
    ax.tick_params(axis="y", length=0, pad=10)
    ax.set_xticks(np.arange(-.5, len(labels), 1), minor=True)
    ax.set_yticks(np.arange(-.5, len(values), 1), minor=True)
    ax.grid(which="minor", color="white", linewidth=1.5)
    ax.tick_params(which="minor", length=0)
    if expanded:
        start = 0
        for stop in range(1, len(labels) + 1):
            if stop == len(labels) or data["configurations"][stop]["group"] != data["configurations"][start]["group"]:
                group = data["configurations"][start]["group"]
                if group:
                    ax.text((start + stop) / (2 * len(labels)), 1.145, group, transform=ax.transAxes,
                            ha="center", va="bottom", size=11, weight="bold")
                start = stop
        for boundary in _group_boundaries(data):
            ax.axvline(boundary, color="white", linewidth=4)
    for spine in ax.spines.values():
        spine.set_visible(False)
    return fig


def latency_figure(data):
    footer = ("Median of completed cases only, including fixture setup and runtime startup/teardown. Completed can still fail an objective check.\n"
              "Task complexity, provider scaffolds, hardware, caching, and request timing differ. No confidence intervals or speed significance are implied.")
    fig = _figure("How long did completed workflows take?", "Descriptive median elapsed time · completed / attempted cases shown beside each model", footer)
    expanded = len(data["latency"]) > 6
    ax = fig.add_axes([0.30, 0.17, 0.58, 0.64] if expanded else [0.19, 0.17, 0.69, 0.64])
    maximum = max((row["median_seconds"] for row in data["latency"] if row["median_seconds"] is not None), default=1) or 1
    for index, row in enumerate(data["latency"]):
        median = row["median_seconds"]
        if median is not None:
            ax.barh(index, median, height=.54, color=MODEL_COLORS[index % len(MODEL_COLORS)], zorder=3)
            text = f"{median:.1f} s"
        else:
            text = "No completed timing" if row["attempted"] else "No report included"
        ax.text((median or 0) + maximum * .025, index, text, va="center", size=11 if median is None else 12,
                weight="normal" if median is None else "bold", color=COLORS["muted"] if median is None else COLORS["ink"])
        if row["attempted"]:
            ax.text(maximum * 1.36, index, f"{row['completed']}/{row['attempted']} completed", va="center", size=11, color=COLORS["muted"])
    ax.set_yticks(range(len(data["latency"])), [row["axis_label"] for row in data["configurations"]], fontsize=9.8 if expanded else 12)
    for boundary in _group_boundaries(data):
        ax.axhline(boundary, color=COLORS["grid"], linewidth=.9)
    ax.set_xlim(0, maximum * 1.67)
    ax.set_ylim(len(data["latency"]) - .5, -.5)
    ax.set_xlabel("Median elapsed seconds per completed case", labelpad=10)
    ax.set_axisbelow(True)
    ax.grid(axis="x", color=COLORS["grid"], linewidth=.7)
    ax.spines["left"].set_visible(False)
    ax.tick_params(axis="y", length=0, pad=10)
    return fig


def failure_figure(data):
    displayed, total = data["failure_rows_shown"], data["failure_rows_total"]
    subtitle = (f"Top {displayed} of {total} model–tool pairs with failures · denominator = all observed calls to that tool"
                if total else f"{data['all_tool_calls']} observed platform-tool calls · no explicit tool failures recorded")
    footer = ("A tool failure is an explicit rejected/error outcome; some tasks recover. Affected attempts count model/task/repetition combinations.\n"
              f"Distinct tasks count workflow types. Unknown tool outcomes: {data['tool_calls_unknown']}. All error messages and counts are retained in the summary.")
    fig = _figure("Which tool calls failed repeatedly?", subtitle, footer)
    ax = fig.add_axes([0.405, 0.17, 0.27, 0.62])
    rows = data["tool_failure_rows"]
    if not rows:
        ax.set_axis_off()
        fig.text(.5, .52, "No explicit tool failures recorded", ha="center", va="center", fontsize=23, color=COLORS["clean"])
        return fig
    maximum = max(row["failed"] for row in rows) or 1
    ax.set_xlim(0, maximum * 1.15)
    ax.set_ylim(len(rows) - .65, -.65)
    ax.set_yticks([])
    ax.grid(axis="x", color=COLORS["grid"], linewidth=.7)
    ax.set_axisbelow(True)
    ax.set_xlabel("Failed tool calls", labelpad=10)
    ax.spines["left"].set_visible(False)
    for index, row in enumerate(rows):
        color_index = data["model_order"].index(row["profile_id"])
        ax.barh(index, row["failed"], height=.56, color=MODEL_COLORS[color_index % len(MODEL_COLORS)])
        ax.text(row["failed"] + maximum * .025, index, str(row["failed"]), va="center", weight="bold", fontsize=11)
        transform = ax.get_yaxis_transform()
        ax.text(-.085, index, row["label"] + "\n" + row["tool"], transform=transform,
                ha="right", va="center", fontsize=10.2, linespacing=1.25, clip_on=False)
        task_word = "task type" if row["distinct_cases_with_failure"] == 1 else "task types"
        attempt_word = "attempt" if row["attempts_with_failure"] == 1 else "attempts"
        note = (f"{row['failed']}/{row['calls']} calls\n"
                f"{row['attempts_with_failure']} {attempt_word} · {row['distinct_cases_with_failure']} {task_word}")
        ax.text(1.10, index, note, transform=transform, va="center", fontsize=10.3, color=COLORS["muted"], linespacing=1.3, clip_on=False)
    return fig


def save_figure(fig, output_dir, stem, data, provenance, dpi):
    import matplotlib.pyplot as plt
    png, svg, raw = (output_dir / (stem + extension) for extension in (".png", ".svg", ".data.json"))
    fig.savefig(png, dpi=dpi)
    fig.savefig(svg)
    raw.write_text(json.dumps({"provenance": provenance, "plotted_data": data}, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    plt.close(fig)
    return {"png": str(png), "svg": str(svg), "data": str(raw)}


def export_figures(summary, output_dir, *, summary_path=None, expected_repeats=3, dpi=240, allow_partial=False):
    running = [source.get("path") for source in summary.get("source_reports", []) if source.get("status") != "run_finished"]
    if running and not allow_partial:
        raise ValueError("Input includes unfinished reports; use --allow-partial only for an explicitly provisional export")
    data = plotted_data(summary, expected_repeats)
    incomplete = [row["profile_id"] for row in data["outcomes"]
                  if row["attempted"] < len(data["case_ids"]) * expected_repeats]
    if incomplete and not allow_partial:
        raise ValueError("Configuration coverage is incomplete; use --allow-partial for a provisional export")
    _style()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    provenance = {"created_at": datetime.now(timezone.utc).isoformat(), "summary_path": str(summary_path) if summary_path else None,
                  "summary_sha256": hashlib.sha256(Path(summary_path).read_bytes()).hexdigest() if summary_path else None,
                  "source_reports": summary.get("source_reports", []), "provisional": bool(running or incomplete),
                  "incomplete_configurations": incomplete,
                  "configurations": data["configurations"], "configuration_manifest": summary.get("configuration_manifest"),
                  "analysis_corrections": data["analysis_corrections"],
                  "summary_warnings": summary.get("warnings", []),
                  "scope": "Observed synthetic workflow contracts; no scientific-answer accuracy score or inferred measurements.",
                  "planned_repeats": expected_repeats, "png_dpi": dpi}
    figures = [
        ("01-task-completion", outcome_figure, {key: data[key] for key in ("outcomes", "status_counts", "objective_attempts_observed")}),
        ("02-task-model-matrix", matrix_figure, {key: data[key] for key in ("model_order", "configurations", "task_matrix", "expected_repeats")}),
        ("03-completed-case-latency", latency_figure, {"latency": data["latency"]}),
        ("04-recurring-tool-failures", failure_figure, {key: data[key] for key in ("tool_failure_rows", "all_tool_failure_rows", "failure_rows_shown", "failure_rows_total", "all_tool_calls", "tool_calls_unknown")}),
    ]
    outputs = {}
    for stem, builder, payload in figures:
        fig = builder(data)
        if running or incomplete:
            fig.text(.945, .975, "PROVISIONAL", ha="right", va="top", size=10, weight="bold", color=COLORS["failed"])
        outputs[stem] = save_figure(fig, output_dir, stem, payload, provenance, dpi)
    manifest = {"provenance": provenance, "figures": outputs, "models": data["outcomes"], "observed_workflow_types": data["case_ids"]}
    (output_dir / "figure-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("summary", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected-repeats", type=int, default=3)
    parser.add_argument("--dpi", type=int, default=240)
    parser.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args(argv)
    output_dir = args.output_dir.expanduser().resolve()
    if not output_dir.is_relative_to(WORKSPACE) or output_dir.is_relative_to(WORKSPACE / "platform"):
        parser.error("Figure output must be inside this workspace and outside platform/")
    if not 72 <= args.dpi <= 600:
        parser.error("--dpi must be between 72 and 600")
    summary_path = args.summary.expanduser().resolve()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    try:
        result = export_figures(summary, output_dir, summary_path=summary_path, expected_repeats=args.expected_repeats,
                                dpi=args.dpi, allow_partial=args.allow_partial)
    except ValueError as exc:
        parser.error(str(exc))
    print(f"Exported {len(result['figures'])} figures as SVG, PNG, and plotted-data JSON to {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
