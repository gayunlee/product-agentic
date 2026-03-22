"""
상품 세팅 에이전트.

Strands Agent SDK로 구현한 관리자센터 상품 세팅 자동화 에이전트.
FlowGuard로 Phase별 Tool 호출 순서를 강제합니다.
"""

import uuid

from strands import Agent
from strands.agent.conversation_manager import SlidingWindowConversationManager
from strands.models.bedrock import BedrockModel

from src.tools import (
    create_master_group,
    search_masters,
    get_master_detail,
    get_master_groups,
    get_series_list,
    create_series,
    create_product_page,
    update_product_page_status,
    create_product,
    update_product_display,
    update_product_sequence,
    update_main_product_setting,
    get_product_page_list,
    get_product_page_detail,
    get_product_list_by_page,
    verify_product_setup,
)
from .system_prompt import SYSTEM_PROMPT
from .flow_guard import FlowGuard
from .memory import create_memory_session, get_context_for_prompt, save_turn

import logging

logger = logging.getLogger(__name__)


def create_product_agent(
    session_id: str | None = None,
    actor_id: str = "default_operator",
    use_memory: bool = False,
) -> tuple[Agent, FlowGuard]:
    """상품 세팅 에이전트를 생성합니다.

    Args:
        session_id: 세션 ID. Langfuse에서 같은 세션으로 묶임. None이면 자동 생성.
        actor_id: Memory에서 유저를 식별하는 ID.
        use_memory: AgentCore Memory 사용 여부.

    Returns:
        (agent, flow_guard) 튜플. flow_guard로 Phase를 수동 전환할 수 있습니다.
    """
    sid = session_id or str(uuid.uuid4())

    model = BedrockModel(
        model_id="us.anthropic.claude-haiku-4-5-20251001-v1:0",
        region_name="us-west-2",
    )

    # Memory 연동 + 이전 컨텍스트 주입
    system_prompt = SYSTEM_PROMPT
    memory_session = None
    if use_memory:
        try:
            memory_session = create_memory_session(session_id=sid, actor_id=actor_id)
            logger.info(f"AgentCore Memory 세션 생성: {sid}")

            # 이전 이력 검색 → 시스템 프롬프트에 주입
            context = get_context_for_prompt(memory_session, query="상품 세팅")
            if context:
                system_prompt = SYSTEM_PROMPT + f"\n\n## 메모리 (이전 대화/이력)\n{context}"
                logger.info(f"Memory 컨텍스트 주입: {len(context)}자")
        except Exception as e:
            logger.warning(f"Memory 세션 생성 실패 (Memory 없이 진행): {e}")

    conversation_manager = SlidingWindowConversationManager(window_size=40)
    flow_guard = FlowGuard()

    agent = Agent(
        model=model,
        system_prompt=system_prompt,
        conversation_manager=conversation_manager,
        hooks=[flow_guard],
        trace_attributes={
            "session.id": sid,
            "langfuse.tags": ["product-agent", "poc"],
        },
        tools=[
            create_master_group,
            search_masters,
            get_master_detail,
            get_master_groups,
            get_series_list,
            create_series,
            create_product_page,
            update_product_page_status,
            create_product,
            update_product_display,
            update_product_sequence,
            update_main_product_setting,
            get_product_page_list,
            get_product_page_detail,
            get_product_list_by_page,
            verify_product_setup,
        ],
    )

    # memory_session을 flow_guard에 붙여서 server.py에서 접근 가능하게
    flow_guard.memory_session = memory_session
    flow_guard.actor_id = actor_id

    return agent, flow_guard
