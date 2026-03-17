"""
상품 세팅 에이전트.

Strands Agent SDK로 구현한 관리자센터 상품 세팅 자동화 에이전트.
CLI에서 대화형으로 실행하거나, Slack 연동으로 사용 가능.
"""

from strands import Agent
from strands.models.bedrock import BedrockModel

from src.tools import (
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
    get_product_page_detail,
    get_product_list_by_page,
)
from .system_prompt import SYSTEM_PROMPT


def create_product_agent() -> Agent:
    """상품 세팅 에이전트를 생성합니다."""
    model = BedrockModel(
        model_id="us.anthropic.claude-haiku-4-5-20251001-v1:0",
        region_name="us-west-2",
    )

    agent = Agent(
        model=model,
        system_prompt=SYSTEM_PROMPT,
        tools=[
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
            get_product_page_detail,
            get_product_list_by_page,
        ],
    )

    return agent
