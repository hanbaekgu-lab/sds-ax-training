# Day 8~10. Mini PJT

[← 전체 미션 맵](../README.md)  ·  [← Day 7](../day07/README.md)

> 3일간 본인이 맡은 업무의 반복 작업을 Agent로 만듭니다. 자동채점과 라이브 시연을 함께 봅니다.

이 구간에서는 `submission.py` 한 파일이 아니라 돌아가는 서비스 한 벌을 냅니다.
자세한 요건과 채점 기준은 Day7이 끝날 때 강사가 따로 안내합니다.

## 제출 위치

```
miniprj/
├── README.md        주제 · 설계 · 핵심 의사결정 2가지
├── app.py           POST /query 진입점
└── eval_set.json    20문항 이상 (no_answer 2+, guardrail 2+)
```

## 커밋 규칙

```bash
git commit -m "[제출] MiniPJT"
```

## Day 8 오전에 먼저 하는 일

**코드보다 평가셋을 먼저 씁니다.** 7일간 쌓아 온 "됐는지 판정하는 능력"을 여기서 꺼내 쓰게 됩니다.
Day8이 끝날 때 "제안 + 스켈레톤 push"를 올려야 다음 날로 넘어갑니다. 점수에는 들어가지 않지만 건너뛸 수 없는 관문입니다.
