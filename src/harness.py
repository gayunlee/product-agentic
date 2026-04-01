"""
ActionHarness — 모든 쓰기 작업의 게이트.

LLM은 request_action(action_id, slots)만 호출.
Harness가 자동으로:
  1. required_slots 검증
  2. visibility_chain 체크 (도메인 규칙)
  3. prerequisites 체크
  4. cascading 경고 수집
  5. confirmation 메시지 + 버튼 생성 → 유저에게
  6. 유저 [실행] 클릭 → API 호출
  7. post_action 검증 + navigate 버튼
"""

from __future__ import annotations

import json
from typing import Any

from src.domain_loader import (
    load_yaml,
    evaluate_check,
    evaluate_condition,
    format_template,
    get_action_def,
    get_chain,
    _resolve_path,
)
from src.agents.response import AgentResponse, render_response_json


# ── API 함수 매핑 (지연 import) ──

def _get_api_map() -> dict:
    from src.tools.admin_api import (
        update_product_display,
        update_product_page_status,
        update_product_page,
        update_main_product_setting,
    )
    return {
        "update_product_display": update_product_display,
        "update_product_page_status": update_product_page_status,
        "update_product_page": update_product_page,
        "update_main_product_setting": update_main_product_setting,
    }


def _get_read_api_map() -> dict:
    from src.tools.admin_api import (
        get_product_page_list,
        get_product_list_by_page,
    )
    return {
        "get_product_page_list": get_product_page_list,
        "get_product_list_by_page": get_product_list_by_page,
    }


class ActionHarness:
    """모든 상태 변경의 게이트."""

    def __init__(self):
        self.registry = load_yaml("actions/registry.yaml").get("actions", {})
        self.chains = load_yaml("domain/visibility_chain.yaml").get("chains", {})

    def validate_and_confirm(
        self,
        action_id: str,
        slots: dict[str, Any],
        context_data: dict[str, Any] | None = None,
    ) -> str:
        """액션 검증 + 확인 메시지 생성.

        Args:
            action_id: 액션 ID (registry.yaml의 키)
            slots: LLM이 수집한 슬롯 데이터
            context_data: API로 조회한 추가 컨텍스트 (선택)

        Returns:
            render_response_json 형식의 JSON 문자열
        """
        action_def = self.registry.get(action_id)
        if not action_def:
            return self._error(f"알 수 없는 액션: {action_id}")

        # 검증/렌더링용 통합 컨텍스트
        ctx = {**(context_data or {}), **slots}

        # 1. 필수 슬롯 검증 (None만 미충족, False/0은 유효값)
        missing = [s for s in action_def.get("required_slots", []) if slots.get(s) is None]
        if missing:
            # 슬롯 불완전 → 목록 조회해서 선택지 반환 시도
            assist = self._assist_missing_slots(action_id, missing, slots)
            if assist:
                return assist
            return self._error(
                f"정보가 부족합니다: {', '.join(missing)}",
                data={"missing_slots": missing},
            )

        # 2. prerequisites 체크 (데이터가 컨텍스트에 있을 때만 검증)
        for prereq in action_def.get("prerequisites", []):
            check_expr = prereq.get("check", "")
            if not check_expr:
                continue
            # 체크 표현식의 좌변 경로가 컨텍스트에 존재할 때만 검증
            left_path = check_expr.split()[0] if check_expr else ""
            left_value = _resolve_path(ctx, left_path) if left_path else None
            if left_value is None:
                continue  # 데이터 없으면 스킵 (LLM이 이미 조회로 확인)
            if not evaluate_check(check_expr, ctx):
                fail_msg = format_template(prereq.get("fail", "사전조건 미충족"), ctx)
                return self._error(fail_msg)

        # 3. cascading 경고 수집
        warnings = []
        suggest_buttons = []
        for cascade in action_def.get("cascading", []):
            condition = cascade.get("condition", "")
            if condition and evaluate_condition(condition, ctx):
                warning_msg = format_template(cascade.get("message", ""), ctx)
                warnings.append(warning_msg)
                if cascade.get("suggest_action"):
                    suggest_params = {}
                    for k, v in cascade.get("suggest_params", {}).items():
                        suggest_params[k] = format_template(str(v), ctx)
                    suggest_buttons.append({
                        "type": "action",
                        "label": cascade.get("suggest_label", "추가 처리"),
                        "action": "execute_confirmed",
                        "variant": "secondary",
                        "clickable": "once",
                        "payload": {
                            "action_id": cascade["suggest_action"],
                            "slots": suggest_params,
                        },
                    })

        # 4. confirmation 메시지 생성
        label = action_def.get("label", action_id)
        confirm_def = action_def.get("confirmation", {})
        template = confirm_def.get("template", "**{label}**\n대상을 확인해주세요.")

        # 상태 변환 텍스트 추가
        ctx["label"] = label
        ctx.update(self._resolve_state_text(action_id, slots, ctx))

        confirm_msg = format_template(template, ctx)

        if warnings:
            confirm_msg += "\n\n⚠️ **주의:**\n" + "\n".join(f"- {w}" for w in warnings)

        # 5. 버튼 생성
        buttons = [
            {
                "type": "action",
                "label": f"{label} 실행",
                "action": "execute_confirmed",
                "variant": "primary",
                "clickable": "once",
                "payload": {"action_id": action_id, "slots": slots},
            },
            *suggest_buttons,
            {
                "type": "action",
                "label": "취소",
                "action": "cancel",
                "variant": "ghost",
                "clickable": "once",
            },
        ]

        # navigate 버튼 (직접 수정용)
        nav = action_def.get("post_action", {}).get("navigate", {})
        if nav.get("url"):
            nav_url = format_template(nav["url"], ctx)
            buttons.append({
                "type": "navigate",
                "label": "직접 수정",
                "url": nav_url,
                "variant": "secondary",
                "clickable": "always",
            })

        resp = AgentResponse(
            type="confirm",
            summary=confirm_msg,
            data={
                "target": self._build_target(ctx),
                "action_label": label,
                "change": ctx.get("change", {}),
                "warnings": warnings,
            },
        )
        msg, _, mode = _render_confirm(resp, buttons)
        return json.dumps(
            {
                "__agent_response__": True,
                "message": msg,
                "buttons": buttons,
                "mode": "execute",
            },
            ensure_ascii=False,
        )

    def execute_confirmed(
        self,
        action_id: str,
        slots: dict[str, Any],
    ) -> dict:
        """유저가 [실행] 클릭 시 API 실행.

        Returns:
            AgentResponse dict (server.py가 _to_response로 변환)
        """
        action_def = self.registry.get(action_id)
        if not action_def:
            return {"message": f"알 수 없는 액션: {action_id}", "buttons": [], "mode": "error"}

        api_def = action_def.get("api", {})
        fn_name = api_def.get("function", "")
        api_map = _get_api_map()
        api_fn = api_map.get(fn_name)

        if not api_fn:
            return {"message": f"알 수 없는 API: {fn_name}", "buttons": [], "mode": "error"}

        # 파라미터 치환
        params = {}
        for k, v in api_def.get("params", {}).items():
            resolved = format_template(str(v), slots)
            # bool 변환
            if resolved.lower() == "true":
                resolved = True
            elif resolved.lower() == "false":
                resolved = False
            # dict 변환 (updates 파라미터)
            elif isinstance(v, dict):
                resolved = {}
                for dk, dv in v.items():
                    val = format_template(str(dv), slots)
                    if val.lower() == "true":
                        val = True
                    elif val.lower() == "false":
                        val = False
                    resolved[dk] = val
            params[k] = resolved

        # API 실행
        try:
            result = api_fn(**params)
        except Exception as e:
            return {
                "message": f"⚠️ 실행 중 오류: {e}",
                "buttons": [],
                "mode": "error",
            }

        # warning 반환 체크 (admin_api의 계단식 경고)
        if isinstance(result, dict) and result.get("warning"):
            return {
                "message": result.get("message", "경고가 발생했습니다."),
                "buttons": [],
                "mode": "error",
            }

        # 완료 응답
        label = action_def.get("label", action_id)
        nav = action_def.get("post_action", {}).get("navigate", {})
        buttons = []
        if nav.get("url"):
            nav_url = format_template(nav["url"], slots)
            buttons.append({
                "type": "navigate",
                "label": nav.get("label", "결과 확인"),
                "url": nav_url,
                "variant": "primary",
                "clickable": "always",
            })

        return {
            "message": f"✅ **{label} 완료**",
            "buttons": buttons,
            "mode": "done",
        }

    # ── 내부 헬퍼 ──

    def _assist_missing_slots(
        self, action_id: str, missing: list[str], slots: dict
    ) -> str | None:
        """슬롯이 부족할 때 목록을 조회해서 선택 버튼을 반환.

        반환값이 None이면 기존 에러 메시지 사용.
        """
        read_api = _get_read_api_map()
        master_cms_id = slots.get("master_cms_id")

        # page_id가 없고 master_cms_id가 있으면 → 상품페이지 목록 반환
        if "page_id" in missing and master_cms_id:
            try:
                pages = read_api["get_product_page_list"](master_id=str(master_cms_id))
                page_list = pages if isinstance(pages, list) else pages.get("pages", [])
                if not page_list:
                    return None  # 목록이 비어있으면 기존 에러로 fallback
                master_name = slots.get("master_name", "")
                buttons = [
                    {
                        "type": "select",
                        "label": f"{p.get('title', '제목 없음')} ({p.get('status', '')})",
                        "value": str(p.get("id", "")),
                        "variant": "secondary",
                        "clickable": "once",
                    }
                    for p in page_list
                ]
                return json.dumps(
                    {
                        "__agent_response__": True,
                        "message": f"📦 **{master_name}** 오피셜클럽의 상품페이지 {len(page_list)}개입니다.\n어떤 상품페이지를 처리할까요?",
                        "buttons": buttons,
                        "mode": "select",
                    },
                    ensure_ascii=False,
                )
            except Exception:
                return None

        # product_id가 없고 page_id가 있으면 → 상품 목록 반환
        if "product_id" in missing and slots.get("page_id"):
            try:
                products = read_api["get_product_list_by_page"](
                    product_page_id=str(slots["page_id"])
                )
                prod_list = products if isinstance(products, list) else products.get("products", [])
                if not prod_list:
                    return None
                buttons = [
                    {
                        "type": "select",
                        "label": f"{p.get('name', '이름 없음')} ({'공개' if p.get('isDisplay') else '비공개'})",
                        "value": str(p.get("id", "")),
                        "variant": "secondary",
                        "clickable": "once",
                    }
                    for p in prod_list
                ]
                page_title = slots.get("page_title", "")
                return json.dumps(
                    {
                        "__agent_response__": True,
                        "message": f"📦 **{page_title}** 상품페이지의 상품 {len(prod_list)}개입니다.\n어떤 상품을 처리할까요?",
                        "buttons": buttons,
                        "mode": "select",
                    },
                    ensure_ascii=False,
                )
            except Exception:
                return None

        return None

    def _error(self, message: str, data: dict | None = None) -> str:
        resp = AgentResponse(
            type="error",
            summary=message,
            data=data or {"guide": message},
        )
        return render_response_json(resp)

    def _build_target(self, ctx: dict) -> str:
        parts = []
        for key in ("master_name", "page_title", "product_name"):
            if ctx.get(key):
                parts.append(str(ctx[key]))
        return " > ".join(parts) if parts else "대상 미지정"

    def _resolve_state_text(self, action_id: str, slots: dict, ctx: dict) -> dict:
        """상태 변환 텍스트 생성."""
        extra = {}
        if action_id == "update_product_display":
            is_display = slots.get("is_display")
            extra["from_state"] = "비공개" if is_display else "공개"
            extra["to_state"] = "공개" if is_display else "비공개"
            extra["display_status"] = "공개" if is_display else "비공개"
        elif action_id == "update_product_page_status":
            status = slots.get("status", "")
            extra["from_status"] = "INACTIVE" if status == "ACTIVE" else "ACTIVE"
            extra["status"] = status
        elif action_id == "update_product_page_hidden":
            is_hidden = slots.get("is_hidden")
            extra["from_hidden"] = "히든 해제" if is_hidden else "히든"
            extra["to_hidden"] = "히든" if is_hidden else "히든 해제"
            extra["hidden_status"] = "히든" if is_hidden else "히든 해제"
        elif action_id == "update_main_product_setting":
            view_status = slots.get("view_status", "")
            extra["from_status"] = ctx.get("mainProduct", {}).get("productGroupViewStatus", "?")
            extra["view_status"] = view_status
        return extra


def _render_confirm(resp: AgentResponse, buttons: list[dict]) -> tuple[str, list[dict], str]:
    """confirm 응답을 message로 렌더링."""
    parts = ["⚡ 실행 확인"]
    if resp.summary:
        parts.append(resp.summary)
    warnings = resp.data.get("warnings", [])
    if warnings:
        parts.append("⚠️ **주의:**\n" + "\n".join(f"- {w}" for w in warnings))
    return "\n\n".join(parts), buttons, "execute"


# ── 싱글톤 ──

_harness: ActionHarness | None = None


def get_harness() -> ActionHarness:
    """ActionHarness 싱글톤."""
    global _harness
    if _harness is None:
        _harness = ActionHarness()
    return _harness
