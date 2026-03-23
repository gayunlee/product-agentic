"""
관리자센터 API Tools.

에이전트가 관리자센터 API를 호출할 수 있도록 Tool로 래핑.
각 함수는 @tool 데코레이터로 에이전트에 노출됨.
LangChain tool 형식 사용.
"""

import os
import httpx
import requests
from langchain_core.tools import tool

ADMIN_BASE = os.environ.get("ADMIN_API_BASE_URL", "")
ADMIN_TOKEN = os.environ.get("ADMIN_API_TOKEN", "")
PARTNER_BASE = os.environ.get("PARTNER_API_BASE_URL", "")
PARTNER_TOKEN = os.environ.get("PARTNER_API_TOKEN", "")
PLACEHOLDER_IMAGE = "https://placehold.co/990x1100/e8e8e8/999?text=PLACEHOLDER"
MOCK_MODE = os.environ.get("MOCK_MODE", "").lower() in ("true", "1", "yes")
EXPLORER_AGENT_URL = os.environ.get("EXPLORER_AGENT_URL", "http://localhost:8001")

# Mock 응답 데이터
MOCK_RESPONSES = {
    "get_master_groups": {"masterGroups": [
        {"id": "69b37159193f23cd69de4df7", "name": "조조형우의 클럽", "masterCount": 1},
    ]},
    "search_masters": [
        {"id": "673301e25aa67ba37f477759", "cmsId": "35", "name": "조조형우", "createdAt": "2024-11-12", "publicType": "PUBLIC", "masterGroupId": "69b37159193f23cd69de4df7", "masterGroupName": "조조형우의 클럽"},
    ],
    "get_master_detail": {"cmsId": "35", "name": "조조형우", "displayName": "조조형우", "clubPublicType": "PUBLIC", "clubName": "조조형우", "productGroupViewStatus": "ACTIVE", "masterDisplayIndex": 10},
    "get_series_list": {"masters": [{"_id": "673301e25aa67ba37f477759", "name": "조조형우", "series": [
        {"_id": "mock_series_001", "title": "투자 기초 시리즈"},
        {"_id": "mock_series_002", "title": "경제 분석 리포트"},
    ]}]},
    "create_master_group": {"success": True, "status": 201},
    "create_series": {"content": {"id": "mock_series_new", "cmsId": "300"}},
    "get_product_page_list": [],  # 첫 조회는 빈 목록
    "create_product_page": {"success": True, "status": 201},
    "get_product_page_list_after": [{"id": "mock_page_001", "title": "월간 투자 리포트 페이지", "status": "INACTIVE", "code": 148, "isAlwaysPublic": True, "isAlwaysApply": True, "startAt": "1970.01.01", "endAt": "9999.12.31", "applyStartAt": "1970-01-01", "applyEndAt": "9999-12-31", "createdAt": "2026-03-18", "isDeletable": True}],
    "create_product": {"id": 99999},
    "update_product_display": {"success": True, "status": 200},
    "update_product_sequence": {"success": True, "status": 200},
    "update_product_page_status": {"success": True, "status": 200},
    "update_main_product_setting": {"success": True, "status": 200},
    "get_product_page_detail": {"id": "mock_page_001", "masterId": "35", "title": "월간 투자 리포트 페이지", "status": "ACTIVE", "type": "SUBSCRIPTION", "code": 148, "isAlwaysPublic": True, "isChangeable": True, "mainContents": [{"type": "IMAGE", "contentUrl": PLACEHOLDER_IMAGE}], "contents": [{"imageUrl": PLACEHOLDER_IMAGE, "sequence": 0}]},
    "get_product_list_by_page": [{"productId": "99999", "name": "월간 투자 리포트", "price": 29900, "type": "SUBSCRIPTION", "paymentPeriod": "ONE_MONTH", "isDisplay": True, "viewSequence": 0}],
}

# product_page_list 호출 카운터 (첫 번째는 빈 목록, 두 번째부터 결과 반환)
_product_page_list_call_count = 0


def _get_mock(tool_name: str, **kwargs) -> dict | list:
    """Mock 응답을 반환합니다. 검색어에 따라 분기."""
    global _product_page_list_call_count

    if tool_name == "get_product_page_list":
        _product_page_list_call_count += 1
        if _product_page_list_call_count <= 1:
            return MOCK_RESPONSES["get_product_page_list"]
        return MOCK_RESPONSES["get_product_page_list_after"]

    # 검색어 기반 분기 (마스터 검색)
    keyword = kwargs.get("keyword", "")
    if tool_name == "search_masters" and keyword:
        if "조조형우" in keyword:
            return MOCK_RESPONSES["search_masters"]
        elif "김영익" in keyword:
            return [{"id": "mock_kim_001", "cmsId": "100", "name": "김영익", "createdAt": "2023-11-21", "publicType": "PUBLIC", "masterGroupId": "mock_group_kim", "masterGroupName": "김영익"}]
        else:
            return []  # 그 외 → 빈 결과 (마스터 없음)
    if tool_name == "get_master_groups" and keyword:
        if "조조형우" in keyword:
            return MOCK_RESPONSES["get_master_groups"]
        elif "김영익" in keyword:
            return {"masterGroups": [{"id": "mock_group_kim", "name": "김영익", "masterCount": 1}]}
        else:
            return {"masterGroups": []}  # 그 외 → 빈 결과

    return MOCK_RESPONSES.get(tool_name, {"mock": True, "tool": tool_name})


def _client() -> httpx.Client:
    print(f"🔐 _client() 토큰 길이={len(ADMIN_TOKEN)}")
    return httpx.Client(
        base_url=ADMIN_BASE,
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
        timeout=30.0,
    )


def _partner_client() -> httpx.Client:
    return httpx.Client(
        base_url=PARTNER_BASE,
        headers={"Authorization": f"Bearer {PARTNER_TOKEN}"},
        timeout=30.0,
    )


def _safe_request(r):
    """API 응답 처리. 에러 시 상세 정보 + 해결 가이드를 에이전트에 반환합니다."""
    if r.status_code >= 400:
        error = {
            "error": True,
            "status": r.status_code,
            "url": str(r.url),
            "method": r.request.method,
            "response_body": r.text[:1000],
            "request_body": r.request.content.decode()[:1000] if r.request.content else "",
        }
        # 에러 패턴별 해결 가이드 (OpenAI 린트 오류에 수정 지침 패턴)
        body = r.text.lower()
        if r.status_code == 401:
            error["guide"] = "인증 토큰이 만료되었습니다. 토큰 갱신이 필요합니다."
        elif "존재하지 않는 마스터" in body or "master not found" in body:
            error["guide"] = "masterId에 cmsId를 사용하세요 (MongoDB ObjectId가 아닌 cmsId='35' 형태). search_masters의 결과에서 cmsId를 확인하세요."
        elif "상시 공개 상품 페이지가 이미 존재" in body or "already exists" in body:
            error["guide"] = "이 마스터에 상시공개 상품 페이지가 이미 있습니다. get_product_page_list로 기존 페이지를 확인하세요."
        elif "contentids" in body or "contentids는 필수" in body:
            error["guide"] = "contentIds가 비어있습니다. get_series_list로 시리즈를 먼저 확인하고 contentIds에 시리즈 ID를 넣으세요."
        elif "productgroupid" in body:
            error["guide"] = "productGroupId가 잘못되었습니다. get_product_page_list로 상품 페이지 ID를 확인하세요."
        return error
    # 201 Created 등 body가 비어있는 경우
    if not r.text.strip():
        return {"success": True, "status": r.status_code}
    return r.json()


# ──────────────────────────────────────────────
# Phase 0: 마스터/시리즈 확인
# ──────────────────────────────────────────────


@tool
def get_master_groups(name: str = "") -> dict:
    """마스터 그룹 목록을 조회합니다. 마스터 그룹은 오피셜클럽의 상위 개념입니다.

    ⚠️ 마스터 그룹 ≠ 오피셜클럽. 오피셜클럽 검색은 search_masters를 사용하세요.
    ⚠️ 상품 페이지 생성에는 오피셜클럽의 cmsId가 필요합니다 (마스터 그룹 id가 아님).

    Args:
        name: 검색할 마스터 그룹명 (빈 문자열이면 전체 조회)

    예시: get_master_groups(name="조조형우")
    """
    if MOCK_MODE:
        return _get_mock("get_master_groups", keyword=name)
    params = {"offset": 0, "limit": 100}
    if name:
        params["name"] = name
    with _client() as c:
        r = c.get("/v1/master-groups", params=params)
        return _safe_request(r)


@tool
def create_master_group(name: str) -> dict:
    """마스터 그룹을 생성합니다. 이름만 넣으면 됩니다.

    Args:
        name: 마스터 그룹명
    """
    if MOCK_MODE:
        return _get_mock("create_master_group")
    with _client() as c:
        r = c.post("/v1/master-groups", json={"name": name})
        return _safe_request(r)


@tool
def search_masters(search_keyword: str = "", public_type: str = "ALL") -> dict:
    """오피셜클럽(마스터) 목록을 검색합니다. 상품 세팅의 첫 단계.

    ⚠️ 중요: 결과의 cmsId를 다른 모든 API의 masterId로 사용해야 합니다.
       id(MongoDB ObjectId)가 아닌 cmsId("1", "35", "136" 등)를 사용하세요.
    ⚠️ 마스터 그룹과 다릅니다. 마스터 그룹 검색은 get_master_groups를 사용하세요.

    Args:
        search_keyword: 검색어 (마스터/오피셜클럽 이름)
        public_type: 공개 상태 필터 (ALL, PUBLIC, PENDING, PRIVATE)

    Returns:
        마스터 목록. 각 항목: {id, cmsId, name, publicType, masterGroupId, masterGroupName}
        cmsId를 masterId로 사용. 예: cmsId="35" → create_product_page(master_id="35")

    예시: search_masters(search_keyword="조조형우")
    """
    if MOCK_MODE:
        return _get_mock("search_masters", keyword=search_keyword)
    params = {}
    if search_keyword:
        params["searchKeyword"] = search_keyword
        params["searchCategory"] = "NAME"
    if public_type != "ALL":
        params["publicType"] = public_type
    with _client() as c:
        r = c.get("/v1/masters", params=params)
        return _safe_request(r)


@tool
def get_master_detail(master_id: str) -> dict:
    """마스터(오피셜클럽) 상세 정보를 조회합니다.

    Args:
        master_id: 마스터 ID
    """
    if MOCK_MODE:
        return _get_mock("get_master_detail")
    with _client() as c:
        r = c.get(f"/v1/masters/{master_id}")
        return _safe_request(r)


@tool
def get_series_list(master_id: str) -> dict:
    """마스터의 시리즈 목록을 조회합니다. 상품 옵션(create_product)의 contentIds에 필수.

    ⚠️ 선행조건: search_masters로 마스터 존재를 먼저 확인해야 합니다.
    ⚠️ 시리즈가 없으면 상품 옵션을 만들 수 없습니다 (contentIds 빈 배열 불가).
       시리즈가 없으면 create_series로 먼저 생성하세요.
    ⚠️ master_id는 반드시 cmsId를 사용하세요.

    Args:
        master_id: 마스터 cmsId (예: "35", "136")

    예시: get_series_list(master_id="35")
    """
    if MOCK_MODE:
        return _get_mock("get_series_list")
    with _client() as c:
        r = c.get("/with-series", params={"masterId": master_id, "seriesState": "PUBLISHED"})
        return _safe_request(r)


@tool
def create_series(
    master_id: str,
    title: str,
    description: str,
    categories: list[str],
) -> dict:
    """시리즈를 생성합니다 (파트너센터 API). 상품 옵션에 연결할 시리즈가 없을 때 사용합니다.

    Args:
        master_id: 마스터 ID (CMS ID 형태, 예: 655bfe94c7dacf9f1db4ceaf)
        title: 시리즈 제목
        description: 시리즈 설명
        categories: 카테고리 배열 (1~3개). 가능한 값:
            secondaryBattery, realty, investment, domesticStock,
            economicTheory, foreignStock, cryptoCurrency,
            companyAnalysis, macroEconomics, personalFinance, safeAsset
    """
    if MOCK_MODE:
        return _get_mock("create_series")
    body = {
        "masterId": master_id,
        "title": title,
        "description": description,
        "category": categories,
        "imageUrl": PLACEHOLDER_IMAGE,
    }
    with _partner_client() as c:
        r = c.post("/v2/contents/series", json=body)
        return _safe_request(r)


# ──────────────────────────────────────────────
# Phase 2: 상품 페이지 생성
# ──────────────────────────────────────────────


@tool
def create_product_page(
    master_id: str,
    title: str,
    product_type: str,
    is_hidden: bool = False,
    is_changeable: bool = True,
    display_letter_status: str = "INACTIVE",
    is_always_public: bool = True,
    start_at: str = "",
    end_at: str = "",
    is_always_apply: bool = True,
    apply_start_at: str = "",
    apply_end_at: str = "",
) -> dict:
    """상품 페이지를 생성합니다. 플레이스홀더 이미지가 자동으로 포함됩니다.

    ⚠️ 선행조건: search_masters로 마스터 확인 + get_series_list로 시리즈 확인 완료 후 호출.
    ⚠️ master_id는 반드시 cmsId를 사용하세요 (MongoDB ObjectId 아님).
    ⚠️ 구독/단건 분기:
       - 구독: product_type="SUBSCRIPTION", is_changeable 선택 가능
       - 단건: product_type="ONE_TIME_PURCHASE", is_changeable=False 고정
    ⚠️ 상시공개 페이지는 마스터당 1개만 가능. 이미 있으면 400 에러.

    Args:
        master_id: 마스터 cmsId (예: "35")
        title: 페이지명 (관리자용, 고객 미노출)
        product_type: 상품 타입 (SUBSCRIPTION 또는 ONE_TIME_PURCHASE)
        is_hidden: 히든 처리 여부
        is_changeable: 상품 변경 가능 여부 (구독만, 단건은 false)
        display_letter_status: 편지글 공개 (ACTIVE/INACTIVE)
        is_always_public: 상시 공개 여부
        start_at: 공개 시작일 (YYYY-MM-DD, is_always_public=false일 때)
        end_at: 공개 종료일
        is_always_apply: 상시 신청 여부
        apply_start_at: 신청 시작일
        apply_end_at: 신청 종료일
    """
    if MOCK_MODE:
        return _get_mock("create_product_page")
    body = {
        "masterId": master_id,
        "title": title,
        "type": product_type,
        "status": "INACTIVE",  # 비공개로 시작, 이미지 교체 후 활성화
        "isHidden": is_hidden,
        "isChangeable": is_changeable if product_type == "SUBSCRIPTION" else False,
        "displayLetterStatus": display_letter_status,
        "isAlwaysPublic": is_always_public,
        "isAlwaysApply": is_always_apply,
        "mainContents": [{
            "type": "IMAGE",
            "contentUrl": PLACEHOLDER_IMAGE,
            "isAlwaysPublic": True,
        }],
        "contents": [{
            "imageUrl": PLACEHOLDER_IMAGE,
            "isAlwaysPublic": True,
            "sequence": 0,
        }],
    }
    if not is_always_public and start_at and end_at:
        body["startAt"] = start_at
        body["endAt"] = end_at
    if not is_always_apply and apply_start_at and apply_end_at:
        body["applyStartAt"] = apply_start_at
        body["applyEndAt"] = apply_end_at

    with _client() as c:
        r = c.post("/v1/product-group", json=body)
        return _safe_request(r)


# ──────────────────────────────────────────────
# Phase 3: 상품 옵션 등록
# ──────────────────────────────────────────────


@tool
def create_product(
    product_group_id: str,
    name: str,
    origin_price: int,
    content_ids: list[str],
    display_texts: list[str],
    is_display: bool = True,
    is_display_recommend: bool = False,
    tags: list[str] | None = None,
    payment_period: str = "",
    usage_period_type: str = "",
    use_duration: int = 0,
    use_start_at: str = "",
    use_end_at: str = "",
    promotion_type: str = "",
    discount_type: str = "",
    discount_value: float = 0,
    subscription_counts: list[int] | None = None,
    promo_start_at: str = "",
    promo_end_at: str = "",
    is_always_promotion: bool = False,
) -> dict:
    """상품 옵션을 등록합니다. 고객이 실제로 구매하는 단위.

    ⚠️ 선행조건: create_product_page로 상품 페이지 생성 + get_series_list로 시리즈 확인 완료 후 호출.
    ⚠️ contentIds는 필수이며 빈 배열 불가. 반드시 get_series_list로 시리즈를 먼저 확인하세요.
    ⚠️ 구독/단건 분기 (중요!):
       - 구독: paymentPeriod 사용 (ONE_MONTH 등). usagePeriodType 사용 금지.
       - 단건: usagePeriodType + useDuration 사용. paymentPeriod 사용 금지.
    ⚠️ 단건 프로모션: REGULAR_DISCOUNT(상시 할인)만 가능. SUBSCRIPTION_COUNT_DISCOUNT 사용 금지.

    Args:
        product_group_id: 상품 페이지 ID (get_product_page_list에서 확인한 ID)
        name: 상품명 (고객 노출)
        origin_price: 정상가 (원)
        content_ids: 포함할 시리즈 ID 배열
        display_texts: 상품 구성 텍스트 배열 (예: ["시리즈A 이용권", "교재 제공"])
        is_display: 노출 여부
        is_display_recommend: BEST PICK 뱃지 표시
        tags: 태그 배열 (7자 이내, 최대 2개)
        payment_period: 결제 주기 - 구독 상품 (ONE_MONTH, THREE_MONTH, SIX_MONTH, ONE_YEAR 등)
        usage_period_type: 이용 기간 유형 - 단건 상품 (DURATION 또는 DATE_RANGE)
        use_duration: 이용 일수 (usage_period_type=DURATION일 때)
        use_start_at: 이용 시작일 (usage_period_type=DATE_RANGE일 때, YYYY-MM-DD)
        use_end_at: 이용 종료일
        promotion_type: 프로모션 타입 (REGULAR_DISCOUNT 또는 SUBSCRIPTION_COUNT_DISCOUNT)
        discount_type: 할인 방식 (PERCENT 또는 AMOUNT)
        discount_value: 할인 값 (% 또는 원)
        subscription_counts: 할인 적용 회차 배열 (예: [1,2,3] = 1~3회차)
        promo_start_at: 프로모션 시작일
        promo_end_at: 프로모션 종료일
        is_always_promotion: 상시 프로모션 여부
    """
    if MOCK_MODE:
        return _get_mock("create_product")
    body: dict = {
        "productGroupId": product_group_id,
        "name": name,
        "originPrice": origin_price,
        "contentIds": content_ids,
        "displayTexts": display_texts,
        "isDisplay": is_display,
        "isDisplayRecommend": is_display_recommend,
    }
    if tags:
        body["tags"] = tags

    # 구독 상품
    if payment_period:
        body["paymentPeriod"] = payment_period

    # 단건 상품
    if usage_period_type:
        body["usagePeriodType"] = usage_period_type
        if usage_period_type == "DURATION" and use_duration > 0:
            body["useDuration"] = use_duration
        elif usage_period_type == "DATE_RANGE" and use_start_at and use_end_at:
            body["useStartAt"] = use_start_at
            body["useEndAt"] = use_end_at

    # 프로모션
    if promotion_type and discount_type and discount_value > 0:
        body["promotionType"] = promotion_type
        if promotion_type == "REGULAR_DISCOUNT":
            body["regularDiscountPromotion"] = {
                "discountType": discount_type,
                "discountValue": discount_value,
            }
        elif promotion_type == "SUBSCRIPTION_COUNT_DISCOUNT":
            body["subscriptionCountDiscountPromotion"] = {
                "discountType": discount_type,
                "discountValue": discount_value,
                "subscriptionCounts": subscription_counts or [1],
                "startAt": promo_start_at,
                "endAt": promo_end_at,
                "isAlwaysPromotion": is_always_promotion,
                "isActive": True,
            }

    with _client() as c:
        r = c.post("/v1/product", json=body)
        return _safe_request(r)


# ──────────────────────────────────────────────
# Phase 4: 활성화
# ──────────────────────────────────────────────


@tool
def update_product_display(product_id: str, is_display: bool = True) -> dict:
    """상품 옵션의 노출 상태를 변경합니다.

    Args:
        product_id: 상품 ID
        is_display: 노출 여부
    """
    if MOCK_MODE:
        return _get_mock("update_product_display")
    with _client() as c:
        r = c.patch("/v1/product/display", json={"id": product_id, "isDisplay": is_display})
        return _safe_request(r)


@tool
def update_product_sequence(product_group_id: str, product_ids: list[str]) -> dict:
    """상품 옵션의 노출 순서를 변경합니다.

    Args:
        product_group_id: 상품 페이지 ID
        product_ids: 상품 ID 배열 (원하는 순서대로)
    """
    if MOCK_MODE:
        return _get_mock("update_product_sequence")
    with _client() as c:
        r = c.patch(f"/v1/product/group/{product_group_id}/sequence", json={"ids": product_ids})
        return _safe_request(r)


@tool
def update_product_page_status(product_page_id: str, status: str = "ACTIVE") -> dict:
    """상품 페이지의 공개 상태를 변경합니다.

    Args:
        product_page_id: 상품 페이지 ID
        status: 상태 (ACTIVE 또는 INACTIVE)
    """
    if MOCK_MODE:
        return _get_mock("update_product_page_status")
    with _client() as c:
        r = c.patch("/v1/product-group/status", json={"id": product_page_id, "status": status})
        return _safe_request(r)


@tool
def update_main_product_setting(
    master_id: str,
    view_status: str = "ACTIVE",
    product_group_type: str = "US_PLUS",
) -> dict:
    """메인 상품 페이지 설정을 변경합니다. 이 설정이 ACTIVE여야 고객에게 상품이 노출됩니다.

    ⚠️ 선행조건: update_product_page_status로 상품 페이지를 ACTIVE로 변경한 후 호출.
    ⚠️ 활성화 순서: update_product_display → update_product_sequence → update_product_page_status → 이 Tool.
    ⚠️ 2레벨 노출: 마스터 공개(PUBLIC) + 이 설정(ACTIVE) 둘 다 충족해야 고객에게 보임.

    Args:
        master_id: 마스터 cmsId (예: "35")
        view_status: 노출 상태 (ACTIVE, INACTIVE, EXCLUDED)
        product_group_type: 상품 그룹 타입 (US_PLUS 또는 US_CAMPUS)
    """
    if MOCK_MODE:
        return _get_mock("update_main_product_setting")
    body = {
        "productGroupType": product_group_type,
        "productGroupViewStatus": view_status,
        "isProductGroupWebLinkStatus": "INACTIVE",
        "isProductGroupAppLinkStatus": "INACTIVE",
    }
    with _client() as c:
        r = c.patch(f"/v1/masters/{master_id}/main-product-group", json=body)
        return _safe_request(r)


# ──────────────────────────────────────────────
# Phase 5: 검증
# ──────────────────────────────────────────────


@tool
def get_product_page_list(master_id: str) -> dict:
    """마스터(오피셜클럽)의 상품 페이지 목록을 조회합니다. masterId는 cmsId를 사용합니다.

    Args:
        master_id: 마스터 cmsId (예: "136")
    """
    if MOCK_MODE:
        return _get_mock("get_product_page_list")
    with _client() as c:
        r = c.get("/v1/product-group", params={"masterId": master_id})
        return _safe_request(r)


@tool
def get_product_page_detail(product_page_id: str) -> dict:
    """상품 페이지 상세 정보를 조회합니다. 검증용.

    Args:
        product_page_id: 상품 페이지 ID
    """
    if MOCK_MODE:
        return _get_mock("get_product_page_detail")
    with _client() as c:
        r = c.get(f"/v1/product-group/{product_page_id}")
        return _safe_request(r)


@tool
def get_product_list_by_page(product_page_id: str) -> dict:
    """상품 페이지에 등록된 상품 옵션 목록을 조회합니다. 검증용.

    Args:
        product_page_id: 상품 페이지 ID
    """
    if MOCK_MODE:
        return _get_mock("get_product_list_by_page")
    with _client() as c:
        r = c.get(f"/v1/product/group/{product_page_id}", params={"publishStatus": "all"})
        return _safe_request(r)


# ──────────────────────────────────────────────
# Phase 5: 탐색 에이전트에 검증 요청
# ──────────────────────────────────────────────


@tool
def verify_product_setup(
    product_group_code: int,
    master_id: str,
    master_display_index: int,
    master_name: str,
    product_name: str = "",
    price: int = 0,
    product_count: int = 0,
) -> dict:
    """상품 세팅 완료 후 탐색 에이전트에 검증을 요청합니다.

    탐색 에이전트가 구독 탭 노출 여부, 상품 페이지 내용을 검증합니다.
    Phase 4(활성화) 완료 후에 호출해야 합니다.

    Args:
        product_group_code: 상품 페이지 코드 (예: 148)
        master_id: 마스터 cmsId (예: "35")
        master_display_index: ACTIVE 마스터 중 노출 순서 (1-based)
        master_name: 오피셜클럽 이름 (예: "조조형우")
        product_name: 상품명 (선택)
        price: 금액 (선택)
        product_count: 상품 옵션 수 (선택)
    """
    expected = {
        "masterDisplayIndex": master_display_index,
        "productGroupViewStatus": "ACTIVE",
        "masterName": master_name,
    }
    if product_name:
        expected["productName"] = product_name
    if price:
        expected["price"] = price
    if product_count:
        expected["productCount"] = product_count

    try:
        resp = requests.post(
            f"{EXPLORER_AGENT_URL}/verify",
            json={
                "type": "product_page",
                "target": {
                    "productGroupCode": product_group_code,
                    "masterId": master_id,
                },
                "expected": expected,
                "level": "full",
            },
            timeout=120,
        )
        return resp.json()
    except requests.ConnectionError:
        return {
            "status": "error",
            "summary": f"탐색 에이전트({EXPLORER_AGENT_URL})에 연결할 수 없습니다. 서버가 실행 중인지 확인하세요.",
        }
    except Exception as e:
        return {"status": "error", "summary": f"검증 요청 실패: {e}"}
