"""Day 2 자가 확인 테스트.

    python scripts/grade.py --day 2

실제 채점은 여기 없는 변형과 비공개 문항으로 한 번 더 확인합니다.
여기서 실패하면 실제 채점에서도 반드시 실패합니다.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from conftest import load_submission, need, load_eval_set  # noqa: E402
from sds_testkit import FakeVectorStore, ScriptedChatModel, make_docs  # noqa: E402

DAY = 2
DOCS_DIR = Path(__file__).resolve().parents[1] / "practice" / "docs"

RELEVANT = make_docs([
    ("r1", "사용하지 않은 연차는 최대 5일까지 다음 해로 이월됩니다.",
     {"source": "leave_policy.md", "department": "people", "updated_at": "2026-03-02"}),
    ("r2", "이월된 연차는 6개월 이내에 사용해야 하며 기한이 지나면 소멸됩니다.",
     {"source": "leave_policy.md", "department": "people", "updated_at": "2026-03-02"}),
])
UNRELATED = make_docs([
    ("u1", "온콜은 주 단위로 순환하며 매주 월요일 오전 10시에 인수인계합니다.",
     {"source": "oncall_policy.md", "department": "sre", "updated_at": "2026-06-30"}),
])

Q_FACT = "연차는 며칠까지 이월되나요?"
Q_NONE = "사내 헬스장 운영 시간이 어떻게 되나요?"


@pytest.fixture(scope="module")
def sub():
    return load_submission(DAY)


@pytest.fixture(scope="module")
def chunks(sub):
    build = need(sub, "build_chunks")
    paths = sorted(str(p) for p in DOCS_DIR.glob("*.md"))
    assert paths, f"실습 문서가 없습니다: {DOCS_DIR}"
    return build(paths)


def _chain(sub, docs, response="연차는 최대 5일까지 이월됩니다."):
    retriever = need(sub, "build_retriever")(FakeVectorStore(docs))
    return need(sub, "build_rag_chain")(retriever, llm=ScriptedChatModel(responses=[response]))


# ── 기초 파트 (7점) ─────────────────────────────────────────────────

@pytest.mark.points(2)
def test_메타데이터_상속(chunks):
    """모든 청크에 source / department / updated_at 세 키가 있는가."""
    assert chunks, "청크가 하나도 만들어지지 않았습니다."
    required = {"source", "department", "updated_at"}
    for i, d in enumerate(chunks):
        missing = required - set(d.metadata or {})
        assert not missing, (
            f"{i}번째 청크에 {sorted(missing)} 키가 없습니다.\n"
            f"  메타데이터는 분할 *전에* 원본 Document에 붙여야 상속됩니다."
        )
    assert len({d.metadata["source"] for d in chunks}) >= 2, "여러 문서를 인덱싱해야 합니다."


@pytest.mark.points(1)
def test_청킹_전략(chunks):
    """청크 수가 합리적이고 원문이 보존되는가."""
    sources = {d.metadata["source"] for d in chunks}
    assert len(chunks) >= len(sources), "문서가 유실되었습니다."
    lengths = [len(d.page_content) for d in chunks]
    assert len(chunks) > len(sources), (
        f"청크 {len(chunks)}개, 문서 {len(sources)}개입니다. 문서당 1개면 분할이 일어나지 않았습니다.\n"
        f"  실습 문서는 700~950자입니다. chunk_size를 800 이하로 낮추세요."
    )
    body = " ".join(d.page_content for d in chunks)
    assert "이월" in body and "롤백" in body, "원문 내용이 유실되었습니다."


@pytest.mark.points(2)
def test_컨텍스트_주입(sub):
    """검색된 문서 본문이 모델 프롬프트에 실제로 들어갔는가."""
    retriever = need(sub, "build_retriever")(FakeVectorStore(RELEVANT))
    llm = ScriptedChatModel(responses=["연차는 최대 5일까지 이월됩니다."])
    need(sub, "build_rag_chain")(retriever, llm=llm).invoke(Q_FACT)

    assert llm.call_count >= 1, "모델이 호출되지 않았습니다."
    text = llm.prompt_text()
    assert "5일" in text, (
        "검색된 문서 본문이 프롬프트에 들어가지 않았습니다.\n"
        "  format_docs 결과를 프롬프트 변수로 넘겼는지 확인하세요."
    )
    assert "이월" in text, "질문 또는 문서 내용이 프롬프트에 없습니다."


@pytest.mark.points(1)
def test_출처_반환(sub):
    """sources가 실제 검색 결과에서 나왔는가."""
    out = _chain(sub, RELEVANT).invoke(Q_FACT)
    assert isinstance(out, dict), f"dict를 반환해야 합니다. 현재 {type(out)}"
    assert {"answer", "sources"} <= set(out), f"키 부족: {list(out)}"
    assert isinstance(out["sources"], list), "sources는 리스트여야 합니다."
    assert out["sources"] == ["leave_policy.md"], (
        f"실제 검색 결과의 source와 다릅니다: {out['sources']}"
    )


@pytest.mark.points(1)
def test_확장_검사_게이트(sub):
    """평가셋과 변형 입력. 공개분 6개 중 5개 이상."""
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
    check("평가셋 5문항 이상", lambda: len(items) >= 5)
    check("세 유형 모두 포함", lambda: {"fact", "paraphrase", "no_answer"}
          <= {i.get("type") for i in items})
    check("문항마다 id·question", lambda: all(i.get("id") and i.get("question") for i in items))
    check("빈 질문", lambda: isinstance(_chain(sub, RELEVANT).invoke(""), dict))
    check("아주 긴 질문", lambda: isinstance(_chain(sub, RELEVANT).invoke("연차 " * 400), dict))
    check("특수문자 질문", lambda: isinstance(_chain(sub, RELEVANT).invoke('{"q": 1} <x>'), dict))

    assert ok >= 5, "확장 검사 {}/6 통과 (5개 이상 필요)\n  실패: {}".format(
        ok, "\n         ".join(fails)
    )


# ── 심화 파트 (3점) ─────────────────────────────────────────────────

@pytest.mark.points(1)
@pytest.mark.advanced
def test_심화_판정의_결정성(sub):
    """assess_retrieval이 상황에 따라 다르게 판정하는가."""
    assess = need(sub, "assess_retrieval")

    v_ok = assess(RELEVANT, Q_FACT)
    v_none = assess([], Q_FACT)
    v_off = assess(UNRELATED, Q_NONE)

    for name, v in (("관련 문서", v_ok), ("빈 목록", v_none), ("무관 문서", v_off)):
        assert isinstance(v, dict) and "usable" in v, f"{name}: dict에 usable 키가 필요합니다."

    assert v_ok["usable"] is True, "관련 문서인데 usable=False 입니다."
    assert v_none["usable"] is False, "검색 결과가 없는데 usable=True 입니다."
    assert v_off["usable"] is False, "무관한 문서인데 usable=True 입니다."


@pytest.mark.points(1)
@pytest.mark.advanced
def test_심화_거절_경로(sub):
    """검색 결과가 비면 모델을 부르지 않고 거절하는가."""
    retriever = need(sub, "build_retriever")(FakeVectorStore([]))
    llm = ScriptedChatModel(responses=["헬스장은 06시부터 22시까지 운영합니다."])
    out = need(sub, "build_rag_chain")(retriever, llm=llm).invoke(Q_NONE)

    assert llm.call_count == 0, (
        f"검색 결과가 없는데 모델을 {llm.call_count}회 호출했습니다.\n"
        "  assess_retrieval이 False면 모델을 부르지 말고 바로 거절하세요."
    )
    assert "찾을 수 없" in out["answer"], f"거절 문구가 없습니다: {out['answer']!r}"
    assert out["sources"] == [], f"거절인데 sources가 비어 있지 않습니다: {out['sources']}"


@pytest.mark.points(1)
@pytest.mark.advanced
def test_심화_파이프라인_연결(sub):
    """무관한 문서만 검색됐을 때 모델이 지어낸 답을 걸러내는가."""
    llm = ScriptedChatModel(responses=["헬스장은 06시부터 22시까지 운영합니다."])
    retriever = need(sub, "build_retriever")(FakeVectorStore(UNRELATED))
    out = need(sub, "build_rag_chain")(retriever, llm=llm).invoke(Q_NONE)

    assert "헬스장은 06시" not in out["answer"], (
        "무관한 문서만 검색됐는데 모델이 지어낸 답이 그대로 나왔습니다.\n"
        "  assess_retrieval 판정을 build_rag_chain에 연결하세요."
    )
    assert out["sources"] == [], "근거가 없는데 sources가 채워졌습니다."
