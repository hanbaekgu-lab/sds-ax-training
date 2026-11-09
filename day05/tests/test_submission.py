"""Day 5 자가 확인 테스트.

    python scripts/grade.py --day 5

여기서는 **공개 세트**로 확인합니다. 실제 채점은 비공개 문항으로 합니다.
공개 세트만 통과하는 하드코딩은 채점에서 걸립니다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from conftest import load_submission, need  # noqa: E402

DAY = 5
DATA = Path(__file__).resolve().parents[1] / "practice" / "data"

ATTACK = json.loads((DATA / "attack_set.json").read_text(encoding="utf-8"))
NORMAL = json.loads((DATA / "normal_set.json").read_text(encoding="utf-8"))

PII_SAMPLE = (
    "담당자 E123456 (010-1234-5678, hong@example.com) 이 "
    "AKIAIOSFODNN7EXAMPLE 키와 eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abc 토큰을 썼습니다."
)


@pytest.fixture(scope="module")
def sub():
    return load_submission(DAY)


# ── 기초 파트 (7점) ─────────────────────────────────────────────────

@pytest.mark.points(2)
def test_공격_차단(sub):
    """공개 공격 10문항 중 9건 이상 차단하는가."""
    guard = need(sub, "input_guard")
    missed = []
    for text in ATTACK:
        blocked, _ = guard(text)
        if not blocked:
            missed.append(text)
    blocked_n = len(ATTACK) - len(missed)
    assert blocked_n >= 9, (
        f"차단 {blocked_n}/{len(ATTACK)} (9건 이상 필요)\n  놓친 것:\n    "
        + "\n    ".join(missed)
    )


@pytest.mark.points(2)
def test_오탐_없음(sub):
    """공개 정상 10문항을 하나도 막지 않는가."""
    guard = need(sub, "input_guard")
    fp = []
    for text in NORMAL:
        blocked, reason = guard(text)
        if blocked:
            fp.append(f"{text}  (사유: {reason})")
    assert not fp, (
        f"정상 요청 {len(fp)}건을 막았습니다 (오탐 0이어야 합니다)\n    "
        + "\n    ".join(fp)
        + "\n\n  단어 하나로 막고 있지 않은지 확인하세요. '무시', '이전', '관리자'는 "
        "정상 문장에도 자주 나옵니다."
    )


@pytest.mark.points(1)
def test_마스킹(sub):
    """다섯 패턴을 모두 가리는가."""
    mask = need(sub, "mask_pii")
    out = mask(PII_SAMPLE)
    leaks = [
        s for s in (
            "E123456", "010-1234-5678", "hong@example.com",
            "AKIAIOSFODNN7EXAMPLE", "eyJhbGciOiJIUzI1NiJ9",
        ) if s in out
    ]
    assert not leaks, f"가려지지 않은 값: {leaks}\n  결과: {out}"


@pytest.mark.points(1)
def test_미들웨어_순서(sub):
    """차단 -> 정제 -> 검증 -> 기록 원칙을 지키는가."""
    order = need(sub, "MIDDLEWARE_ORDER")
    assert len(order) >= 4, f"미들웨어가 {len(order)}개입니다. 4개를 모두 배치하세요."
    idx = {name: i for i, name in enumerate(order)}
    for name in ("InputGuardMiddleware", "MaskingMiddleware", "OutputCheckMiddleware", "LoggingMiddleware"):
        assert name in idx, f"'{name}'이 목록에 없습니다."
    assert idx["InputGuardMiddleware"] < idx["MaskingMiddleware"], "차단이 정제보다 앞이어야 합니다."
    assert idx["MaskingMiddleware"] < idx["LoggingMiddleware"], (
        "마스킹이 로깅보다 뒤에 있으면 로그에 원본이 남습니다."
    )
    assert idx["OutputCheckMiddleware"] < idx["LoggingMiddleware"], "검증이 기록보다 앞이어야 합니다."


@pytest.mark.points(1)
def test_확장_검사_게이트(sub):
    """예외 상황. 공개분 6개 중 5개 이상."""
    guard, mask = need(sub, "input_guard"), need(sub, "mask_pii")
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

    check("빈 입력", lambda: guard("")[0] is False)
    check("공백 입력", lambda: isinstance(guard("   ")[0], bool))
    check("아주 긴 입력", lambda: isinstance(guard("정상 문의 " * 500)[0], bool))
    check("사유 문자열 반환", lambda: bool(str(guard(ATTACK[0])[1]).strip()))
    check("마스킹 멱등성", lambda: mask(mask(PII_SAMPLE)) == mask(PII_SAMPLE))
    check("마스킹 무해 입력 보존", lambda: mask("정상 문장입니다") == "정상 문장입니다")

    assert ok >= 5, "확장 검사 {}/6 통과 (5개 이상 필요)\n  실패: {}".format(
        ok, "\n         ".join(fails)
    )


# ── 심화 파트 (3점) ─────────────────────────────────────────────────

@pytest.mark.points(1)
@pytest.mark.advanced
def test_심화_정책의_결정성(sub):
    """needs_approval이 네 등급에서 표대로 동작하는가."""
    levels = need(sub, "RISK_LEVELS")
    approve = need(sub, "needs_approval")

    counts = {"read": 0, "write": 0, "destructive": 0}
    for tool, lv in levels.items():
        assert lv in counts, f"'{tool}'의 위험도 '{lv}'가 read/write/destructive 중 하나가 아닙니다."
        counts[lv] += 1
    for lv, n in counts.items():
        assert n >= 2, f"'{lv}' 등급 도구가 {n}개입니다. 2개 이상 넣으세요."

    by_level = {lv: [t for t, v in levels.items() if v == lv] for lv in counts}
    assert approve(by_level["read"][0], {})[0] is False, "조회인데 승인을 요구합니다."
    assert approve(by_level["write"][0], {})[0] is True, "변경인데 승인을 요구하지 않습니다."
    assert approve(by_level["destructive"][0], {})[0] is True, "파괴적인데 승인을 요구하지 않습니다."
    assert approve("완전히_모르는_도구", {})[0] is True, "모르는 도구는 승인을 요구해야 합니다."


@pytest.mark.points(1)
@pytest.mark.advanced
def test_심화_과차단_방지(sub):
    """조회 도구를 전부 막아 버리지 않는가."""
    levels, approve = need(sub, "RISK_LEVELS"), need(sub, "needs_approval")
    reads = [t for t, v in levels.items() if v == "read"]
    assert len(reads) >= 2, f"read 등급 도구가 {len(reads)}개입니다. RISK_LEVELS를 채우세요."
    blocked = [t for t in reads if approve(t, {})[0]]
    assert not blocked, (
        f"조회 도구인데 승인을 요구합니다: {blocked}\n"
        "  전부 막으면 자동화의 의미가 없습니다."
    )


@pytest.mark.points(1)
@pytest.mark.advanced
def test_심화_이중_확인(sub):
    """되돌릴 수 없는 작업에 이중 확인 표시가 있는가."""
    levels, approve = need(sub, "RISK_LEVELS"), need(sub, "needs_approval")
    destructive = [t for t, v in levels.items() if v == "destructive"]
    assert len(destructive) >= 2, (
        f"destructive 등급 도구가 {len(destructive)}개입니다. RISK_LEVELS를 채우세요."
    )
    for tool in destructive:
        required, reason = approve(tool, {})
        assert required is True, f"'{tool}'이 승인을 요구하지 않습니다."
        low = str(reason).lower()
        assert "이중" in reason or "double" in low, (
            f"'{tool}'의 사유에 이중 확인 표시가 없습니다: {reason!r}"
        )
