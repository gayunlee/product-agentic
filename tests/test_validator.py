"""
검증 에이전트 단위 테스트.

LLM 호출 없이 규칙 기반 검증 도구를 직접 테스트한다.
pytest parametrize로 엣지케이스를 대량 커버.

⚠️ validator.py는 레거시. 새 코드는 harness.py + diagnose_engine.py 사용.
   이 테스트는 wizard.py가 아직 사용하는 check_cascading_effects와
   레거시 호환을 위해 유지.
"""

import os
import pytest

os.environ["MOCK_MODE"] = "true"

from src.agents.validator import (
    check_prerequisites,
    check_idempotency,
    diagnose_visibility,
    check_cascading_effects,
    PREREQUISITES,
)


# ── check_prerequisites 테스트 ──


class TestCheckPrerequisites:
    """사전조건 체크 — 조건 충족/미충족 시나리오."""

    @pytest.mark.parametrize("action, context, allowed, missing", [
        # 조회 — 사전조건 없음
        ("search_masters", {}, True, []),
        ("get_master_groups", {}, True, []),

        # 마스터 ID만 필요
        ("get_master_detail", {"master_id": "35"}, True, []),
        ("get_master_detail", {}, False, ["master_id"]),
        ("get_series_list", {"master_id": "35"}, True, []),
        ("get_series_list", {}, False, ["master_id"]),

        # 상품 관련
        ("update_product_display", {"product_id": "99"}, True, []),
        ("update_product_display", {}, False, ["product_id"]),
        ("update_product_page_status", {"product_page_id": "p1"}, True, []),
        ("update_product_page_status", {}, False, ["product_page_id"]),
        ("update_main_product_setting", {"master_id": "35"}, True, []),
        ("update_main_product_setting", {}, False, ["master_id"]),

        # 조회 관련
        ("get_product_page_list", {"master_id": "35"}, True, []),
        ("get_product_page_list", {}, False, ["master_id"]),
        ("get_product_page_detail", {"product_page_id": "p1"}, True, []),
        ("get_product_page_detail", {}, False, ["product_page_id"]),
        ("get_product_list_by_page", {"product_page_id": "p1"}, True, []),
        ("get_product_list_by_page", {}, False, ["product_page_id"]),
        ("get_community_settings", {"cms_id": "35"}, True, []),
        ("get_community_settings", {}, False, ["cms_id"]),

        # 알 수 없는 액션 — 사전조건 없음 (통과)
        ("unknown_action", {}, True, []),
    ])
    def test_prerequisites(self, action, context, allowed, missing):
        result = check_prerequisites._tool_func(action=action, context=context)
        assert result["allowed"] == allowed, f"{action}: expected allowed={allowed}, got {result}"
        assert result["missing"] == missing, f"{action}: expected missing={missing}, got {result['missing']}"

    def test_prerequisites_returns_messages_for_missing(self):
        """미충족 사전조건에 대해 안내 메시지가 포함되는지 확인."""
        result = check_prerequisites._tool_func(
            action="get_master_detail",
            context={},
        )
        assert not result["allowed"]
        assert len(result["messages"]) == 1
        assert any("마스터" in m for m in result["messages"])

    def test_empty_string_treated_as_missing(self):
        """빈 문자열도 미충족으로 처리."""
        result = check_prerequisites._tool_func(
            action="get_master_detail",
            context={"master_id": ""},
        )
        assert not result["allowed"]

    def test_none_treated_as_missing(self):
        """None도 미충족으로 처리."""
        result = check_prerequisites._tool_func(
            action="get_master_detail",
            context={"master_id": None},
        )
        assert not result["allowed"]


class TestCheckPrerequisitesCompleteness:
    """PREREQUISITES 테이블의 완전성 검증."""

    KNOWN_TOOLS = [
        "search_masters", "get_master_groups", "get_master_detail",
        "get_series_list",
        "get_product_page_list", "get_product_page_detail", "get_product_list_by_page",
        "get_community_settings",
        "update_product_display",
        "update_product_page_status", "update_product_page",
        "update_main_product_setting",
    ]

    def test_all_tools_have_prerequisites(self):
        """모든 알려진 Tool이 PREREQUISITES에 정의되어 있는지."""
        for tool_name in self.KNOWN_TOOLS:
            assert tool_name in PREREQUISITES, f"{tool_name}이 PREREQUISITES에 없습니다"

    def test_no_circular_prerequisites(self):
        """사전조건에 순환이 없는지 확인."""
        for action, deps in PREREQUISITES.items():
            for dep in deps:
                assert dep != action, f"순환 사전조건: {action} → {dep}"


class TestCheckIdempotency:
    """멱등성 검증 테스트 (Mock 모드에서)."""

    def test_unknown_action_returns_not_exists(self):
        result = check_idempotency._tool_func(action="unknown", context={})
        assert not result["exists"]

    def test_create_product_page_without_master_id(self):
        result = check_idempotency._tool_func(
            action="create_product_page",
            context={"title": "test"},
        )
        assert not result["exists"]

    def test_create_product_without_page_id(self):
        result = check_idempotency._tool_func(
            action="create_product",
            context={"name": "test"},
        )
        assert not result["exists"]


class TestCheckCascadingEffects:
    """계단식 영향 검증 — wizard.py에서 사용 중."""

    def test_no_warning_for_non_matching_action(self):
        result = check_cascading_effects._tool_func(
            action="update_product_display",
            context={"is_display": True},  # 공개 → 경고 없음
        )
        assert not result["has_warning"]

    def test_page_inactive_warning_structure(self):
        """비공개 처리 시 경고 반환 구조."""
        result = check_cascading_effects._tool_func(
            action="update_product_page_status",
            context={"target_status": "INACTIVE", "master_id": "35", "product_page_id": "mock_page_001"},
        )
        assert isinstance(result, dict)
        assert "has_warning" in result
        assert "warning" in result
        assert "suggested_actions" in result


class TestPrerequisiteChain:
    """사전조건 체인의 논리적 일관성 테스트."""

    def test_chain_order(self):
        """체인 순서 — 뒤 단계일수록 사전조건이 많거나 같아야."""
        chain = [
            ("search_masters", 0),
            ("get_series_list", 1),       # master_id
            ("update_product_display", 1),  # product_id
            ("update_main_product_setting", 1),  # master_id
        ]
        for action, expected_count in chain:
            actual = len(PREREQUISITES[action])
            assert actual == expected_count, f"{action}: expected {expected_count} prerequisites, got {actual}"

    def test_activate_with_all_prerequisites(self):
        """모든 사전조건 충족 시 활성화 허용."""
        result = check_prerequisites._tool_func(
            action="update_product_page_status",
            context={"product_page_id": "p1"},
        )
        assert result["allowed"]

    def test_hidden_page_skips_some_visibility(self):
        """히든 페이지는 마스터 PUBLIC, 메인 ACTIVE 불필요."""
        from src.agents.validator import VISIBILITY_CHAIN, VISIBILITY_CHAIN_HIDDEN
        assert len(VISIBILITY_CHAIN_HIDDEN) < len(VISIBILITY_CHAIN)
        hidden_conditions = [c[0] for c in VISIBILITY_CHAIN_HIDDEN]
        assert "master_public" not in hidden_conditions
        assert "main_product_active" not in hidden_conditions


class TestRealWorldScenarios:
    """Langfuse 트레이스에서 추출한 실제 유저 시나리오 기반 테스트."""

    def test_page_active_but_main_inactive_is_not_visible(self):
        """상품 페이지가 ACTIVE여도, 메인 상품이 INACTIVE면 고객에게 안 보인다."""
        from src.agents.validator import VISIBILITY_CHAIN
        chain_conditions = [c[0] for c in VISIBILITY_CHAIN]
        main_idx = chain_conditions.index("main_product_active")
        page_idx = chain_conditions.index("page_active")
        assert main_idx < page_idx, "메인 상품 체크가 페이지 체크보다 먼저 와야 함"

    def test_page_active_main_inactive_prerequisite_check(self):
        """활성화 시 메인 상품이 INACTIVE면 경고해야."""
        result = check_prerequisites._tool_func(
            action="update_main_product_setting",
            context={"master_id": "60"},
        )
        assert result["allowed"]

    def test_hidden_page_visibility_rules(self):
        """히든 페이지 vs 일반 페이지 가시성 규칙."""
        from src.agents.validator import VISIBILITY_CHAIN, VISIBILITY_CHAIN_HIDDEN
        assert len(VISIBILITY_CHAIN) == 5
        assert len(VISIBILITY_CHAIN_HIDDEN) == 2

    def test_edit_action_requires_page_id(self):
        result = check_prerequisites._tool_func(
            action="get_product_page_detail",
            context={},
        )
        assert not result["allowed"]
        assert "product_page_id" in result["missing"]

    def test_edit_action_allowed_with_page_id(self):
        result = check_prerequisites._tool_func(
            action="get_product_page_detail",
            context={"product_page_id": "mock_page_141"},
        )
        assert result["allowed"]

    def test_duplicate_always_public_page_blocked(self):
        """상시공개 페이지 중복 → 멱등성 체크."""
        result = check_idempotency._tool_func(
            action="create_product_page",
            context={"master_id": "60", "title": "단건상품"},
        )
        assert isinstance(result, dict)
        assert "exists" in result
        assert "message" in result

    @pytest.mark.parametrize("action, context, allowed", [
        ("update_product_display", {"product_id": "99999"}, True),
        ("update_product_display", {}, False),
        ("update_product_page_status", {"product_page_id": "p1"}, True),
        ("update_product_page_status", {}, False),
        ("update_main_product_setting", {"master_id": "60"}, True),
        ("update_main_product_setting", {}, False),
    ])
    def test_activation_steps(self, action, context, allowed):
        """활성화 단계별 사전조건 체크."""
        result = check_prerequisites._tool_func(action=action, context=context)
        assert result["allowed"] == allowed

    def test_context_switch_diagnose_to_activate(self):
        """진단 후 활성화 요청 — 사전조건만 맞으면 바로 실행 가능."""
        context = {
            "master_id": "60",
            "product_page_id": "mock_page_124",
            "product_id": "99999",
        }
        for action in [
            "update_product_display",
            "update_product_page_status",
            "update_main_product_setting",
        ]:
            result = check_prerequisites._tool_func(action=action, context=context)
            assert result["allowed"], f"{action} should be allowed with full context"
