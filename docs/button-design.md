# 사이드패널 버튼 설계

수행 에이전트가 응답에 포함하는 구조화된 버튼.
**에이전트가 맥락을 알고 버튼을 결정** — 서버 텍스트 파싱 아님.

---

## 버튼 타입

| type | 용도 | 클릭 시 동작 |
|------|------|-------------|
| `navigate` | 관리자센터 페이지 이동 | 라우터 이동 (내부) 또는 새 탭 (외부) |
| `action` | 에이전트에 실행 요청 | 라벨을 자연어로 에이전트에 전달 |
| `select` | 목록에서 선택 | 선택한 항목을 에이전트에 전달 |

---

## 시나리오별 버튼 매핑

### 진단 모드 (#5, #6, #7, #8, #9, #28)

**원인 발견 시 — 해결 가능한 경우:**

| 원인 | 버튼 |
|------|------|
| 메인 상품 INACTIVE | `action: "메인 상품 페이지 활성화"` + `navigate: "메인 상품 페이지 관리" → /product/page/list` |
| 상품 페이지 INACTIVE | `action: "상품 페이지 공개 처리"` + `navigate: "상품 페이지 수정" → /product/page/{id}?tab=settings` |
| 상품 옵션 비공개 | `action: "상품 옵션 공개 처리"` + `navigate: "상품 옵션 관리" → /product/page/{id}?tab=options` |
| 마스터 PENDING | `navigate: "오피셜클럽 상세" → /official-club/{masterId}` (에이전트가 직접 변경 불가) |
| 게시판 INACTIVE | `navigate: "게시판 설정" → /board/setting` |
| 응원하기 INACTIVE | `navigate: "응원하기 관리" → /donation` |
| 편지글 비공개 | `navigate: "상품 페이지 수정" → /product/page/{id}?tab=settings` |

**이미 정상인 경우:**
- 버튼 없음 또는 `navigate: "설정 확인" → 해당 페이지` 만

### 가이드 모드 (#1, #2, #10, #12)

| 시나리오 | 버튼 |
|----------|------|
| #1 상품페이지 생성 | `navigate: "상품 페이지 생성" → /product/page/create` |
| #2 상품페이지 수정 | `select: 페이지 목록` → 선택 후 `navigate: "상품 페이지 수정" → /product/page/{id}?tab=settings` |
| #10 편지글 세팅 | `navigate: "편지글 관리" → /cs/letter` 또는 `navigate: "상품 페이지 수정" → /product/page/{id}?tab=settings` |
| #12 시리즈 생성 | `navigate: "파트너센터" → https://master.us-insight.com` (외부) |

### 실행 모드 (#16, #23, #24, #36)

**실행 전 확인 단계:**

| 시나리오 | 버튼 |
|----------|------|
| #23 상품 비공개 | `action: "비공개 처리하기"` + `navigate: "직접 수정" → /product/page/{id}?tab=options` |
| #24 상품페이지 비공개 | `action: "비공개 처리하기"` + `navigate: "직접 수정" → /product/page/{id}?tab=settings` |
| #36 상품페이지 공개 | `action: "공개 처리하기"` + `navigate: "직접 수정" → /product/page/{id}?tab=settings` |
| #16 히든 처리 | `action: "히든 처리하기"` + `navigate: "직접 수정" → /product/page/{id}?tab=settings` |

**실행 완료 후:**
- `navigate: "결과 확인" → 해당 페이지` (action 버튼 없음)

### 선택 모드 (슬롯 필링)

**오피셜클럽 선택 (1개만 있으면 자동):**
- `select` 버튼 없음 (자동 선택)

**상품 페이지 선택 (여러 개):**
```json
[
  {"type": "select", "label": "월간 투자 리포트 (코드: 148, 공개)", "value": "mock_page_001"},
  {"type": "select", "label": "단건 특강 (코드: 155, 비공개)", "value": "mock_page_002"}
]
```

**상품 옵션 선택 (여러 개):**
```json
[
  {"type": "select", "label": "월간 구독 (29,900원, 공개)", "value": "99999"},
  {"type": "select", "label": "연간 구독 (299,000원, 비공개)", "value": "99998"}
]
```

### 런칭 체크리스트 (#37)

체크 결과에 따라:
- 부족한 항목별 `action` 또는 `navigate` 버튼
- 전부 OK면 버튼 없음

---

## 응답 포맷

수행 에이전트가 응답 끝에 JSON 블록으로 버튼을 포함:

```
진단 결과 텍스트...

```json:buttons
[
  {"type": "action", "label": "메인 상품 페이지 활성화", "variant": "primary"},
  {"type": "navigate", "label": "메인 상품 페이지 관리", "url": "/product/page/list", "variant": "secondary"}
]
```
```

**규칙:**
- 이미 해당 상태면 action 버튼 생략 (ACTIVE인데 "활성화" 버튼 X)
- 에이전트가 직접 실행 가능하면 action, 불가능하면 navigate만
- action + navigate 짝으로 제공 (직접 실행 or 직접 수정 선택)
- 완료 응답에는 action 없이 navigate만
- select는 목록 선택이 필요할 때만

---

## 서버 파싱

서버(`server.py`)에서 `\`\`\`json:buttons` 블록을 파싱:

```python
def _extract_buttons(text: str) -> tuple[str, list[dict]]:
    """텍스트에서 buttons JSON 블록을 추출하고 제거."""
    match = re.search(r'```json:buttons\s*\n(.*?)\n```', text, re.DOTALL)
    if match:
        buttons = json.loads(match.group(1))
        clean_text = text[:match.start()].rstrip()
        return clean_text, buttons
    return text, []
```
