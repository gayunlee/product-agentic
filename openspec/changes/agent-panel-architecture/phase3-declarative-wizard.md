# Phase 3 — 위저드 선언적 구조

## 목표

시나리오(YAML)만 작성하면 위저드가 자동으로 동작한다. 코드 수정 0.

---

## 1. 위저드 스키마

### 현재: WIZARD_ACTIONS + 코드 분기

```python
WIZARD_ACTIONS = {
    "launch_check": {"label": "런칭 체크", "target_type": "master"},
}

# + _next_after_master()에 elif
# + _handle_select()에 elif
# + _call_api()에 elif
# + _prev_step()에 elif
```

### 변경: YAML 파일로 선언

```yaml
# wizards/launch_check.yaml
id: launch_check
label: 런칭 체크
description: 오피셜클럽 런칭 준비 상태를 점검합니다
icon: 🚀

steps:
  - id: select_master
    type: select_master
    label: 클럽 선택
    message: "**런칭 체크** — 오피셜클럽을 선택하세요."

  - id: execute
    type: execute
    label: 진단 실행
    handler: launch_check    # 커스텀 핸들러 이름
```

```yaml
# wizards/product_page_inactive.yaml
id: product_page_inactive
label: 상품페이지 비공개
description: 상품페이지를 비공개로 전환합니다

steps:
  - id: select_master
    type: select_master
    label: 클럽 선택
    message: "**비공개 처리** — 오피셜클럽을 선택하세요."

  - id: select_page
    type: select_page
    label: 페이지 선택
    message: "**비공개 처리** — {master_name}의 상품페이지를 선택하세요."

  - id: confirm
    type: confirm
    label: 확인
    cascading: true           # cascading check 실행
    message: "**비공개 처리**\n\n**대상**: {target}\n\n진행하시겠어요?"

  - id: execute
    type: execute
    label: 실행
    api: update_product_page_status
    params:
      product_page_id: "{page_id}"
      status: "INACTIVE"
    done_message: "✅ **비공개 처리 완료**\n\n{target}"
    done_buttons:
      - type: navigate
        label: 결과 확인
        url: "/product/page/{page_id}"
        clickable: always
```

```yaml
# wizards/product_hide.yaml
id: product_hide
label: 상품 비공개
description: 상품 옵션을 비공개로 전환합니다

steps:
  - id: select_master
    type: select_master
    label: 클럽 선택
    message: "**상품 비공개** — 오피셜클럽을 선택하세요."

  - id: select_page
    type: select_page
    label: 페이지 선택
    message: "**상품 비공개** — {master_name}의 상품페이지를 선택하세요."

  - id: select_product
    type: select_product
    label: 상품 선택
    message: "**상품 비공개** — {page_title}의 상품을 선택하세요."

  - id: confirm
    type: confirm
    label: 확인
    cascading: true
    message: "**상품 비공개**\n\n**대상**: {target}\n\n진행하시겠어요?"

  - id: execute
    type: execute
    label: 실행
    api: update_product_display
    params:
      product_id: "{product_id}"
      is_display: false
    done_message: "✅ **상품 비공개 완료**\n\n{target}"
    done_buttons:
      - type: navigate
        label: 결과 확인
        url: "/product/page/{page_id}"
        clickable: always
```

---

## 2. 스텝 블록 타입

재사용 가능한 스텝 블록 5종:

### select_master
- API: `search_masters(search_keyword="")`
- PUBLIC 클럽 필터 + 이름순 + 최대 20개
- 선택 결과: `selections.master_cms_id`, `selections.master_name`
- 버튼: select(once) + 취소(once)

### select_page
- API: `get_product_page_list(master_id=selections.master_cms_id)`
- 선택 결과: `selections.page_id`, `selections.page_title`
- 버튼: select(once) + 이전(once) + 취소(once)

### select_product
- API: `get_product_list_by_page(page_id=selections.page_id)`
- 선택 결과: `selections.product_id`, `selections.product_name`
- 버튼: select(once) + 이전(once) + 취소(once)

### confirm
- cascading: true이면 `check_cascading_effects()` 실행
- 경고 있으면 메시지에 포함
- 버튼: 실행(once/primary) + 이전(once/ghost) + 취소(once/ghost)

### execute
- `api` + `params` 지정 → API 함수 자동 호출
- `handler` 지정 → 커스텀 핸들러 함수 호출 (launch_check 등)
- 완료 후: `done_message` + `done_buttons` 렌더링

---

## 3. 위저드 엔진

### WizardEngine (wizard.py 교체)

```python
class WizardEngine:
    """YAML 스키마를 로드하고 실행하는 범용 위저드 엔진."""

    def __init__(self):
        self.schemas: dict[str, WizardSchema] = {}
        self._load_schemas()

    def _load_schemas(self):
        """wizards/*.yaml 로드."""
        for path in Path("wizards").glob("*.yaml"):
            schema = WizardSchema.from_yaml(path)
            self.schemas[schema.id] = schema

    def get_actions(self) -> list[dict]:
        """프론트에 노출할 위저드 목록."""
        return [
            {"action": s.id, "label": s.label, "description": s.description, "icon": s.icon}
            for s in self.schemas.values()
        ]

    def create(self, action: str) -> WizardState:
        schema = self.schemas[action]
        return WizardState(schema=schema)
```

### WizardState (리팩토링)

```python
@dataclass
class WizardState:
    schema: WizardSchema
    current_step_index: int = 0
    selections: dict[str, Any] = field(default_factory=dict)
    _active: bool = True

    @property
    def current_step(self) -> StepDefinition:
        return self.schema.steps[self.current_step_index]

    def get_step_progress(self) -> dict:
        """Phase 1 StepProgress 스키마."""
        return {
            "current": self.current_step_index,
            "total": len(self.schema.steps),
            "label": self.current_step.label,
            "steps": [s.label for s in self.schema.steps],
        }

    def handle(self, button_data: dict) -> dict:
        """버튼 입력 → build_response 반환."""
        action = button_data.get("action", "")
        if action == "cancel":
            return self._cancel()
        if action == "back":
            return self._prev()

        value = button_data.get("value", "")
        if value:
            return self._select(value)

        if action == "execute":
            return self._execute()

        return build_error_response("알 수 없는 입력입니다.")

    def _select(self, value: str) -> dict:
        """스텝 타입에 따라 selection 저장 + 다음 스텝."""
        step = self.current_step
        step_type = step.type

        # 스텝 타입별 selection key
        SELECTION_MAP = {
            "select_master": ("master_cms_id", "master_"),
            "select_page": ("page_id", "page_"),
            "select_product": ("product_id", "product_"),
        }

        if step_type in SELECTION_MAP:
            key, prefix = SELECTION_MAP[step_type]
            self.selections[key] = value.replace(prefix, "")
            name_key = f"_{step_type}_names"
            self.selections[key.replace("_id", "_name").replace("_cms_id", "_name")] = \
                self.selections.get(name_key, {}).get(value, value)

        return self._next()

    def _next(self) -> dict:
        """다음 스텝으로 이동 + 해당 스텝 실행."""
        self.current_step_index += 1
        if self.current_step_index >= len(self.schema.steps):
            return self._execute()
        return self._run_current_step()

    def _prev(self) -> dict:
        """이전 스텝으로."""
        if self.current_step_index <= 0:
            return self._cancel()
        self.current_step_index -= 1
        return self._run_current_step()

    def _run_current_step(self) -> dict:
        """현재 스텝 타입에 따라 실행."""
        step = self.current_step
        runner = STEP_RUNNERS.get(step.type)
        if not runner:
            return build_error_response(f"알 수 없는 스텝: {step.type}")
        return runner(self, step)
```

### 스텝 러너

```python
STEP_RUNNERS = {
    "select_master": run_select_master,
    "select_page": run_select_page,
    "select_product": run_select_product,
    "confirm": run_confirm,
    "execute": run_execute,
}

def run_select_master(state: WizardState, step: StepDefinition) -> dict:
    """클럽 선택 스텝 — API 호출 + 버튼 생성."""
    masters = search_masters(search_keyword="")
    # ... 필터링, 버튼 생성 ...
    return build_response(
        message=step.message.format(**state.selections),
        buttons=buttons,
        mode="wizard",
        step=state.get_step_progress(),
    )

def run_execute(state: WizardState, step: StepDefinition) -> dict:
    """실행 스텝 — handler 또는 api 호출."""
    if step.handler:
        # 커스텀 핸들러 (launch_check 등)
        handler_fn = CUSTOM_HANDLERS[step.handler]
        return handler_fn(state, step)

    # 일반 API 호출
    api_fn = API_MAP[step.api]
    params = {k: v.format(**state.selections) for k, v in step.params.items()}
    result = api_fn(**params)

    state.reset()
    return build_response(
        message=step.done_message.format(**state.selections),
        buttons=step.done_buttons,
        mode="done",
    )
```

---

## 4. 커스텀 핸들러

복잡한 로직(launch_check, diagnose)은 커스텀 핸들러로 분리:

```python
# wizards/handlers.py

CUSTOM_HANDLERS = {
    "launch_check": handle_launch_check,
    "diagnose": handle_diagnose,
}

def handle_launch_check(state: WizardState, step: StepDefinition) -> dict:
    """기존 _execute_launch_check 로직을 그대로 이식."""
    from src.agents.validator import diagnose_visibility
    master_cms_id = state.selections.get("master_cms_id", "")
    master_name = state.selections.get("master_name", "")
    state.reset()

    result = diagnose_visibility(master_cms_id or master_name)
    # ... 기존 렌더링 로직 ...
    return build_response(msg, buttons, "launch_check")
```

---

## 5. 새 위저드 추가 절차

**변경 전:**
1. wizard.py WIZARD_ACTIONS에 등록
2. _next_after_master()에 elif
3. _handle_select()에 elif
4. _call_api()에 elif
5. (선택) _prev_step()에 elif
6. 프론트 수정

**변경 후:**
1. `wizards/새_위저드.yaml` 파일 작성 — **끝**

프론트 변경 0 (스텝 블록 타입이 이미 정의되어 있으므로).
서버 재시작하면 자동 로드.

복잡한 실행 로직이 필요하면:
1. YAML에 `handler: 핸들러명` 지정
2. `wizards/handlers.py`에 핸들러 함수 추가

---

## 6. API 매핑 테이블

YAML의 `api` 필드가 참조하는 함수 매핑:

```python
# wizards/api_map.py

API_MAP = {
    "update_product_page_status": update_product_page_status,
    "update_product_display": update_product_display,
    "update_product_page": update_product_page,
    "update_main_product_setting": update_main_product_setting,
    "batch_update_product_display": batch_update_product_display,
}
```

새 API 추가 시 여기에 등록하면 YAML에서 참조 가능.

---

## 7. 메시지 템플릿 변수

YAML 메시지에서 `{변수명}`으로 selections 값을 참조:

| 변수 | 출처 | 예시 |
|------|------|------|
| `{master_name}` | select_master 결과 | "조조형우" |
| `{page_title}` | select_page 결과 | "월간 투자 리포트" |
| `{product_name}` | select_product 결과 | "월간 구독 29,900원" |
| `{page_id}` | select_page 결과 | "148" |
| `{product_id}` | select_product 결과 | "256" |
| `{target}` | 자동 생성 | "조조형우 > 월간 투자 리포트" |

---

## 8. 디렉토리 구조

```
us-product-agent/
├── wizards/                    # 위저드 YAML 스키마
│   ├── launch_check.yaml
│   ├── product_page_inactive.yaml
│   ├── product_page_active.yaml
│   ├── product_hide.yaml
│   ├── product_show.yaml
│   ├── hidden.yaml
│   ├── handlers.py             # 커스텀 핸들러
│   └── api_map.py              # API 함수 매핑
├── src/
│   └── wizard.py               # WizardEngine + WizardState (범용)
```

---

## 9. 구현 순서

| # | 작업 | 파일 | 의존 |
|---|------|------|------|
| 1 | WizardSchema 데이터 클래스 | `src/wizard.py` | - |
| 2 | YAML 로더 | `src/wizard.py` | #1 |
| 3 | WizardEngine + WizardState 리팩토링 | `src/wizard.py` | #2, Phase 2 build_response |
| 4 | 스텝 러너 구현 (5종) | `src/wizard.py` | #3 |
| 5 | launch_check YAML + 커스텀 핸들러 | `wizards/` | #3, #4 |
| 6 | 기존 위저드 YAML 변환 (6종) | `wizards/` | #4 |
| 7 | server.py WizardEngine 연동 | `server.py` | #3 |
| 8 | GET /wizard/actions를 engine에서 조회 | `server.py` | #3 |
| 9 | 테스트 | `tests/` | #7 |
