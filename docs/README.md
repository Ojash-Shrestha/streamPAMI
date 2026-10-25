# streamPAMI documentation

streamPAMI finds frequent itemsets in transaction streams, processing one batch
at a time. It follows PAMI's package layout and output methods. Choose an exact
sliding window or an approximate summary with the documented accuracy limits.

- [Getting started](gettingStarted.md): installation, inputs, common API and live streams.
- [Choosing an algorithm](choosingAnAlgorithm.md): horizons, work and memory trade-offs.
- [FPStream](frequentPattern/basic/FPStream.md): approximate tilted-time history.
- [DSTree](frequentPattern/basic/DSTree.md): exact sliding batch window.
- [LossyCounting](frequentPattern/basic/LossyCounting.md): approximate landmark counts.

Each algorithm page links to its executed notebook and Colab tutorial. Start
with the small offline examples, then use a notebook to explore the dataset.
See the [project README](../README.md) for accuracy guarantees, evaluation and references.
