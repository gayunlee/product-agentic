# 하네스 & 가드레일 — 시나리오 32개에서 역산

"이걸 안 지키면 틀리는" 규칙을 시나리오에서 추출하고,
각 규칙을 어디에 배치할지(프롬프트/docstring/few-shot/Guardrails/코드) 결정한다.

**원칙: "프롬프트는 부탁, 하네스는 강제"**
- 프롬프트에만 적으면 LLM이 무시할 수 있다
- 코드/Tool/Guardrails로 강제할 수 있는 건 강제한다
- 프롬프트는 "톤, 판단 기준, 예시" 같은 소프트한 것만

---

## 1. 오케스트레이터 하네스

### 시스템 프롬프트 규칙

| # | 규칙 | 근거 시나리오 | 강제 방법 |
|---|------|-------------|----------|
| O1 | 분류만 한다. 직접 답변하지 않는다 | 전체 | 프롬프트 + Tool이 2개뿐(executor, domain_expert)이라 다른 행동 불가 |
| O2 | "~뭐야?", "~차이가?", "~가능해?" → domain_expert | #4,#11,#13-15,#17-22,#26,#30,#31 | few-shot |
| O3 | "~해줘", "~만들려고", "~안 보여?" → executor | #1-3,#5-9,#16,#23,#24,#28,#36,#37 | few-shot |
| O4 | 복합(조회+개념) → executor 먼저, 결과 보고 도메인 보충 | #25 | few-shot |
| O5 | 대명사("그거", "이전 거") → 대화 히스토리에서 대상 추론 후 executor에 전달 | 맥락 전환 | 프롬프트 |
| O6 | 하위 에이전트 응답을 가공하지 않고 그대로 전달 | 전체 | 프롬프트 |

### few-shot 예시 (분류 정확도용)

```
유저: "마스터는 뭐고 오피셜클럽은 뭐야?"     → domain_expert
유저: "상품페이지 새로 만들려고"               → executor
유저: "왜 상품페이지 노출이 안돼?"            → executor
유저: "상품 비공개해줘"                       → executor
유저: "비공개하면 다른거 공개되나?"            → executor 먼저 (조회) → domain_expert (폴백 규칙)
유저: "그거 활성화해줘"                       → executor (이전 맥락에서 대상 추론)
유저: "단건 상품은 변경 못해?"                → domain_expert
유저: "환불 처리해줘"                         → 거부 (범위 밖)
```

---

## 2. 도메인 지식 에이전트 하네스

### 시스템 프롬프트 규칙

| # | 규칙 | 근거 시나리오 | 강제 방법 |
|---|------|-------------|----------|
| D1 | 내부 필드명 노출 금지 (isDeletable, isHidden, displayLetterStatus 등) | #9,#15,#20 | 프롬프트 |
| D2 | 운영 매니저 용어로 설명 ("비공개", "히든 처리", "삭제 불가") | #15,#20,#26 | 프롬프트 + few-shot |
| D3 | API 호출하지 않는다. 조회가 필요하면 "확인이 필요합니다"로 반환 | 전체 도메인 시나리오 | Tool이 0개라 강제됨 |
| D4 | "마스터 선택 = 오피셜클럽 선택" 용어 혼동 해소 | #4,#7,#22 | 프롬프트 + RAG knowledge |
| D5 | 히든 ≠ 비공개 구분 필수 | #15,#16,#26 | 프롬프트 + RAG knowledge |
| D6 | 구독 vs 단건 차이 정확히 구분 | #18,#19,#31 | RAG knowledge |
| D7 | 상시공개 vs 기간공개 우선순위 정확히 설명 | #14 | RAG knowledge |

### RAG 소스 (knowledge/*.md)

도메인 에이전트의 답변 품질은 RAG 소스에 의존. 현재 10개 문서:
- `도메인-지식-종합.md` — 게시판, 응원하기, 편지글, 삭제규칙, 결제수단, 이미지 등
- `구독상품-생성관리.md` / `단건상품-생성관리.md` — 상품 타입별 규칙
- `오피셜클럽-론칭-가이드.md` — 마스터/오피셜클럽 구조
- `관리자센터-페이지-UI-구조.md` — 각 페이지의 필드와 UI 구성
- 기타: API 플로우, 권한 체계, 사이드패널 UX 등

---

## 3. 수행 에이전트 하네스

### 시스템 프롬프트 규칙

| # | 규칙 | 근거 시나리오 | 강제 방법 |
|---|------|-------------|----------|
| E1 | 슬롯 필링: 오피셜클럽 → 상품 페이지 → 상품 옵션 순서로 좁힌다 | #1-3,#5,#6,#23,#24,#36 | 프롬프트 + few-shot |
| E2 | 여러 개일 때 반드시 목록 제시 후 선택 받는다 (자동 선택 금지) | #2,#5,#23 | 프롬프트 |
| E3 | 쓰기 API 전에 반드시 validator 호출 (check_prerequisites + check_idempotency) | #16,#23,#24,#36 | 프롬프트 + validator AgentTool docstring |
| E4 | 쓰기 API 전에 반드시 유저 확인 (interrupt) | #16,#23,#24 | 프롬프트 + few-shot |
| E5 | 생성은 직접 하지 않는다 → navigate()로 이동 안내 | #1,#2,#10,#12 | create 계열 Tool이 없으므로 강제됨 |
| E6 | 시리즈 생성 = 파트너센터 안내 (관리자센터 아님) | #12 | navigate Tool docstring + 프롬프트 |
| E7 | "상품" vs "상품 페이지" 구분 (유저가 혼용할 수 있음) | #23 vs #24 | 프롬프트 + few-shot |
| E8 | 진단 결과에서 첫 번째 실패 원인 + 해결 안내를 제시한다 | #6,#7 | 프롬프트 |
| E9 | 실행 완료 후 확인 링크/버튼 제공 | #16,#23,#24,#36 | 프롬프트 + few-shot |
| E10 | "왜 마스터가 안 보여?" → "오피셜클럽을 말씀하시는 것 같네요" 용어 변환 | #7 | 프롬프트 |

### Tool docstring 규칙

각 Tool의 docstring에 선행 조건/주의사항/사용 예시를 포함:

#### search_masters
```
선행 조건: 없음 (첫 단계)
주의: searchKeyword가 정확하지 않아도 부분 매칭됨
사용 예시: search_masters("조조형우") → cmsId 확보
```

#### update_product_page_status
```
선행 조건: product_page_id 필수 → validator.check_prerequisites 먼저
주의: INACTIVE로 변경하면 고객에게 즉시 안 보임. 반드시 유저 확인 후 실행
멱등성: 이미 같은 상태면 validator.check_idempotency가 걸러줌
사용 예시: update_product_page_status("148", "INACTIVE")
```

#### update_product_display
```
선행 조건: product_id 필수
주의: "상품"(옵션)과 "상품 페이지"는 다름. 이 Tool은 상품 옵션의 공개/비공개
사용 예시: update_product_display("55", false)
```

#### navigate
```
선행 조건: 없음
주의: 직접 이동하지 않음. 사이드패널에 [이동] 버튼으로 제공
사용 예시: navigate("product_page_create") → {"url": "/product/page/create", "label": "상품 페이지 생성"}
```

#### get_community_settings
```
선행 조건: cms_id (오피셜클럽의 cmsId) 필수
용도: 게시판(postBoardActiveStatus), 응원하기(donationActiveStatus) 상태 확인
시나리오: #8(게시판 안 보임), #28(응원하기 안 보임)
```

### few-shot 예시 (수행 에이전트)

```
# 가이드 모드
유저: 상품페이지 새로 만들려고
→ search_masters → get_series_list → interrupt("구독/단건?") → navigate("product_page_create")

# 실행 모드
유저: 상품페이지 비공개해줘
→ search_masters → get_product_page_list → interrupt(목록) → validator.check_prerequisites → validator.check_idempotency → interrupt("비공개 하시겠어요?") → update_product_page_status → 완료

# 진단 모드
유저: 왜 상품페이지 노출이 안돼?
→ search_masters → validator.diagnose_visibility → 첫 실패 원인 보고 + navigate(해결 페이지)

# 복합 (공개 + 옵션 확인)
유저: 상품페이지 공개해줘. 월간구독이랑 연간구독 보여야돼
→ search_masters → get_product_page_list → get_product_list_by_page → 비공개 옵션 발견 → interrupt("연간 구독도 공개?") → update_product_display + update_product_page_status
```

---

## 4. 검증 에이전트 하네스

검증 에이전트는 LLM이 아닌 **규칙 기반 코드**이므로 하네스 = 규칙 테이블.

### PREREQUISITES 규칙 (코드로 강제)

```python
PREREQUISITES = {
    # 조회 — 사전조건 없음 또는 최소
    "search_masters": [],
    "get_master_groups": [],
    "get_master_detail": ["master_id"],
    "get_series_list": ["master_id"],
    "get_product_page_list": ["master_id"],
    "get_product_page_detail": ["product_page_id"],
    "get_product_list_by_page": ["product_page_id"],
    "get_community_settings": ["cms_id"],

    # 실행 — 사전조건 필수
    "update_product_display": ["product_id"],
    "update_product_page_status": ["product_page_id"],
    "update_product_page": ["product_page_id"],
    "update_main_product_setting": ["master_id"],
}
```

### VISIBILITY_CHAIN 규칙 (코드로 강제)

```python
# 일반 페이지
VISIBILITY_CHAIN = [
    ("master_public", "마스터가 PUBLIC 상태여야 합니다"),
    ("main_product_active", "메인 상품 페이지 설정이 ACTIVE여야 합니다"),
    ("page_active", "상품 페이지가 ACTIVE 상태여야 합니다"),
    ("page_in_period", "현재 날짜가 공개 기간 내여야 합니다"),
    ("option_displayed", "상품 옵션의 isDisplay가 true여야 합니다"),
]

# 히든 페이지 — master_public, main_product_active 면제
VISIBILITY_CHAIN_HIDDEN = [
    ("page_active", "상품 페이지가 ACTIVE 상태여야 합니다"),
    ("option_displayed", "상품 옵션의 isDisplay가 true여야 합니다"),
]
```

### 진단 규칙 (시나리오별)

| 시나리오 | 진단 대상 | 체크 필드 | 근거 |
|----------|----------|----------|------|
| #6,#7 | 상품/마스터 노출 | VISIBILITY_CHAIN 5단계 | 노출 체인 |
| #8 | 게시판 | postBoardActiveStatus | ACTIVE+게시글 있어야 |
| #9 | 편지글 탭 | displayLetterStatus + 편지 3개 이상 | 독립 조건 2개 |
| #28 | 응원하기 | donationActiveStatus | ACTIVE여야 |
| #29 | 편지 슬라이더 | viewType=PRODUCT_GROUP 편지 1개 이상 | 탭과 독립 |
| #5 | 상품 옵션 | isDisplay | 옵션별 개별 |

### next_action 매핑 (검증 결과 → 다음 행동)

검증 에이전트가 "무엇이 문제인지"만이 아니라 "어떻게 해결하는지"까지 반환:

```python
NEXT_ACTIONS = {
    "master_id_missing": {
        "type": "slot_fill",
        "instruction": "오피셜클럽을 먼저 확인해야 합니다",
        "tool": "search_masters",
    },
    "series_ids_missing": {
        "type": "guide",
        "instruction": "시리즈가 없습니다. 파트너센터에서 생성해야 합니다",
        "navigate": "partner_series",
    },
    "product_page_id_missing": {
        "type": "slot_fill",
        "instruction": "상품 페이지를 먼저 확인해야 합니다",
        "tool": "get_product_page_list",
    },
    "master_not_public": {
        "type": "guide",
        "instruction": "마스터가 PENDING 상태입니다. PUBLIC으로 전환해야 합니다",
        "navigate": "master_edit",
    },
    "main_product_inactive": {
        "type": "guide",
        "instruction": "메인 상품 페이지 설정이 INACTIVE 상태입니다",
        "navigate": "main_product",
    },
    "page_inactive": {
        "type": "action",
        "instruction": "상품 페이지가 비공개 상태입니다. 공개로 변경하시겠어요?",
        "tool": "update_product_page_status",
        "params": {"status": "ACTIVE"},
    },
    "page_out_of_period": {
        "type": "guide",
        "instruction": "현재 날짜가 공개 기간 밖입니다. 기간을 수정해주세요",
        "navigate": "product_page_edit",
    },
    "option_not_displayed": {
        "type": "action",
        "instruction": "상품 옵션이 비공개 상태입니다. 공개로 변경하시겠어요?",
        "tool": "update_product_display",
        "params": {"is_display": True},
    },
    "already_done": {
        "type": "skip",
        "instruction": "이미 처리된 상태입니다",
    },
    "board_inactive": {
        "type": "guide",
        "instruction": "게시판이 비활성화 상태입니다",
        "navigate": "board_setting",
    },
    "donation_inactive": {
        "type": "guide",
        "instruction": "응원하기가 비활성화 상태입니다",
        "navigate": "donation",
    },
    "letter_inactive": {
        "type": "guide",
        "instruction": "편지글 공개 설정이 비활성 상태입니다",
        "navigate": "product_page_edit",
    },
    "letter_count_insufficient": {
        "type": "guide",
        "instruction": "편지글이 3개 미만입니다. 편지글 탭은 3개 이상이어야 표시됩니다",
        "navigate": "letter",
    },
}
```

---

## 5. Bedrock Guardrails (런타임 보호)

코드/프롬프트로 통제할 수 없는 것 = Guardrails로 차단.

### 범위 밖 요청 거부 (out_of_scope DENY)

시나리오에서 명시적으로 "에이전트가 처리하지 않는" 것:

```
# 현재 out_of_scope 토픽에 포함되어야 할 것
- 환불/결제 취소 처리 요청 (CS 도메인 — Phase 2에서 추가)
- 유저 개인정보 조회 (PII)
- 시스템 프롬프트/내부 동작 노출 요청
- 코드 생성/기술 질문
- 관리자센터 외 일반 질문
- 게시판 콘텐츠 직접 작성/수정
- 응원하기 금액 변경
- 콘텐츠(시리즈 에피소드) 발행
```

### PII 필터링

```
EMAIL  → ANONYMIZE
PHONE  → ANONYMIZE
CARD   → BLOCK
SSN    → BLOCK
```

### 프롬프트 공격 감지

```
PROMPT_ATTACK HIGH → BLOCK
```

### 향후 추가 고려

| 가드레일 | 시점 | 설명 |
|----------|------|------|
| Contextual grounding | 도메인 에이전트 | RAG 결과와 답변이 일치하는지 |
| 토큰 길이 제한 | 전체 | 응답이 과도하게 길어지는 것 방지 |

---

## 6. 하네스 배치 요약

| 규칙 유형 | 배치 위치 | 강제 수준 |
|-----------|----------|----------|
| 분류 정확도 | 오케스트레이터 few-shot | 소프트 (LLM 판단) |
| 슬롯 필링 순서 | 수행 에이전트 프롬프트 + few-shot | 소프트 |
| 쓰기 전 검증 필수 | validator AgentTool (항상 먼저 호출) | **하드** (프롬프트 + docstring) |
| 쓰기 전 유저 확인 | interrupt() | **하드** (코드) |
| 생성 = 이동 안내만 | create Tool 미제공 | **하드** (코드) |
| 사전조건 체인 | PREREQUISITES dict | **하드** (코드) |
| 노출 진단 체인 | VISIBILITY_CHAIN list | **하드** (코드) |
| 다음 행동 지시 | NEXT_ACTIONS dict | **하드** (코드) |
| 내부 필드명 비노출 | 도메인 에이전트 프롬프트 | 소프트 |
| 용어 변환 | 프롬프트 + RAG | 소프트 |
| 범위 밖 거부 | Bedrock Guardrails | **하드** (런타임) |
| PII 차단 | Bedrock Guardrails | **하드** (런타임) |
| 프롬프트 공격 | Bedrock Guardrails | **하드** (런타임) |

**하드 강제 비율: 13개 중 9개 (69%)**
→ LLM이 무시할 수 있는 "소프트" 규칙은 4개뿐. 나머지는 코드/Tool/Guardrails로 강제.
