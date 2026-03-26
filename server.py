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

import json
import asyncio
import queue
import threading

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from src.agents import create_agent_system, AgentSystem

app = FastAPI(title="상품 세팅 에이전트 (멀티 에이전트)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 세션별 에이전트 시스템 + 활성 에이전트 관리
_sessions: dict[str, AgentSystem] = {}
_active_agent: dict[str, str] = {}  # session_id → "executor" | "domain" | None
_DEFAULT_SESSION = "default"


def _get_system(session_id: str = _DEFAULT_SESSION) -> AgentSystem:
    if session_id not in _sessions:
        _sessions[session_id] = create_agent_system()
    return _sessions[session_id]


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    context: dict | None = None  # { currentPath, role, permissions, masterId?, productPageId?, token? }


class ChatResponse(BaseModel):
    message: str
    buttons: list[dict] = []
    mode: str = "idle"


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
    "ask_executor": "🔧 수행 에이전트에게 요청 중...",
    "ask_domain_expert": "📚 도메인 지식 조회 중...",
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


def _handle_message(message: str, session_id: str, context: dict | None = None) -> ChatResponse:
    """분류 → 에이전트 직접 호출 → 포맷팅 레이어. 대화 맥락 유지."""
    from src.agents.response import ExecutorOutput, AgentResponse, render_response

    system = _get_system(session_id)
    active = _active_agent.get(session_id)
    print(f"📥 msg='{message[:50]}' session={session_id} active={active}")

    # 0. 활성 에이전트가 있으면 classifier 안 거치고 직접 전달
    if active == "executor":
        classification = "EXECUTOR"
        print(f"📎 활성 에이전트 유지: {classification}")
    elif active == "domain":
        classification = "DOMAIN"
        print(f"📎 활성 에이전트 유지: {classification}")
    else:
        # 1. 분류 (LLM — 한 단어만 반환)
        classify_result = system.classifier(message)
        classification = _extract_text(classify_result).strip().upper()
        print(f"📎 분류: {classification}")

    # 2. 분류에 따라 에이전트 직접 호출

    if "EXECUTOR" in classification:
        # 수행 에이전트: Tool 호출 → structured_output → 포맷팅
        _active_agent[session_id] = "executor"
        system.executor(message)
        try:
            output = system.executor.structured_output(ExecutorOutput, "위 결과를 response_type, summary, data로 정리해줘")
            resp = AgentResponse.from_executor_output(output)
            msg, buttons, mode = render_response(resp)
            # 완료/에러/거부면 활성 에이전트 해제
            if mode in ("complete", "error", "reject"):
                _active_agent.pop(session_id, None)
            return ChatResponse(message=msg, buttons=buttons, mode=mode)
        except Exception as e:
            print(f"⚠️ structured_output 실패: {e}")
            fallback = _extract_text(system.executor.messages[-1] if system.executor.messages else {})
            return ChatResponse(message=fallback or str(e))

    elif "DOMAIN" in classification:
        # 도메인 에이전트: 직접 응답
        _active_agent[session_id] = "domain"
        result = system.domain(message)
        # 도메인 응답 후 활성 해제 (단발성)
        _active_agent.pop(session_id, None)
        return ChatResponse(message=_extract_text(result))

    elif "REJECT" in classification:
        # 범위 밖 거부
        return ChatResponse(
            message="죄송합니다, 상품 세팅 관련 요청만 도와드릴 수 있습니다.\n\n"
                    "도움이 필요하시면 다음과 같이 요청해보세요:\n"
                    "- 상품 페이지 조회/수정\n"
                    "- 노출 문제 진단\n"
                    "- 도메인 개념 질문",
            mode="reject",
        )

    else:
        # SELF — 직접 답변 (인사, 맥락 등)
        # classifier는 분류만 하므로 별도 응답 생성
        return ChatResponse(
            message="안녕하세요! 관리자센터 상품 세팅 AI 어시스턴트입니다.\n\n"
                    "다음과 같은 작업을 도와드릴 수 있습니다:\n"
                    "- 📊 상품/상품페이지 노출 문제 진단\n"
                    "- ⚡ 상품 공개/비공개/히든 처리\n"
                    "- 🔗 관리자센터 페이지 이동 안내\n"
                    "- 📚 도메인 개념 설명\n\n"
                    "무엇을 도와드릴까요?",
            mode="idle",
        )


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    try:
        _inject_token(req.context)
        session_id = req.session_id or _DEFAULT_SESSION
        result = _handle_message(req.message.strip(), session_id, req.context)
        return result
    except Exception as e:
        import traceback
        traceback.print_exc()
        return ChatResponse(message=f"오류 발생: {e}")


@app.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    """SSE 스트리밍 — 진행 상황을 실시간으로 보여줌."""
    _inject_token(req.context)
    session_id = req.session_id or _DEFAULT_SESSION
    event_queue: queue.Queue = queue.Queue()

    async def event_generator():
        # 에이전트를 별도 스레드에서 실행
        result_holder = {"result": None, "error": None}

        def run_agent():
            try:
                orchestrator = _get_orchestrator(session_id)
                result = orchestrator(req.message.strip())
                result_holder["result"] = _extract_text(result)
            except Exception as e:
                result_holder["error"] = str(e)
            finally:
                event_queue.put({"type": "done"})

        thread = threading.Thread(target=run_agent)
        thread.start()

        # 큐에서 이벤트를 읽어 SSE로 전송
        while True:
            try:
                event = await asyncio.get_event_loop().run_in_executor(None, event_queue.get, True, 0.5)
            except queue.Empty:
                continue

            if event["type"] == "done":
                # 최종 응답 전송
                if result_holder["error"]:
                    final = {"message": f"오류 발생: {result_holder['error']}"}
                else:
                    final = {"message": result_holder["result"]}
                yield f"event: message\ndata: {json.dumps(final, ensure_ascii=False)}\n\n"
                break
            elif event["type"] == "progress":
                yield f"event: progress\ndata: {json.dumps({'message': event['message'], 'tool': event['tool']}, ensure_ascii=False)}\n\n"

        thread.join(timeout=5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/reset")
async def reset():
    global _sessions, _active_agent
    _sessions.clear()
    _active_agent.clear()
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
header h1 { font-size: 18px; font-weight: 600; }
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
</style>
</head>
<body>
<header>
  <h1>상품 세팅 에이전트 (멀티 에이전트)</h1>
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
    const body = { message: text };
    if (token) body.context = { token };
    const res = await fetch('/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    const data = await res.json();
    clearInterval(progressInterval);
    loading.remove();
    addMsg(data.message, 'agent');
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
