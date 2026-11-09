# 수강생 제출 가이드

## 제출 규칙

```bash
python scripts/grade.py --day N     # 먼저 로컬 확인
git add dayNN/ eval_set.json
git commit -m "[제출] DayN"          # 첫 줄이 이 형식이어야 채점됩니다
git push
```

| 제출 종류 | 커밋 메시지 첫 줄 |
|---|---|
| 기초·심화 과제 | `[제출] Day3` |
| Mini PJT | `[제출] MiniPJT` |

작업 중 커밋은 아무 문구나 써도 됩니다. 채점기가 지나갑니다.

## 채점 결과 읽는 법

```
- 점수: **8 / 10**  (기초 7/7, 통과선 7점)
- 심화 파트: **1/3**  (통과 여부에는 영향 없음)
```

**기초 7점을 채우면 통과입니다.** 심화는 못 해도 됩니다.
실패한 테스트 이름이 무엇을 못 했는지 알려 줍니다. 이름을 먼저 보세요.

## 재제출

Day 마감까지 몇 번이든 다시 낼 수 있습니다. **마지막 제출로 판정합니다.**

## 자기 테스트를 쓰고 싶다면

`sds_testkit.py`에 채점기와 같은 도구가 들어 있습니다.

```python
from sds_testkit import ScriptedChatModel, FakeVectorStore, make_docs

llm = ScriptedChatModel(responses=['{"severity": "P1"}'])
chain = build_triage_chain(llm)
chain.invoke(alert)
assert "severity" in llm.prompt_text()      # 모델에게 무엇이 갔는지 확인
```

실제 Bedrock을 부르지 않으므로 비용이 들지 않고 결과가 매번 같습니다.

## 주의

- `.env`, API 키, 비밀번호를 커밋하지 않습니다.
- `dayNN/tests/` 를 고쳐서 통과시키지 마세요. 실제 채점은 별도 테스트로 합니다.
- `eval_set.json`은 **루트에 하나**입니다. Day마다 새로 만들지 말고 덧붙이세요.
