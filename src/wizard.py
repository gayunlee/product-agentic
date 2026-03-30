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
    resolve_page_url,
)
from src.agents.validator import check_cascading_effects


# 위저드 액션 정의 — 프론트에 노출할 것만
WIZARD_ACTIONS = {
    "launch_check": {"label": "런칭 체크", "target_type": "master"},
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

    def start_with_master(self, master_id: str) -> tuple[str, list[dict], str]:
        """context에서 masterId가 있을 때 — 클럽 선택 건너뛰기."""
        from src.tools.admin_api import get_master_detail
        try:
            detail = get_master_detail(master_id=master_id)
            master_name = detail.get("name", f"클럽 {master_id}")
        except Exception:
            master_name = f"클럽 {master_id}"

        self.selections["master_cms_id"] = master_id
        self.selections["master_name"] = master_name
        return self._next_after_master()

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
        """마스터 선택 후 — 진단/런칭체크면 바로 실행, 아니면 페이지 선택."""
        if self.action == "diagnose":
            return self._execute_diagnose()
        if self.action == "launch_check":
            return self._execute_launch_check()
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
        """클럽 선택 스텝 — 전체 목록을 버튼으로 표시."""
        action_label = WIZARD_ACTIONS.get(self.action, {}).get("label", self.action)

        try:
            result = search_masters(search_keyword="")
            masters = result.get("masters", []) if isinstance(result, dict) else result if isinstance(result, list) else []
        except Exception:
            masters = []

        if not masters:
            self.reset()
            return "오피셜클럽을 찾을 수 없습니다. 토큰이 만료되었을 수 있습니다.", [], "error"

        # PUBLIC 클럽만 필터 + 이름순 정렬, 최대 20개
        public_masters = [m for m in masters if m.get("publicType") == "PUBLIC"]
        if not public_masters:
            public_masters = masters
        public_masters.sort(key=lambda m: m.get("name", ""))

        name_map = {}
        buttons = []
        for m in public_masters[:20]:
            cms_id = str(m.get("cmsId", ""))
            name = m.get("name", f"클럽 {cms_id}")
            key = f"master_{cms_id}"
            name_map[key] = name
            buttons.append(_btn_select(name, key))
        buttons.append({"type": "action", "label": "처음으로", "action": "cancel", "variant": "ghost"})

        self.selections["_master_names"] = name_map
        self.step = "select_master"

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

        master_cms_id = self.selections.get("master_cms_id", "")
        master_name = self.selections.get("master_name", "")
        self.reset()

        # cmsId로 직접 호출 (이름 재검색 방지)
        result = diagnose_visibility(master_cms_id or master_name)
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

    def _execute_launch_check(self) -> tuple[str, list[dict], str]:
        """런칭 체크 — diagnose_visibility 결과를 런칭 준비 관점으로 렌더링."""
        from src.agents.validator import diagnose_visibility

        master_cms_id = self.selections.get("master_cms_id", "")
        master_name = self.selections.get("master_name", "")
        self.reset()

        # cmsId로 직접 호출 (이름 재검색 방지)
        result = diagnose_visibility(master_cms_id or master_name)
        checks = result.get("checks", [])
        weblink_warnings = result.get("weblink_warnings", [])

        # 런칭 체크 결과 렌더링
        total = len(checks)
        passed = sum(1 for c in checks if c.get("passed", False))
        all_pass = passed == total

        lines = [f"## 🚀 런칭 체크 — {result.get('master_name', master_name)}"]
        lines.append("")
        lines.append(f"**{passed}/{total} 항목 통과**")
        lines.append("")

        # 체크리스트
        for c in checks:
            icon = "✅" if c.get("passed") else "❌"
            label = c.get("label", c.get("condition", ""))
            actual = c.get("actual", "")
            lines.append(f"{icon} **{label}** — {actual}")

        # 공개 중인 상품페이지 + 상품 정보
        page_check = next((c for c in checks if c.get("condition") == "page_active"), None)
        active_pages = page_check.get("pages", []) if page_check else []
        if active_pages:
            lines.append("")
            lines.append("### 공개 중인 상품페이지")
            for p in active_pages:
                hidden_tag = " (히든)" if p.get("is_hidden") else ""
                lines.append(f"- **{p.get('title', '제목 없음')}**{hidden_tag}")
                options = p.get("options", [])
                for opt in options:
                    display = "공개" if opt.get("is_display") else "비공개"
                    price = opt.get("price", 0)
                    price_str = f"{price:,}원" if isinstance(price, (int, float)) and price > 0 else ""
                    lines.append(f"  - {opt.get('name', '')} ({display}) {price_str}".rstrip())

        # 웹링크 경고
        if weblink_warnings:
            lines.append("")
            for w in weblink_warnings:
                lines.append(f"⚠️ {w}")

        # 결론
        lines.append("")
        if all_pass:
            lines.append("**런칭 준비 완료!** 모든 조건이 정상입니다.")
        else:
            first_fail = result.get("first_failure", "")
            lines.append(f"**런칭 불가** — {first_fail}")
            lines.append("위 항목을 해결한 후 다시 체크해주세요.")

        msg = "\n".join(lines)

        # 버튼: 공개 페이지 → 상세, 실패 항목 → 설정 페이지
        # resolve_page_url로 URL 상수 관리
        buttons = []

        # 공개 중인 상품페이지 링크
        for p in active_pages:
            page_id = p.get("page_id", "")
            title = p.get("title", "페이지")
            if page_id:
                url, _ = resolve_page_url("product_page_detail", id=page_id)
                buttons.append(_btn_navigate(f"📄 {title}", url))

        # 실패 항목별 매핑: condition → (page_key, params)
        FAIL_PAGE_MAP = {
            "master_public": ("official_club", {"masterId": master_cms_id}),
            "main_product_active": ("main_product", {}),
            "page_active": ("product_page_list", {}),
            "weblink_set": ("official_club", {"masterId": master_cms_id}),
            "weblink_target_valid": ("official_club", {"masterId": master_cms_id}),
            "weblink_target_stable": ("official_club", {"masterId": master_cms_id}),
        }

        if not all_pass:
            for c in checks:
                if c.get("passed"):
                    continue
                condition = c.get("condition", "")
                mapping = FAIL_PAGE_MAP.get(condition)
                if mapping:
                    page_key, params = mapping
                    url, label = resolve_page_url(page_key, **params)
                    buttons.append(_btn_navigate(label, url))

        # 중복 제거
        seen = set()
        unique_buttons = []
        for b in buttons:
            key = b.get("url", "")
            if key not in seen:
                seen.add(key)
                unique_buttons.append(b)
        buttons = unique_buttons

        return msg, buttons, "launch_check"

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
