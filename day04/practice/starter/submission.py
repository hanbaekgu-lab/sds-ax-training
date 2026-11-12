"""Day 4 — 운영 지원 MCP 서버와 장애 복구.

[중요]
  1. 함수·상수 이름을 바꾸지 마세요.
  2. 도구는 예외를 밖으로 던지지 않습니다. 무엇이 잘못됐는지 설명하는 문자열을 돌려주세요.
     그 문자열은 모델이 읽고 다음 행동을 정하는 프롬프트입니다.
  3. 자격증명은 절대 반환값이나 로그에 남기지 마세요.

[전체 흐름]
  ┌ 조회 도구 3개 (MCP로 노출: TOOL_SPECS / TOOLS_IMPL)
  │   search_runbook · get_service_owner · query_recent_incidents
  │   - 정상: ops_assets.json 값을 담은 문장
  │   - 잘못된 값: 예외 대신 "쓸 수 있는 값"을 알려 주는 안내 문장
  │
  └ 자산 상태 조회 (장애 복구 층)
      get_asset_status(asset_id, fetch)
        fetch 호출 ─성공→ 응답 스키마 검증 ─통과→ "(출처: 기본 조회)" 문장 반환
           │실패                    │실패(status 누락 등)
           ▼                        ▼
        classify_failure(error) → retryable : 짧게 쉬고 재시도
                                  backoff   : 간격을 늘려 재시도
                                  fatal     : 재시도 없이 즉시 대체 경로
           │ 재시도 상한(MAX_RETRIES, 총 호출 수) 도달 또는 fatal
           ▼
        get_asset_status_backup(asset_id) → "(출처: 대체 경로, 실시간 값 아님)" 문장 반환
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Annotated, Any, Callable

from pydantic import BaseModel, ConfigDict, Field, ValidationError

DATA = json.loads(
    (Path(__file__).resolve().parent.parent / "data" / "ops_assets.json").read_text(
        encoding="utf-8"
    )
)

# 교육용 더미 자격증명입니다. 이 값이 로그나 반환값에 남으면 채점에서 감점됩니다.
BACKEND_TOKEN = "sk-internal-dummy-1234"

# 백엔드 총 호출 상한입니다. (첫 호출 포함. "재시도 횟수"가 아니라 "총 시도 횟수")
#   타임아웃이면 최대 3번까지 부르고, 그래도 안 되면 대체 경로로 넘어갑니다.
MAX_RETRIES = 3

# 이 모듈의 로거입니다. 핸들러는 붙이지 않습니다. (출력 위치는 실행하는 쪽이 정함)
#   MCP stdio 서버에서는 stdout이 프로토콜 통로라서 print 대신 로거(stderr)를 씁니다.
logger = logging.getLogger("sds.day04")


# ══════════════════════════════════════════════════════════════════
# 공통 도우미 — 입력 정규화, 자격증명 가리기
# ══════════════════════════════════════════════════════════════════

# 도구 인자로 받아들일 최대 글자 수입니다.
#   모델이 문단 전체를 인자로 넣는 경우를 막고, 안내 문장에 긴 입력이 그대로 되돌아가지 않게 합니다.
MAX_ARG_CHARS = 100

# 자격증명처럼 보이는 문자열 패턴입니다. BACKEND_TOKEN 자체는 따로 확실히 지웁니다.
#   - "Bearer xxx"   : HTTP Authorization 헤더 값
#   - "sk-xxxx"      : API 키 형태
#   - "token=xxx"    : 쿼리스트링·로그에 섞인 키=값
_SECRET_PATTERNS = [
    re.compile(r"(?i)bearer\s+\S+"),
    re.compile(r"(?i)\bsk-[A-Za-z0-9_\-]{6,}"),   # 대문자로 바뀐 'SK-...' 도 가립니다
    re.compile(r"(?i)\b(token|api[_-]?key|password|secret)\s*[=:]\s*\S+"),
]
_MASK = "[REDACTED]"


def _redact(text: Any) -> str:
    """문자열에서 자격증명을 가립니다. 반환값과 로그는 모두 이 함수를 거칩니다.

    왜 한 곳에 모으는가:
      반환 문자열은 모델 컨텍스트·트레이스·평가 기록까지 따라갑니다.
      도구마다 따로 가리면 한 군데는 꼭 빠지므로, 밖으로 나가는 모든 문자열을
      이 함수 하나로 통과시킵니다. 예외 메시지·백엔드 응답처럼 우리가 쓰지 않은
      문자열도 토큰을 품고 있을 수 있습니다.
    """
    out = str(text)
    if BACKEND_TOKEN:
        # 대소문자를 가리지 않고 지웁니다. 입력을 .upper() 로 정규화하는 도구(get_asset_status)에서
        # 토큰이 'SK-INTERNAL-...' 처럼 대문자로 바뀌어도 그대로 새지 않게 하기 위해서입니다.
        out = re.sub(re.escape(BACKEND_TOKEN), _MASK, out, flags=re.IGNORECASE)
    for pattern in _SECRET_PATTERNS:
        out = pattern.sub(_MASK, out)
    return out


def _normalize_arg(value: Any) -> str:
    """도구 인자의 앞뒤 공백을 지우고 길이를 제한합니다. None 은 빈 문자열이 됩니다.

    모델은 None, 숫자, 앞뒤 공백 섞인 값을
    넣기도 합니다. 여기서 한 번 정리해 두면 아래 조회 코드는 깨끗한 문자열만 다룹니다.
    """
    if value is None:
        return ""
    return str(value).strip()[:MAX_ARG_CHARS]


def _empty_arg_message(tool_name: str, arg_name: str, example: str) -> str:
    """인자가 비었을 때 모델이 다음 호출을 고칠 수 있도록 안내합니다."""
    return (
        f"[{tool_name}] {arg_name} 값이 비어 있습니다. "
        f"예: {example} 처럼 값을 넣어 다시 호출하세요."
    )


def _choices(values) -> str:
    """'쓸 수 있는 값' 목록을 사람이 읽기 좋은 한 줄로 만듭니다."""
    return ", ".join(sorted(values))


# ══════════════════════════════════════════════════════════════════
# 기초 파트 (7점)
# ══════════════════════════════════════════════════════════════════

# ── 인자 설명 (단일 출처) ──────────────────────────────────────────
# 이 문자열들은 두 군데에서 그대로 쓰입니다.
#   1) TOOL_SPECS 의 "args"            : 우리 쪽 명세 / 채점 대상
#   2) 함수 시그니처의 Annotated[..., Field(description=...)]
#        → fastmcp가 MCP inputSchema 의 description 으로 내보냅니다.
#        (평범한 `symptom: str` 로 두면 MCP 스키마에서 설명이 사라집니다)
# 한 상수를 양쪽에서 쓰므로, 설명을 고치면 명세와 MCP 스키마가 함께 바뀝니다.
_SYMPTOM_DESC = (
    "증상 키워드. 등록된 값: '5xx', 'oom', 'cert'. "
    "'500 에러', '메모리 부족', '인증서 만료'처럼 써도 해당 키워드로 찾아 줍니다."
)
_SERVICE_DESC = (
    "조회할 서비스 이름. 예: 'payment-api', 'auth-service', 'gateway'. "
    "사용자 질문에 나온 서비스 이름을 그대로 넣으세요."
)
_ASSET_ID_DESC = (
    "조회할 자산 ID. 'SRV-001' 형식입니다. 서비스 이름(payment-api 등)이 아니라 자산 ID를 넣으세요."
)


# ── 도구 1: 런북 검색 ──────────────────────────────────────────────

# 증상 키워드의 동의어 묶음입니다.
#   모델이나 사용자는 '5xx' 대신 '500 에러', 'oom' 대신 '메모리 부족'이라고 쓰기 쉽습니다.
#   표준 키워드로 바꿔 찾으면 "없는 키워드" 안내를 받고 다시 부르는 왕복이 줄어듭니다.
#   키는 DATA["runbooks"] 의 키와 같아야 합니다. 비교는 모두 소문자로 합니다.
_SYMPTOM_SYNONYMS: dict[str, tuple[str, ...]] = {
    "5xx": ("5xx", "500", "502", "503", "504", "서버 오류", "서버오류", "서버 에러", "서버에러",
            "internal server error", "bad gateway", "service unavailable"),
    "oom": ("oom", "out of memory", "outofmemory", "메모리", "힙", "heap", "oomkilled"),
    "cert": ("cert", "certificate", "인증서", "ssl", "tls", "x509"),
}


def _match_symptom(text: str) -> str | None:
    """입력 문장을 표준 증상 키워드로 바꿉니다. 못 찾으면 None.

    1) 표준 키워드와 정확히 같으면 그대로 씁니다.
    2) 아니면 동의어가 문장 안에 들어 있는지 봅니다. (예: '결제 서버 500 에러' → '5xx')
    """
    lowered = text.lower()
    runbooks = DATA["runbooks"]
    if lowered in runbooks:
        return lowered
    for key, synonyms in _SYMPTOM_SYNONYMS.items():
        if key in runbooks and any(s in lowered for s in synonyms):
            return key
    return None


def search_runbook(
    symptom: Annotated[str, Field(description=_SYMPTOM_DESC)],
) -> str:
    """증상 키워드로 대응 런북을 찾습니다."""
    tool = "search_runbook"
    try:
        text = _normalize_arg(symptom)
        if not text:
            return _empty_arg_message(tool, "symptom", "'5xx'")

        key = _match_symptom(text)
        if key is None:
            # 예외 대신 "무엇을 넣을 수 있는지"를 돌려줍니다. 모델은 이걸 읽고 인자를 고칩니다.
            return _redact(
                f"[{tool}] 등록되지 않은 증상 키워드예요: '{text}'. "
                f"쓸 수 있는 값: {_choices(DATA['runbooks'])}. "
                "가장 가까운 키워드로 다시 호출하세요."
            )

        note = "" if key == text.lower() else f" ('{text}' → '{key}' 키워드로 찾음)"
        return _redact(f"[{tool}] '{key}' 대응 런북{note}\n{DATA['runbooks'][key]}")
    except Exception as exc:  # noqa: BLE001 — 도구는 예외를 밖으로 내보내지 않습니다
        logger.warning(_redact(f"{tool} 내부 오류: {type(exc).__name__}: {exc}"))
        return f"[{tool}] 런북 조회 중 내부 오류가 났습니다({type(exc).__name__}). 잠시 후 다시 시도하세요."


# ── 도구 2: 담당자 조회 ────────────────────────────────────────────

def _known_services() -> set[str]:
    """데이터에 등장하는 모든 서비스 이름입니다. (담당자 표 + 인시던트 표)"""
    return set(DATA["owners"]) | set(DATA["incidents"])


def get_service_owner(
    service: Annotated[str, Field(description=_SERVICE_DESC)],
) -> str:
    """서비스의 담당팀과 온콜 담당자를 조회합니다."""
    tool = "get_service_owner"
    try:
        name = _normalize_arg(service).lower()
        if not name:
            return _empty_arg_message(tool, "service", "'payment-api'")

        owner = DATA["owners"].get(name)
        if not owner:
            return _redact(
                f"[{tool}] 등록되지 않은 서비스예요: '{name}'. "
                f"쓸 수 있는 값: {_choices(DATA['owners'])}. "
                "자산 ID(SRV-001 등)를 넣었다면 get_asset_status 를 쓰세요."
            )

        return _redact(
            f"[{tool}] {name} 담당 정보\n"
            f"- 담당팀: {owner.get('team', '미등록')}\n"
            f"- 온콜 담당자: {owner.get('oncall', '미등록')}\n"
            f"- 알림 채널: {owner.get('slack', '미등록')}"
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(_redact(f"{tool} 내부 오류: {type(exc).__name__}: {exc}"))
        return f"[{tool}] 담당자 조회 중 내부 오류가 났습니다({type(exc).__name__}). 잠시 후 다시 시도하세요."


# ── 도구 3: 최근 인시던트 ──────────────────────────────────────────

def query_recent_incidents(
    service: Annotated[str, Field(description=_SERVICE_DESC)],
) -> str:
    """서비스의 최근 인시던트 이력을 조회합니다."""
    tool = "query_recent_incidents"
    try:
        name = _normalize_arg(service).lower()
        if not name:
            return _empty_arg_message(tool, "service", "'payment-api'")

        # "없는 서비스"와 "서비스는 있지만 이력이 없음"은 다른 답입니다.
        #   gateway 처럼 등록된 서비스인데 인시던트가 없으면 0건이라고 분명히 말합니다.
        #   둘을 섞으면 모델이 멀쩡한 서비스 이름을 고쳐 부르는 헛걸음을 합니다.
        if name not in _known_services():
            return _redact(
                f"[{tool}] 등록되지 않은 서비스예요: '{name}'. "
                f"쓸 수 있는 값: {_choices(_known_services())}."
            )

        incidents = DATA["incidents"].get(name, [])
        if not incidents:
            return f"[{tool}] {name} 의 최근 인시던트 이력이 없습니다. (0건)"

        # 최신순 정렬. 날짜가 'YYYY-MM-DD' 문자열이라 문자열 비교가 곧 날짜 비교입니다.
        ordered = sorted(incidents, key=lambda i: i.get("at", ""), reverse=True)
        lines = [f"[{tool}] {name} 최근 인시던트 ({len(ordered)}건, 최신순)"]
        for i, inc in enumerate(ordered, start=1):
            lines.append(
                f"{i}. {inc.get('id', '?')} ({inc.get('at', '?')}) "
                f"{inc.get('title', '')} — 원인: {inc.get('cause', '미상')}"
            )
        return _redact("\n".join(lines))
    except Exception as exc:  # noqa: BLE001
        logger.warning(_redact(f"{tool} 내부 오류: {type(exc).__name__}: {exc}"))
        return f"[{tool}] 인시던트 조회 중 내부 오류가 났습니다({type(exc).__name__}). 잠시 후 다시 시도하세요."


# MCP로 노출할 도구 명세입니다.
#   description 에는 '무엇을 돌려주는지', '언제 쓰는지', '언제 쓰지 말아야 하는지'를 적습니다.
#   MCP로 내보내면 이 문장을 우리가 프롬프트를 손댈 수 없는 다른 팀 클라이언트·모델이 읽습니다.
#   특히 "쓰지 말 것"에 옆 도구 이름을 적어 두면, 모델이 헷갈릴 때 갈 곳을 알려 주는 효과가 있습니다.
TOOL_SPECS: list[dict] = [
    {
        "name": "search_runbook",
        "description": (
            "증상 키워드(5xx, oom, cert)로 장애 대응 런북의 조치 단계를 찾습니다. "
            "언제 쓰는가: 증상은 알지만 무엇부터 해야 할지 모를 때, 표준 대응 절차가 필요할 때. "
            "쓰지 말 것: 담당자 연락처는 get_service_owner, 과거 장애 이력은 query_recent_incidents를 쓰세요."
        ),
        "args": {"symptom": _SYMPTOM_DESC},
    },
    {
        "name": "get_service_owner",
        "description": (
            "서비스의 담당팀, 온콜 담당자, 알림 슬랙 채널을 조회합니다. "
            "언제 쓰는가: 장애를 누구에게 에스컬레이션할지, 어느 채널에 공유할지 정할 때. "
            "쓰지 말 것: 대응 절차는 search_runbook, 장애 이력은 query_recent_incidents를 쓰세요. "
            "자산 ID(SRV-001 등)를 넣는 도구가 아닙니다."
        ),
        "args": {"service": _SERVICE_DESC},
    },
    {
        "name": "query_recent_incidents",
        "description": (
            "서비스의 최근 인시던트 이력(ID, 날짜, 제목, 원인)을 최신순으로 조회합니다. "
            "언제 쓰는가: 지금 장애가 과거에 같은 원인으로 난 적이 있는지, 재발인지 확인할 때. "
            "쓰지 말 것: 현재 담당자는 get_service_owner, 대응 절차는 search_runbook을 쓰세요."
        ),
        "args": {"service": _SERVICE_DESC},
    },
]

# 이름 -> 실제 함수 매핑. TOOL_SPECS의 name과 키가 정확히 일치해야 합니다.
TOOLS_IMPL: dict[str, Any] = {
    "search_runbook": search_runbook,
    "get_service_owner": get_service_owner,
    "query_recent_incidents": query_recent_incidents,
}


# ── 자산 상태 조회 (장애 복구 층) ──────────────────────────────────

class AssetStatus(BaseModel):
    """기본 조회 경로가 돌려줘야 하는 응답 모양입니다.

    status 가 빠진 응답은 "성공"이 아니라 스키마 오류입니다.
    'field status missing' 같은 응답을 여기서 잡아 fatal 로 분류합니다.
    extra="ignore": 응답에 다른 필드(토큰 포함 가능)가 섞여 와도 우리가 쓰는 세 필드만 꺼냅니다.

    name / owner 는 부가 정보라 None(null)이어도 받아 줍니다. (출력할 때 '미등록'으로 표시)
    핵심 값인 status 가 있는데 owner 가 null 이라는 이유로 캐시 경로로 넘기면
    멀쩡한 실시간 값을 버리게 되기 때문입니다.
    """

    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    status: str = Field(min_length=1)
    owner: str | None = None


def _default_fetch(asset_id: str) -> dict:
    """기본 자산 조회 경로입니다. 실제로는 외부 시스템을 호출한다고 가정합니다."""
    asset = DATA["assets"].get(asset_id)
    if not asset:
        raise LookupError(f"asset not found: {asset_id}")
    return asset


def _validate_response(raw: Any) -> AssetStatus:
    """fetch 응답을 검증합니다. 모양이 틀리면 ValueError('schema validation failed ...').

    pydantic 의 ValidationError 메시지에는 입력값(input_value)이 통째로 찍힙니다.
    응답에 토큰이 섞여 있으면 그 메시지로 새어 나갈 수 있으므로,
    빠진 필드 이름만 담은 짧은 메시지로 바꿔 던집니다.
    """
    if not isinstance(raw, dict):
        raise ValueError(f"schema validation failed: response is {type(raw).__name__}, not object")
    try:
        return AssetStatus.model_validate(raw)
    except ValidationError as exc:
        fields = ", ".join(".".join(str(p) for p in e["loc"]) or "?" for e in exc.errors())
        raise ValueError(f"schema validation failed: field '{fields}' missing or invalid") from None


# 재시도 대기 시간(초)입니다. 교육·채점 환경이라 짧게 둡니다. (운영이라면 수백 ms~수 초)
RETRY_BASE_DELAY = 0.05
def _sleep(seconds: float) -> None:
    """재시도 사이 대기 함수입니다.

    `_sleep = time.sleep` 처럼 모듈을 불러올 때 함수를 붙잡아 두면,
    테스트가 나중에 `time.sleep` 을 가짜 함수로 바꿔 끼워도 반영되지 않습니다.
    호출할 때마다 `time.sleep` 을 새로 찾도록 감싸 두면 어느 쪽을 바꿔 끼워도 동작합니다.
    """
    time.sleep(seconds)


def _retry_delay(kind: str, attempt: int) -> float:
    """실패 종류별 다음 재시도까지의 대기 시간입니다.

    - retryable : 고정된 짧은 간격. 일시적 오류라 금방 풀릴 수 있습니다.
    - backoff   : 지수적으로 늘어나는 간격 (0.05 → 0.1 → 0.2 ...).
                  같은 속도로 두드리면 한도만 더 깎아 먹기 때문입니다.
    """
    if kind == "backoff":
        return RETRY_BASE_DELAY * (2 ** (attempt - 1))
    return RETRY_BASE_DELAY


# 실패 종류를 사람이·모델이 읽을 말로 바꾼 것입니다.
_KIND_LABEL = {
    "retryable": "일시적 오류(재시도함)",
    "backoff": "요청 한도 초과(간격을 늘려 재시도함)",
    "fatal": "재시도로 해결되지 않는 오류(즉시 대체 경로)",
}


def get_asset_status(
    asset_id: Annotated[str, Field(description=_ASSET_ID_DESC)],
    fetch: Callable[[str], dict] | None = None,
) -> str:
    """자산 상태를 조회합니다. 실패하면 재시도하고, 그래도 안 되면 대체 경로를 씁니다.

    반드시 지킬 것:
      - 어떤 경우에도 예외를 밖으로 던지지 않습니다.
      - 대체 경로로 넘어갔다면 반환 문자열에 'get_asset_status_backup' 이름을 남깁니다.
        모델이 다음에 무엇을 할지 알아야 하기 때문입니다.
      - BACKEND_TOKEN 값을 반환 문자열에 넣지 마세요.

    Args:
        asset_id: 조회할 자산 ID
        fetch: 외부 조회 함수. 채점기가 실패하는 함수를 넣습니다. None이면 기본 경로.
    """
    tool = "get_asset_status"
    try:
        fetch = fetch or _default_fetch
        asset = _normalize_arg(asset_id).upper()   # 'srv-001' 도 'SRV-001' 로 받아 줍니다
        if not asset:
            # 백엔드를 부를 필요도 없는 입력 오류입니다. 재시도·폴백 없이 바로 고칠 방법을 알려 줍니다.
            return _empty_arg_message(tool, "asset_id", "'SRV-001'")

        history: list[str] = []      # 시도별 기록. 반환 문장과 로그에 남깁니다.
        last_kind = "retryable"
        attempt = 0

        # 총 호출 수 상한 = MAX_RETRIES.
        while attempt < MAX_RETRIES:
            attempt += 1
            try:
                info = _validate_response(fetch(asset))
            except Exception as exc:  # noqa: BLE001 — 백엔드가 무엇을 던질지 우리는 모릅니다
                last_kind = classify_failure(exc)
                history.append(f"{attempt}회차 {type(exc).__name__}: {_redact(exc)} → {last_kind}")
                logger.warning(_redact(
                    f"{tool}({asset}) 시도 {attempt}/{MAX_RETRIES} 실패 "
                    f"[{last_kind}] {type(exc).__name__}: {exc}"
                ))
                # fatal: 다시 물어도 같은 답 → 즉시 대체 경로. 상한 도달도 마찬가지.
                if last_kind == "fatal" or attempt >= MAX_RETRIES:
                    break
                _sleep(_retry_delay(last_kind, attempt))
                continue

            # ── 기본 경로 성공 ──
            # 재시도 끝에 살아난 값이면 그 값을 그대로 씁니다. (폴백 문구로 덮어쓰지 않음)
            route = "기본 조회" if attempt == 1 else f"기본 조회, {attempt - 1}회 재시도 후 복구"
            if attempt > 1:
                logger.info(_redact(f"{tool}({asset}) {attempt}회차에 복구"))
            return _redact(
                f"[{tool}] {asset} 자산 상태 (출처: {route})\n"
                f"- 이름: {info.name or '미등록'}\n"
                f"- 상태: {info.status}\n"
                f"- 담당: {info.owner or '미등록'}"
            )

        # ── 기본 경로 실패 → 대체 경로 ──
        # 어느 경로에서 나온 답인지 반환값에 남깁니다. 캐시 값을 현재 상태로 착각하지 않게,
        # 그리고 사후에 폴백 비율을 셀 수 있게 하기 위해서입니다.
        backup = get_asset_status_backup(asset)
        # 끝맺는 안내는 실패 종류에 따라 다릅니다. 이 문장은 모델이 다음 행동을 고르는 프롬프트입니다.
        #   fatal 에 "잠시 뒤 다시 호출"을 권하면 모델이 같은 실패를 또 부르는 헛걸음을 합니다.
        if last_kind == "fatal":
            next_step = (
                "기본 조회는 다시 불러도 같은 결과라 재호출하지 마세요. "
                "자산 ID나 입력값을 확인하세요."
            )
        else:
            next_step = "확정이 필요하면 잠시 뒤 get_asset_status 를 다시 호출하세요."
        return _redact(
            f"[{tool}] {asset} 기본 조회 실패 — {_KIND_LABEL.get(last_kind, last_kind)}, "
            f"백엔드 호출 {attempt}회.\n"
            f"시도 기록: {' / '.join(history)}\n"
            f"대체 경로 get_asset_status_backup 결과로 답합니다. "
            f"(대체 경로 값은 캐시라 현재 상태와 다를 수 있음. {next_step})\n"
            f"{backup}"
        )
    except Exception as exc:  # noqa: BLE001 — 마지막 안전망
        logger.error(_redact(f"{tool} 내부 오류: {type(exc).__name__}: {exc}"))
        return (
            f"[{tool}] 자산 조회 중 내부 오류가 났습니다({type(exc).__name__}). "
            "대체 경로 get_asset_status_backup 을 직접 호출해 보세요."
        )


# 대체 경로가 쓰는 캐시입니다. 모듈을 불러올 때 한 번 찍어 둔 사본이라고 가정합니다.
#   기본 경로(DATA["assets"])와 다른 객체로 두어, 기본 경로가 망가져도 영향을 받지 않게 합니다.
_BACKUP_CACHE: dict[str, dict] = {k: dict(v) for k, v in DATA["assets"].items()}


def get_asset_status_backup(
    asset_id: Annotated[str, Field(description=_ASSET_ID_DESC)],
) -> str:
    """대체 조회 경로입니다. 캐시된 값이나 축약 정보를 돌려준다고 가정합니다."""
    tool = "get_asset_status_backup"
    try:
        asset = _normalize_arg(asset_id).upper()
        if not asset:
            return _empty_arg_message(tool, "asset_id", "'SRV-001'")

        cached = _BACKUP_CACHE.get(asset)
        if not cached:
            return _redact(
                f"[{tool}] 캐시에도 없는 자산 ID예요: '{asset}'. "
                f"등록된 자산: {_choices(_BACKUP_CACHE)}. ID를 확인해 다시 호출하세요."
            )

        return _redact(
            f"[{tool}] {asset} 캐시 상태 (출처: 대체 경로, 실시간 값 아님)\n"
            f"- 이름: {cached.get('name', '미등록')}\n"
            f"- 상태(캐시): {cached.get('status', '알 수 없음')}\n"
            f"- 담당: {cached.get('owner', '미등록')}"
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(_redact(f"{tool} 내부 오류: {type(exc).__name__}: {exc}"))
        return f"[{tool}] 대체 경로 조회도 실패했습니다({type(exc).__name__}). 담당팀에 직접 확인하세요."


def _get_asset_status_tool(
    asset_id: Annotated[str, Field(description=_ASSET_ID_DESC)],
) -> str:
    """MCP 노출용 래퍼입니다. fetch 인자를 숨깁니다.

    get_asset_status 의 fetch(Callable)는 JSON 스키마로 표현할 수 없어
    그대로 등록하면 MCP 도구 등록이 깨집니다. 외부에는 asset_id 만 보여 줍니다.
    """
    return get_asset_status(asset_id)


# 자산 조회 도구 명세입니다. TOOL_SPECS(채점 대상, 필수 3개)와 분리해 mcp_server.py 가 함께 등록합니다.
#   get_asset_status 가 반환값에 'get_asset_status_backup' 이름을 남기는 이유는
#   모델이 그 이름으로 다음 호출을 할 수 있게 하려는 것입니다. 그래서 backup 도 도구로 노출합니다.
ASSET_TOOL_SPECS: list[dict] = [
    {
        "name": "get_asset_status",
        "description": (
            "자산 ID(SRV-001 등)로 서버 자산의 현재 상태(running, degraded 등)와 담당팀을 조회합니다. "
            "백엔드가 실패하면 자동으로 재시도하고, 그래도 안 되면 캐시 경로 결과를 '출처'와 함께 돌려줍니다. "
            "쓰지 말 것: 서비스 이름으로 담당자를 찾을 때는 get_service_owner 를 쓰세요."
        ),
        "args": {"asset_id": _ASSET_ID_DESC},
    },
    {
        "name": "get_asset_status_backup",
        "description": (
            "자산 상태의 캐시 값을 조회하는 대체 경로입니다. 실시간 값이 아닙니다. "
            "언제 쓰는가: get_asset_status 가 기본 조회 실패를 알렸고 캐시 값이라도 필요할 때. "
            "쓰지 말 것: 평소 상태 조회에는 get_asset_status 를 먼저 쓰세요."
        ),
        "args": {"asset_id": _ASSET_ID_DESC},
    },
]

ASSET_TOOLS_IMPL: dict[str, Any] = {
    "get_asset_status": _get_asset_status_tool,
    "get_asset_status_backup": get_asset_status_backup,
}


# ══════════════════════════════════════════════════════════════════
# 심화 파트 (3점) — 못 해도 과제는 통과합니다
# ══════════════════════════════════════════════════════════════════

# 판정 기준은 하나: "다시 물었을 때 답이 달라질 수 있는가?"
# 메시지 단서는 모두 소문자로 비교합니다.
_BACKOFF_MARKERS = ("429", "too many requests", "rate limit", "ratelimit", "rate-limit",
                    "throttl", "quota exceeded")
_FATAL_MARKERS = ("schema", "validation", "401", "403", "404", "unauthorized", "forbidden",
                  "authentication", "invalid token", "permission denied", "not found", "no such")
_RETRYABLE_MARKERS = ("timeout", "timed out", "connection", "reset", "refused", "temporar",
                      "unavailable", "502", "503", "504", "try again")


def _has_marker(text: str, markers: tuple[str, ...]) -> bool:
    """메시지에 단서가 들어 있는지 봅니다.

    '429', '404' 같은 숫자 단서는 그냥 부분 문자열로 찾으면
    'asset not found: SRV-4291' 처럼 자산 ID 안의 숫자에도 걸립니다.
    (없는 자원인데 backoff 로 잘못 분류되어 쓸데없이 재시도함)
    그래서 숫자 단서는 앞뒤에 숫자·영문·하이픈이 붙지 않은 독립된 숫자일 때만 인정합니다.
      '429 Too Many Requests', 'status=429', '(404)' → 인정
      'SRV-4291', 'SRV-429', 'req4290'               → 무시
    """
    for m in markers:
        if m.isdigit():
            if re.search(rf"(?<![\w-]){m}(?![\w-])", text):
                return True
        elif m in text:
            return True
    return False

# 예외 타입만으로 판정되는 경우입니다.
#   ValueError(스키마·값 오류, pydantic ValidationError 포함), LookupError(KeyError·IndexError 포함),
#   PermissionError(인증·권한), TypeError(응답 모양 오류)는 다시 불러도 같습니다.
_FATAL_TYPES: tuple[type[BaseException], ...] = (ValueError, LookupError, PermissionError, TypeError)
_RETRYABLE_TYPES: tuple[type[BaseException], ...] = (TimeoutError, ConnectionError)


def classify_failure(error: BaseException | str) -> str:
    """실패를 세 종류로 분류합니다. LLM을 호출하지 않습니다.

    반환값은 정확히 다음 셋 중 하나여야 합니다.

      "retryable"  타임아웃, 일시적 연결 오류      -> 짧게 재시도
      "backoff"    요청 한도 초과 (rate limit)     -> 간격을 늘려 재시도
      "fatal"      스키마 오류, 인증 실패, 없는 자원 -> 재시도하지 말고 즉시 대체 경로

    판단 근거는 예외 타입이나 메시지 문자열 어느 쪽을 써도 됩니다.

    판정 순서 (위에서 먼저 걸리는 것으로 정합니다):
      1. 메시지에 한도 초과 단서 → backoff
         (RuntimeError("429 ...")처럼 한도 초과는 타입이 제각각이라 메시지를 먼저 봅니다)
      2. 타입이 fatal 계열 → fatal
      3. 타입이 타임아웃·연결 오류 → retryable
         (타입을 메시지보다 먼저 보는 이유: "auth-service connection timed out" 같은
          메시지가 'auth' 단어 때문에 fatal 로 잘못 분류되는 일을 막습니다)
      4. 메시지에 fatal 단서 → fatal
      5. 메시지에 일시적 오류 단서 → retryable
      6. 그 외 처음 보는 오류 → retryable
         (답이 달라질지 모르는 오류입니다. MAX_RETRIES 상한이 있으니 몇 번 더 물어볼 여유는 있습니다)
    """
    if isinstance(error, BaseException):
        text = f"{type(error).__name__}: {error}".lower()
    else:
        text = str(error).lower()

    if _has_marker(text, _BACKOFF_MARKERS):
        return "backoff"
    if isinstance(error, BaseException):
        if isinstance(error, _FATAL_TYPES):
            return "fatal"
        if isinstance(error, _RETRYABLE_TYPES):
            return "retryable"
    if _has_marker(text, _FATAL_MARKERS):
        return "fatal"
    if _has_marker(text, _RETRYABLE_MARKERS):
        return "retryable"
    return "retryable"


if __name__ == "__main__":
    # 실호출 없이 도구와 복구 경로를 눈으로 확인하는 진입점입니다. (채점기는 실행하지 않습니다)
    #   python day04/practice/starter/submission.py
    import sys

    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(message)s")

    class _Flaky:
        """지정한 예외를 n번 던진 뒤 성공하는 가짜 백엔드입니다."""

        def __init__(self, exc: BaseException, fail_times: int):
            self.exc, self.fail_times, self.count = exc, fail_times, 0

        def __call__(self, asset_id: str) -> dict:
            self.count += 1
            if self.count <= self.fail_times:
                raise self.exc
            return DATA["assets"][asset_id]

    def show(title: str, out: str) -> None:
        print(f"\n── {title}\n{out}")

    show("런북: 500 에러", search_runbook("결제 서버 500 에러"))
    show("런북: 없는 키워드", search_runbook("디스크 풀"))
    show("담당자: payment-api", get_service_owner("payment-api"))
    show("인시던트: gateway(0건)", query_recent_incidents("gateway"))

    for title, exc, n in [
        ("타임아웃 1회 후 복구", TimeoutError("timed out"), 1),
        ("타임아웃 계속", TimeoutError("timed out"), 99),
        ("한도 초과 계속", RuntimeError("429 Too Many Requests"), 99),
        ("스키마 오류 (토큰 섞인 메시지)",
         ValueError(f"schema validation failed: field 'status' missing (auth={BACKEND_TOKEN})"), 99),
    ]:
        backend = _Flaky(exc, n)
        out = get_asset_status("SRV-002", fetch=backend)
        show(f"{title} — 백엔드 호출 {backend.count}회", out)
        assert BACKEND_TOKEN not in out

    show("status 누락 응답", get_asset_status("SRV-002", fetch=lambda _id: {"name": "x"}))
    show("없는 자산", get_asset_status("SRV-999"))
    show("빈 자산 ID", get_asset_status(""))
