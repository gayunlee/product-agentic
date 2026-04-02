# 멀티레포 에이전트 시스템 — 설계

## Why

상품 에이전트 기능 확장/운영 시 us-product-agent, us-explorer-agent, us-web 3개 레포에 걸쳐 동시 작업이 필요하다. 현재는 사람이 3개 레포를 오가며 수동 작업하는데, 이를 **레포별 에이전트가 계약 기반으로 병렬 작업**하는 시스템으로 전환한다.

## 핵심 원칙: 프롬프트는 참고, 코드는 강제

하네스 엔지니어링의 핵심을 시스템 전체에 적용한다:

- **아키텍처 규칙은 코드로 검증** — LLM한테 "확인해줘"가 아니라, 체커 도구가 위반을 잡음
- **암묵지 → 명시지 → 강제** — 발견된 규칙은 문서가 아니라 검증 코드로 변환
- **실수할 때마다 체커 추가** — 같은 위반이 두 번 발생하면 안 됨
- **읽을 수 없는 것은 존재하지 않는 것** — 모든 규칙은 machine-readable

## 핵심 구조

### 레포별 에이전트 (3개)

| 에이전트 | 레포 | 역할 |
|---------|------|------|
| product-agent | us-product-agent | 세팅 에이전트 코드. 필요한 세팅 정의, 하네스/액션 구현 |
| explorer-agent | us-explorer-agent | QA 에이전트 코드. 서비스 앞단 검증, 결과 수집 |
| web-agent | us-web (us-plus) | web-mcp 인터페이스. 서비스 노출, 프론트 구현 |

각 에이전트는 자기 레포를 잘 알고 있으며, **모드에 따라 하는 일이 달라진다**.

### 2가지 모드

#### 개발 모드 (기능 확장 시)

탐색 + 구현 + 리뷰가 한 루프. 에이전트가 상황에 따라 자연스럽게 전환.

```
탐색 → 계약 도출 → 구현 → 아키텍처 체커 실행 → 위반 시 수정 → 완료
```

- product-agent: 세팅에 필요한 것 정의, 액션/하네스 구현, 아키텍처 체커 실행
- web-agent: us-plus web-mcp에서 뭐가 가능한지 탐색, 프론트 구현, FSD 규칙 체커 실행
- explorer-agent: QA 시나리오 정의, 검증 로직 구현, 체커 실행

구현 후 반드시 **아키텍처 체커를 도구로 실행**하고, 위반이 있으면 수정까지 한 뒤에 완료.

#### QA 모드 (운영 테스트 시)

다 만들어놓고 실제로 돌려보는 것.

```
환경 셋업 → 세팅 조합별 테스트 → 결과 수집 → 리포트
```

- product-agent: 관리자센터에서 세팅 변경
- web-agent: us-plus에서 서비스 노출 상태 확인
- explorer-agent: 서비스 앞단에서 결과 검증

### 계약 (Contract)

3개 에이전트가 소통하는 공유 인터페이스. `us-product-agent/contracts/` 에 위치.

```yaml
# contracts/web-mcp-interface.yaml (예시)
endpoints:
  chat:
    request: { message: string, session_id: string }
    response: { type: "sse", events: [...] }
  
  actions:
    - name: set_visibility
      slots: { master_cms_id, page_id, visibility }
      response: { success: bool, message: string }

shared_types:
  product_status: enum[active, hidden, scheduled, ...]
  harness_button: { label: string, value: string }
```

### 아키텍처 체커 (하네스 엔지니어링 핵심)

각 레포에 `checks/architecture.py` (또는 레포에 맞는 형태)를 두고, 불변 규칙을 **코드로 검증**.

에이전트는 이 체커를 **프롬프트가 아니라 도구로 실행**한다. 체커가 실패하면 에이전트가 수정.

#### us-product-agent 체커 예시

```python
# checks/architecture.py

def check_yaml_ssot():
    """registry.yaml에 없는 액션명이 코드에 하드코딩되어 있으면 실패."""
    registered = load_yaml("actions/registry.yaml")["actions"]
    code_refs = grep("request_action.*action=", "src/")
    violations = [r for r in code_refs if r.action not in registered]
    assert not violations, f"YAML SSOT 위반: {violations}"

def check_single_gate():
    """harness 외부에서 직접 API write 호출이 있으면 실패."""
    write_calls = grep("(create|update|delete)_", "src/", exclude="harness.py")
    assert not write_calls, f"단일 게이트 위반: {write_calls}"

def check_prompt_not_enforce():
    """프롬프트에서 '반드시', '절대' 등 강제 표현이 있으면 경고."""
    # 이런 표현은 Tool/Harness로 강제해야 함
    suspects = grep("(반드시|절대|무조건)", "src/agents/*.py", pattern_type="prompt")
    return warnings(suspects)  # 실패가 아닌 경고 — 리포트에 포함

def check_contract_integrity():
    """contracts/*.yaml의 정의와 실제 코드 구현이 일치하는지 검증."""
    contract = load_yaml("contracts/web-mcp-interface.yaml")
    # endpoint 존재, 타입 일치, 필수 필드 포함 여부 검증
    ...
```

#### us-web 체커 예시

```python
# checks/architecture.py (또는 lint rule)

def check_fsd_no_cross_import():
    """FSD 레이어 간 cross-import 위반 검사."""
    ...

def check_no_barrel_export():
    """중간 레벨 barrel export (ui/index.ts) 금지."""
    ...

def check_contract_types():
    """계약 파일의 shared_types와 TypeScript 타입 정의 일치 여부."""
    ...
```

#### 체커 실행 흐름

```
에이전트가 구현 완료
    ↓
checks/architecture.py 실행 (도구로)
    ↓
├── 통과 → 완료, 리포트에 "아키텍처 검증 통과" 기록
└── 실패 → 위반 내용 확인 → 수정 → 재실행
        ↓
    반복 실패 → 리포트에 "수동 리뷰 필요" 기록 → 사람한테 넘김
```

### 암묵지 축적 루프

발견된 것이 **단순 기록이 아니라 검증 코드로 변환**되는 루프:

```
[발견] → [기록 (리포트)] → [체커 코드로 변환] → [다음부터 자동 검증]
```

| 발견 유형 | 1차 축적 (기록) | 2차 축적 (강제) |
|----------|----------------|----------------|
| 아키텍처 위반 | 리포트에 기록 | checks/architecture.py에 체커 추가 |
| 버그 | qa-test-plan.md TC 추가 | tests/에 자동화 테스트 추가 |
| 계약 위반 | contracts/*.yaml 업데이트 | check_contract_integrity()에 규칙 추가 |
| 하네스 에러 패턴 | fix_hint 축적 | harness 코드에 가드 추가 |
| few-shot 부족 | 라우팅 few-shot 추가 | 라우팅 정확도 테스트에 케이스 추가 |
| 패턴 반복 (3회+) | 리팩토링 제안 | 공통 함수/설정 추출 후 체커에 중복 감지 추가 |

**핵심: 1차 축적(기록)에서 끝나면 하네스 엔지니어링이 아니다. 2차 축적(강제)까지 가야 한다.**

### 루프 리포트

매 루프마다 사람이 리뷰할 수 있는 리포트 생성:

```markdown
## 루프 리포트 — {날짜} {시간}

### 아키텍처 검증
- ✅ YAML SSOT: 통과
- ✅ 단일 게이트: 통과
- ⚠️ 프롬프트 강제 표현: 2건 (orchestrator.py:45, orchestrator.py:82)
- ❌ 계약 정합성: product_status 필드 누락

### 발견
- [버그] {설명} → TC 추가 + 테스트 코드 추가
- [규칙] {설명} → 체커 코드 추가

### 변경
- {레포}: {파일} 수정 (diff 링크)
- 체커: {N}개 규칙 추가
- 테스트: {N}개 추가, 전체 통과율 {pass}/{total}

### 승인 필요
- [ ] {판단이 필요한 항목}
- [ ] {체커가 반복 실패한 항목 — 수동 리뷰}
```

## 구현 방법

### Claude Code Agent SDK

`us-product-agent/orchestrator/` 에 위치. 각 에이전트는 `cwd`로 자기 레포에서 작업.

```python
async def run_dev_mode(task_description: str):
    # 1. 3개 에이전트 병렬 탐색
    results = await asyncio.gather(
        query(prompt=f"탐색: {task_description}", 
              options=ClaudeAgentOptions(cwd=PRODUCT_AGENT_DIR, ...)),
        query(prompt=f"탐색: {task_description}",
              options=ClaudeAgentOptions(cwd=WEB_DIR, ...)),
        query(prompt=f"탐색: {task_description}",
              options=ClaudeAgentOptions(cwd=EXPLORER_DIR, ...)),
    )
    
    # 2. 계약 도출
    contract = await query(
        prompt=f"탐색 결과를 종합하여 계약 생성:\n{results}",
        options=ClaudeAgentOptions(cwd=PRODUCT_AGENT_DIR, ...),
    )
    
    # 3. 계약 기반 병렬 구현
    impl_results = await asyncio.gather(
        query(prompt=f"계약 기반 구현:\n{contract}", 
              options=ClaudeAgentOptions(cwd=PRODUCT_AGENT_DIR, ...)),
        query(prompt=f"계약 기반 구현:\n{contract}",
              options=ClaudeAgentOptions(cwd=WEB_DIR, ...)),
        query(prompt=f"계약 기반 구현:\n{contract}",
              options=ClaudeAgentOptions(cwd=EXPLORER_DIR, ...)),
    )
    
    # 4. 아키텍처 체커 실행 (각 레포에서)
    check_results = await asyncio.gather(
        query(prompt="checks/architecture.py 실행하고 위반 있으면 수정해",
              options=ClaudeAgentOptions(cwd=PRODUCT_AGENT_DIR, ...)),
        query(prompt="checks/architecture.py 실행하고 위반 있으면 수정해",
              options=ClaudeAgentOptions(cwd=WEB_DIR, ...)),
        query(prompt="checks/architecture.py 실행하고 위반 있으면 수정해",
              options=ClaudeAgentOptions(cwd=EXPLORER_DIR, ...)),
    )
    
    # 5. 리포트 생성
    generate_loop_report(results, impl_results, check_results)

async def run_qa_mode(test_plan: str):
    # 1. 환경 셋업
    await run_bash("./scripts/start-test-env.sh")
    
    # 2. 테스트 실행 (3개 에이전트 협업)
    qa_results = await query(
        prompt=f"테스트 계획 실행:\n{test_plan}",
        options=ClaudeAgentOptions(
            cwd=PRODUCT_AGENT_DIR,
            agents={
                "setter": AgentDefinition(description="세팅 변경", ...),
                "checker": AgentDefinition(description="서비스 확인", ...),
                "verifier": AgentDefinition(description="결과 검증", ...),
            },
        ),
    )
    
    # 3. 발견사항 축적 + 리포트
    accumulate_findings(qa_results)
    generate_loop_report(qa_results)
```

### 에이전트 프롬프트에 포함할 핵심 규칙

각 레포 에이전트의 프롬프트에 공통으로:

```
## 필수 행동 규칙

1. 구현 후 반드시 `checks/architecture.py`를 실행하라 (Bash 도구로).
2. 체커가 실패하면 수정하고 재실행하라. 3회 실패 시 리포트에 "수동 리뷰 필요" 기록.
3. 새로운 아키텍처 위반 패턴을 발견하면 체커에 검증 함수를 추가하라.
4. 버그를 발견하면 (a) 수정 (b) 테스트 추가 (c) 체커에 규칙 추가 — 3단계 모두.
5. 발견한 모든 것을 루프 리포트에 기록하라.
```

**이 규칙 자체도 프롬프트이므로**, 에이전트가 안 따를 수 있다. 따라서:
- 체커 실행 여부는 오케스트레이터 코드에서 **강제** (프롬프트가 아닌 코드 흐름으로)
- 리포트 생성도 오케스트레이터 코드에서 **강제**
- 에이전트 자율에 맡기는 것: 탐색 방법, 구현 방법, 위반 수정 방법

### 사람의 역할

| 단계 | 사람 | 에이전트 |
|------|------|---------|
| 모드 전환 | 트리거 | 실행 |
| 계약 정의 | 승인 | 초안 생성 |
| 구현 | 리뷰 | 코드 수정 |
| 아키텍처 검증 | 체커 반복 실패 시 리뷰 | 체커 실행 + 자동 수정 |
| 테스트 결과 | 리뷰/승인 | 실행/기록 |
| 축적된 규칙/체커 | 리뷰 | 자동 추가 |

나중에 자율 루프로 전환 시: 사람의 "트리거"를 Langfuse 에러 로그/웹훅으로 대체, "리뷰"를 리포트 기반 비동기 승인으로 전환.

## 선행 작업

1. **아키텍처 체커 MVP** — us-product-agent의 핵심 불변 규칙 3개를 코드로 검증 (YAML SSOT, single gate, contract integrity)
2. **us-plus web-mcp 인터페이스 탐색** — 계약 첫 버전 도출 (web-agent에게 시킬 첫 번째 태스크)
3. **계약 포맷 확정** — YAML 스키마 정의
4. **오케스트레이터 프로토타입** — Agent SDK로 개발 모드 최소 동작
5. **레포별 에이전트 프롬프트 작성** — 개발/QA 모드별 행동 규칙
6. **start-test-env.sh 검증** — QA 모드 환경 셋업 확인
7. **루프 리포트 템플릿** — 리뷰 포맷 확정

## References

- `proposal.md` — 자율 유지보수 루프 원본 제안 (역할별 에이전트 구조)
- `test-system-review.md` — 테스트 레이어 분리 계획
- `scripts/start-test-env.sh` — 테스트 환경 자동 셋업
- Claude Code Agent SDK — 메인 에이전트 + 서브에이전트 구조
- 하네스 엔지니어링 4요소 — 레포 하네스, 앱 하네스, 헌법, 암묵지 좁히기
- "프롬프트는 참고, Tool은 강제" (2026-03-27 원칙)
- "실수할 때마다 재발 방지 구조 설계" (하네스 엔지니어링 핵심)
