"""Day 4 — 운영 지원 MCP 서버.

practice/starter/submission.py 의 TOOL_SPECS / TOOLS_IMPL 을 읽어
fastmcp 서버로 노출합니다.

실행:
    python day04/mcp_server.py

주의: stdio 전송에서는 print를 쓰면 프로토콜이 깨집니다. 로그는 stderr로 보내세요.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "practice" / "starter"))

from submission import TOOL_SPECS, TOOLS_IMPL  # noqa: E402


def build_server():
    """TOOL_SPECS를 순회하며 fastmcp에 도구를 등록합니다."""
    from fastmcp import FastMCP

    mcp = FastMCP("sds-ops")

    for spec in TOOL_SPECS:
        fn = TOOLS_IMPL[spec["name"]]
        # 명세의 설명을 그대로 도구 설명으로 씁니다.
        mcp.tool(name=spec["name"], description=spec["description"])(fn)

    return mcp


if __name__ == "__main__":
    build_server().run()
