# 빠른 실행 메뉴 + Agent 채팅 하이브리드 설계

## 핵심 결정

- **위저드(빠른 실행)와 채팅은 별도 UI**로 제공. 서로 간섭 없음
- 위저드: 빈번한 핵심 시나리오 4-5개. 버튼만, LLM 0회, 즉시 응답
- 채팅: 지금 그대로 유지. 자연어 → 오케스트레이터 LLM → Agent
- 위저드 진행 중 자연어 입력 → "진행 중인 작업이 있어요. 계속하시려면 버튼을, 다른 요청은 [취소] 후 시작해주세요."

```
┌─────────────────────────────────┐
│  사이드패널                      │
│                                 │
│  ┌───────────────────────────┐  │
│  │ 빠른 실행                  │  │
│  │ [노출 진단] [비공개 처리]   │  │
│  │ [공개 처리] [히든 처리]     │  │
│  └───────────────────────────┘  │
│                                 │
│  ┌───────────────────────────┐  │
│  │ 채팅                      │  │
│  │ 무엇이든 물어보세요        │  │
│  │ _________________________ │  │
│  └───────────────────────────┘  │
└─────────────────────────────────┘
```

## 우선순위

| 순서 | 작업 | 영향 범위 | 효과 |
|------|------|----------|------|
| 1 | executor 인스턴스 재사용 | 채팅 전체 | 히스토리 보존, 슬롯 필링 감소 |
| 2 | 프롬프트 캐싱 | 채팅 전체 | TTFT 감소 |
| 3 | 스트리밍 | 채팅 전체 | 체감 속도 |
| 4 | 빠른 실행 메뉴 (위저드) | 핵심 4-5개 시나리오 | 28초 → ~즉시 |

---

## 1. 시나리오 분석 — 어디에 LLM이 필요한가

### 33개 시나리오 분류

| 유형 | 개수 | LLM 필요성 | 처리 방식 |
|------|------|----------|----------|
| 도메인 질문 | 16개 | 높음 (NL 이해 + KB 검색) | Agent (domain) |
| 진단 | 5개 | 낮음 (코드화 완료) | 코드 직접 실행 |
| 조회 | 2개 | 낮음 (코드화 완료) | 코드 직접 실행 |
| 가이드 | 2개 | 낮음 (코드화 완료) | 코드 직접 실행 |
| **단순 실행** | **6개** | **낮음 (패턴화 가능)** | **버튼 위저드** |
| **복합 실행** | **4개** | **높음 (NL 판단 필요)** | **Agent (executor)** |
| 거부 | 1개 | 낮음 | 오케스트레이터 직접 |

### 버튼 위저드 대상 (6개) — 패턴이 명확한 단순 실행

| # | 시나리오 | 패턴 | 턴 수 |
|---|---------|------|-------|
| 23 | 상품 비공개 | 클럽→페이지→옵션→확인→실행 | 4-5 |
| 24-A | 상품페이지 비공개 | 클럽→페이지→확인→실행 | 3-4 |
| 16-A | 히든 처리 (기존) | 클럽→페이지→확인→실행 | 3-4 |
| 36 | 상품페이지 공개 | 클럽→페이지→옵션확인→실행 | 3-4 |
| 06 | 노출 진단 | 클럽→진단→결과 | 2 (이미 코드화) |
| 03 | 상품페이지 조회 | 클럽→목록 | 2 (이미 코드화) |

### Agent 유지 대상 (4개) — LLM 적응적 판단이 필요

| # | 시나리오 | LLM이 필요한 이유 |
|---|---------|-----------------|
| 24-B | "안 보이게 해줘" | EXCLUDED vs INACTIVE 의도 해석 |
| 25 | "비공개하면 다른거?" | 조회 + 도메인 규칙 결합 설명 |
| 36 복합 | "월간구독이랑 연간구독 보여야돼" | 자연어에서 엔티티 추출 |
| 16-B | "새로 만들려고" | 동적 플로우 전환 |

---

## 2. 버튼 위저드 패턴 정의

### 공통 구조

```
모든 위저드는 동일한 구조:

[시작] → [클럽 선택] → [대상 선택] → [확인/경고] → [실행] → [완료]
                ↑              ↑              ↑
             [← 처음으로]   [← 이전]      [취소]
```

### 패턴 1: 상태 변경 (비공개/공개/히든)

```
입력: execute(action="비공개", target_type="상품페이지")

Step 1 — 클럽 선택
  코드: search_masters() → 최근 사용 클럽 우선 표시
  응답: select 템플릿
  버튼: [조조형우] [봄날의 햇살] ... [← 취소]

Step 2 — 대상 선택
  입력: {type: "select", value: "master_35"}
  코드: get_product_page_list(master_id="35")
  응답: select 템플릿
  버튼: [월간 투자 리포트 (공개)] [단건 특강 (비공개)] [← 이전]

Step 3 — 확인 + 경고
  입력: {type: "select", value: "page_148"}
  코드: check_cascading_effects(action="INACTIVE", context={...})
  응답: confirm 템플릿 (경고 포함 시 warning 표시)
  버튼: [비공개 처리하기] [← 이전] [취소]
  경고 시: [비공개 처리하기] [메인도 EXCLUDED 처리] [← 이전]

Step 4 — 실행 + 완료
  입력: {type: "action", action: "execute"}
  코드: update_product_page_status(page_id, "INACTIVE")
  응답: complete 템플릿
  버튼: [결과 확인 →] [다른 작업하기]
```

### 패턴 2: 상품 옵션 상태 변경

```
Step 1~2: 패턴 1과 동일 (클럽 → 페이지 선택)

Step 3 — 옵션 선택
  코드: get_product_list_by_page(page_id)
  응답: select 템플릿
  버튼: [월간 구독 29,900원 (공개)] [연간 구독 299,000원 (공개)] [← 이전]

Step 4 — 확인 + 경고
  코드: check_cascading_effects(action="hide_product", context={...})
  마지막 공개 상품이면:
  버튼: [비공개 처리하기] [상품페이지도 비공개] [← 이전]

Step 5 — 실행 + 완료
```

### 패턴 3: 히든 처리

```
Step 0 — 방식 선택 (기존/신규)
  버튼: [기존 페이지 히든 처리] [새 히든 페이지 생성 →]
  "새 히든 페이지 생성" → guide 템플릿 (navigate)

Step 1~4: 패턴 1과 동일 (기존 페이지 히든 처리)
  action: update_product_page(page_id, {isHidden: true})
```

---

## 3. 라우팅 — 버튼 입력 vs 자연어 입력

### server.py 처리 흐름

```python
def _handle_message(message, session_id, context=None):
    # 1. 버튼 입력인지 확인
    if isinstance(message, dict) and message.get("type") in ("select", "action", "navigate"):
        # 버튼 위저드 처리 — LLM 불필요
        return _handle_button_input(message, session_id)

    # 2. 자연어 입력 → 오케스트레이터 LLM
    return _handle_natural_language(message, session_id)
```

### 버튼 입력 처리

```python
def _handle_button_input(button_data, session_id):
    """버튼 클릭 → 위저드 다음 스텝 실행. LLM 불필요."""
    wizard = _get_wizard_state(session_id)

    if button_data["type"] == "select":
        # 선택 → 다음 스텝으로 진행
        wizard.set_selection(button_data["value"])
        return wizard.next_step()

    elif button_data["type"] == "action":
        if button_data.get("action") == "back":
            return wizard.prev_step()
        elif button_data.get("action") == "cancel":
            wizard.reset()
            return ChatResponse(message="취소했습니다.", buttons=[], mode="idle")
        else:
            # 실행 확인
            return wizard.execute()

    elif button_data["type"] == "navigate":
        # 페이지 이동 — 프론트엔드가 처리
        return ChatResponse(message="", buttons=[], mode="navigate", url=button_data["url"])
```

### 자연어 → 위저드 시작

오케스트레이터가 의도를 파악하면 위저드를 시작:

```python
# orchestrator.py — execute Tool 수정
@strands_tool
def execute(master_name: str, action: str, target_type: str = "product_page") -> str:
    """실행 위저드 시작. 오케스트레이터가 의도를 파악한 뒤 호출.

    Args:
        master_name: 오피셜클럽 이름 (비어있으면 선택 스텝부터)
        action: 비공개/공개/히든/EXCLUDED
        target_type: product_page/product_option
    """
    wizard = create_wizard(action=action, target_type=target_type)

    if master_name:
        # 이름이 있으면 클럽 선택 스텝 건너뛰기
        masters = search_masters(search_keyword=master_name)
        if masters["masters"]:
            wizard.set_selection(f"master_{masters['masters'][0]['cmsId']}")
            return wizard.next_step()  # 대상 선택 스텝으로

    return wizard.start()  # 클럽 선택 스텝부터
```

---

## 4. 위저드 상태 관리

### WizardState

```python
@dataclass
class WizardStep:
    name: str           # "select_master", "select_page", "confirm", "execute"
    data: dict          # API 호출 결과 등
    response: str       # 렌더링된 응답 (되돌아갈 때 재사용)

@dataclass
class WizardState:
    action: str              # "비공개", "공개", "히든", "EXCLUDED"
    target_type: str         # "product_page", "product_option"
    steps: list[WizardStep]  # 완료된 스텝들
    current_step: int        # 현재 위치
    selections: dict         # {master_cms_id, page_id, product_id, ...}

    def next_step(self) -> ChatResponse:
        """다음 스텝 실행 — API 호출 + 템플릿 렌더링."""
        ...

    def prev_step(self) -> ChatResponse:
        """이전 스텝으로 — 저장된 응답 재사용."""
        self.current_step -= 1
        return self.steps[self.current_step].response

    def execute(self) -> ChatResponse:
        """최종 실행."""
        ...

    def reset(self):
        """위저드 초기화."""
        self.steps.clear()
        self.current_step = 0
        self.selections.clear()
```

### 세션당 위저드 관리

```python
_wizard_states: dict[str, WizardState] = {}

def _get_wizard_state(session_id: str) -> WizardState | None:
    return _wizard_states.get(session_id)
```

---

## 5. Agent가 처리하는 영역 — 위저드로 안 되는 것들

### 자연어 → Agent fallback 조건

| 조건 | 예시 | 처리 |
|------|------|------|
| 모호한 의도 | "안 보이게 해줘" | 오케스트레이터가 의도 확인 후 위저드 or executor |
| 복합 요청 | "공개해줘, 월간구독이랑 연간구독 보여야돼" | executor LLM (엔티티 추출 필요) |
| 맥락 추론 | "그거 해줘", "홍춘욱은?" | 오케스트레이터 (Memory 활용) |
| 도메인 질문 | "히든이랑 비공개 차이가 뭐야?" | domain agent |
| 규칙 기반 설명 | "비공개하면 다른거 공개돼?" | executor LLM (조회 + 규칙 결합) |
| 런칭 체크리스트 | "빠진거 없는지 체크해줘" | executor LLM (7단계 검증) |

### 위저드 중 자연어 입력 — 거부 + 안내

위저드 진행 중에 자연어 입력이 오면 **위저드 맥락을 보호**:

```
위저드: [조조형우] [봄날의 햇살] 선택하세요
유저: "히든이랑 비공개 차이가 뭐야?"  ← 자연어 입력
→ "진행 중인 작업이 있어요. 계속하시려면 버튼을 눌러주세요."
   [조조형우] [봄날의 햇살] [취소]
```

이유:
- 맥락 전환 판단에 LLM 불필요 (버튼 아니면 위저드 안내)
- WizardState 관리 단순 (진행 or 취소, 중간 상태 없음)
- 오케스트레이터 부담 없음
- 다른 요청이 필요하면 [취소] 후 채팅으로 자유롭게 가능

```python
def _handle_message(message, session_id):
    wizard = _get_wizard_state(session_id)

    if wizard and wizard.is_active():
        if isinstance(message, dict):  # 버튼
            return wizard.handle(message)
        else:  # 자연어 → 위저드 보호
            return ChatResponse(
                message="진행 중인 작업이 있어요. 계속하시려면 버튼을 눌러주세요.",
                buttons=[*wizard.current_buttons(), _btn_action("취소", "cancel")],
                mode="wizard"
            )

    # 위저드 없으면 일반 채팅 처리
    return _handle_natural_language(message, session_id)
```

---

## 6. 아키텍처 변경 요약

```
변경 전:
  유저 메시지 → 오케스트레이터 LLM → execute Tool → executor LLM (8라운드) → 응답

변경 후:
  유저 메시지 (자연어) → 오케스트레이터 LLM → execute Tool → 위저드 시작 → 버튼 응답
  유저 버튼 클릭       → 코드 직접 처리 → 다음 스텝 → 버튼 응답
  유저 메시지 (자연어)  → 오케스트레이터 LLM → Agent 처리 (복잡한 요청)

  executor LLM은 유지 — 위저드로 처리 불가능한 복잡한 요청의 fallback
```

```
┌─────────────────────────────────────────────────┐
│                    server.py                     │
│                                                 │
│  메시지 수신                                      │
│    ├─ dict (버튼 클릭) → WizardState.next_step() │
│    │                    LLM 0회, 코드 직접 실행    │
│    │                                             │
│    └─ str (자연어) → 오케스트레이터 LLM             │
│         ├─ diagnose → 코드 (이미 완료)             │
│         ├─ query → 코드 (이미 완료)                │
│         ├─ guide → 코드 (이미 완료)                │
│         ├─ execute (단순) → 위저드 시작             │
│         ├─ execute (복잡) → executor LLM           │
│         └─ domain → domain agent                  │
└─────────────────────────────────────────────────┘
```

---

## 7. Langfuse 트레이싱 근거

### 574 트레이스 분석 결과

| 유형 | 트레이스 수 | 평균 지연 | p90 | 비고 |
|------|-----------|----------|-----|------|
| 진단 | 174 (30%) | 14.9s | 22.6s | 코드화 후 ~6s |
| 실행 | 166 (29%) | 12.5s | 18.4s | **가장 개선 필요** |
| 포맷팅 | 96 (17%) | 3.1s | - | structured_output 제거로 해결 |
| 도메인 | 7 (1%) | 8.0s | 10.7s | 사용 빈도 낮음 |

### 실행 트레이스 — 반복 패턴 4가지

**패턴 1: 상태 변경** (28.8s, LLM 8회) — **위저드 대상**
```
search_masters → get_product_page_list → get_product_list_by_page
→ check/confirm → update → verify
```

**패턴 2: 전체 세팅** (128-148s, LLM 30+회) — **Agent 유지**
```
search → series → create_page → create_product → display → status
→ main_product → verify (14단계)
```

**패턴 3: 진단** (14.9s → 6.75s) — **이미 코드화 완료**

**패턴 4: 조회** (15.3s → 6.46s) — **이미 코드화 완료**

### 위저드 적용 시 예상 효과

| 시나리오 | 현재 | 위저드 | 개선 |
|---------|------|--------|------|
| 상품 비공개 (#23) | 28.8s | ~5s (LLM 1회) | -83% |
| 상품페이지 비공개 (#24-A) | ~20s | ~4s (LLM 1회) | -80% |
| 히든 처리 (#16-A) | ~20s | ~4s (LLM 1회) | -80% |
| 상품페이지 공개 (#36) | ~15s | ~4s (LLM 1회) | -73% |
| 복합 요청 (#24-B, #25) | ~15-20s | 유지 (Agent) | - |

---

## 8. 구현 순서

| Step | 작업 | 파일 | 효과 |
|------|------|------|------|
| 1 | WizardState 클래스 정의 | `src/wizard.py` (신규) | 기반 구조 |
| 2 | 상태 변경 위저드 구현 (비공개/공개/히든) | `src/wizard.py` | 핵심 패턴 |
| 3 | server.py 버튼 입력 분기 | `server.py` | 라우팅 |
| 4 | orchestrator execute Tool 수정 | `src/agents/orchestrator.py` | 위저드 시작점 |
| 5 | executor 인스턴스 재사용 | `server.py`, `src/agents/__init__.py` | 복잡한 요청 속도 개선 |
| 6 | 프롬프트 캐싱 | 각 에이전트 | TTFT 감소 |
| 7 | 스트리밍 연동 | `server.py` | 체감 속도 |

---

## 9. 열린 질문

1. **위저드 중 자연어 입력 처리**: 위저드 상태를 유지하면서 Agent 답변 후 돌아올 수 있는지. 아니면 위저드를 리셋할지
2. **"단순 vs 복잡" 판단 기준**: 오케스트레이터가 위저드로 보낼지 executor로 보낼지 어떻게 판단하는가. "공개해줘"는 위저드, "공개해줘 월간구독이랑 연간구독 보여야돼"는 executor
3. **이전 버튼 UX**: 프론트엔드(사이드패널)에서 이전/취소 버튼을 어떻게 표현할지
4. **위저드 timeout**: 유저가 위저드 중간에 떠나면 상태를 얼마나 유지할지
5. **cascading 경고의 추가 액션**: "메인도 EXCLUDED 처리" 버튼 → 위저드 내에서 추가 API 호출 → 위저드 스텝 확장이 필요한지
