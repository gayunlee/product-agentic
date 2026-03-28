"""
2티어 라우팅 — 패턴 매칭(Tier 1) + LLM 라우터(Tier 2).

Tier 1: 정규식 + 후속 메시지 감지 → 즉시 라우팅 (LLM 호출 0)
Tier 2: LLM에 풀 히스토리 전달 → 맥락 기반 라우팅
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.context import ConversationContext

# ── Tier 1: 패턴 기반 라우팅 ──

ROUTE_PATTERNS: dict[str, list[str]] = {
    "REJECT": [
        r"(환불|결제\s*취소|개인정보|시스템\s*프롬프트|코드\s*생성|코드\s*짜)",
    ],
    "EXECUTOR": [
        # 실행 요청
        r"(해줘|해\s*주세요|비공개|공개|활성화|변경|처리|설정해)",
        # 진단
        r"(왜.*안\s*보여|왜.*노출.*안|안\s*보여|안\s*나와|노출.*안\s*돼)",
        r"(진단|체크해|확인해줘)",
        # 네비게이션
        r"(이동|어디서.*설정|페이지로)",
    ],
    "DOMAIN": [
        r"(뭐야\??|뭔가요|차이가|차이점|가능해\??|어떻게\s*돼)",
        r"(개념|설명|규칙|설정\s*방법|의미|뜻)",
    ],
    "SELF": [
        r"^(안녕|감사|고마워|ㅎㅇ|하이|hello|hi|ㅎㅎ)\s*[!?.]*$",
    ],
}

_COMPILED_PATTERNS: dict[str, list[re.Pattern]] = {
    route: [re.compile(p, re.IGNORECASE) for p in patterns]
    for route, patterns in ROUTE_PATTERNS.items()
}


def _matches_pattern(route: str, message: str) -> bool:
    """주어진 라우트의 패턴에 매칭되는지 확인."""
    for pattern in _COMPILED_PATTERNS.get(route, []):
        if pattern.search(message):
            return True
    return False


def _is_likely_followup(message: str, ctx: ConversationContext) -> bool:
    """직전 대화의 후속 메시지인지 감지."""
    if not ctx.messages:
        return False

    # 슬롯 응답은 무조건 후속
    if ctx.last_response_mode in ("slot_question", "select"):
        return True

    # 활성 에이전트 + 짧은 메시지 → 후속 가능성 높음
    if ctx.active_agent and len(message) < 20:
        return not _matches_pattern("REJECT", message)

    # 진단 직후 → 다른 대상 진단 가능성
    if ctx.last_response_mode == "diagnose" and not _matches_pattern("REJECT", message):
        return True

    return False


class PatternRouter:
    """Tier 1: 정규식 패턴 + 후속 감지로 즉시 분류."""

    @staticmethod
    def classify(message: str, ctx: ConversationContext) -> str | None:
        """매칭되면 라우트 문자열 반환, 안 되면 None (Tier 2로 넘김)."""
        # 1. 후속 메시지 감지
        if _is_likely_followup(message, ctx):
            return "CONTINUE"

        # 2. REJECT 먼저 (빠른 거부)
        if _matches_pattern("REJECT", message):
            return "REJECT"

        # 3. SELF (짧은 인사)
        if _matches_pattern("SELF", message):
            return "SELF"

        # 4. EXECUTOR / DOMAIN 판별
        is_executor = _matches_pattern("EXECUTOR", message)
        is_domain = _matches_pattern("DOMAIN", message)

        if is_executor and not is_domain:
            return "EXECUTOR"
        if is_domain and not is_executor:
            return "DOMAIN"

        # 둘 다 매칭되거나 아무것도 안 매칭 → Tier 2로
        return None


# ── Tier 2: LLM 라우터 ──

LLM_ROUTER_PROMPT = """유저 메시지를 분류하세요.

## 대화 맥락
{conversation_context}

## 현재 상태
활성 에이전트: {active_agent}
마지막 응답 모드: {last_mode}

## 분류
CONTINUE — 이전 작업의 연속 (같은 에이전트에 전달). 다른 대상에 같은 작업도 포함.
EXECUTOR — 조회/진단/변경 수행 요청 ("~해줘", "왜 안 보여?", "비공개해줘")
DOMAIN — 도메인 개념/규칙/설정방법 질문 ("~뭐야?", "차이가?", "가능해?")
REJECT — 범위 밖 (환불, 개인정보, 코드 생성 등)
SELF — 인사, 감사

## 맥락 판단 규칙
- 진단 후 다른 이름만 말하면 → CONTINUE (같은 진단을 다른 대상에)
- "그거", "이전 거", "그것도" → CONTINUE
- 같은 유형의 작업을 다른 대상에 요청 → CONTINUE
- 활성 에이전트가 있고 맥락이 이어지면 → CONTINUE

한 단어만 답하세요: CONTINUE, EXECUTOR, DOMAIN, REJECT, SELF"""


class LLMRouter:
    """Tier 2: LLM에 풀 맥락을 넘겨서 분류."""

    @staticmethod
    def classify(
        message: str,
        conversation_context: str,
        ctx: ConversationContext,
        classifier_agent,
    ) -> str:
        """LLM 기반 분류. 항상 라우트 문자열을 반환."""
        prompt = LLM_ROUTER_PROMPT.format(
            conversation_context=conversation_context or "(대화 없음)",
            active_agent=ctx.active_agent or "없음",
            last_mode=ctx.last_response_mode,
        )

        # classifier agent의 system_prompt를 동적으로 설정
        classifier_agent.system_prompt = prompt

        result = classifier_agent(message)

        # 결과에서 분류 추출
        text = _extract_classification(result)
        print(f"📎 LLM 라우터 분류: {text}")
        return text

    @staticmethod
    def _extract_text(result) -> str:
        """AgentResult에서 텍스트 추출."""
        if hasattr(result, "message") and isinstance(result.message, dict):
            content = result.message.get("content", [])
            texts = [c["text"] for c in content if isinstance(c, dict) and c.get("text")]
            if texts:
                return "\n".join(texts)
        return str(result)


def _extract_classification(result) -> str:
    """AgentResult에서 분류 키워드를 추출."""
    if hasattr(result, "message") and isinstance(result.message, dict):
        content = result.message.get("content", [])
        texts = [c["text"] for c in content if isinstance(c, dict) and c.get("text")]
        if texts:
            raw = "\n".join(texts).strip().upper()
            for keyword in ("CONTINUE", "EXECUTOR", "DOMAIN", "REJECT", "SELF"):
                if keyword in raw:
                    return keyword
            return "SELF"

    raw = str(result).strip().upper()
    for keyword in ("CONTINUE", "EXECUTOR", "DOMAIN", "REJECT", "SELF"):
        if keyword in raw:
            return keyword
    return "SELF"
