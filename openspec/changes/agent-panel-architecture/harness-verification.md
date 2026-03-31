# 하네스 리팩토링 검증 체크리스트

Obsidian 노트(3/27~3/31)에서 추출한 시행착오 이슈 + chat-flow-design.md 설계 기반.
테스트 코드: `tests/test_harness_regression.py`

---

## 1. 코드 강제 (Harness) — Layer 1

프롬프트로 유도하던 규칙이 코드로 강제되는지.

| ID | 이슈 (노트 날짜) | 이전 | 이후 | 테스트 |
|----|-----------------|------|------|--------|
| HC1 | LLM이 쓰기 API 직접 호출 (3/27) | executor에 update_* tool 노출 | request_action만 노출 | `test_no_write_without_harness` |
| HC2 | check_prerequisites 안 부름 (3/27) | E3 프롬프트 규칙 | Harness prerequisites 자동 체크 | `test_idempotency_enforced_by_harness` |
| HC3 | 유저 확인 없이 API 호출 (3/27) | E4 프롬프트 규칙 | Harness confirmation 강제 | `test_confirmation_enforced` |
| HC4 | 계단식 경고 누락 (3/27) | E3 check_cascading_effects 호출 요청 | Harness cascading 자동 체크 | `test_cascading_enforced_by_harness` |
| HC5 | 이미 같은 상태인데 또 실행 (3/27) | check_idempotency 호출 요청 | prerequisites에서 자동 차단 | `test_idempotency_enforced_by_harness` |

## 2. 도메인 규칙 (DiagnoseEngine) — YAML Single Source of Truth

| ID | 이슈 (노트 날짜) | 확인 사항 | 테스트 |
|----|-----------------|----------|--------|
| DR1 | 메인 INACTIVE인데 "노출 중" 답변 (3/28) | DiagnoseEngine이 메인 INACTIVE를 first_failure로 보고 | `test_diagnose_detects_main_inactive` |
| DR2 | 진단 → 해결 후속 요청 미지원 (3/31) | resolve_actions 포함 | `test_diagnose_returns_resolve_actions` |
| DR3 | 노출 체인 순서 (3/28 R0~R7) | R8→R0→R1→R3→R5 순서 | `test_visibility_chain_order` |
| DR4 | 규칙 추가 시 Python 코드 변경 (3/31) | YAML만 수정하면 됨 | `test_new_rule_yaml_only` |
| DR5 | YAML이 프롬프트에 포함되면 느림 (3/31) | executor 프롬프트에 규칙 없음 | `test_yaml_not_in_prompt` |
| DR6 | Single Source of Truth (3/31) | registry ↔ visibility_chain 참조 정합성 | `test_domain_rules_single_source` |

## 3. Executor 최적화

| ID | 이슈 (노트 날짜) | 확인 사항 | 테스트 |
|----|-----------------|----------|--------|
| EO1 | 프롬프트 15개 규칙 LLM 무시 (3/27) | 5개로 축소 | `test_executor_prompt_reduced` |
| EO2 | validator tool이 executor에 불필요 (3/31) | check_* tool 제거 | `test_no_validator_tools_in_executor` |
| EO3 | Tool 23개 토큰 오버헤드 (3/29) | task_type 필터링 유지 | `test_task_type_filtering` |
| EO4 | update task_type에 request_action (3/31) | 포함 확인 | `test_request_action_in_update_tools` |

## 4. 세팅 에이전트 이슈

| ID | 이슈 (노트 날짜) | 확인 사항 | 테스트 |
|----|-----------------|----------|--------|
| SA3 | web_link 파라미터 누락 (3/28) | update_main_product_setting에 파라미터 존재 | `test_s3_web_link_parameter` |
| SA4 | 히든 해제 시 기간 충돌 미검증 (3/28) | registry.yaml cascading 정의 | `test_s4_hidden_release_cascading` |

## 5. 위저드/채팅 분리

| ID | 이슈 (노트 날짜) | 확인 사항 | 테스트 |
|----|-----------------|----------|--------|
| WC1 | 위저드가 Harness를 우회 (3/30) | 위저드는 admin_api 직접 호출 | `test_wizard_does_not_use_harness` |
| WC2 | 위저드 진단이 validator 사용 (3/30) | DiagnoseEngine으로 전환 | `test_wizard_diagnose_uses_engine` |

---

## E2E 검증 (LLM 호출 필요 — 수동)

코드 테스트로 커버 불가. 서버 띄우고 직접 채팅해야 확인되는 항목.

### 채팅 → request_action 플로우
```
1. "조조형우 상품 비공개해줘"
   → executor가 search_masters → get_product_page_list → get_product_list_by_page 호출
   → 목록 제시 후 선택 받기
   → request_action("update_product_display", {product_id, is_display: false, ...}) 호출
   → 확인 메시지 반환
   기대: mode="execute", execute_confirmed 버튼 존재

2. [실행] 버튼 클릭
   → server.py execute_confirmed 핸들러
   → harness.execute_confirmed() → API 실행
   → 완료 메시지
   기대: mode="done"

3. "왜 안 보여?" → "고쳐줘"
   → diagnose_visibility → 진단 결과 (resolve_actions 포함)
   → "고쳐줘" → server.py 후속 감지 → harness.validate_and_confirm
   기대: 확인 메시지

4. 위저드 플로우 (변경 없음 확인)
   → wizard_action="product_page_inactive"
   → 버튼 선택 → 실행 → 완료
   기대: 위저드 기존 동작 유지
```

### 맥락 유지 (기존 이슈 — 이번 범위 밖)
```
5. "조조형우 진단" → "홍춘욱은?"
   → 오케스트레이터가 같은 진단으로 라우팅
   ⚠️ 세션 ID 필요. 미지정 시 맥락 상실 가능.
```

---

## 테스트 실행 방법

```bash
# 코드 테스트 (123개, 0.3초)
MOCK_MODE=true uv run pytest tests/test_domain_loader.py tests/test_harness.py tests/test_harness_regression.py tests/test_validator.py -v

# E2E 수동 테스트
MOCK_MODE=true uv run python server.py
# → http://localhost:8000 에서 채팅
```
