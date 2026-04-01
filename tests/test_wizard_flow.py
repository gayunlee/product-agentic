"""
위저드 전체 플로우 테스트.

이번 세션에서 발견된 버그 3건을 전부 회귀 테스트로 커버:
1. confirm → execute 스텝 미전환 (execute 버튼 클릭 시 confirm에 머무름)
2. _format에서 JSON 중괄호를 템플릿 변수로 오인 (KeyError: '"isHidden"')
3. navigate 버튼의 url/type 필드가 응답에 포함되는지

추가로 모든 위저드 YAML의 전체 플로우를 검증:
- start → select_master → select_page → confirm → execute → done

Usage:
    MOCK_MODE=true uv run pytest tests/test_wizard_flow.py -v
"""

import os
import json
import pytest
from pathlib import Path

os.environ["MOCK_MODE"] = "true"

from src.wizard import WizardState, WizardSchema, create_wizard, WIZARD_ACTIONS, _get_engine


def _all_wizard_ids() -> list[str]:
    """등록된 모든 위저드 ID."""
    return list(_get_engine().schemas.keys())


# ─── 헬퍼 ───


def _start_wizard(action: str) -> WizardState:
    state = create_wizard(action)
    return state


def _click(state: WizardState, value: str = "", action: str = "") -> tuple[str, list[dict], str]:
    """버튼 클릭 시뮬레이션."""
    btn = {}
    if value:
        btn["value"] = value
    if action:
        btn["action"] = action
    return state.handle(btn)


def _find_button(buttons: list[dict], label_contains: str = "", action: str = "") -> dict | None:
    for b in buttons:
        if label_contains and label_contains in b.get("label", ""):
            return b
        if action and b.get("action") == action:
            return b
    return None


# ─── 위저드 목록 ───


class TestWizardRegistry:
    def test_all_yamls_loaded(self):
        """wizards/ 디렉토리의 모든 YAML이 엔진에 등록되어야 한다."""
        yaml_dir = Path(__file__).parent.parent / "wizards"
        yaml_ids = {f.stem for f in yaml_dir.glob("*.yaml")}
        registered_ids = set(_all_wizard_ids())
        assert yaml_ids == registered_ids, f"미등록: {yaml_ids - registered_ids}, 불필요: {registered_ids - yaml_ids}"

    def test_all_wizards_have_steps(self):
        """모든 위저드가 최소 1개 스텝을 가져야 한다."""
        for wid in _all_wizard_ids():
            state = create_wizard(wid)
            assert len(state.schema.steps) >= 1, f"{wid}에 스텝이 없음"


# ─── _format JSON 중괄호 보호 ───


class TestFormatJsonSafe:
    """BUG: _format에서 '{"isHidden": true}' 같은 JSON을 str.format()이
    템플릿 변수로 해석하여 KeyError 발생."""

    def test_json_braces_preserved(self):
        """JSON 중괄호가 치환되지 않고 보존되어야 한다."""
        state = create_wizard("hidden")
        state.selections["page_id"] = "test_page_001"
        state.selections["master_name"] = "테스트"
        result = state._format('{"isHidden": true}')
        assert result == '{"isHidden": true}'

    def test_template_vars_replaced(self):
        """알려진 변수는 정상 치환되어야 한다."""
        state = create_wizard("hidden")
        state.selections["page_id"] = "page_123"
        state.selections["master_name"] = "조조형우"
        result = state._format("대상: {page_id}, 마스터: {master_name}")
        assert result == "대상: page_123, 마스터: 조조형우"

    def test_mixed_json_and_vars(self):
        """JSON + 변수가 섞여 있어도 변수만 치환, JSON은 보존."""
        state = create_wizard("hidden")
        state.selections["page_id"] = "page_001"
        result = state._format('{page_id} → {"isHidden": true}')
        assert result == 'page_001 → {"isHidden": true}'

    def test_unknown_vars_preserved(self):
        """알 수 없는 {변수}도 그대로 보존."""
        state = create_wizard("hidden")
        result = state._format("{unknown_var} 테스트")
        assert result == "{unknown_var} 테스트"


# ─── confirm → execute 전환 ───


class TestConfirmToExecuteTransition:
    """BUG: confirm 스텝에서 '실행' 버튼 클릭 시 execute 스텝으로 이동하지 않고
    confirm의 step_def(api 없음)로 _execute가 실행되어 '실행할 작업이 정의되지 않았습니다' 에러."""

    def test_hidden_full_flow(self):
        """히든 위저드: start → 마스터 → 페이지 → confirm → execute → done."""
        state = create_wizard("hidden")
        msg, buttons, mode = state.start()
        assert mode == "wizard"
        assert any("조조형우" in b.get("label", "") for b in buttons)

        # 마스터 선택
        master_btn = _find_button(buttons, label_contains="조조형우")
        msg, buttons, mode = _click(state, value=master_btn["value"])
        assert mode == "wizard"  # 페이지 선택 단계

        # 페이지 선택
        page_btn = next(b for b in buttons if b.get("value", "").startswith("page_"))
        msg, buttons, mode = _click(state, value=page_btn["value"])
        assert mode == "wizard"  # confirm 단계
        assert "진행하시겠어요" in msg

        # confirm 스텝에서 현재 인덱스 확인
        confirm_idx = state.current_step_index
        assert state._current_step_def().type == "confirm"

        # 실행 버튼 클릭
        msg, buttons, mode = _click(state, action="execute")
        assert mode == "done", f"execute 후 mode가 done이 아님: {mode}, msg: {msg}"
        assert "완료" in msg

    def test_product_page_inactive_full_flow(self):
        """상품페이지 비공개 위저드: 전체 플로우 → done."""
        state = create_wizard("product_page_inactive")
        msg, buttons, mode = state.start()

        # 마스터 선택
        master_btn = _find_button(buttons, label_contains="조조형우")
        msg, buttons, mode = _click(state, value=master_btn["value"])

        # 페이지 선택
        page_btn = next(b for b in buttons if b.get("value", "").startswith("page_"))
        msg, buttons, mode = _click(state, value=page_btn["value"])
        assert "진행하시겠어요" in msg

        # 실행
        msg, buttons, mode = _click(state, action="execute")
        assert mode == "done"
        assert "완료" in msg

    def test_product_page_active_full_flow(self):
        """상품페이지 공개 위저드: 전체 플로우 → done."""
        state = create_wizard("product_page_active")
        msg, buttons, mode = state.start()

        master_btn = _find_button(buttons, label_contains="조조형우")
        msg, buttons, mode = _click(state, value=master_btn["value"])

        page_btn = next(b for b in buttons if b.get("value", "").startswith("page_"))
        msg, buttons, mode = _click(state, value=page_btn["value"])

        msg, buttons, mode = _click(state, action="execute")
        assert mode == "done"


# ─── navigate 버튼 응답 검증 ───


class TestNavigateButtons:
    """BUG: navigate 버튼이 type='navigate'와 url을 포함해야 프론트에서 페이지 이동 가능."""

    def test_hidden_done_has_navigate_button(self):
        """히든 완료 후 '결과 확인' 버튼이 type=navigate + url을 가져야 한다."""
        state = create_wizard("hidden")
        state.start()

        master_btn = _find_button(state.start()[1], label_contains="조조형우")
        # 다시 시작
        state2 = create_wizard("hidden")
        msg, buttons, _ = state2.start()
        master_btn = _find_button(buttons, label_contains="조조형우")
        _click(state2, value=master_btn["value"])
        msg, buttons, _ = state2.handle({"value": buttons[0]["value"]} if buttons else {})

        # 여기서 새로 시작해서 깔끔하게 진행
        state3 = create_wizard("hidden")
        msg, btns, _ = state3.start()
        master = _find_button(btns, label_contains="조조형우")
        msg, btns, _ = _click(state3, value=master["value"])
        page = next(b for b in btns if b.get("value", "").startswith("page_"))
        msg, btns, _ = _click(state3, value=page["value"])
        msg, btns, mode = _click(state3, action="execute")

        assert mode == "done"
        nav_btn = _find_button(btns, label_contains="결과 확인")
        assert nav_btn is not None, f"결과 확인 버튼이 없음. buttons: {btns}"
        assert nav_btn.get("type") == "navigate", f"type이 navigate가 아님: {nav_btn}"
        assert nav_btn.get("url"), f"url이 없음: {nav_btn}"

    def test_navigate_url_has_page_id(self):
        """navigate URL에 page_id가 치환되어 있어야 한다."""
        state = create_wizard("product_page_inactive")
        msg, btns, _ = state.start()
        master = _find_button(btns, label_contains="조조형우")
        msg, btns, _ = _click(state, value=master["value"])
        page = next(b for b in btns if b.get("value", "").startswith("page_"))
        page_id = page["value"].replace("page_", "")
        msg, btns, _ = _click(state, value=page["value"])
        msg, btns, mode = _click(state, action="execute")

        nav_btn = _find_button(btns, label_contains="결과 확인")
        assert nav_btn is not None
        assert page_id in nav_btn.get("url", ""), f"URL에 page_id({page_id})가 없음: {nav_btn['url']}"


# ─── 위저드 버튼 동작 ───


class TestWizardButtons:
    def test_cancel_resets(self):
        """취소 버튼은 위저드를 리셋해야 한다."""
        state = create_wizard("hidden")
        state.start()
        msg, buttons, mode = _click(state, action="cancel")
        assert mode == "idle"
        assert not state.is_active()

    def test_back_goes_previous(self):
        """이전 버튼은 이전 스텝으로 돌아가야 한다."""
        state = create_wizard("hidden")
        msg, btns, _ = state.start()  # step 0: select_master
        master = _find_button(btns, label_contains="조조형우")
        msg, btns, _ = _click(state, value=master["value"])  # step 1: select_page
        assert state.current_step_index == 1

        msg, btns, _ = _click(state, action="back")  # back to step 0
        assert state.current_step_index == 0

    def test_back_from_first_step_cancels(self):
        """첫 스텝에서 이전 버튼은 취소와 동일."""
        state = create_wizard("hidden")
        state.start()
        msg, buttons, mode = _click(state, action="back")
        assert mode == "idle"


# ─── 모든 위저드 YAML 실행 스텝 검증 ───


class TestAllWizardsExecuteStep:
    """모든 위저드의 execute 스텝이 api 또는 handler를 가져야 한다."""

    def test_execute_steps_have_api_or_handler(self):
        """execute 타입 스텝은 api 또는 handler가 정의되어야 실행 가능."""
        for wid in _all_wizard_ids():
            state = create_wizard(wid)
            for step in state.schema.steps:
                if step.type == "execute":
                    has_api = bool(step.api)
                    has_handler = bool(step.handler)
                    assert has_api or has_handler, (
                        f"위저드 '{wid}'의 execute 스텝 '{step.id}'에 "
                        f"api도 handler도 없음 → '실행할 작업이 정의되지 않았습니다' 에러 발생"
                    )

    def test_api_names_are_valid(self):
        """execute 스텝의 api가 api_map에 등록되어 있어야 한다."""
        from src.wizard import _get_api_map
        api_map = _get_api_map()

        for wid in _all_wizard_ids():
            state = create_wizard(wid)
            for step in state.schema.steps:
                if step.type == "execute" and step.api:
                    assert step.api in api_map, (
                        f"위저드 '{wid}'의 api '{step.api}'가 "
                        f"api_map에 없음. 가능한 값: {list(api_map.keys())}"
                    )


# ─── 진단 위저드 (handler 기반) ───


class TestDiagnoseWizardFlow:
    def test_diagnose_full_flow(self):
        """진단 위저드: start → 마스터 선택 → 진단 결과."""
        state = create_wizard("diagnose")
        msg, btns, mode = state.start()
        assert mode == "wizard"

        master = _find_button(btns, label_contains="조조형우")
        msg, btns, mode = _click(state, value=master["value"])
        assert mode == "diagnose", f"진단 결과 mode가 아님: {mode}"
        assert "진단" in msg or "✅" in msg or "❌" in msg

    def test_launch_check_full_flow(self):
        """런칭 체크 위저드: start → 마스터 선택 → 리포트."""
        state = create_wizard("launch_check")
        msg, btns, mode = state.start()
        assert mode == "wizard"

        master = _find_button(btns, label_contains="조조형우")
        msg, btns, mode = _click(state, value=master["value"])
        assert mode == "launch_check", f"런칭 체크 mode가 아님: {mode}"
        assert "런칭" in msg or "✅" in msg or "❌" in msg


# ─── 상품 비공개/공개 (select_product 포함 5스텝) ───


class TestProductWizardFlow:
    """product_hide, product_show는 select_product 스텝이 추가된 5스텝 위저드."""

    def _run_product_wizard(self, wizard_id: str) -> tuple[str, list[dict], str]:
        """상품 위저드 전체 플로우 실행."""
        state = create_wizard(wizard_id)
        msg, btns, mode = state.start()
        assert mode == "wizard", f"{wizard_id} start mode가 wizard가 아님: {mode}"

        # 1. 마스터 선택
        master = _find_button(btns, label_contains="조조형우")
        assert master, f"{wizard_id}: 조조형우 버튼 없음. buttons: {btns}"
        msg, btns, mode = _click(state, value=master["value"])
        assert mode == "wizard", f"{wizard_id} 마스터 선택 후 mode: {mode}, msg: {msg}"

        # 2. 페이지 선택
        page = next((b for b in btns if b.get("value", "").startswith("page_")), None)
        assert page, f"{wizard_id}: page 버튼 없음. buttons: {btns}"
        msg, btns, mode = _click(state, value=page["value"])
        assert mode == "wizard", f"{wizard_id} 페이지 선택 후 mode: {mode}, msg: {msg}"

        # 3. 상품 선택
        product = next((b for b in btns if b.get("value", "").startswith("product_")), None)
        assert product, f"{wizard_id}: product 버튼 없음. buttons: {btns}"
        msg, btns, mode = _click(state, value=product["value"])
        assert mode == "wizard", f"{wizard_id} 상품 선택 후 mode: {mode}, msg: {msg}"
        assert "진행하시겠어요" in msg, f"{wizard_id}: confirm 메시지가 아님: {msg}"

        # 4. 실행
        msg, btns, mode = _click(state, action="execute")
        return msg, btns, mode

    def test_product_hide_full_flow(self):
        """상품 비공개 위저드: 마스터→페이지→상품→확인→실행→done."""
        msg, btns, mode = self._run_product_wizard("product_hide")
        assert mode == "done", f"product_hide 실행 후 mode: {mode}, msg: {msg}"
        assert "완료" in msg

    def test_product_show_full_flow(self):
        """상품 공개 위저드: 마스터→페이지→상품→확인→실행→done."""
        msg, btns, mode = self._run_product_wizard("product_show")
        assert mode == "done", f"product_show 실행 후 mode: {mode}, msg: {msg}"
        assert "완료" in msg

    def test_product_hide_navigate_button(self):
        """상품 비공개 완료 후 navigate 버튼이 있어야 한다."""
        msg, btns, mode = self._run_product_wizard("product_hide")
        nav = _find_button(btns, label_contains="결과 확인")
        assert nav, f"결과 확인 버튼 없음. buttons: {btns}"
        assert nav.get("type") == "navigate"
        assert nav.get("url")


# ─── 모든 위저드 전체 플로우 자동 실행 ───


class TestEveryWizardEndToEnd:
    """모든 위저드를 start부터 done/diagnose/launch_check까지 자동으로 돌린다.
    새 위저드 YAML을 추가하면 자동으로 이 테스트에 포함된다."""

    @pytest.mark.parametrize("wizard_id", _all_wizard_ids())
    def test_wizard_completes(self, wizard_id):
        """위저드를 끝까지 돌려서 error가 아닌 최종 상태에 도달해야 한다."""
        state = create_wizard(wizard_id)
        msg, btns, mode = state.start()
        assert mode == "wizard", f"{wizard_id} start failed: mode={mode}"

        max_steps = 10
        for i in range(max_steps):
            if mode != "wizard":
                break

            # 값이 있는 버튼(선택지) 우선 클릭
            selectable = [b for b in btns if b.get("value")]
            if selectable:
                msg, btns, mode = _click(state, value=selectable[0]["value"])
                continue

            # 실행 버튼
            exec_btn = _find_button(btns, action="execute")
            if exec_btn:
                msg, btns, mode = _click(state, action="execute")
                continue

            # 더 이상 진행 불가
            break

        # 최종 상태 검증: error가 아니어야
        assert mode != "error", (
            f"위저드 '{wizard_id}'가 error로 끝남: {msg}"
        )
        assert mode in ("done", "diagnose", "launch_check", "idle"), (
            f"위저드 '{wizard_id}'가 예상 외 mode로 끝남: {mode}, msg: {msg[:200]}"
        )
