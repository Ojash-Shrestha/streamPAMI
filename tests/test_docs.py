"""Execute every Markdown Python example and compare any displayed stdout."""
import ast
from pathlib import Path
import re
import socket

import pytest


DOCS = Path(__file__).resolve().parents[1] / "docs"
FENCE = re.compile(r"^```(python|text)[ \t]*\n(.*?)^```[ \t]*(?:\n|$)", re.MULTILINE | re.DOTALL)


def _examples():
    examples = []
    for path in sorted(DOCS.rglob("*.md")):
        text = path.read_text(encoding="utf-8")
        fences = list(FENCE.finditer(text))
        for index, fence in enumerate(fences):
            if fence[1] != "python":
                continue
            expected = None
            if index + 1 < len(fences):
                following = fences[index + 1]
                if following[1] == "text" and not text[fence.end():following.start()].strip():
                    expected = following[2]
            line = text.count("\n", 0, fence.start()) + 1
            label = f"{path.relative_to(DOCS).as_posix()}:{line}"
            examples.append(pytest.param(fence[2], expected, label, id=label))
    assert examples, "No Python examples found under docs/"
    return examples


@pytest.mark.parametrize("source,expected,label", _examples())
def test_documentation_python_blocks(source, expected, label, capsys, monkeypatch):
    def offline(*args, **kwargs):
        raise AssertionError(f"Documentation examples must be offline: {label}")

    monkeypatch.setattr(socket, "create_connection", offline)
    parsed = ast.parse(source, filename=label)
    assert not any(isinstance(node, ast.Attribute) and node.attr.startswith("_")
                   for node in ast.walk(parsed)), f"Private attribute in {label}"
    exec(compile(parsed, label, "exec"), {})
    captured = capsys.readouterr()
    if expected is not None:
        assert captured.out == expected, f"Printed output differs in {label}"
    else:
        assert not captured.out, f"Add a following text block for stdout in {label}"
