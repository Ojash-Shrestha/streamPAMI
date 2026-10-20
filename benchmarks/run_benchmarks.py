"""Measure real streaming runs against PAMI FP-growth in fresh subprocesses.

Run from the repository root with the project's virtual environment activated.
No library code is changed and no measured values are synthesised.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
from datetime import datetime, timezone
from fractions import Fraction
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import random
import statistics
import subprocess
import sys
import tempfile
import time

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
MIN_SUPS = ("0.006", "0.007", "0.008", "0.009", "0.010")
BATCH_SIZE = 10_000
WINDOW_SIZE = 3
REPETITIONS = 5
RUN_ORDER_SEED = 20261020
DATA_URL = "https://u-aizu.ac.jp/~udayrage/datasets/transactionalDatabases/Transactional_T10I4D100K.csv"


def read_batches(path):
    batches, batch = [], []
    with path.open(encoding="utf-8") as source:
        for line in source:
            if line.strip():
                batch.append(list(dict.fromkeys(line.strip().split("\t"))))
                if len(batch) == BATCH_SIZE:
                    batches.append(batch)
                    batch = []
    if batch:
        batches.append(batch)
    if len(batches) != 10:
        raise ValueError("Expected ten batches of at most 10,000 non-blank transactions")
    return batches


def peak_memory_mb():
    if sys.platform == "win32":
        return psutil.Process().memory_info().peak_wset / 1_000_000
    import resource
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / (1_000_000 if sys.platform == "darwin" else 1_000)


def normalise(patterns):
    return {tuple(sorted(key.strip().split("\t") if isinstance(key, str) else key)): int(count)
            for key, count in patterns.items()}


def worker(args):
    # Every worker loads the same data before timing, regardless of its horizon.
    batches = read_batches(args.data)
    sigma = Fraction(args.min_sups[0])
    if args.method == "pami":
        from PAMI.frequentPattern.basic.FPGrowth import FPGrowth
    elif args.algorithm == "FPStream":
        from streamPAMI.frequentPattern.basic.FPStream import FPStream
        miner = FPStream(None, float(sigma), float(sigma / 10), BATCH_SIZE)
    else:
        from streamPAMI.frequentPattern.basic.DSTree import DSTree
        miner = DSTree(None, float(sigma), WINDOW_SIZE, BATCH_SIZE)

    snapshots = []
    with tempfile.TemporaryDirectory(prefix="streampami-input-") as temp_dir:
        input_path = Path(temp_dir) / "transactions.txt"
        with open(os.devnull, "w") as quiet:
            started = time.perf_counter()
            for batch_no, batch in enumerate(batches):
                if args.method == "pami":
                    first = 0 if args.algorithm == "FPStream" else max(0, batch_no - WINDOW_SIZE + 1)
                    active = batches[first:batch_no + 1]
                    weight = sum(map(len, active))
                    with input_path.open("w", encoding="utf-8", newline="\n") as target:
                        for active_batch in active:
                            for transaction in active_batch:
                                target.write("\t".join(transaction) + "\n")
                    # PAMI receives an integer absolute count, never a fraction.
                    miner = FPGrowth(str(input_path), math.ceil(sigma * weight), sep="\t")
                    with contextlib.redirect_stdout(quiet):
                        miner.mine()
                    patterns = normalise(miner.getPatterns())
                else:
                    miner.processBatch(batch)
                    patterns = miner.queryPatterns()
                # Retain every answer for validation outside the measured loop.
                snapshots.append(patterns)
            runtime = time.perf_counter() - started
    peak = peak_memory_mb()
    result = {"runtime_s": runtime, "peak_memory_mb": peak,
              "patterns": len(snapshots[-1]),
              "snapshots": [[[list(pattern), count] for pattern, count in sorted(answer.items())]
                            for answer in snapshots]}
    args.worker_output.write_text(json.dumps(result), encoding="utf-8")


def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def machine_details(data, batches, args):
    cpu = platform.processor()
    if sys.platform == "win32":
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
            cpu = winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
    return {
        "recorded_utc": datetime.now(timezone.utc).isoformat(),
        "os": platform.platform(), "cpu": cpu, "logical_cpus": psutil.cpu_count(),
        "ram_gb": psutil.virtual_memory().total / 1_000_000_000,
        "python": platform.python_version(), "python_executable": sys.executable,
        "pandas": importlib.metadata.version("pandas"),
        "pami": importlib.metadata.version("pami"),
        "matplotlib": importlib.metadata.version("matplotlib"),
        "streampami_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "data_sha256": hashlib.sha256(data.read_bytes()).hexdigest(),
        "data_url": DATA_URL, "transactions": sum(map(len, batches)), "batch_size": BATCH_SIZE,
        "batch_sizes": ";".join(str(len(batch)) for batch in batches),
        "batches": len(batches), "window_size": WINDOW_SIZE, "epsilon_ratio": "0.1",
        "memory_unit": "MB (1,000,000 bytes)",
        "run_order_seed": args.seed, "repetitions": args.repetitions,
    }


def unpack(result):
    return [{tuple(pattern): count for pattern, count in snapshot}
            for snapshot in result["snapshots"]]


def check_answers(algorithm, min_sup, stream, baseline):
    actual, exact = unpack(stream), unpack(baseline)
    if algorithm == "DSTree":
        for batch_no, (answer, expected) in enumerate(zip(actual, exact), 1):
            for pattern in sorted(answer.keys() | expected.keys()):
                if answer.get(pattern) != expected.get(pattern):
                    raise AssertionError(
                        f"DSTree mismatch: minSup={min_sup}, batch={batch_no}, itemset={pattern}, "
                        f"DSTree={answer.get(pattern)}, PAMI={expected.get(pattern)}")
        return "", ""
    returned, frequent = set(actual[-1]), set(exact[-1])
    missing = frequent - returned
    if missing:
        pattern = sorted(missing)[0]
        raise AssertionError(
            f"FPStream guarantee violation: minSup={min_sup}, batch=10, itemset={pattern}, "
            f"estimate={actual[-1].get(pattern)}, PAMI={exact[-1][pattern]}")
    precision = len(returned & frequent) / len(returned) if returned else 1.0
    recall = len(returned & frequent) / len(frequent) if frequent else 1.0
    return precision, recall


def build_schedule(min_sups, repetitions, seed):
    schedule = [(algorithm, min_sup, method, repetition)
                for algorithm in ("FPStream", "DSTree")
                for min_sup in min_sups
                for method in ("pami", "streamPAMI")
                for repetition in range(1, repetitions + 1)]
    random.Random(seed).shuffle(schedule)
    return schedule


def run(args):
    batches = read_batches(args.data)  # Validate the ten-batch scenario before measuring.
    schedule = build_schedule(args.min_sups, args.repetitions, args.seed)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    # A failed rerun must not leave a previous summary available for plotting.
    (args.output_dir / "summary.csv").unlink(missing_ok=True)
    log_path = args.output_dir / "console.txt"
    with log_path.open("w", encoding="utf-8") as log:
        def report(message):
            print(message, flush=True)
            log.write(message + "\n")
            log.flush()

        metadata = machine_details(args.data, batches, args)
        write_csv(args.output_dir / "machine.csv", [metadata])
        report(f"Machine: {metadata['cpu']}; {metadata['os']}; RAM={metadata['ram_gb']:.3f} GB")
        report(f"Versions: Python={metadata['python']}, pandas={metadata['pandas']}, "
               f"PAMI={metadata['pami']}, matplotlib={metadata['matplotlib']}")
        report(f"streamPAMI commit: {metadata['streampami_commit']}")
        report(f"Data: {metadata['transactions']} transactions; batch sizes={metadata['batch_sizes']}; "
               f"SHA256={metadata['data_sha256']}")
        report(f"Randomised run order: seed={args.seed}; repetitions={args.repetitions}; "
               f"scheduled_runs={len(schedule)}")
        write_csv(args.output_dir / "schedule.csv", [
            {"run_index": index, "algorithm": algorithm, "min_sup": min_sup,
             "method": method, "repetition": repetition}
            for index, (algorithm, min_sup, method, repetition) in enumerate(schedule, 1)])
        rows = []
        pending = {}
        fp_checks = ds_batch_checks = 0
        started = time.perf_counter()
        with tempfile.TemporaryDirectory(prefix="streampami-results-") as temp_dir:
            for run_index, (algorithm, min_sup, method, repetition) in enumerate(schedule, 1):
                output = Path(temp_dir) / f"worker-{run_index}.json"
                command = [sys.executable, str(Path(__file__).resolve()),
                           "--worker", "--data", str(args.data.resolve()),
                           "--algorithm", algorithm, "--method", method,
                           "--min-sups", min_sup, "--worker-output", str(output)]
                start_utc = datetime.now(timezone.utc).isoformat()
                report(f"START run_index={run_index} start_utc={start_utc} {algorithm} "
                       f"minSup={min_sup} repetition={repetition} method={method}")
                subprocess.run(command, cwd=ROOT, check=True)
                result = json.loads(output.read_text(encoding="utf-8"))
                row = {"run_index": run_index, "start_utc": start_utc,
                       "algorithm": algorithm, "min_sup": min_sup, "method": method,
                       "repetition": repetition, "patterns": result["patterns"],
                       "runtime_s": result["runtime_s"],
                       "peak_memory_mb": result["peak_memory_mb"], "precision": "", "recall": ""}
                rows.append(row)
                report(f"DONE run_index={run_index} {algorithm} minSup={min_sup} "
                       f"repetition={repetition} method={method} patterns={result['patterns']} "
                       f"runtime_s={result['runtime_s']:.6f} peak_memory_mb={result['peak_memory_mb']:.6f}")
                key = (algorithm, min_sup, repetition)
                pair = pending.setdefault(key, {})
                pair[method] = (output, row)
                if len(pair) == 2:
                    results = {name: json.loads(path.read_text(encoding="utf-8"))
                               for name, (path, _) in pair.items()}
                    precision, recall = check_answers(
                        algorithm, min_sup, results["streamPAMI"], results["pami"])
                    pair["streamPAMI"][1].update(precision=precision, recall=recall)
                    report(f"CHECK {algorithm} minSup={min_sup} repetition={repetition}: "
                           + (f"precision={precision:.6f} recall={recall:.6f}" if algorithm == "FPStream"
                              else "identical patterns and supports at all 10 batches"))
                    if algorithm == "FPStream":
                        fp_checks += 1
                    else:
                        ds_batch_checks += len(results["streamPAMI"]["snapshots"])
                    for path, _ in pair.values():
                        path.unlink()
                    del pending[key]
                write_csv(args.output_dir / "runs.csv", rows)
            assert not pending, "Every run must have a checked counterpart"
        summary = []
        for algorithm in ("FPStream", "DSTree"):
            for min_sup in args.min_sups:
                for method in ("pami", "streamPAMI"):
                    group = [row for row in rows if (row["algorithm"], row["min_sup"], row["method"])
                             == (algorithm, min_sup, method)]
                    if any(len({row[field] for row in group}) != 1
                           for field in ("patterns", "precision", "recall")):
                        raise AssertionError("Answers differ between deterministic repetitions")
                    summary.append({"algorithm": algorithm, "min_sup": min_sup, "method": method,
                                    "repetitions": len(group), "patterns": group[0]["patterns"],
                                    "runtime_s": statistics.median(row["runtime_s"] for row in group),
                                    "peak_memory_mb": statistics.median(row["peak_memory_mb"] for row in group),
                                    "runtime_s_min": min(row["runtime_s"] for row in group),
                                    "runtime_s_max": max(row["runtime_s"] for row in group),
                                    "peak_memory_mb_min": min(row["peak_memory_mb"] for row in group),
                                    "peak_memory_mb_max": max(row["peak_memory_mb"] for row in group),
                                    "precision": group[0]["precision"], "recall": group[0]["recall"]})
        write_csv(args.output_dir / "summary.csv", summary)
        elapsed = time.perf_counter() - started
        report(f"Completed {len(rows)} fresh subprocesses in {elapsed:.3f} s.")
        report(f"Run order: seed={args.seed}; {args.repetitions} repetitions; "
               f"run_index=1..{len(rows)}; start_utc recorded for every run.")
        report(f"Correctness: FP-Stream recall=1.0 in {fp_checks} checks; "
               f"DSTree identical in {ds_batch_checks} batch comparisons.")
        report("Summary: median runtime and median peak memory, with min-max ranges; "
               "no averaging of pattern counts.")
        report("Runtime labels use disjoint min-max ranges; overlapping or touching ranges are similar.")
        for algorithm in ("FPStream", "DSTree"):
            comparisons = []
            for min_sup in args.min_sups:
                pair = {point["method"]: point for point in summary
                        if point["algorithm"] == algorithm and point["min_sup"] == min_sup}
                stream, baseline = pair["streamPAMI"], pair["pami"]
                if stream["runtime_s_max"] < baseline["runtime_s_min"]:
                    relation = "faster"
                elif stream["runtime_s_min"] > baseline["runtime_s_max"]:
                    relation = "slower"
                else:
                    relation = "similar"
                comparisons.append(f"{min_sup}={relation}")
            report(f"{algorithm} runtime vs PAMI: " + "; ".join(comparisons))
        if len(args.min_sups) == 1 and args.repetitions == 1:
            projected = elapsed * len(MIN_SUPS) * REPETITIONS
            report(f"Pilot projection for 5 minSup values x {REPETITIONS} repetitions: {projected:.3f} s "
                   f"({projected / 3600:.3f} hours).")
            if projected > 7200:
                report("STOP: projected full run exceeds two hours; ask before changing any parameter.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--min-sups", nargs="+", default=list(MIN_SUPS))
    parser.add_argument("--repetitions", type=int, default=REPETITIONS)
    parser.add_argument("--seed", type=int, default=RUN_ORDER_SEED)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "benchmarks/results")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--algorithm", choices=("FPStream", "DSTree"), help=argparse.SUPPRESS)
    parser.add_argument("--method", choices=("pami", "streamPAMI"), help=argparse.SUPPRESS)
    parser.add_argument("--worker-output", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.repetitions < 1 or any(value not in MIN_SUPS for value in args.min_sups):
        parser.error("Use positive repetitions and minSup values from " + ", ".join(MIN_SUPS))
    if args.worker:
        worker(args)
    else:
        run(args)


if __name__ == "__main__":
    main()
