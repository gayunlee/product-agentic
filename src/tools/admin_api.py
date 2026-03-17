"""
관리자센터 API Tools for Strands Agent.

에이전트가 관리자센터 API를 호출할 수 있도록 Tool로 래핑.
각 함수는 @tool 데코레이터로 에이전트에 노출됨.
"""

import os
import httpx
from strands import tool

ADMIN_BASE = os.environ.get("ADMIN_API_BASE_URL", "")
ADMIN_TOKEN = os.environ.get("ADMIN_API_TOKEN", "")
PARTNER_BASE = os.environ.get("PARTNER_API_BASE_URL", "")
PARTNER_TOKEN = os.environ.get("PARTNER_API_TOKEN", "")
PLACEHOLDER_IMAGE = "https://placehold.co/990x1100/e8e8e8/999?text=PLACEHOLDER"


def _client() -> httpx.Client:
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
    """API 응답 처리. 에러 시 상세 정보를 에이전트에 반환합니다."""
    if r.status_code >= 400:
        return {
            "error": True,
            "status": r.status_code,
            "url": str(r.url),
            "method": r.request.method,
            "response_body": r.text[:1000],
            "request_body": r.request.content.decode()[:1000] if r.request.content else "",
        }
    return r.json()


# ──────────────────────────────────────────────
# Phase 0: 마스터/시리즈 확인
# ──────────────────────────────────────────────


@tool
def get_master_groups() -> dict:
    """마스터 그룹 목록을 조회합니다. 마스터 생성 시 masterGroupId가 필요합니다."""
    with _client() as c:
        r = c.get("/v1/master-groups", params={"offset": 0, "limit": 100})
        return _safe_request(r)


@tool
def search_masters(search_keyword: str = "", public_type: str = "ALL") -> dict:
    """마스터(오피셜클럽) 목록을 검색합니다.

    Args:
        search_keyword: 검색어 (마스터 이름)
        public_type: 공개 상태 필터 (ALL, PUBLIC, PENDING, PRIVATE)
    """
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
    with _client() as c:
        r = c.get(f"/v1/masters/{master_id}")
        return _safe_request(r)


@tool
def get_series_list(master_id: str) -> dict:
    """마스터의 시리즈 목록을 조회합니다. 상품 옵션 생성 시 contentIds로 사용됩니다.

    Args:
        master_id: 마스터 ID
    """
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

    Args:
        master_id: 마스터 ID
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
    """상품 옵션을 등록합니다.

    Args:
        product_group_id: 상품 페이지 ID (create_product_page에서 받은 ID)
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

    Args:
        master_id: 마스터 ID
        view_status: 노출 상태 (ACTIVE, INACTIVE, EXCLUDED)
        product_group_type: 상품 그룹 타입 (US_PLUS 또는 US_CAMPUS)
    """
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
def get_product_page_detail(product_page_id: str) -> dict:
    """상품 페이지 상세 정보를 조회합니다. 검증용.

    Args:
        product_page_id: 상품 페이지 ID
    """
    with _client() as c:
        r = c.get(f"/v1/product-group/{product_page_id}")
        return _safe_request(r)


@tool
def get_product_list_by_page(product_page_id: str) -> dict:
    """상품 페이지에 등록된 상품 옵션 목록을 조회합니다. 검증용.

    Args:
        product_page_id: 상품 페이지 ID
    """
    with _client() as c:
        r = c.get(f"/v1/product/group/{product_page_id}", params={"publishStatus": "all"})
        return _safe_request(r)
