# INSTANT

## Overview

INSTANT maintains maximal frequent itemsets over a landmark stream: every
transaction since the stream began. Its threshold is a fixed support **count**,
not a fraction. It returns itemsets as soon as they become frequent, but does
not know their exact supports, so each output value is `None`.

## When to use it / when not to

Use INSTANT when a fixed occurrence count over the whole history is meaningful
and you want maximal itemsets without running a separate mining query. A
maximal itemset has no frequent proper superset; counts of its frequent subsets
are not returned either.

Prefer [DSTreeMaximal](DSTreeMaximal.md) when you need recent batches, fractional
minSup, frame-range queries or exact counts. That class is streamPAMI's own
composition of DSTree and a maximality filter, not a published maximal mining
algorithm. INSTANT follows Mao et al.'s published algorithm. Do not use INSTANT
to describe recent behaviour: its landmark window never forgets older data.

## Parameters

`INSTANT(iFile, minSup, batchSize, sep="\t")`

| Name | Type | Meaning | Constraints |
|---|---|---|---|
| `iFile` | path, URL string, DataFrame or `None` | Replay input, or feed live batches with `None`. | DataFrame column must be `Transactions`; a missing file raises. |
| `minSup` | int | Fixed support count delta over the whole stream. | At least one; floats (including `3.0`), booleans, strings, zero and negative values are rejected. A fraction is not supported. |
| `batchSize` | int | Transactions per replay batch. | At least one; booleans are rejected. The final smaller batch is processed. |
| `sep` | str | Input/output item separator. | Default tab. |

Direct `processBatch` calls accept a non-empty list of transactions of any
positive length and process them in arrival order. Repeated items within a
transaction count once. Empty transactions count towards stream length but
otherwise leave the algorithm's state unchanged. Blank file and URL lines are
skipped, as in the other frequent-pattern miners.

## Algorithm-specific methods

| Method | Meaning |
|---|---|
| `queryPatterns()` | Current maximal frequent itemsets over the whole landmark stream, as sorted item tuples mapped to `None`. Accepts no frame arguments or threshold override. |
| `getStreamLength()` | Number of transactions processed, including empty transactions. |

`mine()` resets the stream, replays the input and stores its final
`queryPatterns()` result. As with the other miners, `getPatterns()`, `save()`
and `getPatternsAsDataFrame()` use the last `mine()` result; live users should
read the dictionary returned by `queryPatterns()`.

The output format reflects the unknown supports: `save()` writes one pattern
per line, items joined by `sep`, with no `:support` suffix.
`getPatternsAsDataFrame()` has the single column `Patterns`. The runtime,
memory, `printResults()` and deprecated `startMine()` methods work as usual.

## Example

This is the transaction sequence from the paper's Table 1, with delta=3.
Each transaction is fed as a batch to show every change in F. The same inline
DataFrame is then replayed with `mine()` in batches of three.

```python
import pandas as pd
from streamPAMI.frequentPattern.maximal.INSTANT import INSTANT

df = pd.DataFrame({"Transactions": [list(tx) for tx in
    ("abc", "acd", "abcd", "abd", "abcd", "acd", "abcde", "abcefhl")]})
miner = INSTANT(None, minSup=3, batchSize=3)
for index, transaction in enumerate(df["Transactions"], 1):
    miner.processBatch([transaction])
    print(f"After transaction {index}:", miner.queryPatterns())
print("Processed transactions:", miner.getStreamLength())
replayed = INSTANT(df, minSup=3, batchSize=3).mine()
print("Replay result:", replayed.getPatterns())
```

```text
After transaction 1: {}
After transaction 2: {}
After transaction 3: {('a', 'c'): None}
After transaction 4: {('a', 'b'): None, ('a', 'c'): None, ('a', 'd'): None}
After transaction 5: {('a', 'b', 'c'): None, ('a', 'b', 'd'): None, ('a', 'c', 'd'): None}
After transaction 6: {('a', 'b', 'c'): None, ('a', 'b', 'd'): None, ('a', 'c', 'd'): None}
After transaction 7: {('a', 'b', 'c', 'd'): None}
After transaction 8: {('a', 'b', 'c', 'd'): None}
Processed transactions: 8
Replay result: {('a', 'b', 'c', 'd'): None}
```

The `None` values mean that support counts are unknown, not zero. The output
contains only maximal frequent itemsets, so earlier frequent subsets can
disappear from F when a larger itemset becomes frequent.

## Accuracy guarantees and limitations

An output itemset is frequent when its support is at least the fixed count
delta, inclusively. F is maintained as an antichain: no member contains another.
streamPAMI checks that F contains **all** maximal frequent itemsets against an
independent brute-force oracle after every batch on uniform and correlated
streams (`tests/test_INSTANT.py`). Exact support counts are not maintained.

The implementation follows Figs. 1-3, with Fig. 2 using the top U level from
before the transaction, followed by Fig. 3's descending updates. Each level is
checked; finding the transaction at one level does not stop the loop. It makes
these fixes and edge cases explicit:

- **Typo fix 1:** initialise every U level from 1 through delta-1, including
  the top level omitted by Fig. 1's printed loop bounds.
- **Typo fix 2:** insert alpha into U[1] in Fig. 3's last block, not gamma.
- **delta=1:** U is empty; every non-empty transaction is frequent, and F keeps
  only maximal transactions. The paper does not cover this edge case.
- Empty intersections are ignored; the empty set is never a pattern.
- Optional data shedding (Sec. 4.1), unused in the paper's experiments, is not
  implemented.
- Table 1 (Sec. 4.2) additionally removes entries from lower U levels once they
  become frequent, including abcd from U[1]. Figs. 2-3 do not. This implementation
  follows the figures; the retained entries affect memory, not F.

**Notes on the paper's theory.** Theorem 4 calls F "a set of maximal frequent
itemsets". Under Definition 3 this states that its members are frequent and
none contains another; completeness is not proved. The brute-force checks
provide empirical verification of completeness, not a proof.

Theorem 2 states that every itemset in U[i] has support exactly i. This does
not hold for the pseudo-code as written: the stream b, c, b, c, bc, bc, b, a
with delta=4 leaves bc in U[1], although its true support is two. This does
not affect F and is recorded as a regression test.

Memory and time grow with delta because there is one U level per count below
it, and the sizes of the intermediate antichains also depend on the observed
itemsets. Raw transactions are not retained. On an endless stream, more
itemsets eventually reach a fixed count: the result describes the whole
history, not the current rate of occurrence.

## Reference

G. Mao, X. Wu, X. Zhu, G. Chen and C. Liu, "Mining maximal frequent itemsets from
data streams", Journal of Information Science 33(3), 251-262, 2007,
[doi:10.1177/0165551506068179](https://doi.org/10.1177/0165551506068179).

## Tutorial

The offline Table 1 example above is the tutorial for INSTANT; no separate
notebook is provided. See [getting started](../../gettingStarted.md) for inputs
and the common methods, with INSTANT's fixed-count and unknown-support exceptions.
