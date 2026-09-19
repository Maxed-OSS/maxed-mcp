"""End-to-end tool behavior. Shell-backed tools are tested against whatever the
host has installed: when the backend is present the tool must succeed, and when
it is absent the tool must degrade to a structured tool_unavailable error.
"""

import json

from maxed_mcp import server, hmac_verify, runners


def test_list_capabilities_lists_all_tools():
    caps = server.list_capabilities()
    assert caps["ok"] is True
    names = {t["name"] for t in caps["tools"]}
    assert {
        "normalize_bank_statement",
        "normalize_ofx",
        "classify_document",
        "validate_workpaper",
        "money_allocate",
        "money_apply_rate",
        "verify_webhook_hmac",
    } <= names
    # in-process tools are always available
    for t in caps["tools"]:
        if t["name"] in {"money_allocate", "money_apply_rate", "verify_webhook_hmac"}:
            assert t["available"] is True


def test_money_tools_via_server():
    r = server.money_allocate(100, "USD", parts=3)
    assert [p["minor_units"] for p in r["parts"]] == [34, 33, 33]
    r = server.money_apply_rate(1999, "USD", 0.0825)
    assert r["result"]["minor_units"] == 165


def test_money_bad_request_is_enveloped():
    r = server.money_allocate(100, "ZZZ", parts=2)  # unknown currency, no exponent
    assert r["ok"] is False
    assert r["error"]["code"] == "bad_request"


def test_verify_webhook_hmac_via_server():
    sig = hmac_verify.sign("hex", "secret", "body")
    r = server.verify_webhook_hmac("hex", "secret", "body", sig)
    assert r["valid"] is True


def test_normalize_bank_statement_present_or_gated():
    csv = "Date,Description,Amount\n01/05/2024,Coffee,-42.00\n"
    r = server.normalize_bank_statement(csv)
    if runners.resolve_statement_normalizer() is not None:
        assert r["ok"] is True
        assert len(r["statement"]["transactions"]) == 1
    else:
        assert r["ok"] is False
        assert r["error"]["code"] == "tool_unavailable"


def test_classify_document_present_or_gated():
    text = "W-2 Wage and Tax Statement\nEmployer EIN 12-3456789\nWages 54000\n"
    r = server.classify_document(text)
    if runners.resolve_doc_classifier() is not None:
        assert r["ok"] is True
        assert r["label"] in {"w2", "form_1099", "invoice", "bank_statement", "receipt", "unknown"}
    else:
        assert r["ok"] is False
        assert r["error"]["code"] == "tool_unavailable"


def test_normalize_ofx_gated_when_binary_absent():
    r = server.normalize_ofx("<OFX></OFX>")
    if runners.resolve_ofxnorm() is None:
        assert r["ok"] is False
        assert r["error"]["code"] == "tool_unavailable"


def test_validate_workpaper_present_or_gated():
    doc = {"nonsense": True}
    r = server.validate_workpaper(doc, "engagement")
    if runners.resolve_cpa_validator() is not None:
        # a nonsense doc is invalid, but the tool ran and answered
        assert "valid" in r
        assert r["valid"] is False
    else:
        assert r["ok"] is False
        assert r["error"]["code"] == "tool_unavailable"


def test_wrap_cli_command_failure_preserves_stdout_context():
    r = server._wrap_cli(2, "useful stdout hint", "plain stderr", "result")
    assert r["ok"] is False
    assert r["error"]["code"] == "command_failed"
    assert r["error"]["message"] == "plain stderr"
    assert r["error"]["detail"]["exit_code"] == 2
    assert r["error"]["detail"]["stdout"] == "useful stdout hint"

