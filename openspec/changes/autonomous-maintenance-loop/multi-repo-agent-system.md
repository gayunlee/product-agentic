# 멀티레포 에이전트 시스템 — 설계

## Why

상품 에이전트 기능 확장/운영 시 us-product-agent, us-explorer-agent, us-web 3개 레포에 걸쳐 동시 작업이 필요하다. 현재는 사람이 3개 레포를 오가며 수동 작업하는데, 이를 **레포별 에이전트가 계약 기반으로 병렬 작업**하는 시스템으로 전환한다.

## 핵심 구조

### 레포별 에이전트 (3개)

| 에이전트 | 레포 | 역할 |
|---------|------|------|
| product-agent | us-product-agent | 세팅 에이전트 코드. 필요한 세팅 정의, 하네스/액션 구현 |
| explorer-agent | us-explorer-agent | QA 에이전트 코드. 서비스 앞단 검증, 결과 수집 |
| web-agent | us-web (us-plus) | web-mcp 인터페이스. 서비스 노출, 프론트 구현 |

각 에이전트는 자기 레포를 잘 알고 있으며, **모드에 따라 하는 일이 달라진다**.

### 2가지 모드

#### 구현 모드 (기능 확장 시)
```
1. 탐색 — 각 에이전트가 자기 레포에서 현재 상태/가능한 것 파악
2. 계약 도출 — 3개 에이전트의 탐색 결과를 종합하여 인터페이스 계약 생성
3. 구현 — 계약 기반으로 각 에이전트가 병렬로 코드 수정
```

- product-agent: 세팅에 필요한 것 정의, 액션/하네스 구현
- web-agent: us-plus web-mcp에서 뭐가 가능한지 탐색, 프론트 구현
- explorer-agent: QA 시나리오 정의, 검증 로직 구현

#### QA 모드 (운영 테스트 시)
```
1. 환경 셋업 — 3개 서비스 자동 기동 (start-test-env.sh)
2. 테스트 실행 — 세팅 조합 경우의 수별 변경 → 서비스 결과 확인
3. 결과 수집 — 각 조합의 결과 기록, 이상 케이스 식별
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

### 자가발전 루프

에이전트가 구현/테스트 중 발견한 것을 자동 축적:

```
[발견] → [기록] → [다음 루프에 반영]
```

| 발견 유형 | 축적 위치 | 예시 |
|----------|----------|------|
| 버그 | qa-test-plan.md TC 추가 | "히든+날짜지정 시 노출 불안정" → TC E-3 |
| 계약 위반 | contracts/*.yaml 업데이트 제안 | "web-mcp에 product_status 필드 누락" |
| 새 invariant | contracts/*.yaml 규칙 추가 | "비공개 상품은 서비스에서 절대 노출 불가" |
| 하네스 에러 패턴 | fix_hint 축적 | "slot 누락 시 자동 조회 가이드" |
| few-shot 부족 | 라우팅 few-shot 추가 | "이 패턴은 executor로 가면 안 됨" |

### 루프 리포트

매 루프마다 사람이 리뷰할 수 있는 리포트 생성:

```markdown
## 루프 리포트 — {날짜} {시간}

### 발견
- [버그] {설명} → {축적 위치} 추가
- [계약] {설명} → 계약 업데이트 제안

### 변경
- {레포}: {파일} 수정 (diff 링크)
- 테스트: {N}개 추가, 전체 통과율 {pass}/{total}

### 승인 필요
- [ ] {판단이 필요한 항목}
```

## 구현 방법

### Claude Code Agent SDK

```python
# 구현 모드 실행
async def run_implementation_mode(task_description: str):
    # 3개 에이전트 병렬 탐색
    results = await asyncio.gather(
        query(prompt=f"탐색: {task_description}", 
              options=ClaudeAgentOptions(cwd=PRODUCT_AGENT_DIR, ...)),
        query(prompt=f"탐색: {task_description}",
              options=ClaudeAgentOptions(cwd=WEB_DIR, ...)),
        query(prompt=f"탐색: {task_description}",
              options=ClaudeAgentOptions(cwd=EXPLORER_DIR, ...)),
    )
    
    # 계약 도출
    contract = await query(
        prompt=f"탐색 결과를 종합하여 계약 생성:\n{results}",
        options=ClaudeAgentOptions(cwd=PRODUCT_AGENT_DIR, ...),
    )
    
    # 계약 기반 병렬 구현
    await asyncio.gather(
        query(prompt=f"계약 기반 구현:\n{contract}", 
              options=ClaudeAgentOptions(cwd=PRODUCT_AGENT_DIR, ...)),
        query(prompt=f"계약 기반 구현:\n{contract}",
              options=ClaudeAgentOptions(cwd=WEB_DIR, ...)),
        query(prompt=f"계약 기반 구현:\n{contract}",
              options=ClaudeAgentOptions(cwd=EXPLORER_DIR, ...)),
    )
    
    # 리포트 생성
    generate_loop_report()
```

### 사람의 역할

| 단계 | 사람 | 에이전트 |
|------|------|---------|
| 모드 전환 | 트리거 | 실행 |
| 계약 정의 | 승인 | 초안 생성 |
| 구현 | 리뷰 | 코드 수정 |
| 테스트 결과 | 리뷰/승인 | 실행/기록 |
| 축적된 규칙 | 리뷰 | 자동 추가 |

나중에 자율 루프로 전환 시: 사람의 "트리거"를 Langfuse 에러 로그/웹훅으로 대체, "리뷰"를 리포트 기반 비동기 승인으로 전환.

## 선행 작업

1. **us-plus web-mcp 인터페이스 탐색** — 계약 첫 버전 도출
2. **계약 포맷 확정** — YAML 스키마 정의
3. **레포별 에이전트 프롬프트 작성** — 구현 모드/QA 모드별 행동 규칙
4. **start-test-env.sh 검증** — QA 모드 환경 셋업 확인
5. **루프 리포트 템플릿** — 리뷰 포맷 확정

## References

- `proposal.md` — 자율 유지보수 루프 원본 제안 (역할별 에이전트 구조)
- `test-system-review.md` — 테스트 레이어 분리 계획
- `scripts/start-test-env.sh` — 테스트 환경 자동 셋업
- Claude Code Agent SDK — 메인 에이전트 + 서브에이전트 구조
