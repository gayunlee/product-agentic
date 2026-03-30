# Phase 2 — 채팅 안정성

## 목표

Phase 1에서 정의한 계약(AgentResponse)을 서버가 **항상, 확실하게** 지키도록 내부를 정리한다.

---

## 1. SessionContext 통합

### 현재: 4곳 분산

```python
_sessions: dict[str, AgentSystem]       # 에이전트 인스턴스
_memories: dict[str, AgentMemory]       # 메모리 세션
_wizards: dict[str, WizardState]        # 위저드 상태
# + orchestrator 내부 conversation history (암묵적)
```

키가 하나라도 안 맞으면 상태 불일치. 세션 정리 시 누락 가능.

### 변경: 단일 SessionContext

```python
@dataclass
class SessionContext:
    session_id: str
    system: AgentSystem
    memory: AgentMemory | None
    wizard: WizardState | None = None
    created_at: datetime = field(default_factory=datetime.now)

_sessions: dict[str, SessionContext] = {}
```

- 생성/조회/삭제가 한 곳에서
- 위저드 시작/종료도 `ctx.wizard = ...` / `ctx.wizard = None`
- reset 시 `_sessions.clear()` 한 번이면 전부 정리

---

## 2. 응답 파이프라인 정리

### 현재: 3가지 경로, 각각 다른 방식

```
경로 1: 위저드 → wizard.handle() → (msg, buttons, mode) 튜플
경로 2: 벡터 라우팅 → _call_executor_direct → structured_output → render_response
경로 3: 오케스트레이터 → LLM 텍스트 → _try_parse_agent_response (정규식) → fallback _detect_mode
```

경로 3이 불안정의 근원. LLM이 JSON을 깨뜨리거나 빠뜨리면 heuristic fallback.

### 변경: 모든 경로가 AgentResponse를 반환

```python
def build_response(
    message: str,
    buttons: list[dict] | None = None,
    mode: str = "idle",
    step: dict | None = None,
    meta: dict | None = None,
) -> dict:
    """Phase 1 계약에 맞는 응답 생성. 모든 경로가 이걸 통과."""
    return {
        "message": message,
        "buttons": _apply_clickable_defaults(buttons or []),
        "mode": mode,
        "step": step,
        "meta": meta or {},
    }

def _apply_clickable_defaults(buttons: list[dict]) -> list[dict]:
    """clickable 기본값 적용."""
    for btn in buttons:
        if "clickable" not in btn:
            btn["clickable"] = "always" if btn.get("type") == "navigate" else "once"
    return buttons
```

### 경로별 변경

**경로 1 (위저드):**
```python
# 변경 전
return msg, buttons, mode

# 변경 후
return build_response(msg, buttons, mode, step=self._get_step_progress())
```

**경로 2 (벡터 라우팅):**
```python
# 변경 전
msg, buttons, mode = _call_executor_direct(message, system)
return ChatResponse(message=msg, buttons=buttons, mode=mode)

# 변경 후
resp = _call_executor_direct(message, ctx)
return resp  # 이미 build_response로 생성됨
```

**경로 3 (오케스트레이터):**
```python
# 변경 전: LLM 텍스트에서 __agent_response__ 정규식 추출
agent_response = _try_parse_agent_response(result_text)

# 변경 후: orchestrator tool이 직접 build_response 호출
# → 오케스트레이터의 diagnose/query/execute/guide tool이
#    render_response_json 대신 build_response를 반환
# → server.py는 tool 결과를 그대로 전달
```

### __agent_response__ 제거 계획

1. orchestrator의 각 tool (diagnose, query, execute, guide)이 `build_response()`로 응답 생성
2. tool 결과를 서버가 직접 받아서 반환 (LLM 텍스트 파싱 불필요)
3. `_try_parse_agent_response()`, `_detect_mode()`, `_extract_buttons()` 삭제
4. 오케스트레이터 LLM이 직접 답변하는 경우 (인사 등)만 fallback으로 `build_response(result_text)`

---

## 3. 에러 전파 명시화

### 현재: 조용히 삼키는 곳들

| 위치 | 현재 | 문제 |
|------|------|------|
| `_step_confirm()` cascading check | `except Exception: pass` | 경고 없이 진행 |
| `_execute()` 위저드 실행 | `except → reset + 에러 메시지` | 재시도 불가 |
| `_call_executor_direct` structured_output | `except → fallback 텍스트` | 파싱 실패 숨김 |
| `_extract_text` | `except: pass` | 추출 실패 숨김 |

### 변경: 에러도 AgentResponse로

```python
def build_error_response(
    error: str,
    recoverable: bool = False,
    retry_action: str | None = None,
) -> dict:
    buttons = []
    if recoverable and retry_action:
        buttons.append({
            "type": "action",
            "label": "다시 시도",
            "action": retry_action,
            "clickable": "once",
            "variant": "primary",
        })
    return build_response(
        message=f"⚠️ {error}",
        buttons=buttons,
        mode="error",
    )
```

**cascading check 실패:**
```python
# 변경 전
except Exception:
    pass  # 경고 없이 진행

# 변경 후
except Exception as e:
    warning = "⚠️ 연쇄 효과 확인에 실패했습니다. 주의해서 진행해주세요."
    # 경고를 confirm 메시지에 포함하되 실행은 허용
```

**위저드 실행 실패:**
```python
# 변경 전
except Exception as e:
    self.reset()
    return f"⚠️ 실행 중 오류: {e}", [], "error"

# 변경 후
except Exception as e:
    # 리셋하지 않고 재시도 가능하게
    return build_response(
        message=f"⚠️ 실행 중 오류: {e}",
        buttons=[
            {"type": "action", "label": "다시 시도", "action": "execute", ...},
            {"type": "action", "label": "취소", "action": "cancel", ...},
        ],
        mode="error",
        step=self._get_step_progress(),
    )
```

---

## 4. SSE 스트리밍 정리

### 현재
- `/chat`은 동기, `/chat/stream`은 SSE
- 둘의 응답 형태가 다름 (ChatResponse vs SSE 이벤트)
- done 이벤트에서 다시 `_try_parse_agent_response` 파싱

### 변경
- 둘 다 최종 응답은 동일한 `build_response()` 통과
- `/chat` → `build_response()` 결과를 JSON 반환
- `/chat/stream` → done 이벤트의 data가 `build_response()` 결과

```python
# SSE done 이벤트
final = build_response(msg, buttons, mode, step, meta)
yield f"event: done\ndata: {json.dumps(final, ensure_ascii=False)}\n\n"
```

---

## 5. 구현 순서

| # | 작업 | 파일 | 의존 |
|---|------|------|------|
| 1 | SessionContext 정의 | `src/context.py` | - |
| 2 | server.py 세션 관리 교체 | `server.py` | #1 |
| 3 | build_response 함수 | `src/agents/response.py` | Phase 1 스키마 |
| 4 | 위저드 응답을 build_response로 | `src/wizard.py` | #3 |
| 5 | executor direct 응답을 build_response로 | `server.py` | #3 |
| 6 | orchestrator tool 응답 리팩토링 | `src/agents/orchestrator.py` | #3 |
| 7 | __agent_response__ 파싱 제거 | `server.py` | #6 |
| 8 | 에러 전파 수정 | `wizard.py`, `server.py` | #3 |
| 9 | SSE done 이벤트 통일 | `server.py` | #3 |
