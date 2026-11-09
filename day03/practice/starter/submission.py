"""Day 3 — 장애 원인 조사 Agent.

도구 세 개로 장애 원인을 좁혀 갑니다.

[중요]
  1. 함수·상수 이름을 바꾸지 마세요.
  2. 모델은 함수 안에서 만듭니다. `llm` 인자가 오면 그것을 씁니다.
  3. 도구는 결정적이어야 합니다. 같은 인자에 항상 같은 결과를 돌려주세요.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field

MODEL_ID = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
REGION = "us-east-1"

DATA = json.loads(
    (Path(__file__).resolve().parent.parent / "data" / "ops_fixtures.json").read_text(
        encoding="utf-8"
    )
)


def _default_llm():
    from langchain_aws import ChatBedrockConverse

    return ChatBedrockConverse(model=MODEL_ID, region_name=REGION, temperature=0)


# ══════════════════════════════════════════════════════════════════
# 기초 파트 (7점)
# ══════════════════════════════════════════════════════════════════

# TODO: 각 도구의 인자 스키마를 정의하세요.
class DeployArgs(BaseModel):
    service: str = Field(..., description="TODO: 어떤 값을 넣어야 하는지 적으세요.")


@tool(args_schema=DeployArgs)
def get_deploy_history(service: str) -> str:
    """TODO: 이 도구가 무엇을 하고 언제 써야 하는지 30자 이상으로 적으세요.

    모델이 보는 것은 이 설명문뿐입니다. '언제 쓰지 말아야 하는지'도 적으면 좋습니다.
    """
    # TODO: DATA["deploys"]에서 조회해 사람이 읽을 수 있는 문자열로 반환하세요.
    raise NotImplementedError("get_deploy_history 를 구현하세요.")


# TODO: get_logs 를 만드세요.
#   - 인자: service, since (배포 시각). since가 있으면 그 시점 로그를 봅니다.
#   - 이 도구는 get_deploy_history 결과가 있어야 제대로 쓸 수 있습니다.

# TODO: get_metrics 를 만드세요.
#   - 인자: service
#   - DATA["metrics"]에서 조회합니다.


# TODO: 위에서 만든 도구들을 여기에 모으세요.
TOOLS: list = []


def build_agent(llm=None):
    """도구를 쓸 수 있는 Agent 그래프를 만들어 컴파일해 반환합니다.

    반드시 지킬 것:
      - agent 노드와 tools 노드 사이에 순환이 있어야 합니다.
      - 탈출 조건이 있어야 합니다. 없으면 무한 루프입니다.

    create_react_agent를 써도 되고 StateGraph로 직접 만들어도 됩니다.
    심화 파트를 구현했다면 should_stop 판정을 그래프에 연결하세요.
    """
    llm = llm or _default_llm()
    # TODO: 구현하세요.
    raise NotImplementedError("build_agent 를 구현하세요.")


# ══════════════════════════════════════════════════════════════════
# 심화 파트 (3점) — 못 해도 과제는 통과합니다
# ══════════════════════════════════════════════════════════════════

# TODO: 한 번의 조사에서 허용할 도구 호출 상한 (3 이상 8 이하)
MAX_TOOL_CALLS = 0


def should_stop(messages: list, tool_calls_made: int) -> tuple[bool, str]:
    """더 조사할지 멈출지 결정합니다. LLM을 호출하지 않습니다.

    판정 규칙:
      - tool_calls_made >= MAX_TOOL_CALLS        -> (True, "예산 초과")
      - 같은 도구를 같은 인자로 2회 이상 호출함  -> (True, "중복 호출")
      - 세 도구를 모두 한 번 이상 호출함         -> (True, "근거 충분")
      - 그 외                                    -> (False, 아무 문자열)

    Args:
        messages: 지금까지의 메시지 목록. 도구 호출 기록이 들어 있습니다.
        tool_calls_made: 지금까지 실행한 도구 호출 횟수

    Returns:
        (중단할지 여부, 이유 문자열)
    """
    # TODO: 구현하세요.
    raise NotImplementedError("should_stop 을 구현하세요.")
