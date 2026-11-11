"""Day 3 — 장애 원인 조사 Agent.

도구 세 개로 장애 원인을 좁혀 갑니다.

[중요]
  1. 함수·상수 이름을 바꾸지 마세요.
  2. 모델은 함수 안에서 만듭니다. `llm` 인자가 오면 그것을 씁니다.
  3. 도구는 결정적이어야 합니다. 같은 인자에 항상 같은 결과를 돌려주세요.

[전체 흐름]
  START → agent ─(도구 호출 없음)→ END
            │(도구 호출 있음)
            ▼
          tools ─(should_stop=False)→ agent      ← ReAct 순환
            │(should_stop=True)
            ▼
         finalize → END                          ← 도구 없이 결론만 정리

  - agent    : 모델이 지금까지의 대화를 보고 다음에 부를 도구를 고릅니다.
  - tools    : 모델이 요청한 도구를 실제로 실행하고 ToolMessage를 남깁니다.
  - finalize : 예산 초과·중복 호출·근거 충분으로 멈출 때, 도구 없이 결론을 씁니다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel, Field

MODEL_ID = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
REGION = "us-east-1"

# 교육용 더미 데이터입니다. (practice/data/ops_fixtures.json)
# 데이터를 읽는 것은 모델 생성이 아니므로 모듈 최상단에 두어도 됩니다.
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

# 세 도구가 공유하는 서비스 이름 설명입니다.
# 모델은 이 description을 읽고 인자 값을 정하므로, 가능한 값까지 적어 둡니다.
_SERVICE_DESC = (
    "조회할 서비스 이름. 예: 'payment-api', 'auth-service'. "
    "사용자 질문에 나온 서비스 이름을 그대로 넣으세요."
)


def _normalize_service(service: str) -> str:
    """서비스 이름의 앞뒤 공백을 지웁니다. 값이 없으면 빈 문자열로 바꿉니다."""
    return (service or "").strip()


def _empty_service_message(tool_name: str) -> str:
    """서비스 이름이 비었을 때 모델이 다음 행동을 고칠 수 있도록 안내합니다.

    예외를 던지지 않고 문자열을 돌려주는 이유:
      예외가 나면 조사 루프 전체가 깨지지만, 안내 문장을 돌려주면
      모델이 그것을 읽고 올바른 서비스 이름으로 다시 호출할 수 있습니다.
    """
    return (
        f"[{tool_name}] 서비스 이름이 비어 있습니다. "
        "'payment-api'처럼 조회할 서비스 이름을 넣어 다시 호출하세요."
    )


# ── 도구 1: 배포 이력 (판단형 — 여러 배포 중 가장 최근 배포를 골라냄) ──

class DeployArgs(BaseModel):
    service: str = Field(..., description=_SERVICE_DESC)


@tool(args_schema=DeployArgs)
def get_deploy_history(service: str) -> str:
    """서비스의 배포 이력(버전, 배포 시각, 배포 주체)과 가장 최근 배포 시각을 조회합니다.

    언제 쓰는가: 장애 원인을 조사할 때 가장 먼저 부르세요. 장애 직전에 배포가
    있었는지, 있었다면 정확한 배포 시각이 언제인지 알아낼 때 씁니다.
    여기서 얻은 배포 시각은 get_logs의 since 인자로 그대로 넘기세요.
    쓰지 말 것: 에러 내용(로그)이나 오류율·지연 같은 수치(지표)를 볼 때는 쓰지 마세요.
    """
    name = _normalize_service(service)
    if not name:
        return _empty_service_message("get_deploy_history")

    deploys = DATA["deploys"].get(name)
    if not deploys:
        return f"[get_deploy_history] '{name}' 서비스의 배포 이력이 없습니다."

    lines = [f"[get_deploy_history] {name} 배포 이력 ({len(deploys)}건)"]
    latest = deploys[0]
    for i, d in enumerate(deploys):
        lines.append(f"{i + 1}. {d['version']} — 배포 시각 {d['at']} (배포 주체: {d['by']})")
        # ISO8601 문자열은 같은 시간대라면 문자열 크기 비교가 곧 시간 비교입니다.
        if d["at"] > latest["at"]:
            latest = d
    lines.append(
        f"가장 최근 배포 시각: {latest['at']} "
        "→ 이 시각을 get_logs의 since 인자로 넘겨 배포 직후 로그를 확인하세요."
    )
    return "\n".join(lines)


# ── 도구 2: 로그 (조회형 — 배포 시각을 받아 그 구간 로그를 찾음, 연쇄의 뒷단) ──

class LogsArgs(BaseModel):
    service: str = Field(..., description=_SERVICE_DESC)
    since: str = Field(
        default="",
        description=(
            "로그를 볼 기준 시각(ISO8601, 예: '2026-08-11T02:58:00+09:00'). "
            "get_deploy_history가 돌려준 배포 시각을 그대로 넣으세요. "
            "비워 두면 평상시 기본 로그만 나옵니다."
        ),
    )


@tool(args_schema=LogsArgs)
def get_logs(service: str, since: str = "") -> str:
    """서비스의 특정 시각(주로 배포 시각) 전후 애플리케이션 로그를 조회합니다.

    언제 쓰는가: 배포 시각을 알고 난 뒤, 그 시각 전후에 어떤 에러나 경고가
    찍혔는지 확인할 때 씁니다. 배포 시각을 아직 모르면 먼저 get_deploy_history를
    부르고, 그 결과의 배포 시각을 since에 넣으세요.
    쓰지 말 것: 배포 버전이나 오류율·지연 같은 수치가 궁금할 때는 쓰지 마세요.
    """
    name = _normalize_service(service)
    if not name:
        return _empty_service_message("get_logs")

    logs = DATA["logs"]
    when = (since or "").strip()

    # 1) since가 있으면 그 시각의 로그를 먼저 찾습니다. 연쇄의 핵심입니다.
    if when:
        key = f"{name}@{when}"
        if key in logs:
            return f"[get_logs] {name} 로그 (기준 시각 {when})\n{logs[key]}"

    # 2) 해당 시각 로그가 없거나 since가 비었으면 기본 로그로 대체합니다.
    default_key = f"{name}@default"
    if default_key in logs:
        if when:
            note = f"기준 시각 {when}의 로그가 없어 평상시 기본 로그를 보여 줍니다."
        else:
            note = "since가 없어 평상시 기본 로그를 보여 줍니다. 배포 시각을 알면 since에 넣어 다시 조회하세요."
        return f"[get_logs] {name} 로그\n({note})\n{logs[default_key]}"

    return f"[get_logs] '{name}' 서비스의 로그가 없습니다."


# ── 도구 3: 지표 (계산형 — 백분율로 환산하고 기준값과 비교해 이상 여부를 붙임) ──

class MetricsArgs(BaseModel):
    service: str = Field(..., description=_SERVICE_DESC)


# 지표 이상 판정 기준입니다. 교육용 고정값이며 LLM 없이 코드로 판단합니다.
_THRESHOLDS = {"error_rate_5m": 0.05, "p99_latency_ms": 1000, "cpu": 0.80}


@tool(args_schema=MetricsArgs)
def get_metrics(service: str) -> str:
    """서비스의 현재 핵심 지표(5분 오류율, p99 지연, CPU)를 조회하고 이상 여부를 판정합니다.

    언제 쓰는가: 장애의 규모와 영향(오류율이 얼마나 올랐는지, 지연이 얼마나 늘었는지)을
    수치로 확인할 때 씁니다. 원인 조사를 마무리하며 영향 범위를 확인할 때도 씁니다.
    쓰지 말 것: 에러 메시지 내용은 get_logs, 배포 버전·시각은 get_deploy_history를 쓰세요.
    """
    name = _normalize_service(service)
    if not name:
        return _empty_service_message("get_metrics")

    m = DATA["metrics"].get(name)
    if not m:
        return f"[get_metrics] '{name}' 서비스의 지표가 없습니다."

    def flag(key: str) -> str:
        return "이상" if m[key] >= _THRESHOLDS[key] else "정상"

    return "\n".join(
        [
            f"[get_metrics] {name} 지표",
            f"- 5분 오류율: {m['error_rate_5m'] * 100:.1f}% ({flag('error_rate_5m')}, 기준 5%)",
            f"- p99 지연: {m['p99_latency_ms']}ms ({flag('p99_latency_ms')}, 기준 1000ms)",
            f"- CPU 사용률: {m['cpu'] * 100:.0f}% ({flag('cpu')}, 기준 80%)",
        ]
    )


TOOLS: list = [get_deploy_history, get_logs, get_metrics]


SYSTEM_PROMPT = """당신은 운영 장애 원인을 조사하는 당직 엔지니어 보조 Agent입니다.

조사 순서:
1. get_deploy_history로 최근 배포가 있었는지, 배포 시각이 언제인지 확인합니다.
2. 그 배포 시각을 get_logs의 since 인자로 그대로 넘겨 배포 직후 로그를 확인합니다.
3. get_metrics로 오류율·지연 등 영향 규모를 확인합니다.

규칙:
- 매번 직전 도구 결과를 읽고 다음에 무엇을 조회할지 다시 판단하세요.
- 같은 도구를 같은 인자로 다시 부르지 마세요.
- 개념 설명처럼 운영 데이터가 필요 없는 질문에는 도구를 쓰지 말고 바로 답하세요.
- 결론에는 근거가 된 도구 결과(버전, 시각, 에러 메시지, 수치)를 인용하세요."""

FINALIZE_PROMPT = """더 이상 도구를 부르지 말고, 지금까지 수집한 도구 결과만 근거로
장애 원인 추정, 근거, 권장 조치를 한국어로 간결하게 정리하세요."""


def get_text(message):
    """ChatBedrockConverse는 content를 블록 리스트로 주기도 하므로 텍스트만 모아 반환합니다."""
    content = message.content
    if isinstance(content, list):
        return "".join(block.get("text", "") for block in content if isinstance(block, dict))
    return content


class AgentState(TypedDict):
    """그래프가 노드 사이로 주고받는 상태입니다.

    add_messages reducer 덕분에 노드가 새 메시지만 리스트로 반환하면
    기존 대화 기록 뒤에 알아서 누적됩니다. (ReAct 수동 루프의 messages.append 자리)
    """

    messages: Annotated[list, add_messages]


def _count_tool_messages(messages: list) -> int:
    """지금까지 실제로 실행된 도구 호출 수 = ToolMessage 개수."""
    return sum(1 for m in messages if isinstance(m, ToolMessage))


def build_agent(llm=None):
    """도구를 쓸 수 있는 Agent 그래프를 만들어 컴파일해 반환합니다.

    반드시 지킬 것:
      - agent 노드와 tools 노드 사이에 순환이 있어야 합니다.
      - 탈출 조건이 있어야 합니다. 없으면 무한 루프입니다.

    create_react_agent 대신 StateGraph로 직접 조립합니다.
    순환의 탈출 조건은 두 군데입니다.
      1. agent가 도구를 부르지 않으면 END (모델이 스스로 답을 끝낸 경우)
      2. tools 실행 뒤 should_stop이 True면 finalize → END (코드가 강제로 끊는 경우)
    """
    # 모델 생성은 반드시 함수 안에서 합니다. 채점기는 가짜 모델을 주입합니다.
    llm = llm or _default_llm()
    llm_with_tools = llm.bind_tools(TOOLS)

    # [수동 루프의 invoke와 append] -> agent 노드
    def agent_node(state: AgentState) -> dict[str, Any]:
        """모델이 대화를 보고 다음에 부를 도구를 고릅니다 (ReAct의 '생각' 단계)."""
        messages = [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]
        return {"messages": [llm_with_tools.invoke(messages)]}

    # [수동 루프의 if not ai_message.tool_calls] -> 라우팅 함수
    def route_after_agent(state: AgentState) -> Literal["tools", "end"]:
        """도구 호출이 있으면 tools로, 없으면 조사를 끝냅니다."""
        last = state["messages"][-1]
        return "tools" if last.tool_calls else "end"

    # [while 루프의 안전장치] -> 도구 실행 뒤 계속할지 판정하는 라우팅 함수
    def route_after_tools(state: AgentState) -> Literal["agent", "finalize"]:
        """도구 결과를 관찰한 뒤 계속 조사할지 코드로 판정합니다 (LLM 미사용)."""
        messages = state["messages"]
        result = should_stop(messages, _count_tool_messages(messages))  # (중단 여부, 이유)
        return "finalize" if result[0] else "agent"

    def finalize_node(state: AgentState) -> dict[str, Any]:
        """도구 없이 지금까지의 근거로 결론만 정리합니다.

        "도구를 더 부르지 말라"고 지시한 뒤 응답에서 텍스트만 꺼내
        도구 요청이 없는 AIMessage로 남깁니다. 그래서 루프가 다시 돌지 않습니다.
        """
        messages = state["messages"]
        reason = should_stop(messages, _count_tool_messages(messages))[1]  # 이유만 씁니다
        # 멈추라는 지시는 사용자 메시지로 덧붙입니다. (SystemMessage는 맨 앞 하나만 둡니다)
        instruction = HumanMessage(content=f"조사를 여기서 멈춥니다. (중단 이유: {reason})\n{FINALIZE_PROMPT}")
        prompt = [SystemMessage(content=SYSTEM_PROMPT)] + messages + [instruction]
        text = (get_text(llm_with_tools.invoke(prompt)) or "").strip()
        if not text:
            text = f"조사를 중단했습니다({reason}). 위 도구 결과를 근거로 원인을 판단하세요."
        return {"messages": [AIMessage(content=text)]}

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", ToolNode(TOOLS))   # [도구 실행과 ToolMessage 포장] -> 내장 ToolNode
    graph.add_node("finalize", finalize_node)

    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", route_after_agent, {"tools": "tools", "end": END})
    graph.add_conditional_edges(                # [while 루프] -> tools에서 agent로 돌아가는 Cycle
        "tools", route_after_tools, {"agent": "agent", "finalize": "finalize"}
    )
    graph.add_edge("finalize", END)
    return graph.compile()


# ══════════════════════════════════════════════════════════════════
# 심화 파트 (3점) — 못 해도 과제는 통과합니다
# ══════════════════════════════════════════════════════════════════

# 한 번의 조사에서 허용할 도구 호출 상한 (3 이상 8 이하)
# 도구 3개를 한 번씩 + 인자를 고쳐 다시 부를 여유 2회.
# [제약] 상한 판정은 tools 노드 실행이 끝난 뒤에 합니다. 그래서 모델이 한 턴에
#        여러 도구를 동시에 요청하면, 그 턴의 호출 수만큼 상한을 넘을 수 있습니다.
MAX_TOOL_CALLS = 5

_REQUIRED_TOOLS = ["get_deploy_history", "get_logs", "get_metrics"]


def _called_tools(messages: list) -> list:
    """메시지에서 (도구 이름, 인자 dict) 목록을 호출 순서대로 뽑습니다.

    도구 호출 기록은 AIMessage의 tool_calls에 들어 있습니다.
    """
    calls = []
    for m in messages:
        if isinstance(m, AIMessage):
            for tc in m.tool_calls:
                calls.append((tc["name"], tc["args"]))
    return calls


def should_stop(messages: list, tool_calls_made: int) -> tuple[bool, str]:
    """더 조사할지 멈출지 결정합니다. LLM을 호출하지 않습니다.

    판정 규칙 (위에서부터 먼저 걸리는 것을 이유로 씁니다):
      - tool_calls_made >= MAX_TOOL_CALLS        -> (True, "예산 초과")
      - 같은 도구를 같은 인자로 2회 이상 호출함  -> (True, "중복 호출")
      - 세 도구를 모두 한 번 이상 호출함         -> (True, "근거 충분")
      - 그 외                                    -> (False, "조사 계속")

    Args:
        messages: 지금까지의 메시지 목록. 도구 호출 기록이 들어 있습니다.
        tool_calls_made: 지금까지 실행한 도구 호출 횟수

    Returns:
        (중단할지 여부, 이유 문자열)
    """
    if tool_calls_made >= MAX_TOOL_CALLS:
        return True, "예산 초과"

    calls = _called_tools(messages)

    # 앞에서 이미 본 (이름, 인자)가 또 나오면 중복 호출입니다.
    # dict끼리 == 비교는 키 순서와 상관없이 내용만 비교하므로 in으로 찾을 수 있습니다.
    seen = []
    for call in calls:
        if call in seen:
            return True, "중복 호출"
        seen.append(call)

    # 필수 도구 중 하나라도 아직 안 불렀으면 조사를 계속합니다.
    called_names = [call[0] for call in calls]   # call = (도구 이름, 인자)
    for name in _REQUIRED_TOOLS:
        if name not in called_names:
            return False, "조사 계속"

    return True, "근거 충분"


def run_and_trace(agent, question: str) -> None:
    """질문 하나를 실행하고 도구 호출 순서와 최종 답을 출력합니다."""
    print(f"\n{'=' * 60}\n질문: {question}\n{'=' * 60}")
    result = agent.invoke({"messages": [HumanMessage(content=question)]})
    for m in result["messages"]:
        label = type(m).__name__
        if getattr(m, "tool_calls", None):
            for tc in m.tool_calls:
                print(f"  [{label}] 도구 요청: {tc['name']}({tc['args']})")
        elif isinstance(m, ToolMessage):
            print(f"  [{label}] {get_text(m)[:150]}")
        elif get_text(m):
            print(f"  [{label}] {get_text(m)[:300]}")


if __name__ == "__main__":
    # 실제 Bedrock으로 한 번 돌려 보는 진입점입니다. (채점기는 이 블록을 실행하지 않습니다)
    #   python day03/practice/starter/submission.py
    agent = build_agent()
    try:
        print(agent.get_graph().draw_mermaid())   # 그래프 구조 확인 (agent ↔ tools 순환)
    except Exception as e:
        print("그래프 출력은 건너뜁니다:", e)

    # eval_set.json의 d3- 문항과 같은 세 경로를 확인합니다.
    run_and_trace(agent, "ReAct 루프가 무엇인가요?")                           # no_tool
    run_and_trace(agent, "payment-api의 현재 p99 지연은 얼마인가요?")          # single_tool
    run_and_trace(agent, "8월 11일 새벽 payment-api 5xx 급증 원인을 조사해 주세요.")  # multi_tool
