#!/usr/bin/env python3
"""Export PNG/SVG figures from validated aggregate_throughput summary JSON.

Example: .venv/bin/python plot_throughput.py dev/summary.json eval/summary.json
    --selection runs/throughput-followup-v1-selection.json --output figures
Reads summaries only; never opens raw traces, contacts endpoints, or selects arms.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.ticker import PercentFormatter


ARMS = {
    "direct_thinking_8k": "Single full plan (8K)",
    "solo_refine_thinking_8k": "Sequential refinement (4 plans)",
    "ensemble2_thinking_8k": "Two full plans",
    "ensemble4_thinking_8k": "Four full plans",
    "cascade32": "Cascade: 32 paths + plan",
    "independent32": "Independent: 32 paths",
    "independent100": "Independent: 100 paths",
    "democracy32": "Democracy: 32 agents",
    "shared8": "Shared frontier: 8 agents",
}
ORIGINAL = tuple(ARMS)[:5]
COLORS = dict(zip(ARMS, ("#0072B2", "#56A5CC", "#009E73", "#4E806B", "#7355A1", "#D55E00", "#BB8321", "#AA5290", "#657F22")))
NOTE = "Queue rates use actual four-node batch wall, including final drain; no rate confidence intervals."
DISCLOSURE = "The four cheap-policy arms are a later exploratory extension, designed after primary seed 1 inspection."


def check(condition, message):
    if not condition:
        raise ValueError(message)


def number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def read_inputs(paths, selection_path):
    rows, synthetic = [], False
    for path in paths:
        data = json.loads(path.read_text())
        check(isinstance(data, dict) and isinstance(data.get("cohorts"), list), "Expected aggregate_throughput summary JSON")
        rows.extend(data["cohorts"]); synthetic |= data.get("synthetic") is True
    check(bool(rows), "No cohorts to plot")
    identities = [(row["split"], row["arm"], row["jobs_per_node"]) for row in rows]
    check(len(set(identities)) == len(rows), "Duplicate cohort identity")
    for row in rows:
        check(row["arm"] in ARMS and row["split"] in ("development", "evaluation"), "Unsupported arm/split")
        check(row["jobs_per_node"] in (1, 2, 4, 8) and number(row["successes_per_minute"]), "Invalid jobs or rate")
        check(type(row["attempts"]) is int and 0 <= row["verified_successes"] <= row["attempts"] and row["attempts"] > 0, "Invalid success count")
        check(number(row["batch_wall_seconds"]) and row["batch_wall_seconds"] > 0
              and math.isclose(row["successes_per_minute"], row["verified_successes"] * 60 / row["batch_wall_seconds"], rel_tol=1e-8), "Rate/wall mismatch")
        if row.get("server_cost_known") is True:
            check(all(number(row.get("server_" + field)) for field in ("prompt_tokens", "completion_tokens")), "Known cost lacks valid global counters")
    evaluation = [row for row in rows if row["split"] == "evaluation"]
    chosen = {}
    if selection_path:
        selection = json.loads(selection_path.read_text())
        check(selection.get("selection_split") == "development", "Admission selection must originate from development")
        chosen = {row["arm"]: row["jobs_per_node"] for row in selection["selections"]}
        check(len(chosen) == len(selection["selections"]), "Duplicate selected arm")
    if evaluation:
        check(bool(chosen), "Evaluation figures require --selection from development")
        check(len({row["arm"] for row in evaluation}) == len(evaluation), "More than one evaluation admission per arm")
        check(all(chosen.get(row["arm"]) == row["jobs_per_node"] for row in evaluation), "Evaluation admission differs from frozen development selection")
    return rows, chosen, synthetic


def decorate(fig, title, subtitle, synthetic, footer=NOTE):
    fig.suptitle(("SYNTHETIC · " if synthetic else "") + title, x=.02, y=.975, ha="left", fontsize=19, fontweight="bold")
    fig.text(.02, .917, subtitle, fontsize=11, color="#454D58")
    fig.text(.02, .047, footer, fontsize=9, color="#454D58")
    fig.text(.02, .018, DISCLOSURE, fontsize=9, color="#754716")


def scope(rows):
    counts = {(row["unique_tasks"], len(row["seeds"]), row["attempts"]) for row in rows}
    if len(counts) != 1:
        return "Different finite batch sizes; see source summaries"
    tasks, seeds, attempts = next(iter(counts))
    return f"{tasks} distinct tasks × {seeds} seeds = {attempts} attempts per cohort; seeds remain clustered by task"


def save(fig, directory, name):
    for suffix in ("png", "svg"):
        fig.savefig(directory / (name + "." + suffix), dpi=220, facecolor="white")
    plt.close(fig)


def development(rows, chosen, directory, synthetic):
    fig, axes = plt.subplots(1, 2, figsize=(14.5, 8))
    fig.subplots_adjust(left=.065, right=.98, bottom=.30, top=.82, wspace=.19)
    for ax, group, title in zip(axes, (ORIGINAL, tuple(ARMS)[5:]), ("Original throughput plan", "Later exploratory cheap-policy extension")):
        for arm in group:
            points = sorted((row for row in rows if row["arm"] == arm), key=lambda row: row["jobs_per_node"])
            if not points:
                continue
            ax.plot([row["jobs_per_node"] for row in points], [row["successes_per_minute"] for row in points],
                    marker="o", linewidth=2.1, color=COLORS[arm], label=ARMS[arm], linestyle="-" if arm in ORIGINAL else "--")
            selected = next((row for row in points if chosen.get(arm) == row["jobs_per_node"]), None)
            if selected:
                ax.scatter(selected["jobs_per_node"], selected["successes_per_minute"], s=170, marker="*", color=COLORS[arm], edgecolor="white", linewidth=.7, zorder=5)
        ax.set(title=title, xlabel="Admitted task jobs per node", ylabel="Verified solutions / minute")
        ax.set_xscale("log", base=2); ax.set_xticks([1, 2, 4, 8], [1, 2, 4, 8]); ax.set_ylim(bottom=0)
        ax.grid(axis="y", alpha=.2); ax.legend(loc="upper left", bbox_to_anchor=(0, -.18), ncol=2, fontsize=9, frameon=False)
    # Use a common scale: neither panel independently magnifies small changes.
    maximum = max(ax.get_ylim()[1] for ax in axes)
    for ax in axes:
        ax.set_ylim(0, maximum)
    decorate(fig, "Development: useful fleet throughput", scope(rows) + "; stars mark supplied development selections", synthetic)
    save(fig, directory, "development-throughput")


def eval_rows(rows):
    mapping = {row["arm"]: row for row in rows}
    return [mapping[arm] for arm in ARMS if arm in mapping]


def labels(rows):
    return [ARMS[row["arm"]] + f"  ·  j{row['jobs_per_node']}" for row in rows]


def row_style(ax, rows):
    ax.set_yticks(range(len(rows)), labels(rows), fontsize=10); ax.set_ylim(len(rows) - .5, -.5)
    ax.grid(axis="x", alpha=.2); ax.set_axisbelow(True)
    boundary = sum(row["arm"] in ORIGINAL for row in rows) - .5
    if 0 < boundary < len(rows) - 1:
        ax.axhline(boundary, color="#A4ABB4", linestyle=":", linewidth=1)


def evaluation(rows, directory, synthetic):
    rows = eval_rows(rows)
    fig, axes = plt.subplots(1, 2, figsize=(14.5, 8), sharey=True)
    fig.subplots_adjust(left=.25, right=.96, bottom=.17, top=.80, wspace=.16)
    for index, row in enumerate(rows):
        color = COLORS[row["arm"]]
        axes[0].barh(index, row["successes_per_minute"], color=color, height=.65,
                     hatch=None if row["arm"] in ORIGINAL else "//", edgecolor="white")
        axes[0].annotate(f"{row['successes_per_minute']:.2f}", (row["successes_per_minute"], index), xytext=(5, 0), textcoords="offset points", va="center", fontsize=10)
        fraction = row["verified_successes"] / row["attempts"]
        interval = row.get("task_cluster_success_fraction_ci95")
        if interval is not None:
            low, high = interval
            check(0 <= low <= fraction <= high <= 1, "Invalid task-cluster success interval")
            axes[1].errorbar(fraction, index, xerr=[[fraction - low], [high - fraction]], fmt="o", color=color, capsize=4, markersize=7, linewidth=1.8)
        else:
            axes[1].plot(fraction, index, "o", color=color, markersize=7)
        axes[1].text(1.04, index, f"{row['verified_successes']}/{row['attempts']}", va="center", fontsize=9)
    for ax in axes:
        row_style(ax, rows)
    axes[1].tick_params(labelleft=False)
    axes[0].set_xlabel("Verified solutions / minute · no rate CI")
    axes[0].set_xlim(0, max(row["successes_per_minute"] for row in rows) * 1.20 or 1)
    axes[1].set_xlim(0, 1.18); axes[1].set_xticks([0, .25, .5, .75, 1]); axes[1].xaxis.set_major_formatter(PercentFormatter(1))
    axes[1].set_xlabel("Success fraction · 95% task-cluster bootstrap")
    fig.legend(handles=[Patch(facecolor="#647182", label="Original plan"), Patch(facecolor="#647182", hatch="//", edgecolor="white", label="Later exploratory extension")], loc="upper left", bbox_to_anchor=(.245, .875), ncol=2, frameon=False)
    decorate(fig, f"Evaluation: {len(rows)} selected policies", scope(rows) + "; admission fixed from development only", synthetic)
    save(fig, directory, "evaluation-throughput-success")


def latency(rows, directory, synthetic):
    rows = eval_rows(rows)
    fig, axes = plt.subplots(1, 3, figsize=(15.5, 8), sharey=True)
    fig.subplots_adjust(left=.24, right=.98, bottom=.17, top=.79, wspace=.13)
    for ax, field, title in zip(axes, ("queue_wait_seconds", "service_wall_seconds", "total_latency_seconds"),
                                ("Wait before admission", "Service after admission", "Finish since common queue start")):
        for index, row in enumerate(rows):
            values = row.get(field, {})
            median, p95 = values.get("median"), values.get("p95")
            if number(median) and number(p95):
                ax.plot([median, p95], [index, index], color=COLORS[row["arm"]], linewidth=2, alpha=.6)
                ax.scatter([median, p95], [index, index], color=COLORS[row["arm"]], marker="o", s=30)
                ax.scatter(p95, index, color=COLORS[row["arm"]], marker="D", s=38)
            else:
                ax.text(.05, index, "Unknown", transform=ax.get_yaxis_transform(), va="center", color="#6E737B")
        row_style(ax, rows); ax.set_title(title, fontsize=11); ax.set_xlabel("Seconds"); ax.set_xlim(left=0)
    for ax in axes[1:]:
        ax.tick_params(labelleft=False)
    fig.legend(handles=[Line2D([], [], marker="o", linestyle="none", color="#44505F", label="Median (p50)"),
                        Line2D([], [], marker="D", linestyle="none", color="#44505F", label="p95")],
               loc="upper left", bbox_to_anchor=(.24, .875), ncol=2, frameon=False)
    decorate(fig, "Evaluation: queueing and service latency", scope(rows), synthetic,
             footer="p50/p95 describe recorded cases, not confidence intervals. Service deadlines start after admission.")
    save(fig, directory, "evaluation-latency")


def cost(rows, directory, synthetic):
    rows = eval_rows(rows)
    known = sum(row.get("server_cost_known") is True for row in rows)
    fig, axes = plt.subplots(1, 2, figsize=(14.5, 8), sharey=True)
    fig.subplots_adjust(left=.25, right=.98, bottom=.17, top=.81, wspace=.13)
    for ax, field, title in zip(axes, ("server_prompt_tokens", "server_completion_tokens"), ("Global input tokens", "Global output tokens")):
        for index, row in enumerate(rows):
            if row.get("server_cost_known") is True:
                value = row[field] / 1_000_000
                ax.barh(index, value, height=.65, color=COLORS[row["arm"]], edgecolor="white", hatch=None if row["arm"] in ORIGINAL else "//")
            else:
                ax.text(.03, index, "Unknown · incomplete counter coverage", transform=ax.get_yaxis_transform(), va="center", fontsize=9, color="#6E737B")
        row_style(ax, rows); ax.set_title(title, fontsize=12); ax.set_xlabel("Millions of tokens over the entire batch"); ax.set_xlim(left=0)
    axes[1].tick_params(labelleft=False)
    decorate(fig, "Evaluation: global inference-token accounting", f"Complete four-node counter coverage: {known}/{len(rows)} cohorts. " + scope(rows), synthetic,
             footer="Unknown server costs are not zero or replaced with partial client counts. Tokens are not interchangeable GPU-cost units.")
    save(fig, directory, "evaluation-global-cost")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("summaries", nargs="+", type=Path)
    parser.add_argument("--selection", type=Path)
    parser.add_argument("--output", required=True, type=Path, help="New output directory; existing figures are never overwritten")
    parser.add_argument("--synthetic", action="store_true", help="Label every figure SYNTHETIC for fixture QA")
    args = parser.parse_args(argv)
    rows, chosen, synthetic = read_inputs(args.summaries, args.selection)
    synthetic |= args.synthetic
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11, "axes.spines.top": False,
                         "axes.spines.right": False, "svg.fonttype": "none"})
    args.output.mkdir(parents=True, exist_ok=False)
    dev, held = [[row for row in rows if row["split"] == split] for split in ("development", "evaluation")]
    if dev:
        development(dev, chosen, args.output, synthetic)
    if held:
        evaluation(held, args.output, synthetic); latency(held, args.output, synthetic); cost(held, args.output, synthetic)
    inputs = args.summaries + ([args.selection] if args.selection else [])
    manifest = dict(synthetic=synthetic, inputs=[dict(name=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest()) for path in inputs],
                    script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    matplotlib_version=matplotlib.__version__, scope=NOTE, disclosure=DISCLOSURE,
                    figures={path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(args.output.iterdir())})
    (args.output / "figure-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(dict(output=str(args.output), synthetic=synthetic, figures=len(manifest["figures"]))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
