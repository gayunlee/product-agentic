"""
응답 템플릿 시스템 — 일관된 포맷 + 버튼 + 후속질문 보장.

LLM은 summary만 생성, 나머지는 코드로 렌더링.
respond Tool이 이 모듈을 호출하여 완성된 응답을 반환.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field


class ExecutorOutput(BaseModel):
    """수행 에이전트의 structured_output 스키마."""

    response_type: str = Field(
        description="응답 유형: diagnose, confirm, complete, guide, info, select, slot_question, error, reject"
    )
    summary: str = Field(
        description="유저에게 보여줄 요약 (1~2줄, 자연어)"
    )
    data: dict[str, Any] = Field(
        default_factory=dict,
        description="응답 데이터. type별 필수 필드: "
        "diagnose={checks,first_failure,fix_label,nav_url}, "
        "confirm={target,action_label,change,edit_url}, "
        "complete={target,action_done,confirm_url}, "
        "guide={label,url,steps}, "
        "info={title,items,fix_label?,nav_url?}, "
        "select={question,items}, "
        "slot_question={question,items?}, "
        "error={error_type,guide}, "
        "reject={reason}",
    )


@dataclass
class AgentResponse:
    """렌더링에 사용되는 내부 응답 객체."""

    type: str
    summary: str
    data: dict = field(default_factory=dict)

    @classmethod
    def from_executor_output(cls, output: ExecutorOutput) -> AgentResponse:
        return cls(type=output.response_type, summary=output.summary, data=output.data)


# ── 헤더 ──

HEADERS = {
    "diagnose": "📊 노출 진단 결과",
    "confirm": "⚡ 실행 확인",
    "complete": "✅ 완료",
    "guide": "🔗 안내",
    "info": "📄 조회 결과",
    "select": "📋 선택",
    "slot_question": "",  # 헤더 없음 (질문만)
    "error": "⚠️ 오류",
    "reject": "🚫 요청 불가",
}


# ── Body 렌더러 ──


def _render_checklist(data: dict) -> str:
    """진단 결과를 ✅/❌ 테이블로 렌더링."""
    checks = data.get("checks", [])
    if not checks:
        return ""
    # ok/passed 키 호환
    def _is_ok(c):
        return c.get("ok", c.get("passed", False))
    def _get_name(c):
        return c.get("name", c.get("label", c.get("condition", "")))
    def _get_value(c):
        return c.get("value", c.get("actual", ""))

    first_fail = next((c for c in checks if not _is_ok(c)), None)
    lines = ["| 항목 | 상태 |", "|------|------|"]
    for c in checks:
        icon = "✅" if _is_ok(c) else "❌"
        value = _get_value(c)
        suffix = " ← 원인" if c is first_fail else ""
        lines.append(f"| {_get_name(c)} | {icon} {value}{suffix} |")
    return "\n".join(lines)


def _render_preview(data: dict) -> str:
    """변경 전/후 미리보기."""
    target = data.get("target", "")
    change = data.get("change", {})
    if not change:
        return f"**대상**: {target}"
    return (
        f"**대상**: {target}\n"
        f"**변경**: {change.get('field', '')} `{change.get('from', '')}` → `{change.get('to', '')}`"
    )


def _render_result(data: dict) -> str:
    """완료 결과."""
    target = data.get("target", "")
    action_done = data.get("action_done", "처리")
    return f"**{target}** — {action_done} 완료"


def _render_steps(data: dict) -> str:
    """단계별 안내."""
    steps = data.get("steps", [])
    if not steps:
        return ""
    return "\n".join(f"{i}. {s}" for i, s in enumerate(steps, 1))


def _render_table(data: dict) -> str:
    """정보 테이블."""
    items = data.get("items", [])
    if not items:
        return "데이터가 없습니다."
    keys = list(items[0].keys())
    lines = ["| " + " | ".join(keys) + " |", "| " + " | ".join("---" for _ in keys) + " |"]
    for item in items:
        lines.append("| " + " | ".join(str(item.get(k, "")) for k in keys) + " |")
    return "\n".join(lines)


def _render_item_list(data: dict) -> str:
    """선택 목록."""
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
    "slot_question": lambda d: _render_item_list(d) if d.get("items") else "",
    "error": lambda d: d.get("guide", ""),
    "reject": lambda d: d.get("reason", ""),
}


# ── 버튼 헬퍼 ──


def _btn_action(label: str) -> dict:
    return {"type": "action", "label": label, "variant": "primary"}


def _btn_navigate(label: str, url: str) -> dict:
    return {"type": "navigate", "label": label, "url": url, "variant": "secondary"}


def _btn_select(label: str, value: str) -> dict:
    return {"type": "select", "label": label, "value": value}


# ── 버튼 패턴 ──

BUTTON_PATTERNS = {
    "diagnose": lambda d: (
        [_btn_action(d.get("fix_label", "해결하기")), _btn_navigate("설정 관리", d.get("nav_url", "/product/page/list"))]
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
    "info": lambda d: (
        [_btn_action(d["fix_label"]), _btn_navigate("설정 관리", d["nav_url"])]
        if d.get("fix_label")
        else []
    ),
    "select": lambda d: [
        _btn_select(item["label"], item["value"]) for item in d.get("items", [])
    ],
    "slot_question": lambda d: (
        [_btn_select(item["label"], item["value"]) for item in d["items"]]
        if d.get("items")
        else []
    ),
    "error": lambda d: (
        [_btn_navigate("이동", d["nav_url"])] if d.get("nav_url") else []
    ),
    "reject": lambda d: [],
}


# ── 후속 질문 기본값 ──

DEFAULT_FOLLOW_UPS = {
    "diagnose": lambda d: "해결해드릴까요?" if d.get("first_failure") else "다른 확인이 필요하신가요?",
    "confirm": lambda d: None,  # 질문 자체가 확인
    "complete": lambda d: "다른 작업이 필요하시면 말씀해주세요.",
    "guide": lambda d: "완료하시면 말씀해주세요.",
    "info": lambda d: "활성화가 필요하신가요?" if d.get("fix_label") else "수정이 필요하시면 말씀해주세요.",
    "select": lambda d: None,  # 질문 자체가 선택
    "slot_question": lambda d: None,  # 질문 자체
    "error": lambda d: None,
    "reject": lambda d: "상품 세팅 관련 요청만 도와드릴 수 있습니다.",
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

    # 후속 질문: data에 명시적 follow_up 있으면 사용, 없으면 기본값
    follow_up = resp.data.get("follow_up")
    if follow_up is None:
        default_fn = DEFAULT_FOLLOW_UPS.get(resp.type)
        follow_up = default_fn(resp.data) if default_fn else None

    # 조립
    parts = []
    if header:
        parts.append(header)
    if resp.summary:
        parts.append(resp.summary)
    if body:
        parts.append(body)
    if follow_up:
        parts.append(follow_up)

    message = "\n\n".join(parts)
    return message, buttons, mode


def render_response_json(resp: AgentResponse) -> str:
    """AgentResponse를 respond Tool이 반환하는 JSON 문자열로 렌더링.

    respond Tool 내부에서 호출. 서버가 이 JSON을 파싱하여 ChatResponse로 변환.
    """
    message, buttons, mode = render_response(resp)
    return json.dumps(
        {
            "__agent_response__": True,
            "message": message,
            "buttons": buttons,
            "mode": mode,
        },
        ensure_ascii=False,
    )
