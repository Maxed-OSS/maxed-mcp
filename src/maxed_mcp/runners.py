"""Resolve and run the suite's command-line tools as subprocesses.

The MCP server is a thin, honest front door: for the tools that already ship a
CLI it shells out to that CLI and parses its JSON, rather than reimplementing
the parser. This keeps each library the single source of truth for its own
behavior and keeps versions decoupled.

Every tool's backing command is resolved in this order:

1. an explicit environment variable (a full command line, shell-split), so an
   operator can point at any install;
2. the tool's console-script name on ``PATH``;
3. a language-appropriate fallback (``python -m <module>`` for the Python
   tools; a known sibling-checkout path for the spec validator).

If nothing resolves, the tool returns a structured ``tool_unavailable`` error
with an install hint instead of failing opaquely. Nothing here fakes output.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

DEFAULT_TIMEOUT_SECONDS = 30


class ToolUnavailable(RuntimeError):
    """The backing CLI for a tool could not be resolved on this machine."""

    def __init__(self, tool: str, hint: str) -> None:
        super().__init__(f"{tool}: backing command not found. {hint}")
        self.tool = tool
        self.hint = hint


def _env_command(var: str) -> Optional[List[str]]:
    raw = os.environ.get(var, "").strip()
    return shlex.split(raw) if raw else None


def _python_module_available(module: str) -> bool:
    import importlib.util

    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def resolve_statement_normalizer() -> Optional[List[str]]:
    cmd = _env_command("MAXED_MCP_STATEMENT_NORMALIZER")
    if cmd:
        return cmd
    found = shutil.which("statement-normalizer")
    if found:
        return [found]
    if _python_module_available("statement_normalizer"):
        return [sys.executable, "-m", "statement_normalizer.cli"]
    return None


def resolve_doc_classifier() -> Optional[List[str]]:
    cmd = _env_command("MAXED_MCP_DOC_CLASSIFIER")
    if cmd:
        return cmd
    found = shutil.which("doc-classifier-kit")
    if found:
        return [found]
    if _python_module_available("doc_classifier_kit"):
        return [sys.executable, "-m", "doc_classifier_kit"]
    return None


def resolve_ofxnorm() -> Optional[List[str]]:
    cmd = _env_command("MAXED_MCP_OFXNORM")
    if cmd:
        return cmd
    found = shutil.which("ofxnorm")
    if found:
        return [found]
    return None


def _candidate_spec_dirs() -> List[Path]:
    candidates: List[Path] = []
    env_dir = os.environ.get("CPA_WORKPAPER_SPEC_DIR", "").strip()
    if env_dir:
        candidates.append(Path(env_dir))
    here = Path(__file__).resolve()
    # Sibling-repo layouts: .../maxed-oss/{maxed-mcp,cpa-workpaper-spec}
    for base in (Path.cwd(), *here.parents):
        candidates.append(base / "cpa-workpaper-spec")
        candidates.append(base.parent / "cpa-workpaper-spec" if base.parent else base)
    seen = set()
    unique: List[Path] = []
    for c in candidates:
        rc = c.resolve() if c else c
        if rc not in seen:
            seen.add(rc)
            unique.append(c)
    return unique


def resolve_cpa_validator() -> Optional[List[str]]:
    cmd = _env_command("MAXED_MCP_CPA_WORKPAPER_VALIDATE")
    if cmd:
        return cmd
    for spec_dir in _candidate_spec_dirs():
        validate = spec_dir / "validator" / "validate.py"
        if validate.is_file():
            return [sys.executable, str(validate)]
    return None


def run(
    cmd: Sequence[str],
    args: Sequence[str],
    *,
    stdin: Optional[str] = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> Tuple[int, str, str]:
    """Run ``cmd + args``, feeding ``stdin``. Returns (exit_code, out, err)."""
    proc = subprocess.run(
        list(cmd) + list(args),
        input=stdin.encode("utf-8") if stdin is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )
    return (
        proc.returncode,
        proc.stdout.decode("utf-8", errors="replace"),
        proc.stderr.decode("utf-8", errors="replace"),
    )


def error_envelope(code: str, message: str, **detail) -> Dict[str, object]:
    """The single error shape every MCP tool returns on failure."""
    err: Dict[str, object] = {"code": code, "message": message}
    if detail:
        err["detail"] = detail
    return {"ok": False, "error": err}


def truncate_output(text: Optional[str], max_chars: int = 2000) -> str:
    """Truncate CLI output while preserving both initial command context and trailing tracebacks.

    If text length exceeds max_chars, returns the first max_chars//2 chars and the last
    max_chars//2 chars separated by an explicit truncation notice.
    """
    if not text:
        return ""

    text = text.strip()
    if len(text) <= max_chars:
        return text

    half = max_chars // 2
    head = text[:half]
    tail = text[-half:]
    removed = len(text) - (len(head) + len(tail))
    return f"{head}\n\n... [{removed} chars truncated] ...\n\n{tail}"


def run_json(
    cmd: Sequence[str],
    args: Sequence[str],
    *,
    stdin: Optional[str] = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> Dict[str, object]:
    """Run a tool that prints JSON on stdout; return the parsed object.

    On a non-zero exit or unparseable stdout, returns an error envelope rather
    than raising, so the calling agent always gets structured feedback.
    """
    try:
        code, out, err = run(cmd, args, stdin=stdin, timeout=timeout)
    except subprocess.TimeoutExpired:
        return error_envelope("timeout", f"command timed out after {timeout}s")
    except OSError as exc:
        return error_envelope("exec_error", str(exc))

    out = out.strip()
    err = err.strip()
    if code != 0:
        detail: Dict[str, object] = {"exit_code": code}
        if out:
            detail["stdout"] = truncate_output(out)
        if err:
            detail["stderr"] = truncate_output(err)
        return error_envelope(
            "command_failed",
            (truncate_output(err) or f"command exited with status {code}"),
            **detail,
        )
    try:
        parsed = json.loads(out) if out else {}
    except json.JSONDecodeError as exc:
        return error_envelope(
            "invalid_json_output",
            f"tool did not emit valid JSON: {exc}",
            exit_code=code,
            stdout=truncate_output(out),
            stderr=truncate_output(err),
        )
    return {"ok": True, "exit_code": code, "result": parsed}

