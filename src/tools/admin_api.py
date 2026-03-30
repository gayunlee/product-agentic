"""
관리자센터 API Tools.

에이전트가 관리자센터 API를 호출할 수 있도록 Tool로 래핑.
각 함수는 @tool 데코레이터로 에이전트에 노출됨.
Strands SDK tool 형식 사용.
"""

import os
import httpx
from strands import tool

ADMIN_BASE = os.environ.get("ADMIN_API_BASE_URL", "")
ADMIN_TOKEN = os.environ.get("ADMIN_API_TOKEN", "")
PARTNER_BASE = os.environ.get("PARTNER_API_BASE_URL", "")
PARTNER_TOKEN = os.environ.get("PARTNER_API_TOKEN", "")
PLACEHOLDER_IMAGE = "https://placehold.co/990x1100/e8e8e8/999?text=PLACEHOLDER"
MOCK_MODE = os.environ.get("MOCK_MODE", "").lower() in ("true", "1", "yes")

# Mock 응답 데이터
MOCK_RESPONSES = {
    "get_master_groups": {"masterGroups": [
        {"id": "69b37159193f23cd69de4df7", "name": "조조형우의 클럽", "masterCount": 1},
    ]},
    "search_masters": [
        {"id": "673301e25aa67ba37f477759", "cmsId": "35", "name": "조조형우", "createdAt": "2024-11-12", "publicType": "PUBLIC", "masterGroupId": "69b37159193f23cd69de4df7", "masterGroupName": "조조형우의 클럽"},
    ],
    "get_master_detail": {"cmsId": "35", "name": "조조형우", "displayName": "조조형우", "clubPublicType": "PUBLIC", "clubName": "조조형우", "productGroupViewStatus": "INACTIVE", "masterDisplayIndex": 10},
    "get_series_list": {"masters": [{"_id": "673301e25aa67ba37f477759", "name": "조조형우", "series": [
        {"_id": "mock_series_001", "title": "투자 기초 시리즈"},
        {"_id": "mock_series_002", "title": "경제 분석 리포트"},
    ]}]},
    "get_product_page_list": [
        {"id": "mock_page_001", "title": "월간 투자 리포트 페이지", "status": "ACTIVE", "code": 148, "isAlwaysPublic": True, "isAlwaysApply": True, "startAt": "1970.01.01", "endAt": "9999.12.31", "applyStartAt": "1970-01-01", "applyEndAt": "9999-12-31", "createdAt": "2026-03-18", "isDeletable": True},
        {"id": "mock_page_002", "title": "단건 특강", "status": "INACTIVE", "code": 155, "isAlwaysPublic": False, "isAlwaysApply": True, "startAt": "2026-03-01", "endAt": "2026-03-31", "createdAt": "2026-03-10", "isDeletable": True},
    ],
    "update_product_display": {"success": True, "status": 200},
    "update_product_page_status": {"success": True, "status": 200},
    "update_product_page": {"success": True, "status": 200},
    "update_main_product_setting": {"success": True, "status": 200},
    "get_product_page_detail": {"id": "mock_page_001", "masterId": "35", "title": "월간 투자 리포트 페이지", "status": "ACTIVE", "type": "SUBSCRIPTION", "code": 148, "isAlwaysPublic": True, "isChangeable": True, "isHidden": False, "mainContents": [{"type": "IMAGE", "contentUrl": PLACEHOLDER_IMAGE}], "contents": [{"imageUrl": PLACEHOLDER_IMAGE, "sequence": 0}]},
    "get_product_list_by_page": [{"productId": "99999", "name": "월간 투자 리포트", "price": 29900, "type": "SUBSCRIPTION", "paymentPeriod": "ONE_MONTH", "isDisplay": True, "viewSequence": 0}],
    "get_community_settings": {"postBoardActiveStatus": "ACTIVE", "postBoardName": "게시판", "donationActiveStatus": "ACTIVE"},
    "navigate": {"url": "/product", "label": "상품 페이지 목록"},
}

def _get_mock(tool_name: str, **kwargs) -> dict | list:
    """Mock 응답을 반환합니다. 검색어에 따라 분기."""

    # 검색어 기반 분기 (마스터 검색)
    keyword = kwargs.get("keyword", "")
    if tool_name == "search_masters":
        if not keyword:
            # 키워드 없으면 전체 목록 (위저드용)
            return {"masters": [
                {"id": "mock_001", "cmsId": "35", "name": "조조형우", "publicType": "PUBLIC"},
                {"id": "mock_002", "cmsId": "100", "name": "김영익", "publicType": "PUBLIC"},
                {"id": "mock_003", "cmsId": "42", "name": "봄날의 햇살", "publicType": "PUBLIC"},
            ]}
        if "조조형우" in keyword:
            return MOCK_RESPONSES["search_masters"]
        elif "김영익" in keyword:
            return {"masters": [{"id": "mock_kim_001", "cmsId": "100", "name": "김영익", "createdAt": "2023-11-21", "publicType": "PUBLIC", "masterGroupId": "mock_group_kim", "masterGroupName": "김영익"}]}
        else:
            return {"masters": []}  # 그 외 → 빈 결과 (마스터 없음)
    if tool_name == "get_master_groups" and keyword:
        if "조조형우" in keyword:
            return MOCK_RESPONSES["get_master_groups"]
        elif "김영익" in keyword:
            return {"masterGroups": [{"id": "mock_group_kim", "name": "김영익", "masterCount": 1}]}
        else:
            return {"masterGroups": []}  # 그 외 → 빈 결과

    return MOCK_RESPONSES.get(tool_name, {"mock": True, "tool": tool_name})


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
# 조회 Tools
# ──────────────────────────────────────────────


@tool
def get_master_groups(name: str = "") -> dict:
    """마스터 그룹 목록을 조회합니다. 마스터 그룹은 오피셜클럽의 상위 개념입니다.

    선행 조건: 없음 (첫 단계)
    주의: 마스터 그룹 ≠ 오피셜클럽. 오피셜클럽 검색은 search_masters를 사용하세요.
    주의: 상품 페이지 생성에는 오피셜클럽의 cmsId가 필요합니다 (마스터 그룹 id가 아님).

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
def search_masters(search_keyword: str = "", public_type: str = "ALL") -> dict:
    """오피셜클럽(마스터) 목록을 검색합니다. 상품 세팅의 첫 단계.

    선행 조건: 없음 (첫 단계)
    주의: searchKeyword가 정확하지 않아도 부분 매칭됨
    주의: 결과의 cmsId를 다른 모든 API의 masterId로 사용해야 합니다.
       id(MongoDB ObjectId)가 아닌 cmsId("1", "35", "136" 등)를 사용하세요.

    Args:
        search_keyword: 검색어 (마스터/오피셜클럽 이름)
        public_type: 공개 상태 필터 (ALL, PUBLIC, PENDING, PRIVATE)

    Returns:
        마스터 목록. 각 항목: {id, cmsId, name, publicType, masterGroupId, masterGroupName}
        cmsId를 masterId로 사용.

    예시: search_masters(search_keyword="조조형우") → cmsId 확보
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

    선행 조건: master_id (cmsId) 필수
    주의: master_id는 cmsId를 사용하세요.

    Args:
        master_id: 마스터 cmsId (예: "35")
    """
    if MOCK_MODE:
        return _get_mock("get_master_detail")
    with _client() as c:
        r = c.get(f"/v1/masters/{master_id}")
        return _safe_request(r)


@tool
def get_series_list(master_id: str) -> dict:
    """마스터의 시리즈 목록을 조회합니다.

    선행 조건: search_masters로 마스터 존재를 먼저 확인해야 합니다.
    주의: 시리즈가 없으면 상품 옵션을 만들 수 없습니다.
    주의: master_id는 반드시 cmsId를 사용하세요.

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
def get_product_page_list(master_id: str) -> dict:
    """마스터(오피셜클럽)의 상품 페이지 목록을 조회합니다.

    선행 조건: master_id (cmsId) 필수
    주의: masterId는 cmsId를 사용합니다.

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
    """상품 페이지 상세 정보를 조회합니다.

    선행 조건: product_page_id 필수
    용도: 상품 페이지의 상태, 히든 여부, 편지글 설정 등 상세 확인

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
    """상품 페이지에 등록된 상품 옵션 목록을 조회합니다.

    선행 조건: product_page_id 필수
    용도: 상품 옵션의 공개 상태, 가격, 타입 등 확인

    Args:
        product_page_id: 상품 페이지 ID
    """
    if MOCK_MODE:
        return _get_mock("get_product_list_by_page")
    with _client() as c:
        r = c.get(f"/v1/product/group/{product_page_id}", params={"publishStatus": "all"})
        return _safe_request(r)


@tool
def get_community_settings(cms_id: str) -> dict:
    """오피셜클럽의 커뮤니티 설정(게시판, 응원하기 상태)을 조회합니다.

    선행 조건: cms_id (오피셜클럽의 cmsId) 필수
    용도: 게시판(postBoardActiveStatus), 응원하기(donationActiveStatus) 상태 확인
    시나리오: 게시판이 안 보이는 경우, 응원하기가 안 보이는 경우 진단에 사용

    Args:
        cms_id: 오피셜클럽의 cmsId (예: "35")

    Returns:
        {postBoardActiveStatus, postBoardName, donationActiveStatus}
    """
    if MOCK_MODE:
        return _get_mock("get_community_settings")
    with _client() as c:
        r = c.get(f"/v1/master/{cms_id}/community/category")
        return _safe_request(r)


# ──────────────────────────────────────────────
# 변경(Mutation) Tools
# ──────────────────────────────────────────────


@tool
def update_product_display(product_id: str, is_display: bool = True) -> dict:
    """상품 옵션의 노출 상태를 변경합니다.

    비공개로 변경 시 자동으로 계단식 영향을 검증합니다.
    마지막 공개 상품을 비공개하면 경고와 함께 페이지 비공개 제안을 반환합니다.

    Args:
        product_id: 상품 ID
        is_display: 노출 여부
    """
    # 비공개 시 계단식 검증 (Tool 내부 강제)
    if not is_display and not MOCK_MODE:
        # 이 상품이 속한 페이지의 다른 공개 상품 확인
        # product_id로 직접 페이지를 찾을 수 없으므로, 상품 상세에서 productGroupId 추출
        with _client() as c:
            product_detail = c.get(f"/v1/product/{product_id}")
            if product_detail.status_code == 200:
                product_data = product_detail.json()
                page_id = product_data.get("productGroupId", "")
                if page_id:
                    products_resp = c.get(f"/v1/product/group/{page_id}", params={"publishStatus": "all"})
                    if products_resp.status_code == 200:
                        products = products_resp.json() if isinstance(products_resp.json(), list) else []
                        displayed_others = [
                            p for p in products
                            if p.get("isDisplay", False)
                            and str(p.get("productId", p.get("id", ""))) != str(product_id)
                        ]
                        if len(displayed_others) == 0:
                            return {
                                "warning": True,
                                "message": "⚠️ 이 상품이 마지막 공개 상품입니다. "
                                           "비공개 처리하면 상품페이지에 상품이 0개가 되어 빈 페이지가 표시됩니다. "
                                           "상품페이지도 비공개 처리하시겠어요?",
                                "suggested_action": {
                                    "label": "상품페이지도 비공개 처리",
                                    "action": "update_product_page_status",
                                    "params": {"product_page_id": page_id, "status": "INACTIVE"},
                                },
                                "proceed_anyway_label": "상품만 비공개 (페이지는 유지)",
                            }

    if MOCK_MODE:
        return _get_mock("update_product_display")
    with _client() as c:
        r = c.patch("/v1/product/display", json={"id": product_id, "isDisplay": is_display})
        return _safe_request(r)


@tool
def batch_update_product_display(product_page_id: str, is_display: bool = False) -> dict:
    """상품 페이지의 모든 상품을 한번에 공개/비공개 처리합니다.

    "전부 비공개해줘", "다 비공개", "모두 비공개" 요청 시 사용.
    개별 상품을 하나씩 처리하고, 마지막 상품일 때 계단식 경고를 반환합니다.

    Args:
        product_page_id: 상품 페이지 ID
        is_display: 노출 여부 (False=전부 비공개, True=전부 공개)
    """
    if MOCK_MODE:
        return _get_mock("update_product_display")

    with _client() as c:
        # 1. 해당 페이지의 상품 목록 조회
        products_resp = c.get(f"/v1/product/group/{product_page_id}", params={"publishStatus": "all"})
        if products_resp.status_code >= 400:
            return _safe_request(products_resp)

        products = products_resp.json() if isinstance(products_resp.json(), list) else []
        if not products:
            return {"error": True, "message": "상품이 없습니다."}

        # 2. 대상 상품 필터 (이미 원하는 상태인 건 제외)
        targets = [
            p for p in products
            if p.get("isDisplay", False) != is_display
        ]
        if not targets:
            return {
                "message": f"모든 상품이 이미 {'공개' if is_display else '비공개'} 상태입니다.",
                "changed": 0,
            }

        # 3. 전부 비공개 시 계단식 경고
        if not is_display:
            all_displayed = [p for p in products if p.get("isDisplay", False)]
            if len(all_displayed) > 0 and len(all_displayed) == len(targets):
                # 모든 공개 상품이 비공개 대상 → 페이지에 상품 0개
                return {
                    "warning": True,
                    "message": f"⚠️ {len(targets)}개 상품을 모두 비공개하면 상품페이지에 상품이 0개가 됩니다. "
                               "상품페이지도 비공개 처리하시겠어요?",
                    "targets": [{"id": str(p.get("productId", p.get("id", ""))), "name": p.get("name", "")} for p in targets],
                    "suggested_action": {
                        "label": "상품 전부 비공개 + 페이지도 비공개",
                        "action": "batch_and_page_inactive",
                        "params": {"product_page_id": product_page_id},
                    },
                    "proceed_anyway_label": "상품만 전부 비공개 (페이지는 유지)",
                }

        # 4. 실행
        results = []
        for p in targets:
            pid = str(p.get("productId", p.get("id", "")))
            r = c.patch("/v1/product/display", json={"id": pid, "isDisplay": is_display})
            results.append({"id": pid, "name": p.get("name", ""), "success": r.status_code < 400})

        action = "공개" if is_display else "비공개"
        return {
            "message": f"{len(results)}개 상품 {action} 처리 완료",
            "changed": len(results),
            "results": results,
        }


@tool
def update_product_page_status(product_page_id: str, status: str = "ACTIVE") -> dict:
    """상품 페이지의 공개 상태를 변경합니다.

    INACTIVE로 변경 시 자동으로 계단식 영향을 검증합니다.
    마지막 공개 페이지를 비공개하면 경고와 함께 메인 EXCLUDED 제안을 반환합니다.

    Args:
        product_page_id: 상품 페이지 ID
        status: 상태 (ACTIVE 또는 INACTIVE)
    """
    # 비공개 시 계단식 검증 (Tool 내부 강제)
    if status == "INACTIVE" and not MOCK_MODE:
        # 이 페이지의 master_id 확인
        with _client() as c:
            detail = c.get(f"/v1/product-group/{product_page_id}")
            if detail.status_code == 200:
                page_data = detail.json()
                master_id = page_data.get("masterId", "")
                if master_id:
                    # 같은 마스터의 다른 공개 페이지 확인
                    pages_resp = c.get("/v1/product-group", params={"masterId": master_id})
                    if pages_resp.status_code == 200:
                        pages = pages_resp.json() if isinstance(pages_resp.json(), list) else []
                        active_others = [p for p in pages if p.get("status") == "ACTIVE" and str(p.get("id")) != str(product_page_id)]
                        if len(active_others) == 0:
                            return {
                                "warning": True,
                                "message": "⚠️ 이 페이지가 마지막 공개 페이지입니다. "
                                           "비공개 처리하면 모든 상품페이지가 비공개되고, "
                                           "메인 상품페이지 버튼 클릭 시 404가 발생합니다. "
                                           "메인 상품페이지도 EXCLUDED 처리하시겠어요?",
                                "suggested_action": {
                                    "label": "메인도 EXCLUDED 처리",
                                    "action": "update_main_product_setting",
                                    "params": {"master_id": master_id, "view_status": "EXCLUDED"},
                                },
                                "proceed_anyway_label": "비공개만 처리 (메인은 유지)",
                            }

    if MOCK_MODE:
        return _get_mock("update_product_page_status")
    with _client() as c:
        r = c.patch("/v1/product-group/status", json={"id": product_page_id, "status": status})
        return _safe_request(r)


@tool
def update_product_page(product_page_id: str, updates: dict) -> dict:
    """상품 페이지의 속성을 변경합니다.

    현재 데이터를 자동으로 조회한 뒤, 변경할 필드만 덮어쓰고 전체 데이터로 PATCH합니다.
    부분 업데이트를 지원하지 않는 API 제약을 내부에서 처리합니다.

    선행 조건: product_page_id 필수
    주의: 반드시 유저 확인 후 실행.
    용도: isHidden, displayLetterStatus, title, 공개기간(startAt/endAt/isAlwaysPublic) 등

    Args:
        product_page_id: 상품 페이지 ID
        updates: 변경할 필드 딕셔너리 (예: {"isHidden": true}, {"startAt": "2026-04-01", "endAt": "2026-04-30"})

    예시:
        update_product_page("148", {"isHidden": true})
        update_product_page("148", {"startAt": "2026-04-01", "endAt": "2026-04-30", "isAlwaysPublic": false})
    """
    if MOCK_MODE:
        return _get_mock("update_product_page")

    # PATCH API가 전체 필드를 요구하므로, 현재 데이터를 먼저 조회하여 병합
    PATCH_REQUIRED_FIELDS = [
        "title", "status", "type", "isAlwaysPublic", "startAt", "endAt",
        "isAlwaysApply", "applyStartAt", "applyEndAt",
        "isHidden", "isChangeable", "displayLetterStatus",
        "contents", "mainContents",
    ]

    with _client() as c:
        # 1. 현재 데이터 조회
        detail_resp = c.get(f"/v1/product-group/{product_page_id}")
        if detail_resp.status_code >= 400:
            return {"error": True, "message": f"상품 페이지 조회 실패: {detail_resp.status_code}"}
        current = detail_resp.json()

        # 2. 히든 해제 시 기간 충돌 검사 (API가 수정 시에는 안 막으므로 Tool에서 강제)
        if updates.get("isHidden") is False and current.get("isHidden") is True:
            # masterId가 상세 API에 없으므로 masterName으로 검색
            master_id = ""
            master_name = current.get("masterName", "")
            if master_name:
                search_resp = c.get("/v1/masters", params={"searchKeyword": master_name})
                if search_resp.status_code == 200:
                    masters = search_resp.json()
                    if isinstance(masters, list) and masters:
                        master_id = str(masters[0].get("cmsId", ""))
            if master_id and not current.get("isAlwaysPublic", True):
                target_start = updates.get("startAt", current.get("startAt", ""))
                target_end = updates.get("endAt", current.get("endAt", ""))
                # 같은 마스터의 비히든 ACTIVE 페이지 확인
                pages_resp = c.get("/v1/product-group", params={"masterId": master_id})
                if pages_resp.status_code == 200:
                    for page in pages_resp.json():
                        if page.get("id") == product_page_id or page.get("status") != "ACTIVE":
                            continue
                        p_detail = c.get(f"/v1/product-group/{page['id']}")
                        if p_detail.status_code != 200:
                            continue
                        p = p_detail.json()
                        if p.get("isHidden", False):
                            continue
                        if p.get("isAlwaysPublic", False):
                            return {
                                "warning": True,
                                "message": f"히든 해제 시 기간 충돌: '{p.get('title', '')}' 페이지가 상시공개 상태입니다. "
                                           f"히든을 해제하면 상시공개 페이지가 비활성화됩니다.",
                            }
                        p_start = p.get("startAt", "")
                        p_end = p.get("endAt", "")
                        if target_start and target_end and p_start and p_end:
                            if target_start <= p_end and target_end >= p_start:
                                return {
                                    "warning": True,
                                    "message": f"히든 해제 시 기간 충돌: '{p.get('title', '')}' 페이지와 "
                                               f"공개기간이 겹칩니다 ({p_start}~{p_end}).",
                                }

        # 3. 필수 필드를 현재 데이터에서 가져오고, updates로 덮어쓰기
        body = {"id": product_page_id}
        for field in PATCH_REQUIRED_FIELDS:
            body[field] = current.get(field)
        body.update(updates)

        # 4. PATCH 실행
        r = c.patch("/v1/product-group", json=body)
        return _safe_request(r)


@tool
def update_main_product_setting(
    master_id: str,
    view_status: str = "ACTIVE",
    product_group_type: str = "US_PLUS",
    web_link: str = "",
) -> dict:
    """메인 상품 페이지 설정을 변경합니다. 이 설정이 ACTIVE여야 고객에게 상품이 노출됩니다.

    선행 조건: master_id (cmsId) 필수
    주의: 2레벨 노출 — 마스터 공개(PUBLIC) + 이 설정(ACTIVE) 둘 다 충족해야 고객에게 보임.
    주의: 반드시 유저 확인 후 실행.
    주의: web_link를 설정하면 isProductGroupWebLinkStatus도 ACTIVE로 설정됩니다.

    Args:
        master_id: 마스터 cmsId (예: "35")
        view_status: 노출 상태 (ACTIVE, INACTIVE, EXCLUDED)
        product_group_type: 상품 그룹 타입 (US_PLUS 또는 US_CAMPUS)
        web_link: 구독 페이지 버튼 클릭 시 이동할 웹 링크 (예: "https://dev.us-insight.com/products/group/148")
    """
    if MOCK_MODE:
        return _get_mock("update_main_product_setting")
    has_web_link = bool(web_link)
    body = {
        "productGroupType": product_group_type,
        "productGroupViewStatus": view_status,
        "isProductGroupWebLinkStatus": "ACTIVE" if has_web_link else "INACTIVE",
        "isProductGroupAppLinkStatus": "INACTIVE",
    }
    if has_web_link:
        body["productGroupWebLink"] = web_link
    with _client() as c:
        r = c.patch(f"/v1/masters/{master_id}/main-product-group", json=body)
        return _safe_request(r)


@tool
def navigate(page: str, params: dict | None = None) -> dict:
    """관리자센터 페이지 이동 안내를 생성합니다. 직접 이동하지 않고, 사이드패널에 [이동] 버튼으로 제공합니다.

    선행 조건: 없음
    주의: 직접 이동하지 않음. 사이드패널에 [이동] 버튼으로 제공.

    Args:
        page: 페이지 식별자. 가능한 값:
            - product_page_list: 상품 페이지 목록
            - product_page_create: 상품 페이지 생성
            - product_page_edit: 상품 페이지 수정 (params: {id})
            - official_club: 오피셜클럽 상세 (params: {masterId})
            - official_club_create: 오피셜클럽 생성
            - master_list: 마스터 관리
            - main_product: 메인 상품 페이지 설정
            - board_setting: 게시판 설정
            - board: 게시글 관리
            - donation: 응원하기 관리
            - letter: 편지글 관리
            - partner_series: 파트너센터 시리즈 생성 (외부)
            - refund: 환불 처리
            - subscribe: 구독 관리
        params: 추가 파라미터 (예: {"id": "148"}, {"masterId": "35"})

    예시: navigate("product_page_create") → {"url": "/product/create", "label": "상품 페이지 생성"}

    Returns:
        {"url": str, "label": str} — UI에서 버튼으로 렌더링
    """
    PAGE_MAP = {
        # 상품
        "product_page_list": {"url": "/product", "label": "상품 페이지 목록"},
        "product_page_create": {"url": "/product/page/create", "label": "상품 페이지 생성"},
        "product_page_edit": {"url": "/product/page/{id}?tab=settings", "label": "상품 페이지 수정"},
        "product_page_options": {"url": "/product/page/{id}?tab=options", "label": "상품 옵션 관리"},
        "product_page_letters": {"url": "/product/page/{id}?tab=letters", "label": "편지글 관리"},
        "product_page_caution": {"url": "/product/page/{id}?tab=caution", "label": "유의사항 관리"},
        "product_create": {"url": "/product/create?productPageId={productPageId}&productType={productType}&masterId={masterId}", "label": "상품 옵션 등록"},
        "product_edit": {"url": "/product/{productId}?productPageId={productPageId}&productType={productType}&masterId={masterId}", "label": "상품 옵션 수정"},
        # 메인 상품 페이지
        "main_product": {"url": "/product/page/list", "label": "메인 상품 페이지 관리"},
        # 오피셜클럽/마스터
        "official_club_list": {"url": "/official-club", "label": "오피셜클럽 목록"},
        "official_club": {"url": "/official-club/{masterId}", "label": "오피셜클럽 상세"},
        "official_club_create": {"url": "/official-club/create", "label": "오피셜클럽 생성"},
        "master_list": {"url": "/master", "label": "마스터 관리"},
        "master_page": {"url": "/master/page", "label": "마스터 페이지 관리"},
        # 커뮤니티
        "board_setting": {"url": "/board/setting", "label": "게시판 설정"},
        "board": {"url": "/board", "label": "게시글 관리"},
        "donation": {"url": "/donation", "label": "응원하기 관리"},
        "letter": {"url": "/cs/letter", "label": "편지글 관리"},
        # 외부
        "partner_series": {"url": "https://master.us-insight.com", "label": "파트너센터 시리즈 생성"},
        # 기타
        "product_sales": {"url": "/product/sales", "label": "상품 결제 내역"},
        "subscribe": {"url": "/subscribe", "label": "구독 관리"},
    }

    entry = PAGE_MAP.get(page)
    if not entry:
        return {"error": True, "message": f"알 수 없는 페이지: {page}. 가능한 값: {', '.join(PAGE_MAP.keys())}"}

    url = entry["url"]
    label = entry["label"]

    # URL 템플릿에 params 적용
    if params:
        for key, value in params.items():
            url = url.replace(f"{{{key}}}", str(value))

    return {"url": url, "label": label}


# ──────────────────────────────────────────────
# 제거된 Tools (참조용 — 범위 밖 또는 validator로 이관)
# ──────────────────────────────────────────────
#
# create_master_group — 마스터 그룹 생성 (범위 밖, navigate로 안내)
# create_series — 시리즈 생성 (파트너센터에서 생성, navigate로 안내)
# create_product_page — 상품 페이지 생성 (navigate로 안내)
# create_product — 상품 옵션 생성 (navigate로 안내)
# update_product_sequence — 상품 옵션 순서 변경 (범위 축소)
# verify_product_setup — 탐색 에이전트 검증 (별도 에이전트로 분리)
