"""Lossy Counting: frequent itemsets over the processed stream's landmark window.

Reference: G. S. Manku and R. Motwani, "Approximate Frequency Counts over Data
Streams", Proc. 28th VLDB Conference, Hong Kong, 2002.

Correspondence with the paper (Manku & Motwani, VLDB 2002, Sec. 4.2 and 5.1)
------------------------------------------------------------------------
* Bucket width w = ceil(1/epsilon), b_current = ceil(N/w). (MATCH, Sec. 4.2)
  N counts processed transactions, including empty transactions. Each batch
  contains whole buckets, so b_current = N // w at every batch boundary.
* Entries (set, f, delta). (MATCH, Sec. 5.1)
* UPDATE_SET deletion f + delta <= b_current. (MATCH, Sec. 5.1)
* NEW_SET: insert when batch frequency f >= beta, with delta = b_current - beta.
  (MATCH, Sec. 5.1) The paper is inconsistent here: Sec. 5.1 also says a subset
  must occur "beta+1 times or more", and Sec. 5.2 says "exceeds beta".
  streamPAMI follows the formal NEW_SET definition (>=).
* UPDATE_SET runs before NEW_SET; an entry deleted in this batch may be
  re-inserted. This is sound: deletion implies its true count is <= b_current,
  and the new entry has f + delta >= b_current.
* Output f >= (s - epsilon) N. (MATCH, Sec. 5.1)
* DATA-STRUCTURE DEVIATION: Buffer/Trie/SetGen and SetGen's rule that an excluded
  subset prevents considering its supersets are not implemented. D is a dict;
  every tracked entry is counted exactly in every batch, including counts below
  beta. A batch FP-tree finds all itemsets with batch support >= beta. Runtime
  and memory describe this implementation, not the paper's data structures.
* Batch sizes must be positive multiples of w, as each batch is a whole number
  of buckets. mine() processes the largest such prefix and holds any trailing
  transactions that do not fill a bucket unprocessed, with a UserWarning.
* Guarantees (Sec. 3): no false negatives; no output with true frequency below
  (s - epsilon) N; estimates are below true frequencies by at most epsilon N.
  These guarantees cover only the processed landmark window, not held input.

Thresholds use Fraction(str(value)) throughout. queryPatterns() has no frame
arguments: it always covers all N processed transactions. Blank file and URL
lines are skipped; empty transactions supplied directly or in a DataFrame count
towards N. getHeldCount() reports the unprocessed suffix from the last mine().

Importing this algorithm into a python program::

    import pandas as pd
    from streamPAMI.frequentPattern.basic.LossyCounting import LossyCounting

    source = pd.DataFrame({"Transactions": [["a", "b"], [], ["a"], ["b"], ["a"]]})
    miner = LossyCounting(source, 0.6, 0.2, batchSize=5)
    miner.mine()
    print(miner.getPatterns())
"""
from __future__ import annotations

from collections import Counter
from fractions import Fraction
from time import perf_counter
import warnings

from .abstract import _streamFrequentPatterns


class _Node:
    """A batch FP-tree node with a weighted prefix count."""

    __slots__ = ("item", "parent", "children", "count")

    def __init__(self, item=None, parent=None):
        self.item, self.parent = item, parent
        self.children = {}
        self.count = 0


class LossyCounting(_streamFrequentPatterns):
    """Maintain frequent-itemset counts and error bounds over a landmark window."""

    def __init__(self, iFile, minSup, epsilon, batchSize, sep="\t"):
        if not isinstance(minSup, (int, float)) or not 0 < minSup < 1:
            raise ValueError("minSup must be a fraction in (0, 1)")
        if not isinstance(epsilon, (int, float)) or not 0 < epsilon < minSup:
            raise ValueError("epsilon must be a fraction in (0, minSup)")
        if not isinstance(batchSize, int) or isinstance(batchSize, bool) or batchSize < 1:
            raise ValueError("batchSize must be a positive integer")
        self._min_sup = Fraction(str(minSup))
        self._epsilon = Fraction(str(epsilon))
        self._w = (self._epsilon.denominator + self._epsilon.numerator - 1) // self._epsilon.numerator
        if batchSize % self._w:
            raise ValueError(
                f"epsilon={epsilon} gives w={self._w}, which does not divide "
                f"batchSize={batchSize}; choose epsilon so that ceil(1/epsilon) "
                "divides batchSize (for batchSize=10000, try epsilon=0.001 or 0.0005)"
            )
        super().__init__(iFile, float(minSup), float(epsilon), batchSize, sep)
        self._D = {}  # Sorted item tuple -> [estimated count f, error bound delta].
        self._N = self._b_current = 0
        self._held = []

    @staticmethod
    def _batch_counts(transactions, beta, tracked):
        """FP-growth at beta, plus exact counts for every tracked itemset."""
        postings = {}
        for index, transaction in enumerate(transactions):
            for item in transaction:
                postings.setdefault(item, set()).add(index)
        order = {item: rank for rank, item in enumerate(
            sorted(postings, key=lambda item: (-len(postings[item]), item)))}

        def build_tree(paths):
            totals = Counter()
            for path, count in paths:
                totals.update({item: count for item in path})
            root = _Node()
            headers = {item: [] for item, count in totals.items() if count >= beta}
            for path, count in paths:
                node = root
                for item in sorted((item for item in path if item in headers), key=order.__getitem__):
                    child = node.children.get(item)
                    if child is None:
                        child = node.children[item] = _Node(item, node)
                        headers[item].append(child)
                    child.count += count
                    node = child
            return headers

        counts = Counter()

        def grow(headers, suffix):
            for item in sorted(headers, key=order.__getitem__, reverse=True):
                links = headers[item]
                pattern = tuple(sorted(suffix + (item,)))
                counts[pattern] = sum(node.count for node in links)
                paths = []
                for leaf in links:
                    path, parent = [], leaf.parent
                    while parent is not None and parent.item is not None:
                        path.append(parent.item)
                        parent = parent.parent
                    if path:
                        paths.append((path, leaf.count))
                if paths:
                    grow(build_tree(paths), suffix + (item,))

        grow(build_tree([(transaction, 1) for transaction in transactions]), ())
        # D need not be downward closed. Count it independently of FP-growth's
        # threshold pruning, including patterns with no occurrence in this batch.
        for pattern in tracked:
            matches = [postings.get(item, set()) for item in pattern]
            count = len(set.intersection(*matches))
            counts[pattern] = count
        return counts

    def _update_set(self, counts):
        for pattern in list(self._D):
            entry = self._D[pattern]
            entry[0] += counts[pattern]
            if entry[0] + entry[1] <= self._b_current:
                del self._D[pattern]

    def _new_set(self, counts, beta):
        for pattern, count in counts.items():
            if count >= beta and pattern not in self._D:
                self._D[pattern] = [count, self._b_current - beta]

    def processBatch(self, transactions: list[list[str]]):
        if not isinstance(transactions, list):
            raise TypeError("transactions must be a list of transactions")
        if not transactions or len(transactions) % self._w:
            raise ValueError(f"batch length must be a positive multiple of w={self._w}")
        started = perf_counter()
        clean = [list(dict.fromkeys(map(str, transaction))) for transaction in transactions]
        beta = len(clean) // self._w
        self._N += len(clean)
        self._b_current = self._N // self._w
        counts = self._batch_counts(clean, beta, self._D)
        self._update_set(counts)
        self._new_set(counts, beta)
        self._capture_metrics(started)

    def queryPatterns(self):
        threshold = (self._min_sup - self._epsilon) * self._N
        return {pattern: entry[0] for pattern, entry in self._D.items() if entry[0] >= threshold}

    def getHeldCount(self):
        return len(self._held)

    def getStreamLength(self):
        return self._N

    def mine(self):
        started = perf_counter()
        self._D.clear()
        self._N = self._b_current = 0
        self._held = []
        self._patterns = {}
        batch = []
        for transaction in self._iter_transactions():
            batch.append(transaction)
            if len(batch) == self.batchSize:
                self.processBatch(batch)
                batch = []
        processed = len(batch) - len(batch) % self._w
        if processed:
            self.processBatch(batch[:processed])
        self._held = batch[processed:]
        if self._held:
            warnings.warn(
                f"Held {len(self._held)} transactions unprocessed because they do not fill "
                f"a bucket of w={self._w}; they are excluded from the stream length and counts.",
                UserWarning,
                stacklevel=2,
            )
        self._patterns = self.queryPatterns()
        self._capture_metrics(started)
        return self
