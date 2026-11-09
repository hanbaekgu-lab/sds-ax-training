"""Day 7 — 계측과 누적 평가.

6일간 쌓은 시스템을 측정합니다.

[중요]
  1. 함수·상수 이름을 바꾸지 마세요.
  2. run_eval과 compare_eval은 LLM을 호출하지 않습니다.
     '답이 맞았는가'의 판정은 호출자가 넘겨 준 함수가 합니다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

# 판정 결과에 쓰는 상태값입니다. 이 셋만 씁니다.
PASS, FAIL, ERROR = "pass", "fail", "error"


# ══════════════════════════════════════════════════════════════════
# 기초 파트 (7점)
# ══════════════════════════════════════════════════════════════════

class TraceCollector:
    """실행 중 일어난 일을 기록합니다.

    LangChain 콜백 핸들러로도 쓸 수 있게 만들되, 여기서는 최소 인터페이스만 요구합니다.
    trace는 결정적 구조체라서, LLM이 무슨 말을 했든 이벤트 개수와 필드는 확정 검사됩니다.
    """

    def __init__(self) -> None:
        # TODO: 기록을 담을 목록을 준비하세요.
        raise NotImplementedError("TraceCollector.__init__ 을 구현하세요.")

    def record(self, event: str, name: str, **fields: Any) -> None:
        """이벤트 하나를 기록합니다.

        event: "llm_start" | "llm_end" | "tool_start" | "tool_end" 중 하나
        name : 모델 이름 또는 도구 이름
        fields: latency_s, tokens 등 부가 정보
        """
        # TODO: 구현하세요. 최소한 event, name, 그리고 순번을 남기세요.
        raise NotImplementedError("TraceCollector.record 를 구현하세요.")

    @property
    def events(self) -> list[dict]:
        """기록된 이벤트 목록을 반환합니다."""
        # TODO: 구현하세요.
        raise NotImplementedError("TraceCollector.events 를 구현하세요.")

    def dump(self, path: str | Path) -> None:
        """이벤트를 JSON Lines 파일로 씁니다. 한 줄에 한 이벤트."""
        # TODO: 구현하세요.
        raise NotImplementedError("TraceCollector.dump 를 구현하세요.")


def run_eval(answer_fn: Callable[[str], Any], eval_set: list[dict],
             judge: Callable[[dict, Any], bool] | None = None) -> dict:
    """평가셋을 전부 돌려 유형별 통과율을 냅니다.

    Args:
        answer_fn: 질문 문자열을 받아 답을 돌려주는 함수. 예외가 날 수 있습니다.
        eval_set: [{"id", "question", "type", ...}] 목록
        judge: (문항, 답) -> 통과 여부. None이면 '답이 비어 있지 않으면 통과'로 봅니다.

    Returns:
        {
          "total": 전체 문항 수,
          "passed": 통과 수,
          "by_type": {유형: {"total": n, "passed": m}},
          "failures": [{"id", "type", "status", "detail"}],
        }

    반드시 지킬 것:
      - answer_fn이 예외를 던져도 전체 실행이 멈추면 안 됩니다.
        그 문항은 status를 ERROR로 기록하고 계속 진행합니다.
    """
    # TODO: 구현하세요.
    raise NotImplementedError("run_eval 을 구현하세요.")


# ══════════════════════════════════════════════════════════════════
# 심화 파트 (3점) — 못 해도 과제는 통과합니다
# ══════════════════════════════════════════════════════════════════

def compare_eval(before: dict, after: dict) -> dict:
    """개선 전후를 비교합니다. LLM을 호출하지 않습니다.

    통과율 총합만 보면 '무엇이 좋아지고 무엇이 깨졌는지'를 알 수 없습니다.
    한 유형을 고치면 다른 유형이 깨지는 일이 실제로 자주 일어납니다.

    Args:
        before, after: run_eval이 반환한 dict

    Returns:
        {
          "fixed":     [before에서 실패했다가 after에서 통과한 문항 id],
          "regressed": [before에서 통과했다가 after에서 실패한 문항 id],
          "delta": after.passed - before.passed,
          "safe": regressed가 비었으면 True,
        }
    """
    # TODO: 구현하세요.
    raise NotImplementedError("compare_eval 을 구현하세요.")
