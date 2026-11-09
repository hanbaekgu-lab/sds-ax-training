"""Day 1 — 운영 알람 트리아지 체인.

알람 하나를 넣으면 구조화된 분류 결과와 담당팀 안내 초안을 동시에 만듭니다.

[중요] 이 파일의 규칙
  1. 함수 이름과 인자를 바꾸지 마세요. 채점기가 이 이름으로 찾습니다.
  2. 모델은 반드시 함수 **안에서** 만듭니다. 모듈 최상단에서 만들면
     채점기가 가짜 모델을 넣을 수 없어 채점이 실패합니다.
  3. `llm` 인자가 들어오면 그것을 쓰고, None이면 직접 만듭니다.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# 과정 전체에서 고정으로 쓰는 값입니다. 바꾸지 마세요.
MODEL_ID = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
REGION = "us-east-1"


def _default_llm():
    """기본 모델을 만듭니다. 채점기는 이 함수를 부르지 않습니다.

    import를 함수 안에 둔 이유: 모듈을 불러오는 것만으로 AWS 자격증명을
    요구하지 않게 하기 위해서입니다.
    """
    from langchain_aws import ChatBedrockConverse

    return ChatBedrockConverse(model=MODEL_ID, region_name=REGION, temperature=0)


def get_text(message: Any) -> str:
    """ChatBedrockConverse는 content를 블록 리스트로 주기도 하므로 텍스트만 모아 반환합니다."""
    content = message.content if hasattr(message, "content") else message
    if isinstance(content, list):
        return "".join(
            block.get("text", "") for block in content if isinstance(block, dict)
        )
    return str(content)


# ══════════════════════════════════════════════════════════════════
# 기초 파트 (7점)
# ══════════════════════════════════════════════════════════════════

# TODO: 분류 결과 스키마를 정의합니다.
#   - 필드 4개 이상
#   - 모든 필드에 description (모델이 보는 것은 이 설명문뿐입니다)
#   - severity는 Literal 또는 Enum으로 값을 제한합니다
#
# 아래는 최소 형태의 예시입니다. 본인 업무에 맞게 필드를 바꾸고 늘리세요.
class TriageResult(BaseModel):
    """운영 알람 분류 결과입니다."""

    severity: Literal["P1", "P2", "P3", "P4"] = Field(
        ...,
        description="TODO: 어떤 기준으로 P1~P4를 나누는지 여기에 적으세요. "
        "이 설명이 곧 모델에게 주는 판단 기준입니다.",
    )
    # TODO: 필드를 3개 이상 더 추가하세요.
    #   예) 영향 서비스, 증상 카테고리, 첫 확인 항목, 담당팀 ...


TRIAGE_SCHEMA = TriageResult


def build_triage_chain(llm=None):
    """알람 dict를 받아 TRIAGE_SCHEMA 형태의 dict를 반환하는 체인을 만듭니다.

    반드시 지킬 것:
      - 프롬프트에 파서의 format_instructions를 실제로 주입해야 합니다.
        스키마만 정의하고 프롬프트에 넣지 않으면 모델은 형식을 모릅니다.
    """
    llm = llm or _default_llm()

    # TODO: JsonOutputParser + PromptTemplate + llm 을 LCEL로 조립하세요.
    #   parser = JsonOutputParser(pydantic_object=TRIAGE_SCHEMA)
    #   prompt = PromptTemplate(
    #       template="...{alert}...\n{format_instructions}\n",
    #       input_variables=["alert"],
    #       partial_variables={"format_instructions": parser.get_format_instructions()},
    #   )
    #   return {"alert": lambda a: str(a)} | prompt | llm | parser
    raise NotImplementedError("build_triage_chain 을 구현하세요.")


def build_notice_chain(llm=None):
    """알람 dict를 받아 담당팀 안내 초안 문자열을 반환하는 체인을 만듭니다.

    반드시 지킬 것:
      - system 메시지로 역할을 지정합니다 (30자 이상).
      - 기본 예시 문구를 그대로 두지 말고 본인 조직의 맥락으로 바꾸세요.
    """
    llm = llm or _default_llm()

    # TODO: ChatPromptTemplate에 system 메시지를 넣고 llm, StrOutputParser와 연결하세요.
    raise NotImplementedError("build_notice_chain 을 구현하세요.")


def build_full_chain(llm=None):
    """두 체인을 병렬로 묶어 {"triage": dict, "notice": str} 를 반환합니다.

    심화 파트를 구현했다면, triage 결과는 apply_severity_rules를 거친 값이어야 합니다.
    """
    llm = llm or _default_llm()

    # TODO: RunnableParallel로 두 체인을 묶으세요.
    raise NotImplementedError("build_full_chain 을 구현하세요.")


# ══════════════════════════════════════════════════════════════════
# 심화 파트 (3점) — 못 해도 과제는 통과합니다
# ══════════════════════════════════════════════════════════════════

# TODO: 장애 시 최우선으로 봐야 하는 서비스를 3개 이상 넣으세요.
CRITICAL_SERVICES: set[str] = set()

# severity 등급의 높낮이 비교용입니다. 숫자가 작을수록 급합니다.
SEVERITY_ORDER = {"P1": 1, "P2": 2, "P3": 3, "P4": 4}


def apply_severity_rules(triage: dict, alert: dict) -> dict:
    """모델이 매긴 severity 위에 결정적 규칙을 얹습니다.

    이 함수는 LLM을 호출하지 않습니다. 같은 입력에 항상 같은 출력을 내야 합니다.

    규칙:
      - alert["service"]가 CRITICAL_SERVICES에 있으면 최소 P2
      - alert["message"]에 "5xx" 또는 "outage"가 있으면 최소 P1
      - 둘 다면 더 높은 쪽(숫자가 작은 쪽)을 적용
      - 아무것도 해당 없으면 모델 판단을 그대로 둠
      - 규칙이 적용됐으면 그 사실을 결과에 남길 것 (예: rule_applied 키)

    Returns:
        규칙이 반영된 새 dict. 원본을 그대로 바꾸지 말고 복사해서 쓰는 편이 안전합니다.
    """
    # TODO: 구현하세요.
    raise NotImplementedError("apply_severity_rules 를 구현하세요.")
