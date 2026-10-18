"""Common PAMI-style interface for streaming frequent-pattern algorithms."""
from __future__ import annotations

import warnings
from abc import ABC, abstractmethod
from pathlib import Path
from time import perf_counter
from urllib.request import urlopen

try:
    import pandas as pd
except ImportError:  # pandas remains an installation dependency for DataFrame input.
    pd = None
try:
    import psutil
except ImportError:  # Metrics are best effort when psutil is unavailable.
    psutil = None
try:
    import validators
except ImportError:  # URL recognition has a standard-library fallback.
    validators = None


class _streamFrequentPatterns(ABC):
    def __init__(self, iFile, minSup, epsilon, batchSize, sep="\t"):
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
                output.write("\t".join(pattern) + ":" + str(support) + "\n")

    def getPatternsAsDataFrame(self):
        if pd is None:
            raise ImportError("pandas is required for getPatternsAsDataFrame")
        return pd.DataFrame([{"pattern": p, "support": s} for p, s in self._patterns.items()], columns=["pattern", "support"])

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
        if pd is not None and isinstance(source, pd.DataFrame):
            if "Transactions" not in source.columns:
                raise ValueError("DataFrame input must contain a 'Transactions' column")
            for row in source["Transactions"]:
                yield row.split(self.sep) if isinstance(row, str) else list(map(str, row))
            return
        if isinstance(source, (str, Path)):
            value = str(source)
            is_url = bool(validators.url(value)) if validators is not None else value.startswith(("http://", "https://"))
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
        if psutil is not None:
            process = psutil.Process()
            try:
                self._memory_uss = process.memory_full_info().uss
            except (AttributeError, psutil.Error):
                self._memory_uss = 0
            self._memory_rss = process.memory_info().rss
