"""
DiagnoseEngine — visibility_chain.yaml을 코드로 실행하는 진단 엔진.

"왜 안 보여?" 질문에 대해 노출 체인을 순서대로 체크하여
첫 번째 실패 지점과 해결 방법을 반환한다.

validator.py의 diagnose_visibility 로직을 이전 + YAML 기반으로 변경.
"""

from __future__ import annotations

import os
import re
import json
from typing import Any

from src.domain_loader import load_yaml, format_template
from src.agents.response import AgentResponse, render_response_json


MOCK_MODE = os.environ.get("MOCK_MODE", "").lower() in ("true", "1", "yes")
PLACEHOLDER_IMAGE = "https://placehold.co/990x1100/e8e8e8/999?text=PLACEHOLDER"


def _api_get(path: str, params: dict | None = None) -> dict | list:
    """관리자센터 API GET 요청. validator.py의 _api_get과 동일."""
    if MOCK_MODE:
        from src.agents.validator import MOCK_API_RESPONSES
        if path in MOCK_API_RESPONSES:
            return MOCK_API_RESPONSES[path]
        if path == "/v1/product-group" and params:
            return MOCK_API_RESPONSES.get("/v1/product-group", [])
        return {"mock": True, "path": path}
    import httpx
    from src.tools.admin_api import ADMIN_BASE, ADMIN_TOKEN
    with httpx.Client(
        base_url=ADMIN_BASE,
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
        timeout=30.0,
    ) as c:
        r = c.get(path, params=params or {})
        if r.status_code >= 400:
            return {"error": True, "status": r.status_code}
        if not r.text.strip():
            return {}
        return r.json()


class DiagnoseEngine:
    """visibility_chain.yaml 기반 진단 엔진."""

    def __init__(self):
        self.chains = load_yaml("domain/visibility_chain.yaml").get("chains", {})
        self.launch_data = load_yaml("domain/launch_check.yaml")

    def diagnose(self, master_id: str) -> dict:
        """상품 노출 진단. 이름 또는 cmsId로 호출 가능.

        Returns:
            {visible, checks, first_failure, recommendation, weblink_warnings, master_name, resolve_actions}
        """
        from src.tools.admin_api import (
            search_masters,
            get_master_detail,
            get_product_page_list,
            get_product_page_detail,
            get_product_list_by_page,
        )

        checks = []
        resolve_actions = []

        # 0. 이름으로 호출된 경우 → 자동 검색
        if not master_id.isdigit():
            result = search_masters(search_keyword=master_id)
            masters = result.get("masters", result) if isinstance(result, dict) else result
            if isinstance(masters, list) and masters:
                master_id = str(masters[0].get("cmsId", ""))
                if not master_id:
                    return self._not_found(master_id)
            else:
                return self._not_found(master_id)

        # 1. 마스터 상태 확인
        master = get_master_detail(master_id=master_id)
        if isinstance(master, dict) and master.get("error"):
            return self._not_found(master_id)

        master_public = master.get("clubPublicType") == "PUBLIC"
        checks.append({
            "condition": "master_public",
            "label": "마스터 PUBLIC 상태",
            "passed": master_public,
            "actual": master.get("clubPublicType", "UNKNOWN"),
        })
        if not master_public:
            resolve_actions.append({
                "type": "navigate",
                "url": f"/official-club/{master_id}",
                "label": "오피셜클럽 설정",
            })

        # 2. 메인 상품 설정 확인
        main_active, main_product, weblink_warnings = self._check_main_product(master_id, checks)
        if not main_active:
            resolve_actions.append({
                "type": "action",
                "action_id": "update_main_product_setting",
                "slots": {"master_cms_id": master_id, "view_status": "ACTIVE"},
                "label": "ACTIVE로 변경",
            })

        # 3. 상품 페이지들 확인
        pages = get_product_page_list(master_id=master_id)
        page_list = pages if isinstance(pages, list) else pages.get("pages", []) if isinstance(pages, dict) else []
        active_pages = []

        for page in page_list:
            page_id = page.get("id")
            is_active = page.get("status") == "ACTIVE"
            is_hidden = False

            if page_id:
                detail = get_product_page_detail(product_page_id=page_id)
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
                products = get_product_list_by_page(product_page_id=page_id)
                prod_list = products if isinstance(products, list) else products.get("products", []) if isinstance(products, dict) else []
                page_check["options"] = [
                    {
                        "name": p.get("name", ""),
                        "is_display": p.get("isDisplay", False),
                        "price": p.get("price", 0),
                    }
                    for p in prod_list
                ]

        checks.append({
            "condition": "page_active",
            "label": "ACTIVE 상품 페이지 존재",
            "passed": len(active_pages) > 0,
            "actual": f"{len(active_pages)}개 ACTIVE",
            "pages": active_pages,
        })

        # 4. 웹링크 타겟 검증 (기존 로직 유지)
        self._check_weblink_target(checks, main_product, page_list, active_pages, weblink_warnings)

        # 첫 번째 실패 지점
        first_failure = None
        recommendation = None
        for check in checks:
            if not check.get("passed", False):
                first_failure = check["label"]
                recommendation = self._get_recommendation(check)
                break

        return {
            "visible": first_failure is None,
            "checks": checks,
            "first_failure": first_failure,
            "recommendation": recommendation,
            "weblink_warnings": weblink_warnings if weblink_warnings else None,
            "master_name": master.get("name", "") if isinstance(master, dict) else "",
            "resolve_actions": resolve_actions if resolve_actions else None,
        }

    def diagnose_rendered(self, master_id: str) -> str:
        """diagnose() 결과를 render_response_json으로 렌더링."""
        result = self.diagnose(master_id)

        data = {
            "checks": [
                {"name": c.get("label", ""), "ok": c.get("passed", False), "value": c.get("actual", "")}
                for c in result.get("checks", [])
            ],
            "first_failure": result.get("first_failure"),
            "fix_label": "해결하기" if result.get("first_failure") else None,
            "nav_url": "/product/page/list",
            "resolve_actions": result.get("resolve_actions"),
        }
        if result.get("weblink_warnings"):
            data["weblink_warnings"] = result["weblink_warnings"]

        resp_type = "diagnose" if not result.get("visible") else "info"
        master_name = result.get("master_name", master_id)
        summary = f"{master_name} 노출 진단 완료. "
        if result.get("first_failure"):
            summary += f"원인: {result['first_failure']}"
        else:
            summary += "모든 조건 정상."

        resp = AgentResponse(type=resp_type, summary=summary, data=data)
        return render_response_json(resp)

    # ── 내부 헬퍼 ──

    def _not_found(self, master_id: str) -> dict:
        return {
            "visible": False,
            "checks": [],
            "first_failure": f"'{master_id}' 검색 결과 없음",
            "recommendation": "정확한 오피셜클럽 이름을 확인하세요.",
            "master_name": "",
        }

    def _check_main_product(self, master_id: str, checks: list) -> tuple[bool, dict | None, list]:
        """메인 상품 설정 확인 + 웹링크 기본 검사."""
        main_product = _api_get(f"/v1/masters/{master_id}/main-product-group")
        main_active = False
        weblink_warnings = []

        if isinstance(main_product, dict):
            main_active = main_product.get("productGroupViewStatus") == "ACTIVE"

        checks.append({
            "condition": "main_product_active",
            "label": "메인 상품 페이지 ACTIVE",
            "passed": main_active,
            "actual": main_product.get("productGroupViewStatus", "UNKNOWN") if isinstance(main_product, dict) else "조회 실패",
        })

        # 웹링크 기본 검사
        if main_active and isinstance(main_product, dict):
            web_link = main_product.get("productGroupWebLink", "")
            web_link_status = main_product.get("isProductGroupWebLinkStatus", "INACTIVE")

            if web_link_status == "ACTIVE" and web_link:
                code_match = re.search(r"/products/group/(\d+)", web_link)
                if code_match:
                    weblink_code = int(code_match.group(1))
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

        return main_active, main_product, weblink_warnings

    def _check_weblink_target(
        self,
        checks: list,
        main_product: dict | None,
        pages: list,
        active_pages: list,
        weblink_warnings: list,
    ):
        """웹링크 타겟 상품페이지 정합성 검증."""
        weblink_check = next(
            (c for c in checks if c.get("condition") == "weblink_set" and c.get("_weblink_code")),
            None,
        )
        if not weblink_check:
            return

        weblink_code = weblink_check["_weblink_code"]

        # 전체 페이지에서 코드로 매칭
        all_page_details = {}
        for page in pages if isinstance(pages, list) else []:
            page_id = page.get("id") if isinstance(page, dict) else None
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
                weblink_warnings.append(
                    f"웹링크가 비공개(INACTIVE) 상품페이지(코드 {weblink_code})를 가리킵니다."
                )
                checks.append({
                    "condition": "weblink_target_valid",
                    "label": "웹링크 타겟 접근 가능",
                    "passed": False,
                    "actual": f"코드 {weblink_code} INACTIVE",
                })
            elif target_hidden and not target_always:
                weblink_warnings.append(
                    f"웹링크가 히든+날짜지정 상품페이지(코드 {weblink_code})를 가리킵니다."
                )
                checks.append({
                    "condition": "weblink_target_valid",
                    "label": "웹링크 타겟 안정성",
                    "passed": False,
                    "actual": f"코드 {weblink_code} 히든+날짜지정",
                })
            else:
                checks.append({
                    "condition": "weblink_target_valid",
                    "label": "웹링크 타겟 접근 가능",
                    "passed": True,
                    "actual": f"코드 {weblink_code} 정상",
                })

    def _get_recommendation(self, check: dict) -> str:
        """실패 체크에 대한 추천 액션."""
        condition = check.get("condition", "")
        if condition == "master_public":
            return f"마스터를 PUBLIC으로 전환하세요. 현재: {check.get('actual', '?')}"
        if condition == "main_product_active":
            return "메인 상품 페이지 설정을 ACTIVE로 변경하세요."
        if condition == "page_active":
            return "상품 페이지를 ACTIVE로 변경하세요."
        return ""


# ── 싱글톤 ──

_engine: DiagnoseEngine | None = None


def get_engine() -> DiagnoseEngine:
    """DiagnoseEngine 싱글톤."""
    global _engine
    if _engine is None:
        _engine = DiagnoseEngine()
    return _engine
