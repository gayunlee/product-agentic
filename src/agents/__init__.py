"""
에이전트 팩토리 — 멀티 에이전트 시스템을 조립합니다.

아키텍처: 2티어 라우팅 + 에이전트 직접 응답
- Tier 1: 패턴 매칭 (정규식 + 후속 감지) → 즉시 라우팅
- Tier 2: LLM 라우터 (풀 히스토리) → 맥락 기반 라우팅
- 수행 에이전트: Tool 호출 → structured_output → 포맷팅 레이어 → 유저 직접
- 도메인 에이전트: RAG → 유저 직접
"""

from __future__ import annotations

from dataclasses import dataclass

from strands import Agent

from src.agents.executor import create_executor_agent
from src.agents.domain import create_domain_agent


@dataclass
class AgentSystem:
    """멀티 에이전트 시스템. 2티어 라우팅 + 에이전트들."""

    executor: Agent
    domain: Agent
    classifier: Agent  # Tier 2 LLM 라우터 (시스템 프롬프트는 router.py에서 동적 주입)


def create_agent_system(
    role_type: str = "ALL",
    permission_sections: list[str] | None = None,
) -> AgentSystem:
    """멀티 에이전트 시스템을 생성합니다."""
    import os

    model_id = os.environ.get("BEDROCK_MODEL_ID", "anthropic.claude-haiku-4-5-20251001-v1:0")

    executor = create_executor_agent(role_type, permission_sections)
    domain = create_domain_agent()
    # Tier 2 LLM 라우터 — system_prompt는 router.py LLMRouter가 호출 시 동적 설정
    classifier = Agent(
        model=model_id,
        tools=[],
        system_prompt="유저 메시지를 분류하세요. 한 단어만: CONTINUE, EXECUTOR, DOMAIN, REJECT, SELF",
    )

    return AgentSystem(executor=executor, domain=domain, classifier=classifier)


# 하위 호환 — 기존 create_orchestrator도 유지
def create_orchestrator(
    session_id: str = "default",
    role_type: str = "ALL",
    permission_sections: list[str] | None = None,
) -> Agent:
    """레거시 호환. 기존 오케스트레이터 반환."""
    from src.agents.orchestrator import create_orchestrator_agent

    executor = create_executor_agent(role_type, permission_sections)
    domain = create_domain_agent()
    return create_orchestrator_agent(executor, domain)
