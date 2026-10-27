# DSTree

## Overview

DSTree retains a sliding window of transaction batches in a prefix tree. Queries
mine exact frequent itemsets over the whole window or a contiguous part of it.
Older batches leave the tree as new batches arrive.

## When to use it / when not to

Use it when exact answers over recent batches matter and you can retain the
window. Do not use it expecting a compact epsilon-controlled summary, or access
to batches that have already left the window. Frequent queries repeat mining.

## Parameters

`DSTree(iFile, minSup, windowSize, batchSize, sep="\t")`

| Name | Type | Meaning | Constraints |
|---|---|---|---|
| `iFile` | path, URL string, DataFrame or `None` | Replay input, or live input when `None`. | DataFrame column must be `Transactions`; a missing file raises. |
| `minSup` | float | Default relative support within the queried batch range. | `0 < minSup < 1`; an absolute count is not accepted. |
| `windowSize` | int | Maximum number of batches retained. | Integer at least one; booleans are rejected. |
| `batchSize` | int | Transactions per replay batch. | Integer at least one; booleans are rejected. A final smaller batch counts as one batch. |
| `sep` | str | Input/output item separator. | Default tab. |

Each direct `processBatch` call adds one batch, which can have any positive
length. If the window is full, its oldest batch leaves before the new batch is
inserted. There is no epsilon parameter. The constructor's minSup is the default
for queries and is always used by `mine()`.

## Algorithm-specific methods

| Method | Meaning |
|---|---|
| `getTimeFrames()` | One `(startBatch, endBatch)` per retained batch, newest first; ends are exclusive and indices refer to the original stream. |
| `getFrameWeights()` | Each retained batch's transaction count, newest first. |
| `queryPatterns(startFrame=0, endFrame=None, minSup=None)` | Exact query from startFrame inclusive to endFrame exclusive; endFrame=None extends to the oldest retained frame. minSup=None uses the constructor threshold; pass a float in (0, 1) to override it for this query. |

`queryPatterns(0, 1)` queries the latest batch; `queryPatterns()` queries the
whole current window. The support denominator includes empty transactions in
the selected batches.

A minSup override uses exact `Fraction(str(minSup))` arithmetic and rejects
booleans, strings, NaN, infinity and values outside (0, 1). Frame validation runs
first. The override does not rebuild the tree, change the constructor's minSup,
replace `getPatterns()`, or update the captured runtime/memory metrics.

## Example

```python
import pandas as pd
from streamPAMI.frequentPattern.basic.DSTree import DSTree

df = pd.DataFrame({"Transactions": [["a", "b"], ["a"], ["b"], [],
                                  ["a", "b"], ["b"]]})
miner = DSTree(df, minSup=0.5, windowSize=2, batchSize=2)
miner.mine()
print("Current window:", dict(sorted(miner.getPatterns().items())))
print("Frames:", miner.getTimeFrames())
print("Frame weights:", miner.getFrameWeights())
print("Newest frame:", dict(sorted(miner.queryPatterns(0, 1).items())))
```

```text
Current window: {('b',): 3}
Frames: [(2, 3), (1, 2)]
Frame weights: [2, 2]
Newest frame: {('a',): 1, ('a', 'b'): 1, ('b',): 2}
```


The oldest batch has left the window. Its public batch indices do not restart
when the window slides.

The same retained window can be queried at different thresholds without
rebuilding or replaying it:

```python
import pandas as pd
from streamPAMI.frequentPattern.basic.DSTree import DSTree

df = pd.DataFrame({"Transactions": [["a", "b"], ["a"], ["b"], [],
                                  ["a", "b"], ["b"]]})
miner = DSTree(df, minSup=0.5, windowSize=2, batchSize=2)
miner.mine()
for minimum in (0.25, 0.75):
    print(f"minSup={minimum}:", dict(sorted(miner.queryPatterns(minSup=minimum).items())))
print("Stored constructor result:", dict(sorted(miner.getPatterns().items())))
```

```text
minSup=0.25: {('a',): 1, ('a', 'b'): 1, ('b',): 3}
minSup=0.75: {('b',): 3}
Stored constructor result: {('b',): 3}
```

## Accuracy guarantees and limitations

Results are exact over every contiguous batch range still in the window:
an itemset is returned precisely when its count is at least `minSup * W`, with W
the number of transactions in that queried range. Comparisons use exact
Fraction arithmetic. There are no false positives or false negatives.

This implementation is an **eager-maintenance variant**. Every slide drops the
oldest count slot from all nodes and immediately removes all-zero nodes. The
paper defers updates with a per-node last-update pointer and does not specify
when zero nodes are physically deleted. Query results agree, but update time
and memory can differ. A fixed lexicographic item order never follows changing
frequencies; mining is FP-growth-style and happens only when queried.

The tree retains every transaction in the window, compressed by shared
prefixes, with per-batch node counts. Memory grows with window contents and
count vectors; there is no epsilon-bounded summary. The relative support
convention over the queried range is streamPAMI's choice.

## Reference

C. K.-S. Leung and Q. I. Khan, "DSTree: A Tree Structure for the Mining of Frequent
Sets from Data Streams", Proc. IEEE ICDM, 2006, pp. 928-932, doi:10.1109/ICDM.2006.62.

## Tutorial

[Executed notebook](../../../notebooks/frequentPattern/basic/DSTree.ipynb)

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/udayRage/streamPAMI/blob/main/notebooks/frequentPattern/basic/DSTree.ipynb)
