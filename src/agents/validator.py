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


MOCK_API_RESPONSES: dict[str, dict | list] = {
    "/v1/masters/35": {"cmsId": "35", "name": "조조형우", "clubPublicType": "PUBLIC", "productGroupViewStatus": "INACTIVE"},
    "/v1/masters/35/main-product-group": {"productGroupViewStatus": "INACTIVE"},
    "/v1/masters/100": {"cmsId": "100", "name": "김영익", "clubPublicType": "PENDING", "productGroupViewStatus": "INACTIVE"},
    "/v1/masters/100/main-product-group": {"productGroupViewStatus": "INACTIVE"},
    "/v1/product-group": [
        {"id": "mock_page_001", "title": "월간 투자 리포트 페이지", "status": "ACTIVE", "code": 148, "isAlwaysPublic": True},
        {"id": "mock_page_002", "title": "단건 특강", "status": "INACTIVE", "code": 155, "isAlwaysPublic": False},
    ],
    "/v1/product-group/mock_page_001": {"id": "mock_page_001", "title": "월간 투자 리포트 페이지", "status": "ACTIVE", "isHidden": False, "isAlwaysPublic": True},
    "/v1/product-group/mock_page_002": {"id": "mock_page_002", "title": "단건 특강", "status": "INACTIVE", "isHidden": False},
    "/v1/product/group/mock_page_001": [{"productId": "99999", "name": "월간 투자 리포트", "price": 29900, "isDisplay": True}],
    "/v1/product/group/mock_page_002": [],
}


def _api_get(path: str, params: dict | None = None) -> dict | list:
    """관리자센터 API GET 요청."""
    if MOCK_MODE:
        # 정확한 path 매칭 먼저, 없으면 prefix 매칭
        if path in MOCK_API_RESPONSES:
            return MOCK_API_RESPONSES[path]
        # params에 masterId가 있는 product-group 조회
        if path == "/v1/product-group" and params:
            return MOCK_API_RESPONSES.get("/v1/product-group", [])
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
    """상품이 고객에게 보이지 않는 원인을 진단합니다. 이름 또는 cmsId로 호출 가능.

    ⚡ 이름으로 호출하면 내부에서 마스터 검색까지 자동 수행 (search_masters 별도 호출 불필요).
    노출 사전조건 체인을 순서대로 확인하여 첫 번째 실패 지점을 찾습니다:
    마스터 PUBLIC → 메인 상품 ACTIVE → 페이지 ACTIVE → 기간 내 → 옵션 isDisplay

    Args:
        master_id: 마스터 cmsId (예: "35") 또는 오피셜클럽 이름 (예: "조조형우")

    Returns:
        {"visible": True/False, "checks": [...], "first_failure": "...", "recommendation": "..."}
    """
    checks = []

    # 0. 이름으로 호출된 경우 → 자동 검색
    if not master_id.isdigit():
        search_result = _api_get("/v1/masters", {"searchKeyword": master_id})
        if isinstance(search_result, list) and search_result:
            master_id = str(search_result[0].get("cmsId", ""))
            if not master_id:
                return {"visible": False, "checks": [], "first_failure": f"'{master_id}' 검색 결과 없음", "recommendation": "정확한 오피셜클럽 이름을 확인하세요."}
        else:
            return {"visible": False, "checks": [], "first_failure": f"'{master_id}' 검색 결과 없음", "recommendation": "정확한 오피셜클럽 이름을 확인하세요."}

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

    # 2-1. 웹링크 정합성 체크 (메인 상품 ACTIVE일 때만)
    weblink_warnings = []
    if main_active and isinstance(main_product, dict):
        web_link = main_product.get("productGroupWebLink", "")
        web_link_status = main_product.get("isProductGroupWebLinkStatus", "INACTIVE")

        if web_link_status == "ACTIVE" and web_link:
            # 웹링크에서 상품코드 추출
            import re
            code_match = re.search(r"/products/group/(\d+)", web_link)
            if code_match:
                weblink_code = int(code_match.group(1))
                # 웹링크 타겟 상품페이지 상태 확인 (아래 페이지 조회에서 검증)
                checks.append({
                    "condition": "weblink_set",
                    "label": "웹링크 설정",
                    "passed": True,
                    "actual": f"코드 {weblink_code}",
                    "_weblink_code": weblink_code,
                })
            else:
                checks.append({
                    "condition": "weblink_set",
                    "label": "웹링크 설정",
                    "passed": False,
                    "actual": f"잘못된 형식: {web_link[:50]}",
                })
                weblink_warnings.append("웹링크 URL 형식이 올바르지 않습니다.")
        elif web_link_status != "ACTIVE":
            checks.append({
                "condition": "weblink_set",
                "label": "웹링크 설정",
                "passed": False,
                "actual": "미설정 (productGroupCode로 fallback)",
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

    # 4. 웹링크 타겟 상품페이지 정합성 검증
    weblink_check = next((c for c in checks if c.get("condition") == "weblink_set" and c.get("_weblink_code")), None)
    if weblink_check and isinstance(pages, list):
        weblink_code = weblink_check["_weblink_code"]
        target_page = next((p for p in active_pages if p.get("page_id")), None)

        # 코드로 매칭 (active_pages에는 상세 정보가 없으므로 전체 페이지에서 찾기)
        all_page_details = {}
        for page in pages:
            page_id = page.get("id")
            if page_id:
                detail = _api_get(f"/v1/product-group/{page_id}")
                if isinstance(detail, dict):
                    all_page_details[detail.get("code")] = detail

        target = all_page_details.get(weblink_code)

        if target is None:
            weblink_warnings.append(f"웹링크가 존재하지 않는 상품페이지(코드 {weblink_code})를 가리킵니다.")
            checks.append({
                "condition": "weblink_target_valid",
                "label": "웹링크 타겟 유효",
                "passed": False,
                "actual": f"코드 {weblink_code} 없음",
            })
        else:
            target_status = target.get("status", "UNKNOWN")
            target_hidden = target.get("isHidden", False)
            target_always = target.get("isAlwaysPublic", True)

            if target_status != "ACTIVE":
                weblink_warnings.append(f"웹링크가 비공개(INACTIVE) 상품페이지(코드 {weblink_code})를 가리킵니다. 버튼 클릭 시 에러가 발생합니다.")
                checks.append({
                    "condition": "weblink_target_valid",
                    "label": "웹링크 타겟 접근 가능",
                    "passed": False,
                    "actual": f"코드 {weblink_code} INACTIVE",
                })
            elif target_hidden and not target_always:
                weblink_warnings.append(f"웹링크가 히든+날짜지정 상품페이지(코드 {weblink_code})를 가리킵니다. 공개기간 만료 시 404가 발생합니다.")
                checks.append({
                    "condition": "weblink_target_valid",
                    "label": "웹링크 타겟 안정성",
                    "passed": False,
                    "actual": f"코드 {weblink_code} 히든+날짜지정 (기간 만료 위험)",
                })
            elif not target_hidden and not target_always:
                # 비히든 날짜지정 — 다른 비히든 페이지가 우선될 수 있음
                other_non_hidden = [p for p in all_page_details.values()
                                    if p.get("code") != weblink_code
                                    and p.get("status") == "ACTIVE"
                                    and not p.get("isHidden", False)]
                if other_non_hidden:
                    weblink_warnings.append(f"웹링크가 날짜지정 상품페이지(코드 {weblink_code})를 가리키지만, 다른 공개 페이지가 우선 노출될 수 있습니다.")
                checks.append({
                    "condition": "weblink_target_valid",
                    "label": "웹링크 타겟 접근 가능",
                    "passed": True,
                    "actual": f"코드 {weblink_code} ACTIVE",
                })
            else:
                checks.append({
                    "condition": "weblink_target_valid",
                    "label": "웹링크 타겟 접근 가능",
                    "passed": True,
                    "actual": f"코드 {weblink_code} 정상",
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
        "weblink_warnings": weblink_warnings if weblink_warnings else None,
        "master_name": master.get("name", "") if isinstance(master, dict) else "",
    }


@tool
def check_cascading_effects(action: str, context: dict) -> dict:
    """비공개 처리 시 계단식 영향을 검증합니다.

    상품페이지 비공개 시 → 마지막 공개 페이지인지 확인 → 메인 상품도 EXCLUDED 필요 경고
    상품 비공개 시 → 마지막 공개 상품인지 확인 → 상품페이지도 비공개 권장 경고

    Args:
        action: 실행하려는 액션명 (update_product_page_status, update_product_display)
        context: {master_id, product_page_id, product_id, target_status/is_display}

    Returns:
        {"has_warning": bool, "warning": str, "suggested_actions": [...]}
    """
    master_id = context.get("master_id", "")

    # 상품페이지 비공개 시 → 나머지 공개 페이지 확인
    if action == "update_product_page_status" and context.get("target_status") == "INACTIVE":
        product_page_id = context.get("product_page_id", "")
        if master_id:
            pages = _api_get("/v1/product-group", {"masterId": master_id})
            if isinstance(pages, list):
                active_pages = [p for p in pages if p.get("status") == "ACTIVE" and p.get("id") != product_page_id]
                if len(active_pages) == 0:
                    return {
                        "has_warning": True,
                        "warning": "이 페이지가 마지막 공개 페이지입니다. 비공개 처리하면 모든 상품페이지가 비공개됩니다. "
                                   "메인 상품페이지도 EXCLUDED 처리하지 않으면 구독 페이지에서 버튼 클릭 시 404가 발생합니다.",
                        "suggested_actions": [
                            {"label": "메인 상품페이지도 EXCLUDED 처리", "action": "update_main_product_setting",
                             "params": {"master_id": master_id, "view_status": "EXCLUDED"}},
                        ],
                    }

    # 상품 비공개 시 → 나머지 공개 상품 확인
    if action == "update_product_display" and context.get("is_display") is False:
        product_page_id = context.get("product_page_id", "")
        product_id = context.get("product_id", "")
        if product_page_id:
            products = _api_get(f"/v1/product/group/{product_page_id}", {"publishStatus": "all"})
            if isinstance(products, list):
                displayed = [p for p in products
                             if p.get("isDisplay", False)
                             and str(p.get("productId", p.get("id", ""))) != str(product_id)]
                if len(displayed) == 0:
                    return {
                        "has_warning": True,
                        "warning": "이 상품이 마지막 공개 상품입니다. 비공개 처리하면 상품페이지에 상품이 0개가 됩니다. "
                                   "상품페이지도 비공개 처리하는 것을 권장합니다.",
                        "suggested_actions": [
                            {"label": "상품페이지도 비공개 처리", "action": "update_product_page_status",
                             "params": {"product_page_id": product_page_id, "status": "INACTIVE"}},
                        ],
                    }

    # 히든 해제 시 → 기간 충돌 검사 (API는 생성 시에만 검사, 수정 시 미검사)
    if action == "update_product_page" and context.get("isHidden") is False:
        product_page_id = context.get("product_page_id", "")
        if master_id and product_page_id:
            # 변경 대상 페이지 상세 조회
            target = _api_get(f"/v1/product-group/{product_page_id}")
            if isinstance(target, dict) and not target.get("isAlwaysPublic", True):
                target_start = target.get("startAt", "")
                target_end = target.get("endAt", "")

                # 같은 마스터의 다른 비히든 ACTIVE 페이지와 기간 겹침 확인
                pages = _api_get("/v1/product-group", {"masterId": master_id})
                if isinstance(pages, list):
                    for page in pages:
                        if page.get("id") == product_page_id:
                            continue
                        if page.get("status") != "ACTIVE":
                            continue
                        # 히든 여부는 상세 API에서 확인
                        detail = _api_get(f"/v1/product-group/{page['id']}")
                        if isinstance(detail, dict) and detail.get("isHidden", False):
                            continue  # 히든 페이지는 충돌 대상 아님

                        # 상시공개 페이지가 있으면 무조건 충돌
                        if detail.get("isAlwaysPublic", False):
                            return {
                                "has_warning": True,
                                "warning": f"히든 해제 시 기간 충돌이 발생합니다. "
                                           f"'{detail.get('title', '')}' 페이지가 상시공개 상태입니다. "
                                           f"히든을 해제하면 상시공개 페이지가 비활성화됩니다.",
                                "suggested_actions": [
                                    {"label": "히든 유지", "action": "cancel"},
                                ],
                            }

                        # 날짜지정 페이지끼리 기간 겹침 확인
                        page_start = detail.get("startAt", "")
                        page_end = detail.get("endAt", "")
                        if target_start and target_end and page_start and page_end:
                            if target_start <= page_end and target_end >= page_start:
                                return {
                                    "has_warning": True,
                                    "warning": f"히든 해제 시 기간 충돌이 발생합니다. "
                                               f"'{detail.get('title', '')}' 페이지와 공개기간이 겹칩니다 "
                                               f"({page_start}~{page_end}).",
                                    "suggested_actions": [
                                        {"label": "히든 유지", "action": "cancel"},
                                    ],
                                }

    return {"has_warning": False, "warning": "", "suggested_actions": []}


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
        model=os.environ.get("BEDROCK_MODEL_ID", "anthropic.claude-haiku-4-5-20251001-v1:0"),
        tools=[check_prerequisites, check_idempotency, diagnose_visibility],
        system_prompt=VALIDATOR_PROMPT,
    )
