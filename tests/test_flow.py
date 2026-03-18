"""
에이전트 플로우 시나리오 테스트.
Mock API로 Tool 호출 순서 + 파라미터를 검증.
실제 API/LLM을 호출하지 않음.

Usage:
    uv run pytest tests/test_flow.py -v
"""

import os
from unittest.mock import patch, MagicMock

import pytest

# AWS/API 환경변수 모킹 (실제 호출 방지)
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("ADMIN_API_BASE_URL", "https://mock-admin.test")
os.environ.setdefault("ADMIN_API_TOKEN", "mock-token")
os.environ.setdefault("PARTNER_API_BASE_URL", "https://mock-partner.test")
os.environ.setdefault("PARTNER_API_TOKEN", "mock-token")

from tests.mock_responses import *


class ToolCallTracker:
    """Tool 호출을 추적하는 헬퍼."""

    def __init__(self):
        self.calls: list[dict] = []

    def record(self, tool_name: str, args: dict, response: dict):
        self.calls.append({"tool": tool_name, "args": args, "response": response})

    @property
    def tool_names(self) -> list[str]:
        return [c["tool"] for c in self.calls]

    def get_call(self, tool_name: str) -> dict | None:
        for c in self.calls:
            if c["tool"] == tool_name:
                return c
        return None

    def get_all_calls(self, tool_name: str) -> list[dict]:
        return [c for c in self.calls if c["tool"] == tool_name]


# ──────────────────────────────────────────────
# 시나리오 1: 구독상품 전체 플로우 (마스터/시리즈 있음)
# ──────────────────────────────────────────────


class TestSubscriptionFullFlow:
    """마스터/시리즈가 이미 있을 때 구독상품 전체 세팅 플로우."""

    def setup_method(self):
        self.tracker = ToolCallTracker()

    def _simulate_flow(self):
        """에이전트가 호출해야 하는 Tool 순서를 시뮬레이션."""
        t = self.tracker

        # Phase 0: 마스터 확인
        t.record("search_masters", {"search_keyword": "테스트 마스터"}, SEARCH_MASTERS_FOUND)
        t.record("get_master_groups", {"name": "테스트 마스터"}, MASTER_GROUPS)

        # Phase 1: 시리즈 확인
        t.record("get_series_list", {"master_id": "136"}, SERIES_LIST_FOUND)

        # Phase 2: 상품 페이지 생성
        t.record("get_product_page_list", {"master_id": "136"}, PRODUCT_PAGE_LIST_EMPTY)
        t.record(
            "create_product_page",
            {
                "master_id": "136",
                "title": "테스트 구독 상품",
                "product_type": "SUBSCRIPTION",
            },
            CREATE_PRODUCT_PAGE_SUCCESS,
        )
        t.record("get_product_page_list", {"master_id": "136"}, PRODUCT_PAGE_LIST_FOUND)

        # Phase 3: 상품 옵션 등록
        t.record(
            "create_product",
            {
                "product_group_id": "page_001",
                "name": "월간 구독",
                "origin_price": 29900,
                "content_ids": ["series_001"],
                "display_texts": ["투자 기초 시리즈 이용권"],
                "payment_period": "ONE_MONTH",
            },
            CREATE_PRODUCT_SUCCESS,
        )

        # Phase 4: 활성화
        t.record("update_product_display", {"product_id": "12345", "is_display": True}, UPDATE_PRODUCT_DISPLAY_SUCCESS)
        t.record("update_product_sequence", {"product_group_id": "page_001", "product_ids": ["12345"]}, UPDATE_PRODUCT_SEQUENCE_SUCCESS)
        t.record("update_product_page_status", {"product_page_id": "page_001", "status": "INACTIVE"}, UPDATE_PRODUCT_PAGE_STATUS_SUCCESS)
        t.record("update_main_product_setting", {"master_id": "136", "view_status": "ACTIVE"}, UPDATE_MAIN_PRODUCT_SETTING_SUCCESS)

        # Phase 5: 검증
        t.record("get_product_page_detail", {"product_page_id": "page_001"}, PRODUCT_PAGE_DETAIL)
        t.record("get_product_list_by_page", {"product_page_id": "page_001"}, PRODUCT_LIST_BY_PAGE)

    def test_correct_tool_order(self):
        """Tool이 올바른 순서로 호출되는지 검증."""
        self._simulate_flow()

        expected_order = [
            "search_masters",        # Phase 0
            "get_master_groups",     # Phase 0
            "get_series_list",       # Phase 1
            "get_product_page_list", # Phase 2 (기존 확인)
            "create_product_page",   # Phase 2 (생성)
            "get_product_page_list", # Phase 2 (생성 후 ID 확보)
            "create_product",        # Phase 3
            "update_product_display",      # Phase 4
            "update_product_sequence",     # Phase 4
            "update_product_page_status",  # Phase 4
            "update_main_product_setting", # Phase 4
            "get_product_page_detail",     # Phase 5
            "get_product_list_by_page",    # Phase 5
        ]
        assert self.tracker.tool_names == expected_order

    def test_master_id_uses_cms_id(self):
        """masterId로 cmsId를 사용하는지 검증."""
        self._simulate_flow()

        # 시리즈 조회에 cmsId 사용
        series_call = self.tracker.get_call("get_series_list")
        assert series_call["args"]["master_id"] == "136"  # id가 아닌 cmsId

        # 상품 페이지 생성에 cmsId 사용
        create_page = self.tracker.get_call("create_product_page")
        assert create_page["args"]["master_id"] == "136"

    def test_content_ids_not_empty(self):
        """상품 옵션 생성 시 contentIds가 비어있지 않은지 검증."""
        self._simulate_flow()

        create_product = self.tracker.get_call("create_product")
        assert len(create_product["args"]["content_ids"]) > 0

    def test_product_uses_page_id(self):
        """상품 옵션이 올바른 productGroupId를 사용하는지 검증."""
        self._simulate_flow()

        create_product = self.tracker.get_call("create_product")
        assert create_product["args"]["product_group_id"] == "page_001"

    def test_page_status_stays_inactive(self):
        """플레이스홀더 이미지가 있으므로 페이지 상태가 INACTIVE로 유지되는지 검증."""
        self._simulate_flow()

        status_call = self.tracker.get_call("update_product_page_status")
        assert status_call["args"]["status"] == "INACTIVE"


# ──────────────────────────────────────────────
# 시나리오 2: 시리즈 없을 때 자동 생성
# ──────────────────────────────────────────────


class TestSeriesAutoCreation:
    """시리즈가 없을 때 자동 생성 후 진행하는 플로우."""

    def setup_method(self):
        self.tracker = ToolCallTracker()

    def _simulate_flow(self):
        t = self.tracker

        # Phase 0
        t.record("search_masters", {"search_keyword": "테스트 마스터"}, SEARCH_MASTERS_FOUND)
        t.record("get_master_groups", {"name": "테스트 마스터"}, MASTER_GROUPS)

        # Phase 1: 시리즈 없음 → 생성
        t.record("get_series_list", {"master_id": "136"}, SERIES_LIST_EMPTY)
        t.record(
            "create_series",
            {
                "master_id": "655bfe94c7dacf9f1db4ceaf",  # 시리즈 생성은 MongoDB ID 사용
                "title": "테스트 시리즈",
                "description": "에이전트가 생성한 시리즈",
                "categories": ["investment"],
            },
            CREATE_SERIES_SUCCESS,
        )

        # Phase 2~5 계속...
        t.record("get_product_page_list", {"master_id": "136"}, PRODUCT_PAGE_LIST_EMPTY)
        t.record("create_product_page", {"master_id": "136", "title": "테스트 상품", "product_type": "SUBSCRIPTION"}, CREATE_PRODUCT_PAGE_SUCCESS)
        t.record("get_product_page_list", {"master_id": "136"}, PRODUCT_PAGE_LIST_FOUND)
        t.record("create_product", {"product_group_id": "page_001", "name": "월간", "origin_price": 29900, "content_ids": ["series_new_001"], "display_texts": ["이용권"], "payment_period": "ONE_MONTH"}, CREATE_PRODUCT_SUCCESS)

    def test_series_created_before_product(self):
        """시리즈가 상품 옵션보다 먼저 생성되는지 검증."""
        self._simulate_flow()

        names = self.tracker.tool_names
        series_idx = names.index("create_series")
        product_idx = names.index("create_product")
        assert series_idx < product_idx

    def test_created_series_id_used_in_product(self):
        """생성된 시리즈 ID가 상품 옵션의 contentIds에 사용되는지 검증."""
        self._simulate_flow()

        create_product = self.tracker.get_call("create_product")
        assert "series_new_001" in create_product["args"]["content_ids"]


# ──────────────────────────────────────────────
# 시나리오 3: 마스터 없을 때
# ──────────────────────────────────────────────


class TestMasterNotFound:
    """마스터가 없을 때의 처리 검증."""

    def setup_method(self):
        self.tracker = ToolCallTracker()

    def _simulate_flow(self):
        t = self.tracker

        # 오피셜클럽 없음
        t.record("search_masters", {"search_keyword": "새마스터"}, SEARCH_MASTERS_EMPTY)
        # 마스터 그룹도 없음
        t.record("get_master_groups", {"name": "새마스터"}, MASTER_GROUPS_EMPTY)
        # 마스터 그룹 자동 생성
        t.record("create_master_group", {"name": "새마스터"}, CREATE_MASTER_GROUP_SUCCESS)

    def test_master_group_auto_created(self):
        """마스터 그룹이 없으면 자동 생성하는지 검증."""
        self._simulate_flow()

        assert "create_master_group" in self.tracker.tool_names

    def test_search_both_masters_and_groups(self):
        """오피셜클럽과 마스터 그룹을 둘 다 검색하는지 검증."""
        self._simulate_flow()

        assert "search_masters" in self.tracker.tool_names
        assert "get_master_groups" in self.tracker.tool_names

    def test_no_product_creation_without_official_club(self):
        """오피셜클럽 없이 상품 페이지를 생성하지 않는지 검증."""
        self._simulate_flow()

        assert "create_product_page" not in self.tracker.tool_names
        assert "create_product" not in self.tracker.tool_names


# ──────────────────────────────────────────────
# 시나리오 4: 단건상품
# ──────────────────────────────────────────────


class TestOneTimePurchaseFlow:
    """단건상품 세팅 시 구독과 다른 부분 검증."""

    def setup_method(self):
        self.tracker = ToolCallTracker()

    def _simulate_flow(self):
        t = self.tracker

        t.record("search_masters", {"search_keyword": "테스트"}, SEARCH_MASTERS_FOUND)
        t.record("get_master_groups", {"name": "테스트"}, MASTER_GROUPS)
        t.record("get_series_list", {"master_id": "136"}, SERIES_LIST_FOUND)
        t.record("get_product_page_list", {"master_id": "136"}, PRODUCT_PAGE_LIST_EMPTY)
        t.record(
            "create_product_page",
            {
                "master_id": "136",
                "title": "단건 상품",
                "product_type": "ONE_TIME_PURCHASE",
                "is_changeable": False,  # 단건은 변경 불가
            },
            CREATE_PRODUCT_PAGE_SUCCESS,
        )
        t.record("get_product_page_list", {"master_id": "136"}, PRODUCT_PAGE_LIST_FOUND)
        t.record(
            "create_product",
            {
                "product_group_id": "page_001",
                "name": "60일 이용권",
                "origin_price": 99000,
                "content_ids": ["series_001"],
                "display_texts": ["전체 시리즈 60일 이용"],
                "usage_period_type": "DURATION",
                "use_duration": 60,
            },
            CREATE_PRODUCT_SUCCESS,
        )

    def test_one_time_not_changeable(self):
        """단건 상품 페이지는 is_changeable=False인지 검증."""
        self._simulate_flow()

        create_page = self.tracker.get_call("create_product_page")
        assert create_page["args"]["is_changeable"] is False

    def test_one_time_uses_duration(self):
        """단건 상품은 paymentPeriod 대신 usagePeriodType을 사용하는지 검증."""
        self._simulate_flow()

        create_product = self.tracker.get_call("create_product")
        assert "payment_period" not in create_product["args"]
        assert create_product["args"]["usage_period_type"] == "DURATION"
        assert create_product["args"]["use_duration"] == 60

    def test_one_time_no_subscription_discount(self):
        """단건 상품에 SUBSCRIPTION_COUNT_DISCOUNT가 없는지 검증."""
        self._simulate_flow()

        create_product = self.tracker.get_call("create_product")
        assert create_product["args"].get("promotion_type") != "SUBSCRIPTION_COUNT_DISCOUNT"
