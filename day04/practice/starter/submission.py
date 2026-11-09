"""Day 4 — 운영 지원 MCP 서버와 장애 복구.

[중요]
  1. 함수·상수 이름을 바꾸지 마세요.
  2. 도구는 예외를 밖으로 던지지 않습니다. 무엇이 잘못됐는지 설명하는 문자열을 돌려주세요.
     그 문자열은 모델이 읽고 다음 행동을 정하는 프롬프트입니다.
  3. 자격증명은 절대 반환값이나 로그에 남기지 마세요.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

DATA = json.loads(
    (Path(__file__).resolve().parent.parent / "data" / "ops_assets.json").read_text(
        encoding="utf-8"
    )
)

# 교육용 더미 자격증명입니다. 이 값이 로그나 반환값에 남으면 채점에서 감점됩니다.
BACKEND_TOKEN = "sk-internal-dummy-1234"

MAX_RETRIES = 3


# ══════════════════════════════════════════════════════════════════
# 기초 파트 (7점)
# ══════════════════════════════════════════════════════════════════

def search_runbook(symptom: str) -> str:
    """증상 키워드로 대응 런북을 찾습니다."""
    # TODO: DATA["runbooks"]에서 찾아 문자열로 반환하세요.
    #   없는 키워드면 예외가 아니라 "어떤 키워드가 있는지" 알려 주는 문자열을 반환합니다.
    raise NotImplementedError("search_runbook 을 구현하세요.")


def get_service_owner(service: str) -> str:
    """서비스의 담당팀과 온콜 담당자를 조회합니다."""
    # TODO: DATA["owners"] 에서 조회하세요.
    raise NotImplementedError("get_service_owner 를 구현하세요.")


def query_recent_incidents(service: str) -> str:
    """서비스의 최근 인시던트 이력을 조회합니다."""
    # TODO: DATA["incidents"] 에서 조회하세요.
    raise NotImplementedError("query_recent_incidents 를 구현하세요.")


# TODO: MCP로 노출할 도구 명세를 채우세요.
#   각 항목: {"name": ..., "description": 30자 이상, "args": {인자명: 설명}}
#   description에는 '언제 쓰는지'와 '언제 쓰지 말아야 하는지'를 적으세요.
TOOL_SPECS: list[dict] = []

# TODO: 이름 -> 실제 함수 매핑. TOOL_SPECS의 name과 키가 정확히 일치해야 합니다.
TOOLS_IMPL: dict[str, Any] = {}


def _default_fetch(asset_id: str) -> dict:
    """기본 자산 조회 경로입니다. 실제로는 외부 시스템을 호출한다고 가정합니다."""
    asset = DATA["assets"].get(asset_id)
    if not asset:
        raise LookupError(f"asset not found: {asset_id}")
    return asset


def get_asset_status(asset_id: str, fetch: Callable[[str], dict] | None = None) -> str:
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
    fetch = fetch or _default_fetch
    # TODO: 구현하세요.
    #   1) fetch를 호출한다
    #   2) 실패하면 재시도한다 (심화를 했다면 classify_failure로 전략을 나눈다)
    #   3) 끝내 실패하면 get_asset_status_backup 으로 넘어간다
    raise NotImplementedError("get_asset_status 를 구현하세요.")


def get_asset_status_backup(asset_id: str) -> str:
    """대체 조회 경로입니다. 캐시된 값이나 축약 정보를 돌려준다고 가정합니다."""
    # TODO: 구현하세요. 실패해도 예외를 던지지 않습니다.
    raise NotImplementedError("get_asset_status_backup 을 구현하세요.")


# ══════════════════════════════════════════════════════════════════
# 심화 파트 (3점) — 못 해도 과제는 통과합니다
# ══════════════════════════════════════════════════════════════════

def classify_failure(error: BaseException | str) -> str:
    """실패를 세 종류로 분류합니다. LLM을 호출하지 않습니다.

    반환값은 정확히 다음 셋 중 하나여야 합니다.

      "retryable"  타임아웃, 일시적 연결 오류      -> 짧게 재시도
      "backoff"    요청 한도 초과 (rate limit)     -> 간격을 늘려 재시도
      "fatal"      스키마 오류, 인증 실패, 없는 자원 -> 재시도하지 말고 즉시 대체 경로

    판단 근거는 예외 타입이나 메시지 문자열 어느 쪽을 써도 됩니다.
    """
    # TODO: 구현하세요.
    raise NotImplementedError("classify_failure 를 구현하세요.")
