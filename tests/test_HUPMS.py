"""Independent utility/TWU oracles, HUS-tree invariants and PAMI input/output."""
from collections import defaultdict
from copy import deepcopy
from fractions import Fraction
from io import BytesIO
import random

import pandas as pd
import pytest

from streamPAMI.highUtilityPattern.basic import HUPMS as algorithm
from streamPAMI.highUtilityPattern.basic.HUPMS import HUPMS
from tests.bruteForceUtility import utilities, utility_counts, twu


def _reported(value):
    return value.numerator if value.denominator == 1 else float(value)


def _total(batch):
    return sum((sum((Fraction(str(value)) for value in transaction.values()), Fraction(0))
                for transaction in batch), Fraction(0))


def _paper_batches():
    profits = {"a": 2, "b": 6, "c": 3, "d": 8, "e": 10}
    quantities = [{"d": 3, "e": 4}, {"a": 2, "c": 8}, {"b": 2, "c": 8, "d": 2},
                  {"a": 4, "b": 8}, {"b": 3, "e": 2}, {"a": 6, "b": 5, "d": 4},
                  {"a": 2, "b": 2, "c": 7}, {"a": 4, "b": 4, "d": 5, "e": 3}]
    transactions = [{item: quantity * profits[item] for item, quantity in transaction.items()}
                    for transaction in quantities]
    return [transactions[index:index + 2] for index in range(0, len(transactions), 2)]


def _assert_tree(miner, batches, context=""):
    expected = []
    for batch in batches[-miner.windowSize:]:
        prefixes = defaultdict(Fraction)
        prefixes[()] = _total(batch)
        for transaction in batch:
            path = sorted(transaction)
            total = sum((Fraction(str(value)) for value in transaction.values()), Fraction(0))
            for size in range(1, len(path) + 1):
                prefixes[tuple(path[:size])] += total
        expected.append(prefixes)
    pending, paths = [(miner._root, ())], set()
    while pending:
        node, path = pending.pop()
        paths.add(path)
        message = f"{context}, path={path}, slots={node.twu}"
        assert len(node.twu) == len(expected), message
        assert all(isinstance(value, Fraction) for value in node.twu), message
        assert node.twu == [prefixes.get(path, Fraction(0)) for prefixes in expected], message
        # The root is a structural sentinel, so an all-empty window has a zero
        # root but no item nodes. Every retained item node must be non-zero.
        if node is not miner._root:
            assert any(node.twu), message
        assert all(left < right for left, right in zip(path, path[1:])), message
        for slot, value in enumerate(node.twu):
            assert value >= sum((child.twu[slot] for child in node.children.values()), Fraction(0)), message
        for item, child in node.children.items():
            assert child.parent is node and child.item == item, message
            pending.append((child, path + (item,)))
    assert paths == set().union(*(prefixes.keys() for prefixes in expected)), context
    indices = range(max(0, len(batches) - miner.windowSize), len(batches))
    assert miner.getTimeFrames() == [(index, index + 1) for index in reversed(indices)], context
    assert miner.getFrameWeights() == [_reported(_total(batches[index])) for index in reversed(indices)], context
    retained = [batch for _, _, batch in miner._batches]
    converted = [[{item: Fraction(str(value)) for item, value in tx.items()} for tx in batch]
                 for batch in batches[-miner.windowSize:]]
    assert retained == converted, context


def test_utility_oracle_hand_computed():
    batches = [[{"a": "2.5", "b": "1.5"}, {}], [{"a": 1, "c": 3}, {"b": 2}]]
    # Transaction totals are 4, 0, 4, 2. Item utilities accumulate only their
    # own values: a=b=3.5, c=3, ab=4, ac=4. TWU instead adds whole totals.
    assert utility_counts(batches, 0, 2) == {("a",): Fraction("3.5"), ("b",): Fraction("3.5"),
                                           ("c",): Fraction(3), ("a", "b"): Fraction(4),
                                           ("a", "c"): Fraction(4)}
    assert utilities(batches, 0, 2, Fraction("3.5")) == {
        ("a",): Fraction("3.5"), ("b",): Fraction("3.5"),
        ("a", "b"): Fraction(4), ("a", "c"): Fraction(4)}
    assert twu(batches, 0, 2) == {("a",): Fraction(8), ("b",): Fraction(6), ("c",): Fraction(4),
                                 ("a", "b"): Fraction(4), ("a", "c"): Fraction(4)}
    assert utilities(batches, 0, 1, Fraction(3)) == {("a", "b"): Fraction(4)}
    assert twu(batches, 1, 2) == {("a",): Fraction(4), ("c",): Fraction(4),
                                 ("a", "c"): Fraction(4), ("b",): Fraction(2)}
    assert utilities(batches, 1, 1, Fraction(0)) == twu(batches, 1, 1) == {}
    long = [[{str(index): 1 for index in range(17)}]]
    for oracle in (utility_counts, twu):
        with pytest.raises(ValueError, match="longer than 16"):
            oracle(long, 0, 1)


def test_paper_example_candidates_and_pre_insertion_slots(monkeypatch):
    batches = _paper_batches()
    miner = HUPMS(None, 0.3, 3, 2)
    insert = miner._insert_transactions
    checked = []

    def inspect_before_insertion(transactions):
        if miner._batch_count == 3:
            slots = list(miner._root.children["a"].twu)
            assert slots == [Fraction(56), Fraction(74), Fraction(0)]
            checked.append(slots)
        insert(transactions)

    monkeypatch.setattr(miner, "_insert_transactions", inspect_before_insertion)
    for index, batch in enumerate(batches):
        miner.processBatch(batch)
        _assert_tree(miner, batches[:index + 1])
        first = max(0, index - 2)
        threshold = Fraction("0.3") * sum((_total(part) for part in batches[first:index + 1]), Fraction(0))
        assert miner.queryPatterns() == utilities(batches, first, index + 1, threshold)
        if index == 2:
            assert sum(miner.getFrameWeights()) == 312
            assert miner.queryPatterns() == {("b",): 108, ("a", "b"): 98}
    assert checked == [[Fraction(56), Fraction(74), Fraction(0)]]
    assert miner.getTimeFrames() == [(3, 4), (2, 3), (1, 2)]
    assert miner.getFrameWeights() == [139, 112, 108]
    assert miner.queryPatterns() == {("b", "d"): 154, ("a", "b", "d"): 146,
                                      ("a", "b"): 146, ("b",): 144}
    threshold = Fraction("0.3") * Fraction(359)
    assert threshold == Fraction("107.7")
    candidates = miner._candidate_patterns(0, 3, threshold)
    assert candidates == {("b", "e"): Fraction(140), ("e",): Fraction(140),
                          ("a", "d"): Fraction(176), ("b", "d"): Fraction(228),
                          ("d",): Fraction(228), ("a", "b", "d"): Fraction(176),
                          ("a", "b"): Fraction(269), ("b",): Fraction(359),
                          ("a",): Fraction(269)}


def test_low_utility_subsets_must_not_prune_high_utility_superset():
    miner = HUPMS(None, 0.75, 2, 1)
    miner.processBatch([{"a": 4, "b": 4}])
    # a and b each have utility 4 below the threshold 6; their TWU is 8,
    # and ab's utility 8 qualifies. Actual utility cannot prune growth.
    assert miner._candidate_patterns(0, 1, Fraction(6)) == {
        ("a",): Fraction(8), ("b",): Fraction(8), ("a", "b"): Fraction(8)}
    assert miner.queryPatterns() == {("a", "b"): 8}


def test_second_phase_sums_item_utilities_not_transaction_utilities():
    miner = HUPMS(None, 0.1, 1, 2)
    miner.processBatch([{"a": 1, "b": 9}, {"a": 2}])
    assert miner.queryPatterns() == {("a",): 3, ("b",): 9, ("a", "b"): 10}


@pytest.mark.parametrize("minimum,at,other", [(0.3, 3, 7), (0.07, 7, 93)])
def test_exact_inclusive_utility_threshold(minimum, at, other):
    miner = HUPMS(None, minimum, 1, 1)
    miner.processBatch([{"at": at, "other": other}])
    assert Fraction(str(minimum)) * (Fraction(at) + Fraction(other)) == Fraction(at)
    assert miner.queryPatterns()[("at",)] == at


def test_queried_range_uses_its_own_total_utility():
    miner = HUPMS(None, 0.9, 2, 1)
    miner.processBatch([{"x": 3, "f": 7}])
    miner.processBatch([{"y": 8, "f": 12}])
    assert miner.queryPatterns(1, 2, minUtil=0.3)[("x",)] == 3
    assert miner.queryPatterns(0, 1, minUtil=0.4)[("y",)] == 8
    assert ("x",) not in miner.queryPatterns(minUtil=0.3)


def test_zero_utility_windows_and_eager_expiry():
    miner = HUPMS(None, 0.2, 1, 2)
    assert miner.queryPatterns() == {}
    batches = [[{"a": 2, "b": 3}], [{}, {}], [{"c": "2.5"}], [{}]]
    for index, batch in enumerate(batches):
        miner.processBatch(batch)
        _assert_tree(miner, batches[:index + 1])
        if not _total(batch):
            assert miner.queryPatterns() == {} and not miner._root.children
    assert miner.getTimeFrames() == [(3, 4)] and miner.getFrameWeights() == [0]
    assert miner.queryPatterns(0, 0, minUtil=0.1) == {}


def test_query_threshold_does_not_change_state_or_mine_default():
    batches = _paper_batches()
    rows = [tx for batch in batches for tx in batch]
    source = pd.DataFrame({"Transactions": [list(tx) for tx in rows],
                           "Utilities": [list(tx.values()) for tx in rows]})
    miner = HUPMS(source, 0.3, 3, 2).mine()
    root, patterns = miner._root, miner.getPatterns()
    saved_patterns = dict(patterns)
    nodes = [(node, node.parent, dict(node.children), list(node.twu)) for node in miner._nodes()]
    state = (miner.minUtil, miner._min_util, miner.getRuntime(), miner.getMemoryUSS(),
             miner.getMemoryRSS(), miner._batch_count, deepcopy(list(miner._batches)),
             miner.getTimeFrames(), miner.getFrameWeights())
    assert miner.queryPatterns(minUtil=0.9) == {}
    assert miner.queryPatterns(0, 1, minUtil=0.01)
    assert (miner.minUtil, miner._min_util, miner.getRuntime(), miner.getMemoryUSS(),
            miner.getMemoryRSS(), miner._batch_count, list(miner._batches),
            miner.getTimeFrames(), miner.getFrameWeights()) == state
    assert miner.getPatterns() is patterns and patterns == saved_patterns
    assert miner._root is root and list(miner._nodes()) == [node for node, _, _, _ in nodes]
    for node, parent, children, slots in nodes:
        assert node.parent is parent and node.children == children and node.twu == slots
    assert miner.queryPatterns() == miner.queryPatterns(minUtil=None) == saved_patterns
    miner.mine()
    assert miner.getPatterns() == saved_patterns


def test_process_batch_only_maintains_tree_and_copies_transactions(monkeypatch):
    miner = HUPMS(None, 0.2, 2, 2)

    def unexpected_mining(*args, **kwargs):
        pytest.fail("processBatch must only maintain tree and retained transactions")

    with monkeypatch.context() as patch:
        for name in ("queryPatterns", "_candidate_patterns", "_exact_utilities"):
            patch.setattr(miner, name, unexpected_mining)
        transaction = {"b": 3, "a": 2}
        miner.processBatch([transaction, {}])
        transaction.clear()
    assert miner.queryPatterns() == {("a",): 2, ("b",): 3, ("a", "b"): 5}
    assert miner.getPatterns() == {}


def test_pami_file_dataframe_output_and_final_partial_batch(tmp_path, capsys):
    assert algorithm.HUPMS is HUPMS
    path = tmp_path / "utility.txt"
    path.write_text("\na;b:11:6;5\n\na:2.5:2.5\n:0:\nb:1:1\n", encoding="utf-8")
    miner = HUPMS(path, 0.2, 3, 3, sep=";").mine()
    expected = {("a",): 8.5, ("b",): 6, ("a", "b"): 11}
    assert miner.getPatterns() == expected
    assert isinstance(miner.getPatterns()[("a",)], float)
    assert isinstance(miner.getPatterns()[("a", "b")], int)
    assert miner.getTimeFrames() == [(1, 2), (0, 1)]
    assert miner.getFrameWeights() == [1, 13.5]
    frame = miner.getPatternsAsDataFrame()
    assert list(frame.columns) == ["Patterns", "Utility"]
    assert dict(zip(frame["Patterns"], frame["Utility"])) == {"a": 8.5, "b": 6, "a;b": 11}
    output = tmp_path / "patterns.txt"
    miner.save(output)
    assert set(output.read_text(encoding="utf-8").splitlines()) == {"a:8.5", "b:6", "a;b:11"}
    assert miner.getRuntime() >= 0 and miner.getMemoryUSS() >= 0 and miner.getMemoryRSS() > 0
    miner.printResults()
    assert "Total number of patterns: 3" in capsys.readouterr().out
    with pytest.deprecated_call():
        assert miner.startMine() is miner
    assert miner.getPatterns() == expected
    source = pd.DataFrame({"Transactions": [["a", "b"], ["a"], [], ["b"]],
                           "Utilities": [[6, 5], ["2.5"], [], [1]]})
    from_frame = HUPMS(source, 0.2, 3, 3).mine()
    assert from_frame.getPatterns() == expected and from_frame.getFrameWeights() == [1, 13.5]


def test_url_input_is_offline_and_skips_blank_lines(monkeypatch):
    calls = []

    def open_stream(url):
        calls.append(url)
        return BytesIO(b"\na\tb:11:6\t5\n\na:2.5:2.5\n")

    monkeypatch.setattr("streamPAMI.highUtilityPattern.basic.abstract.urlopen", open_stream)
    miner = HUPMS("https://example.com/utility.txt", 0.2, 2, 2).mine()
    assert calls == ["https://example.com/utility.txt"]
    assert miner.getFrameWeights() == [13.5]
    assert miner.getPatterns() == {("a",): 8.5, ("b",): 5, ("a", "b"): 11}


@pytest.mark.parametrize("bad_line", ["a\tb:3:1", "a\ta:3:1\t2", "a:0:0", "a:-1:-1",
                                      "a:1:bad", "a:1:NaN", "a:1:inf", "a:1:1/0",
                                      "a\tb:4:1\t2", "a:1", "a:bad:1",
                                      "a\tb:0.30000000000000004:0.1\t0.2"])
def test_invalid_file_line_names_physical_line_number(tmp_path, bad_line):
    source = tmp_path / "bad.txt"
    source.write_text("a:1:1\n\n" + bad_line + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"line 3:"):
        HUPMS(source, 0.2, 2, 2).mine()


def test_decimal_input_is_exact_before_reporting(tmp_path):
    source = tmp_path / "decimal.txt"
    source.write_text("a\tb:0.3:0.1\t0.2\n", encoding="utf-8")
    miner = HUPMS(source, 0.1, 1, 1).mine()
    assert miner._root.twu == [Fraction("0.3")]
    transactions = miner._transactions_in_range(0, 1)
    assert transactions == [{"a": Fraction("0.1"), "b": Fraction("0.2")}]
    assert miner._exact_utilities([("a",), ("a", "b")], transactions) == {
        ("a",): Fraction("0.1"), ("a", "b"): Fraction("0.3")}
    assert miner.getPatterns() == {("a",): 0.1, ("b",): 0.2, ("a", "b"): 0.3}
    direct = HUPMS(None, 0.3, 1, 1)
    direct.processBatch([{"a": "0.3", "b": "0.7"}])
    assert direct.queryPatterns() == {("a",): 0.3, ("b",): 0.7, ("a", "b"): 1}


def test_parameter_frame_and_direct_input_validation(tmp_path):
    invalid = (0, 1, -0.1, 1.5, float("nan"), float("inf"), True, False, "0.2", pd.NA)
    for minimum in invalid + (None,):
        with pytest.raises(ValueError, match="minUtil"):
            HUPMS(None, minimum, 2, 2)
    for size in (0, -1, 1.5, True, "2", None):
        with pytest.raises(ValueError):
            HUPMS(None, 0.2, size, 2)
        with pytest.raises(ValueError):
            HUPMS(None, 0.2, 2, size)
    miner = HUPMS(None, 0.2, 1, 2)
    for minimum in invalid:
        with pytest.raises(ValueError, match="minUtil"):
            miner.queryPatterns(minUtil=minimum)
    miner.processBatch([{"a": 1}])
    for start, end in ((-1, 1), (1, 0), (0, 2), (0.5, 1), (False, 1)):
        with pytest.raises(ValueError, match="frame range"):
            miner.queryPatterns(start, end, minUtil="invalid")
    assert miner.queryPatterns(0, 0) == miner.queryPatterns(1, 1) == {}
    for bad in ({"a": 0}, {"a": -1}, {"a": True}, {"a": []}, {"a": float("nan")},
                {"a": float("inf")}, {"a": "bad"}, {1: 1, "1": 2}):
        with pytest.raises(ValueError, match="transaction 2"):
            miner.processBatch([{"b": 1}, bad])
        assert miner.queryPatterns() == {("a",): 1}
    with pytest.raises(ValueError):
        miner.processBatch([])
    for bad in (({},), None, [{}, []]):
        with pytest.raises(TypeError):
            miner.processBatch(bad)
    with pytest.raises(FileNotFoundError):
        HUPMS(tmp_path / "missing.txt", 0.2, 1, 1).mine()
    for source in (pd.DataFrame({"Transactions": [[]]}),
                   pd.DataFrame({"Transactions": [["a", "a"]], "Utilities": [[1, 2]]}),
                   pd.DataFrame({"Transactions": [["a"]], "Utilities": [[]]}),
                   pd.DataFrame({"Transactions": ["a"], "Utilities": [[1]]})):
        with pytest.raises(ValueError):
            HUPMS(source, 0.2, 1, 1).mine()


def _random_stream(seed):
    rng = random.Random(seed)
    items = [f"item_{index}" for index in range(rng.randint(4, 8))]
    profits = {item: rng.choice((1, 2.5, 3, 7, 10)) for item in items}
    batches = []
    for _ in range(rng.randint(4, 9)):
        batch = [{}]
        for _ in range(rng.randint(1, 20) - 1):
            chosen = rng.sample(items, rng.randint(0, min(6, len(items))))
            batch.append({item: rng.randint(1, 10) * profits[item] for item in chosen})
        batches.append(batch)
    return batches


@pytest.mark.slow
@pytest.mark.parametrize("window_size", [1, 2, 3, 5])
def test_random_stream_exact_utilities_candidates_and_tree(window_size):
    for seed in range(100):
        batches = _random_stream(seed)
        miner = HUPMS(None, 0.3, window_size, 10)
        batch_utilities, batch_twu, weights = [], [], []
        for batch_no, batch in enumerate(batches):
            batch_utilities.append(utility_counts([batch], 0, 1))
            batch_twu.append(twu([batch], 0, 1))
            weights.append(_total(batch))
            miner.processBatch(batch)
            context = f"seed={seed}, windowSize={window_size}, batch={batch_no}"
            _assert_tree(miner, batches[:batch_no + 1], context)
            frames = miner.getTimeFrames()
            for start in range(len(frames)):
                for end in range(start + 1, len(frames) + 1):
                    first, last = frames[end - 1][0], frames[start][1]
                    true, weighted = defaultdict(Fraction), defaultdict(Fraction)
                    for exact, bound in zip(batch_utilities[first:last], batch_twu[first:last]):
                        for pattern, utility in exact.items():
                            true[pattern] += utility
                        for pattern, bound_value in bound.items():
                            weighted[pattern] += bound_value
                    total = sum(weights[first:last], Fraction(0))
                    for minimum in (0.01, 0.05, 0.1, 1 / 3, 0.5, 0.9):
                        threshold = Fraction(str(minimum)) * total
                        expected = {pattern: utility for pattern, utility in true.items() if utility >= threshold}
                        expected_candidates = {pattern: value for pattern, value in weighted.items() if value >= threshold}
                        actual = miner.queryPatterns(start, end, minUtil=minimum)
                        candidates = miner._candidate_patterns(start, end, threshold)
                        message = f"{context}, range=({start}, {end}), minUtil={minimum}, threshold={threshold}"
                        # Oracle utilities are integers or halves here, so the
                        # public int/float values compare exactly with Fractions.
                        assert actual == expected, message
                        assert candidates == expected_candidates, message
                        assert actual.keys() <= candidates.keys(), message
                        assert all(type(value) in (int, float) for value in actual.values()), message
