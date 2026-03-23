# 멀티 에이전트 설계서

시나리오 32개 기반. 각 에이전트의 역할, 워크플로우, 통신 인터페이스, 툴을 정의한다.

---

## 1. 시나리오 분류 요약

32개 시나리오를 에이전트 라우팅 기준으로 분류:

| 분류 | 시나리오 | 비율 |
|------|----------|------|
| **도메인 지식** | #4, #11, #13, #14, #15, #17, #18, #19, #20, #21, #22, #26, #30, #31 | 14개 (44%) |
| **수행 — 진단** | #5, #6, #7, #8, #9, #28, #29, #37, #38 | 9개 (28%) |
| **수행 — 가이드** | #1, #2, #10, #12 | 4개 (12%) |
| **수행 — 실행** | #16, #23, #24, #36 | 4개 (12%) |
| **복합** | #25 (조회+도메인), #39 (탐색 에이전트) | 2개 (6%) |

---

## 2. 에이전트별 역할

### 2-1. 오케스트레이터

**역할**: 유저와 대화, 의도 분류, 하위 에이전트 라우팅
**판단 범위**: "도메인 질문인가, 수행 요청인가" — 이것만

```
입력: 유저 메시지 + 대화 히스토리
출력: 하위 에이전트 응답을 유저에게 전달
```

**분류 규칙** (few-shot으로 학습):
```
도메인 → "~이 뭐야?", "~차이가 뭐야?", "~어떻게 돼?", "~가능해?" (개념 질문)
수행   → "~해줘", "~만들려고", "~안 보여", "~비공개해줘", "~체크해줘" (행동/진단 요청)
복합   → 도메인 + 수행이 섞인 경우 → 수행 에이전트 먼저, 도메인 보충
```

**맥락 관리**:
- 대화 히스토리 전체 보유 (SessionManager)
- 하위 에이전트에게는 필요한 맥락만 전달
- "그거 활성화해줘" 같은 대명사 → 이전 맥락에서 대상 추론 후 수행 에이전트에 전달

**담당 시나리오**: 전체 32개 (라우팅만)

### 2-2. 도메인 지식 에이전트

**역할**: 관리자센터 도메인 개념 설명
**판단 범위**: 질문 이해 + 지식 기반 답변 (API 호출 없음)

```
입력: 유저 질문 (오케스트레이터가 전달)
출력: 지식 기반 답변 텍스트
```

**지식 소스**: knowledge/*.md → Bedrock Knowledge Base (RAG)
- 시스템 프롬프트: 핵심 규칙만 (답변 톤, 내부 용어 변환 등)
- 도메인 지식: RAG 검색으로 주입 (매 턴마다 전부 넣지 않음)

**답변 규칙**:
- 내부 필드명(isDeletable, isHidden 등) 노출 금지 → 운영 매니저 용어로 설명
- API 호출 없이 답변 (조회가 필요하면 "수행 에이전트에게 맡겨야 한다"고 반환)

**담당 시나리오**: #4, #11, #13, #14, #15, #17, #18, #19, #20, #21, #22, #26, #30, #31

**툴**: 없음 (RAG 검색은 Bedrock Knowledge Base의 retrieve API로 처리, 별도 Tool 불필요)

### 2-3. 수행 에이전트

**역할**: 실제 액션 실행 — 조회, 진단, 가이드(이동 안내), API 변경
**판단 범위**: "어떤 액션을 할지" + "필요한 파라미터 수집"

```
입력: 유저 의도 + 맥락 (오케스트레이터가 전달)
출력: 액션 결과 + 버튼(이동/실행/완료)
```

**3가지 모드**:

| 모드 | 설명 | 시나리오 |
|------|------|----------|
| **가이드** | 관리자센터 페이지 이동 안내 + [이동] 버튼 | #1, #2, #10, #12 |
| **실행** | API 호출로 직접 처리 + 확인 후 실행 | #16, #23, #24, #36 |
| **진단** | 상태 조회 → 체인 검증 → 원인 보고 | #5, #6, #7, #8, #9, #28, #37 |

**슬롯 필링 패턴** (대부분의 시나리오에서 반복):
```
1. 오피셜클럽 특정 → search_masters (없으면 "어떤 오피셜클럽?" 질문)
2. 상품 페이지 특정 → get_product_page_list (여러 개면 목록 제시)
3. 상품 옵션 특정 → get_product_list_by_page (필요한 경우)
```

**검증 에이전트 연동 시점**:
- 실행 모드: 쓰기 API 호출 전 check_prerequisites + check_idempotency
- 진단 모드: diagnose_visibility 호출
- 가이드 모드: 사전조건 체인 확인 (필요시)

**담당 시나리오**: #1, #2, #3, #5, #6, #7, #8, #9, #10, #12, #16, #23, #24, #25, #28, #36, #37, #39

### 2-4. 검증 에이전트 (구현 완료)

**역할**: 사전조건 체크, 멱등성 확인, 노출 진단
**판단 범위**: "이 액션을 실행해도 되나?" — 규칙 기반

```
입력: (action, context) 또는 (master_id)
출력: { ok: bool, missing: [...], message: str }
```

**함수 3개** (이미 구현):
- `check_prerequisites(action, context)` — 사전조건 충족 여부
- `check_idempotency(action, context)` — 이미 실행된 건 아닌지
- `diagnose_visibility(master_id)` — 노출 체인 5단계 진단

**호출자**: 수행 에이전트가 AgentTool로 호출 (유저 직접 호출 X)

---

## 3. 협업 워크플로우

### 3-0. 전체 흐름도

```
┌──────────────────────────────────────────────────────────┐
│                    사이드패널 (UI)                         │
│  유저 메시지 + { roleType, permissionSections, pageUrl }  │
└──────────────────────┬───────────────────────────────────┘
                       ▼
┌──────────────────────────────────────────────────────────┐
│                  오케스트레이터                            │
│                                                          │
│  1. 맥락 로드 (SessionManager)                           │
│  2. 의도 분류 ──────────────────┐                        │
│     │                           │                        │
│     ├─ 도메인 질문 ─────────────┼──► 도메인 에이전트      │
│     │                           │                        │
│     ├─ 수행 요청 ───────────────┼──► 수행 에이전트        │
│     │  (가이드/실행/진단)        │                        │
│     │                           │                        │
│     ├─ 복합 ────────────────────┼──► 수행 먼저 → 도메인   │
│     │                           │                        │
│     └─ 범위 밖 ─────────────────┼──► Guardrails 거부     │
│                                 │                        │
│  3. 하위 에이전트 응답 수신                                │
│  4. 대화 히스토리 저장                                     │
│  5. 응답 반환 (message + buttons)                         │
└──────────────────────────────────────────────────────────┘
```

### 3-0-1. 오케스트레이터 분류 로직

```
입력: 유저 메시지 + 대화 히스토리

판단 기준 (few-shot 예시로 학습):
┌─────────────────────────────────────────────────────┐
│ 패턴                          │ 분류               │
│───────────────────────────────│────────────────────│
│ "~이 뭐야?", "~차이가 뭐야?"  │ 도메인              │
│ "~어떻게 돼?", "~가능해?"      │ 도메인              │
│ "~해줘", "~만들려고"           │ 수행 (가이드/실행)   │
│ "~왜 안 보여?", "~안 돼?"      │ 수행 (진단)         │
│ "~체크해줘", "~확인해줘"       │ 수행 (진단)         │
│ "~비공개해줘", "~공개해줘"     │ 수행 (실행)         │
│ 조회 + 개념 질문 섞임          │ 복합                │
│ 이전 대화 대명사 ("그거")      │ 맥락에서 추론       │
└─────────────────────────────────────────────────────┘

출력: AgentTool 호출 (executor 또는 domain_expert)
- 수행: 원문 메시지 + 맥락(master_id 등 이전 턴에서 확보한 것) 전달
- 도메인: 원문 메시지만 전달
- 복합: 수행 먼저 호출 → 결과 확인 → 도메인 보충 필요하면 추가 호출
```

### 3-0-2. 수행 에이전트 내부 워크플로우

```
입력: 유저 의도 + 맥락

┌─────────────────────────────────────────────────────────┐
│                    수행 에이전트                          │
│                                                         │
│  Step 1. 슬롯 필링 (대상 특정)                           │
│  ┌─────────────────────────────────────────────────┐    │
│  │ master_id 없음?                                  │    │
│  │   → search_masters() 또는 interrupt("어떤 클럽?")│    │
│  │                                                  │    │
│  │ product_page_id 필요한데 없음?                    │    │
│  │   → get_product_page_list()                      │    │
│  │   → 1개면 자동 선택, 여러 개면 interrupt(목록)    │    │
│  │                                                  │    │
│  │ product_id 필요한데 없음?                         │    │
│  │   → get_product_list_by_page()                   │    │
│  │   → interrupt(목록)                               │    │
│  └─────────────────────────────────────────────────┘    │
│                         │                               │
│                         ▼                               │
│  Step 2. 모드 판별 + 실행                                │
│  ┌─────────────────────────────────────────────────┐    │
│  │                                                  │    │
│  │  ┌── 가이드 모드 ──┐                             │    │
│  │  │ 검증: check_prerequisites (사전조건 확인)      │    │
│  │  │ 부족하면 → 해결 안내 (시리즈 없으면 파트너센터)│    │
│  │  │ 충족하면 → navigate() 호출 → [이동] 버튼      │    │
│  │  └─────────────────┘                             │    │
│  │                                                  │    │
│  │  ┌── 실행 모드 ──┐                               │    │
│  │  │ 검증: check_prerequisites                     │    │
│  │  │ 검증: check_idempotency (이미 처리됐는지)     │    │
│  │  │ 확인: interrupt("~하시겠어요?") + 버튼 제시    │    │
│  │  │ 실행: API 호출 (update_*)                     │    │
│  │  │ 결과: 완료 메시지 + 확인 링크                  │    │
│  │  └─────────────────┘                             │    │
│  │                                                  │    │
│  │  ┌── 진단 모드 ──┐                               │    │
│  │  │ 검증: diagnose_visibility (노출 체인)          │    │
│  │  │   또는 개별 상태 조회 (게시판, 응원하기 등)    │    │
│  │  │ 결과: 체크리스트 + 원인 + 해결 안내/버튼       │    │
│  │  └─────────────────┘                             │    │
│  │                                                  │    │
│  └─────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

### 3-0-3. 수행 ↔ 검증 협업 패턴

검증 에이전트는 수행 에이전트의 "안전장치"로, 3가지 시점에 호출된다:

```
패턴 A: 실행 전 사전조건 검사
┌──────────────┐     check_prerequisites     ┌──────────────┐
│  수행 에이전트 │ ──────────────────────────► │  검증 에이전트 │
│              │ ◄────────────────────────── │              │
│              │   {ok: false,              │              │
│              │    missing: ["series_ids"],│              │
│              │    message: "시리즈 먼저..."} │              │
│              │                            │              │
│  → 유저에게  │                            │              │
│    해결 안내  │                            │              │
└──────────────┘                            └──────────────┘

패턴 B: 실행 전 멱등성 검사
┌──────────────┐     check_idempotency       ┌──────────────┐
│  수행 에이전트 │ ──────────────────────────► │  검증 에이전트 │
│              │ ◄────────────────────────── │              │
│              │   {ok: false,              │              │
│              │    already_done: true,     │              │
│              │    message: "이미 비공개..."} │              │
│              │                            │              │
│  → 유저에게  │                            │              │
│    "이미 처리" │                            │              │
└──────────────┘                            └──────────────┘

패턴 C: 진단 (노출 체인 검증)
┌──────────────┐     diagnose_visibility     ┌──────────────┐
│  수행 에이전트 │ ──────────────────────────► │  검증 에이전트 │
│              │ ◄────────────────────────── │              │
│              │   {checks: [              │              │
│              │     {name: "master_public",│              │
│              │      ok: true},            │              │
│              │     {name: "main_active",  │              │
│              │      ok: false, ...}       │              │
│              │   ]}                       │              │
│              │                            │              │
│  → 첫 번째   │                            │              │
│    실패 원인  │                            │              │
│    + 해결 안내 │                            │              │
└──────────────┘                            └──────────────┘
```

### 3-0-4. interrupt() 흐름 (멀티턴 대화)

Strands의 `interrupt()`는 수행 에이전트에서 발생하지만, 오케스트레이터를 통해 유저에게 전달된다:

```
턴 1:
  유저 → 오케스트레이터 → 수행 에이전트
                              │
                              ├─ master_id 없음
                              └─ interrupt("어떤 오피셜클럽?")
                                    │
                          오케스트레이터가 중계
                                    │
                                    ▼
                               유저에게 질문

턴 2:
  유저("조조형우") → 오케스트레이터 → 수행 에이전트 (세션 복원)
                                         │
                                         ├─ search_masters("조조형우")
                                         ├─ get_product_page_list()
                                         ├─ 페이지 3개 → interrupt(목록)
                                         │
                                    유저에게 목록 제시

턴 3:
  유저("1번") → 오케스트레이터 → 수행 에이전트 (세션 복원)
                                     │
                                     ├─ 검증 → 실행 → 완료
                                     └─ 응답 반환 (버튼 포함)
```

**핵심**: 세션 매니저가 대화 상태를 저장하므로, 각 턴에서 수행 에이전트는 이전 턴의 맥락(master_id, product_page_id 등)을 알고 있다.

---

### 3-1. 시나리오별 예시

#### 3-1-1. 도메인 질문 플로우

```
유저: "단건 상품은 상품 변경 못해?"

오케스트레이터
  ├─ 분류: 도메인 질문
  └─ 도메인 에이전트 호출("단건 상품은 상품 변경 못해?")
       └─ RAG 검색 → 답변 생성
            └─ "네, 단건상품은 변경 불가입니다..."
```

#### 3-1-2. 가이드 플로우 (페이지 이동 안내)

```
유저: "상품페이지 새로 만들려고"

오케스트레이터
  ├─ 분류: 수행 요청
  └─ 수행 에이전트 호출("상품페이지 새로 만들려고")
       ├─ 슬롯 필링: "어떤 오피셜클럽?" → interrupt()
       │   유저: "조조형우"
       ├─ search_masters("조조형우") → cmsId 확보
       ├─ 검증: check_prerequisites("create_product_page", {master_id})
       │   └─ series_ids 필요 → get_series_list
       ├─ 시리즈 확인 → 있음
       ├─ "구독/단건?" → interrupt()
       │   유저: "구독"
       └─ 응답: "상품 페이지 생성 화면으로 이동해주세요"
            + [상품 페이지 생성 →] 버튼
```

#### 3-1-3. 실행 플로우 (API 직접 호출)

```
유저: "상품페이지 비공개해줘"

오케스트레이터
  ├─ 분류: 수행 요청
  └─ 수행 에이전트 호출("상품페이지 비공개해줘")
       ├─ 슬롯 필링: "어떤 오피셜클럽?" → interrupt()
       │   유저: "조조형우"
       ├─ search_masters → get_product_page_list → 목록 제시 → interrupt()
       │   유저: "1번"
       ├─ 검증: check_prerequisites("update_product_page_status", {product_page_id})
       │   └─ ok
       ├─ 검증: check_idempotency("update_product_page_status", {product_page_id, status: "INACTIVE"})
       │   └─ ok (이미 INACTIVE 아님)
       ├─ 확인: "비공개 처리하시겠어요?" → interrupt()
       │   유저: "ㅇㅇ"
       ├─ update_product_page_status(id, "INACTIVE")
       └─ 응답: "비공개 처리 완료"
```

#### 3-1-4. 진단 플로우

```
유저: "어스플러스에 왜 상품페이지 노출이 안돼?"

오케스트레이터
  ├─ 분류: 수행 요청 (진단)
  └─ 수행 에이전트 호출("상품페이지 노출이 안돼")
       ├─ 슬롯 필링: "어떤 오피셜클럽?" → interrupt()
       │   유저: "봄날의 햇살"
       ├─ search_masters → master_id 확보
       ├─ 검증: diagnose_visibility(master_id)
       │   └─ { checks: [
       │        {name: "master_public", ok: true},
       │        {name: "main_product_active", ok: false, detail: "INACTIVE"},
       │        ...
       │      ]}
       └─ 응답: "메인 상품 페이지가 INACTIVE 상태입니다. 활성화하시겠어요?"
            + [메인 상품 페이지 관리 →] 버튼
```

#### 3-1-5. 복합 플로우

```
유저: "노출중인 조조형우 상품페이지 뭐가 있어? 비공개하면 다른거 공개되는거 있나?"

오케스트레이터
  ├─ 분류: 복합 (수행 + 도메인)
  ├─ 수행 에이전트 호출("조조형우 노출중 상품페이지 조회")
  │    └─ 목록 반환
  └─ 도메인 에이전트 호출("비공개하면 폴백 규칙")
       └─ "기간공개 비공개 시 상시공개 폴백" 설명
```

---

## 4. 통신 인터페이스

### 4-1. Strands Agent-as-Tool

같은 프로세스 내에서 에이전트를 Tool로 등록:

```python
from strands import Agent
from strands.multiagent import AgentTool
from strands.session import S3SessionManager

# 에이전트 생성
validator = create_validator_agent()    # 이미 구현
domain_agent = create_domain_agent()
executor = create_executor_agent(validator)

# 오케스트레이터에 하위 에이전트를 Tool로 등록
orchestrator = Agent(
    tools=[
        AgentTool(executor, tool_name="executor", tool_description="..."),
        AgentTool(domain_agent, tool_name="domain_expert", tool_description="..."),
    ],
    session_manager=S3SessionManager(bucket="...", key_prefix="sessions/"),
    system_prompt=ORCHESTRATOR_PROMPT,
)
```

### 4-2. 오케스트레이터 ↔ 수행 에이전트

```python
# 오케스트레이터가 수행 에이전트를 Tool로 호출
# AgentTool은 내부적으로 메시지를 전달하고 응답을 받음

# 수행 에이전트의 AgentTool 정의:
AgentTool(
    executor,
    tool_name="executor",
    tool_description="""수행 에이전트. 관리자센터 API를 호출하여 조회, 진단, 가이드, 실행을 처리한다.
    - 조회: 마스터/상품 페이지/옵션 조회
    - 진단: "왜 안 보여?" 류의 원인 분석
    - 가이드: 페이지 이동 안내 + 버튼
    - 실행: 상태 변경 (비공개, 히든, 활성화 등)
    유저에게 추가 정보가 필요하면 interrupt()로 질문한다.""",
)
```

### 4-3. 오케스트레이터 ↔ 도메인 에이전트

```python
AgentTool(
    domain_agent,
    tool_name="domain_expert",
    tool_description="""도메인 지식 에이전트. 관리자센터 도메인 개념을 설명한다.
    API를 호출하지 않는다. 지식 기반 답변만 한다.
    마스터/오피셜클럽 구조, 상품 페이지 설정, 노출 규칙, 결제 수단 등.""",
)
```

### 4-4. 수행 에이전트 ↔ 검증 에이전트

```python
# 수행 에이전트 내부에서 검증 에이전트를 Tool로 사용
executor = Agent(
    tools=[
        # 관리자센터 API Tools (아래 5. 참조)
        search_masters, get_master_detail, get_series_list,
        get_product_page_list, get_product_page_detail,
        get_product_list_by_page, get_community_settings,
        update_product_display, update_product_page_status,
        update_product_page, navigate,
        # 검증 에이전트
        AgentTool(validator, tool_name="validator", tool_description="..."),
    ],
    system_prompt=EXECUTOR_PROMPT,
)
```

### 4-5. 응답 포맷 (수행 에이전트 → 오케스트레이터 → 사이드패널)

사이드패널 UI가 렌더링할 수 있는 구조화된 응답:

```python
# 수행 에이전트 응답 예시 (마크다운 + 버튼)
{
    "message": "월간 투자 리포트를 비공개 처리하시겠어요?\n비공개 시 고객에게 페이지가 보이지 않습니다.",
    "buttons": [
        {"type": "action", "label": "비공개 처리하기", "action_id": "toggle_page_status", "params": {"id": "148", "status": "INACTIVE"}},
        {"type": "navigate", "label": "직접 수정하기 →", "url": "/product/page/148?tab=settings"},
    ]
}
```

버튼 타입:
| type | 설명 | 예시 |
|------|------|------|
| `navigate` | 관리자센터 페이지 이동 | `[상품 페이지 생성 →]` |
| `action` | 에이전트에게 API 실행 요청 | `[비공개 처리하기]` |
| `confirm` | 작업 완료 확인 (유저가 관리자센터에서 작업 후) | `[완료]` |

---

## 5. 툴 설계

### 5-1. 수행 에이전트 — 조회 Tools

| Tool | API | 시나리오 | 설명 |
|------|-----|----------|------|
| `search_masters` | `GET /v1/masters?searchKeyword=` | #1~#39 대부분 | 오피셜클럽 검색 (슬롯 필링 첫 단계) |
| `get_master_detail` | `GET /v1/masters/{id}` | #7, #37 | 마스터 상세 (publicType 등) |
| `get_series_list` | `GET /with-series?masterId=` | #1, #37 | 시리즈 목록 |
| `get_product_page_list` | `GET /v1/product-group?masterId=` | #1~#3, #5, #6, #23, #24, #25, #36, #37 | 상품 페이지 목록 |
| `get_product_page_detail` | `GET /v1/product-group/{id}` | #2, #9, #37 | 상품 페이지 상세 (displayLetterStatus 등) |
| `get_product_list_by_page` | `GET /v1/product/group/{id}` | #5, #23, #36 | 상품 옵션 목록 |
| `get_community_settings` | `GET /v1/master/{cmsId}/community/category` | #8, #28 | 게시판/응원하기 상태 (**신규**) |

### 5-2. 수행 에이전트 — 실행 Tools

| Tool | API | 시나리오 | 설명 |
|------|-----|----------|------|
| `update_product_display` | `PATCH /v1/product/display` | #23, #36 | 상품 옵션 공개/비공개 |
| `update_product_page_status` | `PATCH /v1/product-group/status` | #24, #36 | 상품 페이지 공개/비공개 |
| `update_product_page` | `PATCH /v1/product-group` | #16 | 상품 페이지 수정 (isHidden 등) |

### 5-3. 수행 에이전트 — 유틸 Tools

| Tool | 설명 | 시나리오 |
|------|------|----------|
| `navigate` | 관리자센터 페이지 URL + 안내 텍스트 반환 (**신규**) | #1, #2, #10, #12, #16 |

### 5-4. 기존 Tool 중 제외 대상

POC에서 있었지만 멀티 에이전트에서 제외하거나 변경:

| Tool | 판단 | 이유 |
|------|------|------|
| `get_master_groups` | **유지** (조회) | 마스터 그룹 목록 필요 |
| `create_master_group` | **제외** | 시나리오에 없음. 마스터 생성은 에이전트 범위 밖 |
| `create_series` | **제외** | 파트너센터 이동 안내로 대체 (#12) |
| `create_product_page` | **제외** | 페이지 생성 = 관리자센터 UI에서 직접 (#1) |
| `create_product` | **제외** | 옵션 등록 = 관리자센터 UI에서 직접 |
| `update_product_sequence` | **보류** | 순서 변경은 활성화 플로우에서 필요할 수 있음 |
| `update_main_product_setting` | **보류** | 메인 상품 설정은 진단 후 활성화 시 필요 |
| `verify_product_setup` | **검증 에이전트로 이동** | diagnose_visibility가 대체 |

### 5-5. 신규 Tool

#### `get_community_settings`
```python
@tool
def get_community_settings(cms_id: str) -> dict:
    """오피셜클럽의 커뮤니티 설정을 조회한다.
    게시판(postBoardActiveStatus), 응원하기(donationActiveStatus) 상태를 확인할 수 있다.

    시나리오: #8(게시판 안 보임), #28(응원하기 안 보임)
    API: GET /v1/master/{cmsId}/community/category
    """
```

#### `navigate`
```python
@tool
def navigate(page: str, params: dict | None = None) -> dict:
    """관리자센터 페이지 이동 URL을 생성한다.
    직접 이동하지 않고, 사이드패널에 [이동] 버튼으로 제공한다.

    page 값:
    - "product_page_create": 상품 페이지 생성 (/product/page/create)
    - "product_page_edit": 상품 페이지 수정 (/product/page/{id}?tab=settings)
    - "product_create": 상품 옵션 등록 (/product/create?productGroupId={id})
    - "product_edit": 상품 옵션 수정 (/product/{id}/edit)
    - "partner_series": 파트너센터 시리즈 생성 (외부)
    - "official_club_create": 오피셜클럽 생성 (/official-club/create)
    - "board_setting": 게시판 설정 (/board/setting)
    - "donation": 응원하기 관리 (/donation)
    - "letter": 편지글 관리 (/cs/letter)
    - "main_product": 메인 상품 페이지 관리 (/master/{id}/main-product-group)

    시나리오: #1, #2, #8, #10, #12, #28
    """
```

### 5-6. 최종 Tool 수

| 에이전트 | Tool 수 | 목록 |
|----------|---------|------|
| 오케스트레이터 | 2 | executor(AgentTool), domain_expert(AgentTool) |
| 도메인 에이전트 | 0 | (RAG만 사용) |
| 수행 에이전트 | 11+1 | 조회 7 + 실행 3 + 유틸 1 + validator(AgentTool) |
| 검증 에이전트 | 3 | check_prerequisites, check_idempotency, diagnose_visibility |

---

## 6. 권한 기반 Tool 필터링

사이드패널이 에이전트에 전달하는 정보:
```json
{
  "roleType": "PART",
  "permissionSections": ["PRODUCT"],
  "currentPage": "/product/page/148"
}
```

Tool 필터링 매핑:
```python
PERMISSION_TOOL_MAP = {
    "PRODUCT": [
        "get_product_page_list", "get_product_page_detail",
        "get_product_list_by_page",
        "update_product_display", "update_product_page_status",
        "update_product_page",
    ],
    "MASTER": [
        "search_masters", "get_master_detail", "get_master_groups",
        "get_series_list", "get_community_settings",
        "update_main_product_setting",
    ],
}

# roleType에 따른 적용:
# ALL → 전체 Tool
# PART → permissionSections에 해당하는 Tool만
# NONE → 에이전트 사용 불가
```

---

## 7. interrupt() 사용 지점

Strands `interrupt()`로 유저 확인이 필요한 시점:

| 시점 | 예시 |
|------|------|
| 슬롯 필링 | "어떤 오피셜클럽?" / "어떤 상품 페이지?" |
| 목록 선택 | "1. 월간 투자 리포트 2. 단건 특강 — 어떤 페이지?" |
| 실행 확인 | "비공개 처리하시겠어요?" |
| 타입 선택 | "구독/단건 중 어떤 타입?" |

```python
# 수행 에이전트 내부
from strands import interrupt

# 슬롯이 비어있을 때
if not context.get("master_id"):
    response = interrupt({"question": "어떤 오피셜클럽인가요?"})
    # 유저 응답을 받아 search_masters 호출

# 실행 전 확인
confirmation = interrupt({
    "question": "비공개 처리하시겠어요?",
    "buttons": [
        {"type": "action", "label": "비공개 처리하기", ...},
        {"type": "navigate", "label": "직접 수정하기 →", ...},
    ]
})
```

---

## 8. 확장성 설계

### 8-1. 새 도메인 추가 시 변경점

현재는 "상품 세팅" 도메인만 지원. 향후 CS 환불, 배너 관리, 멤버십 조회 등이 추가될 때:

```
현재:
오케스트레이터 → 수행 에이전트(상품) + 도메인 에이전트

확장 후:
오케스트레이터 → 수행 에이전트(상품) + 수행 에이전트(CS) + 수행 에이전트(배너) + 도메인 에이전트
```

**원칙: 수행 에이전트를 도메인별로 분리**

수행 에이전트를 하나로 유지하면 Tool이 30개, 40개로 늘어나면서 정확도가 떨어진다.
도메인별로 수행 에이전트를 만들고, 오케스트레이터가 라우팅한다.

```python
# 오케스트레이터의 AgentTool 목록
orchestrator = Agent(
    tools=[
        AgentTool(product_executor, tool_name="product_executor",
                  tool_description="상품 세팅 관련 수행. 상품 페이지 CRUD, 활성화, 진단."),
        AgentTool(cs_executor, tool_name="cs_executor",
                  tool_description="CS 관련 수행. 환불 처리, 유저 조회."),
        AgentTool(banner_executor, tool_name="banner_executor",
                  tool_description="배너/프로모션 관련 수행."),
        AgentTool(domain_agent, tool_name="domain_expert",
                  tool_description="도메인 개념 설명."),
    ],
    ...
)
```

오케스트레이터의 분류 역할이 자연스럽게 확장된다:
- "상품 비공개해줘" → product_executor
- "환불 처리해줘" → cs_executor
- "배너 등록해줘" → banner_executor
- "상품 변경이 뭐야?" → domain_expert

### 8-2. 각 레이어의 변경 영향도

| 변경 사항 | 오케스트레이터 | 수행 에이전트 | 검증 에이전트 | 도메인 에이전트 |
|-----------|:-:|:-:|:-:|:-:|
| 새 도메인 지식 추가 | - | - | - | knowledge/*.md 추가 |
| 새 진단 시나리오 추가 | - | 진단 로직 추가 | VISIBILITY_CHAIN 확장 | - |
| 새 실행 액션 추가 | - | Tool 추가 | PREREQUISITES 추가 | - |
| 새 도메인 (CS 등) | AgentTool 추가 | 새 수행 에이전트 | 규칙 테이블 확장 | knowledge 추가 |
| 새 권한 섹션 | - | - | - | PERMISSION_TOOL_MAP 추가 |

### 8-3. 검증 에이전트 확장

검증 에이전트는 도메인에 무관한 패턴 기반:
- `PREREQUISITES` 딕셔너리에 새 액션-조건 추가만 하면 됨
- `VISIBILITY_CHAIN`도 새 체인 추가 가능 (ex: CS 환불 조건 체인)

```python
# 향후 CS 도메인 추가 시
PREREQUISITES["process_refund"] = ["user_id", "order_id", "refund_reason"]
PREREQUISITES["query_user"] = ["user_id"]

REFUND_CHAIN = [
    ("order_exists", "주문이 존재해야 합니다"),
    ("order_paid", "결제 완료 상태여야 합니다"),
    ("within_refund_period", "환불 가능 기간 내여야 합니다"),
]
```

### 8-4. navigate Tool 확장

새 도메인 페이지도 page 값만 추가:
```python
# 현재: 상품 관련 10개
# CS 추가 시:
"refund_detail": "/cs/refund/{id}"
"user_detail": "/user/{id}"
# 배너 추가 시:
"banner_create": "/banner/create"
```

---

## 9. 에러 처리

| 상황 | 에이전트 | 처리 |
|------|----------|------|
| API 400 | 수행 | 에러 분석 + 재시도 안내 |
| 토큰 만료 | 수행 | "세션이 만료되었습니다. 새로고침 후 다시 시도해주세요." |
| 권한 부족 | 오케스트레이터 | Tool 자체가 없으므로 "해당 기능에 대한 권한이 없습니다." |
| 범위 밖 요청 | 오케스트레이터 | "이 요청은 에이전트가 처리할 수 없습니다." (Guardrails) |
| 검증 실패 | 수행+검증 | missing 항목 안내 + 해결 가이드 |

---

## 10. 구현 순서

이 설계서 기반으로:

1. **수행 에이전트** — 기존 admin_api.py Tool을 정리 + 신규 Tool 2개 + 검증 에이전트 연동
2. **도메인 에이전트** — RAG 연동 (Bedrock Knowledge Base)
3. **오케스트레이터** — 분류 few-shot + SessionManager + AgentTool 조립
4. **통합 테스트** — 시나리오 32개 기반 eval
