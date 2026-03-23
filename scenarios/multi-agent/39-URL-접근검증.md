# #39 상품페이지로 랜딩시킬 URL들 접속 다 가능한지 확인해줘

## 분류
- 유저 의도: 수행 (verify_urls)
- 에이전트: 오케스트레이터 → 수행 에이전트 → 탐색 에이전트

---

## Case A: 일부 접근 불가

```
유저: 상품페이지로 랜딩시킬 URL들 있는데 접속 다 가능한지 확인해줘
에이전트: URL을 알려주세요.
유저: us-insight.com/products/group/148, us-insight.com/products/group/155
에이전트: (탐색 에이전트로 검증)
         - /products/group/148 → ✅ 접근 가능
         - /products/group/155 → ❌ "공개되지 않은 상품 페이지입니다" (INACTIVE)

         코드 155 페이지가 비공개 상태입니다. 공개 처리하시겠어요?
```

## Case B: 전부 정상

```
유저: us-insight.com/products/group/148, us-insight.com/products/group/160
에이전트: (탐색 에이전트로 검증)
         - /products/group/148 → ✅ 접근 가능
         - /products/group/160 → ✅ 접근 가능

         모든 URL이 정상 접근 가능합니다.
```

---

## 검증 포인트 (eval 기준)

1. URL 목록을 받아서 하나씩 검증
2. 접근 불가 시 원인 안내 (INACTIVE, 히든 등)
3. 해결 제안 (공개 처리)
