# 응답 템플릿 시스템 설계

LLM은 판단+요약만, 포맷/버튼은 코드로 일관성 보장.

---

## 구조

```
수행 에이전트 → AgentResponse(type, summary, data) 반환
                        ↓
서버 → render_response(resp)
       ├─ HEADERS[type]           → 헤더
       ├─ resp.summary            → LLM 요약 (1~2줄)
       ├─ BODY_RENDERERS[type]    → 구조화 본문
       └─ BUTTON_PATTERNS[type]   → 버튼 배열
                        ↓
ChatResponse(message, buttons, mode)
```

## Response Types (6개)

| type | 용도 | body | buttons |
|------|------|------|---------|
| `diagnose` | 노출 진단 결과 | checklist (✅/❌) | fix+navigate 또는 navigate만 |
| `confirm` | 상태 변경 전 확인 | change_preview | action+navigate |
| `complete` | 실행 완료 | result | navigate만 |
| `guide` | 페이지 이동 안내 | steps | navigate |
| `info` | 정보 조회/표시 | table | 없음 |
| `select` | 목록에서 선택 | item_list | select items |

## 시나리오 매핑

| 시나리오 | type | 설명 |
|----------|------|------|
| #5,#6,#7,#8,#9,#28 | diagnose | "왜 안 보여?" 진단 |
| #37 | diagnose | 런칭 체크리스트 |
| #23,#24 | confirm → complete | 비공개 처리 |
| #36 | confirm → complete | 공개 처리 |
| #16 | confirm → complete | 히든 처리 |
| #1 | guide | 상품 페이지 생성 안내 |
| #2 | select → guide | 수정할 페이지 선택 → 이동 |
| #10 | guide | 편지글 세팅 안내 |
| #12 | guide | 시리즈 생성 (파트너센터) |
| #3 | info | 상품 페이지 조회 |
| #25 | info | 복합 조회 |

## AgentResponse 스키마

```python
@dataclass
class AgentResponse:
    type: str       # "diagnose" | "confirm" | "complete" | "guide" | "info" | "select"
    summary: str    # LLM 생성 요약 (1~2줄)
    data: dict      # type별 필수 데이터 (아래 참조)
```

### type별 data 스키마

```python
# diagnose
{
    "master_name": "봄날의 햇살",
    "checks": [
        {"name": "마스터 PUBLIC", "ok": True, "value": "PUBLIC"},
        {"name": "메인 상품 ACTIVE", "ok": False, "value": "INACTIVE"},
    ],
    "first_failure": "메인 상품 ACTIVE",  # None이면 정상
    "fix_label": "메인 상품 페이지 활성화",  # first_failure 있을 때
    "nav_url": "/product/page/list",
}

# confirm
{
    "target": "월간 투자 리포트 페이지",
    "action_label": "비공개 처리하기",
    "change": {"field": "상태", "from": "공개", "to": "비공개"},
    "edit_url": "/product/page/123?tab=settings",
}

# complete
{
    "target": "월간 투자 리포트 페이지",
    "action_done": "비공개 처리",
    "confirm_url": "/product/page/123?tab=settings",
}

# guide
{
    "label": "상품 페이지 생성",
    "url": "/product/page/create",
    "steps": ["오피셜클럽 선택", "정보 입력", "이미지 등록"],  # 선택
}

# info
{
    "title": "조조형우 상품 페이지 목록",
    "items": [
        {"제목": "월간 투자 리포트", "상태": "공개", "코드": 148},
    ],
}

# select
{
    "question": "어떤 상품 페이지를 수정하시겠어요?",
    "items": [
        {"label": "월간 투자 리포트 (공개)", "value": "mock_page_001"},
        {"label": "단건 특강 (비공개)", "value": "mock_page_002"},
    ],
}
```

## Body 렌더러 (5개)

```python
def render_checklist(data) -> str:
    # | 항목 | 상태 |
    # |------|------|
    # | 마스터 | ✅ PUBLIC |

def render_preview(data) -> str:
    # 대상: 월간 투자 리포트
    # 변경: 상태 공개 → 비공개

def render_result(data) -> str:
    # ✅ 월간 투자 리포트 — 비공개 처리 완료

def render_steps(data) -> str:
    # 1. 오피셜클럽 선택
    # 2. 정보 입력

def render_table(data) -> str:
    # | 제목 | 상태 | 코드 |
    # |------|------|------|

def render_item_list(data) -> str:
    # 1. 월간 투자 리포트 (공개)
    # 2. 단건 특강 (비공개)
```

## Button 패턴 (6개)

```python
BUTTON_PATTERNS = {
    "diagnose": lambda d:
        [action(d["fix_label"]), navigate("설정 관리", d["nav_url"])]
        if d.get("first_failure")
        else [navigate("설정 확인", d["nav_url"])],

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

    "select": lambda d: [
        select(item["label"], item["value"])
        for item in d["items"]
    ],

    "info": lambda d: [],
}
```

## 구현 계획

1. `src/agents/response.py` — AgentResponse, 렌더러, 버튼 패턴
2. `src/agents/executor.py` — structured_output으로 AgentResponse 반환
3. `server.py` — render_response() 호출, json:buttons 파싱 제거
4. 시나리오 테스트 재실행
