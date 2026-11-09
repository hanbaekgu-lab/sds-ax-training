"""Day 1 자가 확인 테스트.

제출 전에 직접 돌려 보는 용도입니다.

    python scripts/grade.py --day 1

여기를 통과한다고 만점이 보장되지는 않습니다.
실제 채점은 여기 없는 변형 입력과 비공개 데이터로 한 번 더 확인합니다.
다만 여기서 실패하면 실제 채점에서도 반드시 실패합니다.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from conftest import load_submission, need  # noqa: E402
from sds_testkit import ScriptedChatModel  # noqa: E402

DAY = 1

SAMPLE_ALERT = {
    "alert_id": "ALT-2026-0811-0042",
    "service": "payment-api",
    "raised_at": "2026-08-11T03:14:22+09:00",
    "message": "HTTP 5xx ratio 12.4% over 5m (threshold 1%)",
    "region": "ap-northeast-2",
}


VALID_JSON = '{"severity": "P1", "service": "payment-api", "category": "availability", "first_check": "최근 배포 이력"}'


@pytest.fixture(scope="module")
def sub():
    return load_submission(DAY)


# ── 기초 파트 (7점) ─────────────────────────────────────────────────

@pytest.mark.points(2)
def test_스키마_계약(sub):
    """TRIAGE_SCHEMA가 필드 4개 이상이고 모든 필드에 설명이 붙었는가."""
    schema = need(sub, "TRIAGE_SCHEMA")
    assert isinstance(schema, type) and issubclass(schema, BaseModel), (
        "TRIAGE_SCHEMA는 pydantic BaseModel을 상속한 클래스여야 합니다."
    )

    fields = schema.model_fields
    assert len(fields) >= 4, f"필드가 {len(fields)}개입니다. 4개 이상 필요합니다."

    no_desc = [n for n, f in fields.items() if not (f.description or "").strip()]
    assert not no_desc, (
        f"설명이 없는 필드: {no_desc}\n"
        f"  모델이 보는 것은 필드 이름과 description 뿐입니다."
    )

    todo = [n for n, f in fields.items() if "TODO" in (f.description or "")]
    assert not todo, f"description에 TODO가 남아 있습니다: {todo}"

    assert "severity" in fields, "severity 필드가 필요합니다."
    sev = str(fields["severity"].annotation)
    assert "Literal" in sev or "Enum" in sev, (
        f"severity는 값을 제한해야 합니다 (Literal 또는 Enum). 현재: {sev}"
    )


@pytest.mark.points(2)
def test_병렬_조립(sub):
    """build_full_chain이 triage와 notice 두 키를 채워 돌려주는가."""
    build = need(sub, "build_full_chain")
    result = build(llm=ScriptedChatModel(responses=[VALID_JSON]))
    out = result.invoke(SAMPLE_ALERT)

    assert isinstance(out, dict), f"dict를 반환해야 합니다. 현재: {type(out)}"
    for key in ("triage", "notice"):
        assert key in out, f"'{key}' 키가 없습니다. 현재 키: {list(out)}"
    assert isinstance(out["triage"], dict), "triage는 dict여야 합니다."
    assert str(out["notice"]).strip(), "notice가 비어 있습니다."


@pytest.mark.points(1)
def test_형식_지침_주입(sub):
    """분류 체인 프롬프트에 파서의 format_instructions가 실제로 들어갔는가."""
    build = need(sub, "build_triage_chain")
    llm = ScriptedChatModel(responses=[VALID_JSON])
    build(llm=llm).invoke(SAMPLE_ALERT)

    assert llm.call_count, "모델이 한 번도 호출되지 않았습니다."
    joined = llm.prompt_text()
    hints = ("json", "schema", "properties", "출력", "형식")
    assert any(h in joined.lower() for h in hints), (
        "프롬프트에 형식 지침이 보이지 않습니다.\n"
        "  parser.get_format_instructions() 를 프롬프트에 넣었는지 확인하세요."
    )


@pytest.mark.points(1)
def test_역할_지정(sub):
    """안내 체인에 system 메시지가 있고 기본 문구에서 바뀌었는가."""
    build = need(sub, "build_notice_chain")
    llm = ScriptedChatModel(responses=["담당팀 안내 초안입니다."])
    build(llm=llm).invoke(SAMPLE_ALERT)

    joined = llm.prompt_text()
    assert len(joined) >= 30, "프롬프트가 너무 짧습니다. system 메시지로 역할을 지정하세요."
    assert "TODO" not in joined, "프롬프트에 TODO가 남아 있습니다."


@pytest.mark.points(1)
def test_확장_검사_게이트(sub):
    """변형 알람에도 파이프라인이 무너지지 않는가. 공개분 6개 중 5개 이상."""
    build = need(sub, "build_full_chain")
    chain = build(llm=ScriptedChatModel(responses=[VALID_JSON]))

    variants = {
        "빈 메시지": {**SAMPLE_ALERT, "message": ""},
        "service 누락": {k: v for k, v in SAMPLE_ALERT.items() if k != "service"},
        "아주 긴 본문": {**SAMPLE_ALERT, "message": "timeout " * 500},
        "한영 혼재": {**SAMPLE_ALERT, "message": "결제 API 5xx 급증 detected"},
        "특수문자": {**SAMPLE_ALERT, "message": "5xx ↑↑ {\"nested\": true} <script>"},
        "재처리 동일성": SAMPLE_ALERT,
    }

    ok, fails = 0, []
    for name, alert in variants.items():
        try:
            out = chain.invoke(alert)
            if isinstance(out, dict) and "triage" in out and "notice" in out:
                ok += 1
            else:
                fails.append(f"{name}: 반환 형태가 어긋남")
        except Exception as exc:  # noqa: BLE001
            fails.append(f"{name}: {type(exc).__name__} {exc}")

    assert ok >= 5, "확장 검사 {}/6 통과 (5개 이상 필요)\n  실패: {}".format(
        ok, "\n         ".join(fails)
    )


# ── 심화 파트 (3점) ─────────────────────────────────────────────────
# 여기를 못 해도 과제는 통과합니다. 통과선은 7점입니다.

@pytest.mark.points(1)
@pytest.mark.advanced
def test_심화_깨진_출력_복구(sub):
    """모델이 JSON이 아닌 응답을 해도 예외 없이 dict를 반환하는가."""
    build = need(sub, "build_full_chain")
    chain = build(llm=ScriptedChatModel(responses=["죄송합니다. 판단할 수 없습니다."]))

    try:
        out = chain.invoke(SAMPLE_ALERT)
    except Exception as exc:  # noqa: BLE001
        pytest.fail(
            f"모델이 형식을 깨자 예외가 났습니다: {type(exc).__name__}: {exc}\n"
            f"  복구 경로를 붙이세요 (try/except 기본값, 재시도, OutputFixingParser 등)."
        )

    assert isinstance(out, dict) and "triage" in out, "복구 후에도 dict를 반환해야 합니다."
    assert isinstance(out["triage"], dict), "복구된 triage도 dict여야 합니다."


@pytest.mark.points(1)
@pytest.mark.advanced
def test_심화_규칙의_결정성(sub):
    """apply_severity_rules가 규칙표대로 동작하고 상수 반환이 아닌가."""
    rules = need(sub, "apply_severity_rules")
    critical = need(sub, "CRITICAL_SERVICES")
    assert len(critical) >= 3, f"CRITICAL_SERVICES가 {len(critical)}개입니다. 3개 이상 넣으세요."

    svc = sorted(critical)[0]
    base = {"severity": "P4"}

    # 중요 서비스 -> 최소 P2
    r1 = rules(dict(base), {"service": svc, "message": "cpu high"})
    assert r1["severity"] in ("P1", "P2"), f"중요 서비스인데 {r1['severity']} 입니다."

    # 5xx -> 최소 P1
    r2 = rules(dict(base), {"service": "etc-api", "message": "HTTP 5xx ratio 9%"})
    assert r2["severity"] == "P1", f"5xx인데 {r2['severity']} 입니다."

    # 해당 없음 -> 그대로
    r3 = rules(dict(base), {"service": "etc-api", "message": "cpu high"})
    assert r3["severity"] == "P4", f"규칙 대상이 아닌데 {r3['severity']}로 바뀌었습니다."

    # 이미 더 높으면 낮추지 않음
    r4 = rules({"severity": "P1"}, {"service": svc, "message": "cpu high"})
    assert r4["severity"] == "P1", "이미 더 높은 등급을 낮추면 안 됩니다."

    assert len({r1["severity"], r2["severity"], r3["severity"]}) > 1, (
        "입력이 달라도 결과가 같습니다. 규칙이 실제로 동작하는지 확인하세요."
    )


@pytest.mark.points(1)
@pytest.mark.advanced
def test_심화_파이프라인_연결(sub):
    """build_full_chain의 triage 결과에 규칙 적용 흔적이 남는가."""
    build = need(sub, "build_full_chain")
    critical = need(sub, "CRITICAL_SERVICES")
    assert critical, "CRITICAL_SERVICES가 비어 있습니다. 중요 서비스를 3개 이상 넣으세요."
    svc = sorted(critical)[0]

    low = '{"severity": "P4", "service": "%s", "category": "etc", "first_check": "확인"}' % svc
    out = build(llm=ScriptedChatModel(responses=[low])).invoke({**SAMPLE_ALERT, "service": svc, "message": "cpu high"})

    triage = out["triage"]
    assert triage.get("severity") in ("P1", "P2"), (
        f"규칙이 파이프라인에 연결되지 않았습니다. severity={triage.get('severity')}\n"
        f"  build_full_chain 안에서 apply_severity_rules를 호출하세요."
    )
