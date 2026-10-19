"""Plot measured CSV values only; never load the dataset or run a miner."""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
COLOURS = ("#0072B2", "#D55E00")
BASELINE = "Exact FP-growth (PAMI, re-mined every batch)"


def finish(fig, axis, target, legend_location="upper center"):
    axis.set_xlabel("Minimum support (minSup)")
    axis.ticklabel_format(axis="x", style="plain", useOffset=False)
    axis.grid(alpha=0.25)
    axis.legend(loc=legend_location, fontsize=8)
    fig.tight_layout()
    fig.savefig(target, dpi=200)
    plt.close(fig)
    print(f"Wrote {target.relative_to(ROOT) if target.is_relative_to(ROOT) else target}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=ROOT / "benchmarks/results")
    parser.add_argument("--images", type=Path, default=ROOT / "images")
    args = parser.parse_args()
    with (args.results / "summary.csv").open(newline="", encoding="utf-8") as source:
        rows = list(csv.DictReader(source))
    if len(rows) != 20 or any(int(row["repetitions"]) != 3 for row in rows):
        raise ValueError("Plots require the complete five-minSup, three-repetition results")
    args.images.mkdir(parents=True, exist_ok=True)
    metrics = (("patterns", "Number of patterns"), ("runtime_s", "Runtime (s)"),
               ("peak_memory_mb", "Peak memory (MB)"))
    for algorithm, stem, title in (("FPStream", "fpstream", "FP-Stream: whole stream"),
                                   ("DSTree", "dstree", "DSTree: last 3 batches")):
        for metric, label in metrics:
            fig, axis = plt.subplots(figsize=(7.5, 4.5))
            measured = []
            for method, colour, marker in zip(("streamPAMI", "pami"), COLOURS, ("o", "s")):
                group = sorted((row for row in rows if row["algorithm"] == algorithm
                                and row["method"] == method), key=lambda row: float(row["min_sup"]))
                measured.extend(float(row[metric]) for row in group)
                axis.plot([float(row["min_sup"]) for row in group],
                          [float(row[metric]) for row in group], color=colour, marker=marker,
                          markersize=6 if method == "streamPAMI" else 8,
                          markerfacecolor=colour if method == "streamPAMI" else "none",
                          label=("FP-Stream" if algorithm == "FPStream" else "DSTree")
                          if method == "streamPAMI" else BASELINE,
                          linestyle="-" if method == "streamPAMI" else "--")
            axis.set_title(title)
            axis.set_ylabel(label)
            # Reserve empty space inside the axes for the two-line legend.
            axis.set_ylim(0, max(measured) * 1.45)
            filename = "runtime" if metric == "runtime_s" else "memory" if metric == "peak_memory_mb" else metric
            finish(fig, axis, args.images / f"{stem}_{filename}.png")
    fig, axis = plt.subplots(figsize=(7.5, 4.5))
    group = sorted((row for row in rows if row["algorithm"] == "FPStream"
                    and row["method"] == "streamPAMI"), key=lambda row: float(row["min_sup"]))
    for metric, colour, marker in zip(("precision", "recall"), COLOURS, ("o", "s")):
        axis.plot([float(row["min_sup"]) for row in group], [float(row[metric]) for row in group],
                  color=colour, marker=marker, label=metric.capitalize())
    axis.set_ylim(0, 1.05)
    axis.set_ylabel("Precision / recall")
    axis.set_title("FP-Stream against exact FP-growth: final whole stream")
    finish(fig, axis, args.images / "fpstream_precision_recall.png", "lower left")


if __name__ == "__main__":
    main()
