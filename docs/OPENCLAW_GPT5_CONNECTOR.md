## OpenClaw / GPT-5.x Connector Plan

Status: design baseline defined on 2026-03-20.

This document fixes the integration direction for the next implementation step:

- OpenClaw should be able to drive this project's MCP tool surface on the main workstation.
- GPT-5.x should reuse the same tool surface, not a second FL-specific API.
- We should avoid introducing a remote-exposed control plane for FL Studio unless it is actually needed.

### References

- OpenClaw repo: [openclaw/openclaw](https://github.com/openclaw/openclaw)
- OpenClaw docs:
  - [Getting started](https://docs.openclaw.ai)
  - [Models](https://docs.openclaw.ai/models)
  - [OpenAI provider](https://docs.openclaw.ai/openai)
  - [OAuth](https://docs.openclaw.ai/oauth)
- OpenAI docs:
  - [MCP and Connectors](https://developers.openai.com/api/docs/guides/tools-connectors-mcp)
  - [GPT-5.4 model page](https://developers.openai.com/api/docs/models/gpt-5.4)

### Current repo baseline

The repo already has the core building block we want:

- [`src/fl_studio_agent_mcp/server.py`](D:/Coding/Projekte/fl-studio_agent/src/fl_studio_agent_mcp/server.py) exposes the FL tool surface as an MCP server.
- [`clients/ollama_mcp_agent.py`](D:/Coding/Projekte/fl-studio_agent/clients/ollama_mcp_agent.py) already shows the intended local pattern:
  - spawn MCP server as a child process,
  - connect via MCP `stdio`,
  - inspect tools dynamically,
  - let a model choose tool calls,
  - execute through the same MCP surface.

That existing client is the template for a GPT-5.x adapter.

### Transport decision

Recommended default for the workstation integration: `stdio`.

Reason:

- The current MCP server is already local-process friendly.
- The existing Ollama client already uses `mcp.client.stdio`, so the repo has a working pattern.
- `stdio` keeps FL control local to the workstation and avoids exposing a network listener just to control a desktop DAW.
- This keeps auth and permission boundaries simpler for a first GPT-5.x integration.

Important constraint from current OpenAI docs:

- OpenAI's built-in `mcp` tool in the Responses API works with remote MCP servers over Streamable HTTP or HTTP/SSE, not local `stdio`.
- That means a direct "Responses API connects straight to this Python MCP server" path is not available with the current server shape.

Implication:

- Phase 1 should use a local adapter process that talks to OpenAI on one side and to this MCP server over `stdio` on the other.
- A remote MCP wrapper is optional Phase 2 work, only if we later want OpenAI's built-in `mcp` tool instead of a local orchestration layer.

### Auth and process model

Recommended model for Phase 1:

- Run a local Python adapter process on the workstation.
- The adapter launches the MCP server as a child process.
- The adapter calls OpenAI with `OPENAI_API_KEY`.
- The MCP server keeps talking locally to FL Studio over the existing MIDI bridge or file backend.

Why this is the right first step:

- No OpenAI credential is passed into FL Studio or the bridge script.
- No inbound network service is required on the workstation.
- The adapter can centrally enforce tool allowlists, confirmations, logging, and timeouts.
- The process boundary matches the existing Ollama agent pattern, which reduces implementation risk.

OpenClaw model auth recommendation:

- Prefer OpenAI API key auth for the first integration path.
- OpenClaw's docs support both OpenAI API keys and OpenAI/Codex OAuth-style subscription auth, but API key auth is the more predictable production path for a local tool-executing adapter.
- OAuth/Codex subscription auth can remain a later optional path after the adapter itself is stable.

### Recommended architecture

Phase 1 architecture:

1. OpenClaw or CLI invokes a local GPT-5.x adapter.
2. The adapter starts this repo's MCP server via `stdio`.
3. The adapter lists MCP tools and maps them into model-usable tool definitions.
4. GPT-5.x chooses tool calls.
5. The adapter executes those calls against the MCP server.
6. The adapter returns structured results to the caller.

This is deliberately similar to [`clients/ollama_mcp_agent.py`](D:/Coding/Projekte/fl-studio_agent/clients/ollama_mcp_agent.py), but with OpenAI as the model backend.

### Safety defaults

Phase 1 safety defaults should be:

- local-only execution,
- explicit MCP command allowlist,
- short RPC timeouts inherited from the existing server,
- approval required for transport-changing or write-heavy actions when invoked from a generic chat surface,
- structured logging of tool name, args, result summary, and errors,
- no arbitrary shell/tool execution beyond the MCP server command.

For FL Studio specifically:

- `fl_get_tempo`, `fl_ping`, `fl_get_stepseq` are safe read paths.
- `fl_set_tempo`, `fl_transport`, `fl_create_drum_loop`, `fl_create_4_4_drumloop`, `fl_panic` are state-changing paths and should be clearly logged.

### Decision summary

Chosen for next implementation step:

- OpenClaw reference: `openclaw/openclaw` + official docs at `docs.openclaw.ai`
- GPT-5.x integration mode: local adapter process
- MCP transport between adapter and this repo: `stdio`
- OpenAI auth for first path: `OPENAI_API_KEY`
- Remote MCP / HTTP-SSE support: deferred until there is a concrete need for OpenAI's built-in remote `mcp` tool

### Next implementation step

Build `clients/openai_mcp_agent.py` as the GPT-5.x equivalent of the existing Ollama client:

- same MCP `stdio` session pattern,
- same dynamic tool discovery,
- OpenAI Responses API as model backend,
- configurable model name,
- configurable MCP command,
- structured JSON output for each executed tool call.
