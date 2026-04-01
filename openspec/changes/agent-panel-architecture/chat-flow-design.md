# 채팅 에이전트 하네스 설계 (v2)

## 핵심 관점

**위저드 = 자주 쓰는 작업 단축키** (버튼, LLM 없음, 0.04초)
**채팅 = 에이전트가 자연어로 알아서 처리** (LLM, agentic, ~15초)

위저드는 이미 잘 동작한다. 건드리지 않는다.
이 문서는 **채팅 경로**를 안정적이고 확장 가능하게 만드는 설계다.

### 설계 원칙

1. **에이전트의 agentic 자유도를 유지한다** — LLM이 판단하고, 질문하고, slot-filling한다
2. **도메인 규칙은 코드(YAML)가 실행한다** — LLM은 규칙을 모른다. 코드가 체크하고 결과를 반환한다
3. **프롬프트 의존을 최소화한다** — 검증/확인/실행 규칙은 프롬프트에 안 쓴다. Harness가 강제한다
4. **시나리오/규칙 추가는 YAML** — 코드 변경 없이 확장
5. **경계 밖에서는 솔직하게** — 모르면 모른다고 하고, 비슷한 게 있으면 제안한다

### 과거 교훈 반영

| 교훈 | 해결 방식 |
|------|----------|
| LangGraph 17-node 실패 (프레임워크 ≠ 로직) | 그래프 없음. 분류 → 핸들러 디스패치 |
| LLM 라우팅 시 대화 이력 오염 | 벡터+패턴 우선. LLM fallback 최소화 |
| Executor 과부하 | 쓰기 tool 제거, request_action 단일 게이트 |
| 프롬프트 무시됨, 하네스가 강제 | 도메인 규칙을 코드로 실행, LLM은 규칙을 모름 |
| 위저드 370x 빠름 | 위저드는 단축키로 유지, 채팅과 별개 |

---

## 1. 3계층 분리

모든 에이전트 동작을 3계층으로 나눈다.

### Layer 1: 코드로 강제 (Harness + Domain Rules)

LLM이 아무리 이상해도 **코드가 막거나 코드가 실행하는 것들.**
프롬프트에 쓰지 않는다. LLM이 몰라도 된다.

```yaml
# 절대 규칙
hard_constraints:
  - id: HC1
    rule: "쓰기 API는 request_action 게이트를 통해서만 호출 가능"
    enforcement: "쓰기 tool 자체가 Executor에 없음"

  - id: HC2
    rule: "request_action 실행 전 도메인 규칙(visibility_chain, prerequisites) 자동 체크"
    enforcement: "Harness가 YAML 규칙 로드 → 코드로 평가 → 실패 시 에러 반환"

  - id: HC3
    rule: "request_action 실행 전 유저 확인 필수"
    enforcement: "Harness가 confirmation 자동 생성, 버튼 클릭 전 API 안 호출"

  - id: HC4
    rule: "cascading 조건 해당 시 경고 자동 포함"
    enforcement: "Harness가 confirmation에 경고 자동 삽입"

  - id: HC5
    rule: "실행 후 사후 검증"
    enforcement: "Harness가 post_action.verify 자동 실행"

  - id: HC6
    rule: "시스템 프롬프트/토큰 노출 금지"
    enforcement: "Bedrock Guardrails"
```

### Layer 2: 프롬프트로 유도 (Soft Rules)

LLM이 **대부분 지키지만**, 안 지켜도 Layer 1이 잡아주는 것들.

```yaml
soft_rules:
  - id: SR1
    rule: "마스터 → 페이지 → 상품 순서로 좁혀가며 확인"
    why: "유저 경험. 역순으로 물어보면 혼란"
    fallback: "순서 안 지켜도 request_action에서 슬롯 검증"

  - id: SR2
    rule: "'상품'과 '상품페이지' 구분이 모호하면 물어보기"
    why: "잘못된 대상에 작업하면 안 됨"
    fallback: "request_action에서 대상 타입 검증"

  - id: SR3
    rule: "검색 결과가 여러 개면 목록 보여주고 선택받기"
    why: "자동 선택하면 유저 의도와 다를 수 있음"
    fallback: "1개여도 request_action에서 확인 단계 있음"

  - id: SR4
    rule: "실행 전에 대상을 명시적으로 보여주기"
    why: "유저가 뭐가 바뀌는지 알아야"
    fallback: "Harness confirmation에 대상 포함됨"
```

### Layer 3: 경계 밖 처리 (Fallback)

시나리오에 없는 요청이 왔을 때.

```yaml
boundary_handling:
  capabilities:
    can_do:
      - "상품/상품페이지 공개/비공개 전환"
      - "히든 처리/해제"
      - "메인 상품페이지 설정"
      - "노출 진단 (왜 안 보이는지)"
      - "런칭 체크"
      - "상품페이지/상품 목록 조회"
      - "관리자센터 페이지 안내"
      - "상품 도메인 개념 설명"
    cannot_do:
      - "상품페이지 직접 생성 (관리자센터에서 직접)"
      - "시리즈 생성 (파트너센터)"
      - "마스터 publicType 변경"
      - "결제/환불 처리"
      - "상품 도메인 외 질문"

  when_unsure:
    - priority: 1
      condition: "요청이 can_do에 가까운데 표현이 다른 경우"
      action: "혹시 ㅇㅇ을 말씀하시는 건가요?"

    - priority: 2
      condition: "요청이 cannot_do에 해당"
      action: "안내 + 대안 제시"

    - priority: 3
      condition: "아예 모르는 요청"
      action: "솔직히 모른다 + 할 수 있는 것 목록 제시"

    - priority: 4
      condition: "말을 이해 못 하겠음"
      action: "다시 질문 요청"
```

---

## 2. Domain Rules — Single Source of Truth

도메인 규칙을 한 곳에 선언하고, 진단/사전조건/프롬프트가 전부 이걸 참조한다.

### 핵심 아이디어

```
현재:
  validator.py에 Python if/elif로 하드코딩
  → 규칙 바뀌면 코드 수정 + 테스트 + 배포

변경:
  visibility_chain.yaml에 선언적으로
  → 규칙 바뀌면 YAML 수정 → 서버 재시작 → 끝
```

### Visibility Chain

```yaml
# domain/visibility_chain.yaml

chains:
  official_club:
    label: "오피셜클럽 노출"
    description: "구독 탭, 마스터 추천 탭에서 보이려면"
    requires:
      - id: R8
        check: "master.publicType == 'PUBLIC'"
        fail_message: "오피셜클럽이 PRIVATE 상태입니다"
        notes:
          - "R9: PRIVATE이어도 URL 직접 접근은 가능 (의도적)"
          - "R10: PRIVATE 전환 시 피드에서도 사라짐"

  subscribe_tab_card:
    label: "구독탭 카드 노출"
    description: "구독 탭에서 카드가 보이고 버튼이 활성화되려면"
    requires:
      - id: R8
        check: "master.publicType == 'PUBLIC'"
        fail_message: "오피셜클럽이 PRIVATE 상태입니다"
      - id: R0
        check: "mainProduct.viewStatus == 'ACTIVE'"
        fail_message: "메인 상품페이지가 EXCLUDED 상태입니다"
        cascading_notes:
          - "R12: 구독 탭에서 카드 자체가 사라짐"
          - "R13: 클럽 페이지 멤버십 배너도 사라짐"
          - "R14: 클럽 페이지 접근 자체는 가능 (콘텐츠만)"

  product_page_accessible:
    label: "상품페이지 접근"
    description: "상품페이지 URL로 접근 가능하려면"
    requires:
      - id: R1
        check: "page.status == 'ACTIVE'"
        fail_message: "상품페이지가 비공개(INACTIVE) 상태입니다"
    notes:
      - "R2: 히든(isHidden)이면 URL 접근은 가능하지만 목록에서 안 보임"

  product_visible:
    label: "상품 노출"
    description: "유저가 상품을 보고 구매할 수 있으려면"
    requires:
      - id: R8
        check: "master.publicType == 'PUBLIC'"
        fail_message: "오피셜클럽이 PRIVATE 상태입니다"
      - id: R0
        check: "mainProduct.viewStatus == 'ACTIVE'"
        fail_message: "메인 상품페이지가 EXCLUDED 상태입니다"
      - id: R1
        check: "page.status == 'ACTIVE'"
        fail_message: "상품페이지가 비공개(INACTIVE) 상태입니다"
      - id: R3
        check: "page.period.isCurrentlyActive"
        fail_message: "노출 기간이 아닙니다 ({period.start}~{period.end})"
      - id: R5
        check: "product.isDisplay == true"
        fail_message: "상품이 비공개 상태입니다"

  weblink:
    label: "구독탭 웹링크"
    description: "구독탭에서 웹링크 버튼이 동작하려면"
    requires:
      - id: R6
        check: "webLinkStatus == 'ACTIVE'"
        fail_message: "웹링크가 비활성 상태입니다"
      - id: R6_target
        check: "webLink.targetPage.status == 'ACTIVE'"
        fail_message: "웹링크가 비공개 페이지를 가리킵니다"
```

### 이 데이터를 누가 쓰는가

```
┌─────────────────────────┐
│  visibility_chain.yaml  │  ← Single Source of Truth
└─────────┬───────────────┘
          │
          ├─→ DiagnoseEngine
          │   "왜 안 보여?" → chain 위→아래 체크 → 첫 실패 보고
          │
          ├─→ ActionHarness (prerequisites)
          │   "상품 공개해줘" → product_visible chain 체크
          │   → 상위 조건 미충족 시 에러 반환
          │
          └─→ KnowledgeHandler (참고용)
              "노출 조건이 뭐야?" → chain 구조를 설명 소스로 활용
```

**LLM 프롬프트에는 이 데이터가 들어가지 않는다.** LLM은 `diagnose_visibility()`나 `request_action()`을 호출하면 되고, 규칙 체크는 코드가 한다.

---

## 3. Action Registry

에이전트가 실행할 수 있는 모든 상태 변경 액션을 정의한다.

```yaml
# actions/registry.yaml

actions:
  update_product_display:
    label: "상품 공개/비공개"
    category: mutate
    required_slots:
      - product_id
      - is_display
    resolved_slots:
      - master_cms_id
      - page_id
    visibility_chain: product_visible     # ← domain rules 참조
    prerequisites:
      - check: "product.exists"
        fail: "상품을 찾을 수 없습니다"
      - check: "product.isDisplay != {is_display}"
        fail: "이미 {is_display ? '공개' : '비공개'} 상태입니다"
    cascading:
      - condition: "is_display == false AND page.displayedProductCount == 1"
        severity: warning
        message: "이 상품이 마지막 공개 상품입니다."
        suggest_action: update_product_page_status
        suggest_params: { status: "INACTIVE" }
    confirmation:
      template: |
        **{action_label}**
        대상: {master_name} > {page_title} > {product_name}
        변경: {from_state} → {to_state}
      require: true
    api:
      function: update_product_display
      params:
        product_id: "{product_id}"
        is_display: "{is_display}"
    post_action:
      verify:
        api: get_product_list_by_page
        params: { page_id: "{page_id}" }
        check: "product.isDisplay == {is_display}"
        fail: "변경이 반영되지 않았습니다."
      navigate:
        url: "/product/page/{page_id}?tab=products"
        label: "결과 확인"

  update_product_page_status:
    label: "상품페이지 공개/비공개"
    category: mutate
    required_slots:
      - page_id
      - status
    resolved_slots:
      - master_cms_id
    visibility_chain: product_page_accessible
    prerequisites:
      - check: "page.exists"
        fail: "상품페이지를 찾을 수 없습니다"
      - check: "page.status != {status}"
        fail: "이미 {status} 상태입니다"
    cascading:
      - condition: "status == 'INACTIVE' AND master.activePageCount == 1"
        severity: warning
        message: "마지막 공개 상품페이지입니다."
        suggest_action: update_main_product_setting
        suggest_params: { view_status: "EXCLUDED" }
    confirmation:
      require: true
    api:
      function: update_product_page_status
      params:
        product_page_id: "{page_id}"
        status: "{status}"
    post_action:
      verify:
        api: get_product_page_list
        params: { master_id: "{master_cms_id}" }
        check: "page.status == {status}"
      navigate:
        url: "/product/page/{page_id}"
        label: "결과 확인"

  update_product_page_hidden:
    label: "히든 처리/해제"
    category: mutate
    required_slots:
      - page_id
      - is_hidden
    resolved_slots:
      - master_cms_id
    prerequisites:
      - check: "page.status == 'ACTIVE'"
        fail: "비공개 상태의 페이지는 히든 설정을 변경할 수 없습니다"
      - check: "page.isHidden != {is_hidden}"
        fail: "이미 {is_hidden ? '히든' : '히든 해제'} 상태입니다"
    cascading:
      - condition: "is_hidden == false AND page.hasDateConflict"
        severity: warning
        message: "히든 해제 시 다른 날짜지정 페이지와 충돌할 수 있습니다."
    confirmation:
      require: true
    api:
      function: update_product_page
      params:
        product_page_id: "{page_id}"
        updates: { isHidden: "{is_hidden}" }
    post_action:
      navigate:
        url: "/product/page/{page_id}?tab=settings"

  update_main_product_setting:
    label: "메인 상품페이지 설정"
    category: mutate
    required_slots:
      - master_cms_id
      - view_status
    visibility_chain: subscribe_tab_card
    prerequisites:
      - check: "mainProduct.exists"
        fail: "메인 상품페이지 설정이 없습니다"
    confirmation:
      require: true
    api:
      function: update_main_product_setting
      params:
        cms_id: "{master_cms_id}"
        view_status: "{view_status}"
    post_action:
      navigate:
        url: "/master/{master_cms_id}/product"
```

---

## 4. Harness Layer

LLM과 API 실행 사이의 게이트.

### 현재 vs 변경

```
현재:
  Executor LLM → update_product_display() 직접 호출 (tool)
  → check_prerequisites는 프롬프트에서 "호출하세요"라고 요청
  → LLM이 안 부르면 그냥 실행됨

변경:
  Executor LLM → request_action(action_id, slots) 호출
  → Harness가 자동으로:
    1. required_slots 검증
    2. visibility_chain 체크 (domain rules)
    3. prerequisites 체크
    4. cascading 경고 수집
    5. confirmation 메시지 + 버튼 생성 → 유저에게
    6. 유저 [실행] 클릭 → API 호출
    7. post_action 검증 + navigate 버튼
```

### Executor Tool 변경

```
현재 Executor tools:
  ✅ search_masters               (조회 — 유지)
  ✅ get_master_detail             (조회 — 유지)
  ✅ get_product_page_list         (조회 — 유지)
  ✅ get_product_list_by_page      (조회 — 유지)
  ✅ diagnose_visibility           (진단 — DiagnoseEngine으로 교체)
  ✅ navigate                      (이동 — 유지)
  ❌ check_prerequisites           (제거 — Harness가 자동 실행)
  ❌ check_idempotency             (제거 — prerequisites에 통합)
  ❌ check_cascading_effects       (제거 — Harness가 자동 실행)
  ❌ update_product_display        (제거 — request_action으로 대체)
  ❌ update_product_page_status    (제거 — request_action으로 대체)
  ❌ update_product_page           (제거 — request_action으로 대체)
  ❌ update_main_product_setting   (제거 — request_action으로 대체)
  🆕 request_action               (추가 — 유일한 쓰기 게이트)
```

### Executor 프롬프트 변경

```
현재 (규칙 15개, E1~E15):
  E1. 사용자 요청 분석
  E3. 마스터 → 페이지 → 상품 순서로
  E5. 반드시 check_prerequisites 호출
  E6. 반드시 interrupt로 유저 확인
  E7. 확인 후 API 호출
  E10. 상품과 상품페이지 구분
  ... (15개)

변경 (5개):
  1. 조회 tool로 정보를 모아라
  2. 상태 변경이 필요하면 request_action(action_id, slots)을 호출해라
  3. request_action이 에러를 반환하면 유저에게 전달해라
  4. 진단이 필요하면 diagnose_visibility를 호출해라
  5. 모르면 모른다고 해라
```

검증/확인/실행 규칙은 프롬프트에서 사라진다. Harness가 강제하니까.
프롬프트가 15줄 → 5줄. 토큰 절약 + LLM이 지킬 규칙이 적으니 오류도 줄어듦.

### Harness 실행 흐름

```python
class ActionHarness:
    def __init__(self):
        self.registry = load_yaml("actions/registry.yaml")
        self.chains = load_yaml("domain/visibility_chain.yaml")

    def validate_and_confirm(self, action_id: str, slots: dict) -> AgentResponse:
        action_def = self.registry[action_id]

        # 1. 필수 슬롯
        missing = [s for s in action_def.required_slots if s not in slots]
        if missing:
            return build_response(f"정보가 부족합니다: {missing}", mode="error")

        # 2. visibility_chain 체크 (도메인 규칙)
        if action_def.visibility_chain:
            chain = self.chains[action_def.visibility_chain]
            for rule in chain.requires:
                if not evaluate_check(rule.check, slots):
                    return build_response(
                        message=rule.fail_message.format(**slots),
                        buttons=self._resolve_buttons(rule, slots),
                        mode="error",
                    )

        # 3. prerequisites
        for prereq in action_def.prerequisites:
            if not evaluate_check(prereq.check, slots):
                return build_response(prereq.fail.format(**slots), mode="error")

        # 4. cascading 경고
        warnings = []
        suggest_buttons = []
        for cascade in action_def.cascading:
            if evaluate_condition(cascade.condition, slots):
                warnings.append(cascade.message.format(**slots))
                if cascade.suggest_action:
                    suggest_buttons.append(...)

        # 5. confirmation 생성
        msg = action_def.confirmation.template.format(**slots)
        if warnings:
            msg += "\n\n⚠️ **주의:**\n" + "\n".join(f"- {w}" for w in warnings)

        buttons = [
            {"type": "action", "action": "execute_confirmed",
             "label": "실행", "variant": "primary", "clickable": "once",
             "payload": {"action_id": action_id, "slots": slots}},
            {"type": "action", "action": "cancel",
             "label": "취소", "variant": "ghost", "clickable": "once"},
        ] + suggest_buttons

        return build_response(msg, buttons, mode="execute")

    def execute_confirmed(self, action_id: str, slots: dict) -> AgentResponse:
        """유저가 [실행] 클릭 시."""
        action_def = self.registry[action_id]

        # API 실행
        api_fn = API_MAP[action_def.api.function]
        params = {k: v.format(**slots) for k, v in action_def.api.params.items()}
        result = api_fn(**params)

        # post_action 검증
        if action_def.post_action.verify:
            # ... 검증 로직

        # 완료 응답
        buttons = []
        if action_def.post_action.navigate:
            buttons.append({
                "type": "navigate",
                "label": action_def.post_action.navigate.label,
                "url": action_def.post_action.navigate.url.format(**slots),
                "clickable": "always",
            })

        return build_response(
            f"✅ {action_def.label} 완료",
            buttons, mode="done",
        )
```

---

## 5. DiagnoseEngine

visibility_chain.yaml을 코드로 실행하는 진단 엔진.

### 노출 진단

```python
class DiagnoseEngine:
    def __init__(self):
        self.chains = load_yaml("domain/visibility_chain.yaml")

    def diagnose(self, chain_id: str, context: dict) -> AgentResponse:
        chain = self.chains[chain_id]
        results = []

        for rule in chain.requires:
            data = self._fetch_data(rule, context)  # API 호출
            passed = evaluate_check(rule.check, data)

            results.append({
                "rule_id": rule.id,
                "passed": passed,
                "message": rule.fail_message.format(**data) if not passed else None,
                "resolve": self._make_resolve(rule, context) if not passed else None,
            })

            if not passed:
                # 상위 실패 → 하위 미검사
                remaining = chain.requires[chain.requires.index(rule)+1:]
                for r in remaining:
                    results.append({"rule_id": r.id, "skipped": True})
                break

        return self._render_checklist(results, context)
```

### 런칭 체크

```yaml
# domain/launch_check.yaml

id: launch_check
label: 런칭 체크
mode: checklist    # 계층이 아닌 독립 체크리스트 (모두 검사)

checks:
  - id: LC1
    label: 마스터 그룹
    check: "masterGroup.exists"
    fail_message: "마스터 그룹이 없습니다"
    resolve: { type: navigate, url: "/master/create" }

  - id: LC2
    label: 오피셜클럽
    check: "officialClub.exists AND publicType == 'PUBLIC'"
    fail_message: "오피셜클럽이 없거나 PRIVATE입니다"

  - id: LC3
    label: 시리즈
    check: "series.count > 0"
    fail_message: "시리즈가 없습니다"
    resolve: { type: navigate, url: "https://partner.example.com/series/create" }

  - id: LC4
    label: 상품페이지
    check: "productPages.any(status == 'ACTIVE')"
    fail_message: "공개 상품페이지가 없습니다"

  - id: LC5
    label: 상품 옵션
    check: "products.any(isDisplay == true)"
    fail_message: "노출 중인 상품이 없습니다"

  - id: LC6
    label: 메인 상품페이지
    check: "mainProduct.viewStatus == 'ACTIVE'"
    fail_message: "메인 상품페이지가 미설정 또는 EXCLUDED입니다"

  - id: LC7
    label: 대표 이미지
    check: "NOT image.isPlaceholder"
    fail_message: "대표 이미지가 플레이스홀더입니다"
```

### 진단 → 액션 전환

진단 결과에 resolve 버튼이 포함된다. resolve 버튼은 `request_action`을 트리거:

```
진단 결과:
  ✅ 오피셜클럽 — PUBLIC
  ❌ 메인 상품페이지 — EXCLUDED
  ── 상품페이지 (미검사)
  ── 상품 (미검사)

  [ACTIVE로 변경]     → request_action("update_main_product_setting", {view_status: "ACTIVE"})
                         → Harness 경유 → 확인 → 실행
```

"고쳐줘" 채팅 후속 요청도 지원:

```python
# SessionContext
last_diagnose_resolves: list[ResolveAction] | None

# 후속 요청 감지
if is_followup(message) and ctx.last_diagnose_resolves:
    resolve = ctx.last_diagnose_resolves[0]
    return harness.validate_and_confirm(resolve.action, resolve.slots)
```

---

## 6. Conversation Contract

대화 품질을 **스크립트가 아닌 계약(불변 조건)**으로 정의한다.

### 위저드 vs 계약의 차이

```
위저드 (스크립트):  "1단계: 이렇게 말한다. 2단계: 저렇게 말한다."
                    → 테스트 가능, 안정적 → 에이전트가 아님

계약 (Contract):    "실행 전에 대상이 특정되어 있어야 한다."
                    "모호하면 구분 질문을 해야 한다."
                    → 어떻게 말하든 자유, 이 조건만 지키면 OK
```

### 액션별 Contract

```yaml
# contracts/update_product_display.yaml

action: update_product_display
label: "상품 공개/비공개"

required_context:
  master_cms_id:
    resolve: "search_masters로 검색"
    if_multiple: "목록 보여주고 선택받기"
    if_zero: "마스터를 찾을 수 없다고 안내"
  page_id:
    resolve: "get_product_page_list로 조회"
    if_multiple: "목록 보여주고 선택받기"
    if_one: "자동 선택 가능 (확인 질문)"
  product_id:
    resolve: "get_product_list_by_page로 조회"
    if_multiple: "목록 보여주고 선택받기"
    if_one: "자동 선택 가능 (확인 질문)"

invariants:
  - id: no_ambiguity
    rule: "유저가 '상품'이라 했을 때 상품페이지와 상품 옵션 구분이 안 되면 물어봐야 한다"

  - id: no_auto_execute
    rule: "유저 확인 없이 쓰기 API를 호출하면 안 된다"

  - id: cascade_warning
    rule: "마지막 공개 상품이면 경고해야 한다"

  - id: target_confirmation
    rule: "실행 전에 대상을 명시해야 한다"

disambiguation:
  - input: "{name} 비공개해줘"
    ambiguous: "상품인지 상품페이지인지"
    required: "구분 질문"

  - input: "비공개해줘"
    ambiguous: "대상 전체"
    required: "마스터부터 물어보기"

  - input: "{master} {page} {product} 비공개해줘"
    ambiguous: null
    required: "확인 후 실행"
```

### Contract 기반 자동 테스트

```yaml
# tests/conversation/product_hide_ambiguous.yaml

id: product_hide_ambiguous
description: "비공개해줘"만 말했을 때 올바르게 유도하는지
contract: update_product_display

turns:
  - user: "조조형우 비공개해줘"
    expect:
      must_ask: ["상품페이지", "상품"]
      must_not: ["완료", "처리했습니다"]

  - user: "상품페이지"
    expect:
      must_show: ["목록", "선택"]

  - user: "월간 투자 리포트"
    expect:
      must_contain: ["월간 투자 리포트"]
      must_ask: ["확인"]

  - user: "응"
    expect:
      action_called: "request_action"
      params:
        action_id: "update_product_page_status"
```

### 테스트 레벨

```
Level 1 (코드 테스트):
  Harness가 잘 막는지 — 유닛 테스트
  → required_slots 미충족 시 에러?
  → visibility_chain 실패 시 차단?
  → cascading 경고 포함?

Level 2 (대화 시나리오 테스트):
  LLM이 contract invariant를 지키는지 — 다턴 대화 시뮬레이션
  → 모호할 때 물어보는지?
  → 최종 액션이 올바른지?

Level 3 (경계 테스트):
  시나리오 밖 요청에 잘 대응하는지
  → "환불해줘" → 거절 + 안내?
  → "그거 해줘" → 재질문?
```

---

## 7. 전체 아키텍처

```
유저 입력 (채팅 or 위저드 버튼)
  │
  ├─ 위저드 버튼 → WizardEngine (기존 유지, 빠른 단축키)
  │
  └─ 채팅 텍스트
      │
      ▼
  벡터/패턴 분류 (기존 유지)
      │
      ├─ 매칭됨 → Executor LLM (agentic)
      │              │
      │              ├─ 조회 tools (자유 호출)
      │              │   search_masters, get_product_page_list, ...
      │              │
      │              ├─ 대화 유도 (Layer 2 soft rules)
      │              │   "어떤 상품페이지요?" / "이걸 말씀하시는 건가요?"
      │              │
      │              ├─ request_action (유일한 쓰기 경로)
      │              │   → ActionHarness
      │              │     1. visibility_chain 체크 (YAML)
      │              │     2. prerequisites 체크 (YAML)
      │              │     3. cascading 경고 (YAML)
      │              │     4. confirmation → 유저 확인
      │              │     5. API 실행
      │              │     6. post_action 검증
      │              │
      │              ├─ diagnose_visibility (진단)
      │              │   → DiagnoseEngine
      │              │     visibility_chain.yaml 순서대로 체크
      │              │     결과 + resolve 버튼 반환
      │              │
      │              └─ navigate (이동 안내)
      │
      ├─ 유사하지만 불확실
      │   → "ㅇㅇ을 말씀하시는 건가요?"
      │
      └─ 전혀 매칭 안 됨
          → "잘 모르겠습니다" + 할 수 있는 것 안내
```

---

## 8. 파일 구조

```
us-product-agent/
├── domain/                            # 도메인 규칙 (Single Source of Truth)
│   ├── visibility_chain.yaml          # R0~R14 노출 체인
│   └── launch_check.yaml             # 런칭 체크 규칙
│
├── actions/                           # 액션 정의
│   └── registry.yaml                  # 모든 상태 변경 액션
│
├── contracts/                         # 대화 계약
│   ├── update_product_display.yaml    # 상품 공개/비공개
│   ├── update_product_page_status.yaml
│   ├── update_product_page_hidden.yaml
│   ├── diagnose_visibility.yaml
│   └── ...
│
├── prompts/                           # 프롬프트 규칙 (Layer 2, 3)
│   ├── executor_rules.yaml            # soft rules
│   └── boundary_handling.yaml         # 경계 밖 처리
│
├── wizards/                           # 기존 유지 (빠른 단축키)
│   └── ...
│
├── src/
│   ├── harness.py                     # ActionHarness (게이트)
│   ├── diagnose_engine.py             # DiagnoseEngine (규칙 평가)
│   ├── domain_loader.py               # YAML 로더 + 규칙 평가
│   ├── response.py                    # build_response (통일된 응답)
│   ├── agents/
│   │   ├── orchestrator.py            # 라우팅 (기존 유지)
│   │   ├── executor.py                # 조회 + request_action (수정)
│   │   └── domain.py                  # 지식 답변 (기존 유지)
│   ├── context.py                     # SessionContext
│   ├── wizard.py                      # WizardEngine (기존 유지)
│   └── validator.py                   # → domain/ + harness로 분산
│
├── tests/
│   ├── test_harness.py                # Level 1: Harness 유닛 테스트
│   ├── conversation/                  # Level 2: 대화 시나리오 테스트
│   │   ├── product_hide_ambiguous.yaml
│   │   ├── last_product_cascade.yaml
│   │   └── ...
│   └── boundary/                      # Level 3: 경계 테스트
│
└── server.py                          # 라우팅 + 응답 (수정)
```

---

## 9. 새 기능 추가 체크리스트

### "새 도메인 규칙 발견" (예: R15)

1. `domain/visibility_chain.yaml`에 체크 항목 추가
→ 진단, 사전조건 체크에 자동 반영. 코드 변경 0.

### "새 상태 변경 액션" (예: 시리즈 삭제)

1. `actions/registry.yaml`에 액션 정의 추가
2. `contracts/새_액션.yaml` 작성 (invariant, disambiguation)
3. (선택) `tests/conversation/` 에 다턴 테스트 추가

### "새 예외 케이스 발견" (예: 특정 조건에서 오동작)

1. 해당 contract에 invariant 추가
2. 테스트 추가
3. invariant가 Layer 1이면 → harness/domain에 체크 추가
4. invariant가 Layer 2면 → soft_rules에 추가 → 프롬프트 재생성

### "경계 밖 요청 추가" (예: "환불" 요청이 잦음)

1. `prompts/boundary_handling.yaml`에 케이스 추가
→ 프롬프트에 자동 반영. 코드 변경 0.

---

## 10. 정리

| 항목 | 현재 | 변경 후 |
|------|------|---------|
| 도메인 규칙 관리 | validator.py if/elif | visibility_chain.yaml (YAML) |
| 규칙 체크 주체 | LLM (프롬프트에 규칙) | 코드 (Harness가 YAML 실행) |
| LLM 프롬프트 크기 | 규칙 15개 | 규칙 5개 (토큰 절약) |
| 상태 변경 안전성 | 프롬프트가 요청 | Harness가 강제 |
| 새 규칙 추가 | Python 코드 수정 + 배포 | YAML 수정 + 서버 재시작 |
| 새 액션 추가 | executor.py + validator.py 수정 | registry.yaml 항목 추가 |
| 대화 품질 관리 | 직접 테스트 → 발견 → 덧대기 | contract 정의 → 자동 테스트 |
| 경계 밖 처리 | LLM이 알아서 | boundary_handling.yaml에 명시 |
| 에이전트 성격 | agentic | **그대로 agentic** |
| 위저드 | 빠른 단축키 | **그대로 유지** |

### 핵심 변경 1줄 요약

**LLM에서 쓰기 tool을 빼고, 도메인 규칙을 YAML로 옮기고, 코드(Harness)가 실행한다.**
