"""Day 3 자가 확인 테스트.

    python scripts/grade.py --day 3
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from conftest import load_submission, need, load_eval_set  # noqa: E402
from sds_testkit import ScriptedChatModel, tool_names_in  # noqa: E402

DAY = 3
Q = "payment-api에서 5xx가 급증했습니다. 원인을 조사해 주세요."


@pytest.fixture(scope="module")
def sub():
    return load_submission(DAY)


def _run(sub, script, responses=None):
    """대본대로 도구를 부르게 하고 최종 메시지 목록을 돌려줍니다."""
    llm = ScriptedChatModel(
        responses=responses or ["조회하겠습니다."] * (len(script) + 1),
        tool_calls_script=script,
    )
    agent = need(sub, "build_agent")(llm=llm)
    out = agent.invoke({"messages": [("user", Q)]}, {"recursion_limit": 30})
    return out["messages"], llm


# ── 기초 파트 (7점) ─────────────────────────────────────────────────

@pytest.mark.points(2)
def test_도구_정의_품질(sub):
    """도구 3개가 설명과 스키마를 갖추고 결정적으로 동작하는가."""
    tools = need(sub, "TOOLS")
    assert len(tools) >= 3, f"도구가 {len(tools)}개입니다. 3개 이상 필요합니다."

    for t in tools:
        desc = (t.description or "").strip()
        assert len(desc) >= 30, f"'{t.name}' 설명이 {len(desc)}자입니다. 30자 이상 필요합니다."
        assert "TODO" not in desc, f"'{t.name}' 설명에 TODO가 남아 있습니다."
        assert t.args_schema is not None, f"'{t.name}'에 args_schema가 없습니다."

    names = {t.name for t in tools}
    assert {"get_deploy_history", "get_logs", "get_metrics"} <= names, (
        f"필수 도구가 없습니다: {sorted(names)}"
    )

    # 결정적인가 — 같은 인자에 항상 같은 결과
    by_name = {t.name: t for t in tools}
    a = by_name["get_metrics"].invoke({"service": "payment-api"})
    b = by_name["get_metrics"].invoke({"service": "payment-api"})
    assert a == b, "같은 인자에 다른 결과가 나옵니다. 도구는 결정적이어야 합니다."


@pytest.mark.points(2)
def test_그래프_위상(sub):
    """agent와 tools 사이에 순환이 있는가."""
    agent = need(sub, "build_agent")(llm=ScriptedChatModel(responses=["ok"]))
    g = agent.get_graph()
    nodes = set(g.nodes)
    assert "tools" in nodes, f"'tools' 노드가 없습니다. 현재 노드: {sorted(nodes)}"

    edges = {(getattr(e, "source", None), getattr(e, "target", None)) for e in g.edges}
    assert ("tools", "agent") in edges or any(
        s == "tools" and t not in (None, "__end__") for s, t in edges
    ), f"tools에서 돌아가는 엣지가 없습니다. 순환이 아닙니다. 엣지: {sorted(map(str, edges))}"


@pytest.mark.points(1)
def test_루프_완주(sub):
    """도구 호출을 강제했을 때 실제로 실행되고 ToolMessage가 남는가."""
    msgs, _ = _run(sub, [[{"name": "get_metrics", "args": {"service": "payment-api"}}], []])
    called = tool_names_in(msgs)
    assert "get_metrics" in called, f"도구가 실행되지 않았습니다. 호출 기록: {called}"
    tool_msgs = [m for m in msgs if m.type == "tool"]
    assert tool_msgs, "ToolMessage가 남지 않았습니다."
    assert "payment-api" in str(tool_msgs[0].content), "도구 결과가 비었습니다."


@pytest.mark.points(1)
def test_연쇄(sub):
    """앞 도구의 결과를 뒤 도구의 인자로 넘기는 흐름이 동작하는가."""
    script = [
        [{"name": "get_deploy_history", "args": {"service": "payment-api"}}],
        [{"name": "get_logs", "args": {"service": "payment-api", "since": "2026-08-11T02:58:00+09:00"}}],
        [],
    ]
    msgs, _ = _run(sub, script)
    called = tool_names_in(msgs)
    assert called[:2] == ["get_deploy_history", "get_logs"], f"호출 순서가 다릅니다: {called}"

    results = [str(m.content) for m in msgs if m.type == "tool"]
    assert any("v2.14.1" in r for r in results), "배포 이력 조회 결과가 비었습니다."
    assert any("NullPointer" in r for r in results), (
        "since를 넘겼는데 해당 구간 로그가 나오지 않았습니다.\n"
        "  get_logs가 since 인자를 실제로 쓰는지 확인하세요."
    )


@pytest.mark.points(1)
def test_확장_검사_게이트(sub):
    """평가셋과 예외 상황. 공개분 6개 중 5개 이상."""
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

    items = load_eval_set()
    types = {i.get("type") for i in items}
    check("no_tool 유형", lambda: "no_tool" in types)
    check("single_tool 유형", lambda: "single_tool" in types)
    check("multi_tool 유형", lambda: "multi_tool" in types)
    check("도구 미사용 경로", lambda: bool(_run(sub, [[]])[0]))
    check("없는 서비스 조회", lambda: "없" in str(
        {t.name: t for t in need(sub, "TOOLS")}["get_metrics"].invoke({"service": "no-such-svc"})
    ))
    check("빈 서비스 이름", lambda: isinstance(
        {t.name: t for t in need(sub, "TOOLS")}["get_metrics"].invoke({"service": ""}), str
    ))

    assert ok >= 5, "확장 검사 {}/6 통과 (5개 이상 필요)\n  실패: {}".format(
        ok, "\n         ".join(fails)
    )


# ── 심화 파트 (3점) ─────────────────────────────────────────────────

@pytest.mark.points(1)
@pytest.mark.advanced
def test_심화_판정의_결정성(sub):
    """should_stop이 네 조건에서 표대로 동작하는가."""
    should_stop = need(sub, "should_stop")
    cap = need(sub, "MAX_TOOL_CALLS")
    assert 3 <= cap <= 8, f"MAX_TOOL_CALLS가 {cap}입니다. 3 이상 8 이하로 정하세요."

    from langchain_core.messages import AIMessage

    def ai(*calls):
        return AIMessage(
            content="",
            tool_calls=[
                {"name": n, "args": a, "id": f"c{i}", "type": "tool_call"}
                for i, (n, a) in enumerate(calls)
            ],
        )

    stop, _ = should_stop([], cap)
    assert stop is True, "예산에 도달했는데 멈추지 않습니다."

    dup = [ai(("get_logs", {"service": "x"})), ai(("get_logs", {"service": "x"}))]
    stop, _ = should_stop(dup, 2)
    assert stop is True, "같은 도구를 같은 인자로 두 번 불렀는데 멈추지 않습니다."

    full = [ai(("get_deploy_history", {"service": "x"})),
            ai(("get_logs", {"service": "x"})),
            ai(("get_metrics", {"service": "x"}))]
    stop, _ = should_stop(full, 3)
    assert stop is True, "세 도구를 모두 썼는데 멈추지 않습니다."

    stop, _ = should_stop([ai(("get_metrics", {"service": "x"}))], 1)
    assert stop is False, "이제 막 시작했는데 멈춥니다."


@pytest.mark.points(1)
@pytest.mark.advanced
def test_심화_예산_준수(sub):
    """모델이 무한히 도구를 부르려 해도 상한에서 멈추는가."""
    cap = need(sub, "MAX_TOOL_CALLS")
    # 매번 다른 인자로 호출해 '중복 호출' 규칙을 피하고 예산 규칙만 시험합니다.
    script = [[{"name": "get_metrics", "args": {"service": f"svc-{i}"}}] for i in range(cap + 8)]
    msgs, _ = _run(sub, script)
    made = sum(1 for m in msgs if m.type == "tool")
    assert made <= cap, f"도구를 {made}회 호출했습니다. 상한 {cap}을 넘었습니다."


@pytest.mark.points(1)
@pytest.mark.advanced
def test_심화_조기_종료(sub):
    """근거가 충분하면 상한에 닿기 전에 멈추는가."""
    cap = need(sub, "MAX_TOOL_CALLS")
    script = [
        [{"name": "get_deploy_history", "args": {"service": "payment-api"}}],
        [{"name": "get_logs", "args": {"service": "payment-api", "since": "2026-08-11T02:58:00+09:00"}}],
        [{"name": "get_metrics", "args": {"service": "payment-api"}}],
    ] + [[{"name": "get_metrics", "args": {"service": f"extra-{i}"}}] for i in range(cap + 5)]

    msgs, _ = _run(sub, script)
    made = sum(1 for m in msgs if m.type == "tool")
    assert made <= 4, (
        f"세 도구를 다 쓴 뒤에도 {made}회까지 조사했습니다.\n"
        "  '근거 충분' 판정을 그래프에 연결하세요."
    )
