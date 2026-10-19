# Reproducing the measurements

Activate the project's virtual environment from the repository root:

```powershell
.venv\Scripts\activate
python -m pip install -e ".[bench]"
```

Download [T10I4D100K](https://u-aizu.ac.jp/~udayrage/datasets/transactionalDatabases/Transactional_T10I4D100K.csv)
once to `benchmarks/data/Transactional_T10I4D100K.csv`. The data directory is ignored by Git.
The supplied URL contains 99,935 non-blank transactions: nine batches of 10,000
and a final batch of 9,935. The runner requires ten batches and uses actual
transaction counts, without padding the dataset.
It preserves transaction order, splits on tabs and removes duplicate items within transactions.

Run the pilot first:

```powershell
python benchmarks/run_benchmarks.py --data benchmarks/data/Transactional_T10I4D100K.csv --min-sups 0.006 --repetitions 1 --output-dir benchmarks/results/pilot
```

The pilot runs both algorithms and both methods. Its elapsed time multiplied by
15 estimates the complete run. Stop and obtain approval if that exceeds two hours;
do not change the specified parameters to reduce the estimate.

The fresh pilot with the optimised FP-Stream completed four subprocesses in
101.774 seconds. Its projected full-run duration was 1,526.605 seconds
(about 25 minutes 27 seconds), below the two-hour stopping limit. Earlier pilot
results from the previous implementation were deleted before this run.

Then run all configurations, followed by the plots:

```powershell
python benchmarks/run_benchmarks.py --data benchmarks/data/Transactional_T10I4D100K.csv
python benchmarks/plot_benchmarks.py
```

## Scenario and measurement boundaries

The stream is queried after each of ten batches of at most 10,000 transactions.
FP-Stream queries all transactions so far with epsilon = 0.1 * minSup.
DSTree queries its current window of three batches. Each is compared with
`PAMI.frequentPattern.basic.FPGrowth`, re-mined at every batch over the matching
horizon, with integer threshold `ceil(Fraction(minSup) * W)`.
The five minSup values are 0.006, 0.007, 0.008, 0.009 and 0.010.
All three repetitions of every configuration run sequentially in fresh subprocesses.

Each subprocess loads the dataset before `perf_counter` starts, so dataset reading
and imports are excluded from runtime. Runtime covers the complete ten-batch loop:
stream updates and queries, or writing the baseline's temporary transaction file
and re-mining it. PAMI's tab-separated pattern keys are normalised to sorted tuples.
Both methods retain answers for validation; output serialisation and parent-process
correctness checks happen after timing. No garbage collection is forced.

Memory is the subprocess's peak working set on Windows (`peak_wset`), or
`resource.getrusage(RUSAGE_SELF).ru_maxrss` elsewhere, converted to decimal MB.
It includes imports, the same preloaded dataset in both methods, tree state,
temporary mining allocations and retained validation answers. It is a process peak,
not the incremental size of a tree or the sum of memory readings after each batch.
It is sampled before serialising the results. The graphs show the maximum peak
across repetitions, and the median total runtime. No values are smoothed or edited.

DSTree's pattern sets and integer supports must match PAMI after every batch.
FP-Stream's final recall must equal 1.0; its precision can be lower because it
also returns candidates below minSup. Any mismatch or missing frequent pattern
raises an exception and stops the runner; no summary is produced for a failed run.

## Evidence and machine details

`results/runs.csv` contains every measured subprocess. `results/summary.csv`
contains the plotted aggregates. `results/machine.csv` records OS, CPU, RAM,
Python, pandas, PAMI and matplotlib versions, the streamPAMI commit, runner and
dataset SHA-256 hashes, and all scenario parameters. `results/console.txt` is the
actual runner output. Pilot evidence is kept separately in `results/pilot/`.

The fresh pilot and full run captured the following machine and software details (the CSV also
preserves full precision, paths and hashes):

| Field | Captured value |
|---|---|
| OS | Windows-10-10.0.26200-SP0 |
| CPU | Intel(R) Core(TM) i7-14650HX, 24 logical CPUs |
| RAM | 34.049486848 GB (decimal) |
| Python | 3.11.9, project's `.venv` |
| pandas | 3.0.6 |
| PAMI | 2026.10.13.1 |
| matplotlib | 3.11.2 |
| streamPAMI commit | `cb5493c1f815250717d1810ff82e25905b933ca7` |
| Dataset SHA-256 | `3fdde151ee63fbf9d608619352a0e69690cc55bc2faa11dc724337fbf413a2b1` |

The recorded commit identifies the library code being measured. The runner's
SHA-256 identifies the benchmark script, which is committed separately with its
results so that measurements do not require a self-referential commit hash.

## Observed results

The full run completed 60 fresh subprocesses in 973.680 seconds (about 16 minutes
14 seconds). The pilot is separate and is not included in the three-repetition
aggregates.

- FP-Stream's final recall was 1.0 in all 15 checks. Precision ranged from
  0.825668449197861 to 0.9144893111638955, reflecting additional returned candidates.
- DSTree matched PAMI's pattern sets and supports in all 150 batch-by-batch checks.
- FP-Stream's median runtime was higher at minSup 0.006, 0.007 and 0.008, and lower
  at 0.009 and 0.010. Its peak process memory was lower at every setting.
- DSTree's median runtime was higher at every setting. Its peak process memory
  was slightly lower at 0.006–0.009 and slightly higher at 0.010.

The timings vary between repetitions. The curves connect measured CSV values;
they are not smoothed. See [all repetitions](results/runs.csv),
[plotted aggregates](results/summary.csv), [machine details](results/machine.csv)
and [the complete real console output](results/console.txt).
