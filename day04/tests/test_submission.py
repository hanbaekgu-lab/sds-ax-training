"""Day 4 자가 확인 테스트.

    python scripts/grade.py --day 4
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from conftest import load_submission, need  # noqa: E402

DAY = 4
DAY_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def sub():
    return load_submission(DAY)


class Failing:
    """지정한 예외를 계속 던지는 가짜 백엔드입니다. 호출 횟수를 셉니다."""

    def __init__(self, exc: BaseException, succeed_after: int | None = None):
        self.exc = exc
        self.succeed_after = succeed_after
        self.count = 0

    def __call__(self, asset_id: str):
        self.count += 1
        if self.succeed_after is not None and self.count > self.succeed_after:
            return {"name": "recovered", "status": "running", "owner": "x"}
        raise self.exc


# ── 기초 파트 (7점) ─────────────────────────────────────────────────

@pytest.mark.points(2)
def test_도구_명세(sub):
    """TOOL_SPECS와 TOOLS_IMPL이 갖춰졌는가."""
    specs = need(sub, "TOOL_SPECS")
    impl = need(sub, "TOOLS_IMPL")
    assert len(specs) >= 3, f"도구 명세가 {len(specs)}개입니다. 3개 이상 필요합니다."

    names = []
    for s in specs:
        assert {"name", "description", "args"} <= set(s), f"명세에 키가 부족합니다: {s}"
        desc = str(s["description"]).strip()
        assert len(desc) >= 30, f"'{s['name']}' 설명이 {len(desc)}자입니다. 30자 이상 필요합니다."
        assert "TODO" not in desc, f"'{s['name']}' 설명에 TODO가 남아 있습니다."
        assert s["args"], f"'{s['name']}'에 인자 설명이 없습니다."
        for arg, adesc in s["args"].items():
            assert str(adesc).strip(), f"'{s['name']}'의 인자 '{arg}'에 설명이 없습니다."
        names.append(s["name"])

    assert set(names) == set(impl), (
        f"TOOL_SPECS와 TOOLS_IMPL의 이름이 다릅니다.\n"
        f"  specs: {sorted(names)}\n  impl : {sorted(impl)}"
    )
    assert {"search_runbook", "get_service_owner", "query_recent_incidents"} <= set(impl), (
        f"필수 도구가 없습니다: {sorted(impl)}"
    )


@pytest.mark.points(2)
def test_호출_동작(sub):
    """정상 인자는 값을, 없는 값은 예외 대신 안내 문자열을 반환하는가."""
    impl = need(sub, "TOOLS_IMPL")

    ok = impl["get_service_owner"]("payment-api")
    assert isinstance(ok, str) and "pay-be" in ok, f"정상 조회 결과가 이상합니다: {ok!r}"

    for name, arg in (
        ("get_service_owner", "no-such-service"),
        ("query_recent_incidents", "no-such-service"),
        ("search_runbook", "존재하지않는증상"),
    ):
        try:
            out = impl[name](arg)
        except Exception as exc:  # noqa: BLE001
            pytest.fail(
                f"{name}('{arg}') 가 예외를 던졌습니다: {type(exc).__name__}\n"
                f"  도구는 예외 대신 무엇이 잘못됐는지 알려 주는 문자열을 반환해야 합니다."
            )
        assert isinstance(out, str) and out.strip(), f"{name}이 빈 값을 반환했습니다."


@pytest.mark.points(1)
def test_장애_복구(sub):
    """fetch가 계속 실패해도 예외 없이 대체 경로로 넘어가는가."""
    get_status = need(sub, "get_asset_status")
    backend = Failing(TimeoutError("connection timed out"))

    try:
        out = get_status("SRV-001", fetch=backend)
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"예외가 밖으로 나왔습니다: {type(exc).__name__}: {exc}")

    assert isinstance(out, str), "문자열을 반환해야 합니다."
    assert "get_asset_status_backup" in out, (
        f"대체 경로 이름이 반환값에 없습니다: {out!r}\n"
        "  모델이 다음에 무엇을 할지 알 수 있어야 합니다."
    )


@pytest.mark.points(1)
def test_재시도_실행(sub):
    """재시도가 실제로 일어났는가. 코드에 for문이 있는 것과 도는 것은 다릅니다."""
    get_status = need(sub, "get_asset_status")
    backend = Failing(TimeoutError("connection timed out"))
    get_status("SRV-001", fetch=backend)
    assert backend.count >= 2, (
        f"백엔드를 {backend.count}회만 호출했습니다. 타임아웃에는 재시도가 필요합니다."
    )

    # 한 번 실패 후 성공하면 그 결과를 써야 합니다.
    recover = Failing(TimeoutError("timed out"), succeed_after=1)
    out = get_status("SRV-001", fetch=recover)
    assert "recovered" in out or "running" in out, f"복구 후 결과를 쓰지 않았습니다: {out!r}"


@pytest.mark.points(1)
def test_확장_검사_게이트(sub):
    """시크릿 유출과 예외 상황. 공개분 6개 중 5개 이상."""
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

    token = need(sub, "BACKEND_TOKEN")
    get_status = need(sub, "get_asset_status")
    impl = need(sub, "TOOLS_IMPL")

    check("정상 조회에 토큰 없음", lambda: token not in get_status("SRV-001"))
    check("실패 응답에 토큰 없음",
          lambda: token not in get_status("SRV-001", fetch=Failing(TimeoutError("timed out"))))
    check("없는 자산", lambda: isinstance(get_status("SRV-999"), str))
    check("빈 자산 ID", lambda: isinstance(get_status(""), str))
    check("mcp_server.py 존재", lambda: (DAY_DIR / "mcp_server.py").exists())
    check("backup 단독 동작", lambda: isinstance(need(sub, "get_asset_status_backup")("SRV-001"), str))

    assert ok >= 5, "확장 검사 {}/6 통과 (5개 이상 필요)\n  실패: {}".format(
        ok, "\n         ".join(fails)
    )


# ── 심화 파트 (3점) ─────────────────────────────────────────────────

@pytest.mark.points(1)
@pytest.mark.advanced
def test_심화_분류의_결정성(sub):
    """classify_failure가 여섯 상황에서 표대로 분류하는가."""
    classify = need(sub, "classify_failure")
    cases = [
        (TimeoutError("connection timed out"), "retryable"),
        (ConnectionError("connection reset by peer"), "retryable"),
        (RuntimeError("429 Too Many Requests"), "backoff"),
        (RuntimeError("rate limit exceeded"), "backoff"),
        (ValueError("schema validation failed: field 'status' missing"), "fatal"),
        (LookupError("asset not found: SRV-999"), "fatal"),
    ]
    outs = []
    for exc, want in cases:
        got = classify(exc)
        assert got == want, f"{type(exc).__name__}('{exc}') -> '{got}', 기대 '{want}'"
        outs.append(got)
    assert len(set(outs)) == 3, f"세 종류가 모두 나와야 합니다: {set(outs)}"


@pytest.mark.points(1)
@pytest.mark.advanced
def test_심화_fatal은_즉시_폴백(sub):
    """스키마 오류처럼 고쳐지지 않는 실패에 재시도를 낭비하지 않는가."""
    get_status = need(sub, "get_asset_status")
    backend = Failing(ValueError("schema validation failed"))
    out = get_status("SRV-001", fetch=backend)

    assert backend.count <= 1, (
        f"fatal 오류인데 백엔드를 {backend.count}회 호출했습니다.\n"
        "  재시도해도 달라지지 않는 실패에는 즉시 대체 경로로 넘어가세요."
    )
    assert "get_asset_status_backup" in out, "대체 경로로 넘어가지 않았습니다."


@pytest.mark.points(1)
@pytest.mark.advanced
def test_심화_retryable은_재시도(sub):
    """타임아웃에는 재시도하되 상한을 지키는가."""
    get_status = need(sub, "get_asset_status")
    cap = need(sub, "MAX_RETRIES")

    backend = Failing(TimeoutError("timed out"))
    get_status("SRV-001", fetch=backend)
    assert 2 <= backend.count <= cap, (
        f"타임아웃에 {backend.count}회 호출했습니다. 2회 이상 {cap}회 이하여야 합니다."
    )
