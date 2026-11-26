# maxed-mcp for agents

Machine interface for the `maxed-mcp` server: one Model Context Protocol (MCP)
server that fronts the suite's deterministic accounting tools. This repo IS the
agentic front door; the sibling repos' AGENT.md files point here.

## Run

```
pip install maxed-mcp            # or: pip install "maxed-mcp[suite]"
maxed-mcp                        # serve MCP over stdio
python -m maxed_mcp              # equivalent
```

Register with any MCP client (Claude Desktop, Claude Code, etc.):

```json
{
  "mcpServers": {
    "maxed": {
      "command": "maxed-mcp",
      "env": { "CPA_WORKPAPER_SPEC_DIR": "/path/to/cpa-workpaper-spec" }
    }
  }
}
```

## Tools (JSON in, JSON out)

Call `list_capabilities` first. It is the honest capability manifest: it returns
`{ok, server, version, tools: [{name, backend, available, install?, summary}]}`
so an agent knows which backends exist on this host before calling anything.

| Tool | Backing repo | Availability |
|---|---|---|
| `list_capabilities` | in-process | always |
| `normalize_bank_statement(content, fmt?, default_currency?, dedup?, invert_amounts?)` | [statement-normalizer](https://github.com/maxed-oss/statement-normalizer) CLI | needs `pip install statement-normalizer` |
| `normalize_ofx(content, fmt?, invert_amounts?)` | [ofx-normalizer](https://github.com/maxed-oss/ofx-normalizer) `ofxnorm` | needs the Go binary on PATH |
| `classify_document(text, min_score?)` | [doc-classifier-kit](https://github.com/maxed-oss/doc-classifier-kit) CLI | needs `pip install doc-classifier-kit` |
| `validate_workpaper(document, schema)` | [cpa-workpaper-spec](https://github.com/maxed-oss/cpa-workpaper-spec) validator | needs `CPA_WORKPAPER_SPEC_DIR` |
| `money_allocate(minor_units, currency, ratios?\|parts?, exponent?)` | [money-rs](https://github.com/maxed-oss/money-rs) semantics, in-process | always |
| `money_apply_rate(minor_units, currency, rate, rounding?, exponent?)` | [money-rs](https://github.com/maxed-oss/money-rs) semantics, in-process | always |
| `money_sum(amounts, currency, exponent?)` | [money-rs](https://github.com/maxed-oss/money-rs) semantics, in-process | always |
| `verify_webhook_hmac(scheme, secret, body, signature, prefix?, tolerance_seconds?, timestamp?)` | [webhook-hmac-verifier](https://github.com/maxed-oss/webhook-hmac-verifier) semantics, in-process | always |

Full per-tool argument and return shapes are in [`llms.txt`](llms.txt).

## Error envelope (uniform)

Every tool returns a JSON object. Success carries `"ok": true` plus tool fields;
failure carries:

```json
{"ok": false, "error": {"code": "tool_unavailable", "message": "...", "detail": {"hint": "pip install statement-normalizer"}}}
```

`error.code` is one of: `tool_unavailable`, `bad_request`, `command_failed`,
`invalid_json_output`, `timeout`, `exec_error`, `unknown_scheme`. A tool whose
backend is absent returns `tool_unavailable` with an install hint. It never
fakes a result.

## Backend resolution (env overrides)

`MAXED_MCP_STATEMENT_NORMALIZER`, `MAXED_MCP_DOC_CLASSIFIER`,
`MAXED_MCP_OFXNORM`, `MAXED_MCP_CPA_WORKPAPER_VALIDATE` each take a full command
line; otherwise the console script / binary on PATH is used, then a `python -m`
fallback. `CPA_WORKPAPER_SPEC_DIR` points the validator at a spec checkout.

## Determinism

Same input, same output. No network calls; shelled-out tools do only local work.
The in-process `money_*` and `verify_webhook_hmac` tools mirror the canonical
Rust and Go libraries exactly, so the answer is identical either way.

## Build / test

`pip install -e ".[dev,suite]"`, `pytest -q`.
