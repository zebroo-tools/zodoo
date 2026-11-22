# Part of Zebroo GmbH. See LICENSE file for full copyright and licensing details (www.zebroo.de/license).
"""Prefixes of CI compose projects vs. the cleanup pattern in bake-test.yml.

The tests name their compose projects with ``ci_project_name(base,
prefix)``; the bake workflow removes the projects and images of its run by
matching ``CI_PROJECT_PREFIX_RE``. If a prefix in the tests is added or
renamed without the pattern, the cleanup finds nothing, still ends green, and
the runner disk fills up again. This test reads both places and fails then.
"""

import ast
import re
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
WORKFLOW = TESTS_DIR.parents[3] / ".github" / "workflows" / "bake-test.yml"
RUN_SUFFIX = "46509"


def _workflow_pattern():
    match = re.search(
        r'^\s*CI_PROJECT_PREFIX_RE:\s*"([^"]+)"\s*$',
        WORKFLOW.read_text(),
        re.MULTILINE,
    )
    assert match, f"CI_PROJECT_PREFIX_RE not found in {WORKFLOW}"
    return match.group(1)


def _example(node):
    """Literal prefix, with every f-string placeholder replaced by digits."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            part.value if isinstance(part, ast.Constant) else "190"
            for part in node.values
        )
    raise AssertionError(f"unsupported prefix expression: {ast.dump(node)}")


def _test_prefixes():
    prefixes = set()
    for path in TESTS_DIR.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if (
                isinstance(node, ast.Call)
                and getattr(node.func, "id", None) == "ci_project_name"
                and len(node.args) == 2
            ):
                prefixes.add((path.name, _example(node.args[1])))
    return prefixes


def test_every_ci_project_prefix_is_cleaned_up():
    pattern = re.compile(rf"^({_workflow_pattern()}){RUN_SUFFIX}$")
    prefixes = _test_prefixes()
    assert prefixes, "no ci_project_name(...) calls found"
    missing = sorted(
        f"{name}: {prefix}"
        for name, prefix in prefixes
        if not pattern.match(prefix + RUN_SUFFIX)
    )
    assert not missing, (
        "CI_PROJECT_PREFIX_RE in bake-test.yml does not match these "
        f"prefixes, their projects and images would stay: {missing}"
    )
