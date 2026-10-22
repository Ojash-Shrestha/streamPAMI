"""Landmark guarantees, literal UPDATE_SET/NEW_SET and PAMI input/output."""
from collections import Counter
from fractions import Fraction
from io import BytesIO
from itertools import combinations
from math import ceil
import random
import warnings

import pandas as pd
import pytest

from streamPAMI.frequentPattern.basic import LossyCounting as algorithm
from streamPAMI.frequentPattern.basic.LossyCounting import LossyCounting
from tests.bruteForce import supports


def _random_stream(seed):
    rng = random.Random(seed)
    epsilon = rng.choice((1 / 2, 1 / 3, 1 / 4, 0.3, 0.15, 0.1))
    error = Fraction(str(epsilon))
    sigma = rng.choice([value for value in (0.2, 0.35, 0.5, 0.6, 0.75, 0.9)
                        if Fraction(str(value)) > error])
    width = ceil(1 / error)
    items = [f"item_{index}" for index in range(rng.randint(4, 8))]
    rates = [rng.uniform(0, 0.95) for _ in items]
    batches = []
    for _ in range(rng.randint(3, 12)):
        if rng.random() < 0.4:
            rates = [rng.uniform(0, 0.95) for _ in items]
        size = width * rng.randint(1, 4)
        batch = [[]]  # Empty transactions count towards N in every batch.
        for _ in range(size - 1):
            transaction = [item for item, rate in zip(items, rates) if rng.random() < rate]
            if len(transaction) > 6:
                transaction = rng.sample(transaction, 6)
            rng.shuffle(transaction)
            batch.append(transaction)
        batches.append(batch)
    return sigma, epsilon, width, batches


class _ReferenceLossyCounting:
    """Literal Sec. 5.1: enumerate every subset, UPDATE_SET, then NEW_SET."""

    def __init__(self, epsilon):
        self.width = ceil(1 / Fraction(str(epsilon)))
        self.N = 0
        self.D = {}

    def processBatch(self, transactions):
        counts = Counter()
        for transaction in transactions:
            items = sorted(set(transaction))
            for size in range(1, len(items) + 1):
                counts.update(combinations(items, size))
        beta = len(transactions) // self.width
        self.N += len(transactions)
        bucket = self.N // self.width
        for pattern in list(self.D):
            frequency, delta = self.D[pattern]
            frequency += counts[pattern]
            if frequency + delta <= bucket:
                del self.D[pattern]
            else:
                self.D[pattern] = [frequency, delta]
        for pattern, frequency in counts.items():
            if frequency >= beta and pattern not in self.D:
                self.D[pattern] = [frequency, bucket - beta]


@pytest.mark.slow
def test_random_stream_guarantees_and_reinsertion_coverage():
    reinsertions = 0
    for seed in range(200):
        sigma, epsilon, width, batches = _random_stream(seed)
        minimum, error = Fraction(str(sigma)), Fraction(str(epsilon))
        miner = LossyCounting(None, sigma, epsilon, width)
        true = Counter()
        length = 0
        for batch_no, batch in enumerate(batches):
            before = {pattern: tuple(entry) for pattern, entry in miner._D.items()}
            batch_counts = supports([batch], 0, 1)
            true.update(batch_counts)
            length += len(batch)
            miner.processBatch(batch)
            bucket = length // width
            beta = len(batch) // width
            context = f"seed={seed}, batch={batch_no}, N={length}, bucket={bucket}"
            assert miner.getStreamLength() == length, context
            assert miner._b_current == bucket, context
            actual = miner.queryPatterns()
            for pattern, frequency in true.items():
                message = (f"{context}, itemset={pattern}, true={frequency}, "
                           f"reported={actual.get(pattern)}, entry={miner._D.get(pattern)}")
                if frequency >= minimum * length:
                    assert pattern in actual, message
                if frequency > bucket:
                    # Keep the stronger bucket form of Lemma 4.3, even when
                    # ceil(1/epsilon) makes bucket smaller than epsilon * N.
                    assert pattern in miner._D, f"bucket-form Lemma 4.3: {message}"
            for pattern, reported in actual.items():
                frequency = true[pattern]
                message = f"{context}, itemset={pattern}, true={frequency}, reported={reported}"
                assert frequency >= (minimum - error) * length, message
                assert frequency - error * length <= reported <= frequency, message
                assert isinstance(pattern, tuple) and pattern == tuple(sorted(pattern)), message
            for pattern, (frequency, delta) in miner._D.items():
                message = f"{context}, itemset={pattern}, true={true[pattern]}, f={frequency}, delta={delta}"
                assert frequency <= true[pattern] <= frequency + delta, message
                assert 0 <= delta <= bucket, message
            for pattern, (frequency, delta) in before.items():
                count = batch_counts.get(pattern, 0)
                if frequency + count + delta <= bucket and count >= beta:
                    reinsertions += 1
                    assert miner._D[pattern] == [count, bucket - beta], context
    assert reinsertions > 0, "UPDATE_SET deletion followed by NEW_SET reinsertion was not exercised"
    print(f"UPDATE_SET deletions re-inserted by NEW_SET: {reinsertions}")


@pytest.mark.slow
def test_literal_reference_random_streams():
    for seed in range(200):
        sigma, epsilon, width, batches = _random_stream(seed)
        miner = LossyCounting(None, sigma, epsilon, width)
        reference = _ReferenceLossyCounting(epsilon)
        for batch_no, batch in enumerate(batches):
            miner.processBatch(batch)
            reference.processBatch(batch)
            actual = {pattern: tuple(entry) for pattern, entry in miner._D.items()}
            expected = {pattern: tuple(entry) for pattern, entry in reference.D.items()}
            assert actual == expected, f"seed={seed}, batch={batch_no}"


def test_hand_computed_updates_deletion_and_reinsertion():
    miner = LossyCounting(None, 0.6, 0.2, 10)
    # w=5. Batch 0 has a:2, b:2, ab:1; beta=1, bucket=1, delta=0.
    miner.processBatch([["a", "b"], ["a"], ["b"], [], []])
    assert miner._D == {("a",): [2, 0], ("b",): [2, 0], ("a", "b"): [1, 0]}
    assert miner.queryPatterns() == {("a",): 2, ("b",): 2}  # (0.6-0.2)*5 = 2.
    # Batch 1 has a:3, b:2, ab:2, c:1; beta=2, bucket=3.
    # UPDATE_SET makes ab:3, delta:0, then deletes it (3 <= 3).
    # NEW_SET re-inserts ab as [2, 1]; c:1 is below beta and never enters D.
    miner.processBatch([["a", "b"], ["a", "b"], ["a"], ["c"]] + [[] for _ in range(6)])
    assert miner._D == {("a",): [5, 0], ("b",): [4, 0], ("a", "b"): [2, 1]}
    # Batch 2 has c:2 only; beta=1, bucket=4. b:4 and ab:2+1 are
    # deleted, a:5 remains, and c enters as [2, 4-1].
    miner.processBatch([["c"], ["c"], [], [], []])
    assert miner._D == {("a",): [5, 0], ("c",): [2, 3]}
    assert miner.getStreamLength() == 20


def test_tracked_low_batch_count_is_exact():
    miner = LossyCounting(None, 0.6, 0.2, 10)
    miner.processBatch([["a"]] * 3 + [[], []])
    # The next batch's beta is 2, but the tracked a occurs once. Its true
    # accumulated count is 4, above bucket=3, so it survives with that count.
    miner.processBatch([["a"]] + [[] for _ in range(9)])
    assert miner._D == {("a",): [4, 0]}


@pytest.mark.parametrize("sigma,epsilon,size,count", [(0.3, 0.1, 10, 2), (0.2, 0.05, 300, 45)])
def test_exact_inclusive_output_threshold(sigma, epsilon, size, count):
    miner = LossyCounting(None, sigma, epsilon, size)
    assert Fraction(str(sigma)) * size - Fraction(str(epsilon)) * size == count
    miner.processBatch([["x"]] * count + [[] for _ in range(size - count)])
    assert miner.queryPatterns() == {("x",): count}


@pytest.mark.parametrize("epsilon,width", [(0.5, 2), (1 / 3, 4), (0.25, 4), (0.3, 4),
                                         (0.15, 7), (0.1, 10), (0.0006, 1667)])
def test_bucket_width_uses_exact_fraction(epsilon, width):
    miner = LossyCounting(None, 0.9, epsilon, width)
    assert miner._w == width == ceil(1 / Fraction(str(epsilon)))
    assert miner._epsilon == Fraction(str(epsilon))
    assert miner._min_sup == Fraction("0.9")
    assert isinstance(miner.minSup, float) and isinstance(miner.epsilon, float)


def test_parameter_validation_and_non_bucket_batch_sizes():
    with pytest.raises(ValueError, match=r"w=1667.*batchSize=10000.*choose epsilon"):
        LossyCounting(None, 0.01, 0.0006, 10000)
    for sigma in (0, 1, -0.1, float("nan"), float("inf"), "0.2", None):
        with pytest.raises(ValueError):
            LossyCounting(None, sigma, 0.1, 10)
    for epsilon in (0, -0.1, 0.2, 0.3, float("nan"), float("inf"), "0.1", None):
        with pytest.raises(ValueError):
            LossyCounting(None, 0.2, epsilon, 10)
    for size in (0, -1, 1.5, True, "10", None):
        with pytest.raises(ValueError):
            LossyCounting(None, 0.6, 0.2, size)
    miner = LossyCounting(None, 0.6, 0.2, 10)
    for size in (0, 1, 4, 6, 11):
        with pytest.raises(ValueError, match=r"positive multiple of w=5"):
            miner.processBatch([[] for _ in range(size)])
        assert miner.getStreamLength() == 0 and miner._D == {}
    with pytest.raises(TypeError):
        miner.processBatch(([], [], [], [], []))
    with pytest.raises(TypeError):
        miner.queryPatterns(0, 1)


@pytest.mark.parametrize("size", [3, 8, 23, 28])
def test_mine_holds_incomplete_bucket(tmp_path, size):
    transactions = [["a", "b"] if index % 3 == 0 else ["a"] for index in range(size)]
    source = tmp_path / "transactions.txt"
    source.write_text("\n".join("\t".join(transaction) for transaction in transactions), encoding="utf-8")
    miner = LossyCounting(source, 0.6, 0.2, 10)
    with pytest.warns(UserWarning, match=r"Held 3 transactions unprocessed"):
        assert miner.mine() is miner
    processed = size - 3
    assert miner.getStreamLength() == processed
    assert miner.getHeldCount() == 3
    direct = LossyCounting(None, 0.6, 0.2, 10)
    for offset in range(0, processed, 10):
        direct.processBatch(transactions[offset:min(offset + 10, processed)])
    assert miner._D == direct._D
    assert miner.getPatterns() == miner.queryPatterns() == direct.queryPatterns()
    # Replaying mine() resets both the processed stream and the held suffix.
    with pytest.warns(UserWarning, match=r"Held 3 transactions unprocessed"):
        miner.mine()
    assert miner._D == direct._D and miner.getStreamLength() == processed
    assert miner.getHeldCount() == 3


def test_blank_file_lines_skipped_and_direct_empty_transactions_count(tmp_path):
    source = tmp_path / "with_blanks.txt"
    source.write_text("\na\n\n \t\nb\n\na\tb\nc\n\na\n", encoding="utf-8")
    miner = LossyCounting(source, 0.6, 0.2, 5)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        miner.mine()
    assert not caught
    assert miner.getStreamLength() == 5 and miner.getHeldCount() == 0
    direct = LossyCounting(None, 0.6, 0.2, 5)
    direct.processBatch([["a"], ["b"], ["a", "b"], ["c"], ["a"]])
    assert miner._D == direct._D
    direct.processBatch([[] for _ in range(5)])
    assert direct.getStreamLength() == 10
    assert direct.getPatterns() == {}  # Only mine() stores final patterns.


def test_url_uses_shared_reader_and_skips_blank_lines(monkeypatch):
    payload = b"\na\n\nb\n\na\tb\nc\n\na\n"
    monkeypatch.setattr("streamPAMI.frequentPattern.basic.abstract.urlopen", lambda url: BytesIO(payload))
    miner = LossyCounting("https://example.com/transactions.txt", 0.6, 0.2, 5).mine()
    assert miner.getStreamLength() == 5 and miner.getHeldCount() == 0
    assert miner.getPatterns() == {("a",): 3, ("b",): 2}


def test_pami_output_dataframe_input_and_module_export(tmp_path, capsys):
    assert algorithm.LossyCounting is LossyCounting
    source = pd.DataFrame({"Transactions": [["b", "a", "a"], [], "b", "a", "a,b"]})
    miner = LossyCounting(source, 0.6, 0.2, 5, sep=",")
    assert miner.queryPatterns() == {} and miner.getHeldCount() == miner.getStreamLength() == 0
    with pytest.warns(DeprecationWarning, match="startMine"):
        assert miner.startMine() is miner
    assert miner.getPatterns() == {("a",): 3, ("b",): 3, ("a", "b"): 2}
    assert miner.getStreamLength() == 5
    frame = miner.getPatternsAsDataFrame()
    assert list(frame.columns) == ["Patterns", "Support"]
    assert dict(zip(frame["Patterns"], frame["Support"])) == {"a": 3, "b": 3, "a,b": 2}
    output = tmp_path / "patterns.txt"
    miner.save(output)
    assert set(output.read_text(encoding="utf-8").splitlines()) == {"a:3", "b:3", "a,b:2"}
    assert miner.getRuntime() >= 0 and miner.getMemoryRSS() > 0 and miner.getMemoryUSS() >= 0
    miner.printResults()
    assert "Total number of patterns: 3" in capsys.readouterr().out


def test_missing_file_bad_dataframe_and_empty_input(tmp_path):
    with pytest.raises(FileNotFoundError):
        LossyCounting(tmp_path / "missing.txt", 0.6, 0.2, 5).mine()
    with pytest.raises(ValueError, match="Transactions"):
        LossyCounting(pd.DataFrame({"wrong": []}), 0.6, 0.2, 5).mine()
    miner = LossyCounting(pd.DataFrame({"Transactions": []}), 0.6, 0.2, 5).mine()
    assert miner.getStreamLength() == miner.getHeldCount() == 0
    assert miner.getPatterns() == miner._D == {}
