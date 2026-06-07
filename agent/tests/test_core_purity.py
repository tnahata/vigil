"""Structural proof of the defended claim: vigil.core imports nothing external.
If this fails, the LLM (or LiveKit, or Moss) can reach the dose path -- a bug.
"""
import ast
import os

FORBIDDEN_ROOTS = {
    "livekit", "openai", "anthropic", "minimax",
    "moss", "inferedge_moss", "dotenv",
}

CORE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "vigil", "core"
)


def _root(name: str) -> str:
    return (name or "").split(".")[0]


def test_core_imports_nothing_external():
    offenders = []
    for fname in sorted(os.listdir(CORE_DIR)):
        if not fname.endswith(".py"):
            continue
        path = os.path.join(CORE_DIR, fname)
        with open(path) as f:
            tree = ast.parse(f.read(), filename=path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if _root(alias.name) in FORBIDDEN_ROOTS:
                        offenders.append(f"{fname}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                # level > 0 is a relative import within our package -> always fine
                if node.level == 0 and _root(node.module) in FORBIDDEN_ROOTS:
                    offenders.append(f"{fname}: from {node.module} import ...")
    assert not offenders, f"vigil.core must not import external/LLM deps: {offenders}"
