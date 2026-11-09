"""Day 6 자가 확인 테스트.

    python scripts/grade.py --day 6
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from conftest import load_submission, need  # noqa: E402
from sds_testkit import ScriptedChatModel  # noqa: E402

DAY = 6
ROUTING_FILE = Path(__file__).resolve().parents[1] / "routing_test.json"

# 공개 라우팅 케이스 — 채점은 여기에 없는 문항으로도 합니다.
CASES = [
    ("payment-api 로그에 어떤 에러가 찍혔나요?", {"log_agent"}),
    ("payment-api 오류율 지표를 알려주세요.", {"metric_agent"}),
    ("인증서 만료 대응 절차가 어떻게 되나요?", {"runbook_agent"}),
    ("로그의 에러와 현재 지표를 함께 봐 주세요.", {"log_agent", "metric_agent"}),
    ("오늘 점심 메뉴 추천해줘", set()),
]


@pytest.fixture(scope="module")
def sub():
    return load_submission(DAY)


# ── 기초 파트 (7점) ─────────────────────────────────────────────────

@pytest.mark.points(2)
def test_구성(sub):
    """Agent 3개가 정의되고 그래프에 모두 존재하는가."""
    names = need(sub, "AGENT_NAMES")
    assert len(names) >= 3, f"Agent가 {len(names)}개입니다. 3개 이상 필요합니다."
    assert len(set(names)) == len(names), f"이름이 중복됩니다: {names}"

    graph = need(sub, "build_supervisor")(llm=ScriptedChatModel(responses=["ok"]))
    nodes = set(graph.get_graph().nodes)
    missing = [n for n in names if n not in nodes]
    assert not missing, f"그래프에 없는 Agent: {missing}\n  현재 노드: {sorted(nodes)}"


@pytest.mark.points(2)
def test_도구_격리(sub):
    """같은 도구가 여러 Agent에 겹쳐 있지 않은가."""
    names = need(sub, "AGENT_NAMES")
    tools = need(sub, "AGENT_TOOLS")
    assert len(tools) >= 3, f"AGENT_TOOLS가 {len(tools)}개입니다. Agent 3개 모두 채우세요."
    assert set(tools) == set(names), (
        f"AGENT_TOOLS의 키가 AGENT_NAMES와 다릅니다.\n  tools {sorted(tools)}\n  names {sorted(names)}"
    )
    for name, ts in tools.items():
        assert ts, f"'{name}'에 도구가 없습니다."

    seen: dict[str, str] = {}
    overlaps = []
    for name, ts in tools.items():
        for t in ts:
            if t in seen:
                overlaps.append(f"'{t}' 가 {seen[t]} 와 {name} 양쪽에 있음")
            seen[t] = name
    assert not overlaps, (
        "도구가 겹칩니다:\n    " + "\n    ".join(overlaps)
        + "\n  '혹시 몰라서' 얹으면 Supervisor가 어디로 보낼지 헷갈립니다."
    )


@pytest.mark.points(1)
def test_라우팅_정확도(sub):
    """공개 케이스에서 필요한 Agent를 고르는가."""
    route = need(sub, "route_question")
    wrong = []
    for q, expected in CASES:
        got = set(route(q))
        if got != expected:
            wrong.append(f"'{q}' -> {sorted(got)}, 기대 {sorted(expected)}")
    assert len(wrong) <= 1, (
        f"라우팅 오류 {len(wrong)}건입니다. 1건까지만 허용합니다.\n    "
        + "\n    ".join(wrong)
        + "\n\n  README의 라우팅 표에 적힌 어휘와 그 동의어·영문 표기를 함께 넣으세요."
    )


@pytest.mark.points(1)
def test_라우팅_테스트셋(sub):
    """routing_test.json이 요건을 갖췄는가."""
    assert ROUTING_FILE.exists(), f"파일이 없습니다: day06/routing_test.json"
    items = json.loads(ROUTING_FILE.read_text(encoding="utf-8"))
    assert len(items) >= 6, f"{len(items)}문항입니다. 6문항 이상 필요합니다."

    for i in items:
        assert {"question", "expected"} <= set(i), f"키가 부족합니다: {i}"
        assert isinstance(i["expected"], list), "expected는 Agent 이름의 리스트여야 합니다."

    multi = [i for i in items if len(i["expected"]) >= 2]
    assert multi, "복합 질문(Agent 2개 이상)이 최소 1문항 필요합니다."
    single = [i for i in items if len(i["expected"]) == 1]
    assert len(single) >= 3, f"단일 Agent 문항이 {len(single)}개입니다. 3개 이상 필요합니다."


@pytest.mark.points(1)
def test_확장_검사_게이트(sub):
    """예외 상황과 호출 절제. 공개분 6개 중 5개 이상."""
    route = need(sub, "route_question")
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

    check("빈 질문", lambda: route("") == [])
    check("무관한 질문", lambda: route("오늘 날씨 어때?") == [])
    check("아주 긴 질문", lambda: isinstance(route("로그 " * 500), list))
    check("반환은 리스트", lambda: isinstance(route("지표 알려줘"), list))
    check("결과 중복 없음", lambda: len(set(route("로그와 에러와 예외"))) == len(route("로그와 에러와 예외")))
    check("불필요 호출 절제", lambda: len(route("지표만 알려주세요")) <= 2)

    assert ok >= 5, "확장 검사 {}/6 통과 (5개 이상 필요)\n  실패: {}".format(
        ok, "\n         ".join(fails)
    )


# ── 심화 파트 (3점) ─────────────────────────────────────────────────

@pytest.mark.points(1)
@pytest.mark.advanced
def test_심화_게이팅_결정성(sub):
    """judge_output이 세 상황을 실제로 구분하는가."""
    judge = need(sub, "judge_output")
    good = judge("log_agent", "payment-api 로그에서 NullPointerException 이 1243건 관측되었습니다.")
    empty = judge("log_agent", "")
    short = judge("log_agent", "확인함")
    bare = judge("metric_agent", "이것은 확실합니다. 틀림없이 배포 때문입니다. 원인은 그것뿐입니다.")

    for name, v in (("정상", good), ("빈 값", empty), ("짧은 값", short), ("근거 없음", bare)):
        assert isinstance(v, dict) and "keep" in v, f"{name}: dict에 keep 키가 필요합니다."

    assert good["keep"] is True, "근거가 있는 정상 산출물을 막았습니다."
    assert empty["keep"] is False, "빈 산출물을 통과시켰습니다."
    assert short["keep"] is False, "너무 짧은 산출물을 통과시켰습니다."
    assert bare["keep"] is False, "근거 없는 단정을 통과시켰습니다."


@pytest.mark.points(1)
@pytest.mark.advanced
def test_심화_저가치_억제(sub):
    """저가치 산출물에 사유가 붙는가."""
    judge = need(sub, "judge_output")
    for text in ("", "ok", "확인"):
        v = judge("log_agent", text)
        assert v["keep"] is False, f"{text!r} 를 통과시켰습니다."
        assert str(v.get("reason", "")).strip(), f"{text!r}: 억제 사유가 없습니다."


@pytest.mark.points(1)
@pytest.mark.advanced
def test_심화_파이프라인_연결(sub):
    """Supervisor 실행 결과에 게이팅이 반영되는가."""
    graph = need(sub, "build_supervisor")(llm=ScriptedChatModel(responses=["ok"]))
    out = graph.invoke(
        {"messages": [("user", "payment-api 로그의 에러를 확인해 주세요.")], "targets": []},
        {"recursion_limit": 30},
    )
    texts = " ".join(str(m.content) for m in out["messages"])
    assert "log_agent" in texts, (
        f"log_agent가 실행되지 않았습니다. 결과: {texts[:200]}"
    )
