# QA 테스트 계획 — 노출 조건 전체 검증

## 목표

각 세팅 조합이 us-plus에서 어떻게 보이는지 체계적으로 확인하여, 진단 위저드의 기반 규칙을 확정한다.

---

## 1. 현재 상태

### QA 에이전트 (us-explorer-agent) — check 함수

| check 함수 | 상태 | 비고 |
|------------|------|------|
| `check_subscribe_page(product_group_code)` | ✅ 동작 | 멤버십 구독 탭 카드 |
| `check_master_recommend(cms_id)` | ✅ 동작 | 마스터 추천 탭 |
| `check_subscribe_club(cms_id)` | ✅ 구현됨 | 구독 탭 카드 상세 (조회키 productGroupCode 주의) |
| `check_product_page(code)` | ✅ 동작 | 상품 상세 페이지 |
| `check_direct_url_access(code)` | ✅ 동작 | URL 직접 접근 (히든 검증) |
| `check_club_page(master_id)` | ✅ 에러 핸들링 적용 | tool 미등록 시 accessible=false |
| `check_my_master_feed(cms_id)` | ❌ 미구현 | /feed 나의 마스터 영역 |

### Web MCP (us-plus) — tool

| tool | 페이지 | 상태 | 비고 |
|------|--------|------|------|
| `get_displayed_clubs` | /subscribe (멤버십 구독 탭) | ✅ | |
| `get_master_recommend_list` | /subscribe (마스터 추천 탭) | ✅ | enabled 제거로 양쪽 탭 다 등록됨 |
| `get_subscribe_club_detail` | /subscribe (멤버십 구독 탭) | ✅ | 조회키: productGroupCode (cmsId 아님) |
| `get_product_page_state` | /products/group/[code] | ✅ | |
| `get_club_page_state` | /club/[masterId] | ✅ | PRIVATE면 렌더링 안 됨 → tool 미등록 |
| `get_page_error_state` | not-found | ✅ | |
| `get_my_master_feed` | /feed | ❌ 미구현 | MyMasterSwiper 데이터 |

---

## 2. 추가 구현 필요

### Web MCP (us-plus) — 1개 추가

**`get_my_master_feed`** — `/feed` 페이지 MyMasterSwiper 컴포넌트

```typescript
// /feed 페이지 또는 MyMasterSwiper 컴포넌트에 등록
webmcp.register({
  name: 'get_my_master_feed',
  description: '나의 마스터 피드에 표시되는 팔로우/구독 마스터 목록',
  handler: (): { masters: Array<{ id: string; name: string; profileImage?: string }> } => ({
    masters: followedMasters.map(m => ({
      id: m.id,          // masterId (cmsId)
      name: m.name,
      profileImage: m.profileImage,
    })),
  }),
});
```

확인 사항:
- `followedMasters` 데이터가 어디서 오는지 (API 엔드포인트)
- PRIVATE 마스터를 팔로우/구독 중이면 피드에 나오는지

### QA 에이전트 (us-explorer-agent) — 1개 추가

**`check_my_master_feed`** — `/feed` 페이지에서 특정 마스터 노출 여부

```python
async def check_my_master_feed(cms_id: str) -> dict:
    """나의 마스터 피드에서 해당 마스터 노출 여부."""
    page = await webmcp_client.navigate_to("/feed")
    await page.wait_for_timeout(PAGE_LOAD_TIMEOUT)

    try:
        data = await webmcp_client.call_tool("get_my_master_feed")
        masters = data.get("masters", [])
        matched = next((m for m in masters if str(m.get("id")) == str(cms_id)), None)

        return {
            "found": matched is not None,
            "name": matched.get("name") if matched else None,
        }
    except Exception:
        return {
            "found": False,
            "reason": "get_my_master_feed tool not available",
        }
```

CHECK_FUNCTIONS에 등록:
```python
"check_my_master_feed": check_my_master_feed,
```

---

## 3. 테스트 매트릭스

### A. 오피셜클럽 publicType 영향 (신규)

테스트 대상: FE 테스트 오피셜클럽 (cmsId=129) vs 조조형우 (cmsId=35)

| TC | publicType | 확인 영역 | check 함수 | expected |
|----|-----------|----------|-----------|----------|
| A-1 | PRIVATE (129) | 구독 탭 카드 | check_subscribe_page | found=false |
| A-2 | PRIVATE (129) | 마스터 추천 탭 | check_master_recommend | found=false |
| A-3 | PRIVATE (129) | 클럽 페이지 | check_club_page | accessible=false |
| A-4 | PRIVATE (129) | 나의 마스터 피드 | check_my_master_feed | ? (구독 중이면 보일 수도) |
| A-5 | PUBLIC (35) | 구독 탭 카드 | check_subscribe_page | found=true |
| A-6 | PUBLIC (35) | 마스터 추천 탭 | check_master_recommend | found=true |
| A-7 | PUBLIC (35) | 클럽 페이지 | check_club_page | accessible=true |
| A-8 | PUBLIC (35) | 나의 마스터 피드 | check_my_master_feed | ? (팔로우 여부에 따라) |

결과: A-1, A-2 pass 확인됨. A-3 에러 핸들링 적용됨 (재시도 필요). A-4~A-8 미실행.

### B. 메인 상품페이지 viewStatus 영향 (기존 R0 재검증)

PUBLIC 오피셜클럽(cmsId=35) 기준:

| TC | 메인 viewStatus | 확인 영역 | check 함수 | expected |
|----|----------------|----------|-----------|----------|
| B-1 | ACTIVE | 구독 탭 버튼 | check_subscribe_club | buttonVisible=true |
| B-2 | EXCLUDED | 구독 탭 버튼 | check_subscribe_club | buttonVisible=false |
| B-3 | ACTIVE | 클럽 페이지 멤버십 배너 | check_club_page | isMembershipBannerVisible=true |
| B-4 | EXCLUDED | 클럽 페이지 멤버십 배너 | check_club_page | isMembershipBannerVisible=false? |

주의: check_subscribe_club의 조회키가 productGroupCode인데, cmsId=35의 productGroupCode를 알아야 함.

### C. 상품페이지 status 영향 (기존 R1~R2 재검증)

| TC | 페이지 status | isHidden | 확인 영역 | check 함수 | expected |
|----|-------------|---------|----------|-----------|----------|
| C-1 | ACTIVE | false | URL 접근 | check_product_page | accessible=true |
| C-2 | INACTIVE | false | URL 접근 | check_product_page | accessible=false |
| C-3 | ACTIVE | true | 구독 탭 | check_subscribe_page | found=false |
| C-4 | ACTIVE | true | URL 직접 접근 | check_direct_url_access | accessible=true |

### D. 복합 조건 (신규)

| TC | publicType | 메인 viewStatus | 페이지 status | 확인 | expected |
|----|-----------|----------------|---------------|------|----------|
| D-1 | PUBLIC | ACTIVE | 전부 INACTIVE | 구독 탭 버튼 클릭 시 | 404 또는 에러? |
| D-2 | PUBLIC | EXCLUDED | ACTIVE | 구독 탭 | 카드 보이지만 버튼 비활성? |
| D-3 | PRIVATE | ACTIVE | ACTIVE | 전부 | 안 보여야 함 |

### E. 히든+날짜지정 조합 (진단 규칙 근거 확인)

상세 계획: `diagnose-coverage-plan.md` 참조.

| TC | isHidden | isAlwaysPublic | 기간 상태 | 확인 영역 | expected |
|----|---------|---------------|----------|----------|----------|
| E-1 | true | false | 기간 내 | URL 직접 접근 | accessible=true? |
| E-2 | true | false | 기간 외 | URL 직접 접근 | **핵심: accessible=false이면 "불안정" 근거** |
| E-3 | true | false | 기간 내 | 구독 탭 카드 | found=false (R2 기반) |
| E-4 | true | true | - | URL 직접 접근 | accessible=true (대조군) |
| E-5 | false | false | 기간 내 | 구독 탭 카드 | found=true? |
| E-6 | false | false | 기간 외 | 구독 탭 카드 | found=false? |

### F. 웹링크 타겟이 히든+날짜지정일 때

| TC | 웹링크 타겟 상태 | 확인 영역 | expected |
|----|-----------------|----------|----------|
| F-1 | ACTIVE+비히든+상시 | 구독 탭 → 클릭 | 정상 이동 (대조군) |
| F-2 | ACTIVE+히든+상시 | 구독 탭 → 클릭 | 정상 이동? |
| F-3 | ACTIVE+히든+날짜지정(기간내) | 구독 탭 → 클릭 | 정상 이동? |
| F-4 | ACTIVE+히든+날짜지정(기간외) | 구독 탭 → 클릭 | **핵심: 에러 나면 "불안정" 근거 확립** |

### G. 자유대화 품질 (2026-04-01 수동 테스트 발견)

| TC | 시나리오 | 검증 포인트 | expected |
|----|---------|-----------|----------|
| G-1 | "상품페이지 수정해줘" → "조조형우" | slots 불완전 시 상품페이지 목록 표시 | 목록 + 선택 요청 |
| G-2 | 진단 후 "그거 고쳐줘" | 진단 실패 항목 기반 해결 액션 제안 | resolve action 버튼 |
| G-3 | 실행 요청 시 harness 버튼 | 확인/취소 버튼 표시 | buttons > 0 |
| G-4 | "에이전트 테스트 오피셜 클럽 진단해줘" → "그 히든 해제해줘" | 이전 대상 맥락 유지 | 코드 148 대상으로 처리 |
| G-5 | "조조형우 상품페이지 뭐있어?" → "메인 상품페이지가 뭐야?" → "그 클럽 메인 설정 바꿔줘" | 맥락 전환 후 복귀 | 조조형우 기억 |
| G-6 | "조조형우 노출 진단해줘" → "그거 고쳐줘" | 대명사 추론 + 진단 후속 | 진단 실패 항목 해결 |
| G-7 | "환불 처리해줘" | 범위 밖 거절 | 정중한 거절 메시지 |
| G-8 | 슬롯 필링 중 "아 그냥 됐어" | 취소 가능 여부 | 자연스럽게 대화 종료 |
| G-9 | 슬롯 필링 중 "메인 상품페이지가 뭐야?" | 맥락 전환 허용 | domain 질문으로 라우팅 |

---

## 4. 실행 순서

1. **Web MCP**: `/feed`에 `get_my_master_feed` tool 추가
2. **QA 에이전트**: `check_my_master_feed` 함수 추가 + 서버 재시작
3. **테스트 A 실행**: 오피셜클럽 publicType 영향 전체 (A-1~A-8)
4. **테스트 B 실행**: 메인 상품페이지 viewStatus (세팅 에이전트로 변경 필요)
5. **테스트 C 실행**: 상품페이지 status (기존 R1~R2 재검증)
6. **테스트 D 실행**: 복합 조건
7. **테스트 E, F 실행**: 히든+날짜지정 조합 (세팅 에이전트로 변경 + QA 에이전트로 확인)
8. **테스트 G 실행**: 자유대화 품질 (수동 테스트)
9. **결과 기록**: knowledge/노출-테스트-결과.md 업데이트

### 주의사항

- `check_subscribe_club`의 조회키가 **productGroupCode**임 (cmsId 아님). 각 오피셜클럽의 productGroupCode를 먼저 확인해야 함
- 세팅 변경(B, C)은 세팅 에이전트 위저드로 가능하지만, 마스터 publicType 변경(admin API 미구현)은 불가 → 기존 PUBLIC/PRIVATE 클럽 비교로 대체
- 테스트 후 원래 상태로 복원 필요
