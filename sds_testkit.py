"""과제 자가 확인 · 채점 공용 테스트킷.

실제 Bedrock을 호출하지 않고 학생 코드의 배선을 검증하기 위한 도구입니다.
정해진 대본대로 응답하고, 모델에게 전달된 프롬프트를 전부 기록합니다.

핵심 아이디어: LLM이 무엇을 답했는지가 아니라
**LLM에게 무엇이 전달되었는지**와 **그 뒤에 무엇이 실행되었는지**를 봅니다.
이렇게 하면 판정이 완전히 결정적이 되고 API 비용이 0이 됩니다.

학생도 자기 테스트를 쓸 때 이 모듈을 그대로 쓸 수 있습니다.

    from sds_testkit import ScriptedChatModel
    llm = ScriptedChatModel(responses=['{"severity": "P1"}'])
    chain = build_triage_chain(llm)
    chain.invoke(alert)
    assert "severity" in llm.prompt_text()
"""


from __future__ import annotations

import json
from typing import Any, Iterator, Sequence

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class ScriptedChatModel(BaseChatModel):
    """대본대로 응답하면서 받은 프롬프트를 기록하는 가짜 모델입니다.

    사용 예:
        llm = ScriptedChatModel(responses=['{"severity": "P1"}'])
        chain = submission.build_triage_chain(llm)
        chain.invoke({"alert": "..."})
        assert "severity" in llm.prompt_text()
    """

    responses: list[str] = []
    """순서대로 반환할 응답 문자열입니다. 다 쓰면 마지막 것을 반복합니다."""

    tool_calls_script: list[list[dict[str, Any]]] = []
    """호출 회차별로 강제할 tool_calls입니다. 빈 리스트면 도구를 부르지 않습니다."""

    seen_prompts: list[list[BaseMessage]] = []
    """모델이 받은 메시지 목록을 호출 순서대로 기록합니다."""

    seen_kwargs: list[dict[str, Any]] = []
    """bind() 등으로 전달된 추가 인자를 기록합니다."""

    call_count: int = 0

    bound_tools: list[str] = []
    """bind_tools로 묶인 도구 이름입니다."""

    model_config = {"arbitrary_types_allowed": True, "extra": "allow"}

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("responses", ["채점용 고정 응답입니다."])
        kwargs.setdefault("tool_calls_script", [])
        super().__init__(**kwargs)
        # Pydantic 필드 기본값이 인스턴스 간에 공유되지 않도록 새 리스트를 만듭니다.
        object.__setattr__(self, "seen_prompts", [])
        object.__setattr__(self, "seen_kwargs", [])
        object.__setattr__(self, "call_count", 0)
        object.__setattr__(self, "bound_tools", [])

    @property
    def _llm_type(self) -> str:
        return "scripted-chat-model"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        idx = self.call_count
        self.seen_prompts.append(list(messages))
        self.seen_kwargs.append(dict(kwargs))
        self.call_count = idx + 1

        text = self.responses[min(idx, len(self.responses) - 1)] if self.responses else ""

        tool_calls: list[dict[str, Any]] = []
        if idx < len(self.tool_calls_script):
            for i, tc in enumerate(self.tool_calls_script[idx]):
                tool_calls.append(
                    {
                        "name": tc["name"],
                        "args": tc.get("args", {}),
                        "id": tc.get("id", f"call_{idx}_{i}"),
                        "type": "tool_call",
                    }
                )

        message = AIMessage(content=text, tool_calls=tool_calls)
        return ChatResult(generations=[ChatGeneration(message=message)])

    def bind_tools(self, tools, **kwargs: Any):
        """도구를 묶습니다. 어떤 도구가 묶였는지 기록해 두고 자기 자신을 돌려줍니다.

        실제 모델이라면 도구 스키마를 API로 보내지만, 여기서는 기록만 합니다.
        도구 호출 여부는 tool_calls_script로 대본에서 강제합니다.
        """
        names = []
        for t in tools or []:
            name = getattr(t, "name", None)
            if name is None and isinstance(t, dict):
                name = (t.get("function") or t).get("name")
            if name is None:
                name = getattr(t, "__name__", str(t))
            names.append(name)
        self.bound_tools.extend(n for n in names if n not in self.bound_tools)
        return self

    # ── 검증 보조 메서드 ────────────────────────────────────────────

    def prompt_text(self, call: int | None = None) -> str:
        """모델이 받은 프롬프트 전체를 하나의 문자열로 이어 붙여 반환합니다.

        call을 주면 그 회차만, 주지 않으면 전 회차를 합칩니다.
        """
        target = self.seen_prompts if call is None else [self.seen_prompts[call]]
        parts: list[str] = []
        for msgs in target:
            for m in msgs:
                content = m.content
                if isinstance(content, list):
                    content = "".join(
                        b.get("text", "") for b in content if isinstance(b, dict)
                    )
                parts.append(f"[{m.type}] {content}")
        return "\n".join(parts)

    def system_text(self) -> str:
        """system 역할 메시지만 모아 반환합니다."""
        parts = []
        for msgs in self.seen_prompts:
            for m in msgs:
                if m.type == "system":
                    parts.append(str(m.content))
        return "\n".join(parts)

    def bound_tool_names(self) -> list[str]:
        """bind_tools로 모델에 묶인 도구 이름을 반환합니다."""
        names: list[str] = list(self.bound_tools)
        for kw in self.seen_kwargs:
            for tool in kw.get("tools", []) or []:
                if isinstance(tool, dict):
                    fn = tool.get("function", tool)
                    name = fn.get("name")
                elif hasattr(tool, "name"):
                    name = tool.name
                else:
                    name = None
                if name and name not in names:
                    names.append(name)
        return names


class CallCounter:
    """도구나 백엔드 함수의 호출 횟수와 인자를 세는 도구입니다.

    재시도가 코드에 적혀 있는 것과 실제로 일어나는 것은 다릅니다. 이걸로 셉니다.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def wrap(self, fn):
        def wrapped(*args: Any, **kwargs: Any):
            self.calls.append((args, kwargs))
            return fn(*args, **kwargs)

        wrapped.__name__ = getattr(fn, "__name__", "wrapped")
        wrapped.__doc__ = getattr(fn, "__doc__", None)
        return wrapped

    @property
    def count(self) -> int:
        return len(self.calls)

    def args_at(self, i: int) -> tuple[tuple[Any, ...], dict[str, Any]]:
        return self.calls[i]


def tool_names_in(messages: Sequence[BaseMessage]) -> list[str]:
    """메시지 목록에서 실제로 호출된 도구 이름을 순서대로 뽑습니다."""
    names: list[str] = []
    for m in messages:
        for tc in getattr(m, "tool_calls", None) or []:
            names.append(tc["name"] if isinstance(tc, dict) else tc.name)
    return names


def tool_results_in(messages: Sequence[BaseMessage]) -> list[str]:
    """ToolMessage 본문을 순서대로 뽑습니다."""
    out: list[str] = []
    for m in messages:
        if m.type == "tool":
            content = m.content
            if isinstance(content, list):
                content = "".join(
                    b.get("text", "") for b in content if isinstance(b, dict)
                )
            out.append(str(content))
    return out


def as_json(text: str) -> Any:
    """모델 응답 문자열에서 JSON을 최대한 관대하게 뽑아냅니다."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"JSON을 찾을 수 없습니다: {text[:120]}")
    return json.loads(text[start : end + 1])


# ══════════════════════════════════════════════════════════════════
# RAG 검증용 가짜 벡터 저장소
# ══════════════════════════════════════════════════════════════════

class FakeRetriever:
    """미리 정해둔 문서를 돌려주는 retriever입니다.

    임베딩 API를 부르지 않으므로 검색 자체는 결정적입니다.
    학생 코드가 '검색 결과를 어떻게 다루는가'만 봅니다.
    """

    def __init__(self, docs, k: int = 3):
        self.docs = list(docs)
        self.k = k
        self.queries: list[str] = []

    def invoke(self, query, *args, **kwargs):
        self.queries.append(str(query))
        return self.docs[: self.k]

    # 구버전 인터페이스도 함께 지원합니다.
    def get_relevant_documents(self, query, **kwargs):
        return self.invoke(query)


class FakeVectorStore:
    """as_retriever()만 제공하는 최소 벡터 저장소입니다."""

    def __init__(self, docs):
        self.docs = list(docs)
        self.last_kwargs: dict[str, Any] = {}

    def as_retriever(self, **kwargs):
        self.last_kwargs = dict(kwargs)
        k = int((kwargs.get("search_kwargs") or {}).get("k", kwargs.get("k", 3)))
        return FakeRetriever(self.docs, k=k)

    def similarity_search(self, query, k: int = 3, **kwargs):
        return self.docs[:k]


def make_docs(items):
    """(id, text, metadata) 튜플 목록으로 Document 리스트를 만듭니다."""
    from langchain_core.documents import Document

    out = []
    for doc_id, text, meta in items:
        md = {"doc_id": doc_id}
        md.update(meta or {})
        out.append(Document(page_content=text, metadata=md))
    return out
