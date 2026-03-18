"""
로컬 웹 UI 서버. 채팅 형태로 에이전트와 대화.

Usage:
    uv run python server.py
    → http://localhost:8000
"""

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from src.agent.product_agent import create_product_agent

app = FastAPI(title="상품 세팅 에이전트 POC")

# 세션별 에이전트 (POC에서는 단일 세션)
_agent = None
_flow_guard = None


def get_agent():
    global _agent, _flow_guard
    if _agent is None:
        _agent, _flow_guard = create_product_agent()
    return _agent


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    response: str


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    agent = get_agent()
    try:
        # Phase 전환 명령어 처리
        msg = req.message.strip()
        if _flow_guard and msg.startswith("/phase "):
            phase = msg.split("/phase ")[-1].strip()
            _flow_guard.advance_to(phase)
            return ChatResponse(response=f"Phase를 '{phase}'로 전환했습니다. 현재 수집된 데이터: {_flow_guard.collected_data}")

        result = agent(msg)

        # Phase 상태 + 수집 데이터를 응답에 포함
        phase_info = ""
        if _flow_guard:
            phase_info = f"\n\n---\n📍 Phase: `{_flow_guard.current_phase}` | 데이터: {list(_flow_guard.collected_data.keys())}"

        return ChatResponse(response=str(result) + phase_info)
    except Exception as e:
        return ChatResponse(response=f"오류 발생: {e}")


@app.post("/reset")
async def reset():
    global _agent, _flow_guard
    _agent = None
    _flow_guard = None
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def index():
    return """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>상품 세팅 에이전트</title>
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
  <h1>어스플러스 상품 세팅 에이전트</h1>
  <button id="reset-btn" onclick="resetChat()">새로 시작</button>
</header>
<div id="chat-container">
  <div class="msg system">상품 세팅을 시작하려면 마스터 이름이나 요청을 입력하세요.</div>
</div>
<div id="input-area">
  <input id="msg-input" type="text" placeholder="메시지 입력..." autocomplete="off" />
  <button id="send-btn" onclick="send()">전송</button>
</div>
<script>
const container = document.getElementById('chat-container');
const input = document.getElementById('msg-input');
const sendBtn = document.getElementById('send-btn');

input.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } });

function addMsg(text, cls) {
  const div = document.createElement('div');
  div.className = 'msg ' + cls;
  div.innerHTML = text.replace(/https?:\\/\\/[^\\s)]+/g, url => `<a href="${url}" target="_blank">${url}</a>`);
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
  return div;
}

async function send() {
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  addMsg(text, 'user');
  sendBtn.disabled = true;
  const loading = addMsg('생각 중', 'agent loading');
  try {
    const res = await fetch('/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text })
    });
    const data = await res.json();
    loading.remove();
    addMsg(data.response, 'agent');
  } catch (e) {
    loading.remove();
    addMsg('오류가 발생했습니다: ' + e.message, 'system');
  }
  sendBtn.disabled = false;
  input.focus();
}

async function resetChat() {
  await fetch('/reset', { method: 'POST' });
  container.innerHTML = '<div class="msg system">세션이 초기화되었습니다. 새로운 상품 세팅을 시작해주세요.</div>';
  input.focus();
}

input.focus();
</script>
</body>
</html>"""


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
