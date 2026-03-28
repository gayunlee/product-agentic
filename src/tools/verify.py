"""
세팅 검증 Tool.

세팅 에이전트가 admin API로 세팅 완료 후,
us-explorer-agent(QA 에이전트)에 HTTP POST /verify 요청을 보내서
Playwright + Web MCP로 us-plus 화면을 실제 확인합니다.
"""

import os

import httpx
from strands import tool

EXPLORER_BASE_URL = os.environ.get("EXPLORER_AGENT_URL", "http://localhost:8001")


@tool
def verify_settings(context: dict, checks: list[dict]) -> dict:
    """세팅 결과를 QA 에이전트로 실제 화면에서 검증합니다.

    us-explorer-agent(QA 에이전트)에 HTTP POST /verify 요청을 보내서
    Playwright + Web MCP로 us-plus 화면을 확인합니다.

    Args:
        context: admin API에서 수집한 현재 상태
            {
                "master": { "cmsId": "35", "name": "조조형우", "publicType": "PUBLIC" },
                "mainProduct": { "viewStatus": "ACTIVE", "webLink": "/products/group/148", "productGroupCode": 148 },
                "productPages": [{ "code": 148, "status": "ACTIVE", "isHidden": false, ... }],
                "products": { "148": [{ "id": "p1", "name": "월간 리포트", "isDisplay": true }] }
            }
        checks: 검증 항목 목록
            [
                { "tool": "check_subscribe_page", "args": { "cms_id": "35" }, "expected": { "found": true } },
                { "tool": "check_product_page", "args": { "code": 148 }, "expected": { "accessible": true, "displayedProductCount": 2 } }
            ]

    Returns:
        {
            "results": [{ "tool": "...", "status": "pass|fail|error", "expected": {...}, "actual": {...}, "mismatches": [...] }],
            "summary": { "total": 4, "passed": 3, "failed": 1, "errors": 0 },
            "context": { ... }
        }
    """
    try:
        with httpx.Client(base_url=EXPLORER_BASE_URL, timeout=60.0) as client:
            response = client.post("/verify", json={"context": context, "checks": checks})
            if response.status_code >= 400:
                return {
                    "results": [],
                    "summary": {"total": len(checks), "passed": 0, "failed": 0, "errors": len(checks)},
                    "context": context,
                    "error": f"QA 에이전트 응답 오류: {response.status_code}",
                }
            return response.json()
    except Exception as e:
        return {
            "results": [],
            "summary": {"total": len(checks), "passed": 0, "failed": 0, "errors": len(checks)},
            "context": context,
            "error": f"QA 에이전트 연결 실패: {str(e)}",
        }
