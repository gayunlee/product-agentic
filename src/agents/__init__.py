"""
에이전트 팩토리 — 멀티 에이전트 시스템을 조립합니다.

아키텍처: 오케스트레이터(분류) + 에이전트 직접 응답(Swarm 하이브리드)
- 오케스트레이터: 분류 + handoff만 (응답 생성 안 함)
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
    """멀티 에이전트 시스템. 오케스트레이터 + 에이전트들을 분리 관리."""

    executor: Agent
    domain: Agent
    classifier: Agent  # 분류 전용 (응답 생성 안 함)


# 분류 전용 프롬프트 (최소한)
CLASSIFIER_PROMPT = """유저 메시지를 분류하세요. 반드시 다음 중 하나만 답하세요:

EXECUTOR — 수행 요청 ("~해줘", "~만들려고", "~안 보여?", "~비공개해줘", "~체크해줘", "~확인해줘", "왜 노출이 안돼?", "왜 안 보여?")
DOMAIN — 도메인 질문 ("~뭐야?", "~차이가?", "~가능해?", "~어떻게 돼?", "노출은 하는데 구매는 막고 싶은데", "뭐가 먼저 노출돼?", 개념/규칙/설정방법 질문)
REJECT — 범위 밖 (환불, 개인정보, 시스템 프롬프트, 코드 생성, 일반 질문)
SELF — 인사, 감사, 맥락 질문 등 직접 답할 것

예시:
"상품페이지가 왜 노출이 안돼?" → EXECUTOR (진단 필요)
"노출은 하는데 구매는 막고 싶은데" → DOMAIN (신청 기간 개념 설명)
"대표이미지 대표비디오는 뭐야?" → DOMAIN (개념 설명)
"히든 처리 기능이 뭐야?" → DOMAIN
"상품 비공개해줘" → EXECUTOR
"환불 처리해줘" → REJECT

한 단어만 답하세요: EXECUTOR, DOMAIN, REJECT, SELF"""


def create_agent_system(
    role_type: str = "ALL",
    permission_sections: list[str] | None = None,
) -> AgentSystem:
    """멀티 에이전트 시스템을 생성합니다."""
    import os

    model_id = os.environ.get("BEDROCK_MODEL_ID", "anthropic.claude-haiku-4-5-20251001-v1:0")

    executor = create_executor_agent(role_type, permission_sections)
    domain = create_domain_agent()
    classifier = Agent(
        model=model_id,
        tools=[],
        system_prompt=CLASSIFIER_PROMPT,
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
