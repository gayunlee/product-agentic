# Phase 1 — 프론트 계약 + 패널 인터페이스

## 1. 응답 스키마

서버가 내려주는 모든 응답은 이 형태를 따른다. 예외 없음.

```json
{
  "message": "마크다운 텍스트",
  "buttons": [],
  "mode": "idle",
  "step": null,
  "meta": {}
}
```

### AgentResponse

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| message | string | O | 마크다운 텍스트 |
| buttons | AgentButton[] | O | 빈 배열 가능 |
| mode | ChatMode | O | 현재 상태 |
| step | StepProgress \| null | X | 위저드 진행 상태 (위저드 아닐 때 null) |
| meta | object | X | mock_mode 등 부가 정보 |

### ChatMode

```
idle        — 기본 대화
diagnose    — 진단 결과
guide       — 페이지 이동 안내
execute     — 실행 확인 대기
done        — 작업 완료
wizard      — 위저드 진행 중
launch_check — 런칭 체크 결과
select      — 선택 대기 (채팅 내)
error       — 오류
reject      — 거부
```

프론트는 mode에 따라:
- border 색상 결정
- 입력 활성/비활성 결정 (wizard → 입력 비활성)
- 모드 뱃지 표시

---

## 2. 버튼 스키마

### AgentButton

```typescript
interface AgentButton {
  type: 'select' | 'action' | 'navigate'
  label: string

  // type별 필드
  value?: string          // select: 선택 값
  action?: string         // action: 'execute' | 'cancel' | 'back' | 커스텀
  url?: string            // navigate: 이동 URL

  // 동작 제어
  clickable: 'once' | 'always'
  variant: 'primary' | 'secondary' | 'ghost' | 'danger'

  // 선택적
  description?: string    // 버튼 아래 부연 설명
}
```

### clickable 규칙

| type | 기본 clickable | 이유 |
|------|---------------|------|
| select | once | 선택 후 되돌릴 수 없음 (서버 상태 변경) |
| action | once | execute/cancel 등 한 번만 실행 |
| navigate | always | 페이지 이동은 반복 가능 |

서버가 명시적으로 `clickable`을 보내면 기본값 오버라이드.

### 프론트 렌더링 규칙

1. `clickable: 'once'` 버튼 → 클릭 후 **해당 버튼만** disabled (전체 메시지 X)
2. `clickable: 'always'` 버튼 → 항상 활성 (이전 메시지여도)
3. 같은 메시지 내 once 버튼 중 하나 클릭 → **같은 메시지의 모든 once 버튼** disabled
   - 이유: select 그룹에서 하나 고르면 나머지도 비활성화
4. navigate 버튼은 독립 — once 버튼 비활성화와 무관

**예시:**
```
메시지: "오피셜클럽을 선택하세요"
버튼: [조조형우 (select/once)] [봄날 (select/once)] [취소 (action/once)]

유저가 "조조형우" 클릭 →
- 조조형우, 봄날, 취소 전부 disabled
- 다음 메시지로 진행

메시지: "런칭 체크 완료"
버튼: [📄 월간 투자 리포트 (navigate/always)] [설정 관리 (navigate/always)]

유저가 "월간 투자 리포트" 클릭 →
- 페이지 이동
- 버튼 여전히 활성 (다시 클릭 가능)
```

---

## 3. 위저드 스텝 진행 상태

### StepProgress

```typescript
interface StepProgress {
  current: number        // 0-indexed 현재 스텝
  total: number          // 전체 스텝 수
  label: string          // 현재 스텝 이름 ("클럽 선택")
  steps: string[]        // 전체 스텝 이름 배열
}
```

서버가 위저드 응답마다 step을 내려준다:

```json
{
  "message": "오피셜클럽을 선택하세요",
  "buttons": [...],
  "mode": "wizard",
  "step": {
    "current": 0,
    "total": 4,
    "label": "클럽 선택",
    "steps": ["클럽 선택", "페이지 선택", "확인", "실행"]
  }
}
```

프론트의 StepIndicator가 이 데이터를 그대로 렌더링.

---

## 4. SSE 이벤트 스키마

스트리밍 응답 (`/chat/stream`)의 이벤트 타입:

| 이벤트 | data | 설명 |
|--------|------|------|
| `text` | `{ text: string }` | 텍스트 청크 (실시간 표시) |
| `progress` | `{ message: string, tool: string, count: number }` | Tool 호출 진행 상황 |
| `done` | `AgentResponse` | 최종 응답 (위 스키마와 동일) |
| `error` | `{ message: string, code?: string }` | 에러 |

**핵심:** `done` 이벤트가 AgentResponse 전체를 내려주므로, 프론트는 스트리밍 중에는 text/progress만 표시하다가 done에서 최종 응답으로 교체.

---

## 5. AgentPanel Props 인터페이스

```typescript
interface AgentPanelProps {
  /** 에이전트 서버 URL */
  apiUrl: string

  /** 인증 토큰 조회 함수 (매 요청마다 호출) */
  getToken: () => string

  /** 페이지 이동 핸들러 (navigate 버튼 클릭 시) */
  onNavigate: (url: string) => void

  /** 현재 페이지 컨텍스트 (선택) */
  context?: {
    currentPath?: string
    masterId?: string
    productPageId?: string
  }

  /** 패널 열림/닫힘 제어 (선택) */
  open?: boolean
  onOpenChange?: (open: boolean) => void

  /** 테마 (선택) */
  theme?: 'light' | 'dark'
}
```

### 관리자센터 사용 예시

```tsx
import { AgentPanel } from '@us/agent-panel'

function AdminLayout() {
  const navigate = useNavigate()
  const { masterId } = useParams()

  return (
    <div>
      <Outlet />
      <AgentPanel
        apiUrl={import.meta.env.VITE_AGENT_URL}
        getToken={() => sessionStorage.getItem('accessToken') || ''}
        onNavigate={(url) => navigate(url)}
        context={{ masterId }}
      />
    </div>
  )
}
```

---

## 6. 서버 API 엔드포인트 정리

현재 엔드포인트를 계약에 맞게 정리:

### POST /chat
- Request: `{ message?, button?, wizard_action?, session_id?, context? }`
- Response: `AgentResponse` (항상 동일 스키마)
- 위저드, 버튼, 채팅 모두 이 하나의 엔드포인트

### POST /chat/stream
- Request: 동일
- Response: SSE (text → progress → done)
- `done` 이벤트의 data = `AgentResponse`

### GET /wizard/actions
- Response: `WizardAction[]`
```typescript
interface WizardAction {
  action: string      // "launch_check"
  label: string       // "런칭 체크"
  description?: string
  icon?: string
}
```

### POST /reset
- 세션 초기화

---

## 7. 구현 작업 목록

| # | 작업 | 위치 | 설명 |
|---|------|------|------|
| 1 | JSON Schema 작성 | `schema/` | AgentResponse, AgentButton, StepProgress, SSE 이벤트 |
| 2 | 서버 응답 파이프라인 수정 | `server.py` | 모든 응답을 AgentResponse 스키마로 통일, `__agent_response__` 파싱 제거 |
| 3 | 버튼에 clickable 필드 추가 | `response.py`, `wizard.py` | 기본값 적용 + 명시적 오버라이드 |
| 4 | 위저드에 step 정보 추가 | `wizard.py` | 각 응답에 StepProgress 포함 |
| 5 | SSE done 이벤트를 AgentResponse로 | `server.py` | 스트리밍 완료 시 전체 스키마 반환 |
| 6 | web/ 패키지 초기화 | `web/` | Vite + React + TypeScript |
| 7 | 기존 사이드패널 코드 이식 | `web/src/` | us-admin worktree에서 이동 |
| 8 | playground 구성 | `web/playground/` | 로컬 테스트 환경 |
| 9 | 버튼 렌더링 로직 수정 | `web/src/` | clickable 규칙 적용 |
| 10 | us-admin 연동 | `us-admin` | `@us/agent-panel` import, Props 전달 |

---

## 8. 열린 질문

1. **스키마 포맷**: JSON Schema vs TypeScript 타입 → TS 타입을 source of truth로 하고 Python은 Pydantic으로 미러링?
2. **패키지 배포**: pnpm link로 개발, npm 배포는 안정화 후?
3. **playground 프레임워크**: Vite standalone? Storybook?
4. **기존 side-panel 브랜치**: 이식 후 브랜치 정리?
5. **SSE vs WebSocket**: 현재 SSE인데 양방향 필요 시 WebSocket 전환 고려?
