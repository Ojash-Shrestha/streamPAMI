"""DSTree: exact frequent itemsets over a sliding window of batches.

Reference: C. K.-S. Leung and Q. I. Khan, "DSTree: A Tree Structure for the
Mining of Frequent Sets from Data Streams", Proc. IEEE ICDM 2006, pp. 928-932.

Every query returns exactly the non-empty itemsets with support >= minSup * W,
where W includes empty transactions in the queried batches. Thresholds use
Fraction(str(minSup)) arithmetic. Frames cover individual batches in the current
window and are returned newest first, with end-exclusive batch boundaries.
Mining uses FP-growth over tree paths only when queried; processBatch does not
mine itemsets. mine stores the result for the whole current window.

Design choices to confirm against the paper
-----------------------------------------
* [CONFIRM] The prefix tree uses a fixed, frequency-independent canonical order:
  lexicographic by item string. This order never changes.
* [CONFIRM] Every node stores a list of counts, one per batch slot in the window.
  The count slots are oldest first, even though the public frames are newest first.
* [CONFIRM] Sliding drops the oldest slot from every node. Nodes whose counts are
  all zero are removed eagerly; the paper may remove them lazily, with identical
  query results.

The tree holds every transaction of the window, compressed by shared prefixes.
Memory grows with the window's transactions (windowSize * batchSize for fixed
batches), transaction lengths and per-node count vectors. Unlike FP-Stream,
there is no epsilon-bounded summary. Empty transactions contribute to W without
creating item nodes; blank input lines also represent empty transactions.

Importing this algorithm into a python program::

    import pandas as pd
    from streamPAMI.frequentPattern.basic.DSTree import DSTree

    source = pd.DataFrame({"Transactions": [["a", "b"], [], ["a"]]})
    miner = DSTree(source, 0.25, windowSize=2, batchSize=2)
    miner.mine()
    print(miner.getPatterns())
"""
from __future__ import annotations

from collections import Counter, deque
from fractions import Fraction
from time import perf_counter

from .abstract import _streamFrequentPatterns


class _Node:
    """A canonical prefix and its batch counts; the root counts all transactions."""

    __slots__ = ("item", "parent", "children", "counts")

    def __init__(self, item, parent, slots):
        self.item = item
        self.parent = parent
        self.children = {}
        self.counts = [0] * slots


class DSTree(_streamFrequentPatterns):
    """Maintain an exact canonical prefix tree for the last windowSize batches."""

    def __init__(self, iFile, minSup, windowSize, batchSize, sep="\t"):
        if not isinstance(minSup, (int, float)) or not 0 < minSup < 1:
            raise ValueError("minSup must be a fraction in (0, 1)")
        for name, value in (("windowSize", windowSize), ("batchSize", batchSize)):
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{name} must be an integer >= 1")
        super().__init__(iFile, float(minSup), batchSize=batchSize, sep=sep)
        self._min_sup = Fraction(str(minSup))
        self.windowSize = windowSize
        self._root = _Node(None, None, 0)
        self._batches = deque()  # (global batch index, transaction count), oldest first
        self._batch_count = 0

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
            node.counts.pop(0)
            if node is not self._root and not any(node.counts):
                del node.parent.children[node.item]
                # All descendants of a zero prefix are zero as well.
                continue
            pending.extend(node.children.values())

    def processBatch(self, transactions: list[list[str]]):
        if not isinstance(transactions, list):
            raise TypeError("transactions must be a list of transactions")
        if not transactions:
            raise ValueError("a batch must contain at least one transaction")
        started = perf_counter()
        clean = [sorted({str(item) for item in transaction if str(item).strip()})
                 for transaction in transactions]
        if len(self._batches) >= self.windowSize:
            self._expire_oldest_batch()
        for node in self._nodes():
            node.counts.append(0)
        self._batches.append((self._batch_count, len(clean)))
        self._root.counts[-1] = len(clean)
        for transaction in clean:
            node = self._root
            for item in transaction:
                child = node.children.get(item)
                if child is None:
                    child = node.children[item] = _Node(item, node, len(self._batches))
                child.counts[-1] += 1
                node = child
        self._batch_count += 1
        self._capture_metrics(started)

    def getTimeFrames(self):
        return [(index, index + 1) for index, _ in reversed(self._batches)]

    def getFrameWeights(self):
        return [weight for _, weight in reversed(self._batches)]

    @staticmethod
    def _conditional_headers(paths, threshold):
        """Build a transient one-slot FP-tree from weighted canonical paths."""
        totals = Counter()
        for path, frequency in paths:
            totals.update({item: frequency for item in path})
        root = _Node(None, None, 1)
        headers = {}
        for path, frequency in paths:
            node = root
            for item in path:
                if totals[item] < threshold:
                    continue
                child = node.children.get(item)
                if child is None:
                    child = node.children[item] = _Node(item, node, 1)
                    headers.setdefault(item, []).append(child)
                child.counts[0] += frequency
                node = child
        return {item: [(node, node.counts[0]) for node in nodes]
                for item, nodes in headers.items()}

    def queryPatterns(self, startFrame=0, endFrame=None):
        frame_count = len(self._batches)
        if endFrame is None:
            endFrame = frame_count
        if (any(not isinstance(index, int) or isinstance(index, bool)
                for index in (startFrame, endFrame))
                or not 0 <= startFrame <= endFrame <= frame_count):
            raise ValueError("frame range must satisfy 0 <= startFrame <= endFrame <= frame count")
        weight = sum(self.getFrameWeights()[startFrame:endFrame])
        if not weight:
            return {}
        slots = slice(frame_count - endFrame, frame_count - startFrame)
        threshold = self._min_sup * weight
        headers = {}
        for node in self._nodes():
            if node is self._root:
                continue
            frequency = sum(node.counts[slots])
            if frequency:
                headers.setdefault(node.item, []).append((node, frequency))

        patterns = {}

        def grow(current_headers, suffix):
            for item in sorted(current_headers, reverse=True):
                links = current_headers[item]
                frequency = sum(count for _, count in links)
                if frequency >= threshold:
                    patterns[tuple(sorted(suffix + (item,)))] = frequency
                    paths = []
                    for node, count in links:
                        path, parent = [], node.parent
                        while parent is not None and parent.item is not None:
                            path.append(parent.item)
                            parent = parent.parent
                        if path:
                            paths.append((list(reversed(path)), count))
                    conditional = self._conditional_headers(paths, threshold)
                    if conditional:
                        grow(conditional, suffix + (item,))

        grow(headers, ())
        return patterns

    def _parse_lines(self, lines):
        # Preserve each blank line as a transaction, unlike approximate FPStream input.
        for line in lines:
            line = line.strip()
            yield (line.split(self.sep) if self.sep else line.split()) if line else []

    def mine(self):
        started = perf_counter()
        self._root = _Node(None, None, 0)
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
