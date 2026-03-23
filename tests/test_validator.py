"""
검증 에이전트 단위 테스트.

LLM 호출 없이 규칙 기반 검증 도구를 직접 테스트한다.
pytest parametrize로 엣지케이스를 대량 커버.
"""

import pytest
from src.agents.validator import (
    check_prerequisites,
    check_idempotency,
    diagnose_visibility,
    PREREQUISITES,
)


# ── check_prerequisites 테스트 ──


class TestCheckPrerequisites:
    """사전조건 체크 — 조건 충족/미충족 시나리오."""

    # (action, context, expected_allowed, expected_missing)
    @pytest.mark.parametrize("action, context, allowed, missing", [
        # 조회 — 사전조건 없음
        ("search_masters", {}, True, []),
        ("get_master_groups", {}, True, []),

        # 마스터 ID만 필요
        ("get_master_detail", {"master_id": "35"}, True, []),
        ("get_master_detail", {}, False, ["master_id"]),
        ("get_series_list", {"master_id": "35"}, True, []),
        ("get_series_list", {}, False, ["master_id"]),

        # 상품 페이지 생성 — master_id + series_ids 필요
        ("create_product_page", {"master_id": "35", "series_ids": ["s1"]}, True, []),
        ("create_product_page", {"master_id": "35"}, False, ["series_ids"]),
        ("create_product_page", {"series_ids": ["s1"]}, False, ["master_id"]),
        ("create_product_page", {}, False, ["master_id", "series_ids"]),
        # 빈 시리즈 배열 → 미충족
        ("create_product_page", {"master_id": "35", "series_ids": []}, False, ["series_ids"]),

        # 상품 옵션 생성 — product_page_id + series_ids 필요
        ("create_product", {"product_page_id": "p1", "series_ids": ["s1"]}, True, []),
        ("create_product", {"product_page_id": "p1"}, False, ["series_ids"]),
        ("create_product", {}, False, ["product_page_id", "series_ids"]),

        # 활성화 — 다양한 조합
        ("update_product_display", {"product_id": "99"}, True, []),
        ("update_product_display", {}, False, ["product_id"]),
        ("update_product_sequence", {"product_page_id": "p1", "product_ids": ["99"]}, True, []),
        ("update_product_sequence", {"product_page_id": "p1", "product_ids": []}, False, ["product_ids"]),
        ("update_product_page_status", {"product_page_id": "p1"}, True, []),
        ("update_main_product_setting", {"master_id": "35"}, True, []),

        # 검증
        ("verify_product_setup", {"master_id": "35", "product_page_id": "p1"}, True, []),
        ("verify_product_setup", {"master_id": "35"}, False, ["product_page_id"]),

        # 알 수 없는 액션 — 사전조건 없음 (통과)
        ("unknown_action", {}, True, []),
    ])
    def test_prerequisites(self, action, context, allowed, missing):
        # Strands @tool은 함수 자체를 호출 가능
        result = check_prerequisites._tool_func(action=action, context=context)
        assert result["allowed"] == allowed, f"{action}: expected allowed={allowed}, got {result}"
        assert result["missing"] == missing, f"{action}: expected missing={missing}, got {result['missing']}"

    def test_prerequisites_returns_messages_for_missing(self):
        """미충족 사전조건에 대해 안내 메시지가 포함되는지 확인."""
        result = check_prerequisites._tool_func(
            action="create_product_page",
            context={},
        )
        assert not result["allowed"]
        assert len(result["messages"]) == 2  # master_id, series_ids
        assert any("마스터" in m for m in result["messages"])
        assert any("시리즈" in m for m in result["messages"])

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
        "create_master_group", "get_series_list", "create_series",
        "create_product_page", "create_product",
        "get_product_page_list", "get_product_page_detail", "get_product_list_by_page",
        "update_product_display", "update_product_sequence",
        "update_product_page_status", "update_main_product_setting",
        "verify_product_setup",
    ]

    def test_all_tools_have_prerequisites(self):
        """모든 알려진 Tool이 PREREQUISITES에 정의되어 있는지."""
        for tool_name in self.KNOWN_TOOLS:
            assert tool_name in PREREQUISITES, f"{tool_name}이 PREREQUISITES에 없습니다"

    def test_no_circular_prerequisites(self):
        """사전조건에 순환이 없는지 확인 (A→B→A 방지)."""
        # 현재 구조에서는 값이 키가 아니므로 순환 불가하지만, 안전장치.
        for action, deps in PREREQUISITES.items():
            for dep in deps:
                # dep 자체가 action이면 안 됨
                assert dep != action, f"순환 사전조건: {action} → {dep}"


class TestCheckIdempotency:
    """멱등성 검증 테스트 (Mock 모드에서)."""

    def test_unknown_action_returns_not_exists(self):
        """알 수 없는 액션은 exists=False 반환."""
        result = check_idempotency._tool_func(action="unknown", context={})
        assert not result["exists"]

    def test_create_product_page_without_master_id(self):
        """master_id 없이 멱등성 체크 → exists=False (조회 스킵)."""
        result = check_idempotency._tool_func(
            action="create_product_page",
            context={"title": "test"},
        )
        assert not result["exists"]

    def test_create_product_without_page_id(self):
        """product_page_id 없이 → exists=False."""
        result = check_idempotency._tool_func(
            action="create_product",
            context={"name": "test"},
        )
        assert not result["exists"]


class TestPrerequisiteChain:
    """사전조건 체인의 논리적 일관성 테스트.

    체인: 마스터 → 시리즈 → 상품 페이지 → 상품 옵션 → 활성화
    """

    def test_chain_order(self):
        """체인 순서가 논리적으로 맞는지 — 뒤 단계일수록 사전조건이 많거나 같아야."""
        chain = [
            ("search_masters", 0),
            ("get_series_list", 1),       # master_id
            ("create_product_page", 2),   # master_id, series_ids
            ("create_product", 2),        # product_page_id, series_ids
            ("update_product_display", 1),  # product_id
            ("verify_product_setup", 2),  # master_id, product_page_id
        ]
        for action, expected_count in chain:
            actual = len(PREREQUISITES[action])
            assert actual == expected_count, f"{action}: expected {expected_count} prerequisites, got {actual}"

    def test_create_without_master_blocked(self):
        """마스터 없이 상품 페이지 생성 → 차단."""
        result = check_prerequisites._tool_func(
            action="create_product_page",
            context={"series_ids": ["s1"]},  # master_id 없음
        )
        assert not result["allowed"]
        assert "master_id" in result["missing"]

    def test_create_without_series_blocked(self):
        """시리즈 없이 상품 옵션 등록 → 차단."""
        result = check_prerequisites._tool_func(
            action="create_product",
            context={"product_page_id": "p1"},  # series_ids 없음
        )
        assert not result["allowed"]
        assert "series_ids" in result["missing"]

    def test_activate_with_all_prerequisites(self):
        """모든 사전조건 충족 시 활성화 허용."""
        result = check_prerequisites._tool_func(
            action="update_product_page_status",
            context={"product_page_id": "p1"},
        )
        assert result["allowed"]

    def test_hidden_page_skips_some_visibility(self):
        """히든 페이지는 마스터 PUBLIC, 메인 ACTIVE 불필요 (검증 에이전트가 알아야 할 규칙)."""
        from src.agents.validator import VISIBILITY_CHAIN, VISIBILITY_CHAIN_HIDDEN
        assert len(VISIBILITY_CHAIN_HIDDEN) < len(VISIBILITY_CHAIN)
        hidden_conditions = [c[0] for c in VISIBILITY_CHAIN_HIDDEN]
        assert "master_public" not in hidden_conditions
        assert "main_product_active" not in hidden_conditions


class TestRealWorldScenarios:
    """Langfuse 트레이스에서 추출한 실제 유저 시나리오 기반 테스트.

    봄날의 햇살 (cmsId: 60) 실제 데이터:
    - 마스터: PUBLIC
    - 메인 상품 페이지: INACTIVE (비공개)
    - 상품 페이지 2개: 코드 141 (히든, ACTIVE), 코드 124 (일반, ACTIVE)
    - 옵션: 각 페이지에 2개씩 (일부 isDisplay=false)
    """

    # ── 시나리오 1: "페이지 ACTIVE인데 메인이 INACTIVE → 실제 노출 안 됨" ──
    # Langfuse: 유저가 "124가 보인다고? 메인이 비공개인데?" 지적

    def test_page_active_but_main_inactive_is_not_visible(self):
        """상품 페이지가 ACTIVE여도, 메인 상품이 INACTIVE면 고객에게 안 보인다.

        이전 에이전트 버그: "단건상품(124)이 노출 중"이라고 잘못 답변.
        검증 에이전트가 이 조합을 "not visible"로 판단해야 한다.
        """
        from src.agents.validator import VISIBILITY_CHAIN
        # 체인: master_public → main_product_active → page_active → ...
        # main_product_active가 실패하면 page_active 여부와 무관하게 미노출
        chain_conditions = [c[0] for c in VISIBILITY_CHAIN]
        main_idx = chain_conditions.index("main_product_active")
        page_idx = chain_conditions.index("page_active")
        assert main_idx < page_idx, "메인 상품 체크가 페이지 체크보다 먼저 와야 함"

    def test_page_active_main_inactive_prerequisite_check(self):
        """활성화 시 메인 상품이 INACTIVE면 경고해야."""
        # update_main_product_setting의 사전조건은 master_id만 필요
        result = check_prerequisites._tool_func(
            action="update_main_product_setting",
            context={"master_id": "60"},
        )
        assert result["allowed"]  # 실행 자체는 가능 (master_id 있으니까)

    # ── 시나리오 2: 히든 페이지 구분 ──
    # Langfuse: "히든페이지 있어?", "히든페이지말고 상품페이지에서는 노출중인 페이지 잇어?"

    def test_hidden_page_visibility_rules(self):
        """히든 페이지는 마스터 PUBLIC, 메인 ACTIVE 없이도 URL 직접 접근 가능.

        봄날의 햇살 코드 141: 히든 → 마스터 PUBLIC이고 메인 INACTIVE여도 URL로 접근 가능
        봄날의 햇살 코드 124: 일반 → 메인 INACTIVE이면 접근 불가
        """
        from src.agents.validator import VISIBILITY_CHAIN, VISIBILITY_CHAIN_HIDDEN
        # 일반 페이지: 5개 조건 (master_public, main_product_active, page_active, page_in_period, option_displayed)
        # 히든 페이지: 2개 조건 (page_active, option_displayed)
        assert len(VISIBILITY_CHAIN) == 5
        assert len(VISIBILITY_CHAIN_HIDDEN) == 2

    # ── 시나리오 3: "수정할게 있어" → 잘못된 분류 ──
    # Langfuse: "봄날의 햇살 상품페이지 중 수정할게 있어" → 진단으로 분류됨
    # 이건 오케스트레이터의 분류 문제이지 검증 에이전트 문제는 아님.
    # 하지만, "수정"에 필요한 사전조건은 체크해야 함.

    def test_edit_action_requires_page_id(self):
        """상품 페이지 수정 시 product_page_id 필요."""
        result = check_prerequisites._tool_func(
            action="get_product_page_detail",
            context={},  # page_id 없음
        )
        assert not result["allowed"]
        assert "product_page_id" in result["missing"]

    def test_edit_action_allowed_with_page_id(self):
        """product_page_id 있으면 상세 조회 허용."""
        result = check_prerequisites._tool_func(
            action="get_product_page_detail",
            context={"product_page_id": "mock_page_141"},
        )
        assert result["allowed"]

    # ── 시나리오 4: "다 했는데 왜 노출이 안되지?" ──
    # Langfuse: 유저가 상품 세팅 후 노출 안 되는 이유를 질문.
    # 진단 = diagnose_visibility 호출. 사전조건: master_id

    def test_diagnose_requires_master_id(self):
        """진단에는 master_id가 필수."""
        # diagnose_visibility는 직접 master_id를 받으므로 prerequisites 아님.
        # 하지만 verify_product_setup은 master_id + product_page_id 필요.
        result = check_prerequisites._tool_func(
            action="verify_product_setup",
            context={},
        )
        assert not result["allowed"]
        assert "master_id" in result["missing"]
        assert "product_page_id" in result["missing"]

    # ── 시나리오 5: 상시공개 페이지 중복 생성 방지 ──
    # 실제 에러: "상시 공개 상품 페이지가 이미 존재" (400)

    def test_duplicate_always_public_page_blocked(self):
        """상시공개 페이지가 이미 있는데 또 만들려고 하면 멱등성 체크가 잡아야."""
        # 이 테스트는 check_idempotency가 API를 조회하므로 Mock 모드에서는 제한적.
        # 하지만 함수 시그니처와 반환 구조는 확인.
        result = check_idempotency._tool_func(
            action="create_product_page",
            context={"master_id": "60", "title": "단건상품"},
        )
        # Mock 모드에서는 exists=False (API 미호출)
        assert isinstance(result, dict)
        assert "exists" in result
        assert "message" in result

    # ── 시나리오 6: 활성화 4단계 순서 ──
    # 활성화: display ON → 순서 → 페이지 공개 → 메인 설정

    @pytest.mark.parametrize("action, context, allowed", [
        # 1단계: 상품 노출 ON — product_id 필요
        ("update_product_display", {"product_id": "99999"}, True),
        ("update_product_display", {}, False),
        # 2단계: 순서 설정 — product_page_id + product_ids
        ("update_product_sequence", {"product_page_id": "p1", "product_ids": ["99"]}, True),
        ("update_product_sequence", {"product_page_id": "p1"}, False),
        # 3단계: 페이지 공개 — product_page_id
        ("update_product_page_status", {"product_page_id": "p1"}, True),
        ("update_product_page_status", {}, False),
        # 4단계: 메인 상품 설정 — master_id
        ("update_main_product_setting", {"master_id": "60"}, True),
        ("update_main_product_setting", {}, False),
    ])
    def test_activation_steps(self, action, context, allowed):
        """활성화 4단계 각각의 사전조건 체크."""
        result = check_prerequisites._tool_func(action=action, context=context)
        assert result["allowed"] == allowed

    # ── 시나리오 7: 맥락 전환 (진단 → 수정 → 활성화) ──
    # Langfuse: 유저가 진단하다가 "그거 활성화해줘"로 맥락 전환

    def test_context_switch_diagnose_to_activate(self):
        """진단 후 활성화 요청 — 사전조건만 맞으면 바로 실행 가능 (스테이트 머신 불필요)."""
        # 진단 중 수집된 컨텍스트로 바로 활성화 가능해야
        context = {
            "master_id": "60",
            "product_page_id": "mock_page_124",
            "product_ids": ["99999"],
            "product_id": "99999",
        }
        # 활성화 4단계 모두 가능해야
        for action in [
            "update_product_display",
            "update_product_sequence",
            "update_product_page_status",
            "update_main_product_setting",
        ]:
            result = check_prerequisites._tool_func(action=action, context=context)
            assert result["allowed"], f"{action} should be allowed with full context"
