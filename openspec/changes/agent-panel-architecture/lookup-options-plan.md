# 선언적 사전 조회 — lookup_options 오케스트레이터 tool

## 배경

자유대화에서 slots이 부분적으로 모였을 때 (예: 오피셜클럽은 알지만 상품페이지는 모름), 오케스트레이터가 유저에게 질문만 하고 executor에 넘기지 않는 문제.

harness의 slot_resolvers는 executor → request_action 경로를 타야 작동하는데, 오케스트레이터가 정보를 자체적으로 모으려 하면 harness까지 안 감.

## 제안

slot_resolvers 선언을 오케스트레이터 레벨 tool로 노출.

```python
@strands_tool
def lookup_options(slot_name: str, known_slots: dict) -> str:
    """부족한 슬롯의 선택지를 조회합니다.
    registry.yaml의 slot_resolvers에 선언된 것만 조회 가능합니다.

    Args:
        slot_name: 조회할 슬롯 (예: "page_id", "product_id")
        known_slots: 이미 알고 있는 슬롯 (예: {"master_cms_id": "135", "master_name": "조조형우"})
    """
```

### 흐름

```
유저: "상품페이지 비공개해줘"
오케스트레이터: "어느 오피셜클럽이요?"

유저: "조조형우"
오케스트레이터:
  1. lookup_options("page_id", {"master_cms_id": "135", "master_name": "조조형우"}) 호출
  2. → 상품페이지 목록 반환
  3. "어떤 상품페이지를 비공개할까요? [1. 월간 리포트, 2. 단건 특강, ...]" 응답
→ 한 턴에 완료
```

### 핵심 포인트

- **선언된 것만 조회 가능**: slot_resolvers YAML에 없는 슬롯은 거부 → 불필요한 조회 방지
- **한 턴에 tool 호출 + 응답**: Strands Agent는 한 턴에 tool 여러 번 호출 가능
- **harness 경유 불필요**: 조회(read)는 오케스트레이터에서, 실행(write)은 executor → harness
- **프롬프트 강제 문제 없음**: tool이 존재하면 LLM이 적절히 호출. "조회하라"는 지시는 잘 따르는 편 (3/27 교훈: 실행 지시만 무시)

### 검토 필요 사항

1. **프롬프트로 충분한가?**: O12에 "오피셜클럽만 특정되면 lookup_options로 목록을 보여줘라" 추가하면 되는지, 아니면 tool 존재만으로 LLM이 적절히 호출하는지
2. **오케스트레이터 tool 수 증가 영향**: 현재 5개(diagnose, query, execute, guide, ask_domain_expert) + lookup_options = 6개. Vercel 연구에서 tool 수가 늘면 정확도 감소하는 경향
3. **query tool과 중복**: 기존 query tool도 상품페이지 목록을 조회하는데, lookup_options와 역할이 겹침. 통합 vs 분리?
4. **slot_resolvers 재사용**: harness._assist_missing_slots()와 lookup_options가 같은 YAML을 읽음. 공통 함수로 추출 필요

### 스코프

- [ ] `lookup_options` tool 구현 (slot_resolvers YAML 기반)
- [ ] 오케스트레이터 tools에 등록
- [ ] ORCHESTRATOR_PROMPT에 사용 가이드 추가
- [ ] query tool과 역할 정리 (중복 제거)
- [ ] 테스트: G-1 시나리오 (상품페이지 수정 → 오피셜클럽 → 목록 표시)
