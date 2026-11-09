"""Day 1 — 운영 알람 트리아지 체인.

알람 하나를 넣으면 구조화된 분류 결과와 담당팀 안내 초안을 동시에 만듭니다.

[중요] 이 파일의 규칙
  1. 함수 이름과 인자를 바꾸지 마세요. 채점기가 이 이름으로 찾습니다.
  2. 모델은 반드시 함수 **안에서** 만듭니다. 모듈 최상단에서 만들면
     채점기가 가짜 모델을 넣을 수 없어 채점이 실패합니다.
  3. `llm` 인자가 들어오면 그것을 쓰고, None이면 직접 만듭니다.

[구성] 실습(inquiry_chain.py / my_inquiry_chain.py)과 같은 뼈대입니다.
  - 부품 A: 분류 체인   PromptTemplate | llm | JsonOutputParser   (기계가 읽을 값)
  - 부품 B: 안내 체인   ChatPromptTemplate(system) | llm | StrOutputParser  (사람이 읽을 문장)
  - 조립:   RunnableParallel(triage=A, notice=B)
  - 심화:   A의 결과에 복구 경로와 결정적 규칙(apply_severity_rules)을 얹습니다.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from langchain_core.output_parsers import JsonOutputParser, StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, PromptTemplate
from langchain_core.runnables import RunnableLambda, RunnableParallel, RunnablePassthrough
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


# 프롬프트에 넣을 알람 본문의 최대 길이입니다.
# 4000자짜리 알람이 들어와도 토큰이 폭주하지 않도록 잘라서 넣습니다.
MAX_ALERT_CHARS = 2000


def _alert_to_text(alert: Any) -> str:
    """알람 dict를 프롬프트에 넣을 JSON 문자열로 바꿉니다.

    - 실습 코드는 {"inquiry": "문자열"}을 직접 넣었지만, 여기서는 체인 입력이
      알람 dict 그 자체이므로 첫 단계에서 문자열로 바꿔 {alert} 자리에 넣습니다.
    - json.dumps로 바꾸면 메시지 안의 중괄호({"nested": true})가 템플릿 변수로
      해석되지 않고 '값'으로만 들어가므로 안전합니다.
    - ensure_ascii=False: 한글·이모지를 \\uXXXX로 깨지 않고 그대로 보여 줍니다.
    - default=str: datetime 등 JSON으로 못 바꾸는 값이 섞여도 예외 없이 문자열로 처리합니다.
    """
    if not isinstance(alert, dict):
        alert = {"raw": alert}
    text = json.dumps(alert, ensure_ascii=False, default=str)
    if len(text) > MAX_ALERT_CHARS:
        text = text[:MAX_ALERT_CHARS] + " ...(이하 생략)"
    return text


# ══════════════════════════════════════════════════════════════════
# 기초 파트 (7점)
# ══════════════════════════════════════════════════════════════════

# 분류 결과 스키마입니다.
#   - 모델이 보는 것은 필드 이름과 description뿐이므로, 판단 기준을 description에 적습니다.
#   - 실습(my_inquiry_chain.py)에서는 severity를 str로 열어 두었지만,
#     여기서는 Literal로 닫아 "높음"·"critical"·"P1"이 한 컬럼에 섞이지 않게 합니다.
class TriageResult(BaseModel):
    """운영 알람 분류 결과입니다. 티켓 시스템에 그대로 적재합니다."""

    severity: Literal["P1", "P2", "P3", "P4"] = Field(
        ...,
        description=(
            "장애 등급. 넷 중 하나만 쓴다. "
            "P1=핵심 서비스(결제·인증·주문) 중단 또는 5xx 급증처럼 고객 영향이 커지는 중, 즉시 호출. "
            "P2=일부 기능 장애 또는 핵심 서비스 성능 저하, 30분 내 대응. "
            "P3=고객 영향 없는 경고(CPU·디스크 사용률 상승 등), 업무시간 내 대응. "
            "P4=정보성 알람, 기록만 남긴다."
        ),
    )
    service: str = Field(
        ...,
        description="알람이 발생한 서비스 이름. 알람에 없으면 'unknown'으로 쓴다",
    )
    category: Literal["availability", "latency", "resource", "security", "etc"] = Field(
        ...,
        description=(
            "증상 분류. availability=오류·중단, latency=응답 지연, "
            "resource=CPU·메모리·디스크, security=보안 이벤트, etc=그 외"
        ),
    )
    owner_team: str = Field(
        ...,
        description="호출할 담당팀 이름. 판단이 어려우면 '운영센터 당직'으로 쓴다",
    )
    first_check: str = Field(
        ...,
        description="당직자가 가장 먼저 열어 볼 항목 한 가지. 예: 최근 배포 이력, 서비스 대시보드",
    )


TRIAGE_SCHEMA = TriageResult


def build_triage_chain(llm=None):
    """알람 dict를 받아 TRIAGE_SCHEMA 형태의 dict를 반환하는 체인을 만듭니다.

    반드시 지킬 것:
      - 프롬프트에 파서의 format_instructions를 실제로 주입해야 합니다.
        스키마만 정의하고 프롬프트에 넣지 않으면 모델은 형식을 모릅니다.
    """
    llm = llm or _default_llm()

    # 부품 A: 파서가 곧 '계약서'입니다. 이 파서의 형식 지침을 프롬프트에 넣어 모델에게 보여 줍니다.
    triage_parser = JsonOutputParser(pydantic_object=TRIAGE_SCHEMA)
    triage_prompt = PromptTemplate(
        template=(
            "다음 모니터링 알람을 장애 티켓 양식으로 분류해. "
            "JSON 앞뒤에 설명 문장을 붙이지 마.\n\n"
            "알람: {alert}\n\n"
            "{format_instructions}"
        ),
        input_variables=["alert"],
        # partial_variables: 사용자 입력이 아닌 값을 미리 채워 두는 자리입니다.
        # 여기 들어간 값은 템플릿으로 다시 해석되지 않아 형식 지침 안의 중괄호도 안전합니다.
        partial_variables={"format_instructions": triage_parser.get_format_instructions()},
    )

    # 입력은 알람 dict 그대로 받고, 첫 단계에서 {"alert": 문자열}로 바꿉니다.
    return {"alert": RunnableLambda(_alert_to_text)} | triage_prompt | llm | triage_parser


def build_notice_chain(llm=None):
    """알람 dict를 받아 담당팀 안내 초안 문자열을 반환하는 체인을 만듭니다.

    반드시 지킬 것:
      - system 메시지로 역할을 지정합니다 (30자 이상).
      - 기본 예시 문구를 그대로 두지 말고 본인 조직의 맥락으로 바꾸세요.
    """
    llm = llm or _default_llm()

    # 부품 B: system 메시지로 역할·형식·말투를 정합니다.
    # 주의: system 문구에 중괄호를 쓰면 템플릿 변수로 해석되므로 쓰지 않습니다.
    notice_prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "너는 삼성SDS 운영센터의 야간 당직 담당자야. "
                "모니터링 알람을 받아 담당팀 채널에 그대로 붙여넣을 안내 초안을 써. "
                "첫 줄은 '[긴급도 추정] 서비스명 - 한 줄 요약'으로 쓰고, "
                "이어서 영향, 현재 상황, 요청 사항을 각각 한 문장으로 써. "
                "정중한 존댓말로 쓰고, 알람에 없는 사실은 추측하지 말고 '확인 필요'로 표시해. "
                "전체 다섯 줄을 넘기지 마.",
            ),
            ("human", "다음 알람에 대한 담당팀 안내 초안을 작성해 주세요.\n\n알람: {alert}"),
        ]
    )

    return {"alert": RunnableLambda(_alert_to_text)} | notice_prompt | llm | StrOutputParser()


# 결과 dict가 항상 같은 키 구조를 갖도록 채워 넣을 기본값입니다.
# 복구 경로에서는 severity를 가장 보수적인 P1로 둡니다 (놓치는 것보다 깨우는 편이 낫습니다).
TRIAGE_DEFAULTS: dict[str, Any] = {
    "severity": "P1",
    "service": "unknown",
    "category": "etc",
    "owner_team": "운영센터 당직",
    "first_check": "알람 원문과 서비스 대시보드 직접 확인",
}


def _ensure_dict(result: Any) -> dict:
    """파서 결과가 dict인지 확인하고 빠진 키를 채웁니다.

    JsonOutputParser는 모델이 "42"나 "[1, 2]"를 뱉으면 int·list를 돌려줄 수 있습니다.
    dict가 아니면 예외를 던져 with_fallbacks의 복구 경로로 넘깁니다.
    """
    if not isinstance(result, dict):
        raise ValueError(f"분류 결과가 dict가 아닙니다: {type(result).__name__}")
    return {**TRIAGE_DEFAULTS, **result, "parse_failed": False}


def _fallback_triage(alert: Any) -> dict:
    """모델 출력이 깨졌을 때 쓰는 복구값입니다.

    parse_failed=True 표시를 남겨, 다음 날 "이 값은 모델이 아니라 복구 경로가 만든 것"을
    구분하고 복구 건수를 셀 수 있게 합니다.
    """
    service = alert.get("service") if isinstance(alert, dict) else None
    return {**TRIAGE_DEFAULTS, "service": service or "unknown", "parse_failed": True}


def build_full_chain(llm=None):
    """두 체인을 병렬로 묶어 {"triage": dict, "notice": str} 를 반환합니다.

    심화 파트를 구현했다면, triage 결과는 apply_severity_rules를 거친 값이어야 합니다.
    """
    llm = llm or _default_llm()

    # 1) 분류 체인 + dict 보장. 어느 단계에서든 예외가 나면 복구값으로 대체합니다.
    #    with_fallbacks의 대체 경로는 원래 입력(알람 dict)을 그대로 받습니다.
    safe_triage = (build_triage_chain(llm) | RunnableLambda(_ensure_dict)).with_fallbacks(
        [RunnableLambda(_fallback_triage)]
    )

    # 2) 규칙 적용에는 분류 결과와 원본 알람이 둘 다 필요하므로 함께 넘깁니다.
    triage_branch = RunnableParallel(
        triage=safe_triage, alert=RunnablePassthrough()
    ) | RunnableLambda(lambda x: apply_severity_rules(x["triage"], x["alert"]))

    # 3) 조립: 기계용(triage)과 사람용(notice) 두 갈래를 병렬로 실행합니다.
    #    모델 객체는 하나만 만들어 두 갈래에 같이 넘깁니다.
    return RunnableParallel(triage=triage_branch, notice=build_notice_chain(llm))


# ══════════════════════════════════════════════════════════════════
# 심화 파트 (3점) — 못 해도 과제는 통과합니다
# ══════════════════════════════════════════════════════════════════

# 장애 시 새벽에도 사람을 깨우는 서비스 목록입니다. 이 목록이 곧 우선순위 정책입니다.
CRITICAL_SERVICES: set[str] = {"payment-api", "auth-api", "order-api"}

# 메시지에 이 단어가 있으면 최소 P1입니다. 대소문자는 구분하지 않습니다.
ERROR_KEYWORDS: tuple[str, ...] = ("5xx", "outage")

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
    # 원본을 건드리지 않도록 복사본에서 작업합니다.
    result = dict(triage) if isinstance(triage, dict) else {}
    alert = alert if isinstance(alert, dict) else {}

    applied: list[str] = []
    model_severity = result.get("severity")

    # 모델이 엉뚱한 등급("critical" 등)을 줬거나 비어 있으면 가장 보수적인 P1로 시작합니다.
    current = model_severity if model_severity in SEVERITY_ORDER else "P1"
    if model_severity not in SEVERITY_ORDER:
        applied.append("invalid_severity_default")

    # service·message가 없거나 숫자여도 문자열로 바꿔서 검사합니다.
    service = str(alert.get("service") or "")
    message = str(alert.get("message") or "").lower()

    # (규칙 이름, 최소 등급) 후보를 모읍니다.
    floors: list[tuple[str, str]] = []
    if service in CRITICAL_SERVICES:
        floors.append(("critical_service", "P2"))
    if any(keyword in message for keyword in ERROR_KEYWORDS):
        floors.append(("error_keyword", "P1"))

    # 현재 등급보다 높을 때만(숫자가 작을 때만) 올립니다. 이미 더 높으면 유지합니다.
    for rule_name, floor in floors:
        if SEVERITY_ORDER[floor] < SEVERITY_ORDER[current]:
            current = floor
            applied.append(rule_name)

    result["severity"] = current
    result["model_severity"] = model_severity  # 모델이 원래 매긴 값 (추적용)
    result["rule_applied"] = applied           # 실제로 등급을 올린 규칙 목록, 없으면 []
    return result
