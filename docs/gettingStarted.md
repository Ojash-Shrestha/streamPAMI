# Getting started

## Install

streamPAMI is not on PyPI. Install it from GitHub in your Python environment:

```shell
pip install git+https://github.com/udayRage/streamPAMI
```

For development:

```shell
git clone https://github.com/udayRage/streamPAMI
cd streamPAMI
pip install -e ".[dev]"
```

Use a virtual environment. For the notebooks, also install the `notebooks` extra
with `pip install -e ".[notebooks]"` from the checkout.

## Inputs and support

`iFile` accepts a local file path (a string or `pathlib.Path`), a URL string, or
a pandas DataFrame with a `Transactions` column. Each DataFrame row is a list
of items or a string split using `sep` (tab by default). Items are converted to
strings; repeated items within a transaction count once. A missing file raises
`FileNotFoundError`; a DataFrame without `Transactions` raises `ValueError`.

Each non-blank file or URL line is one transaction. Leading and trailing
whitespace is stripped and blank lines are skipped. Empty transactions supplied
directly to `processBatch`, or as empty lists in a DataFrame, count towards the
support denominator. Here is a DataFrame mixing lists, a tab-separated string,
and an empty transaction:

```python
import pandas as pd
from streamPAMI.frequentPattern.basic.DSTree import DSTree

df = pd.DataFrame({"Transactions": [["a", "b"], "a\tc", [], ["b"], ["a"]]})
miner = DSTree(df, 0.4, windowSize=2, batchSize=5, sep="\t")
miner.mine()
print(dict(sorted(miner.getPatterns().items())))
```

```text
{('a',): 3, ('b',): 2}
```


`minSup` is a **fraction strictly between zero and one**, relative to the
transactions in the queried horizon. Unlike PAMI, an absolute count is not
accepted. Pattern keys are sorted tuples of item strings; supports are counts,
not fractions. Counts are exact for DSTree and estimates for the other miners.

## Mine once

`mine()` reads the input in batches and stores the final answer. It resets the
miner's earlier stream state. This self-contained example runs all three miners:

```python
import pandas as pd
from streamPAMI.frequentPattern.basic.FPStream import FPStream
from streamPAMI.frequentPattern.basic.DSTree import DSTree
from streamPAMI.frequentPattern.basic.LossyCounting import LossyCounting

df = pd.DataFrame({"Transactions": [["bread", "milk"], ["bread"], ["milk"],
                                  ["bread", "milk"], []] * 2})
miners = [("FPStream", FPStream(df, 0.4, 0.1, 5)),
          ("DSTree", DSTree(df, 0.4, 2, 5)),
          ("LossyCounting", LossyCounting(df, 0.4, 0.2, 5))]
for name, miner in miners:
    miner.mine()
    print(name, dict(sorted(miner.getPatterns().items())))
```

```text
FPStream {('bread',): 6, ('bread', 'milk'): 4, ('milk',): 6}
DSTree {('bread',): 6, ('bread', 'milk'): 4, ('milk',): 6}
LossyCounting {('bread',): 6, ('bread', 'milk'): 4, ('milk',): 6}
```


FPStream covers the whole stream by default, DSTree covers its current batch
window, and LossyCounting covers only its processed landmark stream. LossyCounting
requires whole buckets: its batch lengths must be multiples of `ceil(1/epsilon)`.
`mine()` holds an incomplete trailing bucket unprocessed and emits a warning.

## Feed a live stream

Use `iFile=None`, add batches with `processBatch`, and call `queryPatterns()` for
the current answer. For FPStream and DSTree, direct batches can have different
positive lengths; for LossyCounting each length must be a positive multiple of
its bucket width. Each call defines one batch, regardless of `batchSize`.

```python
import pandas as pd
from streamPAMI.frequentPattern.basic.FPStream import FPStream
from streamPAMI.frequentPattern.basic.DSTree import DSTree
from streamPAMI.frequentPattern.basic.LossyCounting import LossyCounting

df = pd.DataFrame({"Transactions": [["bread", "milk"], ["bread"], ["milk"],
                                  ["bread", "milk"], []] * 2})
miners = [("FPStream", FPStream(None, 0.4, 0.1, 5)),
          ("DSTree", DSTree(None, 0.4, 2, 5)),
          ("LossyCounting", LossyCounting(None, 0.4, 0.2, 5))]
for offset in range(0, len(df), 5):
    batch = df["Transactions"].iloc[offset:offset + 5].tolist()
    for name, miner in miners:
        miner.processBatch(batch)
        print(name, "batch", offset // 5 + 1,
              dict(sorted(miner.queryPatterns().items())))
```

```text
FPStream batch 1 {('bread',): 3, ('bread', 'milk'): 2, ('milk',): 3}
DSTree batch 1 {('bread',): 3, ('bread', 'milk'): 2, ('milk',): 3}
LossyCounting batch 1 {('bread',): 3, ('bread', 'milk'): 2, ('milk',): 3}
FPStream batch 2 {('bread',): 6, ('bread', 'milk'): 4, ('milk',): 6}
DSTree batch 2 {('bread',): 6, ('bread', 'milk'): 4, ('milk',): 6}
LossyCounting batch 2 {('bread',): 6, ('bread', 'milk'): 4, ('milk',): 6}
```


`queryPatterns()` returns a fresh answer without updating the stored result from
`mine()`. To inspect a live stream, use that returned dictionary: `getPatterns`,
`getPatternsAsDataFrame` and `save` use the last `mine()` result.

## Common API

| Method | Meaning |
|---|---|
| `mine()` | Replay the input in batches, store the final answer and return the miner. |
| `processBatch(transactions)` | Add one non-empty list of transactions; empty transactions inside it count. |
| `queryPatterns(...)` | Query current state; FPStream/DSTree accept a frame range, LossyCounting accepts no arguments. |
| `getPatterns()` | Dictionary stored by the last `mine()`. |
| `getPatternsAsDataFrame()` | Stored result with columns `Patterns` and `Support`; items are joined with `sep`. |
| `save(oFile)` | Write the stored result as `item1<sep>item2:support` lines in UTF-8. |
| `printResults()` | Print stored pattern count and captured runtime/memory metrics. |
| `getRuntime()` | Seconds captured by the last `mine()` or `processBatch()`. |
| `getMemoryUSS()` | Captured unique set size in bytes; zero if unavailable. |
| `getMemoryRSS()` | Captured resident set size in bytes. |
| `startMine()` | Deprecated alias of `mine()`; emits `DeprecationWarning`. |

`mine()` metrics include its final query. A later `queryPatterns()` does not
refresh these metrics; after `processBatch()` they describe that update, which
matters especially for DSTree's query-time mining. These are captured process
memory readings, not peak-memory measurements.

Continue with [choosing an algorithm](choosingAnAlgorithm.md), or open the
[FPStream](frequentPattern/basic/FPStream.md), [DSTree](frequentPattern/basic/DSTree.md)
and [LossyCounting](frequentPattern/basic/LossyCounting.md) pages.
