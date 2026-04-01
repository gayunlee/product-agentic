# 채팅 맥락 유실 — 문제 분석 및 수정 계획

수동 테스트(2026-04-01)에서 발견. 위저드는 정상, 자유 대화(채팅)에서 3가지 문제.

---

## 재현 시나리오

```
유저: 에이전트 테스트 클럽 지금 상품페이지 어스플러스에 노출되고 있어?
에이전트: 검색 결과가 없네요. 정확한 오피셜클럽 이름을 다시 확인해 주실 수 있을까요?

유저: 에이전트 테스트 오피셜 클럽
에이전트: 진단 완료. 모든 조건 정상. 데이터가 없습니다.  ← 모순

유저: 상품 페이지 노출되고 있냐고
에이전트: 먼저 어느 오피셜클럽의 상품 페이지인지 알아야 합니다.  ← 맥락 유실
```

---

## 문제 1: 부분 검색 미지원

**증상**: "에이전트 테스트 클럽" → 못 찾음. "에이전트 테스트 오피셜 클럽" → 찾음.

**원인**: `search_masters(search_keyword)` → Admin API에 그대로 전달. API가 정확 매칭만 수행.

**파일**: `src/tools/admin_api.py` L176-179

**수정 방향**:
- API 응답 후 client-side 부분 문자열 필터링 추가
- 검색 결과 0건이면 keyword를 분할("에이전트", "테스트", "클럽")해서 재검색
- 또는 오케스트레이터가 "정확한 이름 필요" 인지하고 유저에게 안내

---

## 문제 2: 진단 결과 모순 — "정상 + 데이터 없음"

**증상**: 진단 결과가 "모든 조건 정상"인데 "데이터가 없습니다"도 동시에 출력.

**원인**: `diagnose_engine.py` — API가 빈 결과 반환 시 checks를 전부 통과시키고, 데이터 없음은 별도 메시지로만 표시.

**파일**: `src/diagnose_engine.py` L114-160, L183-209

**수정 방향**:
- `get_product_page_list()` 빈 결과 → checks에 "데이터 조회 실패" 항목 추가
- checks가 모두 통과했는데 데이터가 없으면 "정상"이 아닌 "확인 불가" 표시
- `_check_main_product()` API 에러 시 `passed=False` + 에러 사유

---

## 문제 3: 맥락 유실 (핵심)

**증상**: 이전 대화에서 "에이전트 테스트 오피셜 클럽"을 찾았는데, 후속 질문에서 다시 "어느 오피셜클럽?" 되물음.

### 원인 분석

#### 3-1. executor의 대화 히스토리 격리
- 오케스트레이터, executor, domain은 각각 독립적인 Strands Agent (별도 message history)
- executor가 이전 턴의 검색 결과(cmsId 등)를 볼 수 없음

#### 3-2. 벡터 라우팅 시 memory_context 미전달
- `server.py` L322-330: memory_context를 오케스트레이터에만 주입
- 벡터 라우팅이 executor를 직접 호출할 때 memory_context 없음
- executor는 "오피셜클럽 검색을 처음부터" 시작

#### 3-3. flow_context 조기 소멸
- `context.py` L86-89: active_agent 해제 시 `flow_context.clear()`
- 진단(diagnose) 후 모드가 idle로 변경 → flow_context(cmsId 포함) 삭제

#### 3-4. ConversationContext에 이전 결과 저장 없음
- `last_master_id`, `last_page_id` 같은 필드 없음
- 대화에서 찾은 대상 정보가 세션에 저장되지 않음

### 수정 방향

| 우선순위 | 파일 | 변경 | 효과 |
|---------|------|------|------|
| P1 | `src/context.py` | ConversationContext에 `last_master_id`, `last_master_name` 필드 추가 | 대상 정보 세션 유지 |
| P1 | `server.py` | executor 직접 호출 시 memory_context + last_master 정보를 프롬프트에 주입 | 맥락 전달 |
| P1 | `src/context.py` | flow_context 소멸 조건 완화 — diagnose/info 모드 후에도 master_id 유지 | 진단 후 후속 대화 가능 |
| P2 | `src/agents/executor.py` | 프롬프트에 "이전 대화에서 {master_name}(cmsId={id})를 다루고 있었음" 컨텍스트 주입 | executor가 맥락 인지 |
| P3 | `src/agents/orchestrator.py` | execute() 도구 호출 시 flow_context 전달 | 오케스트레이터→executor 맥락 연결 |

---

## 문제 4: structured_output 에러

**증상**: `⚠️ structured_output 실패: 'NoneType' object has no attribute 'startswith'`

**원인**: executor.messages[-1]이 None일 때 structured_output이 에러.

**파일**: `server.py` L260-268

**수정 방향**: structured_output 전 executor.messages 유효성 체크 + 폴백 강화

---

## 실행 순서

1. **P1: 맥락 유지** — context.py + server.py + executor.py (핵심)
2. **P2: 부분 검색** — admin_api.py (UX 개선)
3. **P3: 진단 에러 처리** — diagnose_engine.py (데이터 정합성)
4. **P4: structured_output 에러** — server.py (안정성)

각 단계 후 기존 테스트 212개 + E2E 14개 회귀 검증 필요.
