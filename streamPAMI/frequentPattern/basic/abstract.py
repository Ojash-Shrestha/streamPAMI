"""Common PAMI-style interface for streaming frequent-pattern algorithms."""
from __future__ import annotations

import warnings
from abc import ABC, abstractmethod
from pathlib import Path
from time import perf_counter
from urllib.request import urlopen

import pandas as pd
import psutil
import validators


class _streamFrequentPatterns(ABC):
    def __init__(self, iFile, minSup, epsilon=None, batchSize=None, sep="\t"):
        self.iFile, self.minSup, self.epsilon = iFile, minSup, epsilon
        self.batchSize, self.sep = batchSize, sep
        self._patterns = {}
        self._runtime = self._memory_uss = self._memory_rss = 0

    @abstractmethod
    def mine(self): ...

    @abstractmethod
    def processBatch(self, transactions: list[list[str]]): ...

    @abstractmethod
    def queryPatterns(self, startFrame=0, endFrame=None): ...

    def startMine(self):
        warnings.warn("startMine() is deprecated; use mine()", DeprecationWarning, stacklevel=2)
        return self.mine()

    def getPatterns(self):
        return self._patterns

    def save(self, oFile):
        with open(oFile, "w", encoding="utf-8") as output:
            for pattern, support in self._patterns.items():
                output.write(self.sep.join(pattern) + ":" + str(support) + "\n")

    def getPatternsAsDataFrame(self):
        return pd.DataFrame(
            [(self.sep.join(pattern), support) for pattern, support in self._patterns.items()],
            columns=["Patterns", "Support"],
        )

    def getMemoryUSS(self):
        return self._memory_uss

    def getMemoryRSS(self):
        return self._memory_rss

    def getRuntime(self):
        return self._runtime

    def printResults(self):
        print("Total number of patterns:", len(self._patterns))
        print("Total time taken:", self._runtime)
        print("Total memory in USS:", self._memory_uss)
        print("Total memory in RSS:", self._memory_rss)

    def _iter_transactions(self):
        source = self.iFile
        if isinstance(source, pd.DataFrame):
            if "Transactions" not in source.columns:
                raise ValueError("DataFrame input must contain a 'Transactions' column")
            for row in source["Transactions"]:
                yield row.split(self.sep) if isinstance(row, str) else list(map(str, row))
            return
        if isinstance(source, (str, Path)):
            value = str(source)
            is_url = bool(validators.url(value))
            if is_url:
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

    def _parse_lines(self, lines):
        for line in lines:
            line = line.strip()
            if line:
                yield line.split(self.sep) if self.sep else line.split()

    def _capture_metrics(self, started):
        self._runtime = perf_counter() - started
        process = psutil.Process()
        try:
            self._memory_uss = process.memory_full_info().uss
        except (AttributeError, psutil.Error):
            self._memory_uss = 0
        self._memory_rss = process.memory_info().rss
