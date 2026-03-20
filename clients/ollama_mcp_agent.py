import argparse
import json
import sys
from fl_studio_agent_mcp.ollama_agent import run_ollama_mcp_agent_sync


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ollama -> MCP agent for FL Studio")
    parser.add_argument("--model", default="llama3.2", help="Ollama model name (e.g. llama3.2)")
    parser.add_argument(
        "--ollama-url",
        default="http://localhost:11434/api/chat",
        help="Ollama chat endpoint URL",
    )
    parser.add_argument(
        "--mcp-cmd",
        default=None,
        help="Command to run the MCP server (default: current python -m fl_studio_agent_mcp.server --backend midi --midi-in ... --midi-out ...)",
    )
    parser.add_argument("--midi-in", default="fl-agent 0", help="MIDI input port for the MCP server")
    parser.add_argument("--midi-out", default="fl-agent 1", help="MIDI output port for the MCP server")
    parser.add_argument("--max-tool-rounds", type=int, default=8, help="Safety cap for repeated model/tool rounds")
    parser.add_argument("request", nargs="+", help="Natural-language request")
    args = parser.parse_args(argv)

    user_request = " ".join(args.request).strip()
    if not user_request:
        print("Empty request.")
        return 2

    if args.mcp_cmd:
        mcp_command = args.mcp_cmd.split(" ")
    else:
        mcp_command = [
            sys.executable,
            "-m",
            "fl_studio_agent_mcp.server",
            "--backend",
            "midi",
            "--midi-in",
            args.midi_in,
            "--midi-out",
            args.midi_out,
        ]

    result = run_ollama_mcp_agent_sync(
            model=args.model,
            ollama_url=args.ollama_url,
            mcp_command=mcp_command,
            user_request=user_request,
            max_tool_rounds=args.max_tool_rounds,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
