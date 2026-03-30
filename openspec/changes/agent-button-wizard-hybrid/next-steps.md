# 다음 단계 — 에이전트 패널 패키지 분리

## 배경

현재 사이드패널 코드가 `us-admin/src/shared/ui/SidePanel/`에 직접 구현되어 있음.
에이전트 서버(us-product-agent) 변경 시 프론트 수정이 별도 프로젝트에서 이루어져야 하므로 응집도가 떨어짐.

## 계획

### Phase 1: 패키지 분리 (안정화 후)

`us-product-agent/web/`에 React 패널 컴포넌트를 패키지로 분리:

```
us-product-agent/
├── src/              # Python 서버 (기존)
├── web/              # React 사이드패널 패키지 (신규)
│   ├── src/
│   │   ├── AgentPanel.tsx        # 메인 패널 컴포넌트
│   │   ├── ChatMessage.tsx       # 메시지 렌더링
│   │   ├── WizardMenu.tsx        # 위저드 메뉴 (런칭 체크 등)
│   │   ├── ActionButton.tsx      # 버튼 렌더링 (select/action/navigate)
│   │   ├── useAgentApi.ts        # API 호출 (sendMessage, startWizard, sendButton)
│   │   ├── types.ts              # ChatResponse, Button 타입
│   │   └── index.ts
│   ├── package.json              # @us/agent-panel
│   └── tsconfig.json
```

### Phase 2: us-admin 연동

개발 중: pnpm link로 로컬 참조
```json
// us-admin/package.json
"@us/agent-panel": "link:../../../ai/us-product-agent/web"
```

안정화 후: npm 배포로 전환
```json
"@us/agent-panel": "^1.0.0"
```

us-admin에서 사용:
```tsx
import { AgentPanel } from '@us/agent-panel';

<AgentPanel
  apiUrl="http://localhost:8000"
  getToken={() => sessionStorage.getItem('accessToken') || ''}
  onNavigate={(url) => navigate(url)}
/>
```

### Phase 3: 프론트 구현 요구사항

패널 컴포넌트가 처리해야 할 것:

1. **위저드 메뉴**: `GET /wizard/actions` → 버튼 목록
2. **API 호출 3가지**: startWizard, sendButton, sendMessage
3. **mode별 UI 분기**:
   - `wizard` → 채팅 입력 비활성화, 버튼만
   - `wizard_input` → 채팅 입력 활성화 (검색용)
   - `launch_check` / `done` / `diagnose` → 결과 표시
   - 그 외 → 일반 채팅
4. **버튼 활성화 제어**: 마지막 메시지의 buttons만 활성화
5. **navigate 버튼**: `onNavigate` 콜백으로 라우터 이동

## 전제 조건

- 사이드패널 UX가 확정된 후 진행
- 현재는 side-panel 브랜치에서 직접 개발 유지
