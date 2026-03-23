"""
검증 에이전트 — 사전조건 체크 + 상태 검증 + 결과 확인.

판단 범위: "이 액션을 실행해도 되나?" — 규칙 기반 체크.
스테이트 머신 없이, 사전조건 규칙 테이블로 유연하게 순서를 강제한다.
"""

from __future__ import annotations

import os
import httpx
from strands import Agent, tool

ADMIN_BASE = os.environ.get("ADMIN_API_BASE_URL", "")
MOCK_MODE = os.environ.get("MOCK_MODE", "").lower() in ("true", "1", "yes")


# ── 사전조건 규칙 테이블 ──
# 각 액션이 실행되려면 어떤 데이터가 필요한지 정의.
# 스테이트 머신과 달리 "조건만 맞으면 어디든 바로 실행" 가능.

PREREQUISITES: dict[str, list[str]] = {
    # 조회 계열 — 사전조건 없음
    "search_masters": [],
    "get_master_groups": [],
    "get_master_detail": ["master_id"],
    "get_series_list": ["master_id"],
    "get_product_page_list": ["master_id"],
    "get_product_page_detail": ["product_page_id"],
    "get_product_list_by_page": ["product_page_id"],
    "get_community_settings": ["cms_id"],

    # 변경 계열 — 상품이 존재해야
    "update_product_display": ["product_id"],
    "update_product_page_status": ["product_page_id"],
    "update_product_page": ["product_page_id"],
    "update_main_product_setting": ["master_id"],
}

# 사전조건 체인 (사람이 읽기 쉬운 설명)
PREREQUISITE_MESSAGES: dict[str, str] = {
    "master_id": "마스터(오피셜클럽)를 먼저 확인해야 합니다. search_masters로 조회하세요.",
    "series_ids": "시리즈를 먼저 확인해야 합니다. get_series_list로 조회하세요. 시리즈가 없으면 상품 옵션을 만들 수 없습니다.",
    "product_page_id": "상품 페이지가 먼저 존재해야 합니다. get_product_page_list로 확인하세요.",
    "product_id": "상품 옵션이 먼저 존재해야 합니다.",
    "product_ids": "상품 옵션이 먼저 존재해야 합니다.",
}

# 노출 사전조건 체인 — 진단 시 사용
# 상품이 고객에게 보이려면 이 모든 조건이 충족되어야 함
VISIBILITY_CHAIN = [
    ("master_public", "마스터가 PUBLIC 상태여야 합니다"),
    ("main_product_active", "메인 상품 페이지 설정이 ACTIVE여야 합니다"),
    ("page_active", "상품 페이지가 ACTIVE 상태여야 합니다"),
    ("page_in_period", "현재 날짜가 공개 기간 내여야 합니다 (상시공개 또는 기간 내)"),
    ("option_displayed", "상품 옵션의 isDisplay가 true여야 합니다"),
]

# 히든 페이지 예외: URL 직접 접근 가능하므로 일부 조건 불필요
VISIBILITY_CHAIN_HIDDEN = [
    ("page_active", "상품 페이지가 ACTIVE 상태여야 합니다"),
    ("option_displayed", "상품 옵션의 isDisplay가 true여야 합니다"),
]


def _get_token() -> str:
    """현재 활성 토큰을 반환."""
    from src.tools.admin_api import ADMIN_TOKEN
    return ADMIN_TOKEN


def _api_get(path: str, params: dict | None = None) -> dict | list:
    """관리자센터 API GET 요청."""
    if MOCK_MODE:
        return {"mock": True, "path": path}
    with httpx.Client(
        base_url=ADMIN_BASE,
        headers={"Authorization": f"Bearer {_get_token()}"},
        timeout=30.0,
    ) as c:
        r = c.get(path, params=params or {})
        if r.status_code >= 400:
            return {"error": True, "status": r.status_code, "body": r.text[:500]}
        if not r.text.strip():
            return {}
        return r.json()


# ── 검증 도구 ──


@tool
def check_prerequisites(action: str, context: dict) -> dict:
    """액션 실행 전 사전조건을 체크합니다.

    Args:
        action: 실행하려는 액션명 (예: "create_product_page", "update_product_display")
        context: 현재까지 수집된 데이터 (예: {"master_id": "35", "series_ids": ["id1"]})

    Returns:
        {"allowed": True/False, "missing": [...], "messages": [...]}
    """
    required = PREREQUISITES.get(action, [])
    if not required:
        return {"allowed": True, "missing": [], "messages": []}

    missing = []
    messages = []
    for key in required:
        value = context.get(key)
        if value is None or value == [] or value == "":
            missing.append(key)
            msg = PREREQUISITE_MESSAGES.get(key, f"{key}가 필요합니다.")
            messages.append(msg)

    return {
        "allowed": len(missing) == 0,
        "missing": missing,
        "messages": messages,
    }


@tool
def check_idempotency(action: str, context: dict) -> dict:
    """쓰기 액션 전 이미 존재하는지 확인하여 중복 생성을 방지합니다.

    Args:
        action: 실행하려는 액션명
        context: 현재 컨텍스트 (master_id, product_page_id, title 등)

    Returns:
        {"exists": True/False, "existing_id": "..." or None, "message": "..."}
    """
    master_id = context.get("master_id", "")

    if action == "create_product_page" and master_id:
        title = context.get("title", "")
        pages = _api_get("/v1/product-group", {"masterId": master_id})
        if isinstance(pages, list):
            for page in pages:
                if page.get("title") == title:
                    return {
                        "exists": True,
                        "existing_id": page.get("id"),
                        "message": f"동일한 제목의 상품 페이지가 이미 존재합니다: {title} (ID: {page.get('id')})",
                    }
        return {"exists": False, "existing_id": None, "message": ""}

    if action == "create_product":
        product_page_id = context.get("product_page_id", "")
        name = context.get("name", "")
        if product_page_id:
            products = _api_get(f"/v1/product/group/{product_page_id}", {"publishStatus": "all"})
            if isinstance(products, list):
                for p in products:
                    if p.get("name") == name:
                        return {
                            "exists": True,
                            "existing_id": str(p.get("productId", p.get("id", ""))),
                            "message": f"동일한 이름의 상품 옵션이 이미 존재합니다: {name}",
                        }
        return {"exists": False, "existing_id": None, "message": ""}

    # 상태 변경 계열 — 현재 상태 확인
    if action == "update_product_page_status":
        product_page_id = context.get("product_page_id", "")
        target_status = context.get("target_status", "ACTIVE")
        if product_page_id:
            detail = _api_get(f"/v1/product-group/{product_page_id}")
            if isinstance(detail, dict) and detail.get("status") == target_status:
                return {
                    "exists": True,
                    "existing_id": product_page_id,
                    "message": f"상품 페이지가 이미 {target_status} 상태입니다.",
                }
        return {"exists": False, "existing_id": None, "message": ""}

    return {"exists": False, "existing_id": None, "message": ""}


@tool
def diagnose_visibility(master_id: str) -> dict:
    """상품이 고객에게 보이지 않는 원인을 진단합니다.

    노출 사전조건 체인을 순서대로 확인하여 첫 번째 실패 지점을 찾습니다:
    마스터 PUBLIC → 메인 상품 ACTIVE → 페이지 ACTIVE → 기간 내 → 옵션 isDisplay

    Args:
        master_id: 마스터 cmsId (예: "35")

    Returns:
        {"visible": True/False, "checks": [...], "first_failure": "...", "recommendation": "..."}
    """
    checks = []

    # 1. 마스터 상태 확인
    master = _api_get(f"/v1/masters/{master_id}")
    if isinstance(master, dict) and master.get("error"):
        return {"visible": False, "checks": [], "first_failure": "마스터를 찾을 수 없습니다", "recommendation": "masterId(cmsId)를 확인하세요."}

    master_public = master.get("clubPublicType") == "PUBLIC"
    checks.append({
        "condition": "master_public",
        "label": "마스터 PUBLIC 상태",
        "passed": master_public,
        "actual": master.get("clubPublicType", "UNKNOWN"),
    })

    # 2. 메인 상품 설정 확인
    main_product = _api_get(f"/v1/masters/{master_id}/main-product-group")
    main_active = False
    if isinstance(main_product, dict):
        main_active = main_product.get("productGroupViewStatus") == "ACTIVE"
    checks.append({
        "condition": "main_product_active",
        "label": "메인 상품 페이지 ACTIVE",
        "passed": main_active,
        "actual": main_product.get("productGroupViewStatus", "UNKNOWN") if isinstance(main_product, dict) else "조회 실패",
    })

    # 3. 상품 페이지들 확인
    pages = _api_get("/v1/product-group", {"masterId": master_id})
    active_pages = []
    if isinstance(pages, list):
        for page in pages:
            page_id = page.get("id")
            is_active = page.get("status") == "ACTIVE"
            is_hidden = False

            # 히든 여부는 상세 API에서 확인
            if page_id:
                detail = _api_get(f"/v1/product-group/{page_id}")
                if isinstance(detail, dict):
                    is_hidden = detail.get("isHidden", False)

            page_check = {
                "page_id": page_id,
                "title": page.get("title", ""),
                "status": page.get("status", "UNKNOWN"),
                "is_active": is_active,
                "is_hidden": is_hidden,
                "is_always_public": page.get("isAlwaysPublic", False),
            }

            if is_active:
                active_pages.append(page_check)

            # 옵션 확인
            if page_id:
                products = _api_get(f"/v1/product/group/{page_id}", {"publishStatus": "all"})
                if isinstance(products, list):
                    page_check["options"] = [
                        {
                            "name": p.get("name", ""),
                            "is_display": p.get("isDisplay", False),
                            "price": p.get("price", 0),
                        }
                        for p in products
                    ]

    checks.append({
        "condition": "page_active",
        "label": "ACTIVE 상품 페이지 존재",
        "passed": len(active_pages) > 0,
        "actual": f"{len(active_pages)}개 ACTIVE",
        "pages": active_pages,
    })

    # 첫 번째 실패 지점 찾기
    first_failure = None
    recommendation = None
    for check in checks:
        if not check["passed"]:
            first_failure = check["label"]
            if check["condition"] == "master_public":
                recommendation = f"마스터를 PUBLIC으로 전환하세요. 현재: {check['actual']}"
            elif check["condition"] == "main_product_active":
                recommendation = "메인 상품 페이지 설정을 ACTIVE로 변경하세요. update_main_product_setting 사용."
            elif check["condition"] == "page_active":
                recommendation = "상품 페이지를 ACTIVE로 변경하세요. update_product_page_status 사용."
            break

    return {
        "visible": first_failure is None,
        "checks": checks,
        "first_failure": first_failure,
        "recommendation": recommendation,
        "master_name": master.get("name", "") if isinstance(master, dict) else "",
    }


# ── 검증 에이전트 생성 ──

VALIDATOR_PROMPT = """당신은 상품 세팅 검증 에이전트입니다.

## 역할
액션 실행 전 사전조건을 체크하고, 상태를 검증하며, 문제를 진단합니다.

## 판단 범위
"이 액션을 실행해도 되나?" — 이것만 판단합니다.

## 사전조건 체인
오피셜클럽(master_id) → 시리즈(series_ids) → 상품 페이지(product_page_id) → 상품 옵션
어떤 단계도 건너뛸 수 없습니다.

## 노출 사전조건 체인 (진단용)
마스터 PUBLIC → 메인 상품 ACTIVE → 페이지 ACTIVE → 기간 내 → 옵션 isDisplay
히든 페이지는 예외: URL 직접 접근 가능 (마스터 PUBLIC, 메인 ACTIVE 불필요)

## 규칙
1. 사전조건이 충족되지 않으면 반드시 차단하고, 어떤 조건이 빠졌는지 안내
2. 쓰기 액션 전에는 멱등성 확인 (이미 존재하면 중복 생성 방지)
3. 진단 요청 시 노출 체인을 순서대로 확인하여 첫 번째 실패 지점 보고
4. 히든 페이지는 노출 체인의 일부 조건이 면제됨
"""


def create_validator_agent() -> Agent:
    """검증 에이전트를 생성합니다."""
    return Agent(
        model="us.anthropic.claude-haiku-4-5-20251001-v1:0",
        tools=[check_prerequisites, check_idempotency, diagnose_visibility],
        system_prompt=VALIDATOR_PROMPT,
    )
