"""The streaming mode of the test helper ``_run``.

The bake test runs its heavy steps (init, build, db reset) through it. A
captured run that hits its timeout loses every line it printed, which is how
a one-hour build hang in CI left no trace of where it hung.
"""

import sys
import time

import pytest

from .conftest import _run


def _py(code):
    return [sys.executable, "-c", code]


def test_output_of_both_streams_is_returned(tmp_path):
    res = _run(
        _py("import sys; print('out'); print('err', file=sys.stderr)"),
        cwd=tmp_path,
        stream=True,
    )
    assert res.returncode == 0
    assert "out" in res.stdout and "err" in res.stdout


def test_output_appears_while_the_command_runs(tmp_path, capsys):
    _run(_py("print('first', flush=True)"), cwd=tmp_path, stream=True)
    assert "first" in capsys.readouterr().out


def test_failure_raises_with_the_output(tmp_path):
    with pytest.raises(AssertionError, match="exit 3") as exc:
        _run(
            _py("print('boom'); raise SystemExit(3)"), cwd=tmp_path, stream=True
        )
    assert "boom" in str(exc.value)


def test_failure_is_returned_without_check(tmp_path):
    res = _run(_py("raise SystemExit(3)"), cwd=tmp_path, stream=True, check=False)
    assert res.returncode == 3


def test_silent_command_is_stopped_by_the_stall_guard(tmp_path):
    started = time.monotonic()
    with pytest.raises(AssertionError, match="no output for 1s") as exc:
        _run(
            _py("print('last words', flush=True); import time; time.sleep(60)"),
            cwd=tmp_path,
            stream=True,
            stall_timeout=1,
        )
    assert "last words" in str(exc.value)
    assert time.monotonic() - started < 30


def test_chatty_command_is_still_bound_by_the_timeout(tmp_path):
    chatty = "import time\nwhile True:\n    print('.', flush=True)\n    time.sleep(0.2)"
    with pytest.raises(AssertionError, match="timed out after 2s"):
        _run(_py(chatty), cwd=tmp_path, stream=True, timeout=2, stall_timeout=60)
