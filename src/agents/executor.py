"""
수행 에이전트 — 조회 + request_action(유일한 쓰기 경로) + 진단.

쓰기 API는 직접 호출하지 않는다.
request_action → ActionHarness가 자동으로 검증/확인/실행.
"""

from __future__ import annotations

import os
from strands import Agent, tool as strands_tool

from src.tools.admin_api import (
    search_masters,
    get_master_detail,
    get_master_groups,
    get_series_list,
    get_product_page_list,
    get_product_page_detail,
    get_product_list_by_page,
    get_community_settings,
    navigate,
)
from src.tools.verify import verify_settings

EXECUTOR_PROMPT = """당신은 관리자센터 상품 세팅 수행 에이전트입니다.

## 역할
운영 매니저의 요청을 받아 조회, 진단, 상태 변경을 실행합니다.

## 규칙

1. **조회**: 조회 tool로 정보를 모아라.
   - 슬롯 필링: 오피셜클럽 → 상품페이지 → 상품 옵션 순서로 좁힌다.
   - 여러 개면 목록 제시 후 선택 받는다 (자동 선택 금지).
   - "상품" vs "상품페이지" 구분 — 유저가 혼용할 수 있으므로 모호하면 물어본다.

2. **상태 변경**: request_action(action_id, slots)을 호출해라.
   - 가능한 action_id:
     - update_product_display: 상품 공개/비공개 (slots: product_id, is_display, master_name, page_title, product_name, page_id)
     - update_product_page_status: 상품페이지 공개/비공개 (slots: page_id, status, master_cms_id, page_title, master_name)
     - update_product_page_hidden: 히든 처리/해제 (slots: page_id, is_hidden, master_cms_id, page_title, master_name)
     - update_main_product_setting: 메인 상품페이지 설정 (slots: master_cms_id, view_status, master_name)
   - request_action이 확인 메시지를 반환한다. 그 응답을 유저에게 그대로 전달.
   - request_action이 에러를 반환하면 유저에게 전달.

3. **진단**: "왜 안 보여?" → diagnose_visibility 호출.
   - 이름으로 호출 가능 (search_masters 불필요).
   - 결과의 first_failure와 recommendation을 유저에게 전달.

4. **가이드**: 생성은 직접 하지 않는다 → navigate()로 이동 안내.
   - 시리즈 생성 = 파트너센터 안내 (관리자센터 아님).

5. **모르면 모른다고 해라.**

## 중요한 ID 규칙
- search_masters 결과의 cmsId를 masterId로 사용 (MongoDB ObjectId 아님)
- "상품 페이지 ID"와 "상품 ID"는 다름

## few-shot 예시

### 실행 모드
유저: 상품페이지 비공개해줘
→ search_masters → get_product_page_list → interrupt(목록 제시)
→ request_action("update_product_page_status", {page_id, status: "INACTIVE", master_cms_id, page_title, master_name})
→ 확인 메시지 → 유저 확인 → 완료

### 진단 모드
유저: 왜 상품페이지 노출이 안돼?
→ diagnose_visibility(master_id="조조형우")
→ 결과에서 first_failure 확인 → recommendation 전달

### 가이드 모드
유저: 상품페이지 새로 만들려고
→ search_masters → get_series_list → navigate("product_page_create")

유저: 시리즈가 필요하다는데 어디서 만들어야돼?
→ navigate("partner_series") → "파트너센터에서 생성합니다" 안내

"""


# request_action 호출 시 harness 응답을 저장하는 사이드채널.
# executor LLM이 응답을 해석/요약하더라도, orchestrator가 원본을 가져갈 수 있다.
_last_harness_response: str | None = None


def get_last_harness_response() -> str | None:
    """마지막 request_action 호출의 harness 응답을 꺼내고 초기화."""
    global _last_harness_response
    resp = _last_harness_response
    _last_harness_response = None
    return resp


@strands_tool
def request_action(action_id: str, slots: dict) -> str:
    """상태 변경 요청. 유일한 쓰기 경로.

    ActionHarness가 자동으로 검증/확인 메시지를 생성합니다.
    반환된 확인 메시지를 유저에게 그대로 전달하세요.

    Args:
        action_id: 액션 ID. 가능한 값:
            - update_product_display: 상품 공개/비공개
            - update_product_page_status: 상품페이지 공개/비공개
            - update_product_page_hidden: 히든 처리/해제
            - update_main_product_setting: 메인 상품페이지 설정
        slots: 슬롯 데이터. action_id별 필수 슬롯:
            - update_product_display: {product_id, is_display, master_name, page_title, product_name, page_id}
            - update_product_page_status: {page_id, status, master_cms_id, page_title, master_name}
            - update_product_page_hidden: {page_id, is_hidden, master_cms_id, page_title, master_name}
            - update_main_product_setting: {master_cms_id, view_status, master_name}

    Returns:
        확인 메시지 (JSON). 유저에게 그대로 전달하세요.
    """
    global _last_harness_response
    from src.harness import get_harness
    harness = get_harness()
    result = harness.validate_and_confirm(action_id, slots)
    _last_harness_response = result  # 사이드채널 저장
    return result


@strands_tool
def diagnose_visibility(master_id: str) -> str:
    """상품 노출 진단. 이름 또는 cmsId로 호출 가능.

    ⚡ 이름으로 호출하면 내부에서 마스터 검색까지 자동 수행.
    노출 사전조건 체인을 순서대로 확인하여 첫 번째 실패 지점을 찾습니다.

    Args:
        master_id: 마스터 cmsId (예: "35") 또는 오피셜클럽 이름 (예: "조조형우")

    Returns:
        진단 결과 (JSON). 유저에게 그대로 전달하세요.
    """
    from src.diagnose_engine import get_engine
    engine = get_engine()
    return engine.diagnose_rendered(master_id)


# 권한 기반 Tool 필터링
PERMISSION_TOOL_MAP = {
    "PRODUCT": [
        "get_product_page_list", "get_product_page_detail",
        "get_product_list_by_page",
        "request_action",
    ],
    "MASTER": [
        "search_masters", "get_master_detail", "get_master_groups",
        "get_series_list", "get_community_settings",
        "request_action",
    ],
}

COMMON_TOOLS = ["navigate", "diagnose_visibility", "request_action", "verify_settings"]

# 작업 유형별 Tool (TTFT 최적화)
TASK_TOOL_MAP = {
    "diagnose": [
        "diagnose_visibility", "get_community_settings", "navigate",
    ],
    "query": [
        "search_masters", "get_master_detail", "get_product_page_list",
        "get_product_page_detail", "get_product_list_by_page", "get_community_settings",
        "navigate",
    ],
    "update": [
        "search_masters", "get_product_page_list", "get_product_list_by_page",
        "request_action", "navigate",
    ],
    "guide": [
        "search_masters", "get_series_list", "get_product_page_list", "navigate",
    ],
}


def _filter_tools_by_permission(all_tools: list, role_type: str, permission_sections: list[str]) -> list:
    """권한에 따라 Tool 목록을 필터링합니다."""
    if role_type == "ALL":
        return all_tools

    allowed_names = set(COMMON_TOOLS)
    for section in permission_sections:
        allowed_names.update(PERMISSION_TOOL_MAP.get(section, []))

    return [t for t in all_tools if getattr(t, '__name__', getattr(t, 'name', '')) in allowed_names]


def create_executor_agent(
    role_type: str = "ALL",
    permission_sections: list[str] | None = None,
    task_type: str | None = None,
) -> Agent:
    """수행 에이전트를 생성합니다."""
    all_tools = [
        # 조회
        search_masters,
        get_master_detail,
        get_master_groups,
        get_series_list,
        get_product_page_list,
        get_product_page_detail,
        get_product_list_by_page,
        get_community_settings,
        # 네비게이션
        navigate,
        # 쓰기 — 유일한 게이트
        request_action,
        # 진단
        diagnose_visibility,
        # 세팅 결과 검증
        verify_settings,
    ]

    # 1. 권한 필터링
    tools = _filter_tools_by_permission(all_tools, role_type, permission_sections or [])

    # 2. 작업 유형 필터링
    if task_type and task_type in TASK_TOOL_MAP:
        allowed_task_tools = set(TASK_TOOL_MAP[task_type])
        tools = [t for t in tools if getattr(t, '__name__', getattr(t, 'name', '')) in allowed_task_tools]

    return Agent(
        model=os.environ.get("BEDROCK_MODEL_ID", "anthropic.claude-haiku-4-5-20251001-v1:0"),
        tools=tools,
        system_prompt=EXECUTOR_PROMPT,
    )
