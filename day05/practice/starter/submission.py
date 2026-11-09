"""Day 5 — 승인 게이트와 가드레일.

[중요]
  1. 함수·상수 이름을 바꾸지 마세요.
  2. 이 파일의 함수는 LLM을 호출하지 않아도 동작해야 합니다.
     규칙 기반으로 먼저 막고, 필요하면 모델 판별을 덧붙이세요.
  3. 채점은 교안에 공개된 20문항이 아니라 **비공개 문항**으로 합니다.
     공개 문항만 통과하는 하드코딩은 채점에서 걸립니다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def load_public_sets() -> tuple[list[str], list[str]]:
    """연습용 공개 세트를 읽습니다. 채점에는 쓰이지 않습니다."""
    attack = json.loads((DATA_DIR / "attack_set.json").read_text(encoding="utf-8"))
    normal = json.loads((DATA_DIR / "normal_set.json").read_text(encoding="utf-8"))
    return attack, normal


# ══════════════════════════════════════════════════════════════════
# 기초 파트 (7점)
# ══════════════════════════════════════════════════════════════════

def input_guard(text: str) -> tuple[bool, str]:
    """입력을 검사해 차단 여부를 정합니다.

    Returns:
        (차단할지 여부, 사유 문자열)

    주의: 규칙을 늘릴수록 정상 요청도 막힙니다.
    normal_set에는 "이전", "무시", "새로운 역할", "관리자" 같은 함정 단어가
    일부러 들어 있습니다. 단어 하나로 막으면 오탐이 터집니다.
    """
    # TODO: 구현하세요.
    #   힌트: 단일 단어가 아니라 '지시를 덮어쓰려는 의도'의 조합을 보세요.
    raise NotImplementedError("input_guard 를 구현하세요.")


def mask_pii(text: str) -> str:
    """개인정보와 자격증명을 마스킹합니다.

    최소 다섯 가지를 가려야 합니다.
      사번(예: E123456) · 전화번호 · 이메일 · AWS 액세스 키(AKIA...) · JWT(eyJ...)
    """
    # TODO: 구현하세요.
    raise NotImplementedError("mask_pii 를 구현하세요.")


# TODO: 미들웨어를 어떤 순서로 둘지 정하세요.
#   원칙: 차단 -> 정제 -> 검증 -> 기록
#   마스킹이 로깅보다 뒤에 있으면 로그에 원본이 남습니다. 순서 자체가 설계입니다.
#   아래 이름을 그대로 쓰되 순서만 바꾸면 됩니다.
MIDDLEWARE_ORDER: list[str] = [
    # "LoggingMiddleware",
    # "MaskingMiddleware",
    # "OutputCheckMiddleware",
    # "InputGuardMiddleware",
]


# ══════════════════════════════════════════════════════════════════
# 심화 파트 (3점) — 못 해도 과제는 통과합니다
# ══════════════════════════════════════════════════════════════════

# TODO: 도구별 위험도를 정하세요. 값은 "read" | "write" | "destructive" 중 하나입니다.
#   조회는 read, 상태를 바꾸면 write, 되돌릴 수 없으면 destructive.
RISK_LEVELS: dict[str, str] = {}


def needs_approval(tool_name: str, args: dict) -> tuple[bool, str]:
    """이 도구 호출에 사람 승인이 필요한지 판정합니다. LLM을 호출하지 않습니다.

    규칙:
      - read         -> 승인 불필요. (전부 막으면 자동화의 의미가 없습니다)
      - write        -> 승인 필요
      - destructive  -> 승인 필요 + 이중 확인 표시
      - 목록에 없는 도구 -> 승인 필요 (모르는 것은 막는다)

    Returns:
        (승인이 필요한가, 사유 또는 확인 수준)
        destructive인 경우 사유 문자열에 "이중" 또는 "double" 을 포함하세요.
    """
    # TODO: 구현하세요.
    raise NotImplementedError("needs_approval 을 구현하세요.")
