# 에이전트 패널 아키텍처 개선

## 문제

### 1. 프론트 계약 부재
- 서버 응답이 `__agent_response__` JSON을 LLM 텍스트 안에 끼워넣고, 정규식으로 추출
- 파싱 실패 시 heuristic fallback (`_detect_mode`로 텍스트에서 키워드 매칭)
- 서버와 프론트의 버튼 타입이 불일치 (서버: action/select/navigate, 프론트: +confirm/skip)
- 버튼 비활성화가 `isLatest`로만 제어 — navigate도 이전 메시지면 disabled

### 2. 프론트가 에이전트 구조에 의존
- 사이드패널 코드가 us-admin에 직접 구현 (worktree side-panel 브랜치)
- 에이전트 변경 시 관리자센터도 수정 + 배포 필요
- 다른 앱에서 재사용 불가

### 3. 위저드 확장 어려움
- 새 위저드 = wizard.py 4개 메서드에 elif 추가
- 스텝 정의가 코드에 암묵적, 선언적 관리 불가
- 프론트에 StepIndicator 있지만 서버가 step 데이터를 안 내려줌
- 버튼 연타/중복 클릭 시 에러

### 4. 채팅 안정성
- 세션 상태 4곳 분산 (_sessions, _memories, _wizards, orchestrator history)
- cascading check 예외가 조용히 삼켜짐
- 위저드 에러 시 재시도 없이 리셋

## 제안

**모노레포 구조로 에이전트 서버 + 패널 패키지 + 공유 스키마를 한 곳에서 관리.**

```
us-product-agent/
├── src/                  # Python 에이전트 서버
├── web/                  # React 패널 패키지 (@us/agent-panel)
│   ├── src/              # 채팅 UI, 버튼, 위저드 렌더링
│   └── playground/       # 로컬 테스트용 독립 UI
└── schema/               # 서버↔패널 공유 응답 스키마 (JSON Schema)
```

**관리자센터는 패널을 import해서 Props 3개만 넘긴다:**
```tsx
<AgentPanel
  apiUrl="https://agent.example.com"
  getToken={() => sessionStorage.getItem('accessToken') || ''}
  onNavigate={(url) => navigate(url)}
/>
```

## 범위

### Phase 1 — 프론트 계약 + 패널 인터페이스
- 서버↔패널 응답 스키마 정의 (JSON Schema)
- 버튼 동작 타입 (`clickable: once | always`)
- 위저드 스텝 진행 상태 스키마
- AgentPanel Props 인터페이스
- SSE 이벤트 스키마

### Phase 2 — 채팅 안정성
- SessionContext 통합 (세션 상태 한 곳에)
- 응답 파이프라인을 Phase 1 계약에 맞게 리팩토링
- `__agent_response__` 정규식 파싱 → 구조화된 응답 반환
- 에러 전파 명시화

### Phase 3 — 위저드 선언적 구조
- YAML/JSON 스키마 기반 위저드 정의
- 재사용 가능한 스텝 블록 (select_master, select_page, confirm, execute)
- 시나리오만 작성하면 일관되게 적용
- 서버가 step 정보 내려줌 → StepIndicator 연동

### Phase 4 — UX 최적화
- CoT 노출 (SSE progress 활용)
- 메시지 큐잉
- (후속) 투기적 실행

### Out of Scope
- LangGraph 전환 (별도 계획)
- 새로운 API 추가
- 투기적 실행 설계 (Phase 4 이후)

## 예상 효과

| 항목 | 현재 | 개선 후 |
|------|------|---------|
| 위저드 추가 | wizard.py 4곳 수정 + 프론트 수정 | YAML 1파일 작성, 프론트 변경 0 |
| 에이전트 변경 시 | 서버 + 관리자센터 둘 다 배포 | 서버 + 패널 패키지만 배포 |
| 버튼 에러 | 연타/중복 클릭 에러 | clickable 스키마로 일관 제어 |
| 응답 파싱 | 정규식 + heuristic | 구조화된 JSON 직접 반환 |
| 로컬 테스트 | 관리자센터 띄워야 함 | playground에서 독립 테스트 |
