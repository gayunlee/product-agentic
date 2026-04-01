"""
에이전트 서버 ↔ 패널 공유 스키마 (Python 미러).
Source of truth: schema/types.ts
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


# ─── Chat Mode ───

class ChatMode(str, Enum):
    IDLE = "idle"
    DIAGNOSE = "diagnose"
    GUIDE = "guide"
    EXECUTE = "execute"
    DONE = "done"
    WIZARD = "wizard"
    LAUNCH_CHECK = "launch_check"
    SELECT = "select"
    SLOT_QUESTION = "slot_question"
    CONFIRM = "confirm"
    INFO = "info"
    DOMAIN = "domain"
    ERROR = "error"
    REJECT = "reject"


# ─── Button ───

ButtonClickable = Literal["once", "always"]
ButtonVariant = Literal["primary", "secondary", "ghost", "danger"]


class AgentButton(BaseModel):
    type: Literal["select", "action", "navigate"]
    label: str

    # type별 필드
    value: str | None = None       # select
    action: str | None = None      # action
    url: str | None = None         # navigate
    payload: dict | None = None    # execute_confirmed용 (action_id, slots)

    # 동작 제어
    clickable: ButtonClickable = "once"
    variant: ButtonVariant = "secondary"

    # 선택적
    description: str | None = None
    disabled: bool = False


# ─── Step Progress ───

class StepProgress(BaseModel):
    current: int
    total: int
    label: str
    steps: list[str]


# ─── Agent Response ───

class AgentResponseMeta(BaseModel):
    mock_mode: bool = False


class AgentResponse(BaseModel):
    message: str
    buttons: list[AgentButton] = Field(default_factory=list)
    mode: ChatMode = ChatMode.IDLE
    step: StepProgress | None = None
    meta: AgentResponseMeta = Field(default_factory=AgentResponseMeta)


# ─── Request ───

class ButtonInput(BaseModel):
    type: Literal["select", "action"]
    value: str | None = None
    action: str | None = None
    payload: dict | None = None  # execute_confirmed용 (action_id, slots)


class ChatContext(BaseModel):
    token: str | None = None
    currentPath: str | None = None
    masterId: str | None = None
    productPageId: str | None = None
    role: str | None = None
    permissions: list[str] | None = None


class ChatRequest(BaseModel):
    message: str = ""
    button: ButtonInput | None = None
    wizard_action: str | None = None
    session_id: str | None = None
    context: ChatContext | None = None


# ─── Wizard Action ───

class WizardAction(BaseModel):
    action: str
    label: str
    description: str | None = None
    icon: str | None = None


# ─── Builder ───

CLICKABLE_DEFAULTS: dict[str, ButtonClickable] = {
    "select": "once",
    "action": "once",
    "navigate": "always",
}


def build_response(
    message: str,
    buttons: list[dict[str, Any]] | list[AgentButton] | None = None,
    mode: str | ChatMode = "idle",
    step: StepProgress | dict | None = None,
    meta: dict[str, Any] | None = None,
) -> AgentResponse:
    """Phase 1 계약에 맞는 응답 생성. 모든 경로가 이걸 통과."""
    normalized_buttons = []
    for btn in (buttons or []):
        if isinstance(btn, dict):
            # clickable 기본값 적용
            if "clickable" not in btn:
                btn["clickable"] = CLICKABLE_DEFAULTS.get(btn.get("type", "action"), "once")
            # variant 기본값
            if "variant" not in btn:
                btn["variant"] = "secondary"
            normalized_buttons.append(AgentButton(**btn))
        else:
            normalized_buttons.append(btn)

    normalized_step = None
    if step is not None:
        normalized_step = StepProgress(**step) if isinstance(step, dict) else step

    mode_enum = ChatMode(mode) if isinstance(mode, str) else mode

    return AgentResponse(
        message=message,
        buttons=normalized_buttons,
        mode=mode_enum,
        step=normalized_step,
        meta=AgentResponseMeta(**(meta or {})),
    )


def build_error_response(
    error: str,
    recoverable: bool = False,
    retry_action: str | None = None,
) -> AgentResponse:
    """에러 응답. recoverable이면 재시도 버튼 포함."""
    buttons = []
    if recoverable and retry_action:
        buttons.append({
            "type": "action",
            "label": "다시 시도",
            "action": retry_action,
            "clickable": "once",
            "variant": "primary",
        })
    return build_response(
        message=f"⚠️ {error}",
        buttons=buttons,
        mode="error",
    )
