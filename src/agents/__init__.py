"""
에이전트 팩토리 — 멀티 에이전트 시스템을 조립합니다.

create_orchestrator()를 호출하면 validator → executor → domain → orchestrator 순서로
에이전트를 생성하고 연결합니다.
"""

from __future__ import annotations

from strands import Agent

from src.agents.validator import create_validator_agent
from src.agents.executor import create_executor_agent
from src.agents.domain import create_domain_agent
from src.agents.orchestrator import create_orchestrator_agent


def create_orchestrator(session_id: str = "default") -> Agent:
    """멀티 에이전트 시스템을 조립하여 오케스트레이터를 반환합니다.

    조립 순서:
    1. validator (검증 에이전트) — 규칙 기반 체크
    2. executor (수행 에이전트) — validator를 AgentTool로 포함
    3. domain (도메인 에이전트) — Tool 없음, 지식 기반
    4. orchestrator — executor + domain을 AgentTool로 포함

    Args:
        session_id: 세션 ID (향후 SessionManager 연동용)

    Returns:
        오케스트레이터 Agent 인스턴스
    """
    # 1. 검증 에이전트
    validator = create_validator_agent()

    # 2. 수행 에이전트 (validator를 내부 도구로 사용)
    executor = create_executor_agent(validator)

    # 3. 도메인 지식 에이전트
    domain = create_domain_agent()

    # 4. 오케스트레이터 (executor + domain을 라우팅)
    orchestrator = create_orchestrator_agent(executor, domain)

    return orchestrator
