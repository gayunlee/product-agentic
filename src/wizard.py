"""
선언적 위저드 엔진 — YAML 스키마 기반, LLM 0회.

wizards/*.yaml 파일을 로드하여 위저드를 자동 등록.
새 위저드 추가 = YAML 파일 하나 작성. 코드 변경 0.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from src.agents.response import _btn_select, _btn_navigate
from src.tools.admin_api import (
    search_masters,
    get_product_page_list,
    get_product_list_by_page,
    resolve_page_url,
)
from src.agents.validator import check_cascading_effects


def _resolve_btn_url(btn: dict, state: "WizardState") -> dict:
    """버튼의 page_key → 실제 URL로 resolve. url 직접 지정도 지원(하위 호환)."""
    if "page_key" in btn:
        page_key = btn.pop("page_key")
        btn_params = btn.pop("params", {})
        # params 값의 템플릿 치환
        resolved_params = {k: state._format(str(v)) for k, v in btn_params.items()}
        url, _ = resolve_page_url(page_key, **resolved_params)
        btn["url"] = url
    elif "url" in btn:
        btn["url"] = state._format(btn["url"])
    return btn


# ─── YAML 스키마 ───


@dataclass
class RenderConfig:
    """execute 스텝의 렌더링 설정. YAML render: 블록에서 로드."""
    type: str = "result"         # checklist, launch_report, result
    title: str = ""
    summary_pass: str = ""
    summary_fail: str = ""
    show_pages: bool = False
    show_products: bool = False
    fail_links: dict[str, dict] = field(default_factory=dict)  # condition → {label, url}
    default_button: dict | None = None


@dataclass
class StepDefinition:
    id: str
    type: str           # select_master, select_page, select_product, confirm, execute
    label: str
    message: str = ""
    cascading: bool = False
    # select 스텝 전용: 이미 목표 상태인 항목 disable
    exclude: dict | None = None  # {"field": "status", "value": "INACTIVE", "reason": "이미 비공개"}
    # execute 스텝 전용
    handler: str | None = None
    api: str | None = None
    params: dict[str, str] = field(default_factory=dict)
    done_message: str = ""
    done_buttons: list[dict] = field(default_factory=list)
    render: RenderConfig | None = None


@dataclass
class WizardSchema:
    id: str
    label: str
    description: str = ""
    icon: str = ""
    steps: list[StepDefinition] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> WizardSchema:
        steps = []
        for s in data.get("steps", []):
            render_data = s.get("render")
            render_config = None
            if render_data:
                render_config = RenderConfig(
                    type=render_data.get("type", "result"),
                    title=render_data.get("title", ""),
                    summary_pass=render_data.get("summary_pass", ""),
                    summary_fail=render_data.get("summary_fail", ""),
                    show_pages=render_data.get("show_pages", False),
                    show_products=render_data.get("show_products", False),
                    fail_links=render_data.get("fail_links", {}),
                    default_button=render_data.get("default_button"),
                )
            steps.append(StepDefinition(
                id=s["id"],
                type=s["type"],
                label=s["label"],
                message=s.get("message", ""),
                cascading=s.get("cascading", False),
                exclude=s.get("exclude"),
                handler=s.get("handler"),
                api=s.get("api"),
                params=s.get("params", {}),
                done_message=s.get("done_message", ""),
                done_buttons=s.get("done_buttons", []),
                render=render_config,
            ))
        return cls(
            id=data["id"],
            label=data["label"],
            description=data.get("description", ""),
            icon=data.get("icon", ""),
            steps=steps,
        )


# ─── API 매핑 ───

def _get_api_map():
    """지연 import로 순환 참조 방지."""
    from src.tools.admin_api import (
        update_product_display,
        update_product_page_status,
        update_product_page,
        update_main_product_setting,
    )
    return {
        "update_product_display": update_product_display,
        "update_product_page_status": update_product_page_status,
        "update_product_page": update_product_page,
        "update_main_product_setting": update_main_product_setting,
    }


# ─── 커스텀 핸들러 ───


# ─── 데이터 핸들러 (데이터만 반환, 렌더링 안 함) ───


def _data_diagnose_visibility(state: WizardState) -> dict:
    """DiagnoseEngine으로 진단 → 원본 데이터 반환."""
    from src.diagnose_engine import get_engine

    master_cms_id = state.selections.get("master_cms_id", "")
    master_name = state.selections.get("master_name", "")
    engine = get_engine()
    result = engine.diagnose(master_cms_id or master_name)
    return result


DATA_HANDLERS: dict[str, Any] = {
    "diagnose_visibility": _data_diagnose_visibility,
}


# ─── 렌더러 (데이터 + RenderConfig → message + buttons) ───


def _render_checklist(data: dict, config: RenderConfig, selections: dict) -> tuple[str, list[dict], str]:
    """체크리스트 렌더링."""
    checks = data.get("checks", [])
    first_failure = data.get("first_failure")
    master_name = data.get("master_name", selections.get("master_name", ""))

    fmt = {**selections, "master_name": master_name, "first_failure": first_failure or ""}

    lines = [config.title.format(**fmt) if config.title else "📊 진단 결과"]
    lines.append("")

    # 요약
    if first_failure:
        lines.append(config.summary_fail.format(**fmt) if config.summary_fail else f"원인: {first_failure}")
    else:
        lines.append(config.summary_pass.format(**fmt) if config.summary_pass else "모든 조건 정상.")

    lines.append("")
    lines.append("| 항목 | 상태 |")
    lines.append("|------|------|")
    first_fail_check = next((c for c in checks if not c.get("passed", False)), None)
    for c in checks:
        icon = "✅" if c.get("passed") else "❌"
        label = c.get("label", c.get("condition", ""))
        actual = c.get("actual", "")
        suffix = " ← 원인" if c is first_fail_check else ""
        lines.append(f"| {label} | {icon} {actual}{suffix} |")

    msg = "\n".join(lines)

    # 버튼: 실패 항목별 링크
    buttons = _build_fail_buttons(checks, config, selections)

    return msg, buttons, "diagnose"


def _render_launch_report(data: dict, config: RenderConfig, selections: dict) -> tuple[str, list[dict], str]:
    """런칭 체크 리포트 렌더링."""
    checks = data.get("checks", [])
    weblink_warnings = data.get("weblink_warnings", [])
    first_failure = data.get("first_failure")
    master_name = data.get("master_name", selections.get("master_name", ""))

    fmt = {**selections, "master_name": master_name, "first_failure": first_failure or ""}

    total = len(checks)
    passed = sum(1 for c in checks if c.get("passed", False))
    all_pass = passed == total

    lines = [config.title.format(**fmt) if config.title else f"## 런칭 체크 — {master_name}"]
    lines.append("")
    lines.append(f"**{passed}/{total} 항목 통과**")
    lines.append("")

    for c in checks:
        icon = "✅" if c.get("passed") else "❌"
        label = c.get("label", c.get("condition", ""))
        actual = c.get("actual", "")
        lines.append(f"{icon} **{label}** — {actual}")

    # 상품페이지 + 상품 정보
    if config.show_pages:
        page_check = next((c for c in checks if c.get("condition") == "page_active"), None)
        active_pages = page_check.get("pages", []) if page_check else []
        if active_pages:
            lines.append("")
            lines.append("### 공개 중인 상품페이지")
            for p in active_pages:
                hidden_tag = " (히든)" if p.get("is_hidden") else ""
                lines.append(f"- **{p.get('title', '제목 없음')}**{hidden_tag}")
                if config.show_products:
                    for opt in p.get("options", []):
                        display = "공개" if opt.get("is_display") else "비공개"
                        price = opt.get("price", 0)
                        price_str = f"{price:,}원" if isinstance(price, (int, float)) and price > 0 else ""
                        lines.append(f"  - {opt.get('name', '')} ({display}) {price_str}".rstrip())

    if weblink_warnings:
        lines.append("")
        for w in weblink_warnings:
            lines.append(f"⚠️ {w}")

    lines.append("")
    if all_pass:
        lines.append(config.summary_pass.format(**fmt) if config.summary_pass else "모든 조건 정상입니다.")
    else:
        lines.append(config.summary_fail.format(**fmt) if config.summary_fail else f"원인: {first_failure}")

    msg = "\n".join(lines)

    # 버튼: 공개 페이지 링크 + 실패 항목별 링크
    buttons = []
    if config.show_pages:
        page_check = next((c for c in checks if c.get("condition") == "page_active"), None)
        active_pages = page_check.get("pages", []) if page_check else []
        for p in active_pages:
            page_id = p.get("page_id", "")
            title = p.get("title", "페이지")
            if page_id:
                url, _ = resolve_page_url("product_page_detail", id=page_id)
                buttons.append(_btn_navigate(f"📄 {title}", url))

    buttons.extend(_build_fail_buttons(checks, config, selections))

    return msg, buttons, "launch_check"


def _resolve_link(link: dict, fmt: dict) -> str:
    """fail_link/default_button의 URL resolve. page_key 또는 url 지원."""
    if "page_key" in link:
        params = {k: v.format(**fmt) for k, v in link.get("params", {}).items()}
        url, _ = resolve_page_url(link["page_key"], **params)
        return url
    return link.get("url", "").format(**fmt)


def _build_fail_buttons(checks: list, config: RenderConfig, selections: dict) -> list[dict]:
    """실패 항목에 대한 navigate 버튼 생성 (YAML fail_links 기반)."""
    fmt = {**selections}
    buttons = []
    has_failure = any(not c.get("passed", False) for c in checks)

    if has_failure and config.fail_links:
        for c in checks:
            if c.get("passed"):
                continue
            condition = c.get("condition", "")
            link = config.fail_links.get(condition)
            if link:
                url = _resolve_link(link, fmt)
                buttons.append(_btn_navigate(link["label"], url))

    # 중복 제거
    seen = set()
    unique = []
    for b in buttons:
        key = b.get("url", "")
        if key not in seen:
            seen.add(key)
            unique.append(b)

    # 버튼 없으면 기본 버튼
    if not unique and config.default_button:
        url = _resolve_link(config.default_button, fmt)
        unique.append(_btn_navigate(config.default_button["label"], url))

    return unique


RENDER_MAP = {
    "checklist": _render_checklist,
    "launch_report": _render_launch_report,
}


# ─── 위저드 엔진 ───


class WizardEngine:
    """YAML 스키마를 로드하고 위저드를 관리."""

    def __init__(self, wizards_dir: str | Path = "wizards"):
        self.schemas: dict[str, WizardSchema] = {}
        self._load_schemas(Path(wizards_dir))

    def _load_schemas(self, wizards_dir: Path):
        if not wizards_dir.exists():
            print(f"⚠️ 위저드 디렉토리 없음: {wizards_dir}")
            return
        for path in sorted(wizards_dir.glob("*.yaml")):
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
                schema = WizardSchema.from_dict(data)
                self.schemas[schema.id] = schema
                print(f"  📋 위저드 로드: {schema.id} ({schema.label})")
            except Exception as e:
                print(f"  ⚠️ 위저드 로드 실패: {path.name} — {e}")

    def get_actions(self) -> list[dict]:
        """프론트에 노출할 위저드 목록."""
        return [
            {"action": s.id, "label": s.label, "description": s.description, "icon": s.icon}
            for s in self.schemas.values()
        ]

    def create(self, action: str) -> WizardState:
        if action not in self.schemas:
            raise ValueError(f"알 수 없는 위저드: {action}. 가능: {list(self.schemas.keys())}")
        return WizardState(schema=self.schemas[action])


# ─── 위저드 상태 ───


@dataclass
class WizardState:
    """위저드 실행 상태. 세션당 1개."""

    schema: WizardSchema
    current_step_index: int = 0
    selections: dict[str, Any] = field(default_factory=dict)
    _active: bool = True

    @property
    def step(self) -> str:
        """현재 스텝 ID (기존 코드 호환)."""
        if self.current_step_index < len(self.schema.steps):
            return self.schema.steps[self.current_step_index].id
        return "done"

    @property
    def action(self) -> str:
        return self.schema.id

    def is_active(self) -> bool:
        return self._active

    def reset(self):
        self._active = False

    def get_step_progress(self) -> dict:
        """Phase 1 StepProgress 스키마."""
        return {
            "current": self.current_step_index,
            "total": len(self.schema.steps),
            "label": self.schema.steps[self.current_step_index].label if self.current_step_index < len(self.schema.steps) else "완료",
            "steps": [s.label for s in self.schema.steps],
        }

    def handle(self, button_data: dict) -> tuple[str, list[dict], str]:
        """버튼 입력 처리."""
        action = button_data.get("action", "")
        if action == "cancel":
            self.reset()
            return "취소했습니다. 다른 작업이 필요하시면 말씀해주세요.", [], "idle"
        if action == "back":
            return self._prev()

        value = button_data.get("value", "")
        if value:
            return self._select(value)

        if action == "execute":
            # confirm 스텝에서 "실행" 버튼 클릭 시 → execute 스텝으로 이동
            current = self._current_step_def()
            if current.type == "confirm":
                self.current_step_index += 1
            return self._execute()

        return "알 수 없는 입력입니다.", [], "error"

    def start(self) -> tuple[str, list[dict], str]:
        """위저드 시작."""
        self.current_step_index = 0
        return self._run_current_step()

    def start_with_master(self, master_id: str) -> tuple[str, list[dict], str]:
        """masterId로 클럽 선택 건너뛰기."""
        from src.tools.admin_api import get_master_detail
        try:
            detail = get_master_detail(master_id=master_id)
            master_name = detail.get("name", f"클럽 {master_id}")
        except Exception:
            master_name = f"클럽 {master_id}"

        self.selections["master_cms_id"] = master_id
        self.selections["master_name"] = master_name

        # select_master 스텝 건너뛰기
        if self.schema.steps and self.schema.steps[0].type == "select_master":
            self.current_step_index = 1
        return self._run_current_step()

    # ─── 내부 ───

    def _current_step_def(self) -> StepDefinition:
        return self.schema.steps[self.current_step_index]

    def _format(self, template: str) -> str:
        """selections 값으로 템플릿 치환. JSON 중괄호는 보호."""
        target = self._build_target()
        replacements = {
            "master_name": self.selections.get("master_name", ""),
            "page_title": self.selections.get("page_title", ""),
            "product_name": self.selections.get("product_name", ""),
            "page_id": self.selections.get("page_id", ""),
            "product_id": self.selections.get("product_id", ""),
            "target": target,
        }
        # {key}만 치환하고 나머지 중괄호는 보존
        import re
        def _replace(m):
            key = m.group(1)
            return replacements[key] if key in replacements else m.group(0)
        return re.sub(r"\{(\w+)\}", _replace, template)

    def _build_target(self) -> str:
        parts = []
        if self.selections.get("master_name"):
            parts.append(self.selections["master_name"])
        if self.selections.get("page_title"):
            parts.append(self.selections["page_title"])
        if self.selections.get("product_name"):
            parts.append(self.selections["product_name"])
        return " > ".join(parts) if parts else "선택 없음"

    def _select(self, value: str) -> tuple[str, list[dict], str]:
        """선택 처리 → 다음 스텝."""
        step_def = self._current_step_def()
        step_type = step_def.type

        SELECTION_MAP = {
            "select_master": ("master_cms_id", "master_", "_master_names", "master_name"),
            "select_page": ("page_id", "page_", "_page_names", "page_title"),
            "select_product": ("product_id", "product_", "_product_names", "product_name"),
        }

        if step_type in SELECTION_MAP:
            id_key, prefix, names_key, name_key = SELECTION_MAP[step_type]
            self.selections[id_key] = value.replace(prefix, "")
            self.selections[name_key] = self.selections.get(names_key, {}).get(value, value)

        self.current_step_index += 1
        return self._run_current_step()

    def _run_current_step_with_warning(self, warning: str) -> tuple[str, list[dict], str]:
        """현재 스텝을 다시 실행하되 경고 메시지를 앞에 붙인다."""
        msg, buttons, mode = self._run_current_step()
        return f"⚠️ {warning}\n\n{msg}", buttons, mode

    def _prev(self) -> tuple[str, list[dict], str]:
        """이전 스텝."""
        if self.current_step_index <= 0:
            self.reset()
            return "취소했습니다.", [], "idle"
        self.current_step_index -= 1
        return self._run_current_step()

    def _run_current_step(self) -> tuple[str, list[dict], str]:
        """현재 스텝 실행."""
        if self.current_step_index >= len(self.schema.steps):
            return self._execute()

        step_def = self._current_step_def()
        runner = STEP_RUNNERS.get(step_def.type)
        if not runner:
            return f"알 수 없는 스텝 타입: {step_def.type}", [], "error"
        return runner(self, step_def)

    def _execute(self) -> tuple[str, list[dict], str]:
        """execute 스텝 실행."""
        step_def = self._current_step_def()

        # 데이터 핸들러 + 렌더러 파이프라인
        if step_def.handler and step_def.handler in DATA_HANDLERS:
            try:
                data = DATA_HANDLERS[step_def.handler](self)
                self.reset()

                # 렌더러로 렌더링
                if step_def.render and step_def.render.type in RENDER_MAP:
                    return RENDER_MAP[step_def.render.type](data, step_def.render, self.selections)

                # render 미지정 → 기본 결과 표시
                return str(data), [], "done"
            except Exception as e:
                self.reset()
                return f"⚠️ 실행 중 오류: {e}", [], "error"

        # API 호출
        if step_def.api:
            api_map = _get_api_map()
            api_fn = api_map.get(step_def.api)
            if not api_fn:
                self.reset()
                return f"알 수 없는 API: {step_def.api}", [], "error"

            # 파라미터 치환
            params = {}
            for k, v in step_def.params.items():
                resolved = self._format(str(v))
                # JSON 파싱 시도 (updates 같은 dict 파라미터)
                if resolved.startswith("{") or resolved.startswith("["):
                    try:
                        resolved = json.loads(resolved)
                    except json.JSONDecodeError:
                        pass
                # bool 변환
                elif resolved.lower() == "true":
                    resolved = True
                elif resolved.lower() == "false":
                    resolved = False
                params[k] = resolved

            try:
                api_fn(**params)
                self.reset()
                msg = self._format(step_def.done_message) if step_def.done_message else f"✅ **{self.schema.label} 완료**\n\n{self._build_target()}"
                buttons = []
                for btn_def in step_def.done_buttons:
                    btn = dict(btn_def)
                    btn = _resolve_btn_url(btn, self)
                    buttons.append(btn)
                if not buttons:
                    buttons = [_btn_navigate("결과 확인", resolve_page_url("product_page_list")[0])]
                return msg, buttons, "done"
            except Exception as e:
                self.current_step_index = max(0, self.current_step_index - 1)
                msg = f"⚠️ 실행 중 오류가 발생했습니다: {e}"
                buttons = [
                    {"type": "action", "label": "다시 시도", "action": "execute", "variant": "primary"},
                    {"type": "action", "label": "취소", "action": "cancel", "variant": "ghost"},
                ]
                return msg, buttons, "error"

        self.reset()
        return "실행할 작업이 정의되지 않았습니다.", [], "error"


# ─── 스텝 러너 ───


def _run_select_master(state: WizardState, step_def: StepDefinition) -> tuple[str, list[dict], str]:
    """클럽 선택."""
    try:
        result = search_masters(search_keyword="")
        masters = result.get("masters", []) if isinstance(result, dict) else result if isinstance(result, list) else []
    except Exception:
        masters = []

    if not masters:
        state.reset()
        return "오피셜클럽을 찾을 수 없습니다. 토큰이 만료되었을 수 있습니다.", [], "error"

    masters.sort(key=lambda m: m.get("name", ""))

    name_map = {}
    buttons = []
    for m in masters[:30]:
        cms_id = str(m.get("cmsId", ""))
        name = m.get("name", f"클럽 {cms_id}")
        public_type = m.get("publicType", "")
        label = name if public_type == "PUBLIC" else f"{name} ({public_type})"
        key = f"master_{cms_id}"
        name_map[key] = name
        buttons.append(_btn_select(label, key))
    buttons.append({"type": "action", "label": "취소", "action": "cancel", "variant": "ghost"})

    state.selections["_master_names"] = name_map
    msg = state._format(step_def.message) if step_def.message else f"**{state.schema.label}** — 오피셜클럽을 선택하세요."
    return msg, buttons, "wizard"


def _run_select_page(state: WizardState, step_def: StepDefinition) -> tuple[str, list[dict], str]:
    """페이지 선택."""
    cms_id = state.selections["master_cms_id"]

    try:
        pages = get_product_page_list(master_id=cms_id)
        page_list = pages if isinstance(pages, list) else pages.get("pages", [])
    except Exception:
        page_list = []

    if not page_list:
        # reset하지 않고 마스터 선택으로 되돌림 — 다른 클럽 선택 가능
        state.current_step_index = max(0, state.current_step_index - 1)
        master_name = state.selections.get("master_name", "")
        msg = f"{master_name} 오피셜클럽에 상품페이지가 없습니다.\n\n다른 오피셜클럽을 선택하세요."
        return state._run_current_step_with_warning(msg)

    # exclude 설정: 이미 목표 상태인 항목은 disabled 처리
    exclude_field = None
    exclude_value = None
    exclude_reason = ""
    if step_def.exclude:
        exclude_field = step_def.exclude.get("field")
        exclude_value = step_def.exclude.get("value")
        exclude_reason = step_def.exclude.get("reason", "선택 불가")

    name_map = {}
    buttons = []
    selectable_count = 0
    for p in page_list:
        page_id = str(p.get("id", p.get("code", "")))
        title = p.get("title", f"페이지 {page_id}")
        status = p.get("status", "")
        label = f"{title} ({status})" if status else title
        key = f"page_{page_id}"
        name_map[key] = title

        # exclude 매칭 시 disabled
        is_excluded = (
            exclude_field
            and str(p.get(exclude_field, "")).upper() == str(exclude_value).upper()
        )
        if is_excluded:
            buttons.append({"type": "select", "label": f"{label} — {exclude_reason}", "value": key, "disabled": True})
        else:
            buttons.append(_btn_select(label, key))
            selectable_count += 1

    if selectable_count == 0:
        state.current_step_index = max(0, state.current_step_index - 1)
        master_name = state.selections.get("master_name", "")
        msg = f"{master_name}에 {exclude_reason} 상태가 아닌 상품페이지가 없습니다.\n\n다른 오피셜클럽을 선택하세요."
        return state._run_current_step_with_warning(msg)

    buttons.append({"type": "action", "label": "← 이전", "action": "back", "variant": "ghost"})
    buttons.append({"type": "action", "label": "취소", "action": "cancel", "variant": "ghost"})

    state.selections["_page_names"] = name_map
    msg = state._format(step_def.message) if step_def.message else f"**{state.schema.label}** — 상품페이지를 선택하세요."
    return msg, buttons, "wizard"


def _run_select_product(state: WizardState, step_def: StepDefinition) -> tuple[str, list[dict], str]:
    """상품 선택."""
    page_id = state.selections["page_id"]

    try:
        products = get_product_list_by_page(product_page_id=page_id)
        product_list = products if isinstance(products, list) else products.get("products", [])
    except Exception:
        product_list = []

    if not product_list:
        state.current_step_index = max(0, state.current_step_index - 1)
        page_title = state.selections.get("page_title", "")
        msg = f"{page_title}에 상품 옵션이 없습니다.\n\n다른 페이지를 선택하세요."
        return state._run_current_step_with_warning(msg)

    # exclude 설정
    exclude_field = None
    exclude_value = None
    exclude_reason = ""
    if step_def.exclude:
        exclude_field = step_def.exclude.get("field")
        exclude_value = step_def.exclude.get("value")
        exclude_reason = step_def.exclude.get("reason", "선택 불가")

    name_map = {}
    buttons = []
    selectable_count = 0
    for p in product_list:
        prod_id = str(p.get("productId", p.get("id", "")))
        name = p.get("name", p.get("title", f"상품 {prod_id}"))
        display = p.get("isDisplay")
        display_label = "공개" if display else "비공개" if display is not None else ""
        price = p.get("price", "")
        label = f"{name} ({display_label})" if display_label else name
        if price:
            label += f" — {price:,}원" if isinstance(price, (int, float)) else f" — {price}"
        key = f"product_{prod_id}"
        name_map[key] = name

        # exclude 매칭 시 disabled
        is_excluded = False
        if exclude_field:
            field_val = p.get(exclude_field)
            if isinstance(field_val, bool):
                is_excluded = field_val == (str(exclude_value).lower() == "true")
            else:
                is_excluded = str(field_val).upper() == str(exclude_value).upper()

        if is_excluded:
            buttons.append({"type": "select", "label": f"{label} — {exclude_reason}", "value": key, "disabled": True})
        else:
            buttons.append(_btn_select(label, key))
            selectable_count += 1

    if selectable_count == 0:
        state.current_step_index = max(0, state.current_step_index - 1)
        page_title = state.selections.get("page_title", "")
        msg = f"{page_title}에 {exclude_reason} 상태가 아닌 상품이 없습니다.\n\n다른 페이지를 선택하세요."
        return state._run_current_step_with_warning(msg)

    buttons.append({"type": "action", "label": "← 이전", "action": "back", "variant": "ghost"})
    buttons.append({"type": "action", "label": "취소", "action": "cancel", "variant": "ghost"})

    state.selections["_product_names"] = name_map
    msg = state._format(step_def.message) if step_def.message else f"**{state.schema.label}** — 상품을 선택하세요."
    return msg, buttons, "wizard"


def _run_confirm(state: WizardState, step_def: StepDefinition) -> tuple[str, list[dict], str]:
    """확인 — cascading 체크 포함."""
    warning = ""
    if step_def.cascading:
        try:
            cascade = check_cascading_effects(
                action=state.schema.id,
                context=state.selections,
            )
            if cascade and cascade.get("warning"):
                warning = f"\n\n⚠️ {cascade['warning']}"
        except Exception as e:
            warning = f"\n\n⚠️ 연쇄 효과 확인 실패 — 주의해서 진행해주세요. ({e})"

    msg = state._format(step_def.message) if step_def.message else f"**{state.schema.label}**\n\n**대상**: {state._build_target()}\n\n진행하시겠어요?"
    msg += warning

    buttons = [
        {"type": "action", "label": f"{state.schema.label} 실행", "action": "execute", "variant": "primary"},
        {"type": "action", "label": "← 이전", "action": "back", "variant": "ghost"},
        {"type": "action", "label": "취소", "action": "cancel", "variant": "ghost"},
    ]
    return msg, buttons, "wizard"


def _run_execute(state: WizardState, step_def: StepDefinition) -> tuple[str, list[dict], str]:
    """execute 스텝 — _execute로 위임."""
    return state._execute()


STEP_RUNNERS = {
    "select_master": _run_select_master,
    "select_page": _run_select_page,
    "select_product": _run_select_product,
    "confirm": _run_confirm,
    "execute": _run_execute,
}


# ─── 하위 호환 (server.py에서 사용) ───

# 전역 엔진 인스턴스 (서버 시작 시 로드)
_engine: WizardEngine | None = None


def _get_engine() -> WizardEngine:
    global _engine
    if _engine is None:
        _engine = WizardEngine()
    return _engine


def create_wizard(action: str) -> WizardState:
    """위저드 생성 (하위 호환)."""
    return _get_engine().create(action)


# WIZARD_ACTIONS는 이제 엔진에서 동적으로 생성
class _WizardActionsProxy:
    """WIZARD_ACTIONS dict처럼 동작하지만 엔진에서 읽어옴."""

    def items(self):
        return {s.id: {"label": s.label, "target_type": "master"} for s in _get_engine().schemas.values()}.items()

    def get(self, key, default=None):
        schema = _get_engine().schemas.get(key)
        if schema:
            return {"label": schema.label, "target_type": "master"}
        return default

    def keys(self):
        return _get_engine().schemas.keys()

    def __contains__(self, key):
        return key in _get_engine().schemas

    def __getitem__(self, key):
        result = self.get(key)
        if result is None:
            raise KeyError(key)
        return result


WIZARD_ACTIONS = _WizardActionsProxy()
