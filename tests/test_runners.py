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


def test_statement_normalizer_resolves_when_installed():
    # statement-normalizer is a Python fallback, so at minimum the module-run
    # form resolves whenever the package is importable.
    cmd = runners.resolve_statement_normalizer()
    if cmd is not None:
        assert isinstance(cmd, list) and cmd
