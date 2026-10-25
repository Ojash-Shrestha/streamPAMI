# Choosing an algorithm

All three miners accept relative support thresholds and return counts. Their
query horizons and retained state differ. See [getting started](gettingStarted.md)
for the shared API; constructor thresholds are fixed for a miner's run.

| Question | FPStream | DSTree | LossyCounting |
|---|---|---|---|
| Window | Tilted-time frames: older batches merge into coarser frames. | Sliding window of the last `windowSize` batches. | Landmark window: all processed transactions since the start. |
| Exact or approximate? | Approximate, subject to the conditions below. | Exact over any contiguous batch range in the window. | Approximate over the processed landmark stream. |
| What is stored? | Retained itemsets and pruned per-frame support tables. | Window transactions in a canonical prefix tree, with per-batch node counts. | Itemset counts and error bounds in a dictionary; temporary batch FP-tree and item occurrence sets. |
| Memory behaviour | Depends on retained itemsets and logarithmic frame history; tighter error can retain more. | Grows with window transactions, prefix sharing and per-node batch counts. | Depends on retained itemsets, batch size and the held suffix; this is not the paper's Trie/SetGen layout. |
| When does mining work happen? | FP-growth during batch updates; queries sum retained tables. | Updates maintain the tree; FP-growth runs only when queried. | FP-growth and exact tracked-itemset counting during updates; queries filter stored counts. |
| Can minSup change at query time? | No query parameter; construct a new miner and replay. | No query parameter; construct a new miner and replay. | No query parameter; construct a new miner and replay. |
| Main weakness | Guaranteed recall requires `minSup > 2*epsilon` and a period starting at the newest frame; older periods have a known limitation. | Retains the current window's compressed transactions; repeated queries repeat mining work. | No historical subrange queries; batches must contain whole buckets and trailing input may be held. |

## Use FPStream when

- You want approximate history at several time granularities.
- Your guaranteed queries start at the newest frame and satisfy `minSup > 2*epsilon`.
- You accept that pruning can discard old detail. Do not use it for exact answers
  or assume the same guarantee for an older-only frame range.

See [FPStream](frequentPattern/basic/FPStream.md).

## Use DSTree when

- You need exact results over recent batches or any contiguous range within them.
- You can retain the window's transactions in compressed form.
- Mining on demand fits your query rate. Do not choose it expecting an
  epsilon-controlled summary or queries over batches that have left the window.

This is an eager-maintenance variant; its update costs and memory describe this
implementation, not necessarily the original paper's design. See [DSTree](frequentPattern/basic/DSTree.md).

## Use LossyCounting when

- You want approximate counts from the start of the processed stream.
- Your batch lengths can be positive multiples of `ceil(1/epsilon)`.
- You accept extra candidates below minSup and an unprocessed incomplete bucket.
  Do not use it for a sliding horizon or frame-range queries.

See [LossyCounting](frequentPattern/basic/LossyCounting.md).
