import math
import random

import pytest

from streamPAMI.frequentPattern.basic.FPStream import FPStream
from tests.bruteForce import supports


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
    miner = FPStream(None, .3, .1, 2)
    miner.processBatch([['a'], ['b']])
    miner.processBatch([['b'], ['b'], ['b']])
    miner.processBatch([['b'], ['b']])
    assert miner.queryPatterns(1, 2)[('a',)] == 1  # exactly (.3 - .1) * 5


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
                    true = supports(batches, frames[end - 1][0], frames[start][1])
                    estimate = miner.queryPatterns(start, end)
                    weight = sum(miner.getFrameWeights()[start:end])
                    for pattern, frequency in true.items():
                        if frequency >= .2 * weight:
                            assert pattern in estimate, (batch_no, (start, end), pattern, frequency,
                                                         estimate.get(pattern))
                    for pattern, value in estimate.items():
                        assert true.get(pattern, 0) - .05 * weight <= value <= true.get(pattern, 0), (
                            batch_no, (start, end), pattern, true.get(pattern, 0), value)
