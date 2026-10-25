# FPStream

## Overview

FPStream keeps approximate itemset counts over a stream. Recent batches occupy
fine time frames and older batches merge into coarser frames. You can query a
period made of complete frames.

## When to use it / when not to

Use it for approximate history at several time granularities. For guaranteed
queries, start at the newest frame and choose `minSup > 2*epsilon`. Do not use it
when you need exact counts or guaranteed results for an older-only period.

## Parameters

`FPStream(iFile, minSup, epsilon, batchSize, sep="\t")`

| Name | Type | Meaning | Constraints |
|---|---|---|---|
| `iFile` | path, URL string, DataFrame or `None` | Replay input, or live input when `None`. | DataFrame column must be `Transactions`; a missing file raises. |
| `minSup` | float | Minimum relative support, sigma. | `0 < minSup < 1`; an absolute count is not accepted. |
| `epsilon` | float | Support error parameter. | `0 < epsilon < minSup`; `epsilon >= minSup/2` emits `UserWarning`, without rejecting the parameters. |
| `batchSize` | int | Transactions per replay batch. | Positive; a final smaller batch is processed. Direct batches can have other positive lengths. |
| `sep` | str | Input/output item separator. | Default tab. |

Thresholds use exact decimal Fraction arithmetic internally. Parameters are set
at construction; there is no minSup argument on a query.

## Algorithm-specific methods

| Method | Meaning |
|---|---|
| `getTimeFrames()` | Batch boundaries `(startBatch, endBatch)`, newest frame first; batch ends are exclusive. Batch indices start at zero. |
| `getFrameWeights()` | Transaction counts in those frames, in the same order. |
| `queryPatterns(startFrame=0, endFrame=None)` | Query frame indices from startFrame inclusive to endFrame exclusive; `None` includes the oldest remaining frame. |

`queryPatterns(0, 1)` covers the newest frame; `queryPatterns()` covers the whole
stream. A frame may cover several batches. Choose indices from the current
`getTimeFrames()` result; there is no query for a fraction of a frame.

## Example

```python
import pandas as pd
from streamPAMI.frequentPattern.basic.FPStream import FPStream

df = pd.DataFrame({"Transactions": [["a", "b"], ["a"], ["b"], [],
                                  ["a", "b"], ["b"]]})
miner = FPStream(df, minSup=0.4, epsilon=0.05, batchSize=2)
miner.mine()
print("Whole stream:", dict(sorted(miner.getPatterns().items())))
print("Frames:", miner.getTimeFrames())
print("Frame weights:", miner.getFrameWeights())
print("Newest frame:", dict(sorted(miner.queryPatterns(0, 1).items())))
```

```text
Whole stream: {('a',): 3, ('b',): 4}
Frames: [(2, 3), (0, 2)]
Frame weights: [2, 4]
Newest frame: {('a',): 1, ('a', 'b'): 1, ('b',): 2}
```


## Accuracy guarantees and limitations

The guarantee holds only when **sigma > 2*epsilon** and the queried period
**starts at the newest frame**. For such a period with W transactions and an
itemset's true count f, every itemset with `f >= sigma*W` is returned, and every
returned estimate is in `[f - epsilon*W, f]`. Extra candidates below minSup may
be returned because the inclusive query threshold is `(sigma - epsilon)*W`.

With `epsilon >= minSup/2`, false negatives are possible. For periods starting
at an older frame, uneven batch sizes can also cause false negatives; this is a
known limitation recorded by a strict expected-failure test. Do not extend the
newest-frame guarantee to those periods.

Tail pruning uses the strict sigma and prefix-sum epsilon conditions from
Section 3.5. New-pattern insertion is strict; query output is inclusive. Memory
depends on retained patterns and their logarithmic frame tables, rather than
retaining the raw stream.

## Reference

C. Giannella, J. Han, J. Pei, X. Yan and P. S. Yu, "Mining Frequent Patterns in Data
Streams at Multiple Time Granularities", *Next Generation Data Mining*, 2003.
[PDF](https://www2.cs.sfu.ca/~jpei/publications/fpstm03.pdf)

## Tutorial

[Executed notebook](../../../notebooks/frequentPattern/basic/FPStream.ipynb)

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/udayRage/streamPAMI/blob/main/notebooks/frequentPattern/basic/FPStream.ipynb)
