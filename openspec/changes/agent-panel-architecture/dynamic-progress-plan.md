# 동적 진행 상황 메시지 — Tool 파라미터 기반

## 문제

현재 `TOOL_PROGRESS` 딕셔너리가 tool_name → 고정 문자열 매핑이라:
- 실제 파라미터와 무관한 메시지 표시 ("도메인 지식 검색 중" — 실제로는 검색 안 함)
- 모든 호출이 동일 메시지 → 단계 전환이 안 느껴짐
- 유저가 "지금 뭘 하고 있는지" 파악 불가

## 제안

Tool 호출 시 **tool_name + tool_input(파라미터)**을 읽어서 동적 메시지 생성.

### Before (고정)
```
🔍 오피셜클럽 검색 중...
📦 상품 페이지 목록 조회 중...
🔍 노출 체인 진단 중...
```

### After (동적, 파라미터 기반)
```
🔍 '에이전트 테스트 오피셜 클럽' 검색 중...
📦 상품페이지 5개 조회 중...
🔗 웹링크 설정 확인 중...
⚡ 코드 148 히든 해제 요청 검증 중...
📊 진단 결과 정리 중...
```

### 단계별 전환 느낌
```
[1/4] 🔍 '조조형우' 오피셜클럽 검색 중...
[2/4] 📦 상품페이지 목록 조회 중...
[3/4] 🔗 웹링크 설정 확인 중...
[4/4] 📊 진단 결과 정리 중...
```

## 구현

### 서버 (`server.py` StreamingCallbackHandler)

현재 `contentBlockStart`에서 tool_name만 읽음:
```python
tool_use = raw.get("contentBlockStart", {}).get("start", {}).get("toolUse")
if tool_use:
    tool_name = tool_use["name"]
    progress = TOOL_PROGRESS.get(tool_name, f"🔄 {tool_name} 처리 중...")
```

변경: tool_input도 읽어서 동적 메시지 생성:
```python
tool_use = raw.get("contentBlockStart", {}).get("start", {}).get("toolUse")
if tool_use:
    tool_name = tool_use["name"]
    tool_input = tool_use.get("input", {})  # 파라미터
    progress = _build_progress(tool_name, tool_input, self.tool_count)
```

### 메시지 빌더 (`_build_progress`)

```python
def _build_progress(tool_name: str, tool_input: dict, count: int) -> str:
    """tool_name + 파라미터로 동적 진행 메시지 생성."""

    if tool_name == "search_masters":
        keyword = tool_input.get("search_keyword", "")
        return f"🔍 '{keyword}' 오피셜클럽 검색 중..."

    if tool_name == "get_product_page_list":
        master_id = tool_input.get("master_id", "")
        return f"📦 상품페이지 목록 조회 중... (masterId={master_id})"

    if tool_name == "diagnose_visibility":
        master_id = tool_input.get("master_id", "")
        return f"🔍 노출 체인 진단 중... (masterId={master_id})"

    if tool_name == "request_action":
        action_id = tool_input.get("action_id", "")
        labels = {
            "update_product_display": "상품 공개 상태 변경",
            "update_product_page_status": "상품페이지 상태 변경",
            "update_product_page_hidden": "히든 처리/해제",
            "update_main_product_setting": "메인 상품 설정 변경",
        }
        label = labels.get(action_id, action_id)
        return f"⚡ {label} 검증 중..."

    if tool_name == "navigate":
        return "🔗 페이지 이동 안내 생성 중..."

    if tool_name == "retrieve":
        return "📚 관련 지식 검색 중..."

    # 오케스트레이터 tool (하위 에이전트 호출)
    orch_labels = {
        "diagnose": "🔍 노출 진단 시작...",
        "query": "📋 조회 시작...",
        "execute": "🔧 실행 요청 처리 시작...",
        "guide": "🔗 가이드 생성 시작...",
        "ask_domain_expert": "📚 도메인 지식 질의 시작...",
    }
    if tool_name in orch_labels:
        return orch_labels[tool_name]

    return f"🔄 {tool_name} 처리 중..."
```

### 프론트 (`web/src/AgentPanel.tsx`)

현재 progress 이벤트를 받아서 표시하고 있으므로, 서버가 동적 메시지를 보내면 자동 반영.
카운터 표시(`[1/4]`)는 총 tool 수를 모르니까 — 단순히 순번만 표시하거나, 완료 후 "✅ 완료"로 전환.

## 확인 필요

- `contentBlockStart`의 `toolUse`에 `input`이 포함되는지 (Strands SDK SSE 이벤트 구조)
  - 포함 안 되면 `contentBlockDelta`에서 input JSON을 파싱해야 할 수 있음
  - 이 경우 메시지가 약간 지연될 수 있음 (input streaming 완료 후)
- 오케스트레이터 tool(diagnose, execute 등)은 파라미터가 단순 문자열이라 동적 메시지 효과가 적음
  - executor 내부 tool이 더 구체적 (search_masters, get_product_page_list 등)

## 스코프

- [ ] `_build_progress` 함수 구현
- [ ] `StreamingCallbackHandler` 수정
- [ ] SSE 이벤트에서 tool_input 접근 가능 여부 확인
- [ ] 프론트 변경 불필요 (서버 메시지만 변경)
