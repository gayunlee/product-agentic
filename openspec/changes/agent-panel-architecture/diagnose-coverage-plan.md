# 진단 규칙 검증 보완 — 히든+날짜지정 조합 테스트

## 배경

진단 엔진(`diagnose_engine.py` L324)에서 **히든+날짜지정** 조합을 "웹링크 타겟 안정성 실패"로 판정하고 있으나, 이 판정의 근거가 실제 테스트로 확인되지 않았음.

현재 확인된 규칙:
- **R2**: 히든 → 구독 탭에 안 보이지만 URL 직접 접근 가능
- **R3**: 비히든 날짜지정(기간내) > 상시 — 상시 페이지를 비활성화
- **R4**: 히든 = 노출 경쟁에서 제외 — 기간 충돌 검사 제외

미확인:
- 히든+날짜지정(기간내) → URL 접근 가능?
- 히든+날짜지정(기간외) → URL 접근 불가?
- 히든+날짜지정이 웹링크 타겟일 때 → 구독 탭에서 어떻게 보이는지?

## 테스트 케이스

### E. 히든+날짜지정 조합 (신규 — 진단 규칙 근거 확인)

세팅 에이전트로 상태 변경 → QA 에이전트로 노출 확인.

**테스트 대상**: 에이전트 테스트 오피셜 클럽의 상품페이지 코드 148

| TC | isHidden | isAlwaysPublic | 기간 상태 | 확인 영역 | check 함수 | expected (가설) | 비고 |
|----|---------|---------------|----------|----------|-----------|----------------|------|
| E-1 | true | false | 기간 내 | URL 직접 접근 | check_direct_url_access | accessible=true? | R2 기반 추측 |
| E-2 | true | false | 기간 외 | URL 직접 접근 | check_direct_url_access | accessible=false? | **핵심: 기간 외에 URL도 안 되면 "불안정" 근거** |
| E-3 | true | false | 기간 내 | 구독 탭 카드 | check_subscribe_page | found=false | R2 기반 (히든이면 탭에서 안 보임) |
| E-4 | true | true | - | URL 직접 접근 | check_direct_url_access | accessible=true | 히든+상시 (대조군) |
| E-5 | false | false | 기간 내 | 구독 탭 카드 | check_subscribe_page | found=true? | 비히든+날짜지정(기간내) (대조군) |
| E-6 | false | false | 기간 외 | 구독 탭 카드 | check_subscribe_page | found=false? | 비히든+날짜지정(기간외) (대조군) |

### F. 웹링크 타겟이 히든+날짜지정일 때 (진단 엔진 핵심 시나리오)

| TC | 웹링크 타겟 상태 | 확인 영역 | check 함수 | expected (가설) | 비고 |
|----|-----------------|----------|-----------|----------------|------|
| F-1 | ACTIVE+비히든+상시 | 구독 탭 → 클릭 | check_subscribe_club | 정상 이동 | 정상 케이스 (대조군) |
| F-2 | ACTIVE+히든+상시 | 구독 탭 → 클릭 | check_subscribe_club | 정상 이동? | 히든이어도 URL 접근은 되니까 |
| F-3 | ACTIVE+히든+날짜지정(기간내) | 구독 탭 → 클릭 | check_subscribe_club | 정상 이동? | 기간 내라면 |
| F-4 | ACTIVE+히든+날짜지정(기간외) | 구독 탭 → 클릭 | check_subscribe_club | **에러?** | **핵심: 여기서 에러 나면 "불안정" 근거 확립** |

---

## 실행 순서

### 1단계: 상태 변경 (세팅 에이전트)
코드 148 상품페이지의 isHidden, isAlwaysPublic, 공개 기간을 조합별로 변경.

변경 가능 여부 확인 필요:
- `update_product_page_hidden`: isHidden 변경 ✅
- 날짜지정/상시 전환: API로 가능한지 확인 필요 (관리자센터 직접 수정이 필요할 수 있음)

### 2단계: 노출 확인 (QA 에이전트)
각 TC별 check 함수 호출 → 결과 기록.

### 3단계: 결과 분석
- E-2, F-4가 핵심: **히든+날짜지정(기간외)에서 URL 접근 불가하면** → 진단 규칙 유지, 메시지 개선
- E-2가 accessible=true이면 → **날짜지정은 히든 상태에서 영향 없음** → 진단 규칙 과도한 경고, 제거 또는 완화

### 4단계: 진단 엔진 보정
테스트 결과에 따라 `diagnose_engine.py` L324 분기 수정:
- 근거 확립 시: 메시지를 "히든+날짜지정(기간외)에 URL 접근 불가" 등 정확하게 변경
- 근거 없음 시: 해당 체크 제거 또는 경고 수준을 warning으로 하향

### 5단계: 결과 기록
`knowledge/노출-테스트-결과.md`에 E, F 시리즈 결과 추가.

---

## 테스트 환경

- 세팅 에이전트: localhost:8000 (라이브 모드)
- QA 에이전트: localhost:8001
- us-plus: localhost:3000 (web-mcp 브랜치)
- 테스트 대상: 에이전트 테스트 오피셜 클럽, 코드 148 상품페이지

## 사전 작업: 테스트 환경 자동 셋업

현재 테스트 실행 전 수동으로 3개 프로세스를 띄워야 함. 이를 자동화.

### 자동화 대상

1. **us-plus (web-mcp 브랜치)**: `localhost:3000`
   - web-mcp 브랜치 체크아웃 + dev 서버 시작
   - Web MCP tool 등록 확인

2. **QA 에이전트 (us-explorer-agent)**: `localhost:8001`
   - QA 에이전트 서버 시작
   - Web MCP 연결 확인 (us-plus가 떠있어야)

3. **세팅 에이전트 (us-product-agent)**: `localhost:8000`
   - 라이브 모드로 서버 시작

### 구현 방향

- 단일 스크립트 (`scripts/start-test-env.sh` 등)로 3개 프로세스 순차 시작
- 각 서버 health check 후 다음 단계 진행
- 종료 시 전체 정리 (trap)
- 또는 docker-compose / tmux 세션으로 관리
