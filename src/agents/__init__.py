"""
에이전트 팩토리 — 멀티 에이전트 시스템을 조립합니다.

아키텍처: 오케스트레이터 LLM + AgentCore Memory
- 오케스트레이터: 의도 분류 + 맥락 유지 (응답 재가공 안 함)
- 수행 에이전트: Tool 호출 → structured_output → 포맷팅 레이어
- 도메인 에이전트: RAG → 직접 응답
"""

from __future__ import annotations

from dataclasses import dataclass

from strands import Agent

from src.agents.executor import create_executor_agent
from src.agents.domain import create_domain_agent
from src.agents.orchestrator import create_orchestrator_agent


@dataclass
class AgentSystem:
    """멀티 에이전트 시스템. 오케스트레이터 + 에이전트들."""

    orchestrator: Agent  # 오케스트레이터 (라우팅 + 맥락 유지)
    executor: Agent
    domain: Agent


def create_agent_system(
    role_type: str = "ALL",
    permission_sections: list[str] | None = None,
    memory_context: str = "",
) -> AgentSystem:
    """멀티 에이전트 시스템을 생성합니다.

    Args:
        role_type: 유저 권한 (ALL, PART, NONE)
        permission_sections: 권한 섹션 목록
        memory_context: AgentCore Memory에서 가져온 맥락 (오케스트레이터 프롬프트에 주입)
    """
    executor = create_executor_agent(role_type, permission_sections)
    domain = create_domain_agent()
    orchestrator = create_orchestrator_agent(executor, domain, memory_context)

    return AgentSystem(orchestrator=orchestrator, executor=executor, domain=domain)
