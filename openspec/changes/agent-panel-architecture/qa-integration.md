# QA 에이전트 + Web MCP 통합 가이드

## 시스템 구성

```
us-product-agent (세팅 에이전트)     ← localhost:8000
  └─ verify_settings(context, checks)
      └─ POST localhost:8001/verify
          └─ us-explorer-agent (QA 에이전트)  ← localhost:8001
              └─ Playwright → us-plus (localhost:3000)
                  └─ navigator.modelContext.callTool() (Web MCP)
```

## 레포 위치

| 컴포넌트 | 레포/경로 | 브랜치 |
|----------|----------|--------|
| 세팅 에이전트 | `/Users/gygygygy/Documents/ai/us-product-agent` | main |
| QA 에이전트 | `/Users/gygygygy/Documents/ai/us-explorer-agent` | - |
| Web MCP (us-plus) | `/Users/gygygygy/Documents/us/us-web` | feature/web-mcp (worktree: `.claude/worktrees/web-mcp`) |

## 세팅 방법

### 1. us-plus 로컬 서버 (Web MCP 포함)

```bash
cd /Users/gygygygy/Documents/us/us-web/.claude/worktrees/web-mcp
pnpm dev:local --filter=us-plus
# → localhost:3000
```

### 2. QA 에이전트 서버

```bash
cd /Users/gygygygy/Documents/ai/us-explorer-agent

# .env 설정
US_PLUS_BASE_URL=http://localhost:3000
US_PLUS_PHONE=<테스트 계정 전화번호>
US_PLUS_PASSWORD=<테스트 계정 비밀번호>

uv run python server.py
# → localhost:8001
```

### 3. 세팅 에이전트 서버

```bash
cd /Users/gygygygy/Documents/ai/us-product-agent

# .env에 추가
EXPLORER_AGENT_URL=http://localhost:8001

uv run python server.py
# → localhost:8000
```

---

## Web MCP Tool 목록 (us-plus에 구현됨)

### 구독 페이지 (`/subscribe`)

| Tool | 위치 | 반환 |
|------|------|------|
| `get_displayed_clubs` | `widgets/master/ui/MasterCardGrid` | `{ clubs: [{ order, productGroupCode, viewStatus, webLink, isButtonActive, buttonLabel }] }` |
| `get_master_recommend_list` | 동일 | `{ masters: [{ cmsId, hasProductGroup, productGroupCode, viewStatus }] }` |
| `get_subscribe_club_detail` | 동일 | `{ found, cardVisible, buttonVisible, buttonLabel, webLink }` |

### 상품 페이지 (`/products/group/[code]`)

| Tool | 위치 | 반환 |
|------|------|------|
| `get_product_page_state` | `app/products/group/[productGroupId]/page.tsx` | `{ status, displayedProductCount, canApply, products, hasLetterSection }` |

### 오피셜클럽 페이지 (`/club/[masterId]`)

| Tool | 위치 | 반환 |
|------|------|------|
| `get_club_page_state` | `app/club/[masterId]/(officialClub)/layout.tsx` | `{ isMembershipBannerVisible, webLink, webLinkStatus, clubStatus }` |

### 에러 페이지

| Tool | 위치 | 반환 |
|------|------|------|
| `get_page_error_state` | `app/not-found.tsx` | `{ isError, is404, errorType, errorMessage, currentUrl }` |

---

## QA 에이전트 check 함수 (us-explorer-agent)

### 구현됨

| check 함수 | 인자 | 확인 내용 |
|------------|------|----------|
| `check_subscribe_page` | `product_group_code: int` | 구독 탭에서 특정 상품페이지 노출 여부 |
| `check_product_page` | `code: int` | 상품 상세 페이지 접근 + 상품 개수 |
| `check_direct_url_access` | `code: int` | URL 직접 접근 가능 여부 (히든 검증) |
| `check_club_page` | `master_id: str` | 오피셜클럽 홈 멤버십 배너 상태 |

### 추가 필요

| check 함수 | 인자 | 확인 내용 | Web MCP Tool |
|------------|------|----------|-------------|
| `check_master_recommend` | `cms_id: str` | 마스터 추천 목록에서 노출 여부 | `get_master_recommend_list` |
| `check_subscribe_club` | `cms_id: str` | 구독 탭에서 오피셜클럽 카드 상태 | `get_subscribe_club_detail` |

---

## 세팅→검증 사이클 예시

### "마스터 PRIVATE로 바꿨을 때"

```python
# 세팅 에이전트가 admin API로 마스터 비공개 처리 후:
verify_settings(
    context={
        "master": { "cmsId": "35", "name": "조조형우", "publicType": "PRIVATE" },
    },
    checks=[
        {
            "tool": "check_master_recommend",
            "args": { "cms_id": "35" },
            "expected": { "found": False }
        },
        {
            "tool": "check_subscribe_club",
            "args": { "cms_id": "35" },
            "expected": { "found": False }
        },
        {
            "tool": "check_club_page",
            "args": { "master_id": "35" },
            "expected": { "accessible": False }
        },
    ]
)
```

### "메인 상품페이지 EXCLUDED로 바꿨을 때"

```python
verify_settings(
    context={
        "master": { "cmsId": "35", "publicType": "PUBLIC" },
        "mainProduct": { "viewStatus": "EXCLUDED" },
    },
    checks=[
        {
            "tool": "check_subscribe_club",
            "args": { "cms_id": "35" },
            "expected": { "found": True, "buttonVisible": False }
        },
    ]
)
```

### "상품페이지 INACTIVE + 히든 URL 접근"

```python
verify_settings(
    context={ ... },
    checks=[
        {
            "tool": "check_product_page",
            "args": { "code": 148 },
            "expected": { "accessible": False, "errorMessage": "공개되지 않은 상품 페이지입니다" }
        },
        {
            "tool": "check_direct_url_access",
            "args": { "code": 149 },  # 히든 페이지
            "expected": { "accessible": True }
        },
    ]
)
```

---

## 테스트 매트릭스 — 마스터/오피셜클럽 레벨 (미확인)

아래 조합을 세팅→검증 사이클로 실증 필요:

| # | 마스터 publicType | 메인상품 viewStatus | 상품페이지 status | expected |
|---|-------------------|--------------------|--------------------|----------|
| 1 | PUBLIC | ACTIVE | ACTIVE | 구독탭 카드 O, 버튼 O, 상세 접근 O |
| 2 | PUBLIC | EXCLUDED | ACTIVE | 구독탭 카드 O, 버튼 X, 상세 URL 접근 O |
| 3 | PUBLIC | ACTIVE | INACTIVE | 구독탭 카드 O, 버튼 O → 상세 접근 X |
| 4 | PRIVATE | ACTIVE | ACTIVE | 구독탭 카드 ?, 추천 목록 ? |
| 5 | PRIVATE | EXCLUDED | - | 구독탭 ?, 추천 목록 X |
| 6 | PUBLIC | ACTIVE | ACTIVE(히든) | 구독탭 ?, URL 직접 접근 O |

`?` = 미확인. 세팅→검증 사이클로 채워야 할 부분.

---

## 다음 단계

1. **us-explorer-agent에 check 함수 2개 추가** (`check_master_recommend`, `check_subscribe_club`)
2. **3개 서버 동시 구동** (us-plus + explorer + product-agent)
3. **테스트 매트릭스 실행** — 세팅 에이전트로 세팅 변경 → QA 에이전트로 검증 → 결과 기록
4. **결과를 knowledge/에 반영** — 확정된 노출 규칙 업데이트
5. **진단 위저드 설계** — 확정된 규칙 기반으로 각 레벨별 진단 로직
