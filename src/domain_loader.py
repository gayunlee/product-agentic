"""
도메인 규칙 로더 — YAML 로드 + 표현식 평가.

visibility_chain.yaml, launch_check.yaml, registry.yaml을 로드하고,
check 표현식을 평가하는 단순 DSL 엔진.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml


# ── YAML 로더 ──

_CACHE: dict[str, Any] = {}


def load_yaml(path: str | Path) -> dict:
    """YAML 파일을 로드. 캐시 사용."""
    key = str(path)
    if key not in _CACHE:
        p = Path(path)
        if not p.is_absolute():
            # 프로젝트 루트 기준
            p = Path(__file__).parent.parent / p
        _CACHE[key] = yaml.safe_load(p.read_text(encoding="utf-8"))
    return _CACHE[key]


def reload_yaml(path: str | Path) -> dict:
    """캐시 무시하고 YAML 다시 로드."""
    key = str(path)
    _CACHE.pop(key, None)
    return load_yaml(path)


def clear_cache():
    """캐시 전체 초기화."""
    _CACHE.clear()


# ── 값 접근 ──

def _resolve_path(obj: Any, path: str) -> Any:
    """점(.) 표기법으로 중첩 dict 값 접근.

    예: _resolve_path({"master": {"clubPublicType": "PUBLIC"}}, "master.clubPublicType")
        → "PUBLIC"
    """
    parts = path.split(".")
    current = obj
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _parse_value(raw: str) -> Any:
    """문자열 값을 Python 타입으로 변환."""
    if raw in ("true", "True"):
        return True
    if raw in ("false", "False"):
        return False
    if raw in ("null", "None"):
        return None
    # 따옴표 제거
    if (raw.startswith("'") and raw.endswith("'")) or \
       (raw.startswith('"') and raw.endswith('"')):
        return raw[1:-1]
    # 숫자
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    return raw


# ── 표현식 평가 ──

# 패턴: field.path op 'value' 또는 field.path op {slot_name}
_CHECK_PATTERN = re.compile(
    r'^(.+?)\s*(==|!=|>|<|>=|<=)\s*(.+)$'
)


def evaluate_check(expression: str, context: dict) -> bool:
    """단일 check 표현식을 평가.

    지원 형식:
      field.path == 'VALUE'
      field.path != {slot_name}     — slots에서 값 치환
      field.path == true
      field.path > 0

    Args:
        expression: check 표현식
        context: 데이터 컨텍스트 (API 응답 + slots 병합)

    Returns:
        True/False
    """
    match = _CHECK_PATTERN.match(expression.strip())
    if not match:
        # 패턴 매칭 실패 → False
        return False

    left_path, op, right_raw = match.group(1).strip(), match.group(2), match.group(3).strip()

    # 좌변: context에서 값 조회
    left_value = _resolve_path(context, left_path)

    # 우변: {slot_name} 치환 또는 리터럴 파싱
    if right_raw.startswith("{") and right_raw.endswith("}"):
        slot_name = right_raw[1:-1]
        right_value = _resolve_path(context, slot_name)
    else:
        right_value = _parse_value(right_raw)

    # 비교
    try:
        if op == "==":
            return left_value == right_value
        if op == "!=":
            return left_value != right_value
        if op == ">":
            return left_value > right_value
        if op == "<":
            return left_value < right_value
        if op == ">=":
            return left_value >= right_value
        if op == "<=":
            return left_value <= right_value
    except (TypeError, ValueError):
        return False

    return False


def evaluate_condition(condition: str, context: dict) -> bool:
    """복합 조건 평가 (AND/OR 지원).

    예: "is_display == false AND page.displayedProductCount == 1"
    """
    # OR 분리 (낮은 우선순위)
    if " OR " in condition:
        parts = condition.split(" OR ")
        return any(evaluate_condition(p.strip(), context) for p in parts)

    # AND 분리
    if " AND " in condition:
        parts = condition.split(" AND ")
        return all(evaluate_check(p.strip(), context) for p in parts)

    # 단일 표현식
    return evaluate_check(condition, context)


# ── 템플릿 치환 ──

_TEMPLATE_PATTERN = re.compile(r'\{(\w+(?:\.\w+)*)\}')


def format_template(template: str, context: dict) -> str:
    """템플릿 문자열에서 {field.path} 또는 {slot} 치환.

    예: "대상: {master_name} > {page_title}" → "대상: 조조형우 > 월간 투자 리포트"
    """
    def _replace(m):
        path = m.group(1)
        value = _resolve_path(context, path)
        if value is None:
            return m.group(0)  # 치환 실패 시 원본 유지
        return str(value)

    return _TEMPLATE_PATTERN.sub(_replace, template)


# ── 레지스트리/체인 접근 ──

def get_action_def(action_id: str) -> dict | None:
    """actions/registry.yaml에서 액션 정의를 조회."""
    registry = load_yaml("actions/registry.yaml")
    return registry.get("actions", {}).get(action_id)


def get_chain(chain_id: str) -> dict | None:
    """domain/visibility_chain.yaml에서 체인 정의를 조회."""
    chains = load_yaml("domain/visibility_chain.yaml")
    return chains.get("chains", {}).get(chain_id)


def get_launch_checks() -> list[dict]:
    """domain/launch_check.yaml에서 체크리스트를 조회."""
    data = load_yaml("domain/launch_check.yaml")
    return data.get("checks", [])
