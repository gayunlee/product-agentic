# 테스트 시스템 검토 — mock/live 분리 및 자동화

## 현재 상태

| 레이어 | 개수 | 모드 | 자동화 | 문제 |
|--------|------|------|--------|------|
| 유닛 테스트 | 214개 | mock (자체 내장) | ✅ `pytest` | 서버 불필요, API 안 침 |
| E2E 테스트 | 14개 | mock (서버 필요) | ✅ `pytest` + `MOCK_MODE=true` 서버 | 라이브 케이스 커버 안 됨 |
| 라이브 테스트 | 0개 | - | ❌ 없음 | 수동 테스트만 |
| QA 테스트 | qa-test-plan.md | live | ❌ 계획만 | 세팅+QA 에이전트 수동 실행 |

### 문제점

1. **라이브 E2E 없음**: 부분 검색(P2), 진단 모순(P3) 같은 실제 API 의존 버그를 자동 검증 불가
2. **mock과 live 데이터 괴리**: mock은 항상 성공하지만 live에서 검색 실패하는 케이스 미커버
3. **QA 테스트 자동화 없음**: qa-test-plan.md에 TC 40개+ 있지만 실행은 수동
4. **테스트 환경 셋업 수동**: 3개 프로세스(세팅 에이전트, QA 에이전트, us-plus) 수동 시작

## 검토 항목

### 1. 테스트 레이어 재정의

| 레이어 | 목적 | 모드 | 실행 방법 |
|--------|------|------|----------|
| 유닛 | 개별 함수/모듈 검증 | mock | `pytest tests/` |
| E2E mock | 멀티에이전트 플로우 검증 (LLM 호출 포함) | mock 서버 | `pytest tests/test_e2e_conversation.py` |
| E2E live | 실제 API 연동 검증 | live 서버 | 신규 필요 |
| QA 통합 | us-plus 앞단 노출 검증 | live + QA 에이전트 + Web MCP | 신규 필요 |

### 2. 라이브 E2E 테스트 추가

P2/P3 같은 라이브 API 의존 케이스용:

```python
# tests/test_e2e_live.py
@pytest.mark.live  # mock E2E와 분리
class TestLiveSearch:
    def test_partial_name_search(self):
        """G-10: 부분 이름으로 검색."""
        r = _chat("에이전트 테스트 클럽 노출되고 있어?", sid)
        # 부분 이름으로도 찾아야 함
        
    def test_diagnose_empty_result_no_contradiction(self):
        """G-12: 존재하지 않는 대상 진단 시 모순 없어야."""
        r = _chat("없는오피셜클럽123 진단해줘", sid)
        assert "정상" not in r["message"] or "데이터 없음" not in r["message"]
```

실행: `MOCK_MODE=false pytest tests/test_e2e_live.py -m live`

### 3. QA 테스트 자동화

qa-test-plan.md의 TC를 자동 실행하는 러너:

```python
# tests/test_qa_integration.py
@pytest.mark.qa  # 세팅+QA 에이전트+us-plus 필요
class TestQAIntegration:
    """qa-test-plan.md의 TC를 자동 실행."""
    
    @pytest.mark.parametrize("tc", load_qa_test_plan("G"))
    def test_g_series(self, tc):
        """자유대화 품질 테스트."""
        # tc.turns를 순서대로 실행, tc.invariants 검증
```

### 4. 테스트 환경 자동 셋업

`diagnose-coverage-plan.md`에 이미 계획됨. 단일 스크립트로 3개 프로세스 시작.

### 5. CI 통합 고려

| 단계 | 트리거 | 테스트 |
|------|--------|--------|
| PR 체크 | push | 유닛 214개 (빠름, mock) |
| merge 후 | main push | E2E mock 14개 (LLM 호출, 느림) |
| 수동/스케줄 | 주 1회 또는 수동 | E2E live + QA 통합 |

## 스코프

- [ ] 테스트 레이어 정의 및 pytest marker 도입 (`@pytest.mark.live`, `@pytest.mark.qa`)
- [ ] `tests/test_e2e_live.py` 신규 생성 (P2/P3 + G-10~G-12)
- [ ] QA 테스트 러너 설계 (qa-test-plan.md YAML 변환 → 자동 실행)
- [ ] 테스트 환경 자동 셋업 스크립트
- [ ] mock 데이터와 live 데이터 차이 목록 정리
