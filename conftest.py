"""저장소 공통 pytest 설정.

학생용 공개 테스트(dayNN/tests/)와 채점기(grader/) 양쪽에서 쓰는 도우미입니다.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent


def load_submission(day: int) -> ModuleType:
    """dayNN/practice/starter/submission.py 를 독립 모듈로 불러옵니다."""
    path = ROOT / f"day{day:02d}" / "practice" / "starter" / "submission.py"
    if not path.exists():
        pytest.fail(f"제출 파일이 없습니다: day{day:02d}/practice/starter/submission.py")

    name = f"_submission_day{day:02d}"
    sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001
        pytest.fail(
            f"submission.py 를 불러오는 중 오류가 났습니다.\n"
            f"  {type(exc).__name__}: {exc}\n"
            f"  모듈 최상단에서 모델이나 외부 자원을 만들고 있지 않은지 확인하세요."
        )
    return module


def need(module: ModuleType, name: str):
    """제출물에 필요한 이름이 있는지 확인하고 꺼냅니다."""
    if not hasattr(module, name):
        pytest.fail(
            f"`{name}` 이(가) submission.py 에 없습니다.\n"
            f"  starter 파일의 이름과 시그니처를 그대로 유지하세요."
        )
    return getattr(module, name)


def load_eval_set() -> list[dict]:
    """루트에 누적되는 정본 평가셋입니다."""
    path = ROOT / "eval_set.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        pytest.fail(f"eval_set.json 이 올바른 JSON이 아닙니다: {exc}")
    return data if isinstance(data, list) else data.get("items", [])


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "points(value): 테스트 통과 시 부여할 점수")
    config.addinivalue_line("markers", "advanced: 심화 파트. 통과 판정에 포함하지 않음")
