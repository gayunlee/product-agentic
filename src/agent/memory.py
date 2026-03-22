"""
AgentCore Memory 연동.

세션 상태 유지 (short-term) + 세팅 이력 기억 (long-term).
SlidingWindow 맥락 유실을 방지하고, 이전 세팅 이력을 검색합니다.
"""

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from bedrock_agentcore.memory.session import MemorySessionManager
from bedrock_agentcore.memory.constants import ConversationalMessage, MessageRole

logger = logging.getLogger(__name__)

MEMORY_ID_PATH = Path(__file__).parent.parent.parent / "memory_id.json"
REGION = "us-west-2"

# 시스템 프롬프트에 주입할 컨텍스트 최대 글자 수
MAX_CONTEXT_CHARS = 2000


@dataclass
class AgentMemory:
    """에이전트 Memory 세션 래퍼. actor_id/session_id를 함께 들고 다님."""

    manager: MemorySessionManager
    actor_id: str
    session_id: str


def _load_memory_id() -> str:
    with open(MEMORY_ID_PATH) as f:
        return json.load(f)["memoryId"]


def create_memory_session(
    session_id: str,
    actor_id: str = "default_operator",
) -> AgentMemory:
    """AgentCore Memory 세션을 생성/재개합니다."""
    memory_id = _load_memory_id()
    manager = MemorySessionManager(
        memory_id=memory_id,
        region_name=REGION,
    )
    manager.create_memory_session(
        actor_id=actor_id,
        session_id=session_id,
    )
    return AgentMemory(manager=manager, actor_id=actor_id, session_id=session_id)


def save_turn(mem: AgentMemory, role: str, content: str) -> None:
    """대화 턴을 Memory에 저장합니다."""
    msg_role = MessageRole.USER if role == "user" else MessageRole.ASSISTANT
    mem.manager.add_turns(
        actor_id=mem.actor_id,
        session_id=mem.session_id,
        messages=[ConversationalMessage(content, msg_role)],
    )


def _extract_record_text(record) -> str:
    """Memory record에서 텍스트만 추출하고 XML 태그를 정리합니다."""
    if hasattr(record, "content"):
        # MemoryRecord 객체
        text = record.content.get("text", "") if isinstance(record.content, dict) else str(record.content)
    elif isinstance(record, dict):
        text = record.get("content", {}).get("text", "")
    else:
        text = str(record)

    # <topic name="...">내용</topic> → "주제: 내용"
    text = re.sub(
        r'<topic name="([^"]*)">\s*',
        lambda m: f"[{m.group(1)}] ",
        text,
    )
    text = re.sub(r"</topic>", "", text)
    # 연속 공백/줄바꿈 정리
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _truncate_context(text: str, max_chars: int = MAX_CONTEXT_CHARS) -> str:
    """컨텍스트가 너무 길면 잘라냅니다."""
    if len(text) <= max_chars:
        return text
    # 줄 단위로 잘라서 max_chars 이내로
    lines = text.split("\n")
    result = []
    total = 0
    for line in lines:
        if total + len(line) + 1 > max_chars:
            result.append("... (이전 이력 생략)")
            break
        result.append(line)
        total += len(line) + 1
    return "\n".join(result)


def get_context_for_prompt(mem: AgentMemory, query: str) -> str:
    """시스템 프롬프트에 주입할 메모리 컨텍스트를 구성합니다.

    1. Short-term: 최근 대화 (last k turns)
    2. Long-term: 관련 사실/이력 (semantic search)

    전체 컨텍스트는 MAX_CONTEXT_CHARS 이내로 제한합니다.
    """
    context_parts = []

    # 1. Short-term — 최근 대화 (같은 세션)
    try:
        turns = mem.manager.get_last_k_turns(
            actor_id=mem.actor_id,
            session_id=mem.session_id,
            k=5,
        )
        if turns:
            recent = []
            for turn_group in turns[-3:]:
                for msg in turn_group:
                    role = msg.get("role", "")
                    text = msg.get("content", {}).get("text", "")
                    if role and text:
                        label = "유저" if role == "USER" else "어시스턴트"
                        recent.append(f"- {label}: {text[:150]}")
            if recent:
                context_parts.append("## 최근 대화\n" + "\n".join(recent))
    except Exception as e:
        logger.debug(f"Short-term memory 조회 실패: {e}")

    # 2. Long-term — 사실 + 이력 (세션 간)
    try:
        records = mem.manager.search_long_term_memories(
            query=query,
            namespace_prefix=f"/actors/{mem.actor_id}/",
            top_k=5,
        )
        if records:
            facts = []
            for r in records:
                text = _extract_record_text(r)
                if text:
                    facts.append(f"- {text[:200]}")
            if facts:
                context_parts.append("## 이전 이력\n" + "\n".join(facts))
    except Exception as e:
        logger.debug(f"Long-term memory 검색 실패: {e}")

    if not context_parts:
        return ""

    full_context = "\n\n".join(context_parts)
    return _truncate_context(full_context)
