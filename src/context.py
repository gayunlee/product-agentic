"""
세션 관리 — SessionContext + SessionManager.

위저드 상태(WizardState)와 에이전트 시스템(AgentSystem)을 세션별로 관리.
자유대화 맥락은 Strands Agent의 internal message history가 담당.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.agents import AgentSystem
    from src.memory import AgentMemory
    from src.wizard import WizardState


@dataclass
class SessionContext:
    """세션의 모든 상태를 한 곳에서 관리. server.py의 4개 dict를 통합."""

    session_id: str
    system: AgentSystem | None = None
    memory: Any = None  # AgentMemory | None
    wizard: Any = None  # WizardState | None
    last_diagnose_resolves: list[dict] | None = None  # 진단 후 해결 액션
    created_at: float = field(default_factory=time.time)


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
