"""
하네스 회귀 테스트 — Obsidian 노트에서 추출한 시행착오 이슈 검증.

노트에서 발견된 핵심 문제들이 ActionHarness + DiagnoseEngine으로 해결되었는지 확인.
각 테스트에 해당 노트 날짜와 이슈를 주석으로 기록.
"""

import os
import json
import pytest

os.environ["MOCK_MODE"] = "true"

from src.harness import ActionHarness
from src.diagnose_engine import DiagnoseEngine


@pytest.fixture
def harness():
    return ActionHarness()


@pytest.fixture
def engine():
    return DiagnoseEngine()


# ══════════════════════════════════════════════════
# 2026-03-27: "프롬프트 규칙은 확률적, Tool 코드는 결정적"
# ══════════════════════════════════════════════════


class TestPromptRulesToCodeEnforcement:
    """노트 3/27: LLM이 프롬프트 규칙(E3, E5, E12 등)을 무시하는 문제.
    → Harness가 코드로 강제하므로 LLM이 무시해도 실행 불가."""

    def test_no_write_without_harness(self, harness):
        """이슈: LLM이 check_prerequisites를 안 부르고 바로 쓰기 API 호출.
        해결: 쓰기 API가 executor에서 제거됨. request_action만 존재.
        request_action 내부에서 Harness가 자동 검증."""
        from src.agents.executor import create_executor_agent
        agent = create_executor_agent()
        tool_names = agent.tool_names

        # 쓰기 API가 직접 노출되지 않음
        assert "update_product_display" not in tool_names
        assert "update_product_page_status" not in tool_names
        assert "update_product_page" not in tool_names
        assert "update_main_product_setting" not in tool_names
        assert "batch_update_product_display" not in tool_names

        # request_action만 존재
        assert "request_action" in tool_names

    def test_cascading_enforced_by_harness(self, harness):
        """이슈: LLM이 check_cascading_effects를 호출 안 해서 마지막 상품 경고 누락.
        해결: Harness가 cascading을 자동 체크."""
        result = json.loads(harness.validate_and_confirm(
            "update_product_display",
            {
                "product_id": "99999", "is_display": False,
                "master_name": "조조형우", "page_title": "월간",
                "product_name": "리포트", "page_id": "p1",
            },
            {"product": {"exists": True, "isDisplay": True}, "page": {"displayedProductCount": 1}},
        ))
        assert "주의" in result["message"]
        assert "마지막 공개 상품" in result["message"]

    def test_idempotency_enforced_by_harness(self, harness):
        """이슈: LLM이 check_idempotency를 안 불러서 이미 같은 상태인데 또 실행.
        해결: Harness prerequisites에서 자동 체크."""
        result = json.loads(harness.validate_and_confirm(
            "update_product_display",
            {"product_id": "99999", "is_display": False},
            {"product": {"exists": True, "isDisplay": False}},
        ))
        assert result["mode"] == "error"
        assert "이미" in result["message"]

    def test_confirmation_enforced(self, harness):
        """이슈: LLM이 유저 확인(interrupt) 없이 바로 API 호출.
        해결: Harness가 항상 confirmation 단계를 거침. 버튼 없이 실행 불가."""
        result = json.loads(harness.validate_and_confirm(
            "update_product_page_status",
            {"page_id": "p1", "status": "INACTIVE", "master_name": "테스트"},
        ))
        # 항상 확인 모드 반환 (바로 실행 안 함)
        assert result["mode"] == "execute"
        # 실행 버튼 있어야 함
        exec_btn = next((b for b in result["buttons"] if b.get("action") == "execute_confirmed"), None)
        assert exec_btn is not None
        # 버튼에 payload 있어야 함 (서버가 이걸로 execute_confirmed 호출)
        assert exec_btn["payload"]["action_id"] == "update_product_page_status"


# ══════════════════════════════════════════════════
# 2026-03-27: 맥락 상실 — 오케스트레이터 재도입
# ══════════════════════════════════════════════════


class TestExecutorPromptSimplification:
    """노트 3/27: executor 프롬프트가 15개 규칙이라 LLM이 무시.
    → 프롬프트 5개로 축소. 검증/확인/실행은 Harness가 담당."""

    def test_executor_prompt_reduced(self):
        """프롬프트 규칙 수 감소 확인."""
        from src.agents.executor import EXECUTOR_PROMPT
        # 이전: E1~E14 (15개 규칙)
        # 이후: 5개 핵심 규칙만
        assert "E1." not in EXECUTOR_PROMPT
        assert "E3." not in EXECUTOR_PROMPT
        assert "E5." not in EXECUTOR_PROMPT
        # request_action 안내는 있어야 함
        assert "request_action" in EXECUTOR_PROMPT

    def test_no_validator_tools_in_executor(self):
        """check_prerequisites, check_idempotency, check_cascading_effects가
        executor tool에서 제거되었는지 확인."""
        from src.agents.executor import create_executor_agent
        agent = create_executor_agent()
        tool_names = agent.tool_names
        assert "check_prerequisites" not in tool_names
        assert "check_idempotency" not in tool_names
        assert "check_cascading_effects" not in tool_names


# ══════════════════════════════════════════════════
# 2026-03-28: 도메인 규칙 R0~R7 실증
# ══════════════════════════════════════════════════


class TestDomainRules:
    """노트 3/28: 에이전트로 실증한 R0~R7 규칙이 DiagnoseEngine에 반영되었는지."""

    def test_visibility_chain_order(self, engine):
        """R: 마스터 PUBLIC → 메인 ACTIVE → 페이지 ACTIVE → 기간 내 → 옵션 공개.
        DiagnoseEngine이 이 순서대로 체크하는지."""
        chain = engine.chains.get("product_visible", {})
        requires = chain.get("requires", [])
        ids = [r["id"] for r in requires]
        assert ids == ["R8", "R0", "R1", "R3", "R5"]

    def test_diagnose_detects_main_inactive(self, engine):
        """노트 3/28 핵심 이슈: 페이지 ACTIVE인데 메인 INACTIVE → 노출 안 됨.
        이전 에이전트: "노출 중"이라고 잘못 답변.
        DiagnoseEngine이 메인 INACTIVE를 first_failure로 보고하는지."""
        result = engine.diagnose("조조형우")
        # Mock에서 조조형우 메인 상품은 INACTIVE
        checks = result.get("checks", [])
        main_check = next((c for c in checks if c.get("condition") == "main_product_active"), None)
        assert main_check is not None
        assert main_check["passed"] is False

    def test_diagnose_returns_resolve_actions(self, engine):
        """노트 3/31: 진단 결과에 resolve 액션이 포함되어야 함.
        → "고쳐줘" 후속 요청 지원."""
        result = engine.diagnose("조조형우")
        # 메인 INACTIVE → resolve에 update_main_product_setting 포함
        resolves = result.get("resolve_actions", [])
        assert resolves is not None
        action_resolve = next((r for r in resolves if r.get("type") == "action"), None)
        assert action_resolve is not None
        assert action_resolve["action_id"] == "update_main_product_setting"


# ══════════════════════════════════════════════════
# 2026-03-28: 세팅 에이전트 이슈 S1~S4
# ══════════════════════════════════════════════════


class TestSettingAgentIssues:
    """노트 3/28: 세팅 에이전트 이슈."""

    def test_s3_web_link_parameter(self):
        """S3: update_main_product_setting에 web_link 파라미터 존재.
        이전: web_link 누락 → isProductGroupWebLinkStatus가 INACTIVE로 하드코딩."""
        from src.tools.admin_api import update_main_product_setting
        import inspect
        sig = inspect.signature(update_main_product_setting._tool_func)
        assert "web_link" in sig.parameters

    def test_s4_hidden_release_cascading(self, harness):
        """S4: 히든 해제 시 기간 충돌 미검증.
        → actions/registry.yaml에 cascading 조건 정의됨."""
        from src.domain_loader import get_action_def
        action = get_action_def("update_product_page_hidden")
        cascading = action.get("cascading", [])
        assert len(cascading) > 0
        assert "히든 해제" in cascading[0].get("message", "")


# ══════════════════════════════════════════════════
# 2026-03-29: Tool 토큰 오버헤드 → task_type 필터링
# ══════════════════════════════════════════════════


class TestToolOptimization:
    """노트 3/29: Tool 23개 → TTFT 느림 → task_type별 필터링."""

    def test_task_type_filtering(self):
        """작업 유형별 Tool 수 감소 확인."""
        from src.agents.executor import create_executor_agent
        full = create_executor_agent()
        diagnose_only = create_executor_agent(task_type="diagnose")
        update_only = create_executor_agent(task_type="update")

        full_count = len(full.tool_names)
        diagnose_count = len(diagnose_only.tool_names)
        update_count = len(update_only.tool_names)

        assert diagnose_count < full_count
        assert update_count < full_count
        # diagnose는 최소 (diagnose_visibility, get_community_settings, navigate)
        assert diagnose_count <= 3

    def test_request_action_in_update_tools(self):
        """update task_type에 request_action이 포함되어야."""
        from src.agents.executor import create_executor_agent
        agent = create_executor_agent(task_type="update")
        tool_names = agent.tool_names
        assert "request_action" in tool_names


# ══════════════════════════════════════════════════
# 2026-03-30: 위저드 vs 채팅 분리
# ══════════════════════════════════════════════════


class TestWizardChatSeparation:
    """노트 3/30: 위저드(빠른 실행)와 채팅(에이전트)이 분리되어야."""

    def test_wizard_does_not_use_harness(self):
        """위저드는 admin_api를 직접 호출. Harness 미경유."""
        from src.wizard import _get_api_map
        api_map = _get_api_map()
        # 위저드의 API 맵은 admin_api 함수를 직접 참조
        assert "update_product_display" in api_map
        assert "update_product_page_status" in api_map

    def test_wizard_diagnose_uses_engine(self):
        """위저드의 진단은 DiagnoseEngine 사용 (validator가 아닌)."""
        from src.wizard import _data_diagnose_visibility, WizardState, WizardSchema
        # _data_diagnose_visibility가 diagnose_engine을 import하는지 확인
        import inspect
        source = inspect.getsource(_data_diagnose_visibility)
        assert "diagnose_engine" in source
        assert "validator" not in source


# ══════════════════════════════════════════════════
# 2026-03-31: 하네스 설계 핵심 — "LLM은 규칙을 모른다"
# ══════════════════════════════════════════════════


class TestHarnessDesignPrinciples:
    """노트 3/31: 핵심 원칙 검증."""

    def test_yaml_not_in_prompt(self):
        """YAML 규칙이 LLM 프롬프트에 포함되지 않음.
        LLM은 request_action 호출만, 규칙은 코드가 실행."""
        from src.agents.executor import EXECUTOR_PROMPT
        assert "visibility_chain" not in EXECUTOR_PROMPT
        assert "prerequisites" not in EXECUTOR_PROMPT
        assert "cascading" not in EXECUTOR_PROMPT
        assert "R0" not in EXECUTOR_PROMPT
        assert "R8" not in EXECUTOR_PROMPT

    def test_single_write_gate(self, harness):
        """request_action이 유일한 쓰기 경로.
        어떤 action_id를 넣든 Harness를 통과해야 실행."""
        # 유효한 action → confirm
        valid = json.loads(harness.validate_and_confirm(
            "update_product_display",
            {"product_id": "99", "is_display": True, "master_name": "테스트"},
        ))
        assert valid["mode"] == "execute"

        # 잘못된 action → error
        invalid = json.loads(harness.validate_and_confirm("hack_database", {}))
        assert invalid["mode"] == "error"

    def test_domain_rules_single_source(self):
        """도메인 규칙이 YAML Single Source of Truth.
        진단과 Harness가 같은 YAML을 참조."""
        from src.domain_loader import load_yaml
        chains = load_yaml("domain/visibility_chain.yaml")
        registry = load_yaml("actions/registry.yaml")

        # registry의 visibility_chain 참조가 chains에 존재
        for action_def in registry.get("actions", {}).values():
            chain_ref = action_def.get("visibility_chain")
            if chain_ref:
                assert chain_ref in chains.get("chains", {}), \
                    f"registry가 참조하는 chain '{chain_ref}'이 visibility_chain.yaml에 없음"

    def test_new_rule_yaml_only(self):
        """새 규칙 추가 = YAML만 수정. Python 코드 변경 불필요.
        visibility_chain.yaml에 체크 항목이 선언적으로 정의되어 있는지."""
        from src.domain_loader import get_chain
        chain = get_chain("product_visible")
        for rule in chain["requires"]:
            assert "id" in rule
            assert "check" in rule
            assert "fail_message" in rule
