from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from .config import PROFILES, Settings


async def edit_via_mcp(args):
    """Local Ollama editing through a real MCP stdio connection."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=sys.executable, args=["-m", "word_mcp", "server"], env=dict(os.environ))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            async def call(name, data):
                result = await session.call_tool(name, data)
                if result.isError:
                    raise ValueError("\n".join(x.text for x in result.content if hasattr(x, "text")))
                if result.structuredContent is not None:
                    return result.structuredContent
                return json.loads(next(x.text for x in result.content if hasattr(x, "text")))

            proposal = await call("propose_edit", {"path": args.path, "instruction": args.instruction,
                                                   "targets": args.targets or None})
            print(json.dumps(proposal, ensure_ascii=False, indent=2))
            if args.apply:
                result = await call("apply_proposal", {"proposal_id": proposal["proposal_id"]})
                print(json.dumps(result, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description="Offline Word MCP + Ollama")
    parser.add_argument("--root", type=Path)
    parser.add_argument("--profile", choices=PROFILES)
    parser.add_argument("--model")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("server", help="Run MCP over stdio")
    web = commands.add_parser("web", help="Run local browser UI and HTTP MCP")
    web.add_argument("--port", type=int, default=8765)
    commands.add_parser("doctor", help="Check local Ollama and models")
    create = commands.add_parser("create")
    create.add_argument("path")
    create.add_argument("--title", default="")
    read = commands.add_parser("read")
    read.add_argument("path")
    edit = commands.add_parser("edit", help="Propose edits through MCP + local Ollama")
    edit.add_argument("path")
    edit.add_argument("instruction")
    edit.add_argument("--targets", nargs="*")
    edit.add_argument("--apply", action="store_true", help="Authorize applying the generated plan")
    args = parser.parse_args()
    if args.root:
        os.environ["WORD_MCP_ROOT"] = str(args.root.resolve())
    if args.profile:
        os.environ["WORD_MCP_PROFILE"] = args.profile
    if args.model:
        os.environ["WORD_MCP_MODEL"] = args.model
    settings = Settings.from_env()
    try:
        if args.command == "server":
            from .server import build_server
            build_server(settings)[0].run(transport="stdio")
        elif args.command == "web":
            import uvicorn
            from .web import create_app
            uvicorn.run(create_app(settings), host="127.0.0.1", port=args.port, log_level="warning")
        elif args.command == "edit":
            asyncio.run(edit_via_mcp(args))
        else:
            from .documents import DocumentStore
            from .ollama_client import OllamaClient
            store = DocumentStore(settings)
            if args.command == "doctor":
                result = OllamaClient(settings).status()
                result["document_root"] = str(settings.root)
            elif args.command == "create":
                result = store.create(args.path, args.title)
            else:
                result = store.snapshot(args.path)
            print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, FileNotFoundError, PermissionError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
