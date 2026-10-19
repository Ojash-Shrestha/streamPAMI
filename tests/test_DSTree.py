"""Exact window queries and canonical-prefix count invariants for DSTree."""
from collections import Counter
from fractions import Fraction
from io import BytesIO
import random

import pandas as pd
import pytest

from streamPAMI.frequentPattern.basic.DSTree import DSTree
from tests.bruteForce import supports


def _assert_tree(miner, batches, context=""):
    current = batches[-miner.windowSize:]
    expected = []
    for batch in current:
        prefixes = Counter({(): len(batch)})
        for transaction in batch:
            items = sorted(set(transaction))
            # These are root-to-node prefixes, deliberately not subsets.
            for length in range(1, len(items) + 1):
                prefixes[tuple(items[:length])] += 1
        expected.append(prefixes)

    paths = set()
    pending = [(miner._root, ())]
    while pending:
        node, path = pending.pop()
        paths.add(path)
        message = f"{context}, path={path}, counts={node.counts}"
        assert len(node.counts) == len(current), message
        assert any(node.counts), f"all-zero node: {message}"
        assert node.counts == [prefixes[path] for prefixes in expected], message
        assert list(path) == sorted(set(path)), message
        for item, child in node.children.items():
            assert child.parent is node and child.item == item, message
            pending.append((child, path + (item,)))
    assert paths == set().union(*(prefixes.keys() for prefixes in expected)), context

    indices = list(range(max(0, len(batches) - miner.windowSize), len(batches)))
    assert miner.getTimeFrames() == [(index, index + 1) for index in reversed(indices)], context
    assert miner.getFrameWeights() == [len(batches[index]) for index in reversed(indices)], context


def test_hand_example_expires_oldest_batch():
    miner = DSTree(None, 0.25, windowSize=2, batchSize=3)
    batches = [
        [["b", "a", "a"], ["a"], []],
        [["b"], ["a", "b"]],
        [["c"], ["b"], []],
    ]
    # Batch 0: a=2, b=1, ab=1, W=3; the duplicate a counts once.
    miner.processBatch(batches[0])
    assert miner.queryPatterns() == {("a",): 2, ("b",): 1, ("a", "b"): 1}
    _assert_tree(miner, batches[:1])
    # Batches 0+1: a=3, b=3, ab=2, W=5, threshold=1.25.
    miner.processBatch(batches[1])
    assert miner.queryPatterns() == {("a",): 3, ("b",): 3, ("a", "b"): 2}
    _assert_tree(miner, batches[:2])
    # Batch 0 leaves. Batches 1+2: a=1, b=3, c=1, ab=1, W=5.
    miner.processBatch(batches[2])
    assert miner.getTimeFrames() == [(2, 3), (1, 2)]
    assert miner.getFrameWeights() == [3, 2]
    assert miner.queryPatterns() == {("b",): 3}
    assert miner.queryPatterns(0, 1) == {("b",): 1, ("c",): 1}
    assert miner.queryPatterns(1, 2) == {("a",): 1, ("b",): 2, ("a", "b"): 1}
    _assert_tree(miner, batches)


def test_canonical_order_is_fixed_and_items_are_de_duplicated():
    miner = DSTree(None, 0.2, 2, 2)
    batches = [[["2", "10", "2"], ["2"]], [["10"], ["2", "10"]]]
    for index, batch in enumerate(batches):
        miner.processBatch(batch)
        _assert_tree(miner, batches[:index + 1])
    assert miner._root.children["10"].children["2"].counts == [1, 1]
    assert "10" not in miner._root.children["2"].children


def test_eagerly_removes_expired_prefixes():
    miner = DSTree(None, 0.2, 1, 2)
    batches = [[["a", "b"], ["a"]], [["c"]]]
    for index, batch in enumerate(batches):
        miner.processBatch(batch)
        _assert_tree(miner, batches[:index + 1])
    assert set(miner._root.children) == {"c"}


def test_query_sums_queried_slots_not_just_newest():
    miner = DSTree(None, 0.5, 2, 3)
    miner.processBatch([["a"], ["a"], ["a"]])
    miner.processBatch([["b"], ["b"]])
    assert miner.queryPatterns(1, 2) == {("a",): 3}
    assert miner.queryPatterns(0, 1) == {("b",): 2}
    assert miner.queryPatterns() == {("a",): 3}


@pytest.mark.parametrize("sigma,weight,at_count", [(0.25, 4, 1), (0.25, 8, 2), (0.07, 100, 7)])
def test_inclusive_exact_threshold_and_one_below(sigma, weight, at_count):
    miner = DSTree(None, sigma, 2, weight)
    miner.processBatch([["below"]])
    batch = ([["at"] for _ in range(at_count)]
             + [["below"] for _ in range(at_count - 1)]
             + [[] for _ in range(weight - 2 * at_count + 1)])
    miner.processBatch(batch)
    assert miner.queryPatterns(0, 1) == {("at",): at_count}


def test_file_mining_and_pami_output_format(tmp_path, capsys):
    source = tmp_path / "transactions.txt"
    source.write_text("old\nold\na;b\n\nb\n\n", encoding="utf-8")
    miner = DSTree(source, 0.25, 2, 2, sep=";")
    assert miner.epsilon is None
    miner.mine()
    expected = {("a",): 1, ("b",): 2, ("a", "b"): 1}
    assert miner.getPatterns() == expected
    assert miner.getTimeFrames() == [(2, 3), (1, 2)]
    assert miner.getFrameWeights() == [2, 2]
    frame = miner.getPatternsAsDataFrame()
    assert list(frame.columns) == ["Patterns", "Support"]
    assert dict(zip(frame["Patterns"], frame["Support"])) == {"a": 1, "b": 2, "a;b": 1}
    output = tmp_path / "patterns.txt"
    miner.save(output)
    assert set(output.read_text(encoding="utf-8").splitlines()) == {"a:1", "b:2", "a;b:1"}
    assert miner.getRuntime() >= 0
    assert miner.getMemoryRSS() > 0
    assert miner.getMemoryUSS() >= 0
    miner.printResults()
    assert "Total number of patterns: 3" in capsys.readouterr().out
    with pytest.deprecated_call():
        miner.startMine()
    assert miner.getPatterns() == expected
    assert miner.getTimeFrames() == [(2, 3), (1, 2)]


def test_empty_transactions_count_towards_denominator():
    miner = DSTree(None, 0.5, 2, 4)
    miner.processBatch([[], ["x"], [], []])
    assert miner.getFrameWeights() == [4]
    assert miner._root.counts == [4]
    assert miner.queryPatterns() == {}
    frame = pd.DataFrame({"Transactions": [[], ["x"], "", []]})
    from_frame = DSTree(frame, 0.5, 2, 4)
    from_frame.mine()
    assert from_frame.getFrameWeights() == [4]
    assert from_frame.getPatterns() == {}


def test_mine_keeps_final_partial_batch():
    source = pd.DataFrame({"Transactions": [["old"], ["b"], [], ["a"], []]})
    miner = DSTree(source, 0.25, 2, 2)
    miner.mine()
    assert miner.getTimeFrames() == [(2, 3), (1, 2)]
    assert miner.getFrameWeights() == [1, 2]
    assert miner.getPatterns() == {("a",): 1}


def test_url_input_preserves_blank_transactions(monkeypatch):
    urls = []

    def open_stream(url):
        urls.append(url)
        return BytesIO(b"x\n\nx\n\n")

    monkeypatch.setattr("streamPAMI.frequentPattern.basic.abstract.urlopen", open_stream)
    miner = DSTree("https://example.com/stream.txt", 0.5, 2, 2)
    miner.mine()
    assert urls == ["https://example.com/stream.txt"]
    assert miner.getFrameWeights() == [2, 2]
    assert miner.getPatterns() == {("x",): 2}


def test_process_batch_never_mines(monkeypatch):
    miner = DSTree(None, 0.2, 1, 2)

    def unexpected_mining(*args, **kwargs):
        pytest.fail("processBatch must only maintain the prefix tree")

    monkeypatch.setattr(miner, "queryPatterns", unexpected_mining)
    monkeypatch.setattr(miner, "_conditional_headers", unexpected_mining)
    miner.processBatch([["a", "b"], []])
    miner.processBatch([["c"], []])
    assert miner.getPatterns() == {}
    _assert_tree(miner, [[["a", "b"], []], [["c"], []]])


def test_queries_do_not_modify_the_window_tree():
    miner = DSTree(None, 0.2, 2, 2)
    batches = [[["a", "b"], ["a"]], [["b", "c"], []]]
    for batch in batches:
        miner.processBatch(batch)
    miner.queryPatterns()
    miner.queryPatterns(1, 2)
    miner.queryPatterns(0, 1)
    _assert_tree(miner, batches)
    batches[0][0].clear()
    assert miner.queryPatterns() == {("a",): 2, ("b",): 2, ("c",): 1,
                                      ("a", "b"): 1, ("b", "c"): 1}


def test_parameter_and_frame_validation(tmp_path):
    for sigma in (0, 1, -0.1, float("nan"), float("inf"), "0.2", None):
        with pytest.raises(ValueError):
            DSTree(None, sigma, 2, 2)
    for window_size in (0, -1, 1.5, True, "2", None):
        with pytest.raises(ValueError):
            DSTree(None, 0.2, window_size, 2)
    for batch_size in (0, -1, 1.5, True, "2", None):
        with pytest.raises(ValueError):
            DSTree(None, 0.2, 2, batch_size)
    miner = DSTree(None, 0.2, 2, 2)
    assert miner.queryPatterns() == {}
    miner.processBatch([["a"]])
    assert miner.queryPatterns(0, 0) == miner.queryPatterns(1, 1) == {}
    for start, end in ((-1, 1), (1, 0), (0, 2), (0.5, 1), (False, 1)):
        with pytest.raises(ValueError):
            miner.queryPatterns(start, end)
    with pytest.raises(FileNotFoundError):
        DSTree(tmp_path / "absent.txt", 0.2, 2, 2).mine()
    with pytest.raises(ValueError, match="Transactions"):
        DSTree(pd.DataFrame({"wrong": []}), 0.2, 2, 2).mine()


def _random_stream(seed):
    rng = random.Random(seed)
    items = [str(index) for index in range(rng.randint(6, 8))]
    sigma = rng.choice((0.1, 0.2, 0.25, 0.5))
    batch_count = rng.randint(6, 10)
    changes = set(rng.sample(range(1, batch_count), rng.randint(1, min(4, batch_count - 1))))
    rates = [rng.uniform(0, 0.5) for _ in items]
    batches = []
    for batch_no in range(batch_count):
        if batch_no in changes:
            rates = [rng.uniform(0, 0.5) for _ in items]
        size = rng.choice((1, 5, 20, 50, 200))
        batch = [[]]  # Every batch exercises an empty transaction, including size 1.
        for _ in range(size - 1):
            transaction = [item for item, rate in zip(items, rates) if rng.random() < rate]
            if transaction and rng.random() < 0.2:
                transaction.append(rng.choice(transaction))
            rng.shuffle(transaction)
            batch.append(transaction)
        batches.append(batch)
    return sigma, batches


@pytest.mark.slow
@pytest.mark.parametrize("window_size", [1, 2, 3, 5])
def test_random_stream_exact_oracle_and_tree_invariants(window_size):
    for seed in range(100):
        sigma, batches = _random_stream(seed)
        miner = DSTree(None, sigma, window_size, 20)
        exact_batches = []
        for batch_no, batch in enumerate(batches):
            # Exact supports add over batches. Cache only brute-force oracle results.
            exact_batches.append(supports([batch], 0, 1))
            miner.processBatch(batch)
            context = f"seed={seed}, windowSize={window_size}, batch={batch_no}"
            _assert_tree(miner, batches[:batch_no + 1], context)
            frames = miner.getTimeFrames()
            for start in range(len(frames)):
                for end in range(start + 1, len(frames) + 1):
                    first, last = frames[end - 1][0], frames[start][1]
                    true = Counter()
                    for exact in exact_batches[first:last]:
                        true.update(exact)
                    weight = sum(len(transactions) for transactions in batches[first:last])
                    threshold = Fraction(str(sigma)) * weight
                    expected = {pattern: count for pattern, count in true.items() if count >= threshold}
                    actual = miner.queryPatterns(start, end)
                    assert actual == expected, f"{context}, range=({start}, {end}), W={weight}"
