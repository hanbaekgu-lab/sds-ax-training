# SDS AX 교육 저장소 작업 지침

## 디렉터리
- Day 폴더는 `day01`부터 `day10`까지 두 자리 숫자를 씁니다.
- 학생 제출 진입점은 `dayNN/practice/starter/submission.py` 하나로 고정합니다.
- `dayNN/tests/`는 **학생 자가 확인용 공개 테스트**입니다.
- `grader/`는 **실제 채점용이며 학생 배포본에 포함하지 않습니다.**

## 기술 스택 (고정 — 임의 변경 금지)
- LLM: `us.anthropic.claude-sonnet-4-5-20250929-v1:0` (Amazon Bedrock)
- 임베딩: `amazon.titan-embed-text-v2:0` (1024차원)
- 리전: `us-east-1`
- 벡터DB: Chroma, `persist_directory="./chroma_db"`, `collection_name="sds_policies"`
- 체크포인터: `SqliteSaver` / `AsyncSqliteSaver`, 파일명 `checkpoints.sqlite`

## 코드 규약
- 교육용 코드의 주석과 문서는 **한국어로 상세하게** 씁니다.
- 학생 제출 파일은 **모듈 최상단에서 실제 모델을 만들지 않습니다.**
  모델 생성은 반드시 함수 안에서 하고, `llm=None` 인자를 받아 주입 가능하게 둡니다.
  채점기가 가짜 모델을 꽂아 실호출 없이 배선을 검증하기 때문입니다.
- 채점 테스트는 **실제 LLM API를 호출하지 않습니다.** 고정 입력과 가짜 모델만 씁니다.
- 교육용 더미 데이터에는 "교육용 더미 데이터입니다"를 명시합니다.
- 실제 API 키나 정답 코드를 학생 배포 저장소에 커밋하지 않습니다.

## 배점
- Day당 만점 10점. `pass_score`(기본 7점) 이상이면 통과입니다.
- 기초 파트 7점 + 심화 파트 3점 구성이며, **심화 실패는 통과 여부를 바꾸지 않습니다.**
- 테스트의 points 합계는 `grading/dayNN.json`의 `max_score`와 같아야 합니다.
