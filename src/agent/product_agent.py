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
)
from .system_prompt import SYSTEM_PROMPT
from .flow_guard import FlowGuard


def create_product_agent(session_id: str | None = None) -> tuple[Agent, FlowGuard]:
    """상품 세팅 에이전트를 생성합니다.

    Args:
        session_id: 세션 ID. Langfuse에서 같은 세션으로 묶임. None이면 자동 생성.

    Returns:
        (agent, flow_guard) 튜플. flow_guard로 Phase를 수동 전환할 수 있습니다.
    """
    model = BedrockModel(
        model_id="us.anthropic.claude-haiku-4-5-20251001-v1:0",
        region_name="us-west-2",
    )

    conversation_manager = SlidingWindowConversationManager(window_size=40)
    flow_guard = FlowGuard()

    agent = Agent(
        model=model,
        system_prompt=SYSTEM_PROMPT,
        conversation_manager=conversation_manager,
        hooks=[flow_guard],
        trace_attributes={
            "session.id": session_id or str(uuid.uuid4()),
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
        ],
    )

    return agent, flow_guard
