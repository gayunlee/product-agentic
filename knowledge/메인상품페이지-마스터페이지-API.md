# 메인 상품 페이지 & 마스터 페이지 관리 API

출처: Apidog admin OAS + us-admin 소스코드 (2026-03-18 확인)

---

## 1. 메인 상품 페이지 관리

오피셜클럽별 상품페이지 활성화/비활성화 관리

### READ

| Method | Endpoint | Hook | 용도 |
|--------|----------|------|------|
| GET | `/v1/masters/product-group` | `useGetMasterProductList()` | 마스터별 상품 목록 (ACTIVE/INACTIVE/EXCLUDED 분류) |
| GET | `/v1/masters/{masterId}/main-product-group` | `useGetMasterMainProductSetting()` | 마스터별 상품 설정 상세 |
| GET | `/v1/product-group` | `useGetProductPageList()` | 상품 페이지 목록 |
| GET | `/v1/product-group/{productPageId}` | `useGetProductPageById()` | 상품 페이지 상세 |

### WRITE

| Method | Endpoint | Hook | 용도 |
|--------|----------|------|------|
| PATCH | `/v1/masters/{masterId}/main-product-group` | `useUpdateMasterMainProductSetting()` | 활성화 상태 변경 (ACTIVE/INACTIVE/EXCLUDED) |
| PATCH | `/v1/masters/product-group/sequence` | `useUpdateMasterProductOrder()` | 마스터 상품 순서 변경 |
| PATCH | `/v1/product-group/status` | `useUpdateProductPageList()` | 상품 페이지 공개여부 변경 |
| PATCH | `/v1/product-group` | `useUpdateProductPage()` | 상품 페이지 수정 |
| DELETE | `/v1/product-group/{productGroupId}` | `useDeleteProductPageList()` | 상품 페이지 삭제 |

---

## 2. 마스터 페이지 관리

오피셜클럽 노출 순서 관리

### READ

| Method | Endpoint | Hook | 용도 |
|--------|----------|------|------|
| GET | `/v1/masters/view` | `useGetViewMasters()` | 공개/준비중 마스터 목록 (순서 포함) |

### WRITE

| Method | Endpoint | Hook | 용도 |
|--------|----------|------|------|
| PATCH | `/v1/masters/sequence` | `useChangeMasterSequence()` | 노출 순서 변경 |

---

## 2레벨 노출 순서 구조

### Level 1: 마스터(오피셜클럽) 순서

```
GET /v1/masters/view
→ {
    publicMasters: [{ sequence: number, name: string, cmsId: string }],
    pendingMasters: [{ sequence: number, name: string, cmsId: string }]
  }

PATCH /v1/masters/sequence
→ { pageType: "PUBLIC" | "PENDING", ids: [cmsId...] }
  → ids 배열 순서 = 노출 순서
```

### Level 2: 상품 페이지 활성화 + 순서

```
GET /v1/masters/{cmsId}/main-product-group
→ {
    productGroupType: "US_PLUS" | "US_CAMPUS",
    productGroupViewStatus: "ACTIVE" | "INACTIVE" | "EXCLUDED",
    productGroupAppLink?: string,
    productGroupWebLink?: string
  }

PATCH /v1/masters/{cmsId}/main-product-group
→ { productGroupType, productGroupViewStatus, productGroupWebLink?, ... }

PATCH /v1/masters/product-group/sequence
→ { mainProductViewStatus: "ACTIVE" | "INACTIVE" | "EXCLUDED", ids: [cmsId...] }
```

### 핵심

- 구독 탭에 노출되려면: 마스터가 PUBLIC + 상품 페이지가 ACTIVE
- displayIndex는 **ACTIVE인 마스터 중에서의 순서** (전체 아님)
- 실제 검증 (2026-03-18): 조조형우(cmsId:35) = ACTIVE 15개 중 10번째, productGroupCode: 148

---

## API 응답 스키마 (Apidog 확인)

### MasterFindViewResponse
```json
{
  "publicMasters": [{ "sequence": 1, "name": "홍춘욱", "cmsId": "3" }],
  "pendingMasters": [{ "sequence": 1, "name": "준비중마스터", "cmsId": "64" }]
}
```

### MasterUpdateSequenceRequest
```json
{
  "pageType": "PUBLIC",     // "PUBLIC" | "PENDING"
  "ids": ["136", "45", "3"] // cmsId 배열, 순서대로
}
```

### MasterFindOneWithMainProductGroupResponse
```json
{
  "productGroupType": "US_PLUS",
  "productGroupViewStatus": "ACTIVE",
  "productGroupAppLink": "https://dev.us-insight.com/products/group/148",
  "productGroupWebLink": "https://dev.us-insight.com/products/group/148"
}
```

### MasterUpdateMainProductGroupRequest
```json
{
  "productGroupType": "US_PLUS",
  "productGroupViewStatus": "ACTIVE",
  "productGroupWebLink": "https://...",
  "productGroupAppLink": "https://..."
}
```

### MasterUpdateMainProductSequenceRequest
```json
{
  "mainProductViewStatus": "ACTIVE",  // "ACTIVE" | "INACTIVE" | "EXCLUDED"
  "ids": ["35", "97", "102"]          // cmsId 배열, 순서대로
}
```

### MasterFindAllByProductGroupResponse
```json
{
  "masterId": "35",
  "masterName": "조조형우",
  "productGroupViewStatus": "ACTIVE",
  "publicType": "PUBLIC",
  "hasProductGroup": true,
  "productGroupType": "US_PLUS",
  "productGroupWebLink": "https://dev.us-insight.com/products/group/148"
}
```
