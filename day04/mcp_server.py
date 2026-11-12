"""Day 4 — 운영 지원 MCP 서버.

submission.py 의 TOOL_SPECS / TOOLS_IMPL 을 읽어
fastmcp 서버로 노출합니다. 자산 조회 도구(ASSET_TOOL_SPECS)도 함께 노출합니다.

실행:
    python day04/mcp_server.py              # stdio 전송 (MCP 클라이언트가 프로세스로 띄우는 방식)
    python day04/mcp_server.py --http       # HTTP 전송 (http://127.0.0.1:8000/mcp)
    python day04/mcp_server.py --check      # 서버를 띄우지 않고 메모리 안에서 도구 목록·호출 확인

주의: stdio 전송에서는 print를 쓰면 프로토콜이 깨집니다. 로그는 stderr로 보내세요.

[MCP가 M×N을 M+N으로 바꾸는 지점]
  도구 함수(M개)는 이 서버 하나에만 등록합니다. 클라이언트(N개: Agent, Supervisor, 다른 팀 도구)는
  MCP 규약으로 이 서버에 붙기만 하면 같은 도구를 씁니다.
  그래서 도구 설명문과 인자 설명이 곧 "다른 클라이언트가 읽는 유일한 문서"가 됩니다.
"""

from __future__ import annotations

import inspect
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "practice" / "starter"))

# submission 은 위 sys.path 조작으로 실행 시점에만 찾을 수 있어 정적 분석기(Pylance)는 경로를 모릅니다.
# Day마다 submission.py 가 따로 있으므로 워크스페이스 extraPaths 대신 이 줄에서만 경고를 끕니다.
from submission import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    ASSET_TOOL_SPECS,
    ASSET_TOOLS_IMPL,
    TOOL_SPECS,
    TOOLS_IMPL,
)

# stdio 전송에서 stdout은 MCP 메시지 통로입니다. 로그는 반드시 stderr로 보냅니다.
logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(name)s %(message)s")
log = logging.getLogger("sds.day04.mcp")


def _all_tools() -> list[tuple[dict, object]]:
    """(명세, 함수) 쌍 목록입니다. 필수 3개 + 자산 조회 2개."""
    pairs = [(spec, TOOLS_IMPL[spec["name"]]) for spec in TOOL_SPECS]
    pairs += [(spec, ASSET_TOOLS_IMPL[spec["name"]]) for spec in ASSET_TOOL_SPECS]
    return pairs


def _check_spec_matches(spec: dict, fn) -> None:
    """명세의 args 와 함수의 실제 인자 이름이 같은지 기동 시점에 확인합니다.

    MCP 클라이언트는 함수 시그니처로 만든 inputSchema 를 보고 인자를 채웁니다.
    명세(args)에는 'symptom' 이라 적고 함수는 'keyword' 를 받으면,
    문서와 실제가 어긋나 모델이 틀린 인자 이름으로 부르게 됩니다. 그런 상태로는 서버를 띄우지 않습니다.
    """
    params = set(inspect.signature(fn).parameters)
    declared = set(spec["args"])
    if params != declared:
        raise ValueError(
            f"'{spec['name']}' 명세 인자 {sorted(declared)} 와 함수 인자 {sorted(params)} 가 다릅니다."
        )


def build_server():
    """TOOL_SPECS를 순회하며 fastmcp에 도구를 등록합니다."""
    from fastmcp import FastMCP

    mcp = FastMCP("sds-ops")

    for spec, fn in _all_tools():
        _check_spec_matches(spec, fn)
        # 명세의 설명을 그대로 도구 설명으로 씁니다.
        # 인자 설명은 함수 시그니처의 Annotated[..., Field(description=...)] 에서
        # inputSchema 로 들어갑니다. (submission.py 에서 명세 args 와 같은 상수를 씀)
        mcp.tool(name=spec["name"], description=spec["description"])(fn)
        log.info("도구 등록: %s", spec["name"])

    return mcp


async def _self_check() -> None:
    """서버를 메모리 안에서 띄워 도구 목록과 호출 결과를 확인합니다. (실제 LLM 호출 없음)"""
    from fastmcp import Client

    async with Client(build_server()) as client:
        tools = await client.list_tools()
        for t in tools:
            props = t.inputSchema.get("properties", {})
            missing = [name for name, p in props.items() if not p.get("description")]
            status = "OK" if not missing else f"인자 설명 없음: {missing}"
            print(f"- {t.name}: 인자 {list(props)} [{status}]", file=sys.stderr)

        for name, args in [
            ("search_runbook", {"symptom": "5xx"}),
            ("get_service_owner", {"service": "payment-api"}),
            ("query_recent_incidents", {"service": "no-such-service"}),
            ("get_asset_status", {"asset_id": "SRV-002"}),
            ("get_asset_status_backup", {"asset_id": "SRV-999"}),
        ]:
            result = await client.call_tool(name, args)
            text = "".join(getattr(c, "text", "") for c in result.content)
            print(f"\n[{name}({args})]\n{text}", file=sys.stderr)


if __name__ == "__main__":
    if "--check" in sys.argv:
        import asyncio

        asyncio.run(_self_check())
    elif "--http" in sys.argv:
        build_server().run(transport="http", host="127.0.0.1", port=8000)
    else:
        build_server().run()
