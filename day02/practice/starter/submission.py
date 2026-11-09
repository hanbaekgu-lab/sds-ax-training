"""Day 2 — 런북 RAG와 평가셋.

문서를 인덱싱하고, 질문에 근거와 함께 답합니다.

[중요] 이 파일의 규칙
  1. 함수 이름과 인자를 바꾸지 마세요.
  2. 모델·임베딩은 반드시 함수 **안에서** 만듭니다.
  3. `llm` 인자가 들어오면 그것을 씁니다. 채점기가 가짜 모델을 넣습니다.
  4. `build_retriever`와 `build_rag_chain`은 **주어진 vectorstore/retriever를 그대로 씁니다.**
     함수 안에서 새로 인덱싱하지 마세요.
"""

from __future__ import annotations

from typing import Any

MODEL_ID = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
EMBED_MODEL_ID = "amazon.titan-embed-text-v2:0"
REGION = "us-east-1"

PERSIST_DIR = "./chroma_db"
COLLECTION = "sds_policies"


def _default_llm():
    from langchain_aws import ChatBedrockConverse

    return ChatBedrockConverse(model=MODEL_ID, region_name=REGION, temperature=0)


def _default_embeddings():
    from langchain_aws import BedrockEmbeddings

    return BedrockEmbeddings(model_id=EMBED_MODEL_ID, region_name=REGION)


def get_text(message: Any) -> str:
    """ChatBedrockConverse는 content를 블록 리스트로 주기도 하므로 텍스트만 모아 반환합니다."""
    content = message.content if hasattr(message, "content") else message
    if isinstance(content, list):
        return "".join(
            block.get("text", "") for block in content if isinstance(block, dict)
        )
    return str(content)


def format_docs(docs) -> str:
    """검색된 문서를 프롬프트에 넣을 문자열로 만듭니다."""
    return "\n\n".join(
        f"[출처: {d.metadata.get('source', '알 수 없음')}]\n{d.page_content}" for d in docs
    )


# ══════════════════════════════════════════════════════════════════
# 기초 파트 (7점)
# ══════════════════════════════════════════════════════════════════

def build_chunks(doc_paths: list[str]) -> list:
    """문서를 읽어 청크 Document 리스트를 만듭니다.

    반드시 지킬 것:
      - 모든 청크 metadata에 source / department / updated_at 세 키가 있어야 합니다.
      - 메타데이터는 **분할하기 전에** 붙여야 상속됩니다.
      - 고정 길이로 자르지 말고 RecursiveCharacterTextSplitter 또는
        MarkdownHeaderTextSplitter를 쓰세요.

    Args:
        doc_paths: 읽을 마크다운 파일 경로 목록

    Returns:
        langchain_core.documents.Document 의 리스트
    """
    # TODO: 구현하세요.
    #   1) 파일을 읽어 Document를 만들고 metadata 3키를 붙입니다.
    #   2) splitter로 분할합니다. (분할 후에는 metadata가 자동 상속됩니다)
    raise NotImplementedError("build_chunks 를 구현하세요.")


def build_retriever(vectorstore):
    """주어진 벡터저장소에서 retriever를 만듭니다.

    여기서 새로 인덱싱하지 마세요. 인자로 받은 vectorstore를 그대로 씁니다.
    k 값은 직접 정하고, 왜 그 값인지 주석으로 남기세요.
    """
    # TODO: vectorstore.as_retriever(...) 를 반환하세요.
    raise NotImplementedError("build_retriever 를 구현하세요.")


def build_rag_chain(retriever, llm=None):
    """질문 문자열을 받아 {"answer": str, "sources": list[str]} 를 반환하는 체인을 만듭니다.

    반드시 지킬 것:
      - 검색된 문서 본문을 프롬프트에 실제로 넣어야 합니다.
      - sources는 실제 검색 결과의 metadata에서 뽑습니다. 지어내면 안 됩니다.

    심화 파트를 구현했다면 assess_retrieval 판정을 거쳐야 합니다.
    """
    llm = llm or _default_llm()

    # TODO: 구현하세요.
    #   retriever.invoke(question) -> format_docs -> prompt -> llm -> 파싱
    #   반환은 반드시 {"answer": ..., "sources": [...]} 형태의 dict 입니다.
    #   RunnableLambda로 함수 하나를 감싸는 방식이 가장 간단합니다.
    raise NotImplementedError("build_rag_chain 을 구현하세요.")


# ══════════════════════════════════════════════════════════════════
# 심화 파트 (3점) — 못 해도 과제는 통과합니다
# ══════════════════════════════════════════════════════════════════

def assess_retrieval(docs, question: str) -> dict:
    """검색 결과가 이 질문에 답하기에 쓸만한지 판정합니다.

    이 함수는 LLM을 호출하지 않습니다. 같은 입력에 항상 같은 출력을 내야 합니다.

    판정 방법은 자유입니다. 예를 들면
      - 질문에서 핵심어를 뽑아 문서 본문에 몇 개나 등장하는지 센다
      - 검색된 문서 개수와 길이를 본다
      - 특정 임계값을 넘는지 확인한다

    Returns:
        {"usable": bool, "reason": str, "matched": int} 형태의 dict.
        usable이 False면 build_rag_chain은 모델을 부르지 않고 거절해야 합니다.
    """
    # TODO: 구현하세요.
    raise NotImplementedError("assess_retrieval 을 구현하세요.")


NO_ANSWER = {
    "answer": "제공된 문서에서 답을 찾을 수 없습니다.",
    "sources": [],
}
