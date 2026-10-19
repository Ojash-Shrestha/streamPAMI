[![GitHub license](https://img.shields.io/github/license/udayRage/streamPAMI)](https://github.com/udayRage/streamPAMI/blob/main/LICENSE)
![Python](https://img.shields.io/badge/python-%E2%89%A53.9-blue)
![Status](https://img.shields.io/badge/status-alpha-orange)

***

# Table of Contents

- [Introduction](#introduction)
- [Inputs and Outputs of an Algorithm in streamPAMI](#inputs-and-outputs-of-an-algorithm-in-streampami)
- [Accuracy Guarantees](#accuracy-guarantees)
- [Features](#features)
- [Maintenance](#maintenance)
- [Try your first streamPAMI program](#try-your-first-streampami-program)
- [Mining a live stream](#mining-a-live-stream)
- [Testing](#testing)
- [License](#license)
- [Background](#background)
- [Getting Help](#getting-help)
- [Contribution to streamPAMI](#contribution-to-streampami)
- [Algorithms](#algorithms)
- [References](#references)

***

# Introduction

streamPAMI (stream PAttern MIning) is a Python library of algorithms that discover user
interest-based patterns in **data streams**: unbounded sequences of transactions that arrive
over time and cannot be stored or rescanned in full.

It is the stream counterpart of [PAMI](https://github.com/UdayLab/PAMI) and follows the same
package layout and the same method names, so PAMI users can start without learning a new interface.

| | PAMI | streamPAMI |
|---|---|---|
| Data | a static database, read in full | a stream, read one batch at a time |
| Memory | the whole database | a compact summary of the stream |
| Answers | exact, for the whole database | for any time period; exact or with a stated error bound |
| Live data | no | yes: `processBatch()` / `queryPatterns()` |

<!-- TODO(Ojash): add links (tutorials, datasets, discussions) once they exist, as in PAMI's Introduction. -->

***

# Inputs and Outputs of an Algorithm in streamPAMI

**Inputs** (example: FP-Stream)

| Parameter | Meaning |
|---|---|
| `iFile` | Input stream: a file path, a URL, or a pandas DataFrame with a `Transactions` column (same formats as PAMI). Use `None` when feeding batches yourself with `processBatch()`. |
| `minSup` | Minimum support σ as a **fraction** in (0, 1) of the transactions in the queried period. Unlike PAMI, absolute counts are not accepted, because the size of a period depends on the query. |
| `epsilon` | Maximum support error ε, in (0, minSup). Smaller is more accurate but uses more memory. |
| `batchSize` | Number of transactions per batch when reading `iFile`. |
| `sep` | Item separator (default: tab). |

**Outputs**

| Method | Returns |
|---|---|
| `mine()` | Reads `iFile` batch by batch and stores the patterns for the whole stream. |
| `getPatterns()` | `{(item, ...): support}` from the last `mine()`. |
| `getPatternsAsDataFrame()` | The same, as a DataFrame with columns `Patterns` and `Support`. |
| `save(oFile)` | Writes `pattern:support` lines. |
| `processBatch(transactions)` | Adds one batch to the summary. |
| `queryPatterns(startFrame, endFrame)` | Patterns for a period made of time frames (0 = newest). Can be called at any time. |
| `getTimeFrames()` | The batch range `(start, end)` covered by each time frame, newest first. |
| `getRuntime()`, `getMemoryRSS()`, `getMemoryUSS()`, `printResults()` | As in PAMI. |

***

# Accuracy Guarantees

Approximate stream algorithms trade accuracy for memory. Every algorithm in streamPAMI states its
guarantee, and the test suite checks that guarantee against a brute-force miner.

**FP-Stream** (Giannella et al., 2003). The guarantee holds only when σ > 2·ε and
the queried period **starts at the newest time frame**. For such a period with W
transactions and true support f:

1. Every pattern with f ≥ σ·W is returned (no false negatives).
2. Each returned support lies in [f − ε·W, f].
3. Patterns with f between (σ − ε)·W and σ·W may also be returned.

**Known limitations.** With ε ≥ σ/2, false negatives are possible, and the constructor emits a
`UserWarning`. For periods that start at an older frame, a frequent pattern can be missed when
recent batches are much larger than older ones. A reproducible case is recorded in
`tests/test_FPStream.py::test_false_negative_older_period_uneven_batches`.
<!-- TODO(Ojash): update after the Section 3.5 decision (document as a limitation of the paper, or fix the pruning rule). -->

**DSTree** is exact over any contiguous range of batches in its sliding window of
`windowSize` batches. Empty transactions supplied to `processBatch` count towards the support
denominator; blank lines in files and URLs are skipped. Its tree retains the window's
transactions, compressed by shared prefixes, so memory grows with the window and its per-node
batch counts; it has no epsilon-bounded summary.

***

# Features

- ✅ Every algorithm is checked against a brute-force oracle after every batch, on random and drifting streams
- 📏 Stated accuracy guarantees, with exact (fractional) threshold arithmetic
- 🌊 Works on live streams, not only on files replayed from disk
- 🧠 Memory follows the algorithm: a compact summary or a compressed sliding window
- 🔁 Same interface as PAMI
- 🖥️ Operating system independent

***

# Maintenance

__Installation__

streamPAMI is not on PyPI yet. Install it from GitHub:

    pip install git+https://github.com/udayRage/streamPAMI.git

For development (includes pytest):

    git clone https://github.com/udayRage/streamPAMI.git
    cd streamPAMI
    pip install -e ".[dev]"

__Upgradation__

    pip install --upgrade git+https://github.com/udayRage/streamPAMI.git

__Uninstallation__

    pip uninstall streamPAMI

__Information__

    pip show streamPAMI

***

# Try your first streamPAMI program

```shell
$ python
```

```python
# first import streamPAMI
from streamPAMI.frequentPattern.basic import FPStream as alg
fileURL = "https://u-aizu.ac.jp/~udayrage/datasets/transactionalDatabases/Transactional_T10I4D100K.csv"
obj = alg.FPStream(iFile=fileURL, minSup=0.01, epsilon=0.002, batchSize=10000, sep='\t')
obj.mine()
obj.save('frequentPatternsAtMinSup0.01.txt')
frequentPatternsDF = obj.getPatternsAsDataFrame()
print('Total No of patterns: ' + str(len(frequentPatternsDF)))
print('Runtime: ' + str(obj.getRuntime()))
print('Memory (RSS): ' + str(obj.getMemoryRSS()))
print('Memory (USS): ' + str(obj.getMemoryUSS()))
```

```
Output:
<!-- TODO(Ojash): run the code above and paste the REAL output here. -->
```

***

# Mining a live stream

Feed batches as they arrive and ask for the current answer at any time:

```python
from streamPAMI.frequentPattern.basic import FPStream as alg

obj = alg.FPStream(iFile=None, minSup=0.4, epsilon=0.1, batchSize=4)

stream = [
    [["bread", "milk"], ["bread", "butter"], ["milk"], ["bread", "milk", "butter"]],
    [["bread", "milk"], ["milk"], ["milk", "eggs"], ["bread", "milk"]],
    [["eggs"], ["milk", "eggs"], ["eggs", "butter"], ["milk", "eggs"]],
]
for batch in stream:
    obj.processBatch(batch)                      # update the summary with one batch
    print("Time frames (newest first):", obj.getTimeFrames())
    print("Frequent now:", obj.queryPatterns())  # answer for the whole stream so far

print("Most recent batch only:", obj.queryPatterns(startFrame=0, endFrame=1))
```

```
Output:
Time frames (newest first): [(0, 1)]
Frequent now: {('bread',): 3, ('butter',): 2, ('milk',): 3, ('bread', 'butter'): 2, ('bread', 'milk'): 2}
Time frames (newest first): [(1, 2), (0, 1)]
Frequent now: {('bread',): 5, ('milk',): 7, ('bread', 'milk'): 4}
Time frames (newest first): [(2, 3), (0, 2)]
Frequent now: {('bread',): 5, ('milk',): 9, ('bread', 'milk'): 4, ('eggs',): 5}
Most recent batch only: {('milk',): 2, ('eggs',): 4, ('eggs', 'milk'): 2}
```

Notice how `eggs` becomes frequent once it appears in the third batch, and how batches 0 and 1
were merged into one time frame `(0, 2)`: older data is kept at coarser granularity.

***

# Testing

    pytest -v

Each algorithm is compared after every batch against `tests/bruteForce.py`, which counts every
itemset exactly. Exact algorithms must match it; approximate algorithms must satisfy their stated
guarantee. Known limitations are recorded as strict expected failures (`xfail`), so they cannot be
silently forgotten or silently "fixed".

***

# License

[![GitHub license](https://img.shields.io/github/license/udayRage/streamPAMI)](https://github.com/udayRage/streamPAMI/blob/main/LICENSE)

streamPAMI is released under the GNU General Public License v3.0.

***

# Background

streamPAMI is developed at [UdayLab](https://github.com/UdayLab), [University of Aizu](https://u-aizu.ac.jp/en/),
as the stream mining companion to PAMI.
<!-- TODO(Ojash / Professor Rage): confirm wording, start year and maintainers. -->

***

# Getting Help

Please open an issue at [GitHub Issues](https://github.com/udayRage/streamPAMI/issues).

***

# Contribution to streamPAMI

Contributions are welcome: bug reports, fixes, documentation and new algorithms. A new algorithm must:

1. follow the PAMI layout: `streamPAMI/<patternFamily>/<variant>/<Algorithm>.py`;
2. state its paper reference and accuracy guarantee in its docstring;
3. come with a test against the brute-force oracle that checks that guarantee after every batch.

***

# Algorithms

### 1. Pattern mining in binary transactional streams

#### 1.1. Frequent pattern mining

| Basic | Closed | Maximal | Top-k |
|---|---|---|---|
| FP-Stream, DSTree | | | |

***

# References

- C. Giannella, J. Han, J. Pei, X. Yan and P. S. Yu, "Mining Frequent Patterns in Data Streams at
  Multiple Time Granularities", *Next Generation Data Mining*, 2003.
  [PDF](https://www2.cs.sfu.ca/~jpei/publications/fpstm03.pdf)

[Go to Top](#table-of-contents)
