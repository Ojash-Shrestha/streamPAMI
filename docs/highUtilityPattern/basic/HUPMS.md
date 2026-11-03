# HUPMS

## Overview

HUPMS finds exact high-utility itemsets over a sliding window of batches.
Utility is an item's quantity multiplied by its unit profit, supplied directly
in the input. This is a different question from how often an itemset occurs.

## When to use it / when not to

Use it when positive item utilities matter and you need exact results over a
recent window or a contiguous range within it. The threshold can change for
each query without replaying the stream. Do not use it for negative utilities,
frequency thresholds or queries over batches that have left the window.

## Parameters

`HUPMS(iFile, minUtil, windowSize, batchSize, sep="\t")`

| Name | Type | Meaning | Constraints |
|---|---|---|---|
| `iFile` | path, URL string, DataFrame or `None` | Replay utility transactions, or feed live batches when `None`. | DataFrames need `Transactions` and `Utilities` columns, with lists in both. Missing files raise. |
| `minUtil` | float | Fraction of the queried period's total transaction utility. | Strictly between zero and one; booleans, strings, NaN and infinity are rejected. |
| `windowSize` | int | Maximum number of batches retained. | At least one; booleans are rejected. |
| `batchSize` | int | Transactions per replay batch. | At least one; booleans are rejected. A final smaller batch is processed. |
| `sep` | str | Separator between items and between item utilities. | Default tab; also used when saving patterns. |

File and URL lines use `items:transactionUtility:itemUtilities`, for example
`a<tab>b:11:6<tab>5`. Transaction utility must equal the sum of the item utilities.
Counts must match, items cannot repeat and item utilities must be positive;
invalid lines raise `ValueError` naming the physical line number. Blank lines
are skipped. Utilities are parsed exactly from their numeric strings.

`processBatch` takes a non-empty list of dictionaries, such as `{"a": 6, "b": 5}`.
Values may be integers, floats or numeric strings, and must be positive. An
empty dictionary is a transaction with zero utility. Each call defines one
batch, independent of `batchSize`. The oldest batch leaves before a new batch
is inserted when the window is full.

## Algorithm-specific methods

| Method | Meaning |
|---|---|
| `getTimeFrames()` | Retained `(startBatch, endBatch)` boundaries, newest first; ends are exclusive and batch indices refer to the original stream. |
| `getFrameWeights()` | Total transaction utility of each retained batch, newest first; these are utility totals, not transaction counts. |
| `queryPatterns(startFrame=0, endFrame=None, minUtil=None)` | Query frame indices from startFrame inclusive to endFrame exclusive; endFrame=None extends to the oldest frame. minUtil=None uses the constructor value; a valid override affects only this query. |

Queries leave the tree, retained transactions, constructor threshold, stored
patterns and captured metrics unchanged. `mine()` stores the whole current
window's result at the constructor threshold; `getPatterns()` returns that
stored result. After a live update, use `queryPatterns()` for the current answer.

Keys are sorted tuples of item strings. Reported pattern utilities and frame
weights are integers when integral and floats otherwise. Internally, all utility
arithmetic and threshold comparisons use Fraction. `getPatternsAsDataFrame()`
has `Patterns` and `Utility` columns; `save()` writes `item1<sep>item2:utility`.
The runtime, memory, printing and deprecated `startMine()` methods follow the
[common API](../../gettingStarted.md#common-api).

## Example

This reproduces the paper's Fig. 2 stream. Quantities are converted to per-item
utilities before input. After mining the first window, the next batch slides
the same miner to the second window.

```python
import pandas as pd
from streamPAMI.highUtilityPattern.basic.HUPMS import HUPMS

profits = {"a": 2, "b": 6, "c": 3, "d": 8, "e": 10}
quantities = [{"d": 3, "e": 4}, {"a": 2, "c": 8}, {"b": 2, "c": 8, "d": 2},
              {"a": 4, "b": 8}, {"b": 3, "e": 2}, {"a": 6, "b": 5, "d": 4},
              {"a": 2, "b": 2, "c": 7}, {"a": 4, "b": 4, "d": 5, "e": 3}]
df = pd.DataFrame({
    "Transactions": [list(transaction) for transaction in quantities],
    "Utilities": [[quantity * profits[item] for item, quantity in transaction.items()]
                  for transaction in quantities],
})
miner = HUPMS(df.iloc[:6], minUtil=0.3, windowSize=3, batchSize=2).mine()
print("W1 total utility:", sum(miner.getFrameWeights()))
print("W1 patterns:", dict(sorted(miner.getPatterns().items())))
batch = [dict(zip(items, values)) for items, values
         in zip(df["Transactions"].iloc[6:], df["Utilities"].iloc[6:])]
miner.processBatch(batch)
print("W2 total utility:", sum(miner.getFrameWeights()))
print("W2 patterns:", dict(sorted(miner.queryPatterns().items())))
print("Frames:", miner.getTimeFrames())
print("Frame utilities:", miner.getFrameWeights())
```

```text
W1 total utility: 312
W1 patterns: {('a', 'b'): 98, ('b',): 108}
W2 total utility: 359
W2 patterns: {('a', 'b'): 146, ('a', 'b', 'd'): 146, ('b',): 144, ('b', 'd'): 154}
Frames: [(3, 4), (2, 3), (1, 2)]
Frame utilities: [139, 112, 108]
```

The two windows match the paper's W1 and W2. After `processBatch`, the stored
`getPatterns()` answer still belongs to the last `mine()`; the current answer
comes from `queryPatterns()`.

## Accuracy guarantees and limitations

For queried batches R, the threshold is `Fraction(str(minUtil))` multiplied by
the sum of the transaction utilities in R. Each returned non-empty itemset has
exact utility at or above that inclusive threshold, with no false positives or
false negatives. A range with no batches or total utility zero returns `{}`.
Only the final public number conversion may round a non-integral utility to a
float; the mining decisions use exact fractions.

Phase one grows candidates whose transaction-weighted utility (TWU) reaches the
threshold. TWU is an upper bound on itemset utility and is anti-monotone for
positive utilities; actual itemset utility cannot safely prune this growth.
Phase two intersects per-item transaction-ID sets and sums only the candidate's
own item utilities in matching transactions.

The HUS-tree has a fixed lexicographic order and per-batch TWU slots ordered
oldest first. Sliding visits every node, drops its oldest slot and removes
all-zero item nodes eagerly. The structural root remains even for a zero-utility
window. Public frame indices are newest first.

**Storage choice:** we retain each batch's item-to-utility transactions for the
second phase. The paper specifies a second scan without specifying that storage.
Memory grows with these window transactions and the per-node batch vectors;
queries also create temporary conditional trees and transaction-ID sets.

**Deviation:** earlier candidate sets are not reused when the threshold changes;
every query mines afresh. Results are identical, but speed can differ.
**Extension:** contiguous sub-range queries are provided by streamPAMI; the paper
queries the whole sliding window. Negative utilities are not supported.

## Reference

C. F. Ahmed, S. K. Tanbeer, B.-S. Jeong and H.-J. Choi, "Interactive mining of high
utility patterns over data streams", Expert Systems with Applications 39(15),
11979-11991, 2012, doi:10.1016/j.eswa.2012.03.062.

## Tutorial

The offline example above is the HUPMS tutorial; no notebook is added for this
algorithm. See the [documentation index](../../README.md) for the other miners.
