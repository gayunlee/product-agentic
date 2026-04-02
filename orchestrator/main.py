"""멀티레포 에이전트 오케스트레이터.

Usage:
    uv run python -m orchestrator.main dev "us-plus web-mcp 인터페이스 탐색해서 계약 초안 만들어"
    uv run python -m orchestrator.main qa "히든+날짜지정 세팅 조합 테스트"
    uv run python -m orchestrator.main check  # 아키텍처 체커만 실행
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

from claude_agent_sdk import query, ClaudeAgentOptions, ResultMessage

from orchestrator.config import (
    EXPLORER_AGENT_DIR,
    MAX_BUDGET_PER_AGENT,
    MAX_TURNS_PER_AGENT,
    PRODUCT_AGENT_DIR,
    READ_TOOLS,
    WEB_DIR,
    WEB_WORKTREE_BRANCH,
    WEB_WORKTREE_DIR,
    WRITE_TOOLS,
)
from orchestrator.agents.product import DEV_PROMPT as PRODUCT_DEV, QA_PROMPT as PRODUCT_QA
from orchestrator.agents.web import DEV_PROMPT as WEB_DEV, QA_PROMPT as WEB_QA
from orchestrator.agents.explorer import DEV_PROMPT as EXPLORER_DEV, QA_PROMPT as EXPLORER_QA

REPORTS_DIR = PRODUCT_AGENT_DIR / "orchestrator" / "reports"


# ─── helpers ────────────────────────────────────────────────────────

def _ensure_web_worktree() -> Path:
    """us-web 고정 워크트리가 있는지 확인하고, 없으면 생성."""
    import subprocess

    if WEB_WORKTREE_DIR.exists():
        print(f"  [us-web] 기존 워크트리 사용: {WEB_WORKTREE_DIR}")
        return WEB_WORKTREE_DIR

    # 워크트리 생성 (web-mcp 브랜치 기반)
    subprocess.run(
        ["git", "worktree", "add", str(WEB_WORKTREE_DIR), WEB_WORKTREE_BRANCH],
        cwd=str(WEB_DIR),
        capture_output=True,
    )
    # 브랜치가 없으면 새로 생성
    if not WEB_WORKTREE_DIR.exists():
        subprocess.run(
            ["git", "worktree", "add", "-b", WEB_WORKTREE_BRANCH, str(WEB_WORKTREE_DIR)],
            cwd=str(WEB_DIR),
            capture_output=True,
        )
    print(f"  [us-web] 워크트리 생성: {WEB_WORKTREE_DIR}")
    return WEB_WORKTREE_DIR


async def run_agent(
    prompt: str,
    cwd: Path,
    tools: list[str] | None = None,
    system_prompt: str = "",
    use_worktree: bool = False,
) -> str:
    """단일 에이전트 실행. 결과 텍스트 반환.

    Args:
        use_worktree: True이면 us-web 고정 워크트리에서 격리 실행.
    """
    full_prompt = f"{system_prompt}\n\n## 태스크\n{prompt}" if system_prompt else prompt
    actual_cwd = _ensure_web_worktree() if use_worktree else cwd

    result_text = ""
    async for message in query(
        prompt=full_prompt,
        options=ClaudeAgentOptions(
            cwd=str(actual_cwd),
            allowed_tools=tools or WRITE_TOOLS,
            max_turns=MAX_TURNS_PER_AGENT,
            max_budget_usd=MAX_BUDGET_PER_AGENT,
            permission_mode="acceptEdits",
        ),
    ):
        if isinstance(message, ResultMessage):
            if message.subtype == "success":
                result_text = message.result or ""
            print(f"  [{cwd.name}] 완료 (${message.total_cost_usd:.4f})")

    return result_text


def generate_report(
    mode: str,
    task: str,
    results: dict[str, str],
    check_output: str | None = None,
) -> Path:
    """루프 리포트 생성."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = REPORTS_DIR / f"report_{mode}_{timestamp}.md"

    lines = [
        f"## 루프 리포트 — {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**모드**: {mode}",
        f"**태스크**: {task}",
        "",
    ]

    if check_output:
        lines.extend(["### 아키텍처 검증", "```", check_output, "```", ""])

    for agent_name, result in results.items():
        lines.extend([f"### {agent_name}", "", result[:2000], ""])  # 결과 길이 제한

    lines.extend([
        "### 승인 필요",
        "- [ ] 위 결과 리뷰",
        "",
    ])

    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


# ─── modes ──────────────────────────────────────────────────────────

async def run_dev_mode(task: str):
    """개발 모드: 탐색 + 구현 + 아키텍처 체커."""
    print(f"\n{'='*60}")
    print(f"  개발 모드 — {task}")
    print(f"{'='*60}\n")

    # 1. 3개 에이전트 병렬 실행
    print("[1/2] 3개 에이전트 병렬 작업 시작...")
    product_task, web_task, explorer_task = await asyncio.gather(
        run_agent(task, PRODUCT_AGENT_DIR, WRITE_TOOLS, PRODUCT_DEV),
        run_agent(task, WEB_DIR, WRITE_TOOLS, WEB_DEV, use_worktree=True),
        run_agent(task, EXPLORER_AGENT_DIR, WRITE_TOOLS, EXPLORER_DEV),
    )

    # 2. 아키텍처 체커 실행 (us-product-agent만 — 다른 레포는 각자 체커 생기면 추가)
    print("\n[2/2] 아키텍처 체커 실행...")
    import subprocess

    check_result = subprocess.run(
        ["uv", "run", "python", "-m", "checks.architecture"],
        capture_output=True,
        text=True,
        cwd=str(PRODUCT_AGENT_DIR),
    )
    check_output = check_result.stdout + check_result.stderr
    print(check_output)

    # 3. 리포트 생성
    report = generate_report(
        mode="dev",
        task=task,
        results={
            "product-agent": product_task,
            "web-agent": web_task,
            "explorer-agent": explorer_task,
        },
        check_output=check_output,
    )
    print(f"\n리포트: {report}")


async def run_qa_mode(task: str):
    """QA 모드: 환경 셋업 + 테스트 실행."""
    print(f"\n{'='*60}")
    print(f"  QA 모드 — {task}")
    print(f"{'='*60}\n")

    # 1. 환경 체크
    print("[1/3] 환경 확인...")
    import subprocess

    status = subprocess.run(
        [str(PRODUCT_AGENT_DIR / "scripts" / "start-test-env.sh"), "status"],
        capture_output=True,
        text=True,
    )
    print(status.stdout)

    # 2. 3개 에이전트 병렬 QA
    print("[2/3] QA 에이전트 병렬 실행...")
    product_qa, web_qa, explorer_qa = await asyncio.gather(
        run_agent(task, PRODUCT_AGENT_DIR, WRITE_TOOLS, PRODUCT_QA),
        run_agent(task, WEB_DIR, READ_TOOLS, WEB_QA, use_worktree=True),
        run_agent(task, EXPLORER_AGENT_DIR, READ_TOOLS, EXPLORER_QA),
    )

    # 3. 리포트 생성
    report = generate_report(
        mode="qa",
        task=task,
        results={
            "product-agent (세팅)": product_qa,
            "web-agent (서비스 확인)": web_qa,
            "explorer-agent (검증)": explorer_qa,
        },
    )
    print(f"\n리포트: {report}")


async def run_check():
    """아키텍처 체커만 실행."""
    import subprocess

    result = subprocess.run(
        ["uv", "run", "python", "-m", "checks.architecture"],
        text=True,
        cwd=str(PRODUCT_AGENT_DIR),
    )
    sys.exit(result.returncode)


# ─── CLI ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="멀티레포 에이전트 오케스트레이터")
    parser.add_argument("mode", choices=["dev", "qa", "check"], help="실행 모드")
    parser.add_argument("task", nargs="?", default="", help="태스크 설명")
    args = parser.parse_args()

    if args.mode == "check":
        asyncio.run(run_check())
    elif args.mode == "dev":
        if not args.task:
            print("Error: dev 모드에는 태스크 설명이 필요합니다.")
            sys.exit(1)
        asyncio.run(run_dev_mode(args.task))
    elif args.mode == "qa":
        if not args.task:
            print("Error: qa 모드에는 태스크 설명이 필요합니다.")
            sys.exit(1)
        asyncio.run(run_qa_mode(args.task))


if __name__ == "__main__":
    main()
