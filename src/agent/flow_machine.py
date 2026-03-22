"""
사전조건 체인 기반 스테이트머신.

LLM이 의도+엔티티를 추출 → 라우터가 목표 상태 결정 →
사전조건을 역추적하며 빠진 단계부터 실행.
"""

from __future__ import annotations

import json
import boto3
from dataclasses import dataclass, field

from src.tools.admin_api import _client, _safe_request

# ── LLM 대화 관리자 ──
_bedrock = boto3.client("bedrock-runtime", region_name="us-west-2")
_MODEL = "us.anthropic.claude-haiku-4-5-20251001-v1:0"

MANAGER_PROMPT = """당신은 어스플러스 관리자센터 상품 세팅 AI 어시스턴트입니다.
운영매니저의 요청을 이해하고, 적절한 액션을 결정합니다.

## 데이터 구조 (1:N 관계)
```
마스터(오피셜클럽) 1개
  └─ 시리즈 N개 (파트너센터에서 생성)
  └─ 상품 페이지 N개 (각각 독립적인 결제 접점)
       └─ 상품 옵션 N개 (실제 구매 단위)
```
- 마스터 1명이 상품 페이지를 여러 개 가질 수 있음
- 상품 페이지 1개에 상품 옵션을 여러 개 등록 가능
- "상품 옵션 추가" 시 반드시 **어떤 상품 페이지**에 추가할지 특정해야 함

## 도메인 지식
- **마스터(오피셜클럽)**: 콘텐츠 크리에이터의 멤버십 공간. 공개/비공개/준비중 상태.
- **시리즈**: 마스터의 콘텐츠 묶음. 파트너센터에서 생성. 상품 옵션 연결 시 필수.
- **상품 페이지**: 고객이 보는 결제 페이지. 공개/비공개 상태. 이미지, 공개 기간, 신청 기간 포함.
  - 구독상품: 정해진 주기(1/3/6/12개월)마다 정기 결제
  - 단건상품: 한 번만 결제, 상품 변경 불가
- **상품 옵션**: 실제 구매 단위. 상품명, 금액, 결제주기, 시리즈 연결, 프로모션 설정.
  - 프로모션: 상시 할인 / 구독 회차 한정 할인(1~9회차). 최초 구매 시에만 적용.
- **활성화**: 상품 노출 ON → 순서 설정 → 페이지 공개 → 메인 상품 설정 (4단계)
- **메인 상품 페이지**: 어스플러스 구독 탭/오피셜클럽 홈에서 연결되는 대표 상품 페이지
- **선행 조건**: 오피셜클럽 → 시리즈 → 상품 페이지 → 상품 옵션 (순서 필수, 건너뛰기 불가)

## 관리자센터 페이지 구조
- 상품 페이지 목록: /product (마스터별 필터링)
- 상품 페이지 생성: /product/page/create (정보+이미지 한번에)
- 상품 페이지 상세: /product/page/{id}?tab=settings|options|letters|caution
- 상품 옵션 등록: /product/create?productPageId={id}&productType={type}&masterId={cmsId}
- 상품 옵션 수정: /product/{productId}?productPageId={id}&productType={type}&masterId={cmsId}
- 오피셜클럽 관리: /official-club
- 마스터 페이지 관리: /master/page (공개/준비중 순서)
- 메인 상품 페이지 관리: /product/page/list

## 사용 가능한 액션
- search_master: 마스터 정보만 확인 (params: master_name)
- list_masters: 전체 마스터 목록
- check_series: 시리즈 확인 (params: master_name)
- list_pages: 상품 페이지 목록 조회 (params: master_name, filter: all/active/inactive)
- list_options: 특정 페이지의 상품 옵션 목록 (params: master_name, page_code)
- setup: 상품 전체 세팅 (페이지+옵션+활성화) (params: master_name, product_type)
- create_option: 기존 페이지에 옵션 추가 (params: master_name, page_code) ← "옵션 추가/등록" 요청 시
- activate: 활성화 실행 (params: master_name)
- diagnose: 노출 문제 진단 (params: master_name)
- edit: 수정 안내 (params: master_name, target: page/option)
- go_back: 이전 단계로 (params: target: master/page)
- confirm: 유저가 작업 완료 알림
- chat: 액션 없이 대화만

⚠️ 액션 선택 가이드:
- "상품 만들래/세팅해줘" → setup (전체 프로세스)
- "옵션 추가/등록해줘" → create_option (기존 페이지에 추가)
- "마스터 있어?/검색해줘" → search_master (정보 확인만)
- "상품페이지 뭐있어?" → list_pages (목록 조회)

## 응답 형식
반드시 JSON만 출력:
{"action": "...", "params": {...}, "message": "유저에게 보여줄 안내 메시지"}

message: 유저에게 자연스럽게 안내하는 텍스트. 마크다운 사용 가능.
action이 "chat"이면 message에 대화 응답을 넣으세요."""


def _llm_understand(message: str, history: list[dict], context_summary: str) -> dict:
    """LLM이 대화를 이해하고 액션을 결정."""
    try:
        system_text = MANAGER_PROMPT
        if context_summary:
            system_text += f"\n\n## 현재 상태\n{context_summary}"

        # 대화 히스토리를 Bedrock messages 형식으로
        messages = []
        for h in history[-6:]:  # 최근 6턴만
            messages.append({
                "role": h["role"],
                "content": [{"text": h["content"][:500]}],
            })
        messages.append({"role": "user", "content": [{"text": message}]})

        response = _bedrock.converse(
            modelId=_MODEL,
            messages=messages,
            system=[{"text": system_text}],
            inferenceConfig={"maxTokens": 300, "temperature": 0},
        )
        text = response["output"]["message"]["content"][0]["text"].strip()
        if "```" in text:
            text = text.split("```")[1].replace("json", "").strip()
        return json.loads(text)
    except Exception as e:
        print(f"⚠️ LLM 이해 실패: {e}")
        return {"action": "chat", "params": {}, "message": "죄송합니다. 다시 말씀해주세요."}


def _llm_format(results: dict, context_summary: str) -> str:
    """LLM이 실행 결과를 자연어로 포맷."""
    try:
        response = _bedrock.converse(
            modelId=_MODEL,
            messages=[{"role": "user", "content": [{"text": json.dumps(results, ensure_ascii=False)}]}],
            system=[{"text": f"API 실행 결과를 운영매니저에게 자연스럽게 안내하세요. 마크다운 사용. 간결하게.\n\n현재 상태:\n{context_summary}"}],
            inferenceConfig={"maxTokens": 500, "temperature": 0},
        )
        return response["output"]["message"]["content"][0]["text"].strip()
    except Exception as e:
        print(f"⚠️ LLM 포맷 실패: {e}")
        return json.dumps(results, ensure_ascii=False, indent=2)

STEPS = ["마스터 확인", "시리즈 확인", "상품 페이지 생성", "상품 옵션 등록", "활성화", "검증"]

# ── 사전조건 체인 정의 ──
# 각 상태가 필요로 하는 데이터 키
PREREQUISITES = {
    "check_master": [],                          # 시작점
    "check_series": ["master_cms_id"],
    "guide_create_page": ["master_cms_id", "series_ids"],
    "guide_create_option": ["master_cms_id", "series_ids", "product_page_id"],
    "confirm_activate": ["master_cms_id", "product_page_id", "product_ids"],
    "verification": ["master_cms_id", "product_page_id"],
}

# 상태 → 스텝 번호
STATE_TO_STEP = {
    "check_master": 1,
    "check_series": 2,
    "guide_create_page": 3,
    "guide_create_option": 4,
    "confirm_activate": 5,
    "verification": 6,
}

# 의도 → 목표 상태
INTENT_TO_TARGET = {
    "setup": "guide_create_page",
    "create_page": "guide_create_page",
    "create_option": "guide_create_option",
    "activate": "confirm_activate",
    "verify": "verification",
    "query_master": "check_master",
    "query_series": "check_series",
    "diagnose": "diagnose",
}


@dataclass
class Response:
    message: str
    buttons: list[dict] = field(default_factory=list)
    mode: str = "guide"
    step: dict | None = None
    need_llm: bool = False


@dataclass
class ParsedIntent:
    intent: str = "chat"
    master_name: str = ""
    product_type: str = ""  # "SUBSCRIPTION" | "ONE_TIME_PURCHASE" | ""
    extra: str = ""


_STATUS_LABELS = {
    "ACTIVE": "공개", "INACTIVE": "비공개",
    "PUBLIC": "공개", "PRIVATE": "비공개", "PENDING": "준비중",
}


def _status_label(raw: str) -> str:
    return _STATUS_LABELS.get(raw, raw)


def _step_meta(state: str) -> dict:
    num = STATE_TO_STEP.get(state, 1)
    return {"current": num, "total": 6, "label": STEPS[num - 1], "steps": STEPS}


def _api_get(path: str, params: dict | None = None):
    with _client() as c:
        r = c.get(path, params=params or {})
        return _safe_request(r)


def _api_patch(path: str, body: dict):
    with _client() as c:
        r = c.patch(path, json=body)
        return _safe_request(r)


import os
import pathlib

_STATE_DIR = pathlib.Path(os.environ.get("FLOW_STATE_DIR", "/tmp/flow_states"))


class FlowMachine:
    def __init__(self, session_id: str = "default"):
        self.session_id = session_id
        self.state = "idle"
        self.data: dict = {}
        self._pending_target: str | None = None
        self._history: list[dict] = []  # 대화 히스토리
        self._load_state()

    def reset(self):
        self.state = "idle"
        self.data = {}
        self._pending_target = None
        self._history = []
        self._save_state()

    def _state_file(self) -> pathlib.Path:
        _STATE_DIR.mkdir(parents=True, exist_ok=True)
        return _STATE_DIR / f"{self.session_id}.json"

    def _save_state(self):
        """현재 상태를 파일에 저장."""
        try:
            payload = {
                "state": self.state,
                "data": {k: v for k, v in self.data.items() if not k.startswith("_")},
                "pending_target": self._pending_target,
            }
            self._state_file().write_text(json.dumps(payload, ensure_ascii=False))
        except Exception as e:
            print(f"⚠️ 상태 저장 실패: {e}")

    def _load_state(self):
        """파일에서 상태 복구."""
        try:
            f = self._state_file()
            if f.exists():
                payload = json.loads(f.read_text())
                self.state = payload.get("state", "idle")
                self.data = payload.get("data", {})
                self._pending_target = payload.get("pending_target")
                print(f"🔄 상태 복구: state={self.state}, data keys={list(self.data.keys())}")
        except Exception as e:
            print(f"⚠️ 상태 복구 실패: {e}")

    # ══════════════════════════════════════
    # 메인 핸들러
    # ══════════════════════════════════════

    def handle(self, message: str, context: dict | None = None) -> Response:
        msg = message.strip()
        print(f"📍 state={self.state}, msg={msg[:40]}")

        try:
            # ── Phase 1: LLM이 대화를 이해하고 액션 결정 ──
            context_summary = self._build_context_summary()
            understood = _llm_understand(msg, self._history, context_summary)
            action = understood.get("action", "chat")
            params = understood.get("params", {})
            llm_message = understood.get("message", "")
            print(f"📍 LLM 결정: action={action}, params={params}")

            # 대화 기록
            self._history.append({"role": "user", "content": msg})

            # ── Phase 2: 엔티티 저장 + 마스터 변경 감지 ──
            new_master = params.get("master_name", "")
            if new_master and new_master != self.data.get("master_name", ""):
                # 다른 마스터 → 관련 데이터 초기화
                print(f"📍 마스터 변경 감지: {self.data.get('master_name', '')} → {new_master}")
                for key in ["master_cms_id", "master_name", "master_id", "master_public_type",
                            "series_ids", "series_titles", "product_page_id", "product_page_code",
                            "product_page_title", "_all_pages", "product_ids", "_page_choices"]:
                    self.data.pop(key, None)
                self.data["_requested_master"] = new_master
            elif new_master:
                self.data["_requested_master"] = new_master
            if params.get("product_type"):
                self.data["product_type"] = params["product_type"]
            # page_code → product_page_id 변환
            if params.get("page_code") and not self.data.get("product_page_id"):
                self._resolve_page_code(params["page_code"])

            # ── Phase 3: 액션 라우팅 → 스테이트머신 실행 ──
            result = self._route_action(action, params, llm_message)

            # ── Phase 4: 결과를 LLM이 포맷 (코드 텍스트 대신) ──
            if result.message.startswith("__RAW__:"):
                raw_data = result.message[8:]
                result.message = _llm_format(
                    {"action": action, "data": raw_data, "buttons_count": len(result.buttons)},
                    context_summary,
                )

            # 대화 기록
            self._history.append({"role": "assistant", "content": result.message[:500]})

            return result
        finally:
            self._save_state()

    def _route_action(self, action: str, params: dict, llm_message: str) -> Response:
        """액션을 스테이트머신으로 라우팅."""
        # ── 대기 상태에서 confirm 처리 ──
        if action == "confirm" and self.state.startswith("wait_"):
            return self._handle_wait("완료했어")

        # ── 직접 실행 액션 (조회류) ──
        if action == "list_masters":
            return self._action_list_masters()
        if action == "search_master":
            return self._action_search_master(params.get("master_name", ""))
        if action == "list_pages":
            return self._action_list_pages(params)
        if action == "list_options":
            return self._action_list_options(params)
        if action == "check_series":
            self.data["_requested_master"] = params.get("master_name", self.data.get("_requested_master", ""))
            return self._resolve_prerequisites("check_series")

        # ── 스테이트머신 플로우 액션 ──
        if action == "diagnose":
            return self._exec_diagnose(llm_message)
        if action == "edit":
            return self._handle_edit_request(llm_message)
        if action == "go_back":
            return self._handle_go_back(ParsedIntent("go_back", params.get("master_name", ""), "", params.get("target", "")))
        if action in ("setup", "create_option", "activate", "verify"):
            target = INTENT_TO_TARGET.get(action, "guide_create_page")
            return self._resolve_prerequisites(target)

        # ── 대기 상태에서 비-chat 액션 ──
        if self.state.startswith("wait_") and action != "chat":
            return self._handle_wait(llm_message or action)

        # ── chat: LLM 메시지 그대로 사용 ──
        buttons = self._buttons_for_state(self.state) if self.state != "idle" else []
        step = _step_meta(self.state) if self.state in STATE_TO_STEP else None
        return Response(message=llm_message, buttons=buttons, step=step, mode="guide" if self.state != "idle" else "idle")

    # ── 조회 액션 구현 ──

    def _resolve_page_code(self, page_code: str):
        """page_code로 product_page_id를 찾아서 data에 저장."""
        cms_id = self.data.get("master_cms_id", "")
        if not cms_id:
            return
        pages = _api_get("/v1/product-group", {"masterId": cms_id})
        if isinstance(pages, list):
            for p in pages:
                if str(p.get("code", "")) == str(page_code) or p.get("title", "") == page_code:
                    self.data["product_page_id"] = p.get("id", "")
                    self.data["product_page_code"] = p.get("code", "")
                    self.data["product_page_title"] = p.get("title", "")
                    print(f"📍 page_code {page_code} → id={self.data['product_page_id']}")
                    return
            # 부분 매칭 시도
            for p in pages:
                if page_code in p.get("title", ""):
                    self.data["product_page_id"] = p.get("id", "")
                    self.data["product_page_code"] = p.get("code", "")
                    self.data["product_page_title"] = p.get("title", "")
                    print(f"📍 page_code 부분매칭 {page_code} → {self.data['product_page_title']}")
                    return

    def _action_list_masters(self) -> Response:
        result = _api_get("/v1/masters")
        if isinstance(result, list) and len(result) > 0:
            rows = "\n".join(f"- **{m.get('name', '')}** ({_status_label(m.get('publicType', ''))}, cmsId: {m.get('cmsId', '')})" for m in result)
            return Response(message=f"등록된 마스터 **{len(result)}개**:\n{rows}", step=_step_meta("check_master"))
        return Response(message="등록된 마스터가 없습니다.")

    def _action_search_master(self, name: str) -> Response:
        if not name:
            return self._action_list_masters()
        self.data["_requested_master"] = name
        return self._exec_check_master()

    def _action_list_pages(self, params: dict) -> Response:
        master_name = params.get("master_name", self.data.get("master_name", ""))
        if not self.data.get("master_cms_id"):
            if master_name:
                self.data["_requested_master"] = master_name
                self._exec_check_master()  # 마스터 먼저 찾기
            if not self.data.get("master_cms_id"):
                return Response(message="마스터를 먼저 알려주세요.")

        cms_id = self.data["master_cms_id"]
        pages = _api_get("/v1/product-group", {"masterId": cms_id})
        if not isinstance(pages, list) or len(pages) == 0:
            return Response(message=f"**{self.data.get('master_name', '')}** 마스터에 상품 페이지가 없습니다.")

        filter_type = params.get("filter", "all")
        if filter_type == "active":
            pages = [p for p in pages if p.get("status") == "ACTIVE"]
        elif filter_type == "inactive":
            pages = [p for p in pages if p.get("status") != "ACTIVE"]

        label = {"all": "전체", "active": "공개 중인", "inactive": "비공개"}.get(filter_type, "")
        rows = "\n".join(f"- **{p.get('title', '')}** (코드: {p.get('code', '')}, {_status_label(p.get('status', ''))})" for p in pages)
        return Response(
            message=f"**{self.data.get('master_name', '')}** {label} 상품 페이지 **{len(pages)}개**:\n{rows}",
            step=_step_meta("guide_create_page"),
        )

    def _action_list_options(self, params: dict) -> Response:
        page_code = params.get("page_code", "")
        # 페이지 ID 찾기
        page_id = self.data.get("product_page_id", "")
        if page_code and not page_id:
            cms_id = self.data.get("master_cms_id", "")
            if cms_id:
                pages = _api_get("/v1/product-group", {"masterId": cms_id})
                if isinstance(pages, list):
                    match = [p for p in pages if str(p.get("code", "")) == str(page_code)]
                    if match:
                        page_id = match[0].get("id", "")
        if not page_id:
            return Response(message="상품 페이지를 먼저 선택해주세요.")

        products = _api_get(f"/v1/product/group/{page_id}")
        if not isinstance(products, list) or len(products) == 0:
            return Response(message="등록된 상품 옵션이 없습니다.")

        rows = "\n".join(
            f"- **{p.get('name', '')}** ({p.get('originPrice', 0):,}원, {'공개' if p.get('isDisplay') else '비공개'})"
            for p in products
        )
        return Response(
            message=f"상품 옵션 **{len(products)}개**:\n{rows}",
            step=_step_meta("guide_create_option"),
        )

    # ══════════════════════════════════════
    # 사전조건 역추적
    # ══════════════════════════════════════

    def _resolve_prerequisites(self, target: str, _depth: int = 0) -> Response:
        """target 상태에 필요한 사전조건을 역추적, 빠진 것부터 실행."""
        if _depth > 6:
            print(f"⚠️ prerequisite 재귀 깊이 초과 → 중단")
            return Response(message="처리 중 오류가 발생했습니다. 다시 시도해주세요.", mode="idle")

        self._pending_target = target
        required = PREREQUISITES.get(target, [])

        for key in required:
            val = self.data.get(key)
            # 없거나 빈 리스트면 "없음"
            if val is None or val == "" or val == []:
                filler = self._find_filler_state(key)
                # 이미 같은 상태를 실행 중이면 → 사전조건 충족 불가 (wait 상태로)
                if filler == self.state:
                    print(f"⚠️ {key} 충족 불가 (같은 상태 반복) → 대기")
                    self._pending_target = target
                    return self._execute_state(filler)
                print(f"📍 prerequisite missing: {key} → run {filler}")
                return self._execute_state(filler)

        # 모든 사전조건 충족 → 목표 상태 실행
        self._pending_target = None
        print(f"📍 prerequisites met → execute {target}")
        return self._execute_state(target)

    def _find_filler_state(self, missing_key: str) -> str:
        """빠진 데이터 키를 채울 수 있는 상태를 반환."""
        key_to_state = {
            "master_cms_id": "check_master",
            "series_ids": "check_series",
            "product_page_id": "guide_create_page",
            "product_ids": "guide_create_option",
        }
        return key_to_state.get(missing_key, "check_master")

    # ══════════════════════════════════════
    # 상태별 실행
    # ══════════════════════════════════════

    def _execute_state(self, state: str) -> Response:
        self.state = state
        executor = {
            "check_master": self._exec_check_master,
            "check_series": self._exec_check_series,
            "guide_create_page": self._exec_guide_create_page,
            "guide_create_option": self._exec_guide_create_option,
            "confirm_activate": self._exec_confirm_activate,
            "verification": self._exec_verification,
        }
        fn = executor.get(state)
        if fn:
            return fn()
        return Response(message="알 수 없는 상태입니다.", mode="idle")

    # ── check_master ──

    def _exec_check_master(self) -> Response:
        name = self.data.get("_requested_master", "")
        if not name:
            self.state = "idle"
            return Response(
                message="어떤 마스터(오피셜클럽)에 상품 페이지를 만드시겠어요?",
                buttons=[{"type": "navigate", "label": "📋 마스터 목록 보기", "url": "/official-club", "variant": "secondary", "description": "등록된 마스터 목록을 확인합니다."}],
                step=_step_meta("check_master"),
            )

        print(f"🔍 search_master: '{name}'")
        result = _api_get("/v1/masters", {"searchKeyword": name, "searchCategory": "NAME"})
        print(f"🔍 결과: {str(result)[:200]}")

        if isinstance(result, dict) and result.get("error"):
            return Response(
                message=f"API 오류: {result.get('guide', '')}",
                buttons=[{"type": "navigate", "label": "📋 마스터 목록 보기", "url": "/official-club", "variant": "secondary", "description": "직접 확인해보세요."}],
                step=_step_meta("check_master"),
            )

        if isinstance(result, list) and len(result) > 0:
            exact = [m for m in result if m.get("name") == name]
            master = exact[0] if exact else result[0]
            self.data["master_cms_id"] = master.get("cmsId", "")
            self.data["master_name"] = master.get("name", "")
            self.data["master_id"] = master.get("id", "")
            self.data["master_public_type"] = master.get("publicType", "")

            # 사전조건 충족 → 다음 빠진 것 계속 resolve
            if self._pending_target:
                return self._resolve_prerequisites(self._pending_target, _depth=1)

            return Response(
                message=f"✅ **{self.data['master_name']}** 마스터 확인 (상태: {_status_label(self.data['master_public_type'])})",
                step=_step_meta("check_master"),
            )

        # 전체 목록에서 찾기 시도
        all_result = _api_get("/v1/masters")
        if isinstance(all_result, list):
            fuzzy = [m for m in all_result if name in m.get("name", "")]
            if fuzzy:
                master = fuzzy[0]
                self.data["master_cms_id"] = master.get("cmsId", "")
                self.data["master_name"] = master.get("name", "")
                self.data["master_id"] = master.get("id", "")
                self.data["master_public_type"] = master.get("publicType", "")
                if self._pending_target:
                    return self._resolve_prerequisites(self._pending_target)
                return Response(
                    message=f"✅ **{self.data['master_name']}** 마스터 확인 (상태: {_status_label(self.data['master_public_type'])})",
                    step=_step_meta("check_master"),
                )

        return Response(
            message=f"'{name}' 마스터를 찾을 수 없습니다.\n\n다른 이름으로 시도하거나, 새로 만들어주세요.",
            buttons=[
                {"type": "navigate", "label": "📋 마스터 목록 보기", "url": "/official-club", "variant": "secondary", "description": "등록된 마스터 목록을 확인합니다."},
                {"type": "navigate", "label": "➕ 새 마스터 생성", "url": "/official-club/create", "variant": "primary", "description": "새 오피셜클럽을 생성합니다."},
            ],
            step=_step_meta("check_master"),
        )

    # ── check_series ──

    def _exec_check_series(self) -> Response:
        cms_id = self.data.get("master_cms_id", "")
        master_name = self.data.get("master_name", "")
        result = _api_get("/with-series", {"masterId": cms_id, "seriesState": "PUBLISHED"})

        series_list = []
        if isinstance(result, dict):
            masters = result.get("masters", [])
            if masters and masters[0].get("series"):
                series_list = masters[0]["series"]
                self.data["series_ids"] = [s["_id"] for s in series_list]
                self.data["series_titles"] = [s.get("title", "") for s in series_list]

        if series_list:
            series_text = "\n".join(f"  - {s.get('title', '무제')}" for s in series_list)

            # 사전조건 충족 → 계속 resolve
            if self._pending_target:
                # 기존 상품 페이지도 체크
                self._check_existing_page()
                return self._resolve_prerequisites(self._pending_target, _depth=2)

            return Response(
                message=f"✅ **{master_name}** 시리즈 {len(series_list)}개 확인\n{series_text}",
                step=_step_meta("check_series"),
            )

        # 시리즈 없음
        self.state = "wait_series"
        return Response(
            message=f"✅ **{master_name}** 마스터 확인\n❌ 시리즈가 없습니다. 상품 옵션에 시리즈가 필수이므로 먼저 생성해주세요.",
            buttons=[
                {"type": "navigate", "label": "📝 파트너센터에서 시리즈 생성", "url": "/partner", "variant": "primary", "description": "좌측 앱 전환 아이콘에서 '파트너'를 클릭해주세요."},
                {"type": "confirm", "label": "✅ 시리즈 생성 완료", "variant": "primary", "description": "시리즈 생성을 완료했으면 눌러주세요. 시리즈를 재확인합니다."},
            ],
            step=_step_meta("check_series"),
        )

    def _check_existing_page(self):
        """기존 상품 페이지가 있는지 확인하고 데이터에 저장."""
        cms_id = self.data.get("master_cms_id", "")
        if not cms_id:
            return
        print(f"🔍 check_existing_page: cmsId={cms_id}")
        pages = _api_get("/v1/product-group", {"masterId": cms_id})
        if isinstance(pages, list) and len(pages) > 0:
            self.data["_all_pages"] = pages
            # 1개면 자동 선택, 여러 개면 나중에 선택하게
            if len(pages) == 1:
                self.data["product_page_id"] = pages[0].get("id", "")
                self.data["product_page_code"] = pages[0].get("code", "")
                self.data["product_page_title"] = pages[0].get("title", "")

    # ── guide_create_page ──

    def _exec_guide_create_page(self) -> Response:
        master_name = self.data.get("master_name", "")
        series_count = len(self.data.get("series_ids", []))
        series_text = ", ".join(self.data.get("series_titles", []))

        # 기존 페이지 확인
        all_pages = self.data.get("_all_pages", [])
        cms_id = self.data.get("master_cms_id", "")

        if all_pages and "product_page_id" not in self.data:
            # 여러 페이지 → 목록 보여주고 선택하게
            status_label = {"ACTIVE": "공개", "INACTIVE": "비공개"}
            rows = "\n".join(
                f"- **{p.get('title', '')}** (코드: {p.get('code', '')}, {status_label.get(p.get('status', ''), p.get('status', ''))})"
                for p in all_pages
            )
            self.state = "wait_select_page"
            self.data["_page_choices"] = {str(p.get("code", "")): p for p in all_pages}
            return Response(
                message=f"✅ **{master_name}** 마스터 확인\n✅ 시리즈 {series_count}개: {series_text}\n\n기존 상품 페이지 **{len(all_pages)}개**:\n{rows}\n\n코드 번호를 알려주시면 해당 페이지에 옵션을 등록합니다.",
                buttons=[
                    {"type": "navigate", "label": "📄 새 상품 페이지 생성", "url": "/product/page/create", "variant": "secondary", "description": "새 페이지를 만듭니다."},
                ],
                step=_step_meta("guide_create_page"),
            )

        if "product_page_id" in self.data:
            title = self.data.get("product_page_title", "")
            code = self.data.get("product_page_code", "")
            page_id = self.data.get("product_page_id", "")

            self.state = "wait_create_option"
            return Response(
                message=f"✅ **{master_name}** 마스터 확인\n✅ 시리즈 {series_count}개: {series_text}\n✅ 상품 페이지: **{title}** (코드: {code})\n\n이 페이지에 상품 옵션을 등록하시겠어요?",
                buttons=[
                    {"type": "navigate", "label": "📦 상품 옵션 등록하러 가기", "url": f"/product/create?productPageId={page_id}&productType={self.data.get('product_type', 'SUBSCRIPTION')}&masterId={cms_id}", "variant": "primary", "description": f"'{title}' 페이지에 옵션을 추가합니다."},
                    {"type": "confirm", "label": "✅ 상품 옵션 등록 완료", "variant": "primary", "description": "옵션 등록을 완료했으면 눌러주세요."},
                    {"type": "navigate", "label": "📄 새 상품 페이지 생성", "url": "/product/page/create", "variant": "secondary", "description": "기존 페이지 대신 새 페이지를 만듭니다."},
                ],
                step=_step_meta("guide_create_page"),
            )

        self.state = "wait_create_page"
        return Response(
            message=f"✅ **{master_name}** 마스터 확인\n✅ 시리즈 {series_count}개: {series_text}\n\n사전 조건 충족! 상품 페이지를 생성해주세요.",
            buttons=[
                {"type": "navigate", "label": "📄 상품 페이지 생성하러 가기", "url": "/product/page/create", "variant": "primary", "description": f"관리자센터에서 직접 생성합니다. 마스터에서 '{master_name}'을 선택하고, 정보 설정과 이미지까지 등록해주세요."},
                {"type": "confirm", "label": "✅ 상품 페이지 생성 완료", "variant": "primary", "description": "생성을 완료했으면 눌러주세요. 결과를 확인합니다."},
            ],
            step=_step_meta("guide_create_page"),
        )

    # ── guide_create_option ──

    def _exec_guide_create_option(self) -> Response:
        page_id = self.data.get("product_page_id", "")
        master_id = self.data.get("master_cms_id", "")
        master_name = self.data.get("master_name", "")
        page_title = self.data.get("product_page_title", "")

        # 기존 옵션 확인
        existing_text = ""
        products = _api_get(f"/v1/product/group/{page_id}")
        if isinstance(products, list) and len(products) > 0:
            self.data["product_ids"] = [str(p.get("id", "")) for p in products]
            existing_text = f"\n\n현재 등록된 옵션 **{len(products)}개**:\n" + "\n".join(
                f"- {p.get('name', '')} ({p.get('originPrice', 0):,}원, {'공개' if p.get('isDisplay') else '비공개'})"
                for p in products
            )

        product_type = self.data.get("product_type", "SUBSCRIPTION")
        type_label = "구독상품" if product_type == "SUBSCRIPTION" else "단건상품"

        self.state = "wait_create_option"
        return Response(
            message=f"**{master_name}** > **{page_title}** ({type_label}){existing_text}\n\n옵션을 추가하거나, 등록이 끝났으면 활성화로 넘어갈 수 있습니다.",
            buttons=[
                {"type": "navigate", "label": "📦 상품 옵션 등록하러 가기", "url": f"/product/create?productPageId={page_id}&productType={self.data.get('product_type', 'SUBSCRIPTION')}&masterId={master_id}", "variant": "primary", "description": "상품명, 금액, 결제주기, 시리즈를 입력해주세요."},
                {"type": "confirm", "label": "✅ 상품 옵션 등록 완료", "variant": "primary", "description": "옵션 등록을 완료했으면 눌러주세요. 등록된 옵션을 확인합니다."},
                {"type": "confirm", "label": "➕ 옵션 하나 더 등록", "variant": "secondary", "description": "추가 옵션을 등록합니다."},
            ],
            step=_step_meta("guide_create_option"),
        )

    # ── confirm_activate ──

    def _exec_confirm_activate(self) -> Response:
        page_id = self.data.get("product_page_id", "")
        products = _api_get(f"/v1/product/group/{page_id}")
        if isinstance(products, list) and len(products) > 0:
            self.data["product_ids"] = [str(p.get("id", "")) for p in products]
            options_text = "\n".join(f"  - {p.get('name', '')} ({p.get('originPrice', 0):,}원)" for p in products)
            return Response(
                message=f"✅ 상품 옵션 {len(products)}개 확인!\n{options_text}\n\n활성화하면 고객에게 노출됩니다.",
                buttons=[{"type": "action", "label": "🚀 활성화하기", "actionId": "activate", "variant": "primary", "description": "상품 노출, 순서, 페이지 공개, 메인 상품 설정을 한번에 처리합니다."}],
                step=_step_meta("confirm_activate"), mode="execute",
            )
        return Response(message="상품 옵션이 없습니다. 옵션을 먼저 등록해주세요.", step=_step_meta("guide_create_option"))

    # ── verification ──

    def _exec_verification(self) -> Response:
        page_id = self.data.get("product_page_id", "")
        page_code = self.data.get("product_page_code", "")
        checks = []

        page = _api_get(f"/v1/product-group/{page_id}")
        if isinstance(page, dict) and not page.get("error"):
            status = page.get("status", "UNKNOWN")
            sl = {"ACTIVE": "공개", "INACTIVE": "비공개"}
            checks.append(f"{'✅' if status == 'ACTIVE' else '❌'} 상품 페이지: {sl.get(status, status)}")

        products = _api_get(f"/v1/product/group/{page_id}")
        if isinstance(products, list):
            visible = [p for p in products if p.get("isDisplay")]
            checks.append(f"{'✅' if visible else '❌'} 노출 중인 옵션: {len(visible)}개")

        buttons = []
        if page_id:
            buttons.append({"type": "navigate", "label": "⚠️ 유의사항 등록", "url": f"/product/page/{page_id}?tab=caution", "variant": "secondary", "description": "유의사항을 등록합니다."})
        if page_code:
            buttons.append({"type": "navigate", "label": "🌐 고객 화면 확인", "url": f"https://dev.us-insight.com/products/group/{page_code}", "variant": "secondary", "description": "고객에게 보이는 화면을 확인합니다."})

        return Response(
            message=f"🎉 **검증 결과:**\n" + "\n".join(checks) + "\n\n**체크리스트:**\n☐ 금액/구성 확인\n☐ 프로모션 확인\n☐ 유의사항 등록\n☐ 마스터 공개 상태 확인",
            buttons=buttons, step=_step_meta("verification"), mode="execute",
        )

    # ══════════════════════════════════════
    # 대기 상태 처리
    # ══════════════════════════════════════

    def _handle_wait(self, msg: str) -> Response:
        """wait_* 상태에서 유저 입력 처리."""
        parsed = self._parse_intent(msg)

        # "수정" 요청 → 현재 맥락 유지하면서 해당 페이지로 안내
        if "수정" in msg or "편집" in msg or "바꿀" in msg or "변경" in msg:
            return self._handle_edit_request(msg)

        # 새로운 의도 감지 → 다른 마스터면 리셋, 같은 맥락이면 유지
        if parsed.intent not in ("chat", "confirm"):
            # 같은 마스터 관련이면 리셋하지 않음
            if parsed.master_name and parsed.master_name != self.data.get("master_name", ""):
                print(f"📍 다른 마스터 감지: {parsed.master_name} → 리셋")
                self.reset()
                self.data["_requested_master"] = parsed.master_name
                target = INTENT_TO_TARGET.get(parsed.intent, "guide_create_page")
                return self._resolve_prerequisites(target)
            # 마스터 없는 새 의도 → 현재 맥락에서 처리 시도
            if parsed.intent in ("create_option", "activate", "verify"):
                target = INTENT_TO_TARGET.get(parsed.intent, "guide_create_option")
                return self._resolve_prerequisites(target)

        if self.state == "wait_series":
            if "완료" in msg:
                return self._exec_check_series()
            return Response(
                message="시리즈 생성을 완료했으면 '완료' 버튼을 눌러주세요.",
                buttons=[
                    {"type": "navigate", "label": "📝 파트너센터에서 시리즈 생성", "url": "/partner", "variant": "primary", "description": "좌측 앱 전환 아이콘에서 '파트너'를 클릭해주세요."},
                    {"type": "confirm", "label": "✅ 시리즈 생성 완료", "variant": "primary", "description": "시리즈를 재확인합니다."},
                ],
                step=_step_meta("check_series"),
            )

        if self.state == "wait_select_page":
            # 유저가 페이지 코드를 입력하면 선택
            choices = self.data.get("_page_choices", {})
            # 숫자만 추출
            nums = "".join(c for c in msg if c.isdigit())
            if nums and nums in choices:
                page = choices[nums]
                self.data["product_page_id"] = page.get("id", "")
                self.data["product_page_code"] = page.get("code", "")
                self.data["product_page_title"] = page.get("title", "")
                self.state = "wait_create_option"
                return self._exec_guide_create_option()
            # 페이지명으로 매칭 시도
            for code, page in choices.items():
                if page.get("title", "") in msg:
                    self.data["product_page_id"] = page.get("id", "")
                    self.data["product_page_code"] = page.get("code", "")
                    self.data["product_page_title"] = page.get("title", "")
                    self.state = "wait_create_option"
                    return self._exec_guide_create_option()
            return Response(
                message="페이지 코드 번호를 입력해주세요.",
                buttons=self._buttons_for_state("wait_select_page"),
                step=_step_meta("guide_create_page"),
            )

        if self.state == "wait_create_page":
            if "완료" in msg:
                self._check_existing_page()
                if "product_page_id" in self.data:
                    page_title = self.data.get("product_page_title", "")
                    page_code = self.data.get("product_page_code", "")
                    if self._pending_target:
                        return self._resolve_prerequisites(self._pending_target)
                    self.state = "guide_create_option"
                    return Response(
                        message=f"✅ 상품 페이지 확인: {page_title} (코드: {page_code})\n\n상품 옵션을 등록해주세요.",
                        buttons=self._buttons_for_state("guide_create_option"),
                        step=_step_meta("guide_create_option"),
                    )
                master_name = self.data.get("master_name", "")
                return Response(
                    message="상품 페이지가 아직 확인되지 않습니다. 생성 후 다시 눌러주세요.",
                    buttons=[
                        {"type": "navigate", "label": "📄 상품 페이지 생성하러 가기", "url": "/product/page/create", "variant": "primary", "description": f"마스터에서 '{master_name}'을 선택해주세요."},
                        {"type": "confirm", "label": "✅ 상품 페이지 생성 완료", "variant": "primary", "description": "생성을 완료했으면 눌러주세요."},
                    ],
                    step=_step_meta("guide_create_page"),
                )

        if self.state == "wait_create_option":
            if "완료" in msg and "하나 더" not in msg:
                page_id = self.data.get("product_page_id", "")
                products = _api_get(f"/v1/product/group/{page_id}")
                if isinstance(products, list) and len(products) > 0:
                    self.data["product_ids"] = [str(p.get("id", "")) for p in products]
                    return self._exec_confirm_activate()
                return Response(message="상품 옵션이 아직 확인되지 않습니다.", buttons=self._buttons_for_state("guide_create_option"), step=_step_meta("guide_create_option"))
            if "하나 더" in msg or "추가" in msg:
                return self._exec_guide_create_option()
            if "activate" in msg or "활성화" in msg:
                return self._do_activate()

        # 사이드 질문 → LLM 위임 + 현재 상태 버튼 유지
        base_state = self.state.replace("wait_", "guide_create_").replace("wait_series", "check_series")
        return Response(
            message=msg, need_llm=True, mode="guide",
            step=_step_meta(base_state if base_state in STATE_TO_STEP else "check_master"),
            buttons=self._buttons_for_state(self.state),
        )

    # ══════════════════════════════════════
    # 진단 모드 (코드 기반 체크리스트)
    # ══════════════════════════════════════

    def _exec_diagnose(self, msg: str) -> Response:
        """진단: 코드로 체크리스트 순서대로 확인, LLM은 결과 요약만."""
        master_name = self.data.get("_requested_master") or self.data.get("master_name", "")
        if not master_name:
            return Response(
                message="어떤 마스터의 상품을 진단할까요? 마스터명을 알려주세요.",
                step=_step_meta("check_master"), mode="diagnose",
            )

        checks = []
        cms_id = self.data.get("master_cms_id", "")

        # 1. 마스터 존재/공개 상태
        if not cms_id:
            result = _api_get("/v1/masters", {"searchKeyword": master_name, "searchCategory": "NAME"})
            if isinstance(result, list) and len(result) > 0:
                master = result[0]
                cms_id = master.get("cmsId", "")
                self.data["master_cms_id"] = cms_id
                self.data["master_name"] = master.get("name", "")
                self.data["master_id"] = master.get("id", "")
                self.data["master_public_type"] = master.get("publicType", "")
            else:
                # 전체 검색 fallback
                all_result = _api_get("/v1/masters")
                if isinstance(all_result, list):
                    fuzzy = [m for m in all_result if master_name in m.get("name", "")]
                    if fuzzy:
                        master = fuzzy[0]
                        cms_id = master.get("cmsId", "")
                        self.data["master_cms_id"] = cms_id
                        self.data["master_name"] = master.get("name", "")
                        self.data["master_id"] = master.get("id", "")
                        self.data["master_public_type"] = master.get("publicType", "")

        if not cms_id:
            return Response(message=f"'{master_name}' 마스터를 찾을 수 없습니다.", mode="diagnose")

        public_type = self.data.get("master_public_type", "")
        is_public = public_type == "PUBLIC"
        checks.append(f"{'✅' if is_public else '❌'} 마스터 공개 상태: {_status_label(public_type)}")

        # 2. 메인 상품 페이지 활성화
        main_product = _api_get(f"/v1/masters/{cms_id}/main-product-group")
        main_active = False
        if isinstance(main_product, dict) and not main_product.get("error"):
            view_status = main_product.get("productGroupViewStatus", "")
            main_active = view_status == "ACTIVE"
            checks.append(f"{'✅' if main_active else '❌'} 메인 상품 페이지: {_status_label(view_status)}")
        else:
            checks.append("❌ 메인 상품 페이지: 설정 안 됨")

        # 3. 상품 페이지 공개 상태
        pages = _api_get("/v1/product-group", {"masterId": cms_id})
        page_active = False
        page_id = ""
        if isinstance(pages, list) and len(pages) > 0:
            active_pages = [p for p in pages if p.get("status") == "ACTIVE"]
            page_active = len(active_pages) > 0
            if active_pages:
                page_id = active_pages[0].get("id", "")
            checks.append(f"{'✅' if page_active else '❌'} 상품 페이지: {len(active_pages)}개 공개 / {len(pages)}개 전체")
        else:
            checks.append("❌ 상품 페이지: 없음")

        # 4. 공개 기간 확인
        if page_active and active_pages:
            p = active_pages[0]
            if p.get("isAlwaysPublic"):
                checks.append("✅ 공개 기간: 상시")
            else:
                start = p.get("startAt", "?")
                end = p.get("endAt", "?")
                checks.append(f"⚠️ 공개 기간: {start} ~ {end}")

        # 5. 상품 옵션 노출
        if page_id:
            products = _api_get(f"/v1/product/group/{page_id}")
            if isinstance(products, list):
                visible = [p for p in products if p.get("isDisplay")]
                checks.append(f"{'✅' if visible else '❌'} 노출 중인 옵션: {len(visible)}개 / {len(products)}개 전체")

        # 원인 분석
        causes = []
        buttons = []
        if not is_public:
            causes.append("마스터가 비공개 상태")
            buttons.append({"type": "navigate", "label": "📋 마스터 관리", "url": "/master/page", "variant": "primary", "description": "마스터 공개 상태를 변경합니다."})
        if not main_active:
            causes.append("메인 상품 페이지 비활성화")
            buttons.append({"type": "navigate", "label": "📋 메인 상품 페이지 관리", "url": "/product/page/list", "variant": "primary", "description": "메인 상품 페이지를 활성화합니다."})
        if not page_active:
            causes.append("상품 페이지 비공개")

        cause_text = ""
        if causes:
            cause_text = f"\n\n🎯 **원인**: " + ", ".join(causes)

        self.state = "idle"
        return Response(
            message=f"📊 **{self.data.get('master_name', master_name)} 진단 결과**\n\n" + "\n".join(checks) + cause_text,
            buttons=buttons, mode="diagnose",
        )

    def _handle_go_back(self, parsed: ParsedIntent) -> Response:
        """역방향 전환 — 리셋 없이 특정 단계로 돌아감."""
        # 다른 마스터면 마스터 데이터만 초기화
        if parsed.master_name and parsed.master_name != self.data.get("master_name", ""):
            self.data.pop("master_cms_id", None)
            self.data.pop("master_name", None)
            self.data.pop("master_id", None)
            self.data.pop("master_public_type", None)
            self.data.pop("series_ids", None)
            self.data.pop("series_titles", None)
            self.data.pop("product_page_id", None)
            self.data.pop("product_page_code", None)
            self.data.pop("product_page_title", None)
            self.data.pop("_all_pages", None)
            self.data.pop("product_ids", None)
            self.data["_requested_master"] = parsed.master_name
            return self._resolve_prerequisites(self._pending_target or "guide_create_page")

        # "다른 페이지로" → 페이지 데이터만 초기화, 마스터/시리즈 유지
        page_keywords = ["페이지", "다른 페이지"]
        if any(kw in parsed.extra for kw in page_keywords):
            self.data.pop("product_page_id", None)
            self.data.pop("product_page_code", None)
            self.data.pop("product_page_title", None)
            self.data.pop("_all_pages", None)
            self.data.pop("product_ids", None)
            self._check_existing_page()
            return self._exec_guide_create_page()

        # 기본: 한 단계 뒤로
        back_map = {
            "wait_create_option": "guide_create_page",
            "confirm_activate": "guide_create_option",
            "verification": "confirm_activate",
            "wait_create_page": "check_series",
            "wait_series": "check_master",
            "wait_select_page": "check_series",
        }
        target = back_map.get(self.state, "check_master")
        return self._execute_state(target)

    def _handle_edit_request(self, msg: str) -> Response:
        """수정/편집 요청 → 현재 맥락의 관리자센터 페이지로 안내."""
        page_id = self.data.get("product_page_id", "")
        master_id = self.data.get("master_cms_id", "")
        master_name = self.data.get("master_name", "")
        page_title = self.data.get("product_page_title", "")

        buttons = []
        if page_id:
            buttons.extend([
                {"type": "navigate", "label": "📄 상품 페이지 설정", "url": f"/product/page/{page_id}?masterId={master_id}&tab=settings", "variant": "primary", "description": "페이지 정보, 이미지 등을 수정합니다."},
                {"type": "navigate", "label": "📦 상품 옵션 관리", "url": f"/product/page/{page_id}?masterId={master_id}&tab=options", "variant": "primary", "description": "기존 옵션을 수정하거나 새 옵션을 등록합니다."},
            ])

        return Response(
            message=f"**{master_name}** > **{page_title}** 수정 페이지입니다.",
            buttons=buttons,
            step=_step_meta(self.state.replace("wait_create_", "guide_create_").replace("wait_", "") if self.state in STATE_TO_STEP else "guide_create_option"),
        )

    # ══════════════════════════════════════
    # 활성화 실행
    # ══════════════════════════════════════

    def _do_activate(self) -> Response:
        page_id = self.data.get("product_page_id", "")
        master_id = self.data.get("master_cms_id", "")
        product_ids = self.data.get("product_ids", [])
        steps_done = []
        errors = []

        # 1/4 상품 노출
        for pid in product_ids:
            r = _api_patch("/v1/product/display", {"id": pid, "isDisplay": True})
            if isinstance(r, dict) and r.get("error"):
                errors.append("상품 노출 설정 실패")
                break
        if not errors:
            steps_done.append("✅ 1/4 상품 노출 ON")

        # 2/4 순서 설정
        if not errors and product_ids:
            r = _api_patch(f"/v1/product/group/{page_id}/sequence", {"ids": product_ids})
            if isinstance(r, dict) and r.get("error"):
                errors.append("순서 설정 실패")
            else:
                steps_done.append("✅ 2/4 순서 설정")

        # 3/4 페이지 공개
        if not errors:
            r = _api_patch("/v1/product-group/status", {"id": page_id, "status": "ACTIVE"})
            if isinstance(r, dict) and r.get("error"):
                errors.append("페이지 공개 실패")
            else:
                steps_done.append("✅ 3/4 페이지 공개")

        # 4/4 메인 상품 설정
        if not errors:
            r = _api_patch(f"/v1/masters/{master_id}/main-product-group", {
                "productGroupType": "US_PLUS",
                "productGroupViewStatus": "ACTIVE",
                "isProductGroupWebLinkStatus": "INACTIVE",
                "isProductGroupAppLinkStatus": "INACTIVE",
            })
            if isinstance(r, dict) and r.get("error"):
                errors.append("메인 상품 설정 실패")
            else:
                steps_done.append("✅ 4/4 메인 상품 설정")

        progress = "\n".join(steps_done)

        if errors:
            failed_step = len(steps_done) + 1
            return Response(
                message=f"⚠️ 활성화 {failed_step}/4 단계에서 실패\n\n{progress}\n❌ {errors[0]}\n\n완료된 단계까지는 적용되었습니다. 재시도하면 실패한 단계부터 진행합니다.",
                buttons=[{"type": "action", "label": "🔄 재시도", "actionId": "activate", "variant": "danger", "description": f"{failed_step}단계부터 재시도합니다."}],
                step=_step_meta("confirm_activate"), mode="execute",
            )

        self.state = "verification"
        return self._exec_verification()

    # ══════════════════════════════════════
    # 의도 분류 (LLM structured output)
    # ══════════════════════════════════════

    def _parse_intent(self, msg: str) -> ParsedIntent:
        """LLM으로 의도 + 마스터명 추출. 현재 맥락을 함께 전달."""
        context_summary = self._build_context_summary()
        return _classify_with_llm(msg, context_summary)

    def _build_context_summary(self) -> str:
        """현재 플로우 상태를 LLM에 전달할 요약 문자열."""
        parts = [f"현재 단계: {self.state}"]
        if self.data.get("master_name"):
            parts.append(f"마스터: {self.data['master_name']} (cmsId: {self.data.get('master_cms_id', '')})")
        if self.data.get("product_page_title"):
            parts.append(f"상품 페이지: {self.data['product_page_title']} (코드: {self.data.get('product_page_code', '')})")
        if self.data.get("product_ids"):
            parts.append(f"등록된 옵션: {len(self.data['product_ids'])}개")
        if self.data.get("product_type"):
            parts.append(f"상품 타입: {self.data['product_type']}")
        return "\n".join(parts)

    # ══════════════════════════════════════
    # 상태별 버튼
    # ══════════════════════════════════════

    def _buttons_for_state(self, state: str) -> list[dict]:
        master_name = self.data.get("master_name", "")
        page_id = self.data.get("product_page_id", "")
        master_id = self.data.get("master_cms_id", "")

        buttons_map = {
            "wait_series": [
                {"type": "navigate", "label": "📝 파트너센터에서 시리즈 생성", "url": "/partner", "variant": "primary", "description": "좌측 앱 전환 아이콘에서 '파트너'를 클릭해주세요."},
                {"type": "confirm", "label": "✅ 시리즈 생성 완료", "variant": "primary", "description": "시리즈를 재확인합니다."},
            ],
            "wait_create_page": [
                {"type": "navigate", "label": "📄 상품 페이지 생성하러 가기", "url": "/product/page/create", "variant": "primary", "description": f"마스터에서 '{master_name}'을 선택해주세요."},
                {"type": "confirm", "label": "✅ 상품 페이지 생성 완료", "variant": "primary", "description": "생성을 완료했으면 눌러주세요."},
            ],
            "wait_create_option": [
                {"type": "navigate", "label": "📦 상품 옵션 등록하러 가기", "url": f"/product/create?productPageId={page_id}&productType={self.data.get('product_type', 'SUBSCRIPTION')}&masterId={master_id}", "variant": "primary", "description": "상품명, 금액, 결제주기, 시리즈를 입력해주세요."},
                {"type": "confirm", "label": "✅ 상품 옵션 등록 완료", "variant": "primary", "description": "옵션 등록을 완료했으면 눌러주세요."},
                {"type": "confirm", "label": "➕ 옵션 하나 더 등록", "variant": "secondary", "description": "추가 옵션을 등록합니다."},
            ],
        }
        return buttons_map.get(state, [])
