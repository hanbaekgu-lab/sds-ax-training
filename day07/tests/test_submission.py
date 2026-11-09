"""Day 7 자가 확인 테스트.

    python scripts/grade.py --day 7
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from conftest import load_submission, need, load_eval_set  # noqa: E402

DAY = 7
GROWTH = Path(__file__).resolve().parents[2] / "day07" / "growth.md"

SAMPLE = [
    {"id": "s1", "question": "연차 이월", "type": "fact"},
    {"id": "s2", "question": "없는 정보", "type": "no_answer"},
    {"id": "s3", "question": "차단 요청", "type": "guardrail"},
    {"id": "s4", "question": "터지는 질문", "type": "fact"},
]


def answer_ok(q: str):
    if "터지는" in q:
        raise RuntimeError("의도적 예외")
    return "" if "없는" in q else "답변입니다"


@pytest.fixture(scope="module")
def sub():
    return load_submission(DAY)


# ── 기초 파트 (7점) ─────────────────────────────────────────────────

@pytest.mark.points(2)
def test_평가셋_누적(sub):
    """eval_set.json이 Day2부터 실제로 쌓였는가."""
    items = load_eval_set()
    assert len(items) >= 12, (
        f"{len(items)}문항입니다. Day2~6에서 누적하면 12문항 이상이 됩니다.\n"
        "  마지막 날 몰아서 만들면 유형 분포가 어색해집니다."
    )
    types = {i.get("type") for i in items}
    assert len(types) >= 5, f"유형이 {len(types)}종입니다. 5종 이상 필요합니다: {sorted(types)}"
    assert {"fact", "no_answer"} <= types, f"기본 유형이 없습니다: {sorted(types)}"
    ids = [i.get("id") for i in items]
    assert len(set(ids)) == len(ids), "문항 id가 중복됩니다."


@pytest.mark.points(2)
def test_집계_형식(sub):
    """run_eval이 규정 스키마대로 유형별 집계를 내는가."""
    run_eval = need(sub, "run_eval")
    r = run_eval(answer_ok, SAMPLE)

    assert isinstance(r, dict), f"dict를 반환해야 합니다: {type(r)}"
    for key in ("total", "passed", "by_type", "failures"):
        assert key in r, f"'{key}' 키가 없습니다. 현재 키: {list(r)}"

    assert r["total"] == len(SAMPLE), f"total이 {r['total']}입니다."
    assert isinstance(r["by_type"], dict) and r["by_type"], "by_type이 비었습니다."
    for t, v in r["by_type"].items():
        assert {"total", "passed"} <= set(v), f"'{t}' 집계에 키가 부족합니다: {v}"
    assert sum(v["total"] for v in r["by_type"].values()) == len(SAMPLE), "유형별 합이 전체와 다릅니다."


@pytest.mark.points(1)
def test_예외_격리(sub):
    """한 문항이 터져도 전체 실행이 멈추지 않는가."""
    run_eval = need(sub, "run_eval")
    try:
        r = run_eval(answer_ok, SAMPLE)
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"한 문항의 예외가 전체를 멈췄습니다: {type(exc).__name__}: {exc}")

    assert r["total"] == len(SAMPLE), "예외가 난 문항이 집계에서 빠졌습니다."
    errors = [f for f in r["failures"] if f.get("status") == "error"]
    assert errors, "예외가 난 문항이 error로 기록되지 않았습니다."
    assert errors[0].get("id") == "s4", f"error 문항 id가 다릅니다: {errors[0]}"


@pytest.mark.points(1)
def test_계측(sub):
    """trace가 결정적 구조로 남는가."""
    Collector = need(sub, "TraceCollector")
    t = Collector()
    t.record("llm_start", "claude", latency_s=0.42)
    t.record("tool_start", "get_logs")
    t.record("tool_end", "get_logs", latency_s=0.01)

    events = t.events
    assert len(events) == 3, f"이벤트가 {len(events)}개입니다."
    assert {e["event"] for e in events} == {"llm_start", "tool_start", "tool_end"}, (
        f"기록된 event 값이 다릅니다: {sorted({e['event'] for e in events})}"
    )
    assert any("latency_s" in e for e in events), "지연 시간 필드가 없습니다."

    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "trace.jsonl"
        t.dump(path)
        assert path.exists(), "dump가 파일을 만들지 않았습니다."
        lines = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(lines) == 3, f"JSON Lines가 {len(lines)}줄입니다. 한 줄에 한 이벤트여야 합니다."


@pytest.mark.points(1)
def test_확장_검사_게이트(sub):
    """유형별 성적과 산출물. 공개분 6개 중 5개 이상."""
    run_eval = need(sub, "run_eval")
    ok, fails = 0, []

    def check(name, fn):
        nonlocal ok
        try:
            if fn():
                ok += 1
            else:
                fails.append(name)
        except Exception as exc:  # noqa: BLE001
            fails.append(f"{name}: {type(exc).__name__} {exc}")

    check("빈 평가셋", lambda: run_eval(answer_ok, [])["total"] == 0)
    check("judge 주입", lambda: run_eval(lambda q: "x", SAMPLE[:1], judge=lambda i, a: False)["passed"] == 0)
    check("judge 주입 통과", lambda: run_eval(lambda q: "x", SAMPLE[:1], judge=lambda i, a: True)["passed"] == 1)
    check("failures에 id 존재", lambda: all("id" in f for f in run_eval(answer_ok, SAMPLE)["failures"]))
    check("growth.md 존재", lambda: GROWTH.exists())
    check("growth.md 내용", lambda: len(GROWTH.read_text(encoding="utf-8").strip()) >= 100 if GROWTH.exists() else False)

    assert ok >= 5, "확장 검사 {}/6 통과 (5개 이상 필요)\n  실패: {}".format(
        ok, "\n         ".join(fails)
    )


# ── 심화 파트 (3점) ─────────────────────────────────────────────────

@pytest.mark.points(1)
@pytest.mark.advanced
def test_심화_비교의_결정성(sub):
    """compare_eval이 개선과 회귀를 분리하는가."""
    run_eval, compare = need(sub, "run_eval"), need(sub, "compare_eval")

    before = run_eval(lambda q: "" if "연차" in q else "답변", SAMPLE[:3])
    after = run_eval(lambda q: "" if "차단" in q else "답변", SAMPLE[:3])
    r = compare(before, after)

    for key in ("fixed", "regressed", "delta", "safe"):
        assert key in r, f"'{key}' 키가 없습니다: {list(r)}"
    assert "s1" in r["fixed"], f"고쳐진 문항이 fixed에 없습니다: {r}"
    assert "s3" in r["regressed"], f"깨진 문항이 regressed에 없습니다: {r}"


@pytest.mark.points(1)
@pytest.mark.advanced
def test_심화_회귀_탐지(sub):
    """통과율이 올라도 회귀가 있으면 safe가 False인가."""
    run_eval, compare = need(sub, "run_eval"), need(sub, "compare_eval")

    # 전체 통과 수는 늘지만 s1이 깨집니다.
    before = run_eval(lambda q: "" if ("없는" in q or "차단" in q) else "답변", SAMPLE[:3])
    after = run_eval(lambda q: "" if "연차" in q else "답변", SAMPLE[:3])
    r = compare(before, after)

    assert r["delta"] > 0, f"통과 수가 늘어야 하는 시나리오입니다: {r}"
    assert r["safe"] is False, f"회귀가 있는데 safe=True 입니다: {r}"
    assert r["regressed"], "회귀 문항이 비어 있습니다."


@pytest.mark.points(1)
@pytest.mark.advanced
def test_심화_회귀_없음(sub):
    """회귀가 없으면 safe가 True인가. 무조건 False를 내는 구현 방지."""
    run_eval, compare = need(sub, "run_eval"), need(sub, "compare_eval")

    before = run_eval(lambda q: "" if "없는" in q else "답변", SAMPLE[:3])
    after = run_eval(lambda q: "답변", SAMPLE[:3])
    r = compare(before, after)

    assert r["regressed"] == [], f"회귀가 없어야 합니다: {r}"
    assert r["safe"] is True, f"회귀가 없는데 safe=False 입니다: {r}"
