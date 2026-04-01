"""
로컬 웹 UI 서버. 채팅 형태로 에이전트와 대화.

멀티 에이전트 (Strands) — 오케스트레이터 → 수행/도메인/검증.

Usage:
    uv run python server.py
    → http://localhost:8000
"""

from dotenv import load_dotenv

load_dotenv()

# Langfuse OTEL 트레이싱 초기화
import os
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

LANGFUSE_HOST = os.environ.get("LANGFUSE_HOST", "https://us.cloud.langfuse.com")
LANGFUSE_PUBLIC_KEY = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_SECRET_KEY = os.environ.get("LANGFUSE_SECRET_KEY", "")

import base64
_auth = base64.b64encode(f"{LANGFUSE_PUBLIC_KEY}:{LANGFUSE_SECRET_KEY}".encode()).decode()

exporter = OTLPSpanExporter(
    endpoint=f"{LANGFUSE_HOST}/api/public/otel/v1/traces",
    headers={
        "Authorization": f"Basic {_auth}",
    },
)

from opentelemetry import trace
provider = TracerProvider()
provider.add_span_processor(SimpleSpanProcessor(exporter))
trace.set_tracer_provider(provider)
print("Langfuse OTEL tracing initialized")

import os as _os
if _os.environ.get("MOCK_MODE", "").lower() in ("true", "1", "yes"):
    print("⚠️  MOCK MODE — 실제 API 호출 없이 Mock 데이터 반환")
else:
    print("🔴 LIVE MODE — 실제 관리자센터 API 호출")

import json
import re
import asyncio
import queue
import threading

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from src.agents import create_agent_system, AgentSystem
from src.memory import create_memory_session, save_turn, get_context_for_prompt, AgentMemory
from src.vector_router import VectorRouter
from src.wizard import WizardState, create_wizard, WIZARD_ACTIONS
from src.context import SessionManager
from schema.types import build_response, build_error_response, AgentResponse as AgentResponseSchema

app = FastAPI(title="상품 세팅 에이전트 (멀티 에이전트)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 세션 관리 — 단일 매니저로 통합
_sm = SessionManager()
_vector_router = VectorRouter()
_DEFAULT_SESSION = "default"


def _get_memory(session_id: str = _DEFAULT_SESSION) -> AgentMemory | None:
    return _sm.get_or_create_memory(session_id, create_memory_session)


def _get_system(session_id: str = _DEFAULT_SESSION, memory_context: str = "") -> AgentSystem:
    return _sm.get_or_create_system(session_id, create_agent_system, memory_context)


_MOCK_MODE = os.environ.get("MOCK_MODE", "").lower() in ("true", "1", "yes")


class ChatRequest(BaseModel):
    message: str = ""
    button: dict | None = None  # 위저드 버튼 입력: {type, value?, action?}
    wizard_action: str | None = None  # 위저드 시작: "product_page_inactive" 등
    session_id: str | None = None
    context: dict | None = None  # { currentPath, role, permissions, masterId?, productPageId?, token? }


def _to_response(
    message: str,
    buttons: list[dict] | None = None,
    mode: str = "idle",
    step: dict | None = None,
) -> dict:
    """모든 응답 경로의 단일 출구. Phase 1 계약(AgentResponse) 준수."""
    resp = build_response(message, buttons, mode, step, meta={"mock_mode": _MOCK_MODE})
    return resp.model_dump()


def _inject_token(context: dict | None):
    """context에서 토큰 추출 → admin_api에 주입."""
    if context:
        token = context.get("token", "")
        if token:
            import src.tools.admin_api as admin_api
            if admin_api.ADMIN_TOKEN != token:
                print(f"🔑 새 토큰 주입: 길이={len(token)} (이전: {len(admin_api.ADMIN_TOKEN)})")
            admin_api.ADMIN_TOKEN = token
        else:
            print(f"⚠️ context에 token 없음. keys={list(context.keys())}")
    else:
        print("⚠️ context 없음 → .env 토큰 사용")


# Tool 이름 → 한국어 진행 상황 매핑
TOOL_PROGRESS = {
    # 오케스트레이터 Tool
    "diagnose": "🔍 노출 진단 중...",
    "query": "📋 조회 중...",
    "execute": "🔧 실행 요청 처리 중...",
    "guide": "🔗 가이드 생성 중...",
    "ask_domain_expert": "📚 도메인 지식 조회 중...",
    # executor Tool
    "validate": "✅ 사전조건 확인 중...",
    "search_masters": "🔍 오피셜클럽 검색 중...",
    "get_master_detail": "📋 오피셜클럽 상세 조회 중...",
    "get_master_groups": "📋 마스터 그룹 조회 중...",
    "get_series_list": "📋 시리즈 목록 조회 중...",
    "get_product_page_list": "📦 상품 페이지 목록 조회 중...",
    "get_product_page_detail": "📦 상품 페이지 상세 조회 중...",
    "get_product_list_by_page": "📦 상품 옵션 조회 중...",
    "get_community_settings": "🏠 커뮤니티 설정 조회 중...",
    "update_product_display": "⚡ 상품 공개 상태 변경 중...",
    "update_product_page_status": "⚡ 상품 페이지 상태 변경 중...",
    "update_product_page": "⚡ 상품 페이지 수정 중...",
    "update_main_product_setting": "⚡ 메인 상품 설정 변경 중...",
    "navigate": "🔗 페이지 이동 안내 생성 중...",
    "retrieve": "📚 도메인 지식 검색 중...",
    "diagnose_visibility": "🔍 노출 체인 진단 중...",
    "check_prerequisites": "✅ 사전조건 확인 중...",
    "check_idempotency": "✅ 중복 실행 확인 중...",
}


class StreamingCallbackHandler:
    """Tool 호출 시 SSE 이벤트를 큐에 넣는 callback handler."""

    def __init__(self, event_queue: queue.Queue):
        self.event_queue = event_queue
        self.tool_count = 0

    def __call__(self, **kwargs):
        tool_use = kwargs.get("event", {}).get("contentBlockStart", {}).get("start", {}).get("toolUse")
        if tool_use:
            self.tool_count += 1
            tool_name = tool_use["name"]
            progress = TOOL_PROGRESS.get(tool_name, f"🔄 {tool_name} 처리 중...")
            self.event_queue.put({"type": "progress", "message": progress, "tool": tool_name, "count": self.tool_count})


def _extract_text(result) -> str:
    """AgentResult에서 텍스트를 추출."""
    # AgentResult.message가 dict인 경우
    if hasattr(result, 'message') and isinstance(result.message, dict):
        content = result.message.get('content', [])
        texts = [c['text'] for c in content if isinstance(c, dict) and c.get('text')]
        if texts:
            return '\n'.join(texts)
    # str(result)가 dict처럼 보이면 파싱
    s = str(result)
    if s.startswith("{'role'") or s.startswith('{"role"'):
        try:
            import ast
            d = ast.literal_eval(s) if s.startswith("{'") else __import__('json').loads(s)
            content = d.get('content', [])
            texts = [c['text'] for c in content if isinstance(c, dict) and c.get('text')]
            if texts:
                return '\n'.join(texts)
        except Exception:
            pass
    return s


def _extract_buttons(text: str) -> tuple[str, list[dict]]:
    """에이전트 응답에서 ```json:buttons 블록을 파싱하여 버튼 추출 + 텍스트에서 제거."""
    import re

    match = re.search(r'```json:buttons\s*\n(.*?)\n```', text, re.DOTALL)
    if match:
        try:
            buttons = json.loads(match.group(1))
            clean_text = text[:match.start()].rstrip()
            return clean_text, buttons
        except json.JSONDecodeError:
            pass

    return text, []


def _detect_mode(text: str) -> str:
    """응답 텍스트에서 현재 모드를 감지."""
    if any(k in text for k in ['완료되었습니다', '완료했습니다', '처리 완료', '변경 완료', '활성화되었습니다']):
        return 'done'
    if any(k in text for k in ['진단 결과', '노출 진단', '체크 항목', '실패 지점']):
        return 'diagnose'
    if any(k in text for k in ['이동하세요', '페이지로 이동', 'navigate']):
        return 'guide'
    if any(k in text for k in ['처리하시겠', '변경하시겠', '진행하시겠']):
        return 'execute'
    return 'idle'


def _try_parse_agent_response(text: str) -> dict | None:
    """respond Tool의 구조화된 응답(__agent_response__)을 파싱."""
    import re
    # JSON 블록 검색 — __agent_response__: true 포함
    for match in re.finditer(r'\{[^{}]*"__agent_response__"[^{}]*\}', text):
        try:
            data = json.loads(match.group())
            if data.get("__agent_response__"):
                return data
        except json.JSONDecodeError:
            continue
    # nested JSON (buttons 배열 포함)
    for match in re.finditer(r'\{.*?"__agent_response__"\s*:\s*true.*?\}(?=\s|$)', text, re.DOTALL):
        try:
            data = json.loads(match.group())
            if data.get("__agent_response__"):
                return data
        except json.JSONDecodeError:
            continue
    return None


def _call_executor_direct(message: str, system: AgentSystem) -> tuple[str, list, str]:
    """오케스트레이터 없이 executor 직접 호출."""
    from src.agents.response import ExecutorOutput, AgentResponse, render_response
    from src.agents.executor import get_last_harness_response

    system.executor(message)

    # request_action이 호출되었으면 harness 원본 응답을 직접 반환
    harness_resp = get_last_harness_response()
    if harness_resp:
        parsed = json.loads(harness_resp)
        return parsed.get("message", ""), parsed.get("buttons", []), parsed.get("mode", "execute")

    # harness 미경유 → 기존 경로 (structured_output 또는 텍스트)
    try:
        output = system.executor.structured_output(ExecutorOutput, "위 결과를 response_type, summary, data로 정리해줘")
        resp = AgentResponse.from_executor_output(output)
        msg, buttons, mode = render_response(resp)
        return msg, buttons, mode
    except Exception as e:
        print(f"⚠️ structured_output 실패: {e}")
        fallback = _extract_text(system.executor.messages[-1] if system.executor.messages else {})
        return fallback or str(e), [], "error"


def _call_domain_direct(message: str, system: AgentSystem) -> tuple[str, list, str]:
    """오케스트레이터 없이 domain 직접 호출."""
    result = system.domain(message)
    return _extract_text(result), [], "domain"


_FOLLOWUP_PATTERNS = re.compile(r'(고쳐|해결해|수정해|변경해|고쳐줘|해결해줘|수정해줘|변경해줘|해결|수정)', re.IGNORECASE)


def _is_diagnose_followup(message: str, session_ctx) -> bool:
    """진단 후 후속 요청인지 감지."""
    if not hasattr(session_ctx, 'last_diagnose_resolves') or not session_ctx.last_diagnose_resolves:
        return False
    return bool(_FOLLOWUP_PATTERNS.search(message))


def _handle_message(message: str, session_id: str, context: dict | None = None) -> dict:
    """벡터 라우터 → 오케스트레이터 LLM fallback."""
    mem = _get_memory(session_id)
    print(f"📥 msg='{message[:50]}' session={session_id}")

    # 0. 진단 후속 요청 감지 → Harness로 직접 라우팅
    session_ctx = _sm.get(session_id)
    if _is_diagnose_followup(message, session_ctx):
        from src.harness import get_harness
        resolve = session_ctx.last_diagnose_resolves[0]
        if resolve.get("type") == "action":
            harness = get_harness()
            result_json = harness.validate_and_confirm(
                resolve.get("action_id", ""),
                resolve.get("slots", {}),
            )
            parsed = json.loads(result_json)
            session_ctx.last_diagnose_resolves = None
            return _to_response(
                parsed.get("message", ""),
                parsed.get("buttons", []),
                parsed.get("mode", "execute"),
            )
        elif resolve.get("type") == "navigate":
            session_ctx.last_diagnose_resolves = None
            return _to_response(
                f"설정 페이지로 이동해주세요.",
                [{"type": "navigate", "label": resolve.get("label", "이동"), "url": resolve.get("url", "/product/page/list"), "variant": "primary", "clickable": "always"}],
                "guide",
            )

    # 1. Memory에 유저 메시지 저장
    save_turn(mem, "user", message)

    # 2. Memory context 조회
    memory_context = get_context_for_prompt(mem, message)
    system = _get_system(session_id, memory_context)

    # 3. 벡터 라우터 시도 (오케스트레이터 LLM 스킵)
    route, similarity, matched = _vector_router.classify(message)
    if route:
        print(f"📎 벡터 라우팅: {route} (유사도 {similarity:.3f}, 매칭: '{matched[:30]}')")
        if route == "executor":
            msg, buttons, mode = _call_executor_direct(message, system)
        elif route == "domain":
            msg, buttons, mode = _call_domain_direct(message, system)
        else:  # reject
            msg = "죄송합니다, 상품 세팅 관련 요청만 도와드릴 수 있습니다."
            buttons, mode = [], "reject"

        # harness 사이드채널 체크 (LLM이 구조화 응답을 요약했을 때 원본 복원)
        msg, buttons, mode = _check_harness_override(msg, buttons, mode)
        save_turn(mem, "assistant", msg[:500])
        _store_diagnose_resolves(session_id, mode, msg, buttons)
        print(f"📋 응답: mode={mode} buttons={len(buttons)} msg={msg[:100]}")
        return _to_response(msg, buttons, mode)

    # 4. 벡터 유사도 부족 → 오케스트레이터 LLM fallback
    print(f"📎 벡터 유사도 부족 ({similarity:.3f}) → 오케스트레이터 fallback")
    result = system.orchestrator(message)
    result_text = _extract_text(result)

    # 응답 파싱 — diagnose 등 __agent_response__ JSON이 포함될 수 있음
    agent_response = _try_parse_agent_response(result_text)
    if agent_response:
        msg = agent_response.get("message", result_text)
        buttons = agent_response.get("buttons", [])
        mode = agent_response.get("mode", "idle")
    else:
        msg = result_text
        buttons = []
        mode = _detect_mode(result_text)

    # harness 사이드채널 체크
    msg, buttons, mode = _check_harness_override(msg, buttons, mode)

    # 5. Memory에 어시스턴트 응답 저장
    save_turn(mem, "assistant", msg[:500])
    _store_diagnose_resolves(session_id, mode, msg, buttons)

    print(f"📋 응답: mode={mode} buttons={len(buttons)} msg={msg[:100]}")
    return _to_response(msg, buttons, mode)


def _check_harness_override(msg: str, buttons: list, mode: str) -> tuple[str, list, str]:
    """request_action이 호출되었으면 harness 원본 응답으로 교체.

    LLM(executor/orchestrator)이 harness의 구조화 응답을 요약해서
    buttons/mode가 사라지는 문제를 해결.
    """
    from src.agents.executor import get_last_harness_response
    harness_resp = get_last_harness_response()
    if harness_resp:
        try:
            parsed = json.loads(harness_resp)
            print(f"📎 harness 응답 복원: mode={parsed.get('mode')}")
            return (
                parsed.get("message", msg),
                parsed.get("buttons", []),
                parsed.get("mode", "execute"),
            )
        except (json.JSONDecodeError, ValueError):
            pass
    return msg, buttons, mode


def _store_diagnose_resolves(session_id: str, mode: str, msg: str, buttons: list):
    """진단 응답에서 resolve_actions를 세션에 저장."""
    if mode != "diagnose":
        return
    # __agent_response__에서 resolve_actions 추출
    try:
        parsed = _try_parse_agent_response(msg)
        if parsed and parsed.get("resolve_actions"):
            session_ctx = _sm.get(session_id)
            session_ctx.last_diagnose_resolves = parsed["resolve_actions"]
            print(f"📎 진단 resolve 저장: {len(parsed['resolve_actions'])}개")
    except Exception:
        pass


@app.post("/chat")
async def chat(req: ChatRequest):
    try:
        _inject_token(req.context)
        session_id = req.session_id or _DEFAULT_SESSION

        ctx = _sm.get(session_id)

        # 1. 위저드 시작 요청
        if req.wizard_action:
            master_id = (req.context or {}).get("masterId")
            print(f"🧙 위저드 시작: {req.wizard_action} (masterId={master_id})")
            ctx.wizard = create_wizard(req.wizard_action)
            if master_id:
                msg, buttons, mode = ctx.wizard.start_with_master(master_id)
            else:
                msg, buttons, mode = ctx.wizard.start()
            return _to_response(msg, buttons, mode)

        # 2. 위저드 버튼 입력
        if req.button:
            # 2-1. Harness execute_confirmed (액션 실행 확인)
            btn_action = req.button.get("action") if isinstance(req.button, dict) else getattr(req.button, "action", None)
            btn_payload = req.button.get("payload") if isinstance(req.button, dict) else getattr(req.button, "payload", None)
            if btn_action == "execute_confirmed" and btn_payload:
                from src.harness import get_harness
                harness = get_harness()
                result = harness.execute_confirmed(
                    action_id=btn_payload.get("action_id", ""),
                    slots=btn_payload.get("slots", {}),
                )
                return _to_response(
                    result.get("message", ""),
                    result.get("buttons", []),
                    result.get("mode", "done"),
                )

            if ctx.wizard and ctx.wizard.is_active():
                print(f"🧙 위저드 버튼: {req.button}")
                msg, buttons, mode = ctx.wizard.handle(req.button)
                if not ctx.wizard.is_active():
                    ctx.wizard = None
                return _to_response(msg, buttons, mode)
            # 위저드 종료 후 버튼 클릭 → 무시
            return _to_response("이전 작업이 완료되었습니다. 새 작업을 시작해주세요.")

        # 3. 위저드 진행 중 자연어 입력
        if ctx.wizard and ctx.wizard.is_active() and req.message:
            # input_master 스텝이면 검색어로 처리
            if ctx.wizard.step == "input_master":
                print(f"🧙 위저드 검색: {req.message}")
                msg, buttons, mode = ctx.wizard._step_select_master(search_keyword=req.message.strip())
                return _to_response(msg, buttons, mode)
            # 그 외 스텝이면 위저드 보호
            return _to_response(
                "진행 중인 작업이 있어요. 계속하시려면 버튼을 눌러주세요.",
                [{"type": "action", "label": "취소", "action": "cancel", "variant": "ghost"}],
                "wizard",
            )

        # 4. 일반 채팅
        return _handle_message(req.message.strip(), session_id, req.context)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return _to_response(f"오류 발생: {e}", mode="error")


@app.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    """SSE 스트리밍 — 텍스트 청크 + Tool 진행 상황을 실시간 전송."""
    _inject_token(req.context)
    session_id = req.session_id or _DEFAULT_SESSION
    message = req.message.strip()

    mem = _get_memory(session_id)
    save_turn(mem, "user", message)
    memory_context = get_context_for_prompt(mem, message)
    system = _get_system(session_id, memory_context)

    async def event_generator():
        full_text = ""
        tool_count = 0

        try:
            async for event in system.orchestrator.stream_async(message):
                # 텍스트 청크
                data = event.get("data", "")
                if data:
                    full_text += data
                    yield f"event: text\ndata: {json.dumps({'text': data}, ensure_ascii=False)}\n\n"

                # Tool 호출 시작
                raw = event.get("event", {})
                tool_use = raw.get("contentBlockStart", {}).get("start", {}).get("toolUse")
                if tool_use:
                    tool_count += 1
                    tool_name = tool_use["name"]
                    progress = TOOL_PROGRESS.get(tool_name, f"🔄 {tool_name} 처리 중...")
                    yield f"event: progress\ndata: {json.dumps({'message': progress, 'tool': tool_name, 'count': tool_count}, ensure_ascii=False)}\n\n"

        except Exception as e:
            import traceback
            traceback.print_exc()
            yield f"event: error\ndata: {json.dumps({'message': f'오류 발생: {e}'}, ensure_ascii=False)}\n\n"
            return

        # 최종 응답 파싱 (버튼/모드 추출)
        # TODO: Phase 2에서 __agent_response__ 파싱 제거 예정
        agent_response = _try_parse_agent_response(full_text)
        if agent_response:
            msg = agent_response.get("message", full_text)
            buttons = agent_response.get("buttons", [])
            mode = agent_response.get("mode", "idle")
        else:
            msg = full_text
            buttons = []
            mode = _detect_mode(full_text)

        save_turn(mem, "assistant", msg[:500])

        # done 이벤트도 AgentResponse 스키마 준수
        final = _to_response(msg, buttons, mode)
        yield f"event: done\ndata: {json.dumps(final, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/wizard/actions")
async def wizard_actions():
    """사용 가능한 위저드 액션 목록."""
    from src.wizard import _get_engine
    return _get_engine().get_actions()


@app.get("/mode")
async def get_mode():
    """현재 서버 모드 반환."""
    return {"mock": _MOCK_MODE}


@app.post("/reset")
async def reset():
    _sm.clear_all()
    print("🔄 세션 초기화 완료")
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def index():
    return """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>상품 세팅 에이전트</title>
<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f5f5f5; height: 100vh; display: flex; flex-direction: column; }
header { background: #1a1a2e; color: white; padding: 16px 24px; display: flex; justify-content: space-between; align-items: center; }
header h1 { font-size: 18px; font-weight: 600; display: flex; align-items: center; gap: 8px; }
#mode-indicator { font-size: 11px; padding: 2px 10px; border-radius: 10px; font-weight: 700; }
#mode-indicator.mock { background: #ffc107; color: #333; }
#mode-indicator.live { background: #e94560; color: white; }
#reset-btn { background: #e94560; color: white; border: none; padding: 8px 16px; border-radius: 6px; cursor: pointer; font-size: 13px; }
#reset-btn:hover { background: #c73e54; }
#chat-container { flex: 1; overflow-y: auto; padding: 24px; display: flex; flex-direction: column; gap: 16px; }
.msg { max-width: 80%; padding: 12px 16px; border-radius: 12px; line-height: 1.6; white-space: pre-wrap; word-break: break-word; font-size: 14px; }
.msg.user { align-self: flex-end; background: #1a1a2e; color: white; border-bottom-right-radius: 4px; }
.msg.agent { align-self: flex-start; background: white; color: #333; border-bottom-left-radius: 4px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
.msg.agent a { color: #0066cc; }
.msg.agent h1,.msg.agent h2,.msg.agent h3 { margin: 8px 0 4px; font-size: 15px; }
.msg.agent ul,.msg.agent ol { margin: 4px 0; padding-left: 20px; }
.msg.agent code { background: #f0f0f0; padding: 1px 4px; border-radius: 3px; font-size: 13px; }
.msg.agent pre { background: #f0f0f0; padding: 8px; border-radius: 6px; overflow-x: auto; margin: 8px 0; }
.msg.agent pre code { background: none; padding: 0; }
.msg.agent table { border-collapse: collapse; margin: 8px 0; font-size: 13px; }
.msg.agent th,.msg.agent td { border: 1px solid #ddd; padding: 4px 8px; }
.msg.agent th { background: #f5f5f5; }
.msg.system { align-self: center; background: #e8e8e8; color: #666; font-size: 12px; border-radius: 20px; padding: 6px 16px; }
#input-area { padding: 16px 24px; background: white; border-top: 1px solid #e0e0e0; display: flex; gap: 12px; }
#msg-input { flex: 1; padding: 12px 16px; border: 1px solid #ddd; border-radius: 8px; font-size: 14px; outline: none; }
#msg-input:focus { border-color: #1a1a2e; }
#send-btn { background: #1a1a2e; color: white; border: none; padding: 12px 24px; border-radius: 8px; cursor: pointer; font-size: 14px; }
#send-btn:hover { background: #16213e; }
#send-btn:disabled { background: #999; cursor: not-allowed; }
.loading { display: inline-block; }
.loading::after { content: ''; animation: dots 1.5s steps(4) infinite; }
@keyframes dots { 0% { content: ''; } 25% { content: '.'; } 50% { content: '..'; } 75% { content: '...'; } }
#wizard-bar { padding: 8px 24px; background: #fff; border-bottom: 1px solid #e0e0e0; display: flex; gap: 8px; flex-wrap: wrap; }
.wizard-btn { background: #f0f0f0; border: 1px solid #ddd; border-radius: 20px; padding: 6px 14px; font-size: 12px; cursor: pointer; transition: all 0.15s; }
.wizard-btn:hover { background: #1a1a2e; color: white; border-color: #1a1a2e; }
.action-btns { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 8px; }
.action-btn { background: #1a1a2e; color: white; border: none; border-radius: 8px; padding: 8px 16px; font-size: 13px; cursor: pointer; transition: background 0.15s; }
.action-btn:hover { background: #16213e; }
.action-btn:disabled { background: #999; cursor: not-allowed; }
.action-btn.navigate { background: #0066cc; }
.action-btn.navigate:hover { background: #0055aa; }
.action-btn.danger { background: #e94560; }
.action-btn.danger:hover { background: #c73e54; }
.mode-badge { display: inline-block; font-size: 11px; padding: 2px 8px; border-radius: 10px; margin-bottom: 6px; font-weight: 600; }
.mode-badge.diagnose { background: #fff3cd; color: #856404; }
.mode-badge.execute { background: #d4edda; color: #155724; }
.mode-badge.done { background: #cce5ff; color: #004085; }
.mode-badge.wizard { background: #e2d9f3; color: #5a3d8a; }
.mode-badge.guide { background: #d1ecf1; color: #0c5460; }
.mode-badge.error { background: #f8d7da; color: #721c24; }
.mode-badge.reject { background: #f8d7da; color: #721c24; }
</style>
</head>
<body>
<header>
  <h1>상품 세팅 에이전트 <span id="mode-indicator"></span></h1>
  <div style="display:flex;gap:8px;align-items:center;">
    <button id="token-btn" onclick="toggleToken()" style="background:#16213e;color:white;border:none;padding:8px 12px;border-radius:6px;cursor:pointer;font-size:12px;">토큰 설정</button>
    <span id="token-status" style="font-size:11px;color:#aaa;"></span>
    <button id="reset-btn" onclick="resetChat()">새로 시작</button>
  </div>
</header>
<div id="token-area" style="display:none;padding:8px 24px;background:#f0f0f0;border-bottom:1px solid #ddd;">
  <div style="font-size:12px;color:#666;margin-bottom:4px;">관리자센터 sessionStorage에서 토큰을 복사해주세요</div>
  <div style="display:flex;gap:8px;">
    <input id="token-input" type="text" placeholder="eyJhbGci..." style="flex:1;padding:6px 10px;border:1px solid #ccc;border-radius:4px;font-size:12px;font-family:monospace;" />
    <button onclick="saveToken()" style="background:#1a1a2e;color:white;border:none;padding:6px 12px;border-radius:4px;font-size:12px;cursor:pointer;">저장</button>
  </div>
</div>
<div id="wizard-bar"></div>
<div id="chat-container">
  <div class="msg system">상품 세팅을 시작하려면 요청을 입력하세요.</div>
</div>
<div id="input-area">
  <input id="msg-input" type="text" placeholder="메시지 입력..." autocomplete="off" />
  <button id="send-btn" onclick="send()">전송</button>
</div>
<script>
const container = document.getElementById('chat-container');
const input = document.getElementById('msg-input');
const sendBtn = document.getElementById('send-btn');

function getToken() { return localStorage.getItem('agent_token') || ''; }
function toggleToken() {
  const area = document.getElementById('token-area');
  area.style.display = area.style.display === 'none' ? 'block' : 'none';
  document.getElementById('token-input').value = getToken();
}
function saveToken() {
  const token = document.getElementById('token-input').value.trim();
  if (token) {
    localStorage.setItem('agent_token', token);
    document.getElementById('token-status').textContent = '토큰 저장됨';
    document.getElementById('token-area').style.display = 'none';
  }
}
if (getToken()) document.getElementById('token-status').textContent = '토큰 있음';

input.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); } });

function addMsg(text, cls) {
  const div = document.createElement('div');
  div.className = 'msg ' + cls;
  if (cls.includes('agent') && !cls.includes('loading') && typeof marked !== 'undefined') {
    div.innerHTML = marked.parse(text);
  } else {
    div.innerHTML = text.replace(/https?:\\/\\/[^\\s)]+/g, url => `<a href="${url}" target="_blank">${url}</a>`);
  }
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
  return div;
}

function buildContext() {
  const token = getToken();
  return token ? { token } : undefined;
}

// ── 모드 인디케이터 ──
async function loadMode() {
  try {
    const res = await fetch('/mode');
    const data = await res.json();
    const el = document.getElementById('mode-indicator');
    if (data.mock) {
      el.textContent = 'MOCK';
      el.className = 'mock';
      document.querySelector('header').style.background = '#1a1a2e';
    } else {
      el.textContent = 'LIVE';
      el.className = 'live';
      document.querySelector('header').style.background = '#8b0000';
    }
  } catch(e) { console.error('모드 확인 실패:', e); }
}
loadMode();

// ── 위저드 바 로드 ──
async function loadWizardActions() {
  try {
    const res = await fetch('/wizard/actions');
    const actions = await res.json();
    const bar = document.getElementById('wizard-bar');
    bar.innerHTML = actions.map(a =>
      `<button class="wizard-btn" onclick="startWizard('${a.action}')">${a.icon} ${a.label}</button>`
    ).join('');
  } catch(e) { console.error('위저드 로드 실패:', e); }
}
loadWizardActions();

async function startWizard(action) {
  sending = true;
  sendBtn.disabled = true;
  addMsg(`🧙 위저드: ${action}`, 'user');
  const loading = addMsg('🧙 위저드 시작 중...', 'agent loading');
  try {
    const res = await fetch('/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: '', wizard_action: action, context: buildContext() })
    });
    const data = await res.json();
    loading.remove();
    renderResponse(data);
  } catch(e) {
    loading.remove();
    addMsg('오류: ' + e.message, 'system');
  }
  sendBtn.disabled = false;
  sending = false;
  input.focus();
}

async function clickButton(btn) {
  if (btn.disabled) return;
  // navigate 버튼은 URL로 이동
  if (btn.type === 'navigate' && btn.url) {
    window.open(btn.url, '_blank');
    return;
  }
  sending = true;
  sendBtn.disabled = true;
  addMsg(`🔘 ${btn.label || btn.action}`, 'user');
  const loading = addMsg('처리 중...', 'agent loading');
  try {
    const body = { message: '', button: btn, context: buildContext() };
    const res = await fetch('/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    const data = await res.json();
    loading.remove();
    renderResponse(data);
  } catch(e) {
    loading.remove();
    addMsg('오류: ' + e.message, 'system');
  }
  sendBtn.disabled = false;
  sending = false;
  input.focus();
}

function disablePreviousButtons() {
  container.querySelectorAll('.action-btn:not([disabled])').forEach(btn => {
    btn.disabled = true;
    btn.style.opacity = '0.4';
    btn.style.cursor = 'not-allowed';
    btn.onclick = null;
  });
}

function renderResponse(data) {
  disablePreviousButtons();
  const mode = data.mode || 'idle';
  const modeLabels = { diagnose:'진단', execute:'실행 확인', done:'완료', wizard:'위저드', guide:'가이드', error:'오류', reject:'거부', idle:'', select:'선택', launch_check:'런칭 체크', info:'조회' };
  let html = '';
  if (mode !== 'idle' && modeLabels[mode]) {
    html += `<span class="mode-badge ${mode}">${modeLabels[mode]}</span>\\n`;
  }
  if (typeof marked !== 'undefined') {
    html += marked.parse(data.message || '');
  } else {
    html += (data.message || '').replace(/\\n/g, '<br>');
  }
  // 버튼 렌더링
  if (data.buttons && data.buttons.length > 0) {
    html += '<div class="action-btns">';
    data.buttons.forEach((b, i) => {
      const cls = b.action === 'navigate' ? 'navigate' : (b.action === 'cancel' ? 'danger' : '');
      if (b.disabled) {
        html += `<button class="action-btn" disabled style="opacity:0.5;cursor:not-allowed;text-decoration:line-through;">${b.label || b.action}</button>`;
      } else {
        html += `<button class="action-btn ${cls}" onclick='clickButton(${JSON.stringify(b)})'>${b.label || b.action}</button>`;
      }
    });
    html += '</div>';
  }
  const div = document.createElement('div');
  div.className = 'msg agent';
  div.innerHTML = html;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
}

const progressMsgs = [
  '🤔 생각하는 중...',
  '🔍 정보 조회 중...',
  '📚 도메인 지식 검색 중...',
  '✅ 검증 중...',
  '📝 답변 작성 중...',
];

let sending = false;
async function send() {
  if (sending) return;
  const text = input.value.trim();
  if (!text) return;
  sending = true;
  input.value = '';
  disablePreviousButtons();
  addMsg(text, 'user');
  sendBtn.disabled = true;
  const loading = addMsg(progressMsgs[0], 'agent loading');
  let step = 0;
  const progressInterval = setInterval(() => {
    step = (step + 1) % progressMsgs.length;
    loading.innerHTML = progressMsgs[step];
  }, 3000);
  try {
    const token = getToken();
    const body = { message: text, context: buildContext() };
    const res = await fetch('/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    const data = await res.json();
    clearInterval(progressInterval);
    loading.remove();
    renderResponse(data);
  } catch (e) {
    clearInterval(progressInterval);
    loading.remove();
    addMsg('오류가 발생했습니다: ' + e.message, 'system');
  }
  sendBtn.disabled = false;
  sending = false;
  input.focus();
}

async function resetChat() {
  await fetch('/reset', { method: 'POST' });
  container.innerHTML = '<div class="msg system">세션이 초기화되었습니다.</div>';
  input.focus();
}

input.focus();
</script>
</body>
</html>"""


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
