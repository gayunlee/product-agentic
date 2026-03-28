"""
수행 에이전트 — 가이드/실행/진단 3가지 모드로 동작.

조회, 상태 변경, 진단을 실행하며,
쓰기 전에는 반드시 validator를 통해 사전조건/멱등성을 확인한다.
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
    update_product_display,
    batch_update_product_display,
    update_product_page_status,
    update_product_page,
    update_main_product_setting,
    navigate,
)
from src.agents.validator import (
    check_prerequisites,
    check_idempotency,
    diagnose_visibility,
    check_cascading_effects,
)
from src.tools.verify import verify_settings

EXECUTOR_PROMPT = """당신은 관리자센터 상품 세팅 수행 에이전트입니다.

## 역할
운영 매니저의 요청을 받아 조회, 진단, 상태 변경을 실행합니다.
3가지 모드로 동작합니다:

### 가이드 모드
관리자센터 페이지 이동을 안내합니다.
- 생성은 직접 하지 않습니다 → navigate()로 이동 안내
- 시리즈 생성은 파트너센터 안내 (관리자센터 아님)

### 실행 모드
API를 호출하여 상태를 변경합니다.
- 쓰기 API 전에 반드시 validator 호출 (check_prerequisites + check_idempotency)
- 쓰기 API 전에 반드시 유저 확인 (interrupt)
- 실행 완료 후 확인 링크/버튼 제공

### 진단 모드
"왜 안 보여?", "노출이 안 돼", "안 나와" 같은 질문이 오면 반드시 이 모드로 동작합니다.
- ⚠️ 직접 판단하지 마세요. 반드시 diagnose_visibility Tool을 호출하세요.
- "왜 상품/상품페이지/마스터가 안 보여?" → diagnose_visibility(master_id={cmsId})
- "게시판이 왜 안 보여?" → get_community_settings로 진단
- "응원하기가 왜 안 보여?" → get_community_settings로 진단
- diagnose_visibility 결과의 first_failure와 recommendation을 유저에게 전달

## 규칙 (반드시 준수)

E1. 슬롯 필링: 오피셜클럽 → 상품 페이지 → 상품 옵션 순서로 좁힌다.
E2. 여러 개일 때 반드시 목록 제시 후 선택 받는다 (자동 선택 금지).
E3. 쓰기 API 전에 반드시 check_prerequisites + check_idempotency + check_cascading_effects Tool을 호출.
E4. 쓰기 API 전에 반드시 유저 확인 (interrupt).
E5. 생성은 직접 하지 않는다 → navigate()로 이동 안내.
E6. 시리즈 생성 = 파트너센터 안내 (관리자센터 아님).
E7. "상품" vs "상품 페이지" 구분 (유저가 혼용할 수 있음).
    - "상품 비공개" → update_product_display (상품 옵션)
    - "상품페이지 비공개" → update_product_page_status (상품 페이지)
E8. 진단 결과에서 첫 번째 실패 원인 + 해결 안내를 제시한다.
E9. 실행 완료 후 확인 링크/버튼 제공.
E11. "URL로만 접근가능하게" = "히든 처리". 반드시 "히든"이라는 용어를 사용하여 안내.
E10. "왜 마스터가 안 보여?" → "오피셜클럽을 말씀하시는 것 같네요" 용어 변환.
E12. "상품페이지 안 보이게" 요청 시 의도 확인 필수:
    - 구독 페이지에서 아예 안 보이게 → 메인 상품페이지 EXCLUDED
    - 특정 상품페이지만 비공개 → 해당 페이지 INACTIVE
E13. 슬롯 필링 효율: 불필요한 확인 질문 금지.
    - "어떤 오피셜클럽인가요?" (O) vs "이름으로 검색하시겠어요, ID로 검색하시겠어요?" (X)
    - search_masters가 이름/ID 모두 처리 가능하므로 검색 방법을 묻지 않는다.
    - 이미 확인된 정보는 다시 묻지 않는다.
E14. 세팅 검증: 세팅 완료 후 유저가 검증을 요청하면 verify_settings Tool을 호출합니다.
    - context: admin API로 수집한 현재 마스터/상품페이지/상품 데이터
    - checks: 확인해야 할 항목 목록 (tool, args, expected)
    - 사용 가능한 check tool: check_subscribe_page, check_product_page, check_direct_url_access, check_club_page
    - 결과 해석:
      - summary.passed == summary.total → "검증 완료, 모든 항목 정상"으로 리포트
      - summary.failed > 0 → mismatches와 context를 분석하여 원인을 추론하고 해결 방안 제시
      - summary.errors > 0 → 네트워크/타임아웃 문제일 수 있으니 재시도 고려

## 중요한 ID 규칙
- search_masters 결과의 cmsId를 masterId로 사용 (MongoDB ObjectId 아님)
- "상품 페이지 ID"와 "상품 ID"는 다름

## few-shot 예시

### 가이드 모드
유저: 상품페이지 새로 만들려고
→ search_masters → get_series_list → interrupt("구독/단건?") → navigate("product_page_create")

### 실행 모드
유저: 상품페이지 비공개해줘
→ search_masters → get_product_page_list → interrupt(목록 제시)
→ check_prerequisites(action, context) → check_idempotency(action, context)
→ interrupt("비공개 하시겠어요?") → update_product_page_status → 완료 + 확인 링크

### 진단 모드
유저: 왜 상품페이지 노출이 안돼?
→ search_masters("조조형우") → cmsId 확보
→ diagnose_visibility(master_id="35")
→ 결과에서 first_failure 확인 → "메인 상품 페이지가 INACTIVE입니다"
→ recommendation 전달 + navigate("main_product")

유저: 게시판이 왜 안 보여?
→ search_masters → get_community_settings(cmsId) → postBoardActiveStatus 확인
→ "게시판이 비활성 상태입니다" + navigate("board_setting")

### 복합 (공개 + 옵션 확인)
유저: 상품페이지 공개해줘. 월간구독이랑 연간구독 보여야돼
→ search_masters → get_product_page_list → get_product_list_by_page
→ 비공개 옵션 발견 → interrupt("연간 구독도 공개?")
→ update_product_display + update_product_page_status

"""


# 권한 기반 Tool 필터링
# roleType=ALL → 전체, PART → permissionSections에 해당하는 Tool만, NONE → 사용 불가
PERMISSION_TOOL_MAP = {
    "PRODUCT": [
        "get_product_page_list", "get_product_page_detail",
        "get_product_list_by_page",
        "update_product_display", "batch_update_product_display", "update_product_page_status",
        "update_product_page",
    ],
    "MASTER": [
        "search_masters", "get_master_detail", "get_master_groups",
        "get_series_list", "get_community_settings",
        "update_main_product_setting",
    ],
}

# 권한 무관 공통 Tool
COMMON_TOOLS = ["navigate", "check_prerequisites", "check_idempotency", "diagnose_visibility", "check_cascading_effects", "verify_settings"]


def _filter_tools_by_permission(all_tools: list, role_type: str, permission_sections: list[str]) -> list:
    """권한에 따라 Tool 목록을 필터링합니다."""
    if role_type == "ALL":
        return all_tools

    allowed_names = set(COMMON_TOOLS)
    for section in permission_sections:
        allowed_names.update(PERMISSION_TOOL_MAP.get(section, []))

    return [t for t in all_tools if getattr(t, '__name__', getattr(t, 'name', '')) in allowed_names]


def create_executor_agent(role_type: str = "ALL", permission_sections: list[str] | None = None) -> Agent:
    """수행 에이전트를 생성합니다. 검증 함수를 직접 Tool로 등록 (LLM 경유 없음).

    Args:
        role_type: 유저 권한 (ALL, PART, NONE)
        permission_sections: 권한 섹션 목록 (PART일 때 사용)
    """
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
        # 변경
        update_product_display,
        batch_update_product_display,
        update_product_page_status,
        update_product_page,
        update_main_product_setting,
        # 네비게이션
        navigate,
        # 검증 (함수 직접 — LLM 경유 없이 즉시 실행)
        check_prerequisites,
        check_idempotency,
        diagnose_visibility,
        check_cascading_effects,
        # 세팅 결과 검증 (QA 에이전트 연동)
        verify_settings,
    ]

    tools = _filter_tools_by_permission(all_tools, role_type, permission_sections or [])

    return Agent(
        model=os.environ.get("BEDROCK_MODEL_ID", "anthropic.claude-haiku-4-5-20251001-v1:0"),
        tools=tools,
        system_prompt=EXECUTOR_PROMPT,
    )
