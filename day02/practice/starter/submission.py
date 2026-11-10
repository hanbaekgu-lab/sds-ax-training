"""Day 2 — 런북 RAG와 평가셋.

문서를 인덱싱하고, 질문에 근거와 함께 답합니다.

[중요] 이 파일의 규칙
  1. 함수 이름과 인자를 바꾸지 마세요.
  2. 모델·임베딩은 반드시 함수 **안에서** 만듭니다.
  3. `llm` 인자가 들어오면 그것을 씁니다. 채점기가 가짜 모델을 넣습니다.
  4. `build_retriever`와 `build_rag_chain`은 **주어진 vectorstore/retriever를 그대로 씁니다.**
     함수 안에서 새로 인덱싱하지 마세요.

[구성]
  - build_chunks      : 원본 Document에 메타데이터 3키를 먼저 붙이고 → 마크다운 구조 따라 분할
  - build_retriever   : as_retriever(k=4)
  - build_rag_chain   : 검색 → assess_retrieval 게이트 → (통과 시) 프롬프트 주입 → 모델 → 출처 첨부
  - assess_retrieval  : LLM 없이 질문 핵심어가 본문에 몇 개 등장하는지로 결정적 판정
                        (Kiwi 형태소 분석으로 핵심어 추출 + 동의어 표, Kiwi가 없으면 정규식)
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
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

# 문서별 메타데이터 표입니다. (교육용 더미 데이터입니다)
#   - 실습 문서 본문에는 담당 조직·수정일이 적혀 있지 않으므로, 문서 관리 대장에 해당하는
#     표를 코드에 둡니다. 운영에서는 이 값이 문서 저장소(Confluence 등)의 속성에서 옵니다.
#   - department: "이 답 이상한데요"를 보낼 곳.  updated_at: 폐기된 런북을 걸러낼 단서.
DOC_METADATA: dict[str, dict[str, str]] = {
    "incident_runbook.md": {"department": "sre", "updated_at": "2026-05-12"},
    "leave_policy.md": {"department": "people", "updated_at": "2026-03-02"},
    "oncall_policy.md": {"department": "sre", "updated_at": "2026-06-30"},
}

# 표에 없는 문서가 들어왔을 때 쓰는 담당 조직입니다.
#   빈 값으로 두면 "담당 불명" 청크가 조용히 섞이므로, 눈에 띄는 값으로 채워 둡니다.
UNKNOWN_DEPARTMENT = "unassigned"

# 청크 크기 설정입니다.
#   - 실습 문서의 절(## 단위)은 대략 300~600자입니다. 500자면 절 하나가 대체로 한 청크가 되고,
#     문서 하나는 여러 청크로 나뉩니다. 800자를 넘기면 문서 통째로 한 청크가 되는 경우가 생겨
#     질문과 무관한 절까지 컨텍스트로 딸려 들어갑니다.
#   - overlap 50자: 절 경계에서 잘린 문장의 앞뒤 맥락을 조금 이어 줍니다.
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50

# 분할 우선순위입니다. 마크다운 절 제목(##) → 문단(빈 줄) → 줄 → 공백 순으로 자릅니다.
#   고정 길이로 자르면 "롤백 기준" 문장이 중간에 끊겨 검색에도 답변에도 쓸 수 없게 됩니다.
MARKDOWN_SEPARATORS = ["\n## ", "\n### ", "\n\n", "\n", " ", ""]


def _metadata_for(path) -> dict[str, str]:
    """파일 경로에서 청크가 상속받을 메타데이터 3키(source/department/updated_at)를 만듭니다."""
    import datetime as _dt

    p = Path(path)
    known = DOC_METADATA.get(p.name)
    if known:
        return {"source": p.name, **known}

    # 표에 없는 문서: 파일 수정 시각을 updated_at으로 씁니다. (YYYY-MM-DD)
    try:
        updated = _dt.date.fromtimestamp(p.stat().st_mtime).isoformat()
    except OSError:
        updated = "1970-01-01"
    return {"source": p.name, "department": UNKNOWN_DEPARTMENT, "updated_at": updated}


def build_chunks(doc_paths: list[str]) -> list:
    """문서를 읽어 청크 Document 리스트를 만듭니다.

    순서가 핵심입니다.
      1) 원본 문서 전체를 Document로 만들면서 metadata 3키를 **먼저** 붙입니다.
      2) 그 Document를 split_documents로 나눕니다.
         → splitter가 원본 metadata를 각 청크에 복사하므로 모든 청크가 3키를 상속합니다.
    반대로 문자열을 먼저 split_text로 자른 뒤 metadata를 붙이려 하면, 붙이는 걸 잊어도
    오류가 나지 않아 운영에서 "출처 없는 답"을 보고서야 알게 됩니다.

    Args:
        doc_paths: 읽을 마크다운 파일 경로 목록

    Returns:
        langchain_core.documents.Document 의 리스트
    """
    from langchain_core.documents import Document
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    # 1) 메타데이터를 붙인 원본 Document (분할 전)
    originals = []
    for path in doc_paths:
        text = Path(path).read_text(encoding="utf-8")
        if not text.strip():
            continue  # 빈 파일은 검색에 걸리기만 하고 쓸모가 없습니다.
        originals.append(Document(page_content=text, metadata=_metadata_for(path)))

    # 2) 분할: 원본 metadata가 청크마다 복사됩니다.
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=MARKDOWN_SEPARATORS,
    )
    chunks = splitter.split_documents(originals)

    # 안전장치: 3키가 빠진 청크가 있으면 여기서 바로 실패시킵니다.
    #   조용히 넘어가면 운영에서 출처가 빈 답을 받게 됩니다.
    required = {"source", "department", "updated_at"}
    for i, c in enumerate(chunks):
        missing = required - set(c.metadata)
        if missing:
            raise ValueError(f"{i}번째 청크에 메타데이터 {sorted(missing)}가 없습니다.")
    return chunks


def build_vectorstore(chunks, embeddings=None):
    """청크를 Chroma에 인덱싱합니다. (채점 대상 아님 — 실제 실행용 보조 함수)

    과정 고정값(persist_directory, collection_name)을 그대로 씁니다.
    임베딩 모델도 함수 안에서 만들어, 모듈을 불러오기만 해서는 AWS를 부르지 않게 합니다.
    """
    from langchain_chroma import Chroma

    return Chroma.from_documents(
        documents=chunks,
        embedding=embeddings or _default_embeddings(),
        persist_directory=PERSIST_DIR,
        collection_name=COLLECTION,
    )


# 검색 개수입니다.
#   k=4: 문서 3개를 나눈 청크 중 상위 4개. 한 절의 답이 두 청크에 걸쳐 잘린 경우(overlap 경계)까지
#   담을 수 있는 최소값이면서, 그보다 늘리면 무관한 런북(예: 롤백 질문에 온콜 인수인계 절)이
#   컨텍스트의 절반을 넘기 시작합니다.
RETRIEVER_K = 4


def build_retriever(vectorstore):
    """주어진 벡터저장소에서 retriever를 만듭니다.

    여기서 새로 인덱싱하지 않습니다. 인자로 받은 vectorstore를 그대로 씁니다.
    """
    return vectorstore.as_retriever(search_type="similarity", search_kwargs={"k": RETRIEVER_K})


# 프롬프트에 넣을 질문의 최대 길이입니다.
#   "연차 연차 연차 ..." 같은 수천 자 질문이 들어와도 토큰이 폭주하지 않게 자릅니다.
MAX_QUESTION_CHARS = 1000

# RAG 답변 프롬프트입니다.
#   - system: 근거 밖의 지식을 쓰지 말 것, 모르면 정해진 문구로 거절할 것.
#   - human : {context}에 format_docs 결과(출처 꼬리표 + 본문)를, {question}에 질문을 넣습니다.
#   ChatPromptTemplate은 변수 '값' 안의 중괄호를 다시 해석하지 않으므로
#   '{"q": 1}' 같은 질문이 들어와도 템플릿이 깨지지 않습니다.
RAG_SYSTEM = (
    "너는 사내 규정·런북 안내 도우미다. 반드시 아래 <근거> 안의 문서 내용만 사용해 답한다.\n"
    "- 근거에 없는 내용은 추측하지 말고 정확히 '제공된 문서에서 답을 찾을 수 없습니다.'라고만 답한다.\n"
    "- 숫자·기한·조건은 근거 문장 그대로 옮긴다.\n"
    "- 답은 한국어로 2~3문장 이내로 쓴다."
)
RAG_HUMAN = "<근거>\n{context}\n</근거>\n\n질문: {question}"


def _unique_sources(docs) -> list[str]:
    """검색된 문서의 metadata['source']를 순서를 지키며 중복 없이 뽑습니다.

    지어낸 파일명이 섞이지 않도록 오직 검색 결과의 metadata에서만 가져옵니다.
    """
    seen: list[str] = []
    for d in docs:
        src = (getattr(d, "metadata", None) or {}).get("source")
        if src and src not in seen:
            seen.append(src)
    return seen


def _refusal() -> dict:
    """거절 응답. 상수 NO_ANSWER를 그대로 주면 호출자가 수정할 때 원본까지 바뀌므로 복사본을 줍니다."""
    return {"answer": NO_ANSWER["answer"], "sources": []}


def build_rag_chain(retriever, llm=None):
    """질문 문자열을 받아 {"answer": str, "sources": list[str]} 를 반환하는 체인을 만듭니다.

    흐름:
      질문 → retriever.invoke → assess_retrieval(게이트)
           ├─ usable=False → 모델 호출 없이 거절 응답 반환
           └─ usable=True  → format_docs → 프롬프트 → llm → 답 + 검색 결과의 sources
    """
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.runnables import RunnableLambda

    llm = llm or _default_llm()
    prompt = ChatPromptTemplate.from_messages([("system", RAG_SYSTEM), ("human", RAG_HUMAN)])
    answer_chain = prompt | llm

    def _run(question: Any) -> dict:
        # 체인 입력이 {"question": ...} dict로 들어와도 동작하게 질문 문자열만 꺼냅니다.
        if isinstance(question, dict):
            question = question.get("question", "")
        question = str(question or "").strip()[:MAX_QUESTION_CHARS]

        # 빈 질문은 검색할 것이 없으므로 바로 거절합니다. (빈 문자열 임베딩 호출도 막습니다)
        if not question:
            return _refusal()

        docs = list(retriever.invoke(question) or [])

        # 심화: 모델을 부르기 전에 검색 결과부터 판정합니다.
        #   근거가 쓸모없으면 모델에게 묻지 않습니다. 물으면 어떻게든 그럴듯한 답을 만들어 냅니다.
        verdict = assess_retrieval(docs, question)
        if not verdict["usable"]:
            return _refusal()

        message = answer_chain.invoke({"context": format_docs(docs), "question": question})
        answer = get_text(message).strip()

        # 모델이 근거 부족으로 스스로 거절했다면 출처를 붙이지 않습니다.
        #   "찾을 수 없습니다" 답에 leave_policy.md가 붙어 있으면 사람이 원문을 괜히 열어 보게 됩니다.
        if not answer or "찾을 수 없" in answer:
            return _refusal()

        return {"answer": answer, "sources": _unique_sources(docs)}

    return RunnableLambda(_run)


# ══════════════════════════════════════════════════════════════════
# 심화 파트 (3점) — 못 해도 과제는 통과합니다
# ══════════════════════════════════════════════════════════════════

# 질문에서 핵심어를 뽑을 때 버리는 말입니다. 어느 문서에나 맞을 수 있는 의문사·서술어입니다.
STOPWORDS = {
    "어떻게", "무엇", "무엇인가요", "뭔가요", "언제", "어디", "얼마", "얼마나", "며칠",
    "있나요", "있습니까", "되나요", "됩니까", "인가요", "하나요", "합니까", "할까요", "해도",
    "되는", "하는", "있는", "알려", "주세요", "궁금합니다", "지금", "그리고", "혹은",
    # 사내 규정 문서라면 어디에나 나오는 일반 명사입니다. 이 단어들로 "맞았다"고 세면
    # "사내 헬스장 운영 시간"이 온콜 규정의 "운영"·"대응 시간"에 걸려 통과해 버립니다.
    "사내", "회사", "운영", "시간", "규정", "정책", "방법", "기준", "경우", "관련", "다음",
}

# 핵심어 끝에 붙은 조사·어미입니다. 긴 것부터 떼어 "연차는"→"연차", "이월되나요"→"이월".
SUFFIXES = sorted(
    [
        "되나요", "하나요", "인가요", "있나요", "됩니까", "합니까", "할까요", "해도", "하면",
        "에서는", "에서", "에게", "까지", "부터", "으로", "이나", "하고",
        "은", "는", "이", "가", "을", "를", "의", "에", "도", "로", "와", "과", "만", "요",
    ],
    key=len,
    reverse=True,
)

# 영어 질문에서 버리는 기능어입니다. Kiwi는 영어 단어를 SL(외국어)로 그대로 넘겨주므로
#   "What is the ..."의 is/the까지 핵심어가 되지 않게 따로 거릅니다.
STOPWORDS |= {"what", "is", "the", "how", "when", "where", "can", "do", "does", "of", "to", "in"}

# 동의어 묶음입니다. (교육용 더미 데이터입니다 — 실습 문서 3개에 맞춰 고른 최소 목록)
#   형태소 분석은 "대응했으면"→"대응"처럼 **표기 차이**를 정리할 뿐,
#   "에러"와 "오류"처럼 **글자가 아예 다른 같은 뜻**은 이어 주지 못합니다.
#   paraphrase 질문은 대부분 이쪽에서 떨어지므로, 같은 묶음 안의 어느 말이든 본문에 있으면 일치로 봅니다.
#   - 묶음 첫 단어가 대표어이고, reason에도 질문에 나온 단어 그대로 표시합니다.
#   - 동사 어간("되돌리")과 한 글자 명사("밤")는 원래 버리지만, 이 표에 있으면 핵심어로 살립니다.
#   - 너무 넓은 말("장애", "문제")은 넣지 않습니다. 넣는 순간 무관한 런북이 모두 통과합니다.
SYNONYM_GROUPS: list[tuple[str, ...]] = [
    ("오류", "에러", "error"),
    ("롤백", "되돌리", "원복", "rollback"),
    ("연차", "휴가", "월차"),  # "월차"는 엄밀히 다른 제도지만, 현장에서는 연차를 흔히 이렇게 부릅니다.
    ("야간", "밤", "심야"),
    ("근무", "출근"),
]
_SYNONYMS: dict[str, tuple[str, ...]] = {
    form: group for group in SYNONYM_GROUPS for form in group
}

# Kiwi 사전에 없어 잘못 쪼개지는 사내 용어입니다. (등록하지 않으면 "온콜" → "온" + "콜")
KIWI_USER_WORDS = ["온콜", "롤백"]

# 핵심어로 남길 품사입니다.
#   NNG 일반명사, NNP 고유명사, SL 외국어, SN 숫자, XR 어근.
#   동사·형용사(되, 있, 쓰 …)는 어느 문서에나 나오므로 남기면 "사내 헬스장 운영 시간"도
#   통과해 버립니다. 그래서 명사 계열만 남기고, 동사는 동의어 표에 있을 때만 살립니다.
_NOUN_TAGS = {"NNG", "NNP", "SL", "SN", "XR"}

# 판정 임계값입니다. 핵심어의 30% 이상(최소 1개)이 검색된 본문에 등장해야 "쓸 만하다"고 봅니다.
#   - 흔한 일반 명사는 STOPWORDS에서, 조사·어미·동사는 형태소 분석으로 미리 빼 두었으므로
#     남은 핵심어는 대부분 질문의 주제어입니다. 그중 1/3이 맞으면 같은 주제로 봅니다.
#   - 동의어 표 덕분에 paraphrase도 이 비율을 넘깁니다. 표에 없는 바꿔 말하기는 여전히
#     거절될 수 있으므로, 평가셋으로 이 값과 동의어 표를 계속 확인합니다.
MIN_MATCH_RATIO = 0.3


@lru_cache(maxsize=1)
def _kiwi():
    """Kiwi 형태소 분석기를 처음 쓸 때 한 번만 만듭니다. 쓸 수 없으면 None을 돌려줍니다.

    - 모듈 최상단에서 만들지 않습니다. 모델 파일을 읽는 데 1초 가까이 걸리고,
      채점기가 모듈을 불러오기만 해도 그 비용을 치르게 되기 때문입니다.
    - kiwipiepy가 설치되지 않은 환경에서도 과제가 깨지지 않도록 실패하면 None을 주고,
      호출하는 쪽은 정규식 방식으로 돌아갑니다.
    """
    try:
        from kiwipiepy import Kiwi

        kiwi = Kiwi()
        for word in KIWI_USER_WORDS:
            kiwi.add_user_word(word, "NNP")
        return kiwi
    except Exception:  # noqa: BLE001 — 설치 안 됨·모델 로드 실패 모두 대체 경로로 보냅니다.
        return None


def _keywords(question: str) -> list[str]:
    """질문에서 핵심어를 결정적으로 뽑습니다. (같은 질문 → 항상 같은 순서의 같은 목록)

    Kiwi가 있으면 형태소 분석으로, 없으면 정규식 + 조사 떼기로 뽑습니다.
    Kiwi 결과는 같은 버전·같은 입력이면 항상 같으므로 결정성 조건을 지킵니다.
    """
    kiwi = _kiwi()
    if kiwi is None:
        return _keywords_regex(question)

    result: list[str] = []
    for token in kiwi.tokenize(question or ""):
        form = token.form.lower()
        if form in _SYNONYMS:
            keep = True  # 동의어 표에 있으면 품사·길이와 관계없이 살립니다. ("되돌리", "밤")
        else:
            keep = (
                token.tag in _NOUN_TAGS
                and len(form) >= 2  # 한 글자 명사("해", "날")는 거의 모든 문서에 등장합니다.
                and form not in STOPWORDS
            )
        if keep and form not in result:
            result.append(form)
    return result


def _keywords_regex(question: str) -> list[str]:
    """Kiwi를 쓸 수 없을 때의 대체 경로입니다. 공백으로 자르고 끝의 조사·어미를 뗍니다."""
    result: list[str] = []
    for w in re.findall(r"[0-9A-Za-z가-힣]+", question or ""):
        w = w.lower()
        if w in STOPWORDS:
            continue
        for suf in SUFFIXES:
            # 어간이 2자 이상 남을 때만 뗍니다. ("이월"의 "이"를 조사로 오인하지 않도록)
            if w.endswith(suf) and len(w) - len(suf) >= 2:
                w = w[: -len(suf)]
                break
        if len(w) < 2 or w in STOPWORDS:
            continue  # 한 글자는 거의 모든 문서에 등장하므로 판정에 쓰지 않습니다.
        if w not in result:
            result.append(w)
    return result


def assess_retrieval(docs, question: str) -> dict:
    """검색 결과가 이 질문에 답하기에 쓸만한지 판정합니다. (LLM 호출 없음, 결정적)

    방법: 질문의 핵심어 중 몇 개가 검색된 본문 어딘가에 등장하는지 셉니다.
      - 검색 결과가 비었다           → usable=False
      - 핵심어를 하나도 못 뽑았다      → usable=False (빈 질문·기호만 있는 질문)
      - 등장 비율 < MIN_MATCH_RATIO  → usable=False
      - 그 외                         → usable=True

    Returns:
        {"usable": bool, "reason": str, "matched": int}
    """
    docs = list(docs or [])
    if not docs:
        return {"usable": False, "reason": "검색 결과가 없습니다.", "matched": 0}

    keywords = _keywords(question)
    if not keywords:
        return {"usable": False, "reason": "질문에서 핵심어를 찾지 못했습니다.", "matched": 0}

    # 본문은 형태소 분석 없이 부분 문자열로 찾습니다.
    #   질문 쪽을 이미 기본형("대응", "오류")으로 줄여 두었으므로 "대응한", "오류율" 안에서도 잡힙니다.
    #   본문까지 분석하면 검색 결과가 바뀔 때마다 비용이 들고, 얻는 것은 거의 없습니다.
    body = " ".join(getattr(d, "page_content", "") or "" for d in docs).lower()
    hits = [
        k for k in keywords
        if any(form in body for form in _SYNONYMS.get(k, (k,)))
    ]
    matched = len(hits)
    usable = matched >= 1 and matched / len(keywords) >= MIN_MATCH_RATIO

    reason = f"질의어 {len(keywords)}개 중 {matched}개가 본문에 등장"
    if hits:
        reason += f" ({', '.join(hits)})"
    if not usable:
        reason += f" — 기준 {int(MIN_MATCH_RATIO * 100)}% 미달"
    return {"usable": usable, "reason": reason, "matched": matched}


NO_ANSWER = {
    "answer": "제공된 문서에서 답을 찾을 수 없습니다.",
    "sources": [],
}


if __name__ == "__main__":
    # 실제 Bedrock으로 한 번 돌려 보는 진입점입니다. (채점기는 이 블록을 실행하지 않습니다)
    #   python day02/practice/starter/submission.py
    docs_dir = Path(__file__).resolve().parents[1] / "docs"
    chunks = build_chunks(sorted(str(p) for p in docs_dir.glob("*.md")))
    print(f"청크 {len(chunks)}개 생성")
    chain = build_rag_chain(build_retriever(build_vectorstore(chunks)))
    for q in ["지금 롤백해도 되나요?", "연차는 며칠까지 이월되나요?", "사내 헬스장 운영 시간은?"]:
        print(q, "→", chain.invoke(q))
