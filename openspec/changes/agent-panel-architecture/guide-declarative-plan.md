# guide 도구 선언적 리팩토링

## 현재 문제

1. **PAGE_MAP이 코드에 하드코딩** — `admin_api.py`에 Python dict로 URL 매핑. 새 페이지 추가/수정 시 코드 변경 필요
2. **guide 도구가 사전 조건 체크 안 함** — "상품페이지 만들거야" → 오피셜클럽 안 물어보고 바로 링크만 던짐
3. **쿼리파라미터 누락** — 오피셜클럽/마스터 정보를 API로 조회해서 URL 파라미터에 넣어야 하는데, guide가 검색 없이 navigate만 호출
4. **navigate() 파라미터명 불일치** — `page_type` vs `page` 버그 (수정 완료)

## 설계

### YAML 선언 (`guides.yaml` 또는 `registry.yaml` 확장)

```yaml
guides:
  product_page_create:
    label: "상품 페이지 생성"
    url: "/product/page/create"
    required_params:
      masterId:
        resolve: search_masters
        from: cmsId
      masterObjectId:
        resolve: search_masters
        from: id
    requires_input:
      - master_name: "어느 오피셜클럽에서 만드시겠어요?"

  product_page_detail:
    label: "상품 페이지 상세"
    url: "/product/page/{id}"
    required_params:
      id:
        from: objectId  # 상품페이지 objectId
      masterId:
        resolve: search_masters
        from: cmsId

  product_create:
    label: "상품 옵션 등록"
    url: "/product/create"
    required_params:
      productPageId:
        from: page_id
      productType:
        from: product_type
      masterId:
        resolve: search_masters
        from: cmsId

  official_club:
    label: "오피셜클럽 상세"
    url: "/official-club/{masterId}"
    required_params:
      masterId:
        resolve: search_masters
        from: cmsId

  # 파라미터 불필요한 페이지들
  product_page_list:
    label: "상품 페이지 목록"
    url: "/product"
  
  main_product:
    label: "메인 상품 페이지 관리"
    url: "/product/page/list"

  official_club_create:
    label: "오피셜클럽 생성"
    url: "/official-club/create"

  master_page:
    label: "마스터 페이지 관리"
    url: "/master/page"

  board_setting:
    label: "게시판 설정"
    url: "/board/setting"

  partner_series:
    label: "파트너센터 시리즈 생성"
    url: "https://master.us-insight.com"
    external: true
```

### guide 도구 동작 흐름

```
1. YAML에서 page_type에 해당하는 가이드 정의 로드
2. requires_input 확인 → 빠진 입력(master_name 등)이 있으면 "어느 오피셜클럽?" 질문 반환
3. required_params 확인 → resolve API 호출로 값 확보 (search_masters → cmsId, id)
4. URL 템플릿에 params 적용
5. navigate 버튼 + 안내 메시지 반환
```

### 수정 파일

| 파일 | 변경 |
|------|------|
| `guides.yaml` (신규) | 가이드 페이지 선언 |
| `src/agents/orchestrator.py` | guide 도구가 YAML 읽어서 동작 |
| `src/tools/admin_api.py` | PAGE_MAP 제거 → YAML로 이동. navigate()는 YAML 로드 |

### 기존 PAGE_MAP → YAML 매핑

현재 PAGE_MAP (admin_api.py:698):
- `product_page_list` — 파라미터 없음
- `product_page_create` — masterId, masterObjectId 필요
- `product_page_detail` — id(objectId) 필요, masterId
- `product_page_edit` — id 필요
- `product_page_options` — id 필요
- `product_page_letters` — id 필요
- `product_page_caution` — id 필요
- `product_create` — productPageId, productType, masterId 필요
- `product_edit` — productId, productPageId, productType, masterId 필요
- `main_product` — 파라미터 없음
- `official_club` — masterId(cmsId) 필요
- `official_club_create` — 파라미터 없음
- `official_club_list` — 파라미터 없음
- `master_list` — 파라미터 없음
- `master_page` — 파라미터 없음
- `board_setting`, `board`, `donation`, `letter` — 파라미터 없음
- `partner_series` — 외부 URL
- `product_sales`, `subscribe` — 파라미터 없음

### 참고

- `knowledge/관리자센터-페이지-UI-구조.md` — URL 구조, 각 페이지 UI 구조, 네비게이션 흐름 상세
- `legacy/agent/system_prompt.py:95` — 기존 navigate 버튼 패턴 (`masterId=35` 쿼리파라미터)
- 파라미터 값은 API 조회로 확보: `search_masters` → cmsId, id / `get_product_page_list` → page objectId
