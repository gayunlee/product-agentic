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

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from src.agents import create_orchestrator

app = FastAPI(title="상품 세팅 에이전트 (멀티 에이전트)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 세션별 오케스트레이터 관리
_sessions: dict[str, object] = {}
_DEFAULT_SESSION = "default"


def _get_orchestrator(session_id: str = _DEFAULT_SESSION):
    if session_id not in _sessions:
        _sessions[session_id] = create_orchestrator(session_id=session_id)
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


def _handle_message(message: str, session_id: str, context: dict | None = None) -> ChatResponse:
    """오케스트레이터를 호출하고 결과를 ChatResponse로 변환."""
    orchestrator = _get_orchestrator(session_id)

    print(f"📥 msg='{message[:50]}' session={session_id}")
    result = orchestrator(message)
    response_text = str(result)

    return ChatResponse(message=response_text)


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    try:
        _inject_token(req.context)
        session_id = req.session_id or _DEFAULT_SESSION
        return _handle_message(req.message.strip(), session_id, req.context)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return ChatResponse(message=f"오류 발생: {e}")


@app.post("/reset")
async def reset():
    global _sessions
    _sessions.clear()
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

let sending = false;
async function send() {
  if (sending) return;
  const text = input.value.trim();
  if (!text) return;
  sending = true;
  input.value = '';
  addMsg(text, 'user');
  sendBtn.disabled = true;
  const loading = addMsg('생각 중', 'agent loading');
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
    loading.remove();
    addMsg(data.message, 'agent');
  } catch (e) {
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
