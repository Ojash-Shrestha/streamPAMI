"""Independent, exhaustive itemset-utility and TWU oracle for small streams."""
from collections import defaultdict
from fractions import Fraction
from itertools import combinations


def utility_counts(batches, start_batch, end_batch):
    """Exact utility of every occurring non-empty itemset in [start, end)."""
    counts = defaultdict(Fraction)
    for batch in batches[start_batch:end_batch]:
        for transaction in batch:
            if len(transaction) > 16:
                raise ValueError("oracle refuses transactions longer than 16 items")
            items = sorted(transaction)
            for size in range(1, len(items) + 1):
                for pattern in combinations(items, size):
                    counts[pattern] += sum((Fraction(str(transaction[item])) for item in pattern), Fraction(0))
    return dict(counts)


def utilities(batches, start_batch, end_batch, threshold):
    """Return itemsets whose exact utility reaches the supplied Fraction threshold."""
    return {pattern: utility for pattern, utility in utility_counts(batches, start_batch, end_batch).items()
            if utility >= threshold}


def twu(batches, start_batch, end_batch):
    """Exact TWU: add each containing transaction's whole utility to every subset."""
    counts = defaultdict(Fraction)
    for batch in batches[start_batch:end_batch]:
        for transaction in batch:
            if len(transaction) > 16:
                raise ValueError("oracle refuses transactions longer than 16 items")
            total = sum((Fraction(str(value)) for value in transaction.values()), Fraction(0))
            items = sorted(transaction)
            for size in range(1, len(items) + 1):
                for pattern in combinations(items, size):
                    counts[pattern] += total
    return dict(counts)
