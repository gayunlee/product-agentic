"""
LangGraph 기반 상품 세팅 에이전트 그래프.

FlowMachine을 대체. interrupt/resume으로 human-in-the-loop 구현.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict, Annotated

from langchain_aws import ChatBedrockConverse
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.types import interrupt, Command
from langgraph.checkpoint.memory import MemorySaver

from src.tools.admin_api import _client, _safe_request, MOCK_MODE, _get_mock

logger = logging.getLogger(__name__)

# ── State 정의 ──

class AgentState(TypedDict):
    """그래프 상태. LangGraph가 자동으로 관리."""
    messages: Annotated[list, add_messages]
    # 수집된 데이터 (마스터, 시리즈, 페이지, 옵션 등)
    collected: dict[str, Any]
    # 현재 phase
    phase: str
    # 유저가 요청한 액션
    action: str
    # LLM 메시지 (유저에게 보여줄 텍스트)
    response_message: str
    # 버튼
    response_buttons: list[dict]
    # 모드 (guide / execute / diagnose / idle)
    response_mode: str
    # 스텝 진행
    response_step: dict | None
    # 프론트엔드에서 전달한 컨텍스트
    context: dict[str, Any]


# ── 상수 ──

STEPS = ["마스터 확인", "시리즈 확인", "상품 페이지 생성", "상품 옵션 등록", "활성화", "검증"]

STATE_TO_STEP = {
    "check_master": 1,
    "check_series": 2,
    "guide_create_page": 3,
    "guide_create_option": 4,
    "confirm_activate": 5,
    "verification": 6,
}

_STATUS_LABELS = {
    "ACTIVE": "공개", "INACTIVE": "비공개", "EXCLUDED": "제외됨",
    "PUBLIC": "공개", "PRIVATE": "비공개", "PENDING": "준비중",
}


def _status_label(raw: str) -> str:
    return _STATUS_LABELS.get(raw, raw)


def _step_meta(state_name: str) -> dict:
    num = STATE_TO_STEP.get(state_name, 1)
    return {"current": num, "total": 6, "label": STEPS[num - 1], "steps": STEPS}


# API 호출 이력 추적 (eval용, 스레드별 격리)
import threading

_thread_local = threading.local()


def reset_api_log():
    _thread_local.api_log = []
    _thread_local.phase_log = []


def get_api_log() -> list[dict]:
    return list(getattr(_thread_local, "api_log", []))


def get_phase_log() -> list[str]:
    return list(getattr(_thread_local, "phase_log", []))


def _log_api(entry: dict):
    if not hasattr(_thread_local, "api_log"):
        _thread_local.api_log = []
    _thread_local.api_log.append(entry)


def _track_phase(phase: str):
    """phase 방문을 기록."""
    if not hasattr(_thread_local, "phase_log"):
        _thread_local.phase_log = []
    log = _thread_local.phase_log
    if not log or log[-1] != phase:
        log.append(phase)


def _api_get(path: str, params: dict | None = None):
    _log_api({"method": "GET", "path": path, "params": params})
    if MOCK_MODE:
        return _mock_api_get(path, params or {})
    from src.tools.admin_api import ADMIN_BASE, ADMIN_TOKEN
    print(f"🌐 [API GET] {ADMIN_BASE}{path} params={params} token_len={len(ADMIN_TOKEN)}")
    with _client() as c:
        r = c.get(path, params=params or {})
        print(f"🌐 [API GET] status={r.status_code} body={r.text[:200]}")
        return _safe_request(r)


def _api_patch(path: str, body: dict):
    _log_api({"method": "PATCH", "path": path})
    if MOCK_MODE:
        return _mock_api_patch(path, body)
    with _client() as c:
        r = c.patch(path, json=body)
        return _safe_request(r)


def _mock_api_get(path: str, params: dict) -> Any:
    """Mock 모드용 GET 응답."""
    keyword = params.get("searchKeyword", params.get("name", ""))

    if "/v1/masters" in path and "main-product-group" in path:
        return _get_mock("get_master_detail")
    if "/v1/masters" in path:
        return _get_mock("search_masters", keyword=keyword)
    if "/with-series" in path:
        return _get_mock("get_series_list")
    if "/v1/product-group/" in path and path.count("/") > 2:
        # /v1/product-group/{id}
        return _get_mock("get_product_page_detail")
    if "/v1/product-group" in path:
        return _get_mock("get_product_page_list")
    if "/v1/product/group/" in path:
        return _get_mock("get_product_list_by_page")
    if "/v1/master-groups" in path:
        return _get_mock("get_master_groups", keyword=keyword)
    return {"mock": True, "path": path}


def _mock_api_patch(path: str, body: dict) -> dict:
    """Mock 모드용 PATCH 응답."""
    if "/display" in path:
        return _get_mock("update_product_display")
    if "/sequence" in path:
        return _get_mock("update_product_sequence")
    if "/status" in path:
        return _get_mock("update_product_page_status")
    if "/main-product-group" in path:
        return _get_mock("update_main_product_setting")
    return {"success": True, "status": 200}


def _find_active_page(pages: list[dict]) -> dict | None:
    """공개 페이지 중 실제 노출되는 페이지를 판별."""
    from datetime import datetime, date
    today = date.today()
    active_pages = [p for p in pages if p.get("status") == "ACTIVE"]

    for p in active_pages:
        if not p.get("isAlwaysPublic") and (p.get("startAt") or p.get("endAt")):
            try:
                start = _parse_date(p.get("startAt", ""))
                end = _parse_date(p.get("endAt", ""))
                if start <= today <= end:
                    return p
            except (ValueError, TypeError):
                continue

    for p in active_pages:
        if p.get("isAlwaysPublic"):
            return p
    return None


def _parse_date(raw: str):
    from datetime import datetime, date
    if not raw:
        return date.min
    for fmt in ["%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y.%m.%d"]:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()


# ── LLM ──

def _create_llm(guardrail_config: dict | None = None) -> ChatBedrockConverse:
    kwargs = {}
    if guardrail_config:
        kwargs["guardrail_config"] = guardrail_config
    return ChatBedrockConverse(
        model_id="us.anthropic.claude-haiku-4-5-20251001-v1:0",
        region_name="us-west-2",
        temperature=0,
        max_tokens=300,
        **kwargs,
    )


MANAGER_PROMPT = """당신은 어스플러스 관리자센터 상품 세팅 AI 어시스턴트입니다.
운영매니저의 요청을 이해하고, 적절한 액션을 결정합니다.

## 데이터 구조 (1:N 관계)
```
마스터 그룹 1개 (이름만, /master에서 관리)
  └─ 오피셜클럽 N개 (상세 프로필, /official-club에서 관리)
       └─ 시리즈 N개 (파트너센터에서 생성)
       └─ 상품 페이지 N개 (각각 독립적인 결제 접점)
            └─ 상품 옵션 N개 (실제 구매 단위)
```
- 마스터 그룹 ≠ 오피셜클럽. 마스터 그룹은 이름만, 오피셜클럽은 상세 프로필.
- 오피셜클럽 1개에 상품 페이지 여러 개 가능
- 상품 페이지 1개에 상품 옵션 여러 개 가능
- "상품 옵션 추가" 시 반드시 **어떤 상품 페이지**에 추가할지 특정해야 함

## 도메인 지식
- **마스터(오피셜클럽)**: 콘텐츠 크리에이터의 멤버십 공간. 공개/비공개/준비중 상태.
- **시리즈**: 마스터의 콘텐츠 묶음. 파트너센터에서 생성. 상품 옵션 연결 시 필수.
- **상품 페이지**: 고객이 보는 결제 페이지. 구독상품/단건상품.
- **상품 옵션**: 실제 구매 단위. 상품명, 금액, 결제주기, 시리즈 연결, 프로모션 설정.
- **활성화**: 상품 노출 ON → 순서 설정 → 페이지 공개 → 메인 상품 설정 (4단계)
- **선행 조건**: 오피셜클럽 → 시리즈 → 상품 페이지 → 상품 옵션 (순서 필수)

## 관리자센터 페이지 구조
- 상품 페이지 목록: /product (마스터별 필터링)
- 상품 페이지 생성: /product/page/create (정보+이미지 한번에)
- 상품 페이지 상세: /product/page/{id}?tab=settings|options|letters|caution
- 상품 옵션 등록: /product/create?productPageId={id}&productType={type}&masterId={cmsId}
- 상품 옵션 수정: /product/{productId}?productPageId={id}&productType={type}&masterId={cmsId}
- 오피셜클럽 관리: /official-club
- 마스터 페이지 관리: /master/page
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
- diagnose: 노출 문제 진단 (params: master_name) ← "안 보여", "왜 안 되는지" 요청 시에만
- toggle_display: 상품 옵션 공개/비공개 변경 (params: master_name, option_name, action: show/hide)
- toggle_page: 상품 페이지 공개/비공개 변경 (params: master_name, page_code, action: show/hide)
- edit: 수정 안내 (params: master_name, target: page/option, page_code) ← "수정/변경/편집" 요청 시
- go_back: 이전 단계로 (params: target: master/page)
- confirm: 유저가 작업 완료 알림
- chat: 액션 없이 대화만

⚠️ 액션 선택 가이드:
- "상품 만들래/세팅해줘" → setup (전체 프로세스)
- "옵션 추가/등록해줘" → create_option (기존 페이지에 추가)
- "옵션 수정/변경하려고" → edit (target: option)
- "페이지 수정/설정 바꾸려고" → edit (target: page)
- "마스터 있어?/검색해줘" → search_master (정보 확인만)
- "상품페이지 뭐있어?" → list_pages (목록 조회)
- "옵션 비공개해줘/공개해줘" → toggle_display
- "페이지 비공개해줘/공개해줘" → toggle_page
- "안 보여/왜 안 나와" → diagnose (노출 문제 진단)

⚠️ 맥락 연결 중요:
- 이전 대화에서 "상품페이지 등록/세팅" 얘기가 있었고 유저가 마스터명만 답하면 → setup (search_master 아님)
- 이전에 "옵션 추가" 얘기가 있었고 유저가 마스터명만 답하면 → create_option
- 이전에 "진단해줘" 얘기가 있었고 유저가 마스터명만 답하면 → diagnose
- 마스터명만 입력되면 직전 맥락의 action을 이어가야 함

## 응답 형식
반드시 JSON만 출력:
{"action": "...", "params": {...}, "message": "유저에게 보여줄 안내 메시지"}

message: 유저에게 자연스럽게 안내하는 텍스트. 마크다운 사용 가능.
action이 "chat"이면 message에 대화 응답을 넣으세요."""

# 의도 → 목표 phase
INTENT_TO_PHASE = {
    "setup": "guide_create_page",
    "create_page": "guide_create_page",
    "create_option": "guide_create_option",
    "activate": "confirm_activate",
    "verify": "verification",
    "query_master": "check_master",
    "search_master": "check_master",
    "query_series": "check_series",
    "check_series": "check_series",
    "diagnose": "diagnose",
    "list_masters": "check_master",
    "list_pages": "list_pages",
    "list_options": "list_options",
}

# 사전조건 체인
PREREQUISITES = {
    "check_master": [],
    "check_series": ["master_cms_id"],
    "guide_create_page": ["master_cms_id", "series_ids"],
    "guide_create_option": ["master_cms_id", "series_ids", "product_page_id"],
    "confirm_activate": ["master_cms_id", "product_page_id", "product_ids"],
    "verification": ["master_cms_id", "product_page_id"],
}

KEY_TO_FILLER = {
    "master_cms_id": "check_master",
    "series_ids": "check_series",
    "product_page_id": "guide_create_page",
    "product_ids": "guide_create_option",
}


# ══════════════════════════════════════
# 노드 함수들
# ══════════════════════════════════════


def classify_node(state: AgentState) -> dict:
    """LLM이 대화를 읽고 의도를 분류. 모든 라우팅 결정은 LLM이 한다."""
    messages = state["messages"]
    collected = state.get("collected", {})
    phase = state.get("phase", "idle")

    # 마지막 유저 메시지
    last_msg = ""
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            last_msg = m.content
            break

    if not last_msg:
        return {"action": "chat", "response_message": "무엇을 도와드릴까요?"}

    # 버튼 클릭 (JSON) — 유일한 하드코딩 분기
    if last_msg.strip().startswith("{"):
        try:
            parsed = json.loads(last_msg)
            return {
                "action": "direct",
                "collected": {**collected, "_direct_params": parsed},
            }
        except json.JSONDecodeError:
            pass

    # ── LLM이 의도 분류 ──
    llm = _create_llm()

    # 현재 상태 요약
    context_parts = [f"현재 단계: {phase}"]
    if collected.get("master_name"):
        context_parts.append(f"마스터: {collected['master_name']} (cmsId: {collected.get('master_cms_id', '')})")
    if collected.get("product_page_title"):
        context_parts.append(f"상품 페이지: {collected['product_page_title']} (코드: {collected.get('product_page_code', '')})")
    if collected.get("product_ids"):
        context_parts.append(f"등록된 옵션: {len(collected['product_ids'])}개")
    if collected.get("product_type"):
        context_parts.append(f"상품 타입: {collected['product_type']}")
    context_summary = "\n".join(context_parts)

    system_text = MANAGER_PROMPT
    if context_summary:
        system_text += f"\n\n## 현재 상태\n{context_summary}"

    # 대화 히스토리 (LLM이 맥락을 이해하도록)
    recent = []
    history_msgs = [m for m in messages if isinstance(m, (HumanMessage, AIMessage))]
    for m in history_msgs[-8:]:
        role = "user" if isinstance(m, HumanMessage) else "assistant"
        content = m.content[:500] if isinstance(m.content, str) else str(m.content)[:500]
        recent.append(HumanMessage(content=content) if role == "user" else AIMessage(content=content))

    try:
        resp = llm.invoke([SystemMessage(content=system_text)] + recent)
        text = resp.content.strip()
        if "```" in text:
            text = text.split("```")[1].replace("json", "").strip()
        understood = json.loads(text)
        print(f"🧠 LLM 분류: {understood.get('action')} params={understood.get('params', {})}")
    except Exception as e:
        logger.warning(f"LLM 이해 실패: {e}")
        understood = {"action": "chat", "params": {}, "message": "죄송합니다. 다시 말씀해주세요."}

    action = understood.get("action", "chat")
    params = understood.get("params", {})
    llm_message = understood.get("message", "")

    # LLM이 추출한 파라미터를 collected에 저장
    new_collected = {**collected}
    if params.get("master_name"):
        master_name = params["master_name"]
        if master_name != collected.get("master_name", ""):
            for key in ["master_cms_id", "master_name", "master_id", "master_public_type",
                        "series_ids", "series_titles", "product_page_id", "product_page_code",
                        "product_page_title", "_all_pages", "product_ids"]:
                new_collected.pop(key, None)
        new_collected["_requested_master"] = master_name
    if params.get("product_type"):
        new_collected["product_type"] = params["product_type"]
    if params.get("page_code"):
        new_collected["_requested_page_code"] = params["page_code"]
    if params.get("target"):
        new_collected["_edit_target"] = params["target"]
    if params.get("option_name"):
        new_collected["_option_name"] = params["option_name"]

    return {
        "action": action,
        "collected": new_collected,
        "response_message": llm_message,
    }


def resolve_node(state: AgentState) -> dict:
    """액션에 따라 target phase를 결정하고 사전조건을 체크."""
    action = state.get("action", "chat")
    collected = state.get("collected", {})
    phase = state.get("phase", "idle")

    # direct 버튼 클릭
    if action == "direct":
        params = collected.get("_direct_params", {})
        direct_target = params.get("target", "")
        direct_type = params.get("type", "")

        if direct_target in ("activate_display", "activate_page", "activate_main"):
            return {"phase": "do_activate_step", "collected": {**collected, "_activate_target": direct_target}}
        if direct_target == "activate" or direct_type == "do_activate":
            return {"phase": "do_activate"}
        if direct_target == "toggle_display_exec":
            return {"phase": "toggle_display_exec"}
        if direct_target == "toggle_page_exec":
            return {"phase": "toggle_page_exec"}
        if direct_type == "confirm":
            return {"phase": "handle_confirm"}
        if direct_type in INTENT_TO_PHASE:
            target = INTENT_TO_PHASE[direct_type]
            return _check_prerequisites(target, collected)

    # confirm
    if action == "confirm":
        return {"phase": "handle_confirm"}

    # do_activate
    if action == "do_activate":
        return {"phase": "do_activate"}

    # 의도 → target phase
    target_phase = INTENT_TO_PHASE.get(action)
    if target_phase == "diagnose":
        return {"phase": "diagnose"}
    if target_phase == "list_pages":
        return {"phase": "list_pages"}
    if target_phase == "list_options":
        return {"phase": "list_options"}
    if target_phase:
        return _check_prerequisites(target_phase, collected)

    # toggle_display / toggle_page
    if action == "toggle_display":
        return {"phase": "toggle_display"}
    if action == "toggle_page":
        return {"phase": "toggle_page"}

    # edit — 수정 안내 (페이지 이동)
    if action == "edit":
        return {"phase": "edit"}

    # chat — LLM 메시지 그대로
    return {"phase": "chat"}


def _check_prerequisites(target: str, collected: dict) -> dict:
    """사전조건을 체크하고, 빠진 게 있으면 해당 filler phase로 보냄."""
    required = PREREQUISITES.get(target, [])
    for key in required:
        val = collected.get(key)
        if val is None or val == "" or val == []:
            filler = KEY_TO_FILLER.get(key, "check_master")
            return {"phase": filler, "collected": {**collected, "_pending_target": target}}
    # 모든 사전조건 충족
    return {"phase": target, "collected": {**collected, "_pending_target": None}}


# ── 실행 노드들 ──


def check_master_node(state: AgentState) -> dict:
    """마스터 검색 및 확인."""
    _track_phase("check_master")
    collected = state.get("collected", {})
    name = collected.get("_requested_master", "")

    if not name:
        # 마스터명 요청 (interrupt)
        answer = interrupt({
            "message": "어떤 마스터(오피셜클럽)에 상품 페이지를 만드시겠어요?",
            "buttons": [{"type": "navigate", "label": "📋 마스터 목록 보기", "url": "/official-club", "variant": "secondary", "description": "등록된 마스터 목록을 확인합니다."}],
            "mode": "guide",
            "step": _step_meta("check_master"),
        })
        # resume 시 answer = 유저 입력
        collected = {**collected, "_requested_master": answer}

    name = collected.get("_requested_master", "")
    print(f"🔍 [check_master] name='{name}'")
    result = _api_get("/v1/masters", {"searchKeyword": name, "searchCategory": "NAME"})
    print(f"🔍 [check_master] result type={type(result).__name__}, value={str(result)[:300]}")

    if isinstance(result, dict) and result.get("error"):
        return _response(
            collected, "check_master",
            f"API 오류: {result.get('guide', '')}",
            buttons=[{"type": "navigate", "label": "📋 마스터 목록 보기", "url": "/official-club", "variant": "secondary", "description": "직접 확인해보세요."}],
        )

    if isinstance(result, list) and len(result) > 0:
        exact = [m for m in result if m.get("name") == name]
        master = exact[0] if exact else result[0]
        new_collected = {
            **collected,
            "master_cms_id": master.get("cmsId", ""),
            "master_name": master.get("name", ""),
            "master_id": master.get("id", ""),
            "master_public_type": master.get("publicType", ""),
        }

        # 사전조건 해소 → 다음 체크
        pending = new_collected.get("_pending_target")
        if pending:
            prereq = _check_prerequisites(pending, new_collected)
            return {"collected": new_collected, "phase": prereq["phase"]}

        return _response(
            new_collected, "check_master",
            f"✅ **{new_collected['master_name']}** 마스터 확인 (상태: {_status_label(new_collected['master_public_type'])})",
        )

    # 못 찾음 → 전체 검색
    all_result = _api_get("/v1/masters")
    if isinstance(all_result, list):
        fuzzy = [m for m in all_result if name in m.get("name", "")]
        if fuzzy:
            master = fuzzy[0]
            new_collected = {
                **collected,
                "master_cms_id": master.get("cmsId", ""),
                "master_name": master.get("name", ""),
                "master_id": master.get("id", ""),
                "master_public_type": master.get("publicType", ""),
            }
            pending = new_collected.get("_pending_target")
            if pending:
                prereq = _check_prerequisites(pending, new_collected)
                return {"collected": new_collected, "phase": prereq["phase"]}
            return _response(
                new_collected, "check_master",
                f"✅ **{new_collected['master_name']}** 마스터 확인 (상태: {_status_label(new_collected['master_public_type'])})",
            )

    # 마스터 없음 → 생성 안내 (interrupt로 완료 대기)
    groups = _api_get("/v1/master-groups")
    has_group = False
    if isinstance(groups, dict):
        group_list = groups.get("masterGroups", [])
        has_group = any(name in g.get("name", "") for g in group_list)

    if has_group:
        msg = f"'{name}' 오피셜클럽이 아직 없습니다.\n\n마스터 그룹은 있으니, 오피셜클럽을 생성해주세요."
        buttons = [
            {"type": "navigate", "label": "➕ 오피셜클럽 생성", "url": "/official-club/create", "variant": "primary", "description": f"마스터 그룹 '{name}'에 오피셜클럽을 생성합니다."},
            {"type": "confirm", "label": "✅ 오피셜클럽 생성 완료", "variant": "primary", "description": "생성을 완료했으면 눌러주세요."},
        ]
    else:
        msg = f"'{name}' 마스터 그룹과 오피셜클럽 모두 없습니다.\n\n마스터 그룹을 먼저 만들고, 오피셜클럽을 생성해주세요."
        buttons = [
            {"type": "navigate", "label": "📋 마스터 그룹 관리", "url": "/master", "variant": "primary", "description": "마스터 그룹을 먼저 생성합니다."},
            {"type": "navigate", "label": "➕ 오피셜클럽 생성", "url": "/official-club/create", "variant": "secondary", "description": "마스터 그룹 선택 후 오피셜클럽을 생성합니다."},
            {"type": "confirm", "label": "✅ 완료", "variant": "primary", "description": "마스터 그룹과 오피셜클럽 생성을 완료했으면 눌러주세요."},
        ]

    # interrupt: 유저가 생성하고 "완료" 누를 때까지 대기
    answer = interrupt({
        "message": msg,
        "buttons": buttons,
        "mode": "guide",
        "step": _step_meta("check_master"),
    })
    # resume 후 다시 검색
    collected = {**collected, "_requested_master": name}
    return {"collected": collected, "phase": "check_master"}


def check_series_node(state: AgentState) -> dict:
    """시리즈 존재 확인."""
    _track_phase("check_series")
    collected = state.get("collected", {})
    cms_id = collected.get("master_cms_id", "")
    master_name = collected.get("master_name", "")

    result = _api_get("/with-series", {"masterId": cms_id, "seriesState": "PUBLISHED"})

    series_list = []
    if isinstance(result, dict):
        masters = result.get("masters", [])
        if masters and masters[0].get("series"):
            series_list = masters[0]["series"]

    if series_list:
        new_collected = {
            **collected,
            "series_ids": [s["_id"] for s in series_list],
            "series_titles": [s.get("title", "") for s in series_list],
        }
        # 기존 페이지 확인
        _check_existing_pages(new_collected)

        pending = new_collected.get("_pending_target")
        if pending:
            prereq = _check_prerequisites(pending, new_collected)
            return {"collected": new_collected, "phase": prereq["phase"]}

        series_text = "\n".join(f"  - {s.get('title', '무제')}" for s in series_list)
        return _response(
            new_collected, "check_series",
            f"✅ **{master_name}** 시리즈 {len(series_list)}개 확인\n{series_text}",
        )

    # 시리즈 없음 → interrupt
    answer = interrupt({
        "message": f"✅ **{master_name}** 마스터 확인\n❌ 시리즈가 없습니다. 상품 옵션에 시리즈가 필수이므로 먼저 생성해주세요.",
        "buttons": [
            {"type": "navigate", "label": "📝 파트너센터에서 시리즈 생성", "url": "/partner", "variant": "primary", "description": "좌측 앱 전환 아이콘에서 '파트너'를 클릭해주세요."},
            {"type": "confirm", "label": "✅ 시리즈 생성 완료", "variant": "primary", "description": "시리즈 생성을 완료했으면 눌러주세요. 시리즈를 재확인합니다."},
        ],
        "mode": "execute",
        "step": _step_meta("check_series"),
    })
    # resume 후 다시 시리즈 확인
    return {"collected": collected, "phase": "check_series"}


def _check_existing_pages(collected: dict):
    """기존 상품 페이지가 있는지 확인하고 collected에 저장."""
    cms_id = collected.get("master_cms_id", "")
    if not cms_id:
        return
    pages = _api_get("/v1/product-group", {"masterId": cms_id})
    if isinstance(pages, list) and len(pages) > 0:
        collected["_all_pages"] = pages
        if len(pages) == 1:
            collected["product_page_id"] = pages[0].get("id", "")
            collected["product_page_code"] = pages[0].get("code", "")
            collected["product_page_title"] = pages[0].get("title", "")


def guide_create_page_node(state: AgentState) -> dict:
    """상품 페이지 생성 안내."""
    _track_phase("guide_create_page")
    collected = state.get("collected", {})
    master_name = collected.get("master_name", "")
    cms_id = collected.get("master_cms_id", "")
    series_count = len(collected.get("series_ids", []))
    series_text = ", ".join(collected.get("series_titles", []))
    all_pages = collected.get("_all_pages", [])

    # 여러 페이지 → 선택
    if all_pages and "product_page_id" not in collected:
        rows = "\n".join(
            f"- **{p.get('title', '')}** (코드: {p.get('code', '')}, {_status_label(p.get('status', ''))})"
            for p in all_pages
        )
        answer = interrupt({
            "message": f"✅ **{master_name}** 마스터 확인\n✅ 시리즈 {series_count}개: {series_text}\n\n기존 상품 페이지 **{len(all_pages)}개**:\n{rows}\n\n코드 번호를 알려주시면 해당 페이지에 옵션을 등록합니다.",
            "buttons": [
                {"type": "navigate", "label": "📄 새 상품 페이지 생성", "url": "/product/page/create", "variant": "secondary", "description": "새 페이지를 만듭니다."},
            ],
            "mode": "guide",
            "step": _step_meta("guide_create_page"),
        })
        # 유저가 코드 번호 입력
        nums = "".join(c for c in str(answer) if c.isdigit())
        for p in all_pages:
            if str(p.get("code", "")) == nums or p.get("title", "") in str(answer):
                collected = {
                    **collected,
                    "product_page_id": p.get("id", ""),
                    "product_page_code": p.get("code", ""),
                    "product_page_title": p.get("title", ""),
                }
                return {"collected": collected, "phase": "guide_create_option"}
        # 매칭 실패 → 다시 이 노드
        return {"collected": collected, "phase": "guide_create_page"}

    # 이미 페이지 있음 → 옵션 등록 안내
    if "product_page_id" in collected:
        page_id = collected["product_page_id"]
        title = collected.get("product_page_title", "")
        code = collected.get("product_page_code", "")
        product_type = collected.get("product_type", "SUBSCRIPTION")

        answer = interrupt({
            "message": f"✅ **{master_name}** 마스터 확인\n✅ 시리즈 {series_count}개: {series_text}\n✅ 상품 페이지: **{title}** (코드: {code})\n\n이 페이지에 상품 옵션을 등록하시겠어요?",
            "buttons": [
                {"type": "navigate", "label": "📦 상품 옵션 등록하러 가기", "url": f"/product/create?productPageId={page_id}&productType={product_type}&masterId={cms_id}", "variant": "primary", "description": f"'{title}' 페이지에 옵션을 추가합니다."},
                {"type": "confirm", "label": "✅ 상품 옵션 등록 완료", "variant": "primary", "description": "옵션 등록을 완료했으면 눌러주세요."},
                {"type": "navigate", "label": "📄 새 상품 페이지 생성", "url": "/product/page/create", "variant": "secondary", "description": "기존 페이지 대신 새 페이지를 만듭니다."},
            ],
            "mode": "guide",
            "step": _step_meta("guide_create_page"),
        })
        return {"collected": collected, "phase": "handle_confirm"}

    # 페이지 없음 → 생성 안내 (interrupt)
    answer = interrupt({
        "message": f"✅ **{master_name}** 마스터 확인\n✅ 시리즈 {series_count}개: {series_text}\n\n사전 조건 충족! 상품 페이지를 생성해주세요.",
        "buttons": [
            {"type": "navigate", "label": "📄 상품 페이지 생성하러 가기", "url": "/product/page/create", "variant": "primary", "description": f"관리자센터에서 직접 생성합니다. 마스터에서 '{master_name}'을 선택하고, 정보 설정과 이미지까지 등록해주세요."},
            {"type": "confirm", "label": "✅ 상품 페이지 생성 완료", "variant": "primary", "description": "생성을 완료했으면 눌러주세요. 결과를 확인합니다."},
        ],
        "mode": "guide",
        "step": _step_meta("guide_create_page"),
    })
    return {"collected": collected, "phase": "handle_confirm"}


def guide_create_option_node(state: AgentState) -> dict:
    """상품 옵션 등록 안내."""
    _track_phase("guide_create_option")
    collected = state.get("collected", {})
    page_id = collected.get("product_page_id", "")
    master_id = collected.get("master_cms_id", "")
    master_name = collected.get("master_name", "")
    page_title = collected.get("product_page_title", "")
    product_type = collected.get("product_type", "SUBSCRIPTION")

    # 기존 옵션 확인
    existing_text = ""
    products = _api_get(f"/v1/product/group/{page_id}")
    if isinstance(products, list) and len(products) > 0:
        collected["product_ids"] = [str(p.get("id", "")) for p in products]
        existing_text = f"\n\n현재 등록된 옵션 **{len(products)}개**:\n" + "\n".join(
            f"- {p.get('name', '')} ({p.get('originPrice', 0):,}원, {'공개' if p.get('isDisplay') else '비공개'})"
            for p in products
        )

    type_label = "구독상품" if product_type == "SUBSCRIPTION" else "단건상품"

    answer = interrupt({
        "message": f"**{master_name}** > **{page_title}** ({type_label}){existing_text}",
        "buttons": [
            {"type": "navigate", "label": "📦 옵션 추가", "url": f"/product/create?productPageId={page_id}&productType={product_type}&masterId={master_id}", "variant": "primary", "description": "새 상품 옵션을 등록합니다."},
            {"type": "action", "label": "➡️ 다음 (활성화)", "action": {"type": "do_activate", "target": "activate", "params": {}}, "variant": "secondary", "description": "활성화 단계로 넘어갑니다."},
        ],
        "mode": "guide",
        "step": _step_meta("guide_create_option"),
    })
    return {"collected": collected, "phase": "handle_confirm"}


def handle_confirm_node(state: AgentState) -> dict:
    """유저가 '완료' 후 데이터 재확인하고 다음 단계로."""
    collected = state.get("collected", {})
    phase = state.get("phase", "")
    pending = collected.get("_pending_target")

    cms_id = collected.get("master_cms_id", "")

    # 페이지 확인
    if "product_page_id" not in collected and cms_id:
        _check_existing_pages(collected)
        if "product_page_id" in collected:
            if pending:
                prereq = _check_prerequisites(pending, collected)
                return {"collected": collected, "phase": prereq["phase"]}
            return {"collected": collected, "phase": "guide_create_option"}
        # 아직 없음
        return {"collected": collected, "phase": "guide_create_page"}

    # 옵션 확인
    page_id = collected.get("product_page_id", "")
    if page_id:
        products = _api_get(f"/v1/product/group/{page_id}")
        if isinstance(products, list) and len(products) > 0:
            collected["product_ids"] = [str(p.get("id", "")) for p in products]
            return {"collected": collected, "phase": "confirm_activate"}

    # pending target으로
    if pending:
        prereq = _check_prerequisites(pending, collected)
        return {"collected": collected, "phase": prereq["phase"]}

    return {"collected": collected, "phase": "guide_create_option"}


def confirm_activate_node(state: AgentState) -> dict:
    """활성화 전 확인."""
    _track_phase("confirm_activate")
    collected = state.get("collected", {})
    page_id = collected.get("product_page_id", "")

    products = _api_get(f"/v1/product/group/{page_id}")
    if isinstance(products, list) and len(products) > 0:
        collected["product_ids"] = [str(p.get("id", "")) for p in products]
        options_text = "\n".join(f"  - {p.get('name', '')} ({p.get('originPrice', 0):,}원)" for p in products)

        answer = interrupt({
            "message": f"✅ 상품 옵션 {len(products)}개 확인!\n{options_text}\n\n활성화하면 고객에게 노출됩니다.",
            "buttons": [{"type": "action", "label": "🚀 활성화하기", "actionId": "activate", "variant": "primary", "description": "상품 노출, 순서, 페이지 공개, 메인 상품 설정을 한번에 처리합니다."}],
            "mode": "execute",
            "step": _step_meta("confirm_activate"),
        })
        return {"collected": collected, "phase": "do_activate"}

    return _response(collected, "guide_create_option", "상품 옵션이 없습니다. 옵션을 먼저 등록해주세요.")


def do_activate_node(state: AgentState) -> dict:
    """점진적 활성화."""
    _track_phase("do_activate")
    collected = state.get("collected", {})
    page_id = collected.get("product_page_id", "")
    master_id = collected.get("master_cms_id", "")
    master_name = collected.get("master_name", "")
    product_ids = collected.get("product_ids", [])
    page_title = collected.get("product_page_title", "")

    checks = [f"📄 **선택된 페이지: {page_title}**"]

    # 1. 상품 옵션 노출
    products = _api_get(f"/v1/product/group/{page_id}")
    hidden = []
    if isinstance(products, list):
        hidden = [p for p in products if not p.get("isDisplay")]
        visible = [p for p in products if p.get("isDisplay")]
        checks.append(f"{'✅' if not hidden else '⚠️'} 옵션 노출: {len(visible)}개 공개 / {len(hidden)}개 비공개")

    # 2. 페이지 공개 상태
    page = _api_get(f"/v1/product-group/{page_id}")
    page_status = page.get("status", "") if isinstance(page, dict) else ""
    checks.append(f"{'✅' if page_status == 'ACTIVE' else '⚠️'} 이 페이지: {_status_label(page_status)}")

    # 3. 메인 상품 페이지
    main = _api_get(f"/v1/masters/{master_id}/main-product-group")
    main_status = main.get("productGroupViewStatus", "") if isinstance(main, dict) and not main.get("error") else ""
    checks.append(f"{'✅' if main_status == 'ACTIVE' else '⚠️'} 메인 상품 페이지: {_status_label(main_status) if main_status else '미설정'}")

    checks_text = "\n\n".join(checks)
    buttons = []

    if hidden:
        names = ", ".join(p.get("name", "") for p in hidden)
        buttons.append({"type": "action", "label": f"👁️ 비공개 옵션 {len(hidden)}개 공개하기", "action": {"type": "direct", "target": "activate_display", "params": {}}, "variant": "primary", "description": f"{names} 옵션을 공개합니다."})

    if page_status != "ACTIVE":
        buttons.append({"type": "action", "label": "📄 이 페이지 공개하기", "action": {"type": "direct", "target": "activate_page", "params": {}}, "variant": "primary", "description": f"'{page_title}' 페이지를 공개로 변경합니다."})

    if main_status != "ACTIVE":
        buttons.append({"type": "action", "label": "🏠 구독 탭 노출 켜기", "action": {"type": "direct", "target": "activate_main", "params": {}}, "variant": "primary", "description": f"{master_name} 마스터를 구독 탭에 표시합니다."})

    if not buttons:
        # 모두 완료 → 검증
        return {"collected": collected, "phase": "verification"}

    answer = interrupt({
        "message": f"**{master_name}** > **{page_title}** 활성화 현황:\n\n{checks_text}\n\n아래 항목을 하나씩 처리합니다.",
        "buttons": buttons,
        "mode": "execute",
        "step": _step_meta("confirm_activate"),
    })
    return {"collected": collected, "phase": "do_activate_step"}


def do_activate_step_node(state: AgentState) -> dict:
    """개별 활성화 단계 실행."""
    collected = state.get("collected", {})
    target = collected.get("_activate_target", "")
    page_id = collected.get("product_page_id", "")
    master_id = collected.get("master_cms_id", "")
    product_ids = collected.get("product_ids", [])

    if target == "activate_display":
        for pid in product_ids:
            _api_patch("/v1/product/display", {"id": pid, "isDisplay": True})
        if product_ids:
            _api_patch(f"/v1/product/group/{page_id}/sequence", {"ids": product_ids})
    elif target == "activate_page":
        _api_patch("/v1/product-group/status", {"id": page_id, "status": "ACTIVE"})
    elif target == "activate_main":
        _api_patch(f"/v1/masters/{master_id}/main-product-group", {
            "productGroupType": "US_PLUS",
            "productGroupViewStatus": "ACTIVE",
            "isProductGroupWebLinkStatus": "INACTIVE",
            "isProductGroupAppLinkStatus": "INACTIVE",
        })

    # 다시 현황 확인
    return {"collected": collected, "phase": "do_activate"}


def verification_node(state: AgentState) -> dict:
    """검증."""
    _track_phase("verification")
    collected = state.get("collected", {})
    page_id = collected.get("product_page_id", "")
    page_code = collected.get("product_page_code", "")
    checks = []

    page = _api_get(f"/v1/product-group/{page_id}")
    if isinstance(page, dict) and not page.get("error"):
        status = page.get("status", "UNKNOWN")
        checks.append(f"{'✅' if status == 'ACTIVE' else '❌'} 상품 페이지: {_status_label(status)}")

    products = _api_get(f"/v1/product/group/{page_id}")
    if isinstance(products, list):
        visible = [p for p in products if p.get("isDisplay")]
        checks.append(f"{'✅' if visible else '❌'} 노출 중인 옵션: {len(visible)}개")

    buttons = []
    if page_id:
        buttons.append({"type": "navigate", "label": "⚠️ 유의사항 등록", "url": f"/product/page/{page_id}?tab=caution", "variant": "secondary", "description": "유의사항을 등록합니다."})
    if page_code:
        buttons.append({"type": "navigate", "label": "🌐 고객 화면 확인", "url": f"https://dev.us-insight.com/products/group/{page_code}", "variant": "secondary", "description": "고객에게 보이는 화면을 확인합니다."})

    return _response(
        collected, "verification",
        f"🎉 **검증 결과:**\n\n" + "\n\n".join(checks) + "\n\n**체크리스트:**\n\n☐ 금액/구성 확인\n\n☐ 프로모션 확인\n\n☐ 유의사항 등록\n\n☐ 마스터 공개 상태 확인",
        buttons=buttons, mode="execute",
    )


def diagnose_node(state: AgentState) -> dict:
    """진단 모드."""
    _track_phase("diagnose")
    collected = state.get("collected", {})
    master_name = collected.get("_requested_master") or collected.get("master_name", "")

    if not master_name:
        answer = interrupt({
            "message": "어떤 마스터의 상품을 진단할까요? 마스터명을 알려주세요.",
            "buttons": [],
            "mode": "diagnose",
            "step": _step_meta("check_master"),
        })
        master_name = str(answer)
        collected = {**collected, "_requested_master": master_name}

    cms_id = collected.get("master_cms_id", "")
    checks = []

    # 1. 마스터 존재/공개 상태
    if not cms_id:
        result = _api_get("/v1/masters", {"searchKeyword": master_name, "searchCategory": "NAME"})
        print(f"🔍 [diagnose] search_masters('{master_name}') → type={type(result).__name__}, value={str(result)[:300]}")
        if isinstance(result, dict) and result.get("error"):
            return _response(collected, "idle", f"API 오류: {result.get('guide', result.get('response_body', '알 수 없는 오류')[:200])}", mode="diagnose")
        if isinstance(result, list) and len(result) > 0:
            master = result[0]
            cms_id = master.get("cmsId", "")
            collected["master_cms_id"] = cms_id
            collected["master_name"] = master.get("name", "")
            collected["master_public_type"] = master.get("publicType", "")

    if not cms_id:
        return _response(collected, "idle", f"'{master_name}' 마스터를 찾을 수 없습니다.", mode="diagnose")

    public_type = collected.get("master_public_type", "")
    is_public = public_type == "PUBLIC"
    checks.append(f"{'✅' if is_public else '❌'} 마스터 공개 상태: {_status_label(public_type)}")

    # 2. 메인 상품 페이지
    main_product = _api_get(f"/v1/masters/{cms_id}/main-product-group")
    main_active = False
    if isinstance(main_product, dict) and not main_product.get("error"):
        view_status = main_product.get("productGroupViewStatus", "")
        main_active = view_status == "ACTIVE"
        checks.append(f"{'✅' if main_active else '❌'} 메인 상품 페이지: {_status_label(view_status)}")
    else:
        checks.append("❌ 메인 상품 페이지: 설정 안 됨")

    # 3. 상품 페이지
    pages = _api_get("/v1/product-group", {"masterId": cms_id})
    page_active = False
    page_id = ""
    active_pages = []
    if isinstance(pages, list) and len(pages) > 0:
        active_pages = [p for p in pages if p.get("status") == "ACTIVE"]
        page_active = len(active_pages) > 0
        if active_pages:
            page_id = active_pages[0].get("id", "")
        checks.append(f"{'✅' if page_active else '❌'} 상품 페이지: {len(active_pages)}개 공개 / {len(pages)}개 전체")
        showing = _find_active_page(active_pages)
        if showing:
            checks.append(f"🔴 실제 노출 중: **{showing.get('title', '')}** (코드: {showing.get('code', '')})")
            page_id = showing.get("id", "")
    else:
        checks.append("❌ 상품 페이지: 없음")

    # 4. 공개 기간
    if page_active and active_pages:
        p = _find_active_page(active_pages) or active_pages[0]
        if p.get("isAlwaysPublic"):
            checks.append("✅ 공개 기간: 상시")
        else:
            checks.append(f"⚠️ 공개 기간: {p.get('startAt', '?')} ~ {p.get('endAt', '?')}")

    # 5. 상품 옵션 노출
    if page_id:
        products = _api_get(f"/v1/product/group/{page_id}")
        if isinstance(products, list):
            visible = [p for p in products if p.get("isDisplay")]
            checks.append(f"{'✅' if visible else '❌'} 노출 중인 옵션: {len(visible)}개 / {len(products)}개 전체")

    # 원인
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

    cause_text = f"\n\n🎯 **원인**: " + ", ".join(causes) if causes else ""

    return _response(
        collected, "idle",
        f"📊 **{collected.get('master_name', master_name)} 진단 결과**\n\n" + "\n\n".join(checks) + cause_text,
        buttons=buttons, mode="diagnose",
    )


def list_pages_node(state: AgentState) -> dict:
    """상품 페이지 목록 조회."""
    collected = state.get("collected", {})

    if not collected.get("master_cms_id"):
        name = collected.get("_requested_master", "")
        if name:
            result = _api_get("/v1/masters", {"searchKeyword": name, "searchCategory": "NAME"})
            if isinstance(result, list) and len(result) > 0:
                master = result[0]
                collected["master_cms_id"] = master.get("cmsId", "")
                collected["master_name"] = master.get("name", "")
        if not collected.get("master_cms_id"):
            return _response(collected, "check_master", "마스터를 먼저 알려주세요.")

    cms_id = collected["master_cms_id"]
    pages = _api_get("/v1/product-group", {"masterId": cms_id})
    if not isinstance(pages, list) or len(pages) == 0:
        return _response(collected, "guide_create_page", f"**{collected.get('master_name', '')}** 마스터에 상품 페이지가 없습니다.")

    all_active = [p for p in pages if p.get("status") == "ACTIVE"]
    showing = _find_active_page(all_active)
    showing_code = str(showing.get("code", "")) if showing else ""

    rows = "\n".join(
        f"- {'🔴 ' if str(p.get('code', '')) == showing_code else ''}"
        f"**{p.get('title', '')}** (코드: {p.get('code', '')}, {_status_label(p.get('status', ''))})"
        f"{' ← 현재 노출 중' if str(p.get('code', '')) == showing_code else ''}"
        for p in pages
    )
    showing_text = f"\n\n🔴 **현재 노출 중**: {showing.get('title', '')} (코드: {showing.get('code', '')})" if showing else "\n\n⚠️ 현재 노출 중인 페이지 없음"

    return _response(
        collected, "guide_create_page",
        f"**{collected.get('master_name', '')}** 상품 페이지 **{len(pages)}개**:\n{rows}{showing_text}",
    )


def list_options_node(state: AgentState) -> dict:
    """상품 옵션 목록 조회."""
    collected = state.get("collected", {})
    page_id = collected.get("product_page_id", "")
    if not page_id:
        return _response(collected, "guide_create_page", "상품 페이지를 먼저 선택해주세요.")

    products = _api_get(f"/v1/product/group/{page_id}")
    if not isinstance(products, list) or len(products) == 0:
        return _response(collected, "guide_create_option", "등록된 상품 옵션이 없습니다.")

    rows = "\n".join(
        f"- **{p.get('name', '')}** ({p.get('originPrice', 0):,}원, {'공개' if p.get('isDisplay') else '비공개'})"
        for p in products
    )
    return _response(collected, "guide_create_option", f"상품 옵션 **{len(products)}개**:\n{rows}")


def toggle_display_node(state: AgentState) -> dict:
    """상품 옵션 공개/비공개 확인."""
    collected = state.get("collected", {})
    # TODO: 구현 필요시 추가
    return _response(collected, "idle", "상품 옵션 상태 변경은 관리자센터에서 직접 변경해주세요.")


def toggle_page_node(state: AgentState) -> dict:
    """상품 페이지 공개/비공개 확인."""
    collected = state.get("collected", {})
    return _response(collected, "idle", "상품 페이지 상태 변경은 관리자센터에서 직접 변경해주세요.")


def edit_node(state: AgentState) -> dict:
    """수정 안내 — 관리자센터 페이지로 이동."""
    collected = state.get("collected", {})
    llm_message = state.get("response_message", "")
    target = collected.get("_edit_target", "option")
    page_id = collected.get("product_page_id", "")
    master_id = collected.get("master_cms_id", "")
    master_name = collected.get("master_name", "")
    page_title = collected.get("product_page_title", "")

    # 마스터 먼저 확인
    if not master_id:
        name = collected.get("_requested_master", "")
        if name:
            result = _api_get("/v1/masters", {"searchKeyword": name, "searchCategory": "NAME"})
            if isinstance(result, list) and len(result) > 0:
                master = result[0]
                collected["master_cms_id"] = master.get("cmsId", "")
                collected["master_name"] = master.get("name", "")
                master_id = collected["master_cms_id"]
                master_name = collected["master_name"]

    # 페이지 확인
    if not page_id and master_id:
        pages = _api_get("/v1/product-group", {"masterId": master_id})
        if isinstance(pages, list) and len(pages) > 0:
            # page_code로 매칭 시도
            page_code = collected.get("_requested_page_code", "")
            matched = None
            if page_code:
                matched = next((p for p in pages if str(p.get("code", "")) == str(page_code)), None)
            if not matched and len(pages) == 1:
                matched = pages[0]
            if matched:
                page_id = matched.get("id", "")
                collected["product_page_id"] = page_id
                collected["product_page_code"] = matched.get("code", "")
                collected["product_page_title"] = matched.get("title", "")
                page_title = collected["product_page_title"]

    buttons = []
    msg = llm_message or f"**{master_name}** 수정 안내"

    if page_id:
        if target in ("option", "options"):
            buttons.append({"type": "navigate", "label": "📦 상품 옵션 관리", "url": f"/product/page/{page_id}?masterId={master_id}&tab=options", "variant": "primary", "description": "상품 옵션을 수정하거나 새 옵션을 등록합니다."})
        if target in ("page", "settings"):
            buttons.append({"type": "navigate", "label": "📄 상품 페이지 설정", "url": f"/product/page/{page_id}?masterId={master_id}&tab=settings", "variant": "primary", "description": "페이지 정보, 이미지 등을 수정합니다."})
        if not buttons:
            # target 불명확 → 둘 다 제공
            buttons = [
                {"type": "navigate", "label": "📄 상품 페이지 설정", "url": f"/product/page/{page_id}?masterId={master_id}&tab=settings", "variant": "primary", "description": "페이지 정보, 이미지 등을 수정합니다."},
                {"type": "navigate", "label": "📦 상품 옵션 관리", "url": f"/product/page/{page_id}?masterId={master_id}&tab=options", "variant": "primary", "description": "기존 옵션을 수정하거나 새 옵션을 등록합니다."},
            ]
    elif master_id:
        # 페이지 목록에서 선택하게
        pages = _api_get("/v1/product-group", {"masterId": master_id})
        if isinstance(pages, list) and len(pages) > 0:
            rows = "\n".join(f"- **{p.get('title', '')}** (코드: {p.get('code', '')})" for p in pages)
            msg += f"\n\n어떤 페이지를 수정하시겠어요?\n{rows}"
    else:
        msg += "\n\n마스터명을 알려주세요."

    return _response(collected, "idle", msg, buttons=buttons)


def chat_node(state: AgentState) -> dict:
    """일반 대화 — LLM 메시지 그대로 반환."""
    collected = state.get("collected", {})
    msg = state.get("response_message", "")
    if not msg:
        msg = "무엇을 도와드릴까요?"
    return _response(collected, "idle", msg)


def format_response_node(state: AgentState) -> dict:
    """LLM으로 결과 포맷. (현재는 passthrough)"""
    return {}


# ── 헬퍼 ──

def _response(collected: dict, phase: str, message: str,
              buttons: list[dict] | None = None, mode: str = "guide",
              step: dict | None = None) -> dict:
    """응답 dict를 구성."""
    if step is None and phase in STATE_TO_STEP:
        step = _step_meta(phase)
    return {
        "collected": collected,
        "phase": phase,
        "response_message": message,
        "response_buttons": buttons or [],
        "response_mode": mode,
        "response_step": step,
    }


# ══════════════════════════════════════
# 그래프 라우터 (conditional edges)
# ══════════════════════════════════════

def route_after_resolve(state: AgentState) -> str:
    """resolve 노드 결과에 따라 다음 노드로 라우팅."""
    phase = state.get("phase", "idle")
    phase_to_node = {
        "check_master": "check_master",
        "check_series": "check_series",
        "guide_create_page": "guide_create_page",
        "guide_create_option": "guide_create_option",
        "handle_confirm": "handle_confirm",
        "confirm_activate": "confirm_activate",
        "do_activate": "do_activate",
        "do_activate_step": "do_activate_step",
        "verification": "verification",
        "diagnose": "diagnose",
        "list_pages": "list_pages",
        "list_options": "list_options",
        "toggle_display": "toggle_display",
        "toggle_page": "toggle_page",
        "toggle_display_exec": "toggle_display",
        "toggle_page_exec": "toggle_page",
        "edit": "edit",
        "chat": "chat",
    }
    return phase_to_node.get(phase, "chat")


def route_after_execution(state: AgentState) -> str:
    """실행 노드 후 다음으로 라우팅. phase가 변경되었으면 해당 노드로."""
    phase = state.get("phase", "idle")

    # 노드가 다음 phase를 지정한 경우
    if phase in ("check_master", "check_series", "guide_create_page", "guide_create_option",
                 "handle_confirm", "confirm_activate", "do_activate", "do_activate_step",
                 "verification", "diagnose"):
        return phase

    return END


# ══════════════════════════════════════
# 그래프 빌드
# ══════════════════════════════════════

def build_graph(guardrail_config: dict | None = None) -> StateGraph:
    """상품 세팅 에이전트 그래프를 빌드합니다."""

    graph = StateGraph(AgentState)

    # 노드 등록
    graph.add_node("classify", classify_node)
    graph.add_node("resolve", resolve_node)
    graph.add_node("check_master", check_master_node)
    graph.add_node("check_series", check_series_node)
    graph.add_node("guide_create_page", guide_create_page_node)
    graph.add_node("guide_create_option", guide_create_option_node)
    graph.add_node("handle_confirm", handle_confirm_node)
    graph.add_node("confirm_activate", confirm_activate_node)
    graph.add_node("do_activate", do_activate_node)
    graph.add_node("do_activate_step", do_activate_step_node)
    graph.add_node("verification", verification_node)
    graph.add_node("diagnose", diagnose_node)
    graph.add_node("list_pages", list_pages_node)
    graph.add_node("list_options", list_options_node)
    graph.add_node("toggle_display", toggle_display_node)
    graph.add_node("toggle_page", toggle_page_node)
    graph.add_node("edit", edit_node)
    graph.add_node("chat", chat_node)

    # 엣지
    graph.add_edge(START, "classify")
    graph.add_edge("classify", "resolve")

    # resolve → 조건부 라우팅
    graph.add_conditional_edges("resolve", route_after_resolve)

    # 실행 노드들 → 조건부 라우팅 (다음 phase 체인)
    for node_name in ["check_master", "check_series", "guide_create_page",
                      "guide_create_option", "handle_confirm", "confirm_activate",
                      "do_activate", "do_activate_step"]:
        graph.add_conditional_edges(node_name, route_after_execution)

    # 종료 노드들
    graph.add_edge("verification", END)
    graph.add_edge("diagnose", END)
    graph.add_edge("list_pages", END)
    graph.add_edge("list_options", END)
    graph.add_edge("toggle_display", END)
    graph.add_edge("toggle_page", END)
    graph.add_edge("edit", END)
    graph.add_edge("chat", END)

    return graph


def create_app(guardrail_config: dict | None = None):
    """컴파일된 그래프 앱을 생성합니다."""
    graph = build_graph(guardrail_config)
    checkpointer = MemorySaver()
    return graph.compile(checkpointer=checkpointer)
