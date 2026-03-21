---
name: openspec-agentic-ai-flows
description: 상품 세팅 Agentic AI - 순차 호출 플로우 + API 스펙 상세 (request/response 타입 포함)
type: project
---

# 순차 호출 플로우 (구독상품 기준)

## Phase 0: 사전 확인/준비

### 0-1. 마스터 존재 확인
```
GET /v1/masters?searchKeyword={name}
→ MasterManagement[] (id, cmsId, name, publicType, masterGroupId)
```
- 없으면 → 마스터 생성 (0-2)
- 있으면 → masterId 확보, Phase 0-3으로

### 0-2. 마스터 생성 (신규 클럽인 경우)
```
# 이미지 3장 업로드 필요 (최소, PENDING 기준)
POST Lambda/presigned-url-v2/api → presigned URL 획득
PUT  S3 presigned URL            → 파일 업로드 → CDN URL 리턴

POST /v1/masters
body: MasterRequestBody {
  masterGroupId: string          # GET /v1/master-groups로 조회
  name: string                   # 고객 표시명 (max 17자)
  displayName: string            # 관리자 표시명
  clubPublicType: 'PENDING'      # PENDING으로 시작, 나중에 PUBLIC 전환
  profileImage: string           # CDN URL (200x200)
  clubBackGroundImage: string    # CDN URL (990x1100)
  clubTextImage: string          # CDN URL (990x1100)
  communityPermissionType: 'ALL' | 'MEMBERSHIP'
  letterPushMessage: string      # 1-100자
  donationPushMessage: string    # 1-100자
  donationIntroductionMessage: string  # 1-100자
  # PUBLIC 전환 시 추가 필수: clubName, clubIntroduction, recommendIntroduction,
  #   simpleIntroduction, simpleIntroductionImage, masterCardTextImage,
  #   detailIntroduction, detailCareers[{career}], letter
}
→ response: { id: string }  (masterId)
```

### 0-3. 시리즈 존재 확인
```
GET /with-series?masterId={masterId}&state=PUBLISHED
→ { masters: [{ _id, name, series: [{ _id, title }] }] }
```
- contentIds로 사용할 시리즈 _id 확보
- 없으면 → 시리즈 생성 (0-4)

### 0-4. 시리즈 생성 (파트너센터 API, base URL 다름)
```
POST /v2/contents/series  (us-partner API)
body: SeriesContentMutateRequest {
  masterId: string
  title: string
  description: string
  category: ContentCategoryType[]   # 1~3개, enum값
  imageUrl: string                  # 썸네일 CDN URL
}
→ { content: { id: string, cmsId: string } }
```
ContentCategoryType: 'secondaryBattery' | 'realty' | 'investment' | 'domesticStock' | 'economicTheory' | 'foreignStock' | 'cryptoCurrency' | 'companyAnalysis' | 'macroEconomics' | 'personalFinance' | 'safeAsset'

## Phase 1: 상품 페이지 생성

### 1-1. 이미지 업로드 (대표 + 상세)
```
# Step A: presigned URL 요청
POST {VITE_LAMBDA_API_URL}/presigned-url-v2/api
body: {
  uploadType: 'ASSET'
  fileName: '{uuid}.{ext}'
  path: '{stage}/admin/{type}/{subtype}'   # ex: 'prod/admin/image/png'
  contentType: 'image'
}
→ { presignedUrl: string, key: string }

# Step B: S3 직접 업로드
PUT {presignedUrl}
body: File (raw binary, NOT FormData)
→ CDN URL = '{VITE_AWS_ASSET_CLOUDFRONT_URL}/{encodeURIComponent(key)}'
```
이미지 제약: JPG/PNG/WebP 4MB 미만, 비디오: MP4 30MB 이하

### 1-2. 상품 페이지 생성
```
POST /v1/product-group
body: CreateProductPageRequest {
  masterId: string
  title: string                    # 관리자용 페이지명 (고객 미노출)
  status: 'ACTIVE' | 'INACTIVE'    # 비공개로 시작 권장
  type: 'SUBSCRIPTION' | 'ONE_TIME_PURCHASE'
  isHidden: boolean                # 히든 처리 여부
  isChangeable: boolean            # 상품 변경 가능 여부 (구독만, 단건은 false)
  displayLetterStatus: 'ACTIVE' | 'INACTIVE'  # 편지글 공개
  # 공개 기간
  isAlwaysPublic: boolean
  startAt?: string                 # ISO date (isAlwaysPublic=false일 때)
  endAt?: string
  # 신청 기간
  isAlwaysApply: boolean
  applyStartAt?: string
  applyEndAt?: string
  # 이미지 (Phase 1-1에서 업로드한 CDN URL)
  mainContents: ProductGroupMainContent[] {
    type: 'IMAGE' | 'VIDEO'
    contentUrl: string             # CDN URL
    isAlwaysPublic: boolean
    startAt?: string
    endAt?: string
    linkUrl?: string               # 클릭 시 이동 URL (비디오는 미적용)
  }[]
  contents: ProductGroupContent[] {
    imageUrl: string               # CDN URL
    isAlwaysPublic: boolean
    sequence: number               # 순서 (0부터)
    startAt?: string
    endAt?: string
    link?: string
  }[]
}
→ response: { id: string }  (productGroupId)
```

## Phase 2: 상품 옵션 등록 (옵션 수만큼 반복)

### 2-1. 상품 생성
```
POST /v1/product
body: CreateProductRequest {
  productGroupId: string           # Phase 1에서 받은 ID
  name: string                     # 상품명 (고객 노출)
  isDisplay: boolean               # 노출 여부
  originPrice: number              # 정상가 (원)
  # 구독 상품
  paymentPeriod?: 'ONE_MONTH' | 'TWO_MONTH' | 'THREE_MONTH' | 'FOUR_MONTH' | 'SIX_MONTH' | 'ONE_YEAR'
  # 단건 상품
  usagePeriodType?: 'DURATION' | 'DATE_RANGE'
  useDuration?: number             # DURATION: n일
  useStartAt?: string              # DATE_RANGE: 시작일
  useEndAt?: string                # DATE_RANGE: 종료일
  # 시리즈 연결
  contentIds: string[]             # Phase 0에서 확인한 시리즈 ID (cmsId)
  # 상품 구성 텍스트
  displayTexts: string[]           # ["시리즈A 이용권", "교재 제공"]
  # 노출 강조
  isDisplayRecommend: boolean      # BEST PICK 뱃지
  tags?: string[]                  # 태그 (7자 이내)
  # 프로모션 (선택)
  promotionType?: 'REGULAR_DISCOUNT' | 'SUBSCRIPTION_COUNT_DISCOUNT'
  regularDiscountPromotion?: {
    discountType: 'PERCENT' | 'AMOUNT'
    discountValue: number
  }
  subscriptionCountDiscountPromotion?: {
    discountType: 'PERCENT' | 'AMOUNT'
    discountValue: number
    subscriptionCounts: number[]   # [1,2,3] = 1~3회차
    startAt: string
    endAt: string
    isAlwaysPromotion: boolean
    isActive: boolean
  }
}
→ response: { id: number }  (productId)
```

## Phase 3: 활성화

### 3-1. 상품 노출 ON
```
PATCH /v1/product/display
body: { id: string, isDisplay: true }
```

### 3-2. 상품 순서 설정
```
PATCH /v1/product/group/{productGroupId}/sequence
body: { ids: string[] }   # productId 배열 (원하는 순서)
```

### 3-3. 상품 페이지 공개
```
PATCH /v1/product-group/status
body: { id: string, status: 'ACTIVE' }
```

### 3-4. 메인 상품 페이지 설정
```
PATCH /v1/masters/{masterId}/main-product-group
body: MasterMainProductSetting {
  productGroupType: 'US_PLUS'
  productGroupViewStatus: 'ACTIVE'
  productGroupWebLink?: string
  productGroupAppLink?: string
  isProductGroupWebLinkStatus: 'ACTIVE' | 'INACTIVE'
  isProductGroupAppLinkStatus: 'ACTIVE' | 'INACTIVE'
}
```

## Phase 4: 검증

```
GET /v1/product-group/{productGroupId}     → 페이지 상태/이미지 확인
GET /v1/product/group/{productGroupId}     → 상품 옵션 수/금액/시리즈 확인
GET /v1/product/{productId}               → 개별 상품 노출 상태 확인
(선택) Web MCP → 고객 화면 렌더링 스크린샷
```

## Phase 5: 알림

```
Slack 메시지 전송:
  ✅ 세팅 완료
  - 마스터: {마스터명}
  - 상품 페이지: {페이지명} (코드: {code})
  - 옵션 {n}개: {옵션1 이름} {금액}원, {옵션2 이름} {금액}원, ...
  - 관리자센터: admin.us-insight.com/product/page/{productGroupId}
  - 고객 화면: us-insight.com/products/group/{code}
```

---

# 단건상품 차이점

Phase 2에서 구독과 다른 부분만:
```
CreateProductRequest {
  # paymentPeriod 대신:
  usagePeriodType: 'DURATION' | 'DATE_RANGE'
  useDuration?: number          # DURATION: 구매 시점부터 n일
  useStartAt?: string           # DATE_RANGE: 시작일
  useEndAt?: string             # DATE_RANGE: 종료일
  # 프로모션: REGULAR_DISCOUNT만 가능 (SUBSCRIPTION_COUNT_DISCOUNT 불가)
}
```
Phase 1에서: `isChangeable: false` 고정

---

# 이미지 업로드 상세

```
uploadFile({
  file: File,
  uploadType: 'ASSET',              # 관리자센터 이미지
  path: '{VITE_STAGE}/admin/{type}/{subtype}',  # ex: 'prod/admin/image/png'
  fileName?: string,                 # 생략 시 uuid 자동 생성
}) → CDN URL (string)

환경변수:
  VITE_LAMBDA_API_URL              # presigned URL 요청 엔드포인트
  VITE_AWS_ASSET_CLOUDFRONT_URL    # CDN 베이스 URL
  VITE_STAGE                       # dev | staging | prod
```

---

# 전체 API 목록 (에이전트 Tool 래핑 대상)

## 관리자센터 (us-admin 백엔드)
```
# 마스터
GET    /v1/masters                              마스터 검색
GET    /v1/masters/:masterId                     마스터 상세
POST   /v1/masters                              마스터 생성
PATCH  /v1/masters/:masterId                     마스터 수정
GET    /v1/master-groups                         마스터 그룹 목록

# 상품 페이지
GET    /v1/product-group?masterId={id}           페이지 목록
GET    /v1/product-group/:productPageId          페이지 상세
POST   /v1/product-group                         페이지 생성
PATCH  /v1/product-group                         페이지 수정
PATCH  /v1/product-group/status                  상태 변경
PATCH  /v1/product-group/notice                  유의사항 설정

# 상품
GET    /v1/product/:id                           상품 상세
GET    /v1/product/group/:productPageId          페이지별 상품 목록
POST   /v1/product                               상품 생성
PATCH  /v1/product                               상품 수정
PATCH  /v1/product/display                       노출 변경
PATCH  /v1/product/group/:pageId/sequence        순서 변경

# 시리즈 (조회만)
GET    /with-series?masterId={id}                시리즈 목록

# 메인 상품 설정
GET    /v1/masters/:id/main-product-group        메인 상품 조회
PATCH  /v1/masters/:id/main-product-group        메인 상품 설정
```

## 파트너센터 (us-partner 백엔드, base URL 다름)
```
POST   /v2/contents/series                       시리즈 생성
PUT    /v2/contents/:id/series                   시리즈 수정
GET    /v2/masters/:masterId/contents?contentType=series  시리즈 목록
```

## 파일 업로드 (Lambda)
```
POST   {LAMBDA_URL}/presigned-url-v2/api         presigned URL 요청
PUT    {presignedUrl}                            S3 직접 업로드
```

---

# 코드베이스 핵심 파일 위치

## us-admin
- API: `apps/us-admin/src/entities/product/api/api/index.ts`
- API: `apps/us-admin/src/entities/master/api/api/index.ts`
- 타입: `apps/us-admin/src/entities/product/model/types/index.ts`
- 타입: `apps/us-admin/src/entities/master/model/types/index.ts`
- 스키마: `apps/us-admin/src/entities/master/model/schema/index.ts`
- 스키마: `apps/us-admin/src/features/product/model/schema/`
- 업로드: `apps/us-admin/src/shared/lib/utils/fileUpload.ts`
- 페이지: `apps/us-admin/src/pages/product/`, `apps/us-admin/src/pages/master/`

## us-partner
- 시리즈 API: `apps/us-partner/entities/content/series/api/api/index.ts`
- 시리즈 타입: `apps/us-partner/entities/content/series/model/types/index.ts`
