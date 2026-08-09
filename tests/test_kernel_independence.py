"""Test: Kernel independence — no external imports."""

import ast
import pathlib

# These packages should NEVER be imported by the kernel
FORBIDDEN_IMPORTS = {
    "fastapi",
    "sqlalchemy",
    "redis",
    "requests",
    "httpx",
    "uvicorn",
    "celery",
    "flask",
    "django",
    "starlette",
}


def test_kernel_no_external_imports():
    """Verify the Kernel has zero external dependencies.

    Note: The server/ directory is excluded — it's the API layer,
    not the Kernel itself.
    """
    kernel_dir = pathlib.Path(__file__).parent.parent / "intent_kernel"
    violations = []

    # Exclude the server directory — it's allowed to use external deps
    exclude_dirs = {"server"}

    for py_file in kernel_dir.rglob("*.py"):
        # Skip server directory
        if any(excluded in py_file.parts for excluded in exclude_dirs):
            continue

        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top in FORBIDDEN_IMPORTS:
                        violations.append(f"{py_file.name}: import {alias.name}")

            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    top = node.module.split(".")[0]
                    if top in FORBIDDEN_IMPORTS:
                        violations.append(f"{py_file.name}: from {node.module}")

    assert not violations, f"Forbidden imports found:\n" + "\n".join(violations)
