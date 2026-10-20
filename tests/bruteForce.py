"""Transparent brute-force support oracle for small streams."""
from collections import Counter
from itertools import combinations


def supports(batches, start_batch, end_batch):
    """Return exact itemset counts for batches [start_batch, end_batch)."""
    counts = Counter()
    for batch in batches[start_batch:end_batch]:
        for transaction in batch:
            if len(transaction) > 16:
                raise ValueError("oracle refuses transactions longer than 16 items")
            items = sorted(set(transaction))
            for size in range(1, len(items) + 1):
                for itemset in combinations(items, size):
                    counts[itemset] += 1
    return dict(counts)
