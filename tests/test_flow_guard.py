"""
FlowGuard 단위 테스트.
Phase별 Tool 제한 + 자동 전환 + 데이터 수집을 검증.

Usage:
    uv run pytest tests/test_flow_guard.py -v
"""

import pytest
from unittest.mock import MagicMock
from legacy.agent.flow_guard import FlowGuard, PHASE_TOOLS


def _wrap_result(data) -> dict:
    """테스트 데이터를 실제 ToolResult 형식으로 감싼다.

    FlowGuard._after_tool_call은 event.result를 사용하고,
    _extract_result가 result["content"][0]["text"]에서 JSON을 파싱한다.
    에러 응답은 {"status": "error"}로 전달.
    """
    import json
    if data is None:
        return {}
    if isinstance(data, dict) and data.get("error"):
        return {"status": "error"}
    return {"content": [{"text": json.dumps(data)}]}


class FakeToolEvent:
    """BeforeToolCallEvent/AfterToolCallEvent mock."""

    def __init__(self, tool_name: str, result=None):
        self.tool_use = {"name": tool_name}
        self.result = _wrap_result(result)
        self.cancel_tool = False


# ──────────────────────────────────────────────
# Phase 전환 테스트
# ──────────────────────────────────────────────


class TestPhaseTransition:
    def test_starts_at_init(self):
        guard = FlowGuard()
        assert guard.current_phase == "init"

    def test_init_to_series_on_master_found(self):
        """오피셜클럽 검색 결과에 cmsId가 있으면 series로 전환."""
        guard = FlowGuard()
        event = FakeToolEvent("search_masters", result=[
            {"id": "abc", "cmsId": "136", "name": "테스트", "publicType": "PUBLIC"}
        ])
        guard._after_tool_call(event)
        assert guard.current_phase == "series"
        assert guard.collected_data["master_cms_id"] == "136"

    def test_stays_init_when_no_master(self):
        """검색 결과가 비어있으면 init에 머무름."""
        guard = FlowGuard()
        event = FakeToolEvent("search_masters", result=[])
        guard._after_tool_call(event)
        assert guard.current_phase == "init"

    def test_series_to_product_page_on_series_found(self):
        """시리즈가 있으면 product_page로 전환."""
        guard = FlowGuard()
        guard.current_phase = "series"
        guard.collected_data["master_cms_id"] = "136"

        event = FakeToolEvent("get_series_list", result={
            "masters": [{"_id": "abc", "name": "테스트", "series": [{"_id": "s1", "title": "시리즈1"}]}]
        })
        guard._after_tool_call(event)
        assert guard.current_phase == "product_page"
        assert guard.collected_data["series_ids"] == ["s1"]

    def test_series_stays_when_no_series(self):
        """시리즈가 없으면 series에 머무름."""
        guard = FlowGuard()
        guard.current_phase = "series"

        event = FakeToolEvent("get_series_list", result={
            "masters": [{"_id": "abc", "name": "테스트", "series": []}]
        })
        guard._after_tool_call(event)
        assert guard.current_phase == "series"

    def test_series_to_product_page_after_create_series(self):
        """시리즈 생성 후 product_page로 전환."""
        guard = FlowGuard()
        guard.current_phase = "series"

        event = FakeToolEvent("create_series", result={"content": {"id": "new_s1", "cmsId": "291"}})
        guard._after_tool_call(event)
        assert guard.current_phase == "product_page"
        assert "new_s1" in guard.collected_data["series_ids"]

    def test_product_page_to_option_on_page_found(self):
        """상품 페이지가 조회되면 product_option으로 전환."""
        guard = FlowGuard()
        guard.current_phase = "product_page"
        guard.collected_data["series_ids"] = ["s1"]

        event = FakeToolEvent("get_product_page_list", result=[
            {"id": "page_001", "title": "테스트", "code": 197}
        ])
        guard._after_tool_call(event)
        assert guard.current_phase == "product_option"
        assert guard.collected_data["product_page_id"] == "page_001"

    def test_product_option_to_activation_after_create(self):
        """상품 옵션 생성 후 activation으로 전환."""
        guard = FlowGuard()
        guard.current_phase = "product_option"
        guard.collected_data["product_page_id"] = "page_001"

        event = FakeToolEvent("create_product", result={"id": 12345})
        guard._after_tool_call(event)
        assert guard.current_phase == "activation"
        assert "12345" in guard.collected_data["product_ids"]


# ──────────────────────────────────────────────
# Tool 차단 테스트
# ──────────────────────────────────────────────


class TestToolBlocking:
    def test_blocks_create_product_in_init(self):
        """init Phase에서 create_product 호출 차단."""
        guard = FlowGuard()
        event = FakeToolEvent("create_product")
        guard._before_tool_call(event)
        assert event.cancel_tool  # 차단됨

    def test_blocks_create_product_in_series(self):
        """series Phase에서 create_product 호출 차단."""
        guard = FlowGuard()
        guard.current_phase = "series"
        event = FakeToolEvent("create_product")
        guard._before_tool_call(event)
        assert event.cancel_tool

    def test_allows_create_product_in_product_option(self):
        """product_option Phase에서 create_product 허용."""
        guard = FlowGuard()
        guard.current_phase = "product_option"
        event = FakeToolEvent("create_product")
        guard._before_tool_call(event)
        assert not event.cancel_tool

    def test_blocks_create_product_page_in_init(self):
        """init Phase에서 create_product_page 차단."""
        guard = FlowGuard()
        event = FakeToolEvent("create_product_page")
        guard._before_tool_call(event)
        assert event.cancel_tool

    def test_allows_create_product_page_in_product_page(self):
        """product_page Phase에서 create_product_page 허용."""
        guard = FlowGuard()
        guard.current_phase = "product_page"
        event = FakeToolEvent("create_product_page")
        guard._before_tool_call(event)
        assert not event.cancel_tool

    def test_allows_search_masters_in_any_phase(self):
        """search_masters는 대부분의 Phase에서 허용."""
        for phase in ["init", "series", "product_page", "verification"]:
            guard = FlowGuard()  # 매 phase마다 새 인스턴스 (반복 호출 감지 방지)
            guard.current_phase = phase
            event = FakeToolEvent("search_masters")
            guard._before_tool_call(event)
            assert not event.cancel_tool, f"search_masters should be allowed in {phase}"

    def test_blocks_activation_tools_in_product_option(self):
        """product_option Phase에서 활성화 Tool 차단."""
        guard = FlowGuard()
        guard.current_phase = "product_option"
        for tool in ["update_product_display", "update_product_page_status", "update_main_product_setting"]:
            event = FakeToolEvent(tool)
            guard._before_tool_call(event)
            assert event.cancel_tool, f"{tool} should be blocked in product_option"


# ──────────────────────────────────────────────
# 에러 시 Phase 전환 안 함
# ──────────────────────────────────────────────


class TestErrorHandling:
    def test_no_transition_on_error_response(self):
        """API 에러 응답이면 Phase 전환하지 않음."""
        guard = FlowGuard()
        event = FakeToolEvent("search_masters", result={"error": True, "status": 401})
        guard._after_tool_call(event)
        assert guard.current_phase == "init"  # 전환 안 됨

    def test_no_data_collected_on_error(self):
        """에러 시 데이터 수집하지 않음."""
        guard = FlowGuard()
        event = FakeToolEvent("search_masters", result={"error": True, "status": 400})
        guard._after_tool_call(event)
        assert "master_cms_id" not in guard.collected_data


# ──────────────────────────────────────────────
# 전체 플로우 시나리오
# ──────────────────────────────────────────────


class TestFullFlowScenario:
    def test_subscription_flow_phases(self):
        """구독상품 전체 세팅 시 Phase 전환 순서 검증."""
        guard = FlowGuard()

        # Phase 0: init → 마스터 검색 → series
        assert guard.current_phase == "init"
        guard._after_tool_call(FakeToolEvent("search_masters", [
            {"id": "abc", "cmsId": "136", "name": "테스트", "publicType": "PUBLIC"}
        ]))
        assert guard.current_phase == "series"

        # Phase 1: series → 시리즈 조회 → product_page
        guard._after_tool_call(FakeToolEvent("get_series_list", {
            "masters": [{"_id": "abc", "name": "테스트", "series": [{"_id": "s1", "title": "시리즈"}]}]
        }))
        assert guard.current_phase == "product_page"

        # Phase 2: product_page → 페이지 생성 + 목록 조회 → product_option
        guard._after_tool_call(FakeToolEvent("create_product_page", {"success": True, "status": 201}))
        assert guard.current_phase == "product_page"  # 아직 페이지 ID 없음
        guard._after_tool_call(FakeToolEvent("get_product_page_list", [
            {"id": "page_001", "title": "테스트", "code": 197}
        ]))
        assert guard.current_phase == "product_option"

        # Phase 3: product_option → 상품 생성 → activation
        guard._after_tool_call(FakeToolEvent("create_product", {"id": 12345}))
        assert guard.current_phase == "activation"

    def test_cancel_message_includes_allowed_tools(self):
        """차단 메시지에 허용된 Tool 목록이 포함되는지 검증."""
        guard = FlowGuard()
        event = FakeToolEvent("create_product")
        guard._before_tool_call(event)
        assert "search_masters" in str(event.cancel_tool)
        assert "init" in str(event.cancel_tool)
