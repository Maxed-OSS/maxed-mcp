"""maxed-mcp: an MCP server that fronts the deterministic tools in the
open-source accounting suite.

It exposes a small set of Model Context Protocol tools so an AI agent can do
the boring, auditable, deterministic parts of accounting work through one door:
parse a bank statement, classify a document, validate a workpaper against the
open spec, do exact money math, and check a webhook signature. Every tool
returns structured JSON and an agent-friendly error envelope; nothing here is
generative and nothing is faked.

The heavy parsers stay in their own repositories. Tools that already ship a CLI
are shelled out to and their JSON parsed (see :mod:`maxed_mcp.runners`); the
pure, small primitives (money math, HMAC) are computed in-process and mirror
the semantics of their canonical sibling libraries (``money-rs`` and
``webhook-hmac-verifier``).

Run it:

    maxed-mcp                 # stdio transport, ready for an MCP client
    python -m maxed_mcp       # equivalent
"""

from __future__ import annotations

import json
from typing import Dict, List, Optional

from mcp.server.fastmcp import FastMCP

from . import __version__, money, hmac_verify, runners

mcp = FastMCP(
    "maxed-mcp",
    instructions=(
        "Deterministic accounting tools: parse bank statements and OFX/QFX "
        "downloads, classify accounting documents, validate CPA workpaper-spec "
        "documents, do exact money math (allocation and rate application), and "
        "verify webhook HMAC signatures. Call list_capabilities first to see "
        "which shell-backed tools are available on this host."
    ),
)


# --- helpers ---------------------------------------------------------------

def _unavailable(tool: str, hint: str) -> Dict[str, object]:
    return runners.error_envelope("tool_unavailable", f"{tool} is not available", hint=hint)


def _wrap_cli(code: int, out: str, err: str, ok_key: str) -> Dict[str, object]:
    """Turn a CLI's (exit, stdout, stderr) into a uniform tool response.

    On success (exit 0) the stdout JSON is placed under ``ok_key``. On failure
    the stderr is parsed as an error envelope when possible, else wrapped.
    """
    out = out.strip()
    if code == 0:
        try:
            return {"ok": True, ok_key: json.loads(out) if out else {}}
        except json.JSONDecodeError as exc:
            return runners.error_envelope(
                "invalid_json_output",
                f"tool did not emit valid JSON: {exc}",
                stdout=runners.truncate_output(out),
                stderr=runners.truncate_output(err),
            )
    err = err.strip()
    try:
        parsed = json.loads(err)
        if isinstance(parsed, dict) and "error" in parsed:
            parsed.setdefault("ok", False)
            return parsed
    except json.JSONDecodeError:
        pass

    detail: Dict[str, object] = {"exit_code": code}
    if out:
        detail["stdout"] = runners.truncate_output(out)
    if err:
        detail["stderr"] = runners.truncate_output(err)

    return runners.error_envelope(
        "command_failed",
        runners.truncate_output(err) or f"command exited with status {code}",
        **detail,
    )


# --- capability discovery --------------------------------------------------

@mcp.tool()
def list_capabilities() -> Dict[str, object]:
    """List every tool this server exposes and whether it is ready to run.

    Shell-backed tools depend on a sibling CLI being installed; this reports
    which resolve on the current host so an agent can plan around what is
    available. In-process tools (money, HMAC) are always ready.
    """
    stmt = runners.resolve_statement_normalizer()
    doc = runners.resolve_doc_classifier()
    ofx = runners.resolve_ofxnorm()
    cpa = runners.resolve_cpa_validator()
    return {
        "ok": True,
        "server": "maxed-mcp",
        "version": __version__,
        "tools": [
            {
                "name": "normalize_bank_statement",
                "backend": "statement-normalizer (CLI)",
                "available": stmt is not None,
                "install": "pip install statement-normalizer",
                "summary": "Parse CSV/OFX/QFX/MT940/CAMT/QIF/text into normalized transaction JSON.",
            },
            {
                "name": "normalize_ofx",
                "backend": "ofx-normalizer / ofxnorm (Go CLI)",
                "available": ofx is not None,
                "install": "go install github.com/maxed-oss/ofx-normalizer/cmd/ofxnorm@latest",
                "summary": "Parse an OFX/QFX or CSV bank export into normalized transaction JSON.",
            },
            {
                "name": "classify_document",
                "backend": "doc-classifier-kit (CLI)",
                "available": doc is not None,
                "install": "pip install doc-classifier-kit",
                "summary": "Classify accounting document text (w2, form_1099, invoice, bank_statement, receipt).",
            },
            {
                "name": "validate_workpaper",
                "backend": "cpa-workpaper-spec validator",
                "available": cpa is not None,
                "install": "set CPA_WORKPAPER_SPEC_DIR to a cpa-workpaper-spec checkout",
                "summary": "Validate a document against a cpa-workpaper-spec JSON Schema.",
            },
            {
                "name": "money_allocate",
                "backend": "money-rs semantics (in-process)",
                "available": True,
                "summary": "Split an amount across ratios or evenly with no lost minor units.",
            },
            {
                "name": "money_apply_rate",
                "backend": "money-rs semantics (in-process)",
                "available": True,
                "summary": "Apply a rate to an amount with explicit rounding.",
            },
            {
                "name": "verify_webhook_hmac",
                "backend": "webhook-hmac-verifier semantics (in-process)",
                "available": True,
                "summary": "Constant-time verify a Stripe/hex/base64 webhook HMAC signature.",
            },
        ],
    }


# --- parsers ---------------------------------------------------------------

@mcp.tool()
def normalize_bank_statement(
    content: str,
    fmt: Optional[str] = None,
    default_currency: str = "USD",
    dedup: bool = True,
    invert_amounts: bool = False,
) -> Dict[str, object]:
    """Normalize a raw bank or credit-card statement into transaction JSON.

    Pass the statement's text/content in ``content``. The format is
    auto-detected (CSV, OFX/QFX, MT940, CAMT.053, CAMT.052, QIF, or text);
    set ``fmt`` to force one. Deterministic and rule-based. Returns the
    normalized statement under ``statement``, or an error envelope.
    """
    cmd = runners.resolve_statement_normalizer()
    if cmd is None:
        return _unavailable(
            "normalize_bank_statement",
            "install the statement-normalizer package (pip install statement-normalizer) "
            "or set MAXED_MCP_STATEMENT_NORMALIZER to its command.",
        )
    args: List[str] = ["-", "--json-errors"]
    if fmt:
        args += ["--format", fmt]
    if default_currency:
        args += ["--currency", default_currency]
    if not dedup:
        args.append("--no-dedup")
    if invert_amounts:
        args.append("--invert-amounts")
    try:
        code, out, err = runners.run(cmd, args, stdin=content)
    except Exception as exc:  # pragma: no cover - defensive
        return runners.error_envelope("exec_error", str(exc))
    return _wrap_cli(code, out, err, "statement")


@mcp.tool()
def normalize_ofx(
    content: str,
    fmt: str = "auto",
    invert_amounts: bool = False,
) -> Dict[str, object]:
    """Normalize an OFX/QFX or CSV bank export into transaction JSON.

    Backed by the ``ofxnorm`` CLI from ofx-normalizer. ``fmt`` is ``auto``,
    ``ofx``, or ``csv``. Returns the normalized statement under ``statement``.
    Note statement-normalizer also reads OFX/QFX if ofxnorm is not installed.
    """
    cmd = runners.resolve_ofxnorm()
    if cmd is None:
        return _unavailable(
            "normalize_ofx",
            "build the ofxnorm binary from the ofx-normalizer repo "
            "(go install github.com/maxed-oss/ofx-normalizer/cmd/ofxnorm@latest) "
            "or set MAXED_MCP_OFXNORM to its path. As a fallback, "
            "normalize_bank_statement also parses OFX/QFX.",
        )
    args: List[str] = ["--pretty=false"]
    if fmt and fmt != "auto":
        args += ["--format", fmt]
    if invert_amounts:
        args.append("--invert-amounts")
    args.append("-")
    try:
        code, out, err = runners.run(cmd, args, stdin=content)
    except Exception as exc:  # pragma: no cover - defensive
        return runners.error_envelope("exec_error", str(exc))
    return _wrap_cli(code, out, err, "statement")


@mcp.tool()
def classify_document(text: str, min_score: float = 1.0) -> Dict[str, object]:
    """Classify a single accounting document's text into the kit taxonomy.

    Labels: ``w2``, ``form_1099``, ``invoice``, ``bank_statement``,
    ``receipt``, or ``unknown`` (honest abstention). Uses doc-classifier-kit's
    dependency-free keyword baseline. Returns ``label``, ``confidence``, and a
    short ``rationale``.
    """
    cmd = runners.resolve_doc_classifier()
    if cmd is None:
        return _unavailable(
            "classify_document",
            "install the doc-classifier-kit package (pip install doc-classifier-kit) "
            "or set MAXED_MCP_DOC_CLASSIFIER to its command.",
        )
    args = ["classify", "--json", "--min-score", str(min_score)]
    try:
        code, out, err = runners.run(cmd, args, stdin=text)
    except Exception as exc:  # pragma: no cover - defensive
        return runners.error_envelope("exec_error", str(exc))
    wrapped = _wrap_cli(code, out, err, "classification")
    # Flatten the classification onto the top level for convenience.
    if wrapped.get("ok") and isinstance(wrapped.get("classification"), dict):
        result = dict(wrapped["classification"])
        result["ok"] = True
        return result
    return wrapped


@mcp.tool()
def validate_workpaper(document: Dict[str, object], schema: str) -> Dict[str, object]:
    """Validate a document against a cpa-workpaper-spec JSON Schema.

    ``schema`` is a spec schema name: ``engagement``, ``workpaper``,
    ``close-checklist``, ``tax-prep``, ``engagement-letter``, or
    ``request-list-item``. Returns ``valid`` plus any schema ``errors``.
    """
    cmd = runners.resolve_cpa_validator()
    if cmd is None:
        return _unavailable(
            "validate_workpaper",
            "point CPA_WORKPAPER_SPEC_DIR at a cpa-workpaper-spec checkout "
            "(the dir containing validator/validate.py), or set "
            "MAXED_MCP_CPA_WORKPAPER_VALIDATE to its command.",
        )
    args = ["-", "--schema", schema, "--json"]
    try:
        code, out, err = runners.run(cmd, args, stdin=json.dumps(document))
    except Exception as exc:  # pragma: no cover - defensive
        return runners.error_envelope("exec_error", str(exc))
    out = out.strip()
    if out:
        try:
            parsed = json.loads(out)
            if isinstance(parsed, dict):
                parsed.setdefault("ok", True)
                return parsed
        except json.JSONDecodeError:
            pass
    return _wrap_cli(code, out, err, "validation")


# --- money math ------------------------------------------------------------

@mcp.tool()
def money_allocate(
    minor_units: int,
    currency: str,
    ratios: Optional[List[int]] = None,
    parts: Optional[int] = None,
    exponent: Optional[int] = None,
) -> Dict[str, object]:
    """Split an amount (in minor units) with no lost or invented minor units.

    Give either ``ratios`` (for example ``[3, 7]`` for a 30/70 split) or
    ``parts`` (an even split into N). Amounts are integer minor units (cents),
    so nothing drifts. ``currency`` is a known code (USD, EUR, GBP, JPY, BHD)
    or any code plus an explicit ``exponent`` for custom currencies. Mirrors
    money-rs's largest-remainder allocation.
    """
    try:
        return money.allocate(
            minor_units, currency, ratios=ratios, parts=parts, exponent=exponent
        )
    except money.MoneyError as exc:
        return runners.error_envelope("bad_request", str(exc))


@mcp.tool()
def money_apply_rate(
    minor_units: int,
    currency: str,
    rate: float,
    rounding: str = "half_even",
    exponent: Optional[int] = None,
) -> Dict[str, object]:
    """Apply a rate to an amount, rounding to whole minor units.

    Use for tax, tips, discounts, or a percentage share. ``rounding`` is one
    of ``half_even`` (default, bias-free), ``half_up``, ``floor``, ``ceil``,
    or ``truncate``. Mirrors money-rs's ``mul_round``.
    """
    try:
        return money.apply_rate(
            minor_units, currency, rate, rounding=rounding, exponent=exponent
        )
    except money.MoneyError as exc:
        return runners.error_envelope("bad_request", str(exc))


# --- webhook signature verification ---------------------------------------

@mcp.tool()
def verify_webhook_hmac(
    scheme: str,
    secret: str,
    body: str,
    signature: str,
    prefix: str = "",
    tolerance_seconds: int = 300,
    timestamp: Optional[int] = None,
) -> Dict[str, object]:
    """Verify an inbound webhook's HMAC signature in constant time.

    ``scheme`` is ``stripe`` (``t=..,v1=..`` header, timestamped),
    ``hex`` (bare hex HMAC, for example QuickBooks Online), or ``base64``
    (for example Bill.com). ``body`` is the exact raw request body, ``secret``
    the signing secret, ``prefix`` an optional signature prefix to strip.
    Returns ``valid`` and a ``reason``. Mirrors webhook-hmac-verifier.
    """
    return hmac_verify.verify(
        scheme,
        secret,
        body,
        signature,
        prefix=prefix,
        tolerance_seconds=tolerance_seconds,
        timestamp=timestamp,
    )


def main() -> None:
    """Console-script entry point: run the server over stdio."""
    mcp.run()


if __name__ == "__main__":  # pragma: no cover
    main()
