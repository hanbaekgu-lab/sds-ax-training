"""일차별 pytest 결과와 배점을 계산하는 자동 채점 실행기입니다."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[1]


def normalize_day(value: str) -> str:
    """`1`, `01`, `day01` 입력을 채점 설정에서 사용하는 `01`로 통일합니다."""
    normalized = value.lower().removeprefix("day")
    if not normalized.isdigit() or not 1 <= int(normalized) <= 10:
        raise argparse.ArgumentTypeError("Day는 1부터 10 사이여야 합니다.")
    return f"{int(normalized):02d}"


@dataclass(eq=False)
class GradePlugin:
    """pytest hook에서 테스트별 points marker와 실행 결과를 수집합니다."""

    max_points: float = 0
    earned_points: float = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    collected: int = 0
    advanced_max: float = 0
    advanced_earned: float = 0
    _points_by_node: dict[str, float] = field(default_factory=dict)
    _advanced_nodes: set[str] = field(default_factory=set)
    _finished_nodes: set[str] = field(default_factory=set)

    def pytest_collection_modifyitems(self, items: list[pytest.Item]) -> None:
        self.collected = len(items)
        for item in items:
            marker = item.get_closest_marker("points")
            points = float(marker.args[0]) if marker and marker.args else 0
            if points < 0:
                raise pytest.UsageError(f"음수 배점은 사용할 수 없습니다: {item.nodeid}")
            self._points_by_node[item.nodeid] = points
            self.max_points += points
            # 심화 표시가 붙은 테스트는 따로 집계합니다. 통과 판정에는 넣지 않습니다.
            if item.get_closest_marker("advanced") is not None:
                self._advanced_nodes.add(item.nodeid)
                self.advanced_max += points

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        # 일반 테스트는 call 단계에서, setup 실패는 setup 단계에서 한 번만 집계합니다.
        if report.nodeid in self._finished_nodes:
            return
        if report.when == "setup":
            if report.failed:
                self.failed += 1
                self._finished_nodes.add(report.nodeid)
            elif report.skipped:
                self.skipped += 1
                self._finished_nodes.add(report.nodeid)
            return
        if report.when != "call":
            return

        self._finished_nodes.add(report.nodeid)
        if report.passed:
            self.passed += 1
            gained = self._points_by_node.get(report.nodeid, 0)
            self.earned_points += gained
            if report.nodeid in self._advanced_nodes:
                self.advanced_earned += gained
        elif report.skipped:
            self.skipped += 1
        else:
            self.failed += 1


def load_config(day: str) -> dict[str, Any]:
    """일차별 활성화 상태와 만점을 읽고 필수 값을 검증합니다."""
    config_path = ROOT / "grading" / f"day{day}.json"
    if not config_path.exists():
        raise FileNotFoundError(f"채점 설정을 찾을 수 없습니다: {config_path}")

    config = json.loads(config_path.read_text(encoding="utf-8"))
    if config.get("status") not in {"draft", "active"}:
        raise ValueError("status는 draft 또는 active여야 합니다.")
    if not isinstance(config.get("max_score"), (int, float)) or config["max_score"] <= 0:
        raise ValueError("max_score는 0보다 큰 숫자여야 합니다.")

    # pass_score를 두지 않으면 만점을 받아야 통과합니다.
    # 기초 7점 + 심화 3점 구성에서는 pass_score를 7로 두어
    # 심화를 못 해도 통과하도록 합니다.
    pass_score = config.get("pass_score", config["max_score"])
    if not isinstance(pass_score, (int, float)) or not 0 < pass_score <= config["max_score"]:
        raise ValueError("pass_score는 0보다 크고 max_score 이하인 숫자여야 합니다.")
    config["pass_score"] = pass_score
    return config


def append_step_summary(content: str) -> None:
    """GitHub Actions에서 채점 결과를 Job Summary에 추가합니다."""
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with Path(summary_path).open("a", encoding="utf-8") as summary_file:
            summary_file.write(content + "\n")


def grade(day: str, force: bool = False, grader: bool = False) -> int:
    config = load_config(day)
    title = config.get("title", f"Day {int(day)}")
    if grader:
        title += " (채점기)"

    if config["status"] == "draft" and not force:
        message = (
            f"## {title} 채점\n\n"
            "> 🚧 아직 채점 대상이 아닙니다. **테스트가 한 개도 실행되지 않았습니다.**"
        )
        print(message)
        append_step_summary(message)
        return 4   # exit 0(통과)과 반드시 구분되어야 합니다

    # 학생 자가 확인은 dayNN/tests, 실제 채점은 grader/dayNN 을 실행합니다.
    tests_path = (ROOT / "grader" / f"day{day}") if grader else (ROOT / f"day{day}" / "tests")
    if not tests_path.exists():
        message = (
            f"## {title} 채점\n\n"
            f"> 테스트 디렉터리가 없습니다: `{tests_path.relative_to(ROOT)}`"
        )
        print(message)
        append_step_summary(message)
        return 3

    plugin = GradePlugin()
    args = [str(tests_path), "-q", "-p", "no:cacheprovider"]
    if grader:
        # 학생 레포의 로컬 pytest 설정이 채점에 끼어들지 못하게 막습니다.
        # 학생 레포의 conftest.py / pytest.ini 가 채점에 끼어들지 못하게 막습니다.
        args += ["--rootdir", str(ROOT),
                 "--confcutdir", str(ROOT / "grader"),
                 "-p", "no:randomly"]
    pytest_exit_code = int(pytest.main(args, plugins=[plugin]))

    expected_max = float(config["max_score"])
    pass_score = float(config["pass_score"])
    config_valid = plugin.max_points == expected_max
    score = plugin.earned_points if config_valid else 0
    tests_complete = plugin.collected > 0 and plugin.skipped == 0

    # 통과 판정은 pytest 종료 코드가 아니라 **기초 파트 점수**로 합니다.
    # 심화를 다 맞아도 기초가 모자라면 통과가 아닙니다.
    advanced_max = plugin.advanced_max
    advanced_earned = plugin.advanced_earned if config_valid else 0
    basic_earned = score - advanced_earned
    reached = basic_earned >= pass_score
    result = "통과" if reached and config_valid and tests_complete else "실패"

    summary = (
        f"## {title} 채점: {result}\n\n"
        f"- 점수: **{score:g} / {expected_max:g}**  "
        f"(기초 {basic_earned:g}/{pass_score:g}, 통과선 {pass_score:g}점)\n"
        f"- 테스트: 통과 {plugin.passed}, 실패 {plugin.failed}, 건너뜀 {plugin.skipped}\n"
        f"- 수집된 테스트: {plugin.collected}개"
    )
    if advanced_max > 0:
        badge = "달성" if advanced_earned >= advanced_max else f"{advanced_earned:g}/{advanced_max:g}"
        summary += f"\n- 심화 파트: **{badge}**  (통과 여부에는 영향 없음)"
    if not config_valid:
        summary += (
            f"\n- ⚠️ 설정 오류: 테스트 배점 합계 `{plugin.max_points:g}`와 "
            f"max_score `{expected_max:g}`가 다릅니다."
        )
    if not tests_complete:
        summary += "\n- ⚠️ 테스트 준비 오류: 테스트가 없거나 건너뛴 테스트가 있습니다."
    if not reached and config_valid and tests_complete:
        summary += (
            f"\n- 기초 파트가 통과선까지 **{pass_score - basic_earned:g}점** 부족합니다. "
            f"실패한 테스트 이름을 확인하세요."
        )

    print("\n" + summary)
    append_step_summary(summary)
    if not config_valid:
        return 2
    if not tests_complete:
        return 3
    return 0 if reached else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="SDS AX 일차별 자동 채점")
    parser.add_argument("--day", required=True, type=normalize_day, help="채점할 Day (1~10)")
    parser.add_argument(
        "--force",
        action="store_true",
        help="draft 상태에서도 강사용 사전 검증을 실행합니다.",
    )
    parser.add_argument(
        "--grader",
        action="store_true",
        help="학생 공개 테스트 대신 grader/dayNN 의 실제 채점 테스트를 실행합니다.",
    )
    args = parser.parse_args()
    return grade(args.day, args.force, args.grader)


if __name__ == "__main__":
    raise SystemExit(main())
