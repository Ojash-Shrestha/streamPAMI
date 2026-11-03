"""HUPMS: exact high-utility patterns over a sliding window of batches.

Reference: C. F. Ahmed, S. K. Tanbeer, B.-S. Jeong and H.-J. Choi, "Interactive
mining of high utility patterns over data streams", Expert Systems with
Applications 39(15), 11979-11991, 2012, doi:10.1016/j.eswa.2012.03.062.

Correspondence with the paper (Ahmed et al., ESWA 2012, Sec. 3)
------------------------------------------------------------
* Inputs give positive per-item utilities u(i, T) directly, rather than quantities
  and unit profits. (MATCH, Def. 3) Empty transactions have utility zero.
* tu(T) sums all item utilities in T. (MATCH, Def. 6) An itemset's utility sums
  its own item utilities over containing transactions. (MATCH, Def. 11-12)
* minUtil is a fraction of the queried window's total transaction utility.
  (MATCH, Def. 13) Output includes utility equal to the threshold. (MATCH, Def. 14)
* TWU sums transaction utilities over containing transactions. (MATCH, Def. 15-16)
  Candidates have TWU >= threshold. (MATCH, Def. 17) Positive utilities ensure
  anti-monotone TWU and itemset utility <= TWU. (MATCH, Lemmas 1-2)
* The lexicographic HUS-tree keeps per-batch prefix TWU, OLDEST batch first.
  Sliding traverses every node, drops its oldest slot and eagerly removes zero
  item nodes. (MATCH, Sec. 3.2/Fig. 6) The root is a structural sentinel.
* Queries grow candidates by conditional TWU, then calculate their exact utility
  in a second phase using transaction-ID intersections. (MATCH, Sec. 3.3)
* Retaining each batch's item-to-utility transactions for the second scan is
  UNSPECIFIED in the paper; it is our storage choice. Both these transactions
  and per-node batch vectors use memory that grows with the window.
* Queries mine afresh, including after a threshold change; earlier candidate
  sets are not reused. Results agree, but speed can differ. (DEVIATION, Sec. 3.4)
* Contiguous sub-range queries are a streamPAMI EXTENSION; the paper queries
  the whole sliding window. Public frames and query indices are NEWEST first,
  with end-exclusive boundaries. A query changes no retained state or metrics.
* Utilities must be positive. All utility arithmetic and threshold comparisons
  use Fraction, including decimal input parsed from strings. Returned pattern
  utilities and frame weights are int if integral, otherwise float.

The threshold is Fraction(str(minUtil)) times the total utility of the selected
batches. Every returned itemset has its exact utility at or above that inclusive
threshold; a zero-utility or empty period returns no patterns. minUtil=None on
a query uses the constructor value. mine() stores the whole current window's
answer with that default. Blank file and URL lines are skipped.

Importing this algorithm into a python program::

    import pandas as pd
    from streamPAMI.highUtilityPattern.basic.HUPMS import HUPMS

    source = pd.DataFrame({"Transactions": [["a", "b"], ["a"]],
                           "Utilities": [[2, 3], [1]]})
    miner = HUPMS(source, 0.5, windowSize=2, batchSize=1)
    miner.mine()
    print(miner.getPatterns())
"""
from __future__ import annotations

from collections import defaultdict, deque
from fractions import Fraction
from time import perf_counter

from .abstract import _streamUtilityPatterns


class _HUSNode:
    """A canonical transaction prefix with one TWU slot per retained batch."""

    __slots__ = ("item", "parent", "children", "twu")

    def __init__(self, item, parent, slots):
        self.item, self.parent = item, parent
        self.children = {}
        self.twu = [Fraction(0)] * slots


class HUPMS(_streamUtilityPatterns):
    """Maintain an exact HUS-tree and retained transactions for a batch window."""

    def __init__(self, iFile, minUtil, windowSize, batchSize, sep="\t"):
        minimum = self._validate_min_util(minUtil)
        for name, value in (("windowSize", windowSize), ("batchSize", batchSize)):
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{name} must be an integer >= 1")
        super().__init__(iFile, float(minUtil), windowSize, batchSize, sep)
        self._min_util = minimum
        self._root = _HUSNode(None, None, 0)
        self._batches = deque()  # (global index, total utility, transactions), oldest first.
        self._batch_count = 0

    @staticmethod
    def _reported(utility):
        return utility.numerator if utility.denominator == 1 else float(utility)

    def _nodes(self):
        pending = [self._root]
        while pending:
            node = pending.pop()
            yield node
            pending.extend(node.children.values())

    def _expire_oldest_batch(self):
        self._batches.popleft()
        pending = [self._root]
        while pending:
            node = pending.pop()
            # Capture descendants before deleting a zero prefix: every node
            # still has its oldest slot dropped during this eager traversal.
            pending.extend(node.children.values())
            node.twu.pop(0)
            if node is not self._root and not any(node.twu):
                del node.parent.children[node.item]

    def _insert_transactions(self, transactions):
        for transaction in transactions:
            total = sum(transaction.values(), Fraction(0))
            node = self._root
            for item in sorted(transaction):
                child = node.children.get(item)
                if child is None:
                    child = node.children[item] = _HUSNode(item, node, len(self._batches))
                child.twu[-1] += total
                node = child

    def processBatch(self, transactions: list[dict]):
        if not isinstance(transactions, list):
            raise TypeError("transactions must be a list of dictionaries")
        if not transactions:
            raise ValueError("a batch must contain at least one transaction")
        started = perf_counter()
        clean = []
        for index, transaction in enumerate(transactions, 1):
            if not isinstance(transaction, dict):
                raise TypeError(f"transaction {index} must be a dictionary")
            clean.append(self._pair_transaction(list(transaction), list(transaction.values()),
                                                f"transaction {index}"))
        if len(self._batches) >= self.windowSize:
            self._expire_oldest_batch()
        for node in self._nodes():
            node.twu.append(Fraction(0))
        weight = sum((sum(transaction.values(), Fraction(0)) for transaction in clean), Fraction(0))
        self._batches.append((self._batch_count, weight, clean))
        self._root.twu[-1] = weight
        self._insert_transactions(clean)
        self._batch_count += 1
        self._capture_metrics(started)

    def getTimeFrames(self):
        return [(index, index + 1) for index, _, _ in reversed(self._batches)]

    def getFrameWeights(self):
        return [self._reported(weight) for _, weight, _ in reversed(self._batches)]

    def _transactions_in_range(self, startFrame, endFrame):
        count = len(self._batches)
        return [transaction for _, _, batch in list(self._batches)[count - endFrame:count - startFrame]
                for transaction in batch]

    @staticmethod
    def _conditional_headers(paths, threshold):
        totals = defaultdict(Fraction)
        for path, weight in paths:
            for item in path:
                totals[item] += weight
        root = _HUSNode(None, None, 1)
        headers = {item: [] for item, weight in totals.items() if weight >= threshold}
        for path, weight in paths:
            node = root
            root.twu[0] += weight
            for item in path:
                if item not in headers:
                    continue
                child = node.children.get(item)
                if child is None:
                    child = node.children[item] = _HUSNode(item, node, 1)
                    headers[item].append(child)
                child.twu[0] += weight
                node = child
        return {item: [(node, node.twu[0]) for node in nodes] for item, nodes in headers.items()}

    def _candidate_patterns(self, startFrame, endFrame, threshold):
        """Return every phase-one candidate and its exact queried-range TWU."""
        count = len(self._batches)
        slots = slice(count - endFrame, count - startFrame)
        headers = {}
        for node in self._nodes():
            if node is self._root:
                continue
            weight = sum(node.twu[slots], Fraction(0))
            if weight:
                headers.setdefault(node.item, []).append((node, weight))
        candidates = {}

        def grow(current_headers, suffix):
            for item in sorted(current_headers, reverse=True):
                links = current_headers[item]
                pattern = tuple(sorted(suffix + (item,)))
                twu = sum((weight for _, weight in links), Fraction(0))
                if twu >= threshold:
                    candidates[pattern] = twu
                    paths = []
                    for node, weight in links:
                        path, parent = [], node.parent
                        while parent is not None and parent.item is not None:
                            path.append(parent.item)
                            parent = parent.parent
                        if path:
                            paths.append((list(reversed(path)), weight))
                    conditional = self._conditional_headers(paths, threshold)
                    if conditional:
                        grow(conditional, suffix + (item,))

        grow(headers, ())
        return candidates

    @staticmethod
    def _exact_utilities(candidates, transactions):
        postings = {}
        for index, transaction in enumerate(transactions):
            for item in transaction:
                postings.setdefault(item, set()).add(index)
        utilities = {}
        for pattern in candidates:
            matching = set(postings.get(pattern[0], ()))
            for item in pattern[1:]:
                matching.intersection_update(postings.get(item, ()))
            utilities[pattern] = sum((sum((transactions[index][item] for item in pattern), Fraction(0))
                                      for index in matching), Fraction(0))
        return utilities

    def queryPatterns(self, startFrame=0, endFrame=None, minUtil=None):
        count = len(self._batches)
        if endFrame is None:
            endFrame = count
        if (any(not isinstance(index, int) or isinstance(index, bool) for index in (startFrame, endFrame))
                or not 0 <= startFrame <= endFrame <= count):
            raise ValueError("frame range must satisfy 0 <= startFrame <= endFrame <= frame count")
        minimum = self._min_util if minUtil is None else self._validate_min_util(minUtil)
        selected = list(self._batches)[count - endFrame:count - startFrame]
        total = sum((weight for _, weight, _ in selected), Fraction(0))
        if not total:
            return {}
        threshold = minimum * total
        candidates = self._candidate_patterns(startFrame, endFrame, threshold)
        transactions = self._transactions_in_range(startFrame, endFrame)
        utilities = self._exact_utilities(candidates, transactions)
        return {pattern: self._reported(utility) for pattern, utility in utilities.items()
                if utility >= threshold}

    def mine(self):
        started = perf_counter()
        self._root = _HUSNode(None, None, 0)
        self._batches.clear()
        self._batch_count = 0
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
