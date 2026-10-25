# LossyCounting

## Overview

LossyCounting estimates frequent itemsets over a landmark window: the processed
stream from its beginning. It updates itemset counts and error bounds using
batches made of complete transaction buckets. Queries cannot select an older
subrange or sliding window.

## When to use it / when not to

Use it for approximate whole-stream counts when your batches can contain whole
buckets. Do not use it for historical subranges, exact answers, or a workflow
that must immediately include a final incomplete bucket. Extra candidates below
minSup are allowed.

## Parameters

`LossyCounting(iFile, minSup, epsilon, batchSize, sep="\t")`

| Name | Type | Meaning | Constraints |
|---|---|---|---|
| `iFile` | path, URL string, DataFrame or `None` | Replay input, or live input when `None`. | DataFrame column must be `Transactions`; a missing file raises. |
| `minSup` | float | Relative landmark support threshold, s. | `0 < minSup < 1`; an absolute count is not accepted. |
| `epsilon` | float | Error parameter; bucket width is `w = ceil(1/epsilon)`. | `0 < epsilon < minSup`; conversion uses `Fraction(str(epsilon))`. |
| `batchSize` | int | Transactions per full replay batch. | Positive integer, not a boolean, and a multiple of w. Every direct batch must also be a positive multiple of w. |
| `sep` | str | Input/output item separator. | Default tab. |

`mine()` processes full batches and the largest whole-bucket prefix of a final
partial batch. It holds any remainder unprocessed and emits `UserWarning` with
the number held. Held transactions do not enter the stream length or counts.

## Algorithm-specific methods

| Method | Meaning |
|---|---|
| `queryPatterns()` | Estimated counts over all processed transactions; takes **no frame arguments**. |
| `getStreamLength()` | N, the number of processed transactions, including empty transactions. |
| `getHeldCount()` | Size of the unprocessed suffix held by the last `mine()`. |

There are no time-frame methods or per-query minSup parameter.

## Example

```python
import pandas as pd
from fractions import Fraction
from streamPAMI.frequentPattern.basic.LossyCounting import LossyCounting

df = pd.DataFrame({"Transactions": [["a", "b"], ["a"], ["b", "c"], ["a", "b"]] * 5})
miner = LossyCounting(df, minSup=0.4, epsilon=0.2, batchSize=5)
miner.mine()
print("Estimated patterns:", dict(sorted(miner.getPatterns().items())))
print("Processed:", miner.getStreamLength(), "Held:", miner.getHeldCount())
true_c = sum("c" in transaction for transaction in df["Transactions"])
print("True c support:", true_c, "/", len(df), "=", true_c / len(df))
threshold = (Fraction(str(miner.minSup)) - Fraction(str(miner.epsilon))) * miner.getStreamLength()
print("Output threshold:", threshold)
```

```text
Estimated patterns: {('a',): 15, ('a', 'b'): 10, ('b',): 15, ('b', 'c'): 4, ('c',): 4}
Processed: 20 Held: 0
True c support: 5 / 20 = 0.25
Output threshold: 4
```


This example shows false positives relative to minSup. Both `('c',)` and
`('b', 'c')` are returned with estimate 4,
although c occurs in only 5/20 transactions
(relative support 0.25, below minSup).
The inclusive output threshold is `(minSup - epsilon) * N = 4`.
Guarantee 2 permits these candidates: their true counts are above that lower
threshold. Their reported counts can underestimate the true count.

## Accuracy guarantees and limitations

For the **processed landmark stream** with N transactions and true itemset count f:

1. Every itemset with `f >= minSup * N` is returned.
2. No returned itemset has `f < (minSup - epsilon) * N`.
3. Every returned estimate is in `[f - epsilon * N, f]`.

Thresholds use exact Fraction arithmetic. In particular, epsilon written as
the floating-point expression `1/3` gives **w = 4**, not a bucket of three:

```python
from fractions import Fraction
from math import ceil

epsilon = 1 / 3
print("epsilon as a float:", epsilon)
print("Bucket width:", ceil(1 / Fraction(str(epsilon))))
```

```text
epsilon as a float: 0.3333333333333333
Bucket width: 4
```


Each batch contains beta whole buckets. UPDATE_SET runs first and deletes an
entry when its updated count plus error is at most the current bucket id.
NEW_SET then inserts missing entries with batch count at least beta, even if
they were just deleted. Insertion follows the formal inclusive NEW_SET rule;
the paper's surrounding prose also uses inconsistent strict wording.

**Data-structure deviation:** this implementation uses a dictionary and counts
every tracked itemset exactly each batch. It does not reproduce the paper's
Buffer/Trie/SetGen modules or SetGen's subset-pruning rule. Runtime and memory
describe this implementation. Held transactions are outside all guarantees
until processed; there is no guarantee for an arbitrary historical subrange.

## Reference

G. S. Manku and R. Motwani, "Approximate Frequency Counts over Data Streams",
Proc. 28th VLDB Conference, Hong Kong, 2002.

## Tutorial

[Executed notebook](../../../notebooks/frequentPattern/basic/LossyCounting.ipynb)

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/udayRage/streamPAMI/blob/main/notebooks/frequentPattern/basic/LossyCounting.ipynb)
