"""INSTANT: maximal frequent itemsets over a fixed-count landmark stream.

Reference: G. Mao, X. Wu, X. Zhu, G. Chen and C. Liu, "Mining maximal frequent
itemsets from data streams", Journal of Information Science 33(3), 251-262,
2007, doi:10.1177/0165551506068179.

Correspondence with the paper (Mao et al., JIS 2007, Sec. 2-4)
----------------------------------------------------------
* The landmark window covers every transaction since the stream began. minSup
  is a fixed positive integer support COUNT delta. Fractional thresholds and
  query-time threshold changes are not supported. (MATCH, Sec. 2/Fig. 1)
* F contains maximal frequent itemsets; U holds the intermediate antichains.
  For each non-empty transaction not contained in F, Fig. 2 runs before Fig. 3,
  using the top U level as it stood before that transaction. Maintain_information
  visits every level in descending order without an early stop. (MATCH, Figs. 1-3)
* TYPO FIX 1: initialise all U[1..delta-1], including U[delta-1], rather than the
  incomplete loop bounds printed in Fig. 1.
* TYPO FIX 2: the last block of Fig. 3 inserts ALPHA into U[1], not gamma.
* EDGE CASE: for delta=1, U is empty and F is the maximal family of all non-empty
  transactions seen so far. This case is not covered by the paper.
* Empty intersections and empty transactions never become patterns. Empty
  transactions still count towards the processed stream length.
* Data shedding from Sec. 4.1 is not implemented; it was optional and unused in
  the paper's experiments. Table 1 additionally prunes lower U levels, whereas
  Figs. 2-3 do not. We follow the figures and retain those entries; this affects
  memory, not F. In particular, Table 1's extra pruning of abcd from U[1] is not
  reproduced.
* Exact supports are unknown. queryPatterns() returns sorted item tuples mapped
  to None, save() writes patterns without supports, and the DataFrame has only
  a Patterns column. No frame arguments are accepted.

Notes on the paper's theory
--------------------------
Theorem 4 calls F "a set of maximal frequent itemsets". Under Definition 3 this
states that its members are frequent and none contains another; completeness
is not proved. streamPAMI verifies completeness empirically against brute force
in tests/test_INSTANT.py. Theorem 2, which assigns support exactly i to every
member of U[i], does not hold for the pseudo-code as written: with delta=4, the
stream b, c, b, c, bc, bc, b, a leaves bc (true support 2) in U[1]. It does not
affect F.

Memory and time grow with delta, with one intermediate level per count below
it. Antichains also depend on the observed itemsets. On an endless stream more
itemsets eventually reach a fixed count; the output describes the whole history,
not recent behaviour. The stream's transactions are not retained.

Importing this algorithm into a python program::

    import pandas as pd
    from streamPAMI.frequentPattern.maximal.INSTANT import INSTANT

    source = pd.DataFrame({"Transactions": [["a", "b"], ["a", "b"], ["a", "c"]]})
    miner = INSTANT(source, minSup=2, batchSize=2)
    miner.mine()
    print(miner.getPatterns())
"""
from time import perf_counter

import pandas as pd

from ..basic.abstract import _streamFrequentPatterns


class INSTANT(_streamFrequentPatterns):
    """Maintain F and U from Figs. 1-3 with a fixed landmark support count."""

    def __init__(self, iFile, minSup, batchSize, sep="\t"):
        if not isinstance(minSup, int) or isinstance(minSup, bool) or minSup < 1:
            raise ValueError(
                "minSup must be an int >= 1. INSTANT uses a fixed count over the whole "
                "stream, so a fraction is not supported."
            )
        if not isinstance(batchSize, int) or isinstance(batchSize, bool) or batchSize < 1:
            raise ValueError("batchSize must be an integer >= 1")
        super().__init__(iFile, minSup, batchSize=batchSize, sep=sep)
        self._delta = minSup
        self._F = set()
        self._U = {level: set() for level in range(1, self._delta)}
        self._N = 0

    @staticmethod
    def _in_sub(pattern, collection):
        return any(pattern <= member for member in collection)

    def _make_frequent(self, alpha):
        # Fig. 2 reads the top U level before any Fig. 3 update.
        for beta in tuple(self._U[self._delta - 1]):
            gamma = alpha & beta
            if gamma and not self._in_sub(gamma, self._F):
                self._F.difference_update({member for member in self._F if member <= gamma})
                self._F.add(gamma)

    def _maintain_information(self, alpha):
        for level in range(self._delta - 1, 1, -1):
            if not self._in_sub(alpha, self._U[level]):
                # Descending levels preserve the source level's pre-update state.
                for beta in tuple(self._U[level - 1]):
                    gamma = alpha & beta
                    if gamma and not self._in_sub(gamma, self._U[level]):
                        self._U[level].difference_update(
                            {member for member in self._U[level] if member <= gamma})
                        self._U[level].add(gamma)
        if not self._in_sub(alpha, self._U[1]) and not self._in_sub(alpha, self._F):
            self._U[1].difference_update({member for member in self._U[1] if member <= alpha})
            self._U[1].add(alpha)

    def _process_transaction(self, alpha):
        if not alpha or self._in_sub(alpha, self._F):
            return
        if self._delta == 1:
            self._F.difference_update({member for member in self._F if member <= alpha})
            self._F.add(alpha)
            return
        self._make_frequent(alpha)
        self._maintain_information(alpha)

    def processBatch(self, transactions: list[list[str]]):
        if not isinstance(transactions, list):
            raise TypeError("transactions must be a list of transactions")
        if not transactions:
            raise ValueError("a batch must contain at least one transaction")
        started = perf_counter()
        clean = [frozenset(map(str, transaction)) for transaction in transactions]
        for alpha in clean:
            self._N += 1
            self._process_transaction(alpha)
        self._capture_metrics(started)

    def queryPatterns(self):
        patterns = sorted(tuple(sorted(pattern)) for pattern in self._F)
        return {pattern: None for pattern in patterns}

    def getStreamLength(self):
        return self._N

    def save(self, oFile):
        with open(oFile, "w", encoding="utf-8") as output:
            for pattern in self._patterns:
                output.write(self.sep.join(pattern) + "\n")

    def getPatternsAsDataFrame(self):
        return pd.DataFrame([(self.sep.join(pattern),) for pattern in self._patterns], columns=["Patterns"])

    def mine(self):
        started = perf_counter()
        self._F.clear()
        self._U = {level: set() for level in range(1, self._delta)}
        self._N = 0
        self._patterns = {}
        batch = []
        for transaction in self._iter_transactions():
            batch.append(transaction)
            if len(batch) == self.batchSize:
                self.processBatch(batch)
                batch = []
        if batch:
            self.processBatch(batch)
        self._patterns = self.queryPatterns()
        self._capture_metrics(started)
        return self
