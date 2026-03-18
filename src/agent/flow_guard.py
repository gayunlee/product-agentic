"""
Phase별 Tool 호출을 제어하는 FlowGuard.

BeforeToolCallEvent hook으로 현재 Phase에서 허용되지 않는 Tool 호출을 차단합니다.
에이전트가 프롬프트를 무시하고 잘못된 순서로 Tool을 호출하는 것을 방지합니다.
"""

from typing import Any
from strands.hooks.registry import HookProvider, HookRegistry
from strands.hooks.events import BeforeToolCallEvent, AfterToolCallEvent


# Phase별 허용 Tool 정의
PHASE_TOOLS: dict[str, list[str]] = {
    "init": [
        "search_masters",
        "get_master_groups",
        "get_master_detail",
        "create_master_group",
    ],
    "series": [
        "get_series_list",
        "create_series",
        # init 단계 Tool도 허용 (되돌아갈 수 있음)
        "search_masters",
        "get_master_groups",
        "get_master_detail",
    ],
    "product_page": [
        "get_product_page_list",
        "create_product_page",
        "get_product_page_detail",
        # 이전 단계 조회도 허용
        "search_masters",
        "get_master_groups",
        "get_series_list",
    ],
    "product_option": [
        "create_product",
        "get_product_list_by_page",
        # 조회는 허용
        "get_product_page_list",
        "get_product_page_detail",
        "get_series_list",
    ],
    "activation": [
        "update_product_display",
        "update_product_sequence",
        "update_product_page_status",
        "update_main_product_setting",
        # 조회는 허용
        "get_product_page_detail",
        "get_product_list_by_page",
    ],
    "verification": [
        "get_product_page_detail",
        "get_product_list_by_page",
        "get_product_page_list",
        "search_masters",
        "get_master_detail",
    ],
}

# Tool 호출 성공 시 자동으로 다음 Phase로 전환하는 규칙
PHASE_TRANSITIONS: dict[str, dict[str, str]] = {
    "init": {
        "search_masters": "init",  # 검색 결과에 따라 수동 전환
        "get_master_groups": "init",
        "create_master_group": "init",
    },
    "series": {
        "get_series_list": "series",
        "create_series": "product_page",  # 시리즈 생성 후 → 상품 페이지
    },
    "product_page": {
        "create_product_page": "product_page",  # 생성 후 목록 조회 필요
        "get_product_page_list": "product_page",
    },
    "product_option": {
        "create_product": "product_option",  # 여러 옵션 등록 가능
    },
    "activation": {
        "update_main_product_setting": "verification",  # 마지막 활성화 후 검증
    },
}


class FlowGuard(HookProvider):
    """Phase별 Tool 호출을 제어하는 가드.

    현재 Phase에서 허용되지 않는 Tool 호출을 차단하고,
    에러 메시지를 에이전트에 전달하여 올바른 순서로 진행하도록 유도합니다.
    """

    def __init__(self):
        self.current_phase = "init"
        self.collected_data: dict[str, Any] = {}
        self.tool_history: list[dict] = []

    def register_hooks(self, registry: HookRegistry, **kwargs) -> None:
        registry.add_callback(BeforeToolCallEvent, self._before_tool_call)
        registry.add_callback(AfterToolCallEvent, self._after_tool_call)

    def _before_tool_call(self, event: BeforeToolCallEvent) -> None:
        tool_name = event.tool_use.get("name", "")
        allowed = PHASE_TOOLS.get(self.current_phase, [])

        if tool_name not in allowed:
            event.cancel_tool = (
                f"[FlowGuard] '{tool_name}' Tool은 현재 Phase '{self.current_phase}'에서 사용할 수 없습니다. "
                f"현재 Phase에서 사용 가능한 Tool: {allowed}. "
                f"현재까지 수집된 데이터: {self.collected_data}"
            )

    def _after_tool_call(self, event: AfterToolCallEvent) -> None:
        tool_name = event.tool_use.get("name", "")
        tool_result = event.result

        # 에러 상태면 Phase 전환하지 않음
        if tool_result.get("status") == "error":
            return

        # ToolResult.content에서 실제 데이터 추출
        result = self._extract_result(tool_result)
        if result is None:
            return

        # Tool 호출 기록
        self.tool_history.append({"tool": tool_name, "phase": self.current_phase})

        # 결과에서 중요 데이터 수집
        self._collect_data(tool_name, result)

        # 자동 Phase 전환
        self._auto_advance()

    @staticmethod
    def _extract_result(tool_result) -> Any | None:
        """ToolResult에서 실제 데이터를 추출합니다."""
        import json
        content = tool_result.get("content", [])
        if not content:
            return None
        # content[0]에서 text를 가져와 JSON 파싱
        first = content[0]
        if isinstance(first, dict) and "text" in first:
            try:
                return json.loads(first["text"])
            except (json.JSONDecodeError, TypeError):
                return first["text"]
        return None

    def _collect_data(self, tool_name: str, result: Any) -> None:
        """Tool 결과에서 다음 Phase에 필요한 데이터를 수집합니다."""
        if tool_name == "search_masters" and isinstance(result, list) and len(result) > 0:
            # 오피셜클럽 발견 → cmsId 저장
            master = result[0]
            self.collected_data["master_cms_id"] = master.get("cmsId")
            self.collected_data["master_id"] = master.get("id")
            self.collected_data["master_name"] = master.get("name")

        elif tool_name == "get_series_list" and isinstance(result, dict):
            masters = result.get("masters", [])
            if masters and masters[0].get("series"):
                series = masters[0]["series"]
                self.collected_data["series_ids"] = [s["_id"] for s in series]
                self.collected_data["series_titles"] = [s["title"] for s in series]

        elif tool_name == "create_series" and isinstance(result, dict):
            content = result.get("content", {})
            if content.get("id"):
                self.collected_data.setdefault("series_ids", []).append(content["id"])

        elif tool_name == "get_product_page_list" and isinstance(result, list) and len(result) > 0:
            page = result[0]
            self.collected_data["product_page_id"] = page.get("id")
            self.collected_data["product_page_code"] = page.get("code")

        elif tool_name == "create_product" and isinstance(result, dict):
            if result.get("id"):
                self.collected_data.setdefault("product_ids", []).append(str(result["id"]))

    def _auto_advance(self) -> None:
        """수집된 데이터를 기반으로 자동 Phase 전환."""
        prev = self.current_phase

        if self.current_phase == "init" and self.can_advance_to_series():
            self.current_phase = "series"
        elif self.current_phase == "series" and self.can_advance_to_product_page():
            self.current_phase = "product_page"
        elif self.current_phase == "product_page" and self.can_advance_to_product_option():
            self.current_phase = "product_option"
        elif self.current_phase == "product_option" and self.can_advance_to_activation():
            self.current_phase = "activation"

        if self.current_phase != prev:
            self.tool_history.append({"phase_transition": f"{prev} → {self.current_phase}"})

    def advance_to(self, phase: str) -> None:
        """수동으로 Phase를 전환합니다."""
        if phase in PHASE_TOOLS:
            self.current_phase = phase

    def can_advance_to_series(self) -> bool:
        return "master_cms_id" in self.collected_data

    def can_advance_to_product_page(self) -> bool:
        return "series_ids" in self.collected_data and len(self.collected_data["series_ids"]) > 0

    def can_advance_to_product_option(self) -> bool:
        return "product_page_id" in self.collected_data

    def can_advance_to_activation(self) -> bool:
        return "product_ids" in self.collected_data and len(self.collected_data["product_ids"]) > 0
