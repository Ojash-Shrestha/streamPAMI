"""Tests for DSTreeMaximal: streamPAMI composition, not a published algorithm."""
from collections import Counter
from fractions import Fraction

import pandas as pd
import pytest

from streamPAMI.frequentPattern.basic.DSTree import DSTree
from streamPAMI.frequentPattern.maximal import DSTreeMaximal as composition
from streamPAMI.frequentPattern.maximal.DSTreeMaximal import DSTreeMaximal
from tests.bruteForce import supports
from tests.test_DSTree import _random_stream


def _naive_maximal(frequent):
    # Deliberately quadratic and independent of the immediate-subset filter:
    # compare each X with every Y, using the definition of proper subset.
    itemsets = {pattern: set(pattern) for pattern in frequent}
    return {pattern: count for pattern, count in frequent.items()
            if not any(itemsets[pattern] < other for other in itemsets.values())}


def _hand_batch():
    return [["a", "b"], ["a", "b", "c"], ["a", "b", "c"], ["b", "d"], ["b", "d"]]


def test_hand_example_is_maximal_not_closed():
    miner = DSTreeMaximal(None, 0.4, windowSize=1, batchSize=5)
    miner.processBatch(_hand_batch())
    # W=5, threshold=2. F: a3 b5 c2 d2 ab3 ac2 bc2 bd2 abc2.
    # M: abc2, bd2. In particular ab3 is not maximal even though abc's
    # count is 2: keeping ab because the counts differ would give CLOSED sets.
    frequent = DSTree.queryPatterns(miner)
    assert frequent == {("a",): 3, ("b",): 5, ("c",): 2, ("d",): 2,
                        ("a", "b"): 3, ("a", "c"): 2, ("b", "c"): 2,
                        ("b", "d"): 2, ("a", "b", "c"): 2}
    assert miner.queryPatterns() == {("a", "b", "c"): 2, ("b", "d"): 2}
    assert frequent[("a", "b")] != frequent[("a", "b", "c")]


def test_empty_results_and_maximal_singletons():
    miner = DSTreeMaximal(None, 0.5, windowSize=1, batchSize=2)
    assert miner.queryPatterns() == {}
    miner.processBatch([["solo"], []])
    assert miner.queryPatterns() == {("solo",): 1}
    assert miner.queryPatterns(0, 0) == {}
    miner.processBatch([["a"], ["b"]])
    assert miner.queryPatterns(minSup=0.9) == {}
    assert miner.queryPatterns() == {("a",): 1, ("b",): 1}
    miner.processBatch([[], []])
    assert miner.queryPatterns(minSup=0.05) == {}


def test_only_query_is_overridden_and_validation_is_inherited():
    assert composition.DSTreeMaximal is DSTreeMaximal
    for method in ("__init__", "processBatch", "mine", "getTimeFrames", "getFrameWeights",
                   "getPatterns", "getPatternsAsDataFrame", "save", "printResults",
                   "getRuntime", "getMemoryUSS", "getMemoryRSS", "startMine"):
        assert getattr(DSTreeMaximal, method) is getattr(DSTree, method), method
    miner = DSTreeMaximal(None, 0.5, 1, 2)
    for minimum in (0, 1, -0.1, float("nan"), float("inf"), True, "0.2"):
        with pytest.raises(ValueError, match="minSup"):
            miner.queryPatterns(minSup=minimum)
    with pytest.raises(ValueError, match="frame range"):
        miner.queryPatterns(-1, 0, minSup="invalid")


def test_query_min_sup_preserves_stored_state():
    source = pd.DataFrame({"Transactions": _hand_batch()})
    miner = DSTreeMaximal(source, 0.4, 1, 5).mine()
    root, patterns = miner._root, miner.getPatterns()
    saved = dict(patterns)
    nodes = [(node, node.parent, dict(node.children), list(node.counts)) for node in miner._nodes()]
    state = (miner.minSup, miner._min_sup, miner.getRuntime(), miner.getMemoryUSS(),
             miner.getMemoryRSS(), miner._batch_count, list(miner._batches),
             miner.getTimeFrames(), miner.getFrameWeights())
    assert miner.queryPatterns(minSup=0.6) == {("a", "b"): 3}
    assert miner.queryPatterns(minSup=0.9) == {("b",): 5}
    assert (miner.minSup, miner._min_sup, miner.getRuntime(), miner.getMemoryUSS(),
            miner.getMemoryRSS(), miner._batch_count, list(miner._batches),
            miner.getTimeFrames(), miner.getFrameWeights()) == state
    assert miner.getPatterns() is patterns and patterns == saved
    assert miner._root is root and list(miner._nodes()) == [node for node, _, _, _ in nodes]
    for node, parent, children, counts in nodes:
        assert node.parent is parent and node.children == children and node.counts == counts
    assert miner.queryPatterns() == miner.queryPatterns(minSup=None) == saved
    assert saved == {("a", "b", "c"): 2, ("b", "d"): 2}
    miner.mine()
    assert miner.getPatterns() == saved


def test_mine_stores_maximal_patterns_and_pami_outputs(tmp_path, capsys):
    source = tmp_path / "transactions.txt"
    source.write_text("a;b\na;b;c\na;b;c\nb;d\nb;d\n", encoding="utf-8")
    miner = DSTreeMaximal(source, 0.4, 1, 5, sep=";")
    assert miner.getPatterns() == {}
    assert miner.mine() is miner
    expected = {("a", "b", "c"): 2, ("b", "d"): 2}
    assert miner.getPatterns() == miner.queryPatterns() == expected
    assert miner.getTimeFrames() == [(0, 1)] and miner.getFrameWeights() == [5]
    frame = miner.getPatternsAsDataFrame()
    assert list(frame.columns) == ["Patterns", "Support"]
    assert dict(zip(frame["Patterns"], frame["Support"])) == {"a;b;c": 2, "b;d": 2}
    output = tmp_path / "patterns.txt"
    miner.save(output)
    assert set(output.read_text(encoding="utf-8").splitlines()) == {"a;b;c:2", "b;d:2"}
    assert miner.getRuntime() >= 0 and miner.getMemoryUSS() >= 0 and miner.getMemoryRSS() > 0
    miner.printResults()
    assert "Total number of patterns: 2" in capsys.readouterr().out
    with pytest.deprecated_call():
        assert miner.startMine() is miner
    assert miner.getPatterns() == expected


def test_differential_against_plain_dstree_for_a_few_seeds():
    for seed in (0, 7, 19):
        minimum, batches = _random_stream(seed)
        for window_size in (1, 3):
            miner = DSTreeMaximal(None, minimum, window_size, 20)
            plain = DSTree(None, minimum, window_size, 20)
            for batch_no, batch in enumerate(batches):
                miner.processBatch(batch)
                plain.processBatch(batch)
                assert miner.getTimeFrames() == plain.getTimeFrames()
                assert miner.getFrameWeights() == plain.getFrameWeights()
                count = len(miner.getTimeFrames())
                for start in range(count):
                    for end in range(start + 1, count + 1):
                        for query_minimum in (None, 0.05, 0.1, 0.2, 1 / 3, 0.5, 0.9):
                            frequent = plain.queryPatterns(start, end, minSup=query_minimum)
                            expected = _naive_maximal(frequent)
                            actual = miner.queryPatterns(start, end, minSup=query_minimum)
                            message = (f"seed={seed}, windowSize={window_size}, batch={batch_no}, "
                                       f"range=({start}, {end}), minSup={query_minimum}")
                            assert actual == expected, message


@pytest.mark.slow
@pytest.mark.parametrize("window_size", [1, 2, 3, 5])
def test_random_stream_exact_maximal_oracle(window_size):
    for seed in range(100):
        minimum, batches = _random_stream(seed)
        miner = DSTreeMaximal(None, minimum, window_size, 20)
        exact_batches = []
        for batch_no, batch in enumerate(batches):
            exact_batches.append(supports([batch], 0, 1))
            miner.processBatch(batch)
            frames = miner.getTimeFrames()
            for start in range(len(frames)):
                for end in range(start + 1, len(frames) + 1):
                    first, last = frames[end - 1][0], frames[start][1]
                    true = Counter()
                    for exact in exact_batches[first:last]:
                        true.update(exact)
                    weight = sum(len(batch) for batch in batches[first:last])
                    for query_minimum in (0.05, 0.1, 0.2, 1 / 3, 0.5, 0.9):
                        threshold = Fraction(str(query_minimum)) * weight
                        frequent = {pattern: count for pattern, count in true.items() if count >= threshold}
                        expected = _naive_maximal(frequent)
                        actual = miner.queryPatterns(start, end, minSup=query_minimum)
                        message = (f"seed={seed}, windowSize={window_size}, batch={batch_no}, "
                                   f"range=({start}, {end}), minSup={query_minimum}, W={weight}")
                        assert actual == expected, message
