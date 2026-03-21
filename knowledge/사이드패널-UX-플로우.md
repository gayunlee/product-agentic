# 사이드패널 UX 플로우 (확정)

관리자센터 사이드패널 AI 어시스턴트의 상품 세팅 플로우.
"폼 입력이 필요한 것 → 관리자센터 페이지로 이동" / "API 호출만 필요한 것 → 사이드패널에서 처리"

---

## 역할 구분

| 역할 | 사이드패널 | 유저 (관리자센터 페이지) |
|------|:---:|:---:|
| 마스터/시리즈 확인 | API 조회 + 결과 표시 | — |
| 오피셜클럽 생성 | 링크 제공 | `/official-club/create`에서 직접 |
| 시리즈 생성 | 파트너센터 안내 | 파트너센터에서 직접 |
| 상품 페이지 생성 | 링크 + 가이드 | `/product/page/create`에서 직접 |
| 이미지 등록 | 링크 제공 | 상세 `?tab=settings` 하단에서 직접 |
| 상품 옵션 등록 | 링크 + 가이드 | `/product/create?...`에서 직접 |
| **활성화** | **API 직접 호출 (4단계)** | 버튼 1개만 클릭 |
| **검증** | **API 자동 확인** | — |
| **진단** | **API 자동 진단** | — |

---

## 플로우 상세

### Step 1: 마스터/오피셜클럽 확인 (사이드패널 자동)

사이드패널: API로 `search_masters` + `get_master_groups` 호출
- ✅ 있으면: cmsId, publicType 표시 → Step 2로
- ❌ 없으면: "오피셜클럽을 먼저 생성해야 합니다"
  - [오피셜클럽 생성하러 가기] → `/official-club/create`
  - [✅ 생성 완료] → 사이드패널이 API로 재확인 → Step 2로

### Step 2: 시리즈 확인 (사이드패널 자동)

사이드패널: API로 `get_series_list` 호출
- ✅ 있으면: 시리즈 목록 표시 → Step 3으로
- ❌ 없으면: "시리즈가 필요합니다"
  - [파트너센터로 이동] → 좌측 앱 전환 아이콘 "파트너" 클릭 안내
  - [✅ 시리즈 생성 완료] → 사이드패널이 API로 재확인 → Step 3으로

### Step 3: 상품 페이지 생성 (유저가 관리자센터에서)

사이드패널: `get_product_page_list`로 기존 페이지 확인
- 이미 있으면: "기존 페이지 있음. 옵션 추가?" → Step 5로
- 없으면:
  - [상품 페이지 생성하러 가기] → `/product/page/create`
  - 가이드: "마스터 선택에서 '{마스터명}'을 선택해주세요"
  - [✅ 상품 페이지 생성 완료] → API로 재확인 (페이지명, 코드, 상태) → Step 4로

### Step 4: 이미지 등록 (유저가 관리자센터에서)

사이드패널: 이미지 등록 안내
- [이미지 설정으로 이동] → `/product/page/{objectId}?masterId={cmsId}&tab=settings`
  - 기본설정 탭 하단 "상품 대표 이미지/비디오" + "상품 소개 이미지" 영역
- [이미지는 나중에] → Step 5로 (플레이스홀더 유지)
- [✅ 이미지 등록 완료] → Step 5로

### Step 5: 상품 옵션 등록 (유저가 관리자센터에서)

사이드패널: 옵션 등록 안내
- [상품 옵션 등록하러 가기] → `/product/create?productPageId={objectId}&productType={SUBSCRIPTION|ONE_TIME_PURCHASE}&masterId={cmsId}`
- 가이드: 상품명, 금액, 결제주기, 시리즈 선택, 프로모션 항목 안내
- [✅ 상품 옵션 등록 완료] → API로 재확인 (옵션 수, 금액, 시리즈)
- [➕ 옵션 하나 더 등록] → Step 5 반복

### Step 6: 활성화 (사이드패널이 API로 직접)

사이드패널: 등록된 옵션 요약 표시 + 활성화 버튼
- [🚀 활성화하기] → 사이드패널이 4개 API 순차 호출:
  1. `update_product_display` (각 옵션 노출 ON)
  2. `update_product_sequence` (순서 설정)
  3. `update_product_page_status` (페이지 ACTIVE)
  4. `update_main_product_setting` (메인 상품 페이지 ACTIVE)
- ⚠️ 이미지 플레이스홀더면 경고: "이미지가 아직 플레이스홀더입니다. 교체 후 활성화를 권장합니다."

### Step 7: 검증 + 체크리스트 (사이드패널 자동)

사이드패널: 검증 수행
- `get_product_page_detail` + `get_product_list_by_page`로 확인
- 구독 탭 노출 순서 확인 (ACTIVE 목록에서 몇 번째)
- 체크리스트 안내:
  - [이미지 설정으로 이동] → `?tab=settings`
  - [유의사항 등록으로 이동] → `?tab=caution`
  - [고객 화면에서 확인] → `https://dev.us-insight.com/products/group/{code}`

---

## 버튼 타입 정리

### 이동 버튼 (관리자센터/파트너센터 페이지로)
| 버튼 | 이동 URL |
|------|---------|
| 오피셜클럽 생성하러 가기 | `/official-club/create` |
| 파트너센터로 이동 | 앱 전환 아이콘 안내 |
| 상품 페이지 생성하러 가기 | `/product/page/create` |
| 이미지 설정으로 이동 | `/product/page/{id}?masterId={cmsId}&tab=settings` |
| 상품 옵션 등록하러 가기 | `/product/create?productPageId={id}&productType={type}&masterId={cmsId}` |
| 유의사항 등록으로 이동 | `/product/page/{id}?tab=caution` |
| 고객 화면에서 확인 | `https://dev.us-insight.com/products/group/{code}` |
| 메인 상품 페이지 관리 | `/product/page/list` |
| 마스터 페이지 관리 | `/master/page` |

### 완료 버튼 (사이드패널이 API로 재확인)
| 버튼 | 사이드패널 액션 |
|------|----------------|
| ✅ 오피셜클럽 생성 완료 | `search_masters` 재호출 → 확인 |
| ✅ 시리즈 생성 완료 | `get_series_list` 재호출 → 확인 |
| ✅ 상품 페이지 생성 완료 | `get_product_page_list` 재호출 → 페이지 정보 확인 |
| ✅ 이미지 등록 완료 | 다음 단계로 |
| ✅ 상품 옵션 등록 완료 | `get_product_list_by_page` 재호출 → 옵션 정보 확인 |

### 실행 버튼 (사이드패널이 API 직접 호출)
| 버튼 | API 호출 |
|------|---------|
| 🚀 활성화하기 | `update_product_display` → `update_product_sequence` → `update_product_page_status` → `update_main_product_setting` |
| 🔍 진단하기 | 체크리스트 순서로 조회 API 호출 |
