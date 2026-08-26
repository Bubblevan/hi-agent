"""A safe read-only Mini-MCP example for the Hi-Agent protocol lab.

The server exposes read_file and grep_code while restricting both tools to one
explicit root directory. It is intentionally small and educational.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import re
from typing import Any

from protocols.mcp.mini_mcp import MiniMCPHTTPServer, MiniMCPServer, run_stdio


def safe_path(root: Path, relative_path: str) -> Path:
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("path escapes the configured root") from exc
    return candidate


def build_server(root: Path) -> MiniMCPServer:
    root = root.resolve()
    server = MiniMCPServer(name="hi-agent-filesystem-mini", version="0.1.0")

    server.register(
        "read_file",
        lambda args: safe_path(root, args["path"]).read_text(encoding="utf-8"),
        description="Read one UTF-8 text file below the configured root.",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string", "minLength": 1}},
            "required": ["path"],
            "additionalProperties": False,
        },
    )

    def grep_code(args: dict[str, Any]) -> dict[str, Any]:
        pattern = args["pattern"]
        base = safe_path(root, args.get("path", "."))
        regex = re.compile(pattern)
        matches: list[dict[str, Any]] = []
        for path in base.rglob("*"):
            if not path.is_file() or path.stat().st_size > 1_000_000:
                continue
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except UnicodeDecodeError:
                continue
            for line_number, line in enumerate(lines, start=1):
                if regex.search(line):
                    matches.append(
                        {
                            "path": str(path.relative_to(root)),
                            "line": line_number,
                            "text": line,
                        }
                    )
        return {"matches": matches}

    server.register(
        "grep_code",
        grep_code,
        description="Search UTF-8 text files below the configured root.",
        input_schema={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "minLength": 1},
                "path": {"type": "string"},
            },
            "required": ["pattern"],
            "additionalProperties": False,
        },
    )
    return server


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--http", action="store_true")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    server = build_server(args.root)
    if args.http:
        MiniMCPHTTPServer(server, port=args.port).serve_forever()
    else:
        run_stdio(server)


if __name__ == "__main__":
    main()
