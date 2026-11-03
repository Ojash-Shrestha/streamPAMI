# streamPAMI documentation

streamPAMI finds frequent and high-utility itemsets in transaction streams,
processing one batch at a time. It follows PAMI's package layout and output
methods. Choose an exact sliding window or an approximate frequency summary
with the documented accuracy limits.

- [Getting started](gettingStarted.md): installation, inputs, common API and live streams.
- [Choosing an algorithm](choosingAnAlgorithm.md): horizons, work and memory trade-offs.
- [FPStream](frequentPattern/basic/FPStream.md): approximate tilted-time history.
- [DSTree](frequentPattern/basic/DSTree.md): exact sliding batch window.
- [DSTreeMaximal](frequentPattern/maximal/DSTreeMaximal.md): streamPAMI composition, not a published algorithm; exact maximal itemsets over DSTree's sliding window.
- [INSTANT](frequentPattern/maximal/INSTANT.md): maximal itemsets over a landmark stream with a fixed support count; exact supports are unknown.
- [LossyCounting](frequentPattern/basic/LossyCounting.md): approximate landmark counts.
- [HUPMS](highUtilityPattern/basic/HUPMS.md): exact high-utility patterns in a sliding window, using positive per-item utilities.

The basic frequent-pattern pages link to executed notebooks and Colab tutorials.
HUPMS, INSTANT and the DSTreeMaximal composition have offline example tutorials
on their pages. Start with the small offline examples, then use a frequency notebook to
explore the dataset.
See the [project README](../README.md) for accuracy guarantees, evaluation and references.
