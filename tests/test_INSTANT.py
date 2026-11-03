"""INSTANT's literal figure states, empirical completeness and antichains."""
from collections import Counter
from copy import deepcopy
from io import BytesIO
from itertools import combinations
import random

import pandas as pd
import pytest

from streamPAMI.frequentPattern.maximal import INSTANT as algorithm
from streamPAMI.frequentPattern.maximal.INSTANT import INSTANT
from tests.bruteForce import supports


def _paper_stream():
    return [list(transaction) for transaction in ("abc", "acd", "abcd", "abd", "abcd",
                                                 "acd", "abcde", "abcefhl")]


def _antichain(collection, name, context):
    assert all(isinstance(pattern, frozenset) and pattern for pattern in collection), (context, name)
    for left, right in combinations(collection, 2):
        assert not (left <= right or right <= left), (
            f"{context}, {name}: comparable itemsets {sorted(left)} and {sorted(right)}")


def _assert_invariants(miner, true, context):
    assert set(miner._U) == set(range(1, miner.minSup)), context
    _antichain(miner._F, "F", context)
    for level, collection in miner._U.items():
        _antichain(collection, f"U[{level}]", context)
    for pattern in miner._F:
        assert true[tuple(sorted(pattern))] >= miner.minSup, (context, pattern)


def _naive_maximal(counts, delta):
    frequent = {pattern: set(pattern) for pattern, count in counts.items() if count >= delta}
    return {pattern: None for pattern, items in frequent.items()
            if not any(items < other for other in frequent.values())}


def test_paper_table_one_f_and_figure_u_states():
    miner = INSTANT(None, 3, 3)
    expected = [(), (), ("ac",), ("ab", "ac", "ad"), ("abc", "abd", "acd"),
                ("abc", "abd", "acd"), ("abcd",), ("abcd",)]
    seen = []
    for index, transaction in enumerate(_paper_stream(), 1):
        miner.processBatch([transaction])
        seen.append([transaction])
        expected_f = {frozenset(pattern) for pattern in expected[index - 1]}
        assert miner._F == expected_f, f"transaction={index}"
        assert miner.queryPatterns() == {tuple(sorted(pattern)): None for pattern in expected_f}
        _assert_invariants(miner, supports(seen, 0, len(seen)), f"transaction={index}")
        if index == 4:
            assert miner._U[2] == {frozenset("abc"), frozenset("abd"), frozenset("acd")}
            assert miner._U[1] == {frozenset("abcd")}
        if index == 5:
            assert miner._U[2] == {frozenset("abcd")}
            # Table 1 adds pruning and shows U[1] empty. Figs. 2-3 retain abcd;
            # this test deliberately follows the figures, including that entry.
            assert miner._U[1] == {frozenset("abcd")}
    assert miner.getStreamLength() == 8 and miner.getPatterns() == {}


def test_theorem_two_counterexample_is_documented_state():
    transactions = [list(transaction) for transaction in ("b", "c", "b", "c", "bc", "bc", "b", "a")]
    miner = INSTANT(None, 4, 8)
    miner.processBatch(transactions)
    true = supports([transactions], 0, 1)
    assert frozenset("bc") in miner._U[1]
    assert true[("b", "c")] == 2  # Not support 1 as Theorem 2 claims for U[1].
    assert miner.queryPatterns() == {("b",): None, ("c",): None}
    _assert_invariants(miner, true, "Theorem 2 counterexample")


def test_delta_one_empty_transactions_and_duplicate_items():
    miner = INSTANT(None, 1, 2)
    assert miner._U == {} and miner.queryPatterns() == {}
    batches = [[[], ["b", "a", "a"]], [["b"], ["c"]], [["a", "b", "c"], []]]
    seen = []
    for batch in batches:
        seen.append(batch)
        miner.processBatch(batch)
        true = supports(seen, 0, len(seen))
        assert miner.queryPatterns() == _naive_maximal(true, 1)
        _assert_invariants(miner, true, "delta=1")
    assert miner.getStreamLength() == 6
    assert miner.queryPatterns() == {("a", "b", "c"): None}
    assert miner._U == {}


def test_delta_two_initialises_u_one_and_uses_previous_state():
    miner = INSTANT(None, 2, 1)
    assert miner._U == {1: set()}
    miner.processBatch([["a", "a", "b"]])
    assert miner.queryPatterns() == {}
    assert miner._U[1] == {frozenset("ab")}
    miner.processBatch([["a", "b"]])
    assert miner.queryPatterns() == {("a", "b"): None}


def test_empty_and_contained_transactions_leave_f_and_u_unchanged():
    miner = INSTANT(None, 3, 3)
    miner.processBatch([list("abc") for _ in range(3)])
    before = deepcopy((miner._F, miner._U))
    miner.processBatch([[], list("ab"), list("a"), list("abc")])
    assert (miner._F, miner._U) == before
    assert miner.getStreamLength() == 7
    assert miner.queryPatterns() == {("a", "b", "c"): None}


@pytest.mark.parametrize("minimum", [0, -1, True, False, "3", None, 0.5, 3.0,
                                     float("nan"), float("inf")])
def test_min_sup_requires_a_fixed_integer_count(minimum):
    with pytest.raises(ValueError, match="fixed count over the whole stream.*fraction"):
        INSTANT(None, minimum, 2)


def test_batch_validation_no_query_arguments_and_unknown_supports():
    assert algorithm.INSTANT is INSTANT
    for size in (0, -1, True, 1.5, "2", None):
        with pytest.raises(ValueError, match="batchSize"):
            INSTANT(None, 2, size)
    miner = INSTANT(None, 1, 2)
    for bad in (None, ([], [])):
        with pytest.raises(TypeError):
            miner.processBatch(bad)
    with pytest.raises(ValueError):
        miner.processBatch([])
    miner.processBatch([["a"], []])
    for arguments in ((0,), (0, 1), (None,)):
        with pytest.raises(TypeError):
            miner.queryPatterns(*arguments)
    with pytest.raises(TypeError):
        miner.queryPatterns(minSup=1)
    assert miner.minSup == 1 and isinstance(miner.minSup, int)
    assert miner.getStreamLength() == 2
    result = miner.queryPatterns()
    assert result == {("a",): None} and all(value is None for value in result.values())
    assert miner.getPatterns() == {}


def test_file_mine_skips_blanks_and_saves_patterns_only(tmp_path, capsys):
    source = tmp_path / "stream.txt"
    source.write_text("\n\n" + "\n\n".join(";".join(tx) for tx in _paper_stream()) + "\n\n", encoding="utf-8")
    miner = INSTANT(source, 3, 3, sep=";")
    assert list(miner.getPatternsAsDataFrame().columns) == ["Patterns"]
    assert miner.mine() is miner
    assert miner.getStreamLength() == 8  # Replay batches are 3, 3 and a final 2.
    assert miner.getPatterns() == {("a", "b", "c", "d"): None}
    frame = miner.getPatternsAsDataFrame()
    assert list(frame.columns) == ["Patterns"]
    assert frame["Patterns"].tolist() == ["a;b;c;d"]
    output = tmp_path / "patterns.txt"
    miner.save(output)
    assert output.read_text(encoding="utf-8") == "a;b;c;d\n"
    assert miner.getRuntime() >= 0 and miner.getMemoryUSS() >= 0 and miner.getMemoryRSS() > 0
    miner.printResults()
    assert "Total number of patterns: 1" in capsys.readouterr().out
    with pytest.deprecated_call():
        assert miner.startMine() is miner
    assert miner.getStreamLength() == 8 and miner.getPatterns() == {("a", "b", "c", "d"): None}


def test_dataframe_url_empty_input_and_query_state(tmp_path, monkeypatch):
    source = pd.DataFrame({"Transactions": [[], "a\tb", ["a", "b"], []]})
    miner = INSTANT(source, 2, 3).mine()
    assert miner.getStreamLength() == 4
    assert miner.getPatterns() == {("a", "b"): None}
    snapshot = deepcopy((miner._F, miner._U, miner.getPatterns(), miner.getStreamLength(),
                         miner.getRuntime(), miner.getMemoryUSS(), miner.getMemoryRSS()))
    result = miner.queryPatterns()
    result.clear()
    assert (miner._F, miner._U, miner.getPatterns(), miner.getStreamLength(),
            miner.getRuntime(), miner.getMemoryUSS(), miner.getMemoryRSS()) == snapshot
    monkeypatch.setattr("streamPAMI.frequentPattern.basic.abstract.urlopen",
                        lambda url: BytesIO(b"\na\tb\n\na\tb\n\n"))
    from_url = INSTANT("https://example.com/stream.txt", 2, 3).mine()
    assert from_url.getStreamLength() == 2 and from_url.getPatterns() == {("a", "b"): None}
    empty = INSTANT(pd.DataFrame({"Transactions": []}), 2, 3).mine()
    assert empty.getStreamLength() == 0 and empty.getPatterns() == {}
    assert list(empty.getPatternsAsDataFrame().columns) == ["Patterns"]
    with pytest.raises(FileNotFoundError):
        INSTANT(tmp_path / "absent.txt", 2, 3).mine()
    with pytest.raises(ValueError, match="Transactions"):
        INSTANT(pd.DataFrame({"wrong": []}), 2, 3).mine()


def _random_stream(seed):
    rng = random.Random(seed)
    items = [f"item_{index}" for index in range(rng.randint(3, 8))]
    delta = rng.randint(1, 9)
    hot = set(rng.sample(items, rng.randint(2, min(4, len(items)))))
    transactions = []
    for _ in range(rng.randint(5, 40)):
        if seed >= 150 and rng.random() < 0.75:
            chosen = [item for item in items if item in hot or rng.random() < 0.15]
        else:
            chosen = [item for item in items if rng.random() < 0.5]
        if chosen and rng.random() < 0.15:
            chosen.append(rng.choice(chosen))
        rng.shuffle(chosen)
        transactions.append(chosen)
    batches = []
    offset = 0
    while offset < len(transactions):
        size = rng.randint(1, 5)
        batches.append(transactions[offset:offset + size])
        offset += size
    return delta, batches


@pytest.mark.slow
def test_random_stream_oracle_and_antichains():
    deltas = set()
    for seed in range(300):
        delta, batches = _random_stream(seed)
        deltas.add(delta)
        miner = INSTANT(None, delta, 5)
        true = Counter()
        length = 0
        for batch_no, batch in enumerate(batches):
            true.update(supports([batch], 0, 1))
            length += len(batch)
            miner.processBatch(batch)
            context = f"seed={seed}, delta={delta}, batch={batch_no}, N={length}"
            assert miner.getStreamLength() == length, context
            assert miner.queryPatterns() == _naive_maximal(true, delta), context
            _assert_invariants(miner, true, context)
    assert deltas == set(range(1, 10))
