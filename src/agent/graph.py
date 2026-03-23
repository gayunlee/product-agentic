"""
LangGraph 래퍼 — FlowMachine을 LangGraph로 감싸서 interrupt/resume + checkpointer 제공.

FlowMachine의 LLM 분류 + 라우팅 + 실행은 그대로 유지.
wait_* 상태만 interrupt()로 대체, 세션 상태는 checkpointer가 관리.
"""

from __future__ import annotations

import json
import logging
from typing import Any, TypedDict, Annotated

from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.types import interrupt
from langgraph.checkpoint.memory import MemorySaver

from src.agent.flow_machine import FlowMachine
from langfuse import observe

logger = logging.getLogger(__name__)


# ── State ──

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    # FlowMachine 상태 보존
    flow_state: str
    flow_data: dict[str, Any]
    flow_pending_target: str | None
    flow_history: list[dict]
    # 응답
    response_message: str
    response_buttons: list[dict]
    response_mode: str
    response_step: dict | None
    # 프론트엔드 컨텍스트
    context: dict[str, Any]


def _restore_flow(state: AgentState) -> FlowMachine:
    """checkpointer에서 FlowMachine 복원."""
    flow = FlowMachine.__new__(FlowMachine)
    flow.session_id = "langgraph"
    flow.state = state.get("flow_state", "idle")
    flow.data = dict(state.get("flow_data", {}))
    flow._pending_target = state.get("flow_pending_target")
    flow._history = list(state.get("flow_history", []))
    return flow


def _save_flow(flow: FlowMachine, result) -> dict:
    """FlowMachine 상태를 graph state로 저장."""
    return {
        "flow_state": flow.state,
        "flow_data": {k: v for k, v in flow.data.items() if _is_serializable(v)},
        "flow_pending_target": flow._pending_target,
        "flow_history": flow._history[-20:],  # 최근 20개만
        "response_message": result.message,
        "response_buttons": result.buttons,
        "response_mode": result.mode,
        "response_step": result.step,
    }


def _is_serializable(v: Any) -> bool:
    """JSON 직렬화 가능한 값인지 체크."""
    try:
        json.dumps(v)
        return True
    except (TypeError, ValueError):
        return False


def _result_to_interrupt(result) -> dict:
    """FlowMachine Response를 interrupt 값으로 변환."""
    return {
        "message": result.message,
        "buttons": result.buttons,
        "mode": result.mode,
        "step": result.step,
    }


# ── 메인 노드 ──

@observe(name="agent_node")
def agent_node(state: AgentState) -> dict:
    """FlowMachine을 실행하는 단일 노드.

    wait_* 상태면 interrupt로 중단, resume 시 계속.
    """
    from langchain_core.messages import HumanMessage

    # 마지막 유저 메시지
    messages = state.get("messages", [])
    last_msg = ""
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            last_msg = m.content
            break

    if not last_msg:
        return {
            "response_message": "무엇을 도와드릴까요?",
            "response_buttons": [],
            "response_mode": "idle",
            "response_step": None,
        }

    # FlowMachine 복원
    flow = _restore_flow(state)
    context = state.get("context", {})

    # 토큰 주입
    if context and context.get("token"):
        import src.tools.admin_api as admin_api
        admin_api.ADMIN_TOKEN = context["token"]

    print(f"📍 [agent] state={flow.state}, msg='{last_msg[:50]}'")

    # FlowMachine 실행
    result = flow.handle(last_msg, context)
    print(f"📍 [agent] after handle: state={flow.state}, msg='{result.message[:80]}'")

    # wait_* 상태면 interrupt로 중단 → resume 시 계속
    max_loops = 10
    loop_count = 0
    while flow.state.startswith("wait_") and loop_count < max_loops:
        loop_count += 1
        print(f"📍 [agent] wait state={flow.state} → interrupt (loop {loop_count})")

        # 현재 응답을 interrupt로 전달 (프론트엔드에 표시)
        human_input = interrupt(_result_to_interrupt(result))

        print(f"📍 [agent] resumed with: '{str(human_input)[:50]}'")

        # resume된 입력으로 FlowMachine 재실행
        result = flow.handle(str(human_input), context)
        print(f"📍 [agent] after resume handle: state={flow.state}, msg='{result.message[:80]}'")

    # 최종 상태 저장
    return _save_flow(flow, result)


# ── 그래프 빌드 ──

def build_graph() -> StateGraph:
    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_edge(START, "agent")
    graph.add_edge("agent", END)
    return graph


def create_app(guardrail_config: dict | None = None):
    """컴파일된 그래프 앱을 생성."""
    graph = build_graph()
    checkpointer = MemorySaver()
    return graph.compile(checkpointer=checkpointer)


# ── eval 호환 ──

import threading

_thread_local = threading.local()


def reset_api_log():
    _thread_local.api_log = []
    _thread_local.phase_log = []


def get_api_log() -> list[dict]:
    return list(getattr(_thread_local, "api_log", []))


def get_phase_log() -> list[str]:
    return list(getattr(_thread_local, "phase_log", []))
