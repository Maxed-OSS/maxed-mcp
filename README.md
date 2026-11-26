# maxed-mcp

[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

One [Model Context Protocol](https://modelcontextprotocol.io) server that fronts
the deterministic tools in the open-source accounting suite, so an AI agent can
call them the same way it calls any other MCP tool.

Agents are good at judgement and bad at arithmetic, parsing, and signature
checks. This server hands the deterministic, auditable work to the libraries
built for it: parse a bank statement, classify a document, validate a workpaper
against the open spec, do exact money math, and verify a webhook signature.
Every tool returns structured JSON and a uniform error envelope. Nothing here is
generative, and nothing is faked: when a backing tool is not installed, the tool
says so and tells the agent how to install it, rather than inventing an answer.

This is the agentic front door to the suite. The parsers and validators live in
their own repositories and stay the single source of truth for their behavior;
maxed-mcp shells out to the ones that ship a CLI and parses their JSON, and
computes the small pure primitives (money math, HMAC) in-process, mirroring the
semantics of their canonical sibling libraries.

## Tools

| Tool | What it does | Backend |
|---|---|---|
| `list_capabilities` | List every tool and whether its backend is installed on this host. | in-process |
| `normalize_bank_statement` | Parse CSV / OFX / QFX / MT940 / CAMT / QIF / text into normalized transaction JSON. | [statement-normalizer](https://github.com/maxed-oss/statement-normalizer) CLI |
| `normalize_ofx` | Parse an OFX/QFX or CSV bank export into normalized transaction JSON. | [ofx-normalizer](https://github.com/maxed-oss/ofx-normalizer) `ofxnorm` (Go) |
| `classify_document` | Classify accounting document text: `w2`, `form_1099`, `invoice`, `bank_statement`, `receipt`, or `unknown`. | [doc-classifier-kit](https://github.com/maxed-oss/doc-classifier-kit) CLI |
| `validate_workpaper` | Validate a document against a [cpa-workpaper-spec](https://github.com/maxed-oss/cpa-workpaper-spec) JSON Schema. | spec validator |
| `money_allocate` | Split an amount across ratios or evenly, with no lost minor units. | [money-rs](https://github.com/maxed-oss/money-rs) semantics |
| `money_apply_rate` | Apply a rate (tax, tip, share) with explicit rounding. | [money-rs](https://github.com/maxed-oss/money-rs) semantics |
| `money_sum` | Sum integer minor-unit amounts exactly, with no floating-point drift. | [money-rs](https://github.com/maxed-oss/money-rs) semantics |
| `verify_webhook_hmac` | Constant-time verify a Stripe / hex / base64 webhook HMAC signature. | [webhook-hmac-verifier](https://github.com/maxed-oss/webhook-hmac-verifier) semantics |

`money_*` and `verify_webhook_hmac` are computed in-process and are always
available; they faithfully mirror the rules of the canonical Rust and Go
libraries so an agent gets the same answer either way. The four parser and
validator tools shell out to a sibling CLI; call `list_capabilities` first to
see which are installed.

## Install

```sh
pip install maxed-mcp

# Make the two Python-backed tools available out of the box:
pip install "maxed-mcp[suite]"      # adds statement-normalizer + doc-classifier-kit
```

Optional backends for the remaining shell-backed tools:

- `normalize_ofx`: build the Go binary and put it on `PATH`
  (`go install github.com/maxed-oss/ofx-normalizer/cmd/ofxnorm@latest`).
- `validate_workpaper`: point `CPA_WORKPAPER_SPEC_DIR` at a `cpa-workpaper-spec`
  checkout (the directory containing `validator/validate.py`).

## Run

```sh
maxed-mcp            # start the server on stdio
python -m maxed_mcp  # equivalent
```

The server speaks MCP over stdio, so it plugs into any MCP client. Register it
with a client like this (the exact file differs per client):

```json
{
  "mcpServers": {
    "maxed": {
      "command": "maxed-mcp",
      "env": {
        "CPA_WORKPAPER_SPEC_DIR": "/path/to/cpa-workpaper-spec"
      }
    }
  }
}
```

## Backend resolution

Each shell-backed tool resolves its command in this order:

1. an explicit environment variable (a full command line):
   `MAXED_MCP_STATEMENT_NORMALIZER`, `MAXED_MCP_DOC_CLASSIFIER`,
   `MAXED_MCP_OFXNORM`, `MAXED_MCP_CPA_WORKPAPER_VALIDATE`;
2. the tool's console-script (or `ofxnorm` binary) on `PATH`;
3. a fallback: `python -m ...` for the Python tools, or a sibling
   `cpa-workpaper-spec/` checkout for the validator (`CPA_WORKPAPER_SPEC_DIR`).

If nothing resolves, the tool returns `{"ok": false, "error": {"code":
"tool_unavailable", ...}}` with an install hint instead of failing opaquely.

## Response shape

Every tool returns a JSON object. Success carries `"ok": true` plus tool
fields; failure carries `"ok": false` and an `error` object:

```json
{ "ok": false, "error": { "code": "tool_unavailable", "message": "...", "detail": { "hint": "..." } } }
```

See [`AGENT.md`](AGENT.md) for the condensed machine interface,
[`llms.txt`](llms.txt) for the machine-readable tool reference, and
[`examples/agent_call_example.py`](examples/agent_call_example.py) for a full,
runnable in-process client that calls every tool.

## Development

```sh
pip install -e ".[dev,suite]"
pytest -q
```

The test suite exercises the in-process tools directly and the shell-backed
tools against the installed Python siblings; tools whose backend is not present
assert the graceful `tool_unavailable` path.

## License

Apache-2.0.
