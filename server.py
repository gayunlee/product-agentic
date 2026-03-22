"""
로컬 웹 UI 서버. 채팅 형태로 에이전트와 대화.

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

import re
import json

import asyncio
import threading

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from src.agent.product_agent import create_product_agent
from src.agent.memory import save_turn, get_context_for_prompt

app = FastAPI(title="상품 세팅 에이전트 POC")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 세션별 에이전트 (POC에서는 단일 세션)
_agent = None
_flow_guard = None

USE_MEMORY = os.environ.get("USE_MEMORY", "").lower() in ("true", "1", "yes")


def get_agent():
    global _agent, _flow_guard
    if _agent is None:
        _agent, _flow_guard = create_product_agent(use_memory=USE_MEMORY)
        if USE_MEMORY and _flow_guard.memory_session:
            print(f"🧠 AgentCore Memory 활성화 (session: {_flow_guard.memory_session.session_id})")
    return _agent


class ChatRequest(BaseModel):
    message: str
    context: dict | None = None  # { currentPath, role, permissions, masterId?, productPageId? }


class Button(BaseModel):
    type: str  # "navigate" | "confirm" | "action" | "skip"
    label: str
    url: str | None = None
    actionId: str | None = None
    variant: str | None = None  # "primary" | "secondary" | "danger"
    description: str | None = None  # 버튼 아래 설명 텍스트


class StepProgress(BaseModel):
    current: int
    total: int
    label: str
    steps: list[str]


class ChatResponse(BaseModel):
    message: str  # 마크다운 텍스트 (JSON 블록 제거된)
    buttons: list[Button] = []
    mode: str = "idle"  # "guide" | "execute" | "diagnose" | "idle"
    step: StepProgress | None = None


def _parse_agent_response(raw: str) -> dict:
    """에이전트 응답에서 structured blocks 파싱."""
    buttons = []
    meta = {"mode": "idle"}
    message = raw

    # json:buttons 블록 파싱
    btn_match = re.search(r'```json:buttons\s*\n(.*?)\n```', raw, re.DOTALL)
    if btn_match:
        try:
            buttons = json.loads(btn_match.group(1))
        except json.JSONDecodeError:
            pass
        message = message.replace(btn_match.group(0), '').strip()

    # json:meta 블록 파싱
    meta_match = re.search(r'```json:meta\s*\n(.*?)\n```', raw, re.DOTALL)
    if meta_match:
        try:
            meta = json.loads(meta_match.group(1))
        except json.JSONDecodeError:
            pass
        message = message.replace(meta_match.group(0), '').strip()

    return {"message": message, "buttons": buttons, "meta": meta}


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    agent = get_agent()
    try:
        msg = req.message.strip()

        # context를 메시지 앞에 추가
        if req.context:
            ctx_str = (
                f"[컨텍스트: path={req.context.get('currentPath', '')}, "
                f"role={req.context.get('role', '')}, "
                f"masterId={req.context.get('masterId', '')}, "
                f"productPageId={req.context.get('productPageId', '')}]\n"
            )
            full_msg = ctx_str + msg
        else:
            full_msg = msg

        # Memory: 유저 턴 저장
        mem = _flow_guard.memory_session if _flow_guard else None
        if mem:
            try:
                save_turn(mem, "user", msg)
            except Exception as e:
                print(f"⚠️ Memory 저장 실패 (user): {e}")

        result = agent(full_msg)
        raw = str(result)

        # Memory: 어시스턴트 턴 저장
        if mem:
            try:
                save_turn(mem, "assistant", raw[:2000])
            except Exception as e:
                print(f"⚠️ Memory 저장 실패 (assistant): {e}")

        # structured 파싱
        parsed = _parse_agent_response(raw)

        return ChatResponse(
            message=parsed["message"],
            buttons=[Button(**b) for b in parsed["buttons"]],
            mode=parsed["meta"].get("mode", "idle"),
            step=StepProgress(**parsed["meta"]["step"]) if parsed["meta"].get("step") else None,
        )
    except Exception as e:
        return ChatResponse(message=f"오류 발생: {e}")


TOOL_DESCRIPTIONS: dict[str, str] = {
    "search_masters": "마스터 검색 중...",
    "get_master_groups": "마스터 그룹 확인 중...",
    "get_master_detail": "마스터 상세 확인 중...",
    "create_master_group": "마스터 그룹 생성 중...",
    "get_series_list": "시리즈 확인 중...",
    "create_series": "시리즈 생성 중...",
    "get_product_page_list": "상품 페이지 확인 중...",
    "get_product_page_detail": "상품 페이지 상세 확인 중...",
    "get_product_list_by_page": "상품 옵션 확인 중...",
    "create_product_page": "상품 페이지 생성 중...",
    "create_product": "상품 옵션 등록 중...",
    "update_product_display": "상품 노출 설정 중...",
    "update_product_sequence": "상품 순서 설정 중...",
    "update_product_page_status": "상품 페이지 상태 변경 중...",
    "update_main_product_setting": "메인 상품 설정 중...",
    "verify_product_setup": "검증 중...",
}


@app.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    async def event_generator():
        agent = get_agent()

        # context prefix
        msg = req.message.strip()
        if req.context:
            ctx_str = (
                f"[컨텍스트: path={req.context.get('currentPath', '')}, "
                f"role={req.context.get('role', '')}, "
                f"masterId={req.context.get('masterId', '')}, "
                f"productPageId={req.context.get('productPageId', '')}]\n"
            )
            full_msg = ctx_str + msg
        else:
            full_msg = msg

        # Memory: 유저 턴 저장
        mem = _flow_guard.memory_session if _flow_guard else None
        if mem:
            try:
                save_turn(mem, "user", msg)
            except Exception as e:
                print(f"⚠️ Memory 저장 실패 (user): {e}")

        # FlowGuard의 tool_history를 폴링하여 tool 호출을 추적
        result_container: dict = {"result": None, "error": None}
        initial_tool_count = len(_flow_guard.tool_history) if _flow_guard else 0

        def run_agent():
            try:
                result_container["result"] = str(agent(full_msg))
            except Exception as e:
                result_container["error"] = str(e)

        thread = threading.Thread(target=run_agent)
        thread.start()

        seen_tools = initial_tool_count
        while thread.is_alive():
            await asyncio.sleep(0.3)
            if _flow_guard and len(_flow_guard.tool_history) > seen_tools:
                for tool_entry in _flow_guard.tool_history[seen_tools:]:
                    tool_name = tool_entry.get("tool", "") if isinstance(tool_entry, dict) else ""
                    if not tool_name:
                        continue
                    desc = TOOL_DESCRIPTIONS.get(tool_name, f"{tool_name} 처리 중...")
                    yield f"event: tool_start\ndata: {json.dumps({'tool': tool_name, 'message': desc}, ensure_ascii=False)}\n\n"
                    yield f"event: tool_end\ndata: {json.dumps({'tool': tool_name, 'message': desc.replace('중...', '완료')}, ensure_ascii=False)}\n\n"
                seen_tools = len(_flow_guard.tool_history)

        thread.join()

        # 남은 tool 이벤트 flush (스레드 종료 직전에 기록된 것)
        if _flow_guard and len(_flow_guard.tool_history) > seen_tools:
            for tool_entry in _flow_guard.tool_history[seen_tools:]:
                tool_name = tool_entry.get("tool", "") if isinstance(tool_entry, dict) else ""
                if not tool_name:
                    continue
                desc = TOOL_DESCRIPTIONS.get(tool_name, f"{tool_name} 처리 중...")
                yield f"event: tool_start\ndata: {json.dumps({'tool': tool_name, 'message': desc}, ensure_ascii=False)}\n\n"
                yield f"event: tool_end\ndata: {json.dumps({'tool': tool_name, 'message': desc.replace('중...', '완료')}, ensure_ascii=False)}\n\n"

        if result_container["error"]:
            err_msg = f"오류 발생: {result_container['error']}"
            yield f"event: message\ndata: {json.dumps({'message': err_msg, 'buttons': [], 'mode': 'idle', 'step': None}, ensure_ascii=False)}\n\n"
            return

        raw = result_container["result"]

        # Memory: 어시스턴트 턴 저장
        if mem:
            try:
                save_turn(mem, "assistant", raw[:2000])
            except Exception as e:
                print(f"⚠️ Memory 저장 실패 (assistant): {e}")

        parsed = _parse_agent_response(raw)

        step = parsed["meta"].get("step")
        final_data = {
            "message": parsed["message"],
            "buttons": parsed["buttons"],
            "mode": parsed["meta"].get("mode", "idle"),
            "step": step,
        }
        yield f"event: message\ndata: {json.dumps(final_data, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
    const res = await fetch('/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text })
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
