"""
대화 맥락 관리 — 세션별 히스토리 + flow 상태 + active agent 관리.

server.py의 _chat_history / _active_agent를 대체.
truncate 없이 풀 메시지를 저장하고, 라우터에 맥락을 제공한다.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.agents import AgentSystem
    from src.memory import AgentMemory
    from src.wizard import WizardState


MAX_MESSAGES = 20  # 세션당 최대 메시지 수 (초과 시 오래된 것부터 제거)
IDLE_TIMEOUT_SEC = 600  # 10분 idle → active agent 해제

# active agent를 유지하는 응답 모드
KEEP_ACTIVE_MODES = frozenset({
    "slot_question", "select", "diagnose", "confirm", "info", "complete",
})


@dataclass
class SessionContext:
    """세션의 모든 상태를 한 곳에서 관리. server.py의 4개 dict를 통합."""

    session_id: str
    system: AgentSystem | None = None
    memory: Any = None  # AgentMemory | None
    wizard: Any = None  # WizardState | None
    created_at: float = field(default_factory=time.time)


@dataclass
class ConversationContext:
    """세션 하나의 대화 맥락."""

    session_id: str
    messages: list[dict] = field(default_factory=list)
    active_agent: str | None = None  # "executor" | "domain" | None
    last_response_mode: str = "idle"
    flow_context: dict = field(default_factory=dict)  # 축적된 슬롯 데이터
    last_activity: float = field(default_factory=time.time)
    last_diagnose_resolves: list[dict] | None = None  # 진단 후 해결 액션


class SessionStore:
    """세션별 ConversationContext를 관리."""

    def __init__(self) -> None:
        self._sessions: dict[str, ConversationContext] = {}

    def get_or_create(self, session_id: str) -> ConversationContext:
        if session_id not in self._sessions:
            self._sessions[session_id] = ConversationContext(session_id=session_id)
        return self._sessions[session_id]

    def add_user_message(self, session_id: str, message: str) -> None:
        ctx = self.get_or_create(session_id)
        ctx.messages.append({"role": "user", "content": message})
        ctx.last_activity = time.time()
        self._trim(ctx)

    def add_assistant_message(
        self,
        session_id: str,
        message: str,
        mode: str,
        flow_data: dict | None = None,
    ) -> None:
        """어시스턴트 응답을 저장하고 active agent 상태를 갱신."""
        ctx = self.get_or_create(session_id)
        ctx.messages.append({"role": "assistant", "content": message, "mode": mode})
        ctx.last_response_mode = mode
        ctx.last_activity = time.time()

        if flow_data:
            ctx.flow_context.update(flow_data)

        # active agent 유지 판단
        if not self.should_keep_active(session_id, mode):
            ctx.active_agent = None
            ctx.flow_context.clear()

        self._trim(ctx)

    def set_active_agent(self, session_id: str, agent: str) -> None:
        ctx = self.get_or_create(session_id)
        ctx.active_agent = agent
        ctx.last_activity = time.time()

    def release_active_agent(self, session_id: str) -> None:
        ctx = self.get_or_create(session_id)
        ctx.active_agent = None
        ctx.flow_context.clear()

    def should_keep_active(self, session_id: str, new_mode: str) -> bool:
        """active agent를 유지할지 결정."""
        ctx = self.get_or_create(session_id)

        # idle timeout
        if time.time() - ctx.last_activity > IDLE_TIMEOUT_SEC:
            return False

        # 유지 모드
        if new_mode in KEEP_ACTIVE_MODES:
            return True

        # flow_context에 데이터가 있으면 슬롯 필링 중
        if ctx.flow_context:
            return True

        return False

    def get_context_for_router(self, session_id: str) -> str:
        """Tier 2 LLM 라우터에 전달할 대화 맥락 문자열."""
        ctx = self.get_or_create(session_id)
        if not ctx.messages:
            return ""

        recent = ctx.messages[-10:]  # 최근 5턴
        lines = []
        for msg in recent:
            role = "유저" if msg["role"] == "user" else "에이전트"
            content = msg["content"][:500]
            mode_tag = f" [{msg.get('mode', '')}]" if msg.get("mode") else ""
            lines.append(f"{role}{mode_tag}: {content}")
        return "\n".join(lines)

    def clear(self, session_id: str | None = None) -> None:
        """세션 초기화."""
        if session_id:
            self._sessions.pop(session_id, None)
        else:
            self._sessions.clear()

    def clear_all(self) -> None:
        self._sessions.clear()

    def _trim(self, ctx: ConversationContext) -> None:
        """메시지가 MAX_MESSAGES를 초과하면 오래된 것부터 제거."""
        if len(ctx.messages) > MAX_MESSAGES:
            ctx.messages = ctx.messages[-MAX_MESSAGES:]


class SessionManager:
    """세션별 SessionContext를 관리. server.py의 4개 dict를 대체."""

    def __init__(self) -> None:
        self._contexts: dict[str, SessionContext] = {}

    def get(self, session_id: str) -> SessionContext:
        """세션 조회. 없으면 생성."""
        if session_id not in self._contexts:
            self._contexts[session_id] = SessionContext(session_id=session_id)
        return self._contexts[session_id]

    def get_or_create_system(self, session_id: str, factory, memory_context: str = ""):
        """AgentSystem을 조회하거나 생성. factory는 create_agent_system 함수."""
        ctx = self.get(session_id)
        if ctx.system is None:
            ctx.system = factory(memory_context=memory_context)
        else:
            # 기존 시스템 유지 (대화 히스토리 보존), memory_context만 갱신
            if memory_context:
                from src.agents.orchestrator import ORCHESTRATOR_PROMPT
                ctx.system.orchestrator.system_prompt = ORCHESTRATOR_PROMPT
                ctx.system.orchestrator.system_prompt += f"\n## 관련 이력 (Memory)\n{memory_context}\n"
        return ctx.system

    def get_or_create_memory(self, session_id: str, factory):
        """AgentMemory를 조회하거나 생성. factory는 create_memory_session 함수."""
        ctx = self.get(session_id)
        if ctx.memory is None:
            ctx.memory = factory(session_id)
        return ctx.memory

    @property
    def wizard(self):
        """편의 접근자 — 현재 세션의 wizard."""
        raise AttributeError("Use get(session_id).wizard instead")

    def clear(self, session_id: str | None = None) -> None:
        """세션 초기화."""
        if session_id:
            self._contexts.pop(session_id, None)
        else:
            self._contexts.clear()

    def clear_all(self) -> None:
        self._contexts.clear()
