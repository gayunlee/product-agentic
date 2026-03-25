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
    update_product_page_status,
    update_product_page,
    update_main_product_setting,
    navigate,
)
from src.agents.validator import (
    check_prerequisites,
    check_idempotency,
    diagnose_visibility,
)

EXECUTOR_PROMPT = """당신은 관리자센터 상품 세팅 수행 에이전트입니다.

⚠️ 최우선 규칙: 작업이 끝나면 반드시 respond Tool을 호출하세요. 직접 텍스트로 응답하면 안 됩니다.

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
E3. 쓰기 API 전에 반드시 check_prerequisites + check_idempotency Tool을 호출.
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

## 응답 규칙 (⚠️ 반드시 준수)

작업이 끝나면 반드시 respond Tool을 호출하여 구조화된 응답을 반환하세요.
직접 텍스트로 응답하지 마세요. 반드시 respond Tool을 통해 응답하세요.

respond Tool 파라미터:
- response_type: "diagnose" | "confirm" | "complete" | "guide" | "info" | "select"
- summary: 유저에게 보여줄 요약 (1~2줄, 자연어)
- data: 응답 데이터 (JSON)

### response_type별 data 형식

diagnose (진단 결과):
  data = {
    "master_name": "봄날의 햇살",
    "checks": [{"name": "마스터 PUBLIC", "ok": true, "value": "PUBLIC"}, ...],
    "first_failure": "메인 상품 ACTIVE" 또는 null (정상이면),
    "fix_label": "메인 상품 페이지 활성화" (first_failure 있을 때),
    "nav_url": "/product/page/list"
  }

confirm (실행 확인):
  data = {
    "target": "월간 투자 리포트 페이지",
    "action_label": "비공개 처리하기",
    "change": {"field": "상태", "from": "공개", "to": "비공개"},
    "edit_url": "/product/page/{id}?tab=settings"
  }

complete (실행 완료):
  data = {
    "target": "월간 투자 리포트 페이지",
    "action_done": "비공개 처리",
    "confirm_url": "/product/page/{id}?tab=settings"
  }

guide (이동 안내):
  data = {
    "label": "상품 페이지 생성",
    "url": "/product/page/create",
    "steps": ["오피셜클럽 선택", "정보 입력", "이미지 등록"]
  }

info (정보 조회):
  data = {
    "title": "상품 페이지 목록",
    "items": [{"제목": "...", "상태": "...", "코드": 148}]
  }

select (목록 선택):
  data = {
    "question": "어떤 상품 페이지를 수정하시겠어요?",
    "items": [{"label": "월간 투자 리포트 (공개)", "value": "mock_page_001"}]
  }
"""


# 권한 기반 Tool 필터링
# roleType=ALL → 전체, PART → permissionSections에 해당하는 Tool만, NONE → 사용 불가
PERMISSION_TOOL_MAP = {
    "PRODUCT": [
        "get_product_page_list", "get_product_page_detail",
        "get_product_list_by_page",
        "update_product_display", "update_product_page_status",
        "update_product_page",
    ],
    "MASTER": [
        "search_masters", "get_master_detail", "get_master_groups",
        "get_series_list", "get_community_settings",
        "update_main_product_setting",
    ],
}

# 권한 무관 공통 Tool
COMMON_TOOLS = ["navigate", "check_prerequisites", "check_idempotency", "diagnose_visibility", "respond"]


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
    from src.agents.response import AgentResponse, render_response_json as _render
    import json as _json

    @strands_tool
    def respond(response_type: str, summary: str, data: str) -> str:
        """구조화된 응답을 반환합니다. 작업 완료 시 반드시 이 Tool을 호출하세요.

        Args:
            response_type: 응답 유형 — diagnose, confirm, complete, guide, info, select, slot_question, error, reject
            summary: 유저에게 보여줄 요약 (1~2줄, 자연어)
            data: 응답 데이터 (JSON 문자열). type별 필수 필드는 프롬프트 참조.
        """
        try:
            parsed = _json.loads(data) if isinstance(data, str) else data
        except _json.JSONDecodeError:
            parsed = {"raw": data}

        resp = AgentResponse(type=response_type, summary=summary, data=parsed)
        return _render(resp)

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
        update_product_page_status,
        update_product_page,
        update_main_product_setting,
        # 네비게이션
        navigate,
        # 검증 (함수 직접 — LLM 경유 없이 즉시 실행)
        check_prerequisites,
        check_idempotency,
        diagnose_visibility,
        # 응답 (구조화된 응답 반환)
        respond,
    ]

    tools = _filter_tools_by_permission(all_tools, role_type, permission_sections or [])

    return Agent(
        model=os.environ.get("BEDROCK_MODEL_ID", "anthropic.claude-haiku-4-5-20251001-v1:0"),
        tools=tools,
        system_prompt=EXECUTOR_PROMPT,
    )
