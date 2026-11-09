"""Day 6 — Supervisor 인시던트 대응팀.

전문 Agent 셋을 Supervisor가 지휘합니다.

[중요]
  1. 함수·상수 이름을 바꾸지 마세요.
  2. `route_question`은 LLM을 호출하지 않습니다. 결정적 규칙으로 배분하세요.
     실제 운영에서는 모델이 배분하지만, 규칙으로 먼저 나눠 보면
     '무엇을 근거로 나누는가'가 분명해집니다.
"""

from __future__ import annotations

from typing import Any

MODEL_ID = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
REGION = "us-east-1"


def _default_llm():
    from langchain_aws import ChatBedrockConverse

    return ChatBedrockConverse(model=MODEL_ID, region_name=REGION, temperature=0)


# ══════════════════════════════════════════════════════════════════
# 기초 파트 (7점)
# ══════════════════════════════════════════════════════════════════

# TODO: 전문 Agent 이름 3개를 정하세요.
#   권장: log_agent / metric_agent / runbook_agent
AGENT_NAMES: list[str] = []

# TODO: Agent별로 쓸 도구를 나누세요.
#   같은 도구가 두 Agent에 들어가면 안 됩니다. 도메인이 겹치면 Supervisor가 헷갈립니다.
#   "혹시 몰라서" 얹지 마세요.
AGENT_TOOLS: dict[str, list[str]] = {}


def route_question(question: str) -> list[str]:
    """질문을 처리할 Agent 목록을 반환합니다. LLM을 호출하지 않습니다.

    반환 규칙:
      - 로그·에러·예외·스택·트레이스·5xx, 영문 log/exception/trace -> log_agent
      - 지표·수치·지연·레이턴시·CPU·메모리·오류율·배포, 영문 metric/latency -> metric_agent
      - 절차·대응·방법·런북·매뉴얼·담당·누구·어떻게, 영문 runbook -> runbook_agent
      - 여러 주제가 섞이면 해당하는 Agent를 모두 반환
      - 어디에도 해당하지 않으면 빈 목록 (Supervisor가 직접 답한다)

    **필요한 것만 반환하세요.** 전부 부르면 정확도는 오르지만 호출 비용이 폭증합니다.
    """
    # TODO: 구현하세요.
    raise NotImplementedError("route_question 을 구현하세요.")


def build_supervisor(llm=None):
    """Supervisor 그래프를 만들어 컴파일해 반환합니다.

    반드시 지킬 것:
      - AGENT_NAMES의 이름이 모두 그래프 노드로 존재해야 합니다.
      - supervisor 노드에서 각 Agent로 가는 경로가 있어야 합니다.
      - 종료 경로가 있어야 합니다.

    langgraph_supervisor를 써도 되고 StateGraph로 직접 만들어도 됩니다.
    """
    llm = llm or _default_llm()
    # TODO: 구현하세요.
    raise NotImplementedError("build_supervisor 를 구현하세요.")


# ══════════════════════════════════════════════════════════════════
# 심화 파트 (3점) — 못 해도 과제는 통과합니다
# ══════════════════════════════════════════════════════════════════

def judge_output(agent_name: str, output: str) -> dict:
    """워커 산출물을 내보내기 전에 걸러냅니다. LLM을 호출하지 않습니다.

    워커가 만든 것을 그대로 사용자에게 주면 근거 없는 단정과 빈 답변이 섞입니다.
    Supervisor는 게이트 역할을 해야 합니다.

    판정 규칙:
      - 내용이 비었거나 20자 미만          -> {"keep": False, "reason": "저가치"}
      - "확실합니다" "틀림없습니다" 같은
        근거 없는 단정이 있는데 수치·출처가 없음 -> {"keep": False, "reason": "근거 없는 단정"}
      - 그 외                              -> {"keep": True, "reason": ...}

    Returns:
        {"keep": bool, "reason": str} 형태의 dict
    """
    # TODO: 구현하세요.
    raise NotImplementedError("judge_output 을 구현하세요.")
