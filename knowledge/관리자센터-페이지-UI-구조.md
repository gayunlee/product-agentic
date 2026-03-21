# 관리자센터 페이지 & UI 구조

출처: 코드베이스 분석 + Playwright 스크린샷 (2026-03-21)

---

## A. 페이지 URL 구조

| 페이지 | URL | 비고 |
|--------|-----|------|
| 상품 페이지 목록 | `/product` | 마스터 셀렉터 드롭다운으로 필터링 |
| 상품 페이지 생성 | `/product/page/create` | 별도 페이지 (모달 아님) |
| 상품 페이지 상세 | `/product/page/:objectId?masterId=...&tab=settings\|options\|letters\|caution` | 4탭, 쿼리파라미터로 탭 전환 |
| 상품 옵션 등록 | `/product/create?productPageId=...&productType=...&masterId=...` | 별도 페이지 |
| 상품 수정 | `/product/:productId?productPageId=...&productType=...&masterId=...` | 별도 페이지 |
| 오피셜클럽 목록 | `/official-club` | 검색+필터 |
| 오피셜클럽 생성 | `/official-club/create` | 2단 레이아웃 |
| 오피셜클럽 상세 | `/official-club/:masterId` | 생성과 동일 폼 |
| 마스터 관리 | `/master` | 마스터 그룹 관리 |
| 마스터 페이지 관리 | `/master/page` | 공개/준비중 순서 관리 |
| 메인 상품 페이지 관리 | `/product/page/list` | ACTIVE/INACTIVE/EXCLUDED 3개 리스트 |
| 상품 결제 내역 | `/product/sales` | |
| 연동 상품 관리 | `/product/integration` | |
| 환불 정책 관리 | `/product/policy` | |

---

## B. 각 페이지 UI 구조

### 상품 페이지 생성 (`/product/page/create`)
- 별도 풀 페이지 폼
- 필드 순서:
  1. 히든 처리 여부 (체크박스)
  2. 마스터 선택 (드롭다운)
  3. 페이지명 (40자 제한)
  4. 페이지 공개 여부 (공개/비공개 드롭다운)
  5. 공개 기간 (날짜 범위 / 상시 체크박스)
  6. 상품 변경 가능 여부 (변경 불가/변경 가능 드롭다운)
  7. 상품 타입 (구독상품/단건상품 드롭다운) ← *단건은 변경 불가능할 때만 선택 가능
  8. 신청 기간 (날짜 범위 / 상시 체크박스)
  9. 편지글 공개 여부 (공개/비공개)
  10. 상품 대표 이미지/비디오 (콘텐츠 추가 버튼 → DataGrid)
  11. 상품 소개 이미지 (이미지 등록 버튼 → DataGrid, 순서↑↓)
- 생성 후: `/product?masterId=${masterId}` (목록으로 이동)

### 상품 페이지 상세 (`/product/page/:id`)
4개 탭 (URL `?tab=` 으로 접근 가능):

**a. 기본설정 (`?tab=settings`)**
- 생성 폼과 동일한 필드 수정
- 상품 대표 이미지/비디오: 콘텐츠 추가 버튼 → DefaultImageUploadModal
- 상품 소개 이미지: 이미지 등록 버튼, DataGrid에서 순서↑↓, 수정, 삭제
- 드래그앤드롭 지원 (useImageDragAndDrop)
- 최대 4MB, PNG/JPG/JPEG/GIF/SVG

**b. 상품옵션 (`?tab=options`)**
- "상품등록" 버튼 → `/product/create?productPageId=...&productType=...&masterId=...` (별도 페이지)
- DataGrid: 노출순서, 상품ID, 상품명, 금액, 결제주기, 이용기간, 공개여부(드롭다운), 삭제, 선택수표시, 순서변경
- "순서 변경" 버튼
- 상품 공개 여부 필터 (전체/공개/비공개)

**c. 편지 (`?tab=letters`)**
- displayLetterStatus=ACTIVE일 때만 노출
- 상단 고정 목록 + 전체 목록
- 프로필이미지, 내용, 작성자, 최초작성일, 베스트 후기

**d. 유의사항 (`?tab=caution`)**
- 노출여부 (노출함/노출안함 라디오)
- 유의사항 항목 추가(+) 버튼

### 상품 등록 (`/product/create`)
- 별도 페이지 (상품옵션 탭의 "상품등록" 버튼 클릭 시 이동)
- 필드 순서:
  1. 상품명* (40자)
  2. 공개여부* (비공개/공개 드롭다운)
  3. 결제주기* (구독: 1개월~1년 드롭다운) / 이용기간 유형 (단건: 일수/기간지정)
  4. 금액* (원)
  5. 포함할 시리즈 선택* ← "선택할 수 있는 시리즈가 없습니다. 시리즈를 먼저 생성해주세요." 메시지
  6. 추천상품 표시 (체크박스)
  7. 태그 추가 (입력 + 추가 버튼)
  8. 상품 구성 (텍스트 입력 + 추가 버튼, 드래그 정렬, 최대 10개, 각 20자)
  9. 프로모션 (프로모션 적용/적용 안함 라디오)
- 등록 후: 상품페이지 상세 상품옵션 탭으로 돌아감

### 오피셜클럽 생성 (`/official-club/create`)
- 2단 레이아웃 별도 페이지
- 좌측:
  1. 공개 여부 (공개/준비중/비공개 라디오)
  2. 프로필 이미지 (900x900px, 드래그앤드롭)
  3. 마스터 선택 (드롭다운)
  4. 오피셜클럽명 (관리자&파트너센터 표시명)
  5. 오피셜클럽명 (고객 화면 표시명, 17자)
  6. 오피셜클럽 타이틀 (100자)
  7. 오피셜클럽 소개 (100자)
  8. 추천 인사말
  9. 간단 소개
  10. 간단소개 이미지 (900x900px)
  11. 오피셜 클럽명 이미지 (900x900px)
  12. 상세 소개
  13. 대표 이력 (입력 + 추가 버튼)
- 우측:
  1. 클럽 이미지 (990x1100px)
  2. 클럽 텍스트 이미지 (990x1100px)
  3. 편지글
  4. 편지 읽음 피드백 알림 설정
  5. 응원 피드백 알림 설정
  6. 응원하기 타이틀 설정
  7. 커뮤니티 작성 권한 (전체/멤버십)
- 생성 후: `/official-club` (목록으로 이동)

### 오피셜클럽 상세 (`/official-club/:masterId`)
- 생성과 동일한 폼 (수정 모드)

---

## C. 네비게이션 흐름

```
상품 목록 → 상품 상세: /product → 행 클릭 → /product/page/:objectId
상품 상세 탭 전환: ?tab=options 쿼리파라미터
상품 옵션 등록: "상품등록" 버튼 → /product/create?productPageId=...&productType=...&masterId=...
상품 페이지 생성 후: /product?masterId=${masterId} (목록)
오피셜클럽 상세 → 상품 관리: 직접 연결 없음 (사이드바로 별도 이동 필요)
파트너센터: 좌측 최외곽 앱 전환 아이콘으로 이동
```

---

## D. 사이드바 메뉴 구조

```
대시보드
  ├── 주요 지표, 마스터, 회원, 매출, 구독, 콘텐츠
회원관리
매출관리
구독관리
상품관리 (PRODUCT 권한)
  ├── 상품 관리 → /product
  ├── 상품 결제 내역 관리 → /product/sales
  ├── 연동 상품 관리 → /product/integration
  ├── 선물관리 → /gift
  └── 환불 정책 관리 → /product/policy
서비스 운영 관리 (OPERATION 권한)
  ├── 배너 관리, 라운지 관리, 온보딩 관리, 응원하기 관리
  ├── 마스터 페이지 관리 → /master/page
  ├── 메인 상품 페이지 관리 → /product/page/list
  ├── 체험권 관리/적용, 게시판 설정, 구독해지사유 설정
  ├── 결제일 추가 → /product/billing-date/add
  ├── 선물하기 설정, 추천상품 관리
  └── 공지사항 관리
콘텐츠관리
CS관리
Shop 관리
마스터 & 권한관리 (MASTER, PERMISSION 권한)
  ├── 운영 권한 → /cs/operator
  ├── 서비스 이용 권한 관리 → /cs/user-role
  ├── 오피셜 클럽 관리 → /official-club
  └── 마스터 관리 → /master
```

좌측 최외곽 앱 전환: 관리자, 파트너, 플러스, Shop

---

## E. 상태 확인 UI

| 상태 | 확인 위치 | UI 형태 |
|------|---------|--------|
| 상품 페이지 ACTIVE/INACTIVE | `/product` 목록 DataGrid | "공개여부" 드롭다운 (직접 전환 가능) |
| 마스터 PUBLIC/PENDING | `/master/page` | 좌측: PUBLIC, 우측: PENDING 분리 |
| 메인 상품 페이지 활성화 | `/product/page/list` | ACTIVE/INACTIVE/EXCLUDED 3개 리스트, MainProductSettingModal |
| 상품 옵션 노출 | 상품 상세 `?tab=options` | DataGrid "공개여부" 드롭다운 |
