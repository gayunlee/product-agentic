"""
ActionHarness 단위 테스트.

MOCK_MODE=true 전제. 슬롯 검증, prerequisites, cascading, confirm, execute를 테스트한다.
"""

import json
import os
import pytest

os.environ["MOCK_MODE"] = "true"

from src.harness import ActionHarness, get_harness


@pytest.fixture
def harness():
    return ActionHarness()


# ── 슬롯 검증 ──


class TestSlotValidation:
    def test_missing_required_slots(self, harness):
        result = json.loads(harness.validate_and_confirm("update_product_display", {}))
        assert result["mode"] == "error"
        assert "product_id" in result["message"]

    def test_partial_slots(self, harness):
        result = json.loads(harness.validate_and_confirm(
            "update_product_display", {"product_id": "99999"}
        ))
        assert result["mode"] == "error"
        assert "is_display" in result["message"]

    def test_false_is_valid_slot(self, harness):
        """is_display=False는 유효한 값 (falsy지만 None이 아님)."""
        result = json.loads(harness.validate_and_confirm(
            "update_product_display",
            {"product_id": "99999", "is_display": False, "master_name": "테스트"},
        ))
        assert result["mode"] == "execute"

    def test_unknown_action(self, harness):
        result = json.loads(harness.validate_and_confirm("unknown_action", {}))
        assert result["mode"] == "error"
        assert "알 수 없는" in result["message"]


# ── Prerequisites ──


class TestPrerequisites:
    def test_idempotent_block(self, harness):
        """이미 같은 상태면 차단."""
        result = json.loads(harness.validate_and_confirm(
            "update_product_display",
            {"product_id": "99999", "is_display": False},
            {"product": {"exists": True, "isDisplay": False}},
        ))
        assert result["mode"] == "error"

    def test_skip_when_no_data(self, harness):
        """컨텍스트에 데이터가 없으면 prerequisites 스킵."""
        result = json.loads(harness.validate_and_confirm(
            "update_product_display",
            {"product_id": "99999", "is_display": False, "master_name": "테스트"},
        ))
        # 데이터 없으므로 스킵 → 확인 메시지
        assert result["mode"] == "execute"

    def test_prerequisite_pass(self, harness):
        """조건 충족 시 통과."""
        result = json.loads(harness.validate_and_confirm(
            "update_product_display",
            {"product_id": "99999", "is_display": False, "master_name": "테스트"},
            {"product": {"exists": True, "isDisplay": True}},
        ))
        assert result["mode"] == "execute"


# ── Cascading ──


class TestCascading:
    def test_last_product_warning(self, harness):
        """마지막 공개 상품 비공개 시 경고."""
        result = json.loads(harness.validate_and_confirm(
            "update_product_display",
            {
                "product_id": "99999", "is_display": False,
                "master_name": "조조형우", "page_title": "월간 투자",
                "product_name": "리포트", "page_id": "p1",
            },
            {"product": {"exists": True, "isDisplay": True}, "page": {"displayedProductCount": 1}},
        ))
        assert result["mode"] == "execute"
        assert "주의" in result["message"]
        # suggest 버튼 존재
        suggest_btns = [b for b in result["buttons"] if "상품페이지" in b.get("label", "")]
        assert len(suggest_btns) >= 1

    def test_no_warning_when_multiple_products(self, harness):
        """여러 상품이 공개 중이면 경고 없음."""
        result = json.loads(harness.validate_and_confirm(
            "update_product_display",
            {
                "product_id": "99999", "is_display": False,
                "master_name": "조조형우", "page_title": "월간 투자",
                "product_name": "리포트", "page_id": "p1",
            },
            {"product": {"exists": True, "isDisplay": True}, "page": {"displayedProductCount": 3}},
        ))
        assert "주의" not in result["message"]


# ── Confirmation ──


class TestConfirmation:
    def test_confirm_message_format(self, harness):
        result = json.loads(harness.validate_and_confirm(
            "update_product_display",
            {
                "product_id": "99999", "is_display": False,
                "master_name": "조조형우", "page_title": "월간 투자",
                "product_name": "리포트",
            },
        ))
        assert result["mode"] == "execute"
        assert "조조형우" in result["message"]
        assert "월간 투자" in result["message"]
        assert "비공개" in result["message"]

    def test_confirm_buttons(self, harness):
        result = json.loads(harness.validate_and_confirm(
            "update_product_display",
            {"product_id": "99999", "is_display": True, "master_name": "테스트"},
        ))
        buttons = result["buttons"]
        # 실행 버튼
        exec_btn = next((b for b in buttons if b.get("action") == "execute_confirmed"), None)
        assert exec_btn is not None
        assert exec_btn["payload"]["action_id"] == "update_product_display"
        # 취소 버튼
        cancel_btn = next((b for b in buttons if b.get("action") == "cancel"), None)
        assert cancel_btn is not None

    def test_page_status_confirm(self, harness):
        result = json.loads(harness.validate_and_confirm(
            "update_product_page_status",
            {"page_id": "p1", "status": "INACTIVE", "master_cms_id": "35", "master_name": "조조형우", "page_title": "페이지"},
        ))
        assert result["mode"] == "execute"
        assert "INACTIVE" in result["message"]

    def test_main_product_confirm(self, harness):
        result = json.loads(harness.validate_and_confirm(
            "update_main_product_setting",
            {"master_cms_id": "35", "view_status": "ACTIVE", "master_name": "조조형우"},
        ))
        assert result["mode"] == "execute"


# ── Execute Confirmed ──


class TestExecuteConfirmed:
    def test_execute_success(self, harness):
        result = harness.execute_confirmed(
            "update_product_display",
            {"product_id": "99999", "is_display": False, "page_id": "p1"},
        )
        assert result["mode"] == "done"
        assert "완료" in result["message"]

    def test_execute_navigate_button(self, harness):
        result = harness.execute_confirmed(
            "update_product_display",
            {"product_id": "99999", "is_display": True, "page_id": "p1"},
        )
        nav_btns = [b for b in result.get("buttons", []) if b.get("type") == "navigate"]
        assert len(nav_btns) >= 1

    def test_execute_page_status(self, harness):
        result = harness.execute_confirmed(
            "update_product_page_status",
            {"page_id": "mock_page_001", "status": "INACTIVE"},
        )
        assert result["mode"] == "done"

    def test_execute_unknown_action(self, harness):
        result = harness.execute_confirmed("unknown", {})
        assert result["mode"] == "error"

    def test_execute_main_product(self, harness):
        result = harness.execute_confirmed(
            "update_main_product_setting",
            {"master_cms_id": "35", "view_status": "ACTIVE"},
        )
        assert result["mode"] == "done"
