"""DSTreeMaximal: streamPAMI composition, not a published algorithm.

DSTree mines the exact frequent itemsets of the queried sliding batch window.
streamPAMI's own maximality filter then keeps only itemsets with no frequent
proper superset, preserving their exact counts. The maximal step is not from
Leung and Khan's paper and must not be attributed to them.

For W transactions in the queried range, let F contain every non-empty X with
count(X) >= Fraction(str(minSup)) * W. Return M = {X in F: no Y in F has X as a
proper subset}, with counts from F. The filter marks one-item deletions of each
frequent itemset. It still materialises all of F before reducing the output.

The constructor, batch updates, frame conventions, validation, query-time minSup
and output methods are inherited from DSTree. A query changes no retained state
or captured metrics. The inherited mine() calls this query override, so its
stored result is maximal over the whole current window. Memory retains DSTree's
compressed window transactions plus the temporary frequent-set and filter state.

Underlying DSTree reference only: C. K.-S. Leung and Q. I. Khan, "DSTree: A Tree
Structure for the Mining of Frequent Sets from Data Streams", Proc. IEEE ICDM,
2006, pp. 928-932, doi:10.1109/ICDM.2006.62. This reference does not describe
streamPAMI's maximality composition.

Importing this composition into a python program::

    import pandas as pd
    from streamPAMI.frequentPattern.maximal.DSTreeMaximal import DSTreeMaximal

    source = pd.DataFrame({"Transactions": [["a", "b"], ["a", "b", "c"],
                                          ["a", "b", "c"], ["b", "d"], ["b", "d"]]})
    miner = DSTreeMaximal(source, 0.4, windowSize=1, batchSize=5)
    miner.mine()
    print(dict(sorted(miner.getPatterns().items())))
"""
from itertools import combinations

from ..basic.DSTree import DSTree


class DSTreeMaximal(DSTree):
    """streamPAMI composition, not a published algorithm: DSTree plus maximality."""

    def queryPatterns(self, startFrame=0, endFrame=None, minSup=None):
        """Return maximal counts via this streamPAMI composition, not a published algorithm."""
        frequent = DSTree.queryPatterns(self, startFrame, endFrame, minSup=minSup)
        non_maximal = set()
        # F is downward closed: a frequent proper superset exists exactly when
        # a frequent one-item extension exists. Marking each Y's immediate
        # subsets therefore marks every non-maximal X without pairwise scans.
        for pattern in frequent:
            if len(pattern) >= 2:
                non_maximal.update(combinations(pattern, len(pattern) - 1))
        return {pattern: count for pattern, count in frequent.items() if pattern not in non_maximal}
