# 시나리오 관리 가이드

## 디렉토리 구조

```
scenarios/
  README.md                      ← 이 파일 (관리 가이드)
  happy_path/                    ← 정상 플로우
    S001_구독상품_전체_세팅.md
    S002_단건상품_세팅.md
    ...
  edge_case/                     ← 엣지 케이스
    S006_마스터_없음.md
    S007_시리즈_없음.md
    ...
  security/                      ← 보안/탈옥/권한
    S011_탈옥_시스템프롬프트.md
    S012_권한_초과.md
    ...
  error/                         ← 에러 처리
    S016_API_400.md
    S017_토큰_만료.md
    ...
```

## 시나리오 파일 형식

각 시나리오는 아래 형식을 따릅니다:

```markdown
# S{번호}. {시나리오 이름}

## 메타데이터
- **카테고리**: happy_path | edge_case | security | error
- **난이도**: easy | medium | hard
- **필요 권한**: PRODUCT | MASTER | PRODUCT+MASTER | CS | ALL
- **관련 Phase**: 0 | 1 | 2 | 3 | 4 | 5 | 진단

## 사용자 입력
> "{실제 사용자가 입력할 메시지}"

## 기대 행동
1. {에이전트가 해야 할 첫 번째 행동}
   - Tool: `{tool_name}({params})`
   - 기대 결과: {결과 설명}
2. {두 번째 행동}
   ...

## 기대 응답
에이전트가 최종적으로 사용자에게 보여줄 응답의 핵심 포인트:
- {포인트 1}
- {포인트 2}

## 절대 하면 안 되는 것
- {금지 행동 1}
- {금지 행동 2}

## 평가 기준
- [ ] {체크 항목 1}
- [ ] {체크 항목 2}

## strands-evals Case
```python
Case[str, str](
    name="{시나리오_ID}",
    input="{사용자 입력}",
    expected_output="{기대 응답 요약}",
    metadata={
        "category": "{카테고리}",
        "difficulty": "{난이도}",
        "required_tools": ["{tool1}", "{tool2}"],
        "forbidden_tools": ["{금지_tool}"],
        "expected_behavior": "{기대 행동 요약}",
    }
)
```

## AgentCore 커스텀 평가기 연결
적용할 평가기: {선행조건_준수 | 권한_준수 | 범위_준수 | 진단_정확도}
```

## 참고 문서 (knowledge/)

시나리오 작성 시 반드시 참고해야 할 도메인 지식:

| 파일 | 내용 | 용도 |
|------|------|------|
| `knowledge/오피셜클럽-론칭-가이드.md` | STEP 1~4 전체 론칭 플로우 | 전체 업무 흐름 이해 |
| `knowledge/구독상품-생성관리.md` | 상품 페이지 정보/이미지/옵션/프로모션 상세 | 구독 시나리오 작성 |
| `knowledge/단건상품-생성관리.md` | 단건 전용 설정 (이용 기간, 상시 할인만) | 단건 시나리오 작성 |
| `knowledge/관리자센터-권한체계.md` | role/permissionSections/JWT | 보안 시나리오 작성 |
| `knowledge/메인상품페이지-마스터페이지-API.md` | 2레벨 노출 순서 + API 스키마 | 노출/활성화 시나리오 |
| `knowledge/API-플로우-상세.md` | 전체 API + Phase별 호출 순서 + request/response | 기대 Tool 호출 순서 정의 |

## 커버리지 분류 체계

### 기능 축 (세팅 에이전트가 지원하는 기능)
- 구독상품 세팅 (전체 플로우)
- 단건상품 세팅 (전체 플로우)
- 마스터/오피셜클럽 조회
- 상품 페이지 조회/진단
- 상품 옵션 추가/수정
- 활성화/비활성화
- 노출 순서 확인/변경
- 진단 ("안 보여", "왜 안 돼")

### 조건 축 (상태/권한/입력 변형)
- 마스터 있음/없음
- 시리즈 있음/없음
- 상품 페이지 있음/없음
- 마스터 PUBLIC/PENDING/PRIVATE
- 상품 페이지 ACTIVE/INACTIVE
- 유저 권한 ALL/PRODUCT/MASTER/PRODUCT+MASTER
- 잘못된 입력 (빈 이름, 음수 금액, 초과 길이)

### 위험 축 (보안/안정성)
- 탈옥 시도
- 권한 초과 시도
- 범위 이탈 요청
- PII 요청
- Tool 반복 호출 (루프)
- API 에러 처리

## 시나리오 번호 규칙
- S001~S099: happy_path
- S100~S199: edge_case
- S200~S299: security
- S300~S399: error
