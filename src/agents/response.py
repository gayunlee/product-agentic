"""
응답 템플릿 시스템 — 일관된 포맷 + 버튼 보장.

LLM은 summary만 생성, 나머지는 코드로 렌더링.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AgentResponse:
    """수행 에이전트가 반환하는 구조화된 응답."""

    type: str  # diagnose | confirm | complete | guide | info | select
    summary: str  # LLM 생성 요약 (1~2줄)
    data: dict = field(default_factory=dict)


# ── 헤더 ──

HEADERS = {
    "diagnose": "📊 노출 진단 결과",
    "confirm": "⚡ 실행 확인",
    "complete": "✅ 완료",
    "guide": "🔗 안내",
    "info": "📄 조회 결과",
    "select": "📋 선택",
}


# ── Body 렌더러 ──

def _render_checklist(data: dict) -> str:
    checks = data.get("checks", [])
    if not checks:
        return ""
    lines = ["| 항목 | 상태 |", "|------|------|"]
    for c in checks:
        icon = "✅" if c["ok"] else "❌"
        name = c["name"]
        value = c.get("value", "")
        suffix = f" ← 원인" if not c["ok"] and c == next((x for x in checks if not x["ok"]), None) else ""
        lines.append(f"| {name} | {icon} {value}{suffix} |")
    return "\n".join(lines)


def _render_preview(data: dict) -> str:
    target = data.get("target", "")
    change = data.get("change", {})
    if not change:
        return f"**대상**: {target}"
    return f"**대상**: {target}\n**변경**: {change.get('field', '')} `{change.get('from', '')}` → `{change.get('to', '')}`"


def _render_result(data: dict) -> str:
    target = data.get("target", "")
    action_done = data.get("action_done", "처리")
    return f"**{target}** — {action_done} 완료"


def _render_steps(data: dict) -> str:
    steps = data.get("steps", [])
    if not steps:
        return ""
    return "\n".join(f"{i}. {s}" for i, s in enumerate(steps, 1))


def _render_table(data: dict) -> str:
    items = data.get("items", [])
    if not items:
        return "데이터가 없습니다."
    keys = list(items[0].keys())
    lines = [" | ".join(keys), " | ".join("---" for _ in keys)]
    for item in items:
        lines.append(" | ".join(str(item.get(k, "")) for k in keys))
    return "\n".join(lines)


def _render_item_list(data: dict) -> str:
    items = data.get("items", [])
    question = data.get("question", "선택해주세요.")
    lines = [question, ""]
    for i, item in enumerate(items, 1):
        lines.append(f"{i}. {item['label']}")
    return "\n".join(lines)


BODY_RENDERERS = {
    "diagnose": _render_checklist,
    "confirm": _render_preview,
    "complete": _render_result,
    "guide": _render_steps,
    "info": _render_table,
    "select": _render_item_list,
}


# ── 버튼 패턴 ──

def _btn_action(label: str) -> dict:
    return {"type": "action", "label": label, "variant": "primary"}


def _btn_navigate(label: str, url: str) -> dict:
    return {"type": "navigate", "label": label, "url": url, "variant": "secondary"}


def _btn_select(label: str, value: str) -> dict:
    return {"type": "select", "label": label, "value": value}


BUTTON_PATTERNS = {
    "diagnose": lambda d: (
        [_btn_action(d["fix_label"]), _btn_navigate("설정 관리", d["nav_url"])]
        if d.get("first_failure")
        else [_btn_navigate("설정 확인", d.get("nav_url", "/product/page/list"))]
    ),
    "confirm": lambda d: [
        _btn_action(d["action_label"]),
        _btn_navigate("직접 수정", d["edit_url"]),
    ],
    "complete": lambda d: [
        _btn_navigate("결과 확인", d["confirm_url"]),
    ],
    "guide": lambda d: [
        _btn_navigate(d["label"], d["url"]),
    ],
    "select": lambda d: [
        _btn_select(item["label"], item["value"])
        for item in d.get("items", [])
    ],
    "info": lambda d: [],
}


# ── 응답 조립 ──

def render_response(resp: AgentResponse) -> tuple[str, list[dict], str]:
    """AgentResponse를 (message, buttons, mode)로 렌더링.

    Returns:
        (message: str, buttons: list[dict], mode: str)
    """
    header = HEADERS.get(resp.type, "")
    renderer = BODY_RENDERERS.get(resp.type)
    body = renderer(resp.data) if renderer else ""
    button_fn = BUTTON_PATTERNS.get(resp.type)
    buttons = button_fn(resp.data) if button_fn else []
    mode = resp.type

    parts = [header]
    if resp.summary:
        parts.append(resp.summary)
    if body:
        parts.append(body)

    message = "\n\n".join(parts)
    return message, buttons, mode
