# DSTreeMaximal

**streamPAMI composition, not a published algorithm.**

## Overview

DSTreeMaximal combines DSTree's exact frequent-itemset query with streamPAMI's
own maximality filter. Leung and Khan are credited for the underlying DSTree;
the maximal step is streamPAMI's composition and is not attributed to them.

For a queried batch range R with W transactions and the effective minSup:

- F contains every non-empty X with `count_R(X) >= Fraction(str(minSup)) * W`,
  exactly as returned by DSTree.
- M contains each X in F for which no Y in F is a proper superset of X.
- The output maps each X in M to its exact `count_R(X)`.

## When to use it / when not to

Use this composition for a compact summary of which frequent itemsets can no
longer be extended while remaining frequent. Counts of non-maximal frequent
subsets are not returned. Choose plain DSTree when you need every frequent
itemset's count; maximal output does not preserve those counts.

This composition first mines all frequent itemsets and then filters them. A
smaller output does not imply less mining work or a smaller retained tree.
It cannot query batches that have left the sliding window.

## Parameters

`DSTreeMaximal(iFile, minSup, windowSize, batchSize, sep="\t")`

All constructor validation and input handling are inherited unchanged from DSTree.

| Name | Type | Meaning | Constraints |
|---|---|---|---|
| `iFile` | path, URL string, DataFrame or `None` | Replay input, or feed live batches with `None`. | DataFrame column must be `Transactions`; a missing file raises. |
| `minSup` | float | Default relative support within the queried batch range. | `0 < minSup < 1`; absolute counts, booleans, strings, NaN and infinity are rejected. |
| `windowSize` | int | Maximum number of batches retained. | At least one; booleans are rejected. |
| `batchSize` | int | Transactions per replay batch. | At least one; booleans are rejected. A final smaller batch counts as one batch. |
| `sep` | str | Input/output item separator. | Default tab. |

Each `processBatch` call adds one batch of any positive length. When the window
is full, the oldest batch leaves first. Blank file and URL lines are skipped;
empty transactions supplied directly or in a DataFrame count towards W.

## Algorithm-specific methods

| Method | Meaning |
|---|---|
| `getTimeFrames()` | Inherited batch boundaries `(startBatch, endBatch)`, newest first; ends are exclusive and indices refer to the original stream. |
| `getFrameWeights()` | Inherited transaction counts for those frames, newest first. |
| `queryPatterns(startFrame=0, endFrame=None, minSup=None)` | Exact maximal itemsets over frame indices from startFrame inclusive to endFrame exclusive. endFrame=None extends to the oldest retained frame; minSup=None uses the constructor threshold. |

The override delegates the same arguments to DSTree and then applies
streamPAMI's maximality filter. Query-time minSup affects only that query;
stored patterns, constructor minSup, metrics and the tree remain unchanged.

The inherited `mine()` calls this override and stores maximal patterns over the
whole current window. `getPatternsAsDataFrame()` has `Patterns` and `Support`
columns; `save()` writes `item1<sep>item2:support`. As with DSTree, use
`queryPatterns()` for a live answer and `getPatterns()` for the last `mine()` result.

## Example

The batch is ab, abc, abc, bd, bd. This runs plain DSTree for comparison, then
the streamPAMI composition on the same inline DataFrame.

```python
import pandas as pd
from streamPAMI.frequentPattern.basic.DSTree import DSTree
from streamPAMI.frequentPattern.maximal.DSTreeMaximal import DSTreeMaximal

df = pd.DataFrame({"Transactions": [["a", "b"], ["a", "b", "c"],
                                  ["a", "b", "c"], ["b", "d"], ["b", "d"]]})
plain = DSTree(df, minSup=0.4, windowSize=1, batchSize=5).mine()
maximal = DSTreeMaximal(df, minSup=0.4, windowSize=1, batchSize=5).mine()
print("Frequent patterns:", dict(sorted(plain.getPatterns().items())))
print("Maximal patterns:", dict(sorted(maximal.getPatterns().items())))
```

```text
Frequent patterns: {('a',): 3, ('a', 'b'): 3, ('a', 'b', 'c'): 2, ('a', 'c'): 2, ('b',): 5, ('b', 'c'): 2, ('b', 'd'): 2, ('c',): 2, ('d',): 2}
Maximal patterns: {('a', 'b', 'c'): 2, ('b', 'd'): 2}
```

The frequent pair ab has count three, while abc has count two. ab is still
not maximal because abc is a frequent proper superset. Equal counts are not
required: a closed-itemset filter would answer a different question.

## Accuracy guarantees and limitations

Counts and maximality are exact over any contiguous batch range retained in the
window, using DSTree's inclusive Fraction threshold. Empty periods and queries
with no frequent itemsets return `{}`. A frequent singleton with no frequent
superset is maximal.

F is downward closed. If X has any frequent proper superset, it also has a
frequent one-item extension. The filter therefore marks the immediate subsets
of every frequent Y, avoiding pairwise comparisons across F. Counts are passed
through unchanged, regardless of whether subset and superset counts match.

The underlying eager-maintenance DSTree retains the window's transactions,
compressed by shared prefixes, with per-batch node counts. The query also
materialises the full frequent family F and its non-maximal markers. Memory
grows with the window and these intermediate query results. Returning only M
does not return the counts of non-maximal frequent subsets.

This is streamPAMI's own composition, not a published maximal mining algorithm.

## Reference

Underlying DSTree only: C. K.-S. Leung and Q. I. Khan, "DSTree: A Tree Structure
for the Mining of Frequent Sets from Data Streams", Proc. IEEE ICDM, 2006,
pp. 928-932, doi:10.1109/ICDM.2006.62.

This reference supports DSTree, not streamPAMI's maximality step. The latter is
a streamPAMI composition, not a published algorithm.

## Tutorial

The offline example above is the tutorial for this composition; no separate
notebook is added. [INSTANT](INSTANT.md) (Mao et al., 2007) is a separate published
landmark-window algorithm with a fixed integer support count and unknown exact
supports. It is not implemented by DSTreeMaximal.
