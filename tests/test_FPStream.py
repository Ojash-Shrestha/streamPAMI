import math
import random
from fractions import Fraction

import pytest

from streamPAMI.frequentPattern.basic.FPStream import FPStream
from tests.bruteForce import supports


def _check_guarantee(batches, miner, start, end, seed, batch_no):
    frames = miner.getTimeFrames()
    true = supports(batches, frames[end - 1][0], frames[start][1])
    estimate = miner.queryPatterns(start, end)
    weight = sum(miner.getFrameWeights()[start:end])

    def context(pattern):
        return (f"seed={seed}, batch={batch_no}, period=({start}, {end}), "
                f"itemset={pattern}, true={true.get(pattern, 0)}, "
                f"estimate={estimate.get(pattern)}")

    for pattern, frequency in true.items():
        if frequency >= Fraction("0.2") * weight:
            assert pattern in estimate, context(pattern)
    for pattern, value in estimate.items():
        assert true.get(pattern, 0) - Fraction("0.05") * weight <= value <= true.get(pattern, 0), context(pattern)


def test_oracle_hand_computed():
    batches = [[['a', 'b'], ['a']], [['b', 'c']]]
    assert supports(batches, 0, 1) == {('a',): 2, ('b',): 1, ('a', 'b'): 1}
    assert supports(batches, 0, 2) == {
        ('a',): 2, ('b',): 2, ('a', 'b'): 1, ('c',): 1, ('b', 'c'): 1}


def test_oracle_refuses_long_transactions():
    with pytest.raises(ValueError):
        supports([[[str(i) for i in range(17)]]], 0, 1)


def test_validation():
    for sigma, epsilon in [(0, .1), (1, .1), (.2, 0), (.2, .2), (.2, .3)]:
        with pytest.raises(ValueError):
            FPStream(None, sigma, epsilon, 10)


def test_inclusive_query_boundary():
    miner = FPStream(None, 0.2, 0.05, 300)
    miner.processBatch([["x"] if t < 45 else ["f"] for t in range(300)])
    assert miner.queryPatterns()[("x",)] == 45


def test_tracked_patterns_below_batch_threshold_get_exact_counts():
    miner = FPStream(None, 0.2, 0.05, 100)
    miner.processBatch([["x", "y", "z"] if t < 30 else ["f"] for t in range(100)])
    tracked = set(miner._tables)
    miner.processBatch([["x", "y", "z"] if t == 0 else ["f"] for t in range(100)])
    for pattern in tracked - {("f",)}:
        assert miner._tables[pattern][0] == 1, pattern


def test_type_ii_removes_tracked_supersets(monkeypatch):
    miner = FPStream(None, 0.2, 0.05, 100)
    miner.processBatch([["a", "b"] if t < 10 else ["f"] for t in range(100)])
    superset_table = miner._tables[("a", "b")]
    visited = []
    tail_prune = miner._tail_prune

    def record_pruning(table):
        visited.append(table)
        tail_prune(table)

    monkeypatch.setattr(miner, "_tail_prune", record_pruning)
    miner.processBatch([["a"]] + [["f"] for _ in range(9999)])
    assert ("a",) not in miner._tables
    assert ("a", "b") not in miner._tables
    assert ("f",) in miner._tables
    # A removed superset must not survive until its own subsequent scan/pruning.
    assert all(table is not superset_table for table in visited)


def test_process_batch_defers_final_patterns(monkeypatch):
    miner = FPStream(None, 0.2, 0.05, 10)

    def unexpected_query(*args, **kwargs):
        pytest.fail("processBatch must not query or populate the final patterns")

    monkeypatch.setattr(miner, "queryPatterns", unexpected_query)
    miner.processBatch([["a"]])
    assert miner.getPatterns() == {}


def test_pami_output_format_and_file_mining(tmp_path):
    source = tmp_path / "transactions.txt"
    source.write_text("a;b\na\nb\n", encoding="utf-8")
    miner = FPStream(source, 0.2, 0.05, 2, sep=";")
    miner.mine()
    assert miner.getPatterns() == {("a",): 2, ("b",): 2, ("a", "b"): 1}
    frame = miner.getPatternsAsDataFrame()
    assert list(frame.columns) == ["Patterns", "Support"]
    assert dict(zip(frame["Patterns"], frame["Support"])) == {"a": 2, "b": 2, "a;b": 1}
    output = tmp_path / "patterns.txt"
    miner.save(output)
    assert set(output.read_text(encoding="utf-8").splitlines()) == {"a:2", "b:2", "a;b:1"}
    assert isinstance(miner.minSup, float)
    assert isinstance(miner.epsilon, float)


def test_unpruned_frame_tables_match_oracle():
    rng = random.Random(823)
    miner = FPStream(None, .2, 1e-9, 7)
    batches = []
    for _ in range(10):
        batch = [[str(i) for i in range(5) if rng.random() < .4]
                 for _ in range(rng.randint(3, 8))]
        batches.append(batch)
        miner.processBatch(batch)
        for frame_index, (start, end) in enumerate(miner.getTimeFrames()):
            exact = supports(batches, start, end)
            for pattern, frequency in exact.items():
                assert miner._tables[pattern][frame_index] == frequency
            for pattern, table in miner._tables.items():
                assert table[frame_index] == exact.get(pattern, 0)


def test_random_stream_frame_layout_and_guarantee():
    for seed in range(20):
        rng = random.Random(seed)
        items = [str(i) for i in range(rng.randint(6, 8))]
        miner = FPStream(None, .2, .05, rng.randint(20, 40))
        batches = []
        for batch_no in range(10):
            batch = []
            for _ in range(rng.randint(20, 40)):
                # Skew the item probabilities to create support near thresholds.
                tx = [item for pos, item in enumerate(items)
                      if rng.random() < (0.35 if pos < 3 else 0.15)]
                batch.append(tx)
            batches.append(batch)
            miner.processBatch(batch)
            frames = miner.getTimeFrames()

            chronological = list(reversed(frames))
            assert chronological[0][0] == 0
            assert chronological[-1][1] == batch_no + 1
            assert all(a[1] == b[0] for a, b in zip(chronological, chronological[1:]))
            assert all((end - start) & (end - start - 1) == 0 for start, end in frames)
            assert len(frames) <= 2 * math.ceil(math.log2(batch_no + 1)) + 2

            for start in range(len(frames)):
                for end in range(start + 1, len(frames) + 1):
                    _check_guarantee(batches, miner, start, end, seed, batch_no)


@pytest.mark.xfail(strict=True, reason="tail-pruning prefix sums start at the newest frame; guarantee fails for periods starting at older frames with uneven batch sizes - pending decision")
def test_false_negative_older_period_uneven_batches():
    def batch(size, x):
        return [["x"] if t < x else ["f"] for t in range(size)]
    batches = [batch(100, 13), batch(100, 12), batch(100, 40), batch(2000, 0)]
    miner = FPStream(None, 0.2, 0.05, 100)
    for b in batches:
        miner.processBatch(b)
    assert miner.getTimeFrames() == [(3, 4), (2, 3), (0, 2)]
    # batches [0,3): x has true support 65 >= 0.2 * 300, so it must be returned
    assert ("x",) in miner.queryPatterns(1, 3)


@pytest.mark.slow
def test_drifting_random_stream_variable_batch_sizes_guarantee():
    for seed in range(200):
        rng = random.Random(seed)
        items = [str(i) for i in range(rng.randint(6, 8))]
        rates = [rng.uniform(0, 0.3) for _ in items]
        changes = set(rng.sample(range(1, 10), rng.randint(2, 5)))
        miner = FPStream(None, 0.2, 0.05, 100)
        batches = []
        for batch_no in range(10):
            if batch_no in changes:
                rates = [rng.uniform(0, 0.3) for _ in items]
            batch_size = rng.choice((10, 20, 50, 200, 400))
            batch = [[item for item, rate in zip(items, rates) if rng.random() < rate]
                     for _ in range(batch_size)]
            batches.append(batch)
            miner.processBatch(batch)
            frames = miner.getTimeFrames()
            for start in range(len(frames)):
                # Older starting frames are pending the tail-pruning decision in item 5.
                if start > 0:
                    continue
                for end in range(start + 1, len(frames) + 1):
                    _check_guarantee(batches, miner, start, end, seed, batch_no)
