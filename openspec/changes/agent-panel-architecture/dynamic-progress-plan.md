# 진행 상황 메시지

## 현재 상태 (2026-04-01 구현 완료)

### 문제
- `TOOL_PROGRESS` 고정 딕셔너리 → "도메인 지식 검색 중" 같은 부정확한 메시지
- non-streaming `/chat` 엔드포인트라 서버 progress가 프론트에 전달 안 됨

### 해결 (임시)
프론트에서 2초마다 랜덤 영어 메시지 로테이션 (Claude Code 스타일).
서버가 실제로 뭘 하는지와 무관한 가벼운 메시지.

```
Thinking... → Buzzing... → Rummaging... → Almost there...
```

- `server.py` 인라인 HTML: `progressMsgs` 배열 + `randomProgress()` + `setInterval(2000)`
- `web/src/useAgentChat.ts`: `LOADING_MESSAGES` + `getRandomLoadingText()` + `setInterval(2000)`
- 서버 `_build_progress()`: 명확한 tool(search_masters, request_action 등)은 구체적, 나머지 랜덤 fallback (스트리밍 전환 시 사용)

---

## 후속: 스트리밍 전환 → 진짜 progress 표시

`/chat` → `/chat/stream` (SSE) 전환 시 서버가 tool 호출마다 실시간 progress 전달 가능.

### Before (현재)
```
프론트 요청 → [Thinking... Buzzing... Rummaging...] → 응답 수신
                 ↑ 프론트 자체 랜덤 (서버와 무관)
```

### After (스트리밍 전환 후)
```
프론트 요청 → SSE event: "🔍 '조조형우' 검색 중..." → "📦 상품페이지 조회 중..." → 응답 수신
                 ↑ 서버가 실제 tool 호출 기반으로 전송
```

### 스코프
- [ ] `useAgentChat.ts`에서 `sendMessage` → `streamMessage` 전환
- [ ] `onProgress` 핸들러로 서버 progress 메시지 표시
- [ ] 프론트 자체 랜덤 fallback 제거
- [ ] SSE 이벤트에서 tool_input 접근 가능 여부 확인 (Strands SDK)
- [ ] 8000 인라인 HTML도 EventSource 기반으로 전환
