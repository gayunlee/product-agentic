# 아키텍처 갭 — 선언과 구현 불일치 정리

## 발견 일시: 2026-04-03

## 요약

YAML로 선언적 아키텍처를 설계했지만, 코드가 선언을 안 읽거나 빠진 API가 있어서 선언이 무의미한 상태.
체커가 이걸 못 잡았음 → 체커 규칙 추가 필요.

---

## 긴급 — 선언은 있는데 구현 안 됨

### G-1. visibility_chain 코드 미구현
- **선언**: `domain/visibility_chain.yaml`에 `subscribe_tab_card`, `product_visible` 등 체인 정의
- **로드**: `harness.py:65`에서 `self.chains = load_yaml(...)` 로드함
- **문제**: `validate_and_confirm()`에서 실제로 chain 검증 안 함. 대신 `prerequisites`에서 수동 검증
- **영향**: registry.yaml의 `visibility_chain: product_visible` 선언이 무시됨
- **수정**: harness에서 visibility_chain 읽어서 자동 체크하는 로직 추가

### G-2. visibility_chain이 참조하는 API 함수 누락
- **선언**: `domain/visibility_chain.yaml`에서 `api: get_product_detail`, `api: get_weblink_target` 참조
- **문제**: `admin_api.py`에 해당 함수 없음
- **영향**: visibility_chain 구현해도 API가 없어서 실행 불가
- **수정**: `get_product_detail()`, `get_weblink_target()` 함수 추가

### G-3. update_product_sequence 함수 누락
- **선언**: `knowledge/사이드패널-UX-플로우.md`에서 활성화 Step 6에 명시
- **문제**: `admin_api.py`에 함수 없음
- **영향**: 상품 노출 순서 변경 불가
- **수정**: `update_product_sequence()` 함수 추가 (`PATCH /v1/product/group/{id}/sequence`)

### G-4. diagnose_visibility contract가 registry에 없음
- **선언**: `contracts/diagnose_visibility.yaml` 존재
- **문제**: `registry.yaml`의 `actions:` 섹션에 `diagnose_visibility` 없음
- **영향**: 체커의 contract integrity 검증이 이걸 못 잡음 (registry → contract 방향만 체크)
- **수정**: 양방향 체크 — contract → registry도 확인. 또는 diagnose는 액션이 아니라 별도 카테고리

### G-5. contracts invariants 강제 메커니즘 불명확
- **선언**: contracts/*.yaml에 `invariants` 섹션 (no_ambiguity, cascade_warning 등)
- **문제**: harness가 `prerequisites`, `cascading`, `confirmation`으로 일부 대응하지만 1:1 매핑이 아님
- **영향**: 어떤 invariant가 코드로 강제되고 어떤 게 프롬프트 수준인지 불분명
- **수정**: 각 invariant에 `enforcement` 필드 추가 (harness/code/prompt 중 어디서 강제하는지)

---

## 설계 문제 — 구조 개선 필요

### D-1. guide PAGE_MAP 하드코딩
- `admin_api.py`에 Python dict로 URL 매핑
- → `guides.yaml`로 이동 (별도 계획: guide-declarative-plan.md)

### D-2. visibility_chain과 prerequisites 이중 관리
- registry.yaml `prerequisites`와 `domain/visibility_chain.yaml`이 같은 규칙을 다르게 표현
- → visibility_chain으로 통합하고, prerequisites는 chain에서 자동 생성

### D-3. orchestrator 도구가 registry 참조 안 함
- diagnose, query, guide 도구가 registry.yaml과 독립적으로 구현
- → 도구도 registry/contracts를 읽어서 동작하는 선언적 구조로

---

## 체커 추가 필요 — 오늘 발견한 것을 자동으로 잡도록

### 추가할 체커 규칙

```python
# checks/architecture.py에 추가

def check_visibility_chain_apis():
    """visibility_chain.yaml에서 참조하는 API 함수가 admin_api.py에 존재하는지."""
    chain = load_yaml("domain/visibility_chain.yaml")
    # chain의 각 requires에서 api 필드 추출
    # admin_api.py에 해당 함수가 있는지 grep
    
def check_visibility_chain_used():
    """harness.py에서 visibility_chain을 실제로 사용하는지."""
    # self.chains 로드 후 validate_and_confirm에서 참조하는지

def check_contract_bidirectional():
    """contracts/ ↔ registry.yaml 양방향 정합성."""
    # 기존: registry에 있는데 contract 없으면 실패
    # 추가: contract에 있는데 registry에 없으면 경고 (diagnose처럼 액션이 아닌 것도 있을 수 있음)

def check_knowledge_api_exists():
    """knowledge/*.md에서 참조하는 API 함수가 admin_api.py에 존재하는지."""
    # 사이드패널-UX-플로우.md의 update_product_sequence 같은 케이스
```

---

## 우선순위

| 순위 | 항목 | 이유 |
|------|------|------|
| 1 | **체커 규칙 추가** (G-1~G-5 자동 감지) | 다시는 수동으로 발견하지 않도록 |
| 2 | **G-2 누락 API 추가** (get_product_detail, get_weblink_target, update_product_sequence) | visibility_chain 구현의 선행 조건 |
| 3 | **G-1 visibility_chain 구현** | 선언적 아키텍처의 핵심. 이게 돌아야 YAML SSOT가 의미 있음 |
| 4 | **D-1 guide YAML 선언화** (guide-declarative-plan.md) | 현재 guide 도구가 제대로 안 동작하는 원인 |
| 5 | **G-5 invariants enforcement 명시** | 어떤 게 강제되고 어떤 게 안 되는지 정리 |
| 6 | **D-2 prerequisites → visibility_chain 통합** | SSOT 확보 |
