"""FP-Stream: C. Giannella, J. Han, J. Pei, X. Yan, P. S. Yu, "Mining Frequent Patterns in Data Streams at Multiple Time Granularities", Next Generation Data Mining, 2003, Section 3.

Tail pruning uses the two strict inequalities in Section 3.5; strictness is required by condition (3.1). A new itemset is inserted only when its batch frequency is strictly greater than epsilon times batch size, following Algorithm 1. Query output includes estimates equal to (sigma - epsilon) times the period size; the inclusive boundary preserves no-false-negative recall.

Threshold comparisons use exact decimal fractions internally. The public
minSup and epsilon attributes retain their floating-point values.

Accuracy guarantees hold only when sigma > 2 * epsilon and the queried period
starts at the newest frame. For such a period with W transactions and true
support f, every itemset with f >= sigma * W is returned, and each returned
estimate lies in [f - epsilon * W, f]. The constructor emits a UserWarning when
epsilon >= minSup / 2 because false negatives are possible.

Known failure pending a pruning decision: with uneven batch sizes, prefix sums
starting at the newest frame can cause false negatives for periods starting
at older frames. The strict expected-failure test records this limitation;
the tail-pruning condition remains the confirmed condition (3.1).

Importing this algorithm into a python program::

    from streamPAMI.frequentPattern.basic.FPStream import FPStream
    miner = FPStream("transactions.txt", 0.2, 0.02, 100)
    miner.mine()
    print(miner.getPatterns())
"""
from __future__ import annotations

from collections import Counter
from fractions import Fraction
from itertools import combinations
from time import perf_counter
import warnings

from .abstract import _streamFrequentPatterns


class FPStream(_streamFrequentPatterns):
    """Incremental FP-Stream miner with a logarithmic tilted-time window."""

    def __init__(self, iFile, minSup, epsilon, batchSize, sep="\t"):
        if not isinstance(minSup, (int, float)) or not 0 < minSup < 1:
            raise ValueError("minSup must be a float in (0, 1)")
        if not isinstance(epsilon, (int, float)) or not 0 < epsilon < minSup:
            raise ValueError("epsilon must be a float in (0, minSup)")
        if not isinstance(batchSize, int) or batchSize < 1:
            raise ValueError("batchSize must be a positive integer")
        self._min_sup = Fraction(str(minSup))
        self._epsilon = Fraction(str(epsilon))
        if 2 * self._epsilon >= self._min_sup:
            warnings.warn(
                "Accuracy guarantees require minSup > 2 * epsilon; "
                "epsilon >= minSup / 2 can cause false negatives.",
                UserWarning,
                stacklevel=2,
            )
        super().__init__(iFile, float(minSup), float(epsilon), batchSize, sep)
        self._frames = []  # newest first: [start, end, transaction weight]
        self._tables = {}  # itemset -> support per visible frame, newest first
        self._patterns = {}
        self._batch_count = 0

    def getTimeFrames(self):
        return [(frame[0], frame[1]) for frame in self._frames]

    def getFrameWeights(self):
        return [frame[2] for frame in self._frames]

    def _merge_frames(self):
        # Keep at most two frames per power-of-two level. Merge the two oldest
        # adjacent frames at an overfull level, summing every pattern's support.
        while True:
            levels = Counter(frame[1] - frame[0] for frame in self._frames)
            oversized = next((size for size, count in sorted(levels.items()) if count > 2), None)
            if oversized is None:
                break
            positions = [i for i, frame in enumerate(self._frames) if frame[1] - frame[0] == oversized]
            left, right = positions[-2:]
            if right != left + 1:
                raise RuntimeError("logarithmic frames at a merge level are not adjacent")
            newer, older = self._frames[left], self._frames[right]
            self._frames[left:right + 1] = [[older[0], newer[1], older[2] + newer[2]]]
            for table in self._tables.values():
                table[left:right + 1] = [table[left] + table[right]]

    def _tail_prune(self, table):
        weights = self.getFrameWeights()
        for m in range(len(table)):
            if not all(table[i] < self._min_sup * weights[i] for i in range(m, len(table))):
                continue
            support_sum = weight_sum = 0
            safe = True
            for i in range(len(table)):
                support_sum += table[i]
                weight_sum += weights[i]
                if i >= m and not support_sum < self._epsilon * weight_sum:
                    safe = False
                    break
            if safe:
                del table[m:]
                return

    @staticmethod
    def _batch_counts(transactions, threshold, tracked):
        """Mine new qualifying patterns and exact counts for tracked patterns.

        The transaction tree includes every item. Type I pruning applies only
        to patterns absent from the stream structure, including conditional
        extensions whose support is below the batch threshold.
        """
        item_counts = Counter(item for tx in transactions for item in set(tx))
        order = {item: rank for rank, (item, _) in enumerate(
            sorted(item_counts.items(), key=lambda pair: (-pair[1], pair[0])))}

        class Node:
            __slots__ = ("item", "count", "parent", "children")

            def __init__(self, item=None, parent=None):
                self.item, self.count, self.parent = item, 0, parent
                self.children = {}

        root = Node()
        headers = {item: [] for item in item_counts}
        for transaction in transactions:
            node = root
            for item in sorted(set(transaction), key=lambda value: order[value]):
                child = node.children.get(item)
                if child is None:
                    child = node.children[item] = Node(item, node)
                    headers[item].append(child)
                child.count += 1
                node = child

        mined = Counter()

        def grow(tree_root, header, suffix, threshold):
            for item in sorted(header, key=lambda value: (item_counts.get(value, 0), value)):
                support = sum(node.count for node in header[item])
                pattern = tuple(sorted(suffix + (item,)))
                if pattern not in tracked and support <= threshold:
                    continue
                mined[pattern] = support
                paths = []
                for leaf in header[item]:
                    path, parent = [], leaf.parent
                    while parent is not None and parent.item is not None:
                        path.append(parent.item)
                        parent = parent.parent
                    if path:
                        paths.append((path, leaf.count))
                if not paths:
                    continue
                conditional_counts = Counter()
                for path, count in paths:
                    conditional_counts.update({value: count for value in path})
                conditional_root = Node()
                conditional_header = {value: [] for value in conditional_counts
                                      if conditional_counts[value] > threshold
                                      or tuple(sorted(suffix + (item, value))) in tracked}
                for path, count in paths:
                    node = conditional_root
                    kept = sorted((value for value in path if value in conditional_header),
                                  key=lambda value: (order[value], value))
                    for value in kept:
                        child = node.children.get(value)
                        if child is None:
                            child = node.children[value] = Node(value, node)
                            conditional_header[value].append(child)
                        child.count += count
                        node = child
                grow(conditional_root, conditional_header, suffix + (item,), threshold)

        grow(root, headers, tuple(), threshold)
        return mined

    @staticmethod
    def _has_subset_in(pattern, patterns):
        return any(sub in patterns for r in range(1, len(pattern) + 1)
                   for sub in combinations(pattern, r))

    def _drop_pattern_and_supersets(self, pattern):
        """Defer Type II removal until the single purge at the end of the batch."""
        self._pending_drops.add(pattern)

    def processBatch(self, transactions: list[list[str]]):
        if not isinstance(transactions, list):
            raise TypeError("transactions must be a list of transactions")
        clean = [list(dict.fromkeys(map(str, transaction))) for transaction in transactions]
        if not clean:
            raise ValueError("a batch must contain at least one transaction")
        started = perf_counter()
        self._pending_drops = set()
        counts = self._batch_counts(clean, self._epsilon * len(clean), self._tables)
        old_frame_count = len(self._frames)
        # The full-tree scan begins by recording zero for the newly arrived batch.
        updated = set()
        for pattern in list(self._tables):
            # Pruned tail entries represent zero support in the discarded frames.
            self._tables[pattern].extend([0] * (old_frame_count - len(self._tables[pattern])))
            self._tables[pattern].insert(0, 0)
        self._frames.insert(0, [self._batch_count, self._batch_count + 1, len(clean)])
        self._merge_frames()

        threshold = self._epsilon * len(clean)
        type_two_blocked = set()
        for pattern, frequency in sorted(counts.items(), key=lambda pair: (len(pair[0]), pair[0])):
            if self._has_subset_in(pattern, type_two_blocked):
                continue
            if pattern in self._tables:
                table = self._tables[pattern]
                table[0] = frequency
                updated.add(pattern)
                self._tail_prune(table)
                if not table:
                    type_two_blocked.add(pattern)
                    self._drop_pattern_and_supersets(pattern)
            elif frequency > threshold:
                self._tables[pattern] = [frequency] + [0] * (len(self._frames) - 1)
                updated.add(pattern)
            else:
                # Type I: a pattern at the batch threshold cannot have a qualifying superset.
                type_two_blocked.add(pattern)

        # Patterns absent from the batch retain the zero inserted above.
        for pattern in sorted(list(self._tables), key=lambda value: (len(value), value)):
            if pattern not in self._tables:
                continue
            table = self._tables[pattern]
            if pattern not in updated:
                self._tail_prune(table)
            if not table:
                self._drop_pattern_and_supersets(pattern)
        if self._pending_drops:
            for pattern in list(self._tables):
                if self._has_subset_in(pattern, self._pending_drops):
                    del self._tables[pattern]
        self._pending_drops = set()
        self._batch_count += 1
        self._capture_metrics(started)

    def queryPatterns(self, startFrame=0, endFrame=None):
        frame_count = len(self._frames)
        if endFrame is None:
            endFrame = frame_count
        if (not isinstance(startFrame, int) or not isinstance(endFrame, int)
                or startFrame < 0 or endFrame < startFrame or endFrame > frame_count):
            raise ValueError("frame range must satisfy 0 <= startFrame <= endFrame <= frame count")
        period_weight = sum(frame[2] for frame in self._frames[startFrame:endFrame])
        if not period_weight:
            return {}
        result = {}
        for pattern, table in self._tables.items():
            estimate = sum(table[startFrame:min(endFrame, len(table))]) if startFrame < len(table) else 0
            if estimate >= (self._min_sup - self._epsilon) * period_weight:
                result[pattern] = estimate
        return result

    def mine(self):
        started = perf_counter()
        self._frames.clear()
        self._tables.clear()
        self._patterns = {}
        self._batch_count = 0
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

