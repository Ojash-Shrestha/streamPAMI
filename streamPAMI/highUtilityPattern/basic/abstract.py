"""PAMI-style interface, utility input and metrics for streaming utility miners."""
from __future__ import annotations

from abc import ABC, abstractmethod
from fractions import Fraction
from pathlib import Path
from time import perf_counter
from urllib.request import urlopen
import warnings

import pandas as pd
import psutil
import validators


class _streamUtilityPatterns(ABC):
    def __init__(self, iFile, minUtil, windowSize, batchSize, sep="\t"):
        self.iFile, self.minUtil = iFile, minUtil
        self.windowSize, self.batchSize, self.sep = windowSize, batchSize, sep
        self._patterns = {}
        self._runtime = self._memory_uss = self._memory_rss = 0

    @abstractmethod
    def mine(self): ...

    @abstractmethod
    def processBatch(self, transactions: list[dict]): ...

    @abstractmethod
    def queryPatterns(self, startFrame=0, endFrame=None, minUtil=None): ...

    @abstractmethod
    def getTimeFrames(self): ...

    @abstractmethod
    def getFrameWeights(self): ...

    def startMine(self):
        warnings.warn("startMine() is deprecated; use mine()", DeprecationWarning, stacklevel=2)
        return self.mine()

    def getPatterns(self):
        return self._patterns

    def getPatternsAsDataFrame(self):
        return pd.DataFrame(
            [(self.sep.join(pattern), utility) for pattern, utility in self._patterns.items()],
            columns=["Patterns", "Utility"],
        )

    def save(self, oFile):
        with open(oFile, "w", encoding="utf-8") as output:
            for pattern, utility in self._patterns.items():
                output.write(self.sep.join(pattern) + ":" + str(utility) + "\n")

    def printResults(self):
        print("Total number of patterns:", len(self._patterns))
        print("Total time taken:", self._runtime)
        print("Total memory in USS:", self._memory_uss)
        print("Total memory in RSS:", self._memory_rss)

    def getRuntime(self):
        return self._runtime

    def getMemoryUSS(self):
        return self._memory_uss

    def getMemoryRSS(self):
        return self._memory_rss

    @staticmethod
    def _validate_min_util(value):
        if (not isinstance(value, (int, float)) or isinstance(value, bool)
                or not 0 < value < 1):
            raise ValueError("minUtil must be a fraction in (0, 1)")
        return Fraction(str(value))

    @staticmethod
    def _utility(value, where):
        if not isinstance(value, (int, float, str)) or isinstance(value, bool):
            raise ValueError(f"{where}: utility must be a positive number")
        try:
            utility = Fraction(str(value))
        except (ValueError, ZeroDivisionError, OverflowError) as error:
            raise ValueError(f"{where}: invalid utility {value!r}") from error
        if utility <= 0:
            raise ValueError(f"{where}: utility must be > 0")
        return utility

    def _pair_transaction(self, items, utilities, where):
        if len(items) != len(utilities):
            raise ValueError(f"{where}: item and utility counts differ")
        transaction = {}
        for item, value in zip(items, utilities):
            item = str(item)
            if item in transaction:
                raise ValueError(f"{where}: repeated item {item!r}")
            transaction[item] = self._utility(value, where)
        return transaction

    def _parse_lines(self, lines):
        for line_number, line in enumerate(lines, 1):
            line = line.strip()
            if not line:
                continue
            where = f"line {line_number}"
            parts = line.split(":")
            if len(parts) != 3:
                raise ValueError(f"{where}: expected items:transactionUtility:itemUtilities")
            items = (parts[0].split(self.sep) if self.sep else parts[0].split()) if parts[0] else []
            values = (parts[2].split(self.sep) if self.sep else parts[2].split()) if parts[2] else []
            transaction = self._pair_transaction(items, values, where)
            try:
                total = Fraction(parts[1])
            except (ValueError, ZeroDivisionError, OverflowError) as error:
                raise ValueError(f"{where}: invalid transactionUtility") from error
            if total != sum(transaction.values(), Fraction(0)):
                raise ValueError(f"{where}: transactionUtility does not equal the item utility sum")
            # Canonical numeric strings preserve exact values through the public
            # processBatch validation; retained transactions contain Fractions.
            yield {item: str(utility) for item, utility in transaction.items()}

    def _iter_transactions(self):
        source = self.iFile
        if isinstance(source, pd.DataFrame):
            if not {"Transactions", "Utilities"}.issubset(source.columns):
                raise ValueError("DataFrame input must contain 'Transactions' and 'Utilities' columns")
            for row_number, (items, values) in enumerate(zip(source["Transactions"], source["Utilities"]), 1):
                where = f"DataFrame row {row_number}"
                if not isinstance(items, list) or not isinstance(values, list):
                    raise ValueError(f"{where}: Transactions and Utilities must be lists")
                transaction = self._pair_transaction(items, values, where)
                yield {item: str(utility) for item, utility in transaction.items()}
            return
        if isinstance(source, (str, Path)):
            value = str(source)
            if validators.url(value):
                with urlopen(value) as response:
                    yield from self._parse_lines(line.decode("utf-8") for line in response)
                return
            path = Path(value)
            if not path.is_file():
                raise FileNotFoundError(value)
            with path.open(encoding="utf-8") as handle:
                yield from self._parse_lines(handle)
            return
        raise TypeError("iFile must be a path, URL, or pandas DataFrame")

    def _capture_metrics(self, started):
        self._runtime = perf_counter() - started
        process = psutil.Process()
        try:
            self._memory_uss = process.memory_full_info().uss
        except (AttributeError, psutil.Error):
            self._memory_uss = 0
        self._memory_rss = process.memory_info().rss
