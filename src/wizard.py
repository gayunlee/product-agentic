"""
빠른 실행 위저드 — 버튼 기반 상품 상태 변경. LLM 0회.

패턴:
  [시작] → [클럽 선택] → [대상 선택] → [확인/경고] → [실행] → [완료]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.agents.response import (
    AgentResponse,
    render_response,
    _btn_select,
    _btn_action,
    _btn_navigate,
)
from src.tools.admin_api import (
    search_masters,
    get_product_page_list,
    get_product_list_by_page,
    update_product_display,
    update_product_page_status,
    update_product_page,
)
from src.agents.validator import check_cascading_effects


# 위저드 액션 정의
WIZARD_ACTIONS = {
    "diagnose": {"label": "노출 진단", "target_type": "master"},
    "product_page_inactive": {"label": "상품페이지 비공개", "target_type": "product_page"},
    "product_page_active": {"label": "상품페이지 공개", "target_type": "product_page"},
    "product_hide": {"label": "상품 비공개", "target_type": "product_option"},
    "product_show": {"label": "상품 공개", "target_type": "product_option"},
    "hidden": {"label": "히든 처리", "target_type": "product_page"},
}


@dataclass
class WizardState:
    """위저드 상태. 세션당 1개."""

    action: str  # WIZARD_ACTIONS 키
    step: str = "select_master"  # 현재 스텝
    selections: dict[str, Any] = field(default_factory=dict)
    _active: bool = True

    def is_active(self) -> bool:
        return self._active

    def reset(self):
        self._active = False

    def handle(self, button_data: dict) -> tuple[str, list[dict], str]:
        """버튼 입력 처리 → (message, buttons, mode) 반환."""
        action = button_data.get("action", "")
        if action == "cancel":
            self.reset()
            return "취소했습니다. 다른 작업이 필요하시면 말씀해주세요.", [], "idle"
        if action == "back":
            return self._prev_step()

        # select 버튼
        value = button_data.get("value", "")
        if value:
            return self._handle_select(value)

        # execute 버튼
        if action == "execute":
            return self._execute()

        return "알 수 없는 입력입니다.", [], "error"

    def start(self) -> tuple[str, list[dict], str]:
        """위저드 시작 — 클럽 선택 스텝."""
        self.step = "select_master"
        return self._step_select_master()

    def _handle_select(self, value: str) -> tuple[str, list[dict], str]:
        if self.step == "select_master":
            self.selections["master_cms_id"] = value.replace("master_", "")
            self.selections["master_name"] = self.selections.get("_master_names", {}).get(value, value)
            return self._next_after_master()

        if self.step == "select_page":
            self.selections["page_id"] = value.replace("page_", "")
            self.selections["page_title"] = self.selections.get("_page_names", {}).get(value, value)
            return self._next_after_page()

        if self.step == "select_product":
            self.selections["product_id"] = value.replace("product_", "")
            self.selections["product_name"] = self.selections.get("_product_names", {}).get(value, value)
            return self._step_confirm()

        return "알 수 없는 스텝입니다.", [], "error"

    def _next_after_master(self) -> tuple[str, list[dict], str]:
        """마스터 선택 후 — 진단이면 바로 실행, 아니면 페이지 선택."""
        action_info = WIZARD_ACTIONS.get(self.action, {})
        if self.action == "diagnose":
            return self._execute_diagnose()
        self.step = "select_page"
        return self._step_select_page()

    def _next_after_page(self) -> tuple[str, list[dict], str]:
        """페이지 선택 후 — 상품 옵션이면 옵션 선택, 아니면 확인."""
        action_info = WIZARD_ACTIONS.get(self.action, {})
        if action_info.get("target_type") == "product_option":
            self.step = "select_product"
            return self._step_select_product()
        return self._step_confirm()

    # ── 각 스텝 구현 ──

    def _step_select_master(self) -> tuple[str, list[dict], str]:
        """클럽 선택 스텝."""
        try:
            result = search_masters(search_keyword="")
            masters = result.get("masters", [])
        except Exception:
            masters = []

        if not masters:
            self.reset()
            return "오피셜클럽을 찾을 수 없습니다.", [], "error"

        name_map = {}
        buttons = []
        for m in masters[:10]:
            cms_id = str(m.get("cmsId", ""))
            name = m.get("name", f"클럽 {cms_id}")
            key = f"master_{cms_id}"
            name_map[key] = name
            buttons.append(_btn_select(name, key))
        buttons.append({"type": "action", "label": "취소", "action": "cancel", "variant": "ghost"})

        self.selections["_master_names"] = name_map

        action_label = WIZARD_ACTIONS.get(self.action, {}).get("label", self.action)
        return f"**{action_label}** — 오피셜클럽을 선택하세요.", buttons, "wizard"

    def _step_select_page(self) -> tuple[str, list[dict], str]:
        """페이지 선택 스텝."""
        cms_id = self.selections["master_cms_id"]
        master_name = self.selections.get("master_name", "")

        try:
            pages = get_product_page_list(master_id=cms_id)
            page_list = pages if isinstance(pages, list) else pages.get("pages", [])
        except Exception:
            page_list = []

        if not page_list:
            self.reset()
            return f"{master_name} 오피셜클럽에 상품페이지가 없습니다.", [], "error"

        name_map = {}
        buttons = []
        for p in page_list:
            page_id = str(p.get("id", p.get("code", "")))
            title = p.get("title", f"페이지 {page_id}")
            status = p.get("status", "")
            label = f"{title} ({status})" if status else title
            key = f"page_{page_id}"
            name_map[key] = title
            buttons.append(_btn_select(label, key))
        buttons.append({"type": "action", "label": "← 이전", "action": "back", "variant": "ghost"})
        buttons.append({"type": "action", "label": "취소", "action": "cancel", "variant": "ghost"})

        self.selections["_page_names"] = name_map

        action_label = WIZARD_ACTIONS.get(self.action, {}).get("label", self.action)
        return f"**{action_label}** — {master_name}의 상품페이지를 선택하세요.", buttons, "wizard"

    def _step_select_product(self) -> tuple[str, list[dict], str]:
        """상품 옵션 선택 스텝."""
        page_id = self.selections["page_id"]
        page_title = self.selections.get("page_title", "")

        try:
            products = get_product_list_by_page(page_id=page_id)
            product_list = products if isinstance(products, list) else products.get("products", [])
        except Exception:
            product_list = []

        if not product_list:
            self.reset()
            return f"{page_title}에 상품 옵션이 없습니다.", [], "error"

        name_map = {}
        buttons = []
        for p in product_list:
            prod_id = str(p.get("id", ""))
            name = p.get("name", p.get("title", f"상품 {prod_id}"))
            display = p.get("displayStatus", p.get("status", ""))
            price = p.get("price", "")
            label = f"{name} ({display})" if display else name
            if price:
                label += f" — {price:,}원" if isinstance(price, (int, float)) else f" — {price}"
            key = f"product_{prod_id}"
            name_map[key] = name
            buttons.append(_btn_select(label, key))
        buttons.append({"type": "action", "label": "← 이전", "action": "back", "variant": "ghost"})
        buttons.append({"type": "action", "label": "취소", "action": "cancel", "variant": "ghost"})

        self.selections["_product_names"] = name_map

        action_label = WIZARD_ACTIONS.get(self.action, {}).get("label", self.action)
        return f"**{action_label}** — {page_title}의 상품을 선택하세요.", buttons, "wizard"

    def _step_confirm(self) -> tuple[str, list[dict], str]:
        """확인 스텝 — cascading 체크 포함."""
        self.step = "confirm"
        action_label = WIZARD_ACTIONS.get(self.action, {}).get("label", self.action)
        target = self._build_target_description()

        # cascading 체크
        warning = ""
        try:
            cascade = check_cascading_effects(
                action=self.action,
                context=self.selections,
            )
            if cascade and cascade.get("warning"):
                warning = f"\n\n⚠️ {cascade['warning']}"
        except Exception:
            pass

        msg = f"**{action_label}**\n\n**대상**: {target}{warning}\n\n진행하시겠어요?"
        buttons = [
            {"type": "action", "label": f"{action_label} 실행", "action": "execute", "variant": "primary"},
            {"type": "action", "label": "← 이전", "action": "back", "variant": "ghost"},
            {"type": "action", "label": "취소", "action": "cancel", "variant": "ghost"},
        ]
        return msg, buttons, "wizard"

    def _execute(self) -> tuple[str, list[dict], str]:
        """최종 실행."""
        self.step = "done"
        action_label = WIZARD_ACTIONS.get(self.action, {}).get("label", self.action)
        target = self._build_target_description()

        try:
            result = self._call_api()
            self.reset()
            msg = f"✅ **{action_label} 완료**\n\n{target}"
            buttons = [
                _btn_navigate("결과 확인", "/product/page/list"),
            ]
            return msg, buttons, "done"
        except Exception as e:
            self.reset()
            return f"⚠️ 실행 중 오류가 발생했습니다: {e}", [], "error"

    def _execute_diagnose(self) -> tuple[str, list[dict], str]:
        """진단 실행."""
        from src.agents.validator import diagnose_visibility
        from src.agents.response import AgentResponse, render_response

        master_name = self.selections.get("master_name", "")
        self.reset()

        result = diagnose_visibility(master_name)
        data = {
            "checks": [
                {"name": c.get("label", ""), "ok": c.get("passed", False), "value": c.get("actual", "")}
                for c in result.get("checks", [])
            ],
            "first_failure": result.get("first_failure"),
            "fix_label": "해결하기" if result.get("first_failure") else None,
            "nav_url": "/product/page/list",
        }
        resp_type = "diagnose" if not result.get("visible") else "info"
        resp = AgentResponse(
            type=resp_type,
            summary=f"{result.get('master_name', master_name)} 노출 진단 완료. "
                    + (f"원인: {result['first_failure']}" if result.get("first_failure") else "모든 조건 정상."),
            data=data,
        )
        return render_response(resp)

    def _call_api(self) -> dict:
        """액션에 따라 적절한 API 호출."""
        if self.action == "product_page_inactive":
            return update_product_page_status(
                product_page_id=self.selections["page_id"],
                status="INACTIVE",
            )
        elif self.action == "product_page_active":
            return update_product_page_status(
                product_page_id=self.selections["page_id"],
                status="ACTIVE",
            )
        elif self.action == "product_hide":
            return update_product_display(
                product_id=self.selections["product_id"],
                is_display=False,
            )
        elif self.action == "product_show":
            return update_product_display(
                product_id=self.selections["product_id"],
                is_display=True,
            )
        elif self.action == "hidden":
            return update_product_page(
                product_page_id=self.selections["page_id"],
                updates={"isHidden": True},
            )
        else:
            raise ValueError(f"알 수 없는 액션: {self.action}")

    def _prev_step(self) -> tuple[str, list[dict], str]:
        """이전 스텝으로."""
        if self.step == "confirm":
            action_info = WIZARD_ACTIONS.get(self.action, {})
            if action_info.get("target_type") == "product_option":
                self.step = "select_product"
                return self._step_select_product()
            self.step = "select_page"
            return self._step_select_page()
        if self.step == "select_product":
            self.step = "select_page"
            return self._step_select_page()
        if self.step == "select_page":
            self.step = "select_master"
            return self._step_select_master()
        # select_master에서 이전 → 취소
        self.reset()
        return "취소했습니다.", [], "idle"

    def _build_target_description(self) -> str:
        """현재 선택 상태를 텍스트로."""
        parts = []
        if self.selections.get("master_name"):
            parts.append(self.selections["master_name"])
        if self.selections.get("page_title"):
            parts.append(self.selections["page_title"])
        if self.selections.get("product_name"):
            parts.append(self.selections["product_name"])
        return " > ".join(parts) if parts else "선택 없음"


def create_wizard(action: str) -> WizardState:
    """위저드 생성."""
    if action not in WIZARD_ACTIONS:
        raise ValueError(f"알 수 없는 위저드 액션: {action}. 가능: {list(WIZARD_ACTIONS.keys())}")
    return WizardState(action=action)
