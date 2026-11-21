"""Regression coverage for the popup sizing contract used by netui.refit()."""
import ast
from pathlib import Path


def test_refit_resizes_to_natural_height_after_revealer_settles():
    source = Path(__file__).parents[1].joinpath("glitterde", "netui.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    refit = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "refit")
    calls = [
        node
        for node in ast.walk(refit)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "resize"
    ]
    assert calls, "refit must explicitly resize the popup"
    resize = calls[0]
    assert len(resize.args) == 2
    assert isinstance(resize.args[1], ast.Constant) and resize.args[1].value == 1
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "queue_resize"
        for node in ast.walk(refit)
    )

