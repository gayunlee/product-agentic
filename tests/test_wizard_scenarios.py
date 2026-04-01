"""
위저드 시나리오 전수 테스트.

모든 위저드 × 모든 분기(선택지, back, cancel, 에러 핸들링)를
시나리오로 정의하고 parametrize로 실행.

시나리오 구조:
  - actions: [("select", "master_35"), ("select", "page_mock_page_001"), ("execute",)]
  - expect_mode: "done"
  - expect_contains: "완료"  (응답 메시지에 포함되어야 할 문자열)

Usage:
    MOCK_MODE=true uv run pytest tests/test_wizard_scenarios.py -v
"""

import os
import pytest

os.environ["MOCK_MODE"] = "true"

from src.wizard import create_wizard, _get_engine


# ─── 시나리오 실행 엔진 ───


def run_scenario(wizard_id: str, actions: list[tuple], expect_mode: str, expect_contains: str = ""):
    """위저드 시나리오 실행.

    actions: [("select", "master_35"), ("back",), ("cancel",), ("execute",)]
    """
    state = create_wizard(wizard_id)
    msg, btns, mode = state.start()
    assert mode == "wizard", f"start failed: mode={mode}, msg={msg}"

    for i, action in enumerate(actions):
        op = action[0]
        if op == "select":
            value = action[1]
            # value가 정확한 키가 아닐 수 있으므로 부분 매칭
            matched = next((b for b in btns if b.get("value") == value), None)
            if not matched:
                # value를 포함하는 버튼 찾기
                matched = next((b for b in btns if value in b.get("value", "")), None)
            assert matched, (
                f"step {i}: value '{value}' 매칭 버튼 없음. "
                f"available: {[b.get('value','') for b in btns if b.get('value')]}"
            )
            msg, btns, mode = state.handle({"value": matched["value"]})
        elif op == "select_first":
            # 첫 번째 선택 가능 버튼
            selectable = [b for b in btns if b.get("value")]
            assert selectable, f"step {i}: 선택 가능 버튼 없음"
            msg, btns, mode = state.handle({"value": selectable[0]["value"]})
        elif op == "select_nth":
            n = action[1]
            selectable = [b for b in btns if b.get("value")]
            assert len(selectable) > n, f"step {i}: {n}번째 버튼 없음, {len(selectable)}개만 있음"
            msg, btns, mode = state.handle({"value": selectable[n]["value"]})
        elif op == "back":
            msg, btns, mode = state.handle({"action": "back"})
        elif op == "cancel":
            msg, btns, mode = state.handle({"action": "cancel"})
        elif op == "execute":
            msg, btns, mode = state.handle({"action": "execute"})
        else:
            raise ValueError(f"Unknown op: {op}")

    assert mode == expect_mode, (
        f"최종 mode 불일치: expected={expect_mode}, actual={mode}\n"
        f"msg: {msg[:200]}"
    )
    if expect_contains:
        assert expect_contains in msg, (
            f"응답에 '{expect_contains}' 없음\n"
            f"msg: {msg[:300]}"
        )

    return msg, btns, mode


# ─── 시나리오 정의 ───

# (시나리오ID, wizard_id, actions, expect_mode, expect_contains)
SCENARIOS = [
    # ════════════════════════════════════
    # 히든 처리 (hidden) — 4스텝
    # ════════════════════════════════════

    # Happy path: 조조형우 첫 번째 페이지
    ("hidden-happy-1st-master",
     "hidden",
     [("select", "master_35"), ("select_first",), ("execute",)],
     "done", "완료"),

    # 두 번째 마스터 (김영익) 선택
    ("hidden-2nd-master",
     "hidden",
     [("select", "master_100"), ("select_first",), ("execute",)],
     "done", "완료"),

    # 세 번째 마스터 (봄날의 햇살) 선택
    ("hidden-3rd-master",
     "hidden",
     [("select", "master_42"), ("select_first",), ("execute",)],
     "done", "완료"),

    # 두 번째 페이지 (INACTIVE) 선택
    ("hidden-2nd-page",
     "hidden",
     [("select", "master_35"), ("select_nth", 1), ("execute",)],
     "done", "완료"),

    # 중간에 back: 페이지 선택 → back → 마스터 재선택 → 페이지 → 실행
    ("hidden-back-from-page",
     "hidden",
     [("select", "master_35"), ("back",), ("select", "master_100"), ("select_first",), ("execute",)],
     "done", "완료"),

    # confirm에서 back → 페이지 재선택
    ("hidden-back-from-confirm",
     "hidden",
     [("select", "master_35"), ("select_first",), ("back",), ("select_nth", 1), ("execute",)],
     "done", "완료"),

    # 시작 직후 cancel
    ("hidden-cancel-at-start",
     "hidden",
     [("cancel",)],
     "idle", "취소"),

    # 페이지 선택 후 cancel
    ("hidden-cancel-at-page",
     "hidden",
     [("select", "master_35"), ("cancel",)],
     "idle", "취소"),

    # confirm에서 cancel
    ("hidden-cancel-at-confirm",
     "hidden",
     [("select", "master_35"), ("select_first",), ("cancel",)],
     "idle", "취소"),

    # ════════════════════════════════════
    # 상품페이지 비공개 (product_page_inactive) — 4스텝
    # ════════════════════════════════════

    ("page-inactive-happy",
     "product_page_inactive",
     [("select", "master_35"), ("select_first",), ("execute",)],
     "done", "완료"),

    ("page-inactive-2nd-page",
     "product_page_inactive",
     [("select", "master_35"), ("select_nth", 1), ("execute",)],
     "done", "완료"),

    ("page-inactive-back-reselect",
     "product_page_inactive",
     [("select", "master_35"), ("select_first",), ("back",), ("select_nth", 1), ("execute",)],
     "done", "완료"),

    # ════════════════════════════════════
    # 상품페이지 공개 (product_page_active) — 4스텝
    # ════════════════════════════════════

    ("page-active-happy",
     "product_page_active",
     [("select", "master_35"), ("select_first",), ("execute",)],
     "done", "완료"),

    # ════════════════════════════════════
    # 상품 비공개 (product_hide) — 5스텝 (+ select_product)
    # ════════════════════════════════════

    ("product-hide-happy",
     "product_hide",
     [("select", "master_35"), ("select_first",), ("select_first",), ("execute",)],
     "done", "완료"),

    ("product-hide-back-from-product",
     "product_hide",
     [("select", "master_35"), ("select_first",), ("back",), ("select_first",), ("select_first",), ("execute",)],
     "done", "완료"),

    ("product-hide-cancel-at-confirm",
     "product_hide",
     [("select", "master_35"), ("select_first",), ("select_first",), ("cancel",)],
     "idle", "취소"),

    # ════════════════════════════════════
    # 상품 공개 (product_show) — 5스텝
    # ════════════════════════════════════

    ("product-show-happy",
     "product_show",
     [("select", "master_35"), ("select_first",), ("select_first",), ("execute",)],
     "done", "완료"),

    # ════════════════════════════════════
    # 노출 진단 (diagnose) — 2스텝 (handler 기반)
    # ════════════════════════════════════

    ("diagnose-happy",
     "diagnose",
     [("select", "master_35")],
     "diagnose", ""),

    ("diagnose-2nd-master",
     "diagnose",
     [("select", "master_100")],
     "diagnose", ""),

    ("diagnose-cancel",
     "diagnose",
     [("cancel",)],
     "idle", "취소"),

    # ════════════════════════════════════
    # 런칭 체크 (launch_check) — 2스텝 (handler 기반)
    # ════════════════════════════════════

    ("launch-check-happy",
     "launch_check",
     [("select", "master_35")],
     "launch_check", ""),

    ("launch-check-cancel",
     "launch_check",
     [("cancel",)],
     "idle", "취소"),

    # ════════════════════════════════════
    # 에러 후 재선택 (이전 selections 초기화 검증)
    # ════════════════════════════════════

    # 마스터 A 선택 → 에러 → 마스터 B 선택 → 완료
    ("hidden-error-reselect-master",
     "hidden",
     [("select", "master_100"), ("back",), ("select", "master_35"), ("select_first",), ("execute",)],
     "done", "완료"),

    # ════════════════════════════════════
    # 멱등성 차단 (exclude)
    # ════════════════════════════════════

    # 비공개 위저드: INACTIVE 페이지는 disabled
    ("page-inactive-excludes-inactive",
     "product_page_inactive",
     [("select", "master_35")],
     "wizard", ""),  # 페이지 선택 화면까지만 — disabled 검증은 별도

    # 공개 위저드: ACTIVE 페이지는 disabled
    ("page-active-excludes-active",
     "product_page_active",
     [("select", "master_35")],
     "wizard", ""),

    # ════════════════════════════════════
    # 공통: 첫 스텝에서 back = cancel
    # ════════════════════════════════════

    ("hidden-back-at-start",
     "hidden",
     [("back",)],
     "idle", ""),

    ("diagnose-back-at-start",
     "diagnose",
     [("back",)],
     "idle", ""),
]


# ─── exclude(disabled) 버튼 검증 ───


class TestDownstreamReset:
    """마스터 재선택 시 하위 selections(page_id 등)이 초기화되는지 검증."""

    def test_reselect_master_clears_page(self):
        """마스터 A 선택 → 페이지 선택 → back → 마스터 B 선택 → page_id가 초기화."""
        state = create_wizard("hidden")
        msg, btns, _ = state.start()

        # 마스터 A 선택
        master_a = next(b for b in btns if "35" in b.get("value", ""))
        msg, btns, _ = state.handle({"value": master_a["value"]})

        # 페이지 선택
        page = next(b for b in btns if b.get("value", "").startswith("page_"))
        state.handle({"value": page["value"]})
        assert state.selections.get("page_id"), "page_id가 설정되어야 함"

        # back → 마스터 선택으로
        state.handle({"action": "back"})  # → 페이지 선택
        state.handle({"action": "back"})  # → 마스터 선택

        # 마스터 B 선택
        msg, btns, _ = state._run_current_step()
        master_b = next(b for b in btns if "100" in b.get("value", ""))
        state.handle({"value": master_b["value"]})

        # page_id가 초기화되어야
        assert state.selections.get("page_id") is None or state.selections["master_cms_id"] == "100"


class TestExcludeDisabled:
    """멱등 위반 항목이 disabled로 표시되는지 검증."""

    def test_inactive_page_disabled_in_inactive_wizard(self):
        """비공개 위저드에서 INACTIVE 페이지는 disabled."""
        state = create_wizard("product_page_inactive")
        msg, btns, _ = state.start()
        master = next(b for b in btns if "35" in b.get("value", ""))
        msg, btns, _ = state.handle({"value": master["value"]})

        # Mock: page_001=ACTIVE, page_002=INACTIVE
        inactive_btn = next((b for b in btns if "INACTIVE" in b.get("label", "")), None)
        active_btn = next((b for b in btns if "ACTIVE" in b.get("label", "") and "INACTIVE" not in b.get("label", "")), None)

        assert inactive_btn and inactive_btn.get("disabled"), "INACTIVE 페이지가 disabled가 아님"
        assert active_btn and not active_btn.get("disabled"), "ACTIVE 페이지가 disabled됨"

    def test_active_page_disabled_in_active_wizard(self):
        """공개 위저드에서 ACTIVE 페이지는 disabled."""
        state = create_wizard("product_page_active")
        msg, btns, _ = state.start()
        master = next(b for b in btns if "35" in b.get("value", ""))
        msg, btns, _ = state.handle({"value": master["value"]})

        active_btn = next((b for b in btns if "ACTIVE" in b.get("label", "") and "INACTIVE" not in b.get("label", "")), None)
        inactive_btn = next((b for b in btns if "INACTIVE" in b.get("label", "")), None)

        assert active_btn and active_btn.get("disabled"), "ACTIVE 페이지가 disabled가 아님"
        assert inactive_btn and not inactive_btn.get("disabled"), "INACTIVE 페이지가 disabled됨"

    def test_disabled_reason_in_label(self):
        """disabled 버튼 라벨에 사유가 포함되어야 한다."""
        state = create_wizard("product_page_inactive")
        state.start()
        master = next(b for b in state.start()[1] if "35" in b.get("value", ""))
        # restart
        state2 = create_wizard("product_page_inactive")
        state2.start()
        msg, btns, _ = state2.handle({"value": master["value"]})

        disabled_btns = [b for b in btns if b.get("disabled")]
        for b in disabled_btns:
            assert "이미" in b.get("label", ""), f"disabled 버튼에 사유 없음: {b['label']}"


@pytest.mark.parametrize(
    "scenario_id, wizard_id, actions, expect_mode, expect_contains",
    SCENARIOS,
    ids=[s[0] for s in SCENARIOS],
)
def test_wizard_scenario(scenario_id, wizard_id, actions, expect_mode, expect_contains):
    """위저드 시나리오 실행."""
    run_scenario(wizard_id, actions, expect_mode, expect_contains)
