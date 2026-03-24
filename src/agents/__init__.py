"""
에이전트 팩토리 — 멀티 에이전트 시스템을 조립합니다.

create_orchestrator()를 호출하면 executor → domain → orchestrator 순서로
에이전트를 생성하고 연결합니다.
검증 함수(check_prerequisites 등)는 executor의 Tool로 직접 등록 (LLM 경유 없음).
"""

from __future__ import annotations

from strands import Agent

from src.agents.executor import create_executor_agent
from src.agents.domain import create_domain_agent
from src.agents.orchestrator import create_orchestrator_agent


def create_orchestrator(
    session_id: str = "default",
    role_type: str = "ALL",
    permission_sections: list[str] | None = None,
) -> Agent:
    """멀티 에이전트 시스템을 조립하여 오케스트레이터를 반환합니다.

    Args:
        session_id: 세션 ID (향후 SessionManager 연동용)
        role_type: 유저 권한 (ALL, PART, NONE)
        permission_sections: 권한 섹션 목록 (PART일 때 ["PRODUCT", "MASTER"] 등)
    """
    if role_type == "NONE":
        return Agent(
            model="anthropic.claude-haiku-4-5-20251001-v1:0",
            tools=[],
            system_prompt="권한이 없습니다. 관리자에게 문의해주세요.",
        )

    # 1. 수행 에이전트 (검증 함수 직접 포함, 권한 기반 Tool 필터링)
    executor = create_executor_agent(role_type, permission_sections)

    # 2. 도메인 지식 에이전트
    domain = create_domain_agent()

    # 3. 오케스트레이터 (executor + domain 라우팅)
    orchestrator = create_orchestrator_agent(executor, domain)

    return orchestrator
