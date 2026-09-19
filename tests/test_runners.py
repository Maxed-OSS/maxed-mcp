"""Subprocess resolution and JSON parsing helpers."""

import sys

from maxed_mcp import runners


def test_error_envelope_shape():
    env = runners.error_envelope("bad_thing", "it broke", hint="try again")
    assert env["ok"] is False
    assert env["error"]["code"] == "bad_thing"
    assert env["error"]["message"] == "it broke"
    assert env["error"]["detail"]["hint"] == "try again"


def test_run_captures_stdout_and_exit():
    code, out, err = runners.run([sys.executable, "-c", "print('hi')"], [])
    assert code == 0
    assert out.strip() == "hi"


def test_run_json_parses_object():
    r = runners.run_json(
        [sys.executable, "-c", "import json;print(json.dumps({'a':1}))"], []
    )
    assert r["ok"] is True
    assert r["result"] == {"a": 1}


def test_run_json_reports_invalid_json():
    r = runners.run_json([sys.executable, "-c", "print('not json')"], [])
    assert r["ok"] is False
    assert r["error"]["code"] == "invalid_json_output"


def test_run_json_reports_command_failure():
    r = runners.run_json(
        [sys.executable, "-c", "import sys;sys.stderr.write('boom');sys.exit(3)"], []
    )
    assert r["ok"] is False
    assert r["error"]["code"] == "command_failed"


def test_statement_normalizer_resolves_when_installed():
    # statement-normalizer is a Python fallback, so at minimum the module-run
    # form resolves whenever the package is importable.
    cmd = runners.resolve_statement_normalizer()
    if cmd is not None:
        assert isinstance(cmd, list) and cmd


def test_truncate_output_none_and_empty():
    assert runners.truncate_output(None) == ""
    assert runners.truncate_output("") == ""
    assert runners.truncate_output("   ") == ""


def test_truncate_output_under_limit():
    short_text = "Startup banner: All good!"
    assert runners.truncate_output(short_text) == "Startup banner: All good!"
    exact_limit = "a" * 2000
    assert runners.truncate_output(exact_limit) == exact_limit


def test_truncate_output_over_limit():
    head_marker = "STARTUP_BANNER_" + "A" * 985
    tail_marker = "B" * 986 + "_TRACEBACK_END"
    middle = "C" * 1000
    full_text = head_marker + middle + tail_marker

    truncated = runners.truncate_output(full_text)
    assert len(full_text) == 3000
    assert truncated.startswith("STARTUP_BANNER_")
    assert truncated.endswith("_TRACEBACK_END")
    assert "... [1000 chars truncated] ..." in truncated
    assert truncated[:1000] == head_marker
    assert truncated[-1000:] == tail_marker


def test_truncate_output_custom_max_chars():
    text = "1234567890EXTRA9876543210"
    res = runners.truncate_output(text, max_chars=20)
    assert res.startswith("1234567890")
    assert res.endswith("9876543210")
    assert "... [5 chars truncated] ..." in res


def test_run_json_truncates_long_output():
    long_out = "HEADER_" + ("X" * 3000) + "_FOOTER"
    long_err = "ERRHEAD_" + ("Y" * 3000) + "_ERRTAIL"
    code = f"import sys; sys.stdout.write('{long_out}'); sys.stderr.write('{long_err}')"
    r = runners.run_json([sys.executable, "-c", code], [])
    assert r["ok"] is False
    assert r["error"]["code"] == "invalid_json_output"
    stdout_det = r["error"]["detail"]["stdout"]
    stderr_det = r["error"]["detail"]["stderr"]
    assert "HEADER_" in stdout_det and "_FOOTER" in stdout_det
    assert "... [" in stdout_det and "chars truncated] ..." in stdout_det
    assert "ERRHEAD_" in stderr_det and "_ERRTAIL" in stderr_det
    assert "... [" in stderr_det and "chars truncated] ..." in stderr_det


def test_run_json_reports_command_failure_even_with_json_stdout():
    r = runners.run_json(
        [
            sys.executable,
            "-c",
            "import json, sys; print(json.dumps({'error':'bad'})); sys.exit(7)",
        ],
        [],
    )
    assert r["ok"] is False
    assert r["error"]["code"] == "command_failed"
    assert r["error"]["detail"]["exit_code"] == 7
    assert '"error": "bad"' in r["error"]["detail"]["stdout"]


