# 응답 템플릿 시스템 설계 (최종)

에이전트는 파라미터만 반환, respond Tool이 렌더링+버튼+후속질문 결정.

---

## 아키텍처

```
오케스트레이터(LLM) → 분류 + handoff (응답 생성 안 함)
                       ↓
수행 에이전트(LLM) → Tool 호출 + 판단 → respond(type, summary, data)
                                            ↓
respond Tool (코드) → 헤더 + 요약 + 본문 + 후속질문 + 버튼
                       ↓
서버 → 그대로 전달 → 사이드패널
```

---

## Response Types (9개)

| type | 용도 | 렌더러 | 버튼 | 후속 질문 |
|------|------|--------|------|----------|
| `diagnose` | 노출/상태 진단 | checklist | fix있으면 action+nav, 없으면 nav만 | "해결해드릴까요?" / "다른 확인?" |
| `confirm` | 실행 전 확인 | preview | action+nav | (질문 자체가 확인) |
| `complete` | 실행 완료 | result | nav만 | "다른 작업이 필요하시면 말씀해주세요." |
| `guide` | 페이지 이동 안내 | steps | nav | "완료하시면 말씀해주세요." |
| `info` | 정보 조회 | table | fix있으면 action+nav, 없으면 없음 | "활성화 필요하신가요?" / "수정 필요하시면 말씀해주세요." |
| `select` | 목록 선택 | item_list | select들 | (질문 자체가 선택) |
| `slot_question` | 추가 정보 질문 | 없음 | items있으면 select, 없으면 없음 | (질문 자체) |
| `error` | API 에러/토큰 만료 | 없음 | guide있으면 nav | 에러별 안내 |
| `reject` | 범위 밖/불가능 | 없음 | 없음 | "상품 세팅 관련 요청만 도와드릴 수 있습니다." |

---

## data 스키마

### diagnose
```json
{
    "master_name": "봄날의 햇살",
    "checks": [
        {"name": "오피셜클럽 공개", "ok": true, "value": "PUBLIC"},
        {"name": "메인 상품 ACTIVE", "ok": false, "value": "INACTIVE"}
    ],
    "first_failure": "메인 상품 ACTIVE",
    "fix_label": "메인 상품 페이지 활성화",
    "nav_url": "/product/page/list",
    "follow_up": "해결해드릴까요?"
}
```

### confirm
```json
{
    "target": "단건상품 (코드: 141)",
    "action_label": "비공개 처리하기",
    "change": {"field": "상태", "from": "공개", "to": "비공개"},
    "edit_url": "/product/page/688c0f34?tab=settings"
}
```

### complete
```json
{
    "target": "단건상품 (코드: 141)",
    "action_done": "비공개 처리",
    "confirm_url": "/product/page/688c0f34?tab=settings",
    "follow_up": "다른 작업이 필요하시면 말씀해주세요."
}
```

### guide
```json
{
    "label": "상품 페이지 생성",
    "url": "/product/page/create",
    "steps": ["마스터 선택", "정보 설정", "이미지 등록", "저장"],
    "follow_up": "완료하시면 말씀해주세요."
}
```

### info
```json
{
    "title": "조조형우 상태",
    "items": [
        {"항목": "오피셜클럽", "상태": "✅ PUBLIC"},
        {"항목": "메인 상품", "상태": "❌ INACTIVE"}
    ],
    "follow_up": "활성화가 필요하신가요?",
    "fix_label": "메인 상품 활성화",
    "nav_url": "/product/page/list"
}
```

### select
```json
{
    "question": "어떤 상품 페이지를 비공개 하시겠어요?",
    "items": [
        {"label": "단건상품 (코드: 141, 공개)", "value": "688c0f34"},
        {"label": "테스트 (코드: 155, 공개)", "value": "687abcde"}
    ]
}
```

### slot_question
```json
{
    "question": "어떤 오피셜클럽인가요?",
    "items": [
        {"label": "구독상품", "value": "SUBSCRIPTION"},
        {"label": "단건상품", "value": "ONE_TIME_PURCHASE"}
    ]
}
```
items 없으면 텍스트 입력 대기, 있으면 select 버튼.

### error
```json
{
    "error_type": "token_expired",
    "guide": "관리자센터에 다시 로그인해주세요.",
    "nav_url": "/login"
}
```

### reject
```json
{
    "reason": "환불 처리는 CS 도메인입니다.",
    "follow_up": "상품 세팅 관련 요청만 도와드릴 수 있습니다."
}
```

---

## 렌더링 포맷

### diagnose (문제 발견)
```
📊 노출 진단 결과

메인 상품 페이지가 INACTIVE 상태입니다

| 항목 | 상태 |
|------|------|
| 오피셜클럽 공개 | ✅ PUBLIC |
| 메인 상품 ACTIVE | ❌ INACTIVE ← 원인 |
| 상품 페이지 ACTIVE | ✅ 2개 ACTIVE |

해결해드릴까요?

[메인 상품 페이지 활성화] [설정 관리 →]
```

### diagnose (정상)
```
📊 노출 진단 결과

모든 노출 조건이 충족되어 있습니다

| 항목 | 상태 |
|------|------|
| 오피셜클럽 공개 | ✅ PUBLIC |
| 메인 상품 ACTIVE | ✅ ACTIVE |

다른 확인이 필요하신가요?

[설정 확인 →]
```

### confirm
```
⚡ 실행 확인

단건상품 페이지를 비공개 처리합니다

**대상**: 단건상품 (코드: 141)
**변경**: 상태 `공개` → `비공개`

[비공개 처리하기] [직접 수정 →]
```

### complete
```
✅ 완료

**단건상품 (코드: 141)** — 비공개 처리 완료

다른 작업이 필요하시면 말씀해주세요.

[결과 확인 →]
```

### guide
```
🔗 안내

상품 페이지 생성 화면으로 이동해주세요

1. 마스터 선택
2. 정보 설정
3. 이미지 등록
4. 저장

완료하시면 말씀해주세요.

[상품 페이지 생성 →]
```

### info (문제 발견)
```
📄 조회 결과

조조형우 오피셜클럽 상태입니다

| 항목 | 상태 |
|------|------|
| 오피셜클럽 | ✅ PUBLIC |
| 메인 상품 | ❌ INACTIVE |

활성화가 필요하신가요?

[메인 상품 활성화] [설정 관리 →]
```

### info (정상)
```
📄 조회 결과

조조형우 오피셜클럽 상태입니다

| 항목 | 상태 |
|------|------|
| 오피셜클럽 | ✅ PUBLIC |
| 메인 상품 | ✅ ACTIVE |

수정이 필요하시면 말씀해주세요.
```

### select
```
📋 선택

어떤 상품 페이지를 비공개 하시겠어요?

[단건상품 (코드: 141, 공개)] [테스트 (코드: 155, 공개)]
```

### slot_question (선택지 있음)
```
구독상품과 단건상품 중 어떤 타입으로 만드시겠어요?

[구독상품] [단건상품]
```

### slot_question (선택지 없음)
```
어떤 오피셜클럽인가요?
```

### error
```
⚠️ 오류

토큰이 만료되었습니다

관리자센터에 다시 로그인해주세요.
```

### reject
```
🚫 요청 불가

환불 처리는 CS 도메인입니다.

상품 세팅 관련 요청만 도와드릴 수 있습니다.
```

---

## 로딩 진행 상황 (COT)

respond Tool 호출 전, 각 Tool 호출 시 진행 상황을 실시간 표시:

| Tool | 진행 메시지 |
|------|------------|
| search_masters | 🔍 오피셜클럽 검색 중... |
| get_product_page_list | 📦 상품 페이지 조회 중... |
| diagnose_visibility | 📊 노출 체인 진단 중... |
| check_prerequisites | ✅ 사전조건 확인 중... |
| update_* | ⚡ 상태 변경 중... |
| retrieve | 📚 도메인 지식 검색 중... |
| respond | 📝 결과 정리 중... |

사이드패널에서 SSE 또는 폴링으로 표시.

---

## 버튼 패턴 (9개)

```python
BUTTON_PATTERNS = {
    "diagnose": lambda d:
        [action(d["fix_label"]), navigate("설정 관리", d["nav_url"])]
        if d.get("first_failure")
        else [navigate("설정 확인", d.get("nav_url", "/product/page/list"))],

    "confirm": lambda d: [
        action(d["action_label"]),
        navigate("직접 수정", d["edit_url"]),
    ],

    "complete": lambda d: [
        navigate("결과 확인", d["confirm_url"]),
    ],

    "guide": lambda d: [
        navigate(d["label"], d["url"]),
    ],

    "info": lambda d:
        [action(d["fix_label"]), navigate("설정 관리", d["nav_url"])]
        if d.get("fix_label")
        else [],

    "select": lambda d: [
        select(item["label"], item["value"])
        for item in d.get("items", [])
    ],

    "slot_question": lambda d:
        [select(item["label"], item["value"]) for item in d.get("items", [])]
        if d.get("items")
        else [],

    "error": lambda d:
        [navigate("이동", d["nav_url"])]
        if d.get("nav_url")
        else [],

    "reject": lambda d: [],
}
```

---

## 도메인 에이전트

respond Tool 사용 안 함. RAG + LLM 자연어 직접 응답. 버튼 없음.
오케스트레이터가 도메인 응답을 그대로 전달.

---

## 시나리오별 흐름 요약

| 시나리오 | 흐름 |
|----------|------|
| #5,#6,#7 진단 | slot_question → diagnose |
| #8,#28 게시판/응원 | slot_question → diagnose |
| #9 편지글 | slot_question → select → diagnose |
| #37 체크리스트 | slot_question → diagnose |
| #23,#24 비공개 | slot_question → select → confirm → complete |
| #36 공개 | slot_question → select → confirm → complete |
| #16 히든 | slot_question → select → confirm → complete |
| #1 생성 | slot_question → guide |
| #2 수정 | slot_question → select → guide |
| #10 편지글 세팅 | slot_question → guide |
| #12 시리즈 | guide |
| #3 조회 | slot_question → info |
| #25 복합 | slot_question → info |
| 범위 밖 | reject |
| API 에러 | error |
