"""
도메인 로더 단위 테스트.

YAML 로드, 표현식 평가, 템플릿 치환을 테스트한다.
"""

import pytest
from src.domain_loader import (
    load_yaml,
    evaluate_check,
    evaluate_condition,
    format_template,
    get_action_def,
    get_chain,
    get_launch_checks,
    _resolve_path,
    _parse_value,
    clear_cache,
)


# ── YAML 로드 ──


class TestLoadYaml:
    def test_visibility_chain_loads(self):
        data = load_yaml("domain/visibility_chain.yaml")
        assert "chains" in data
        assert "product_visible" in data["chains"]

    def test_launch_check_loads(self):
        data = load_yaml("domain/launch_check.yaml")
        assert "checks" in data
        assert len(data["checks"]) == 7

    def test_registry_loads(self):
        data = load_yaml("actions/registry.yaml")
        assert "actions" in data
        assert "update_product_display" in data["actions"]

    def test_get_action_def(self):
        action = get_action_def("update_product_display")
        assert action is not None
        assert action["label"] == "상품 공개/비공개"
        assert "product_id" in action["required_slots"]

    def test_get_action_def_unknown(self):
        assert get_action_def("unknown_action") is None

    def test_get_chain(self):
        chain = get_chain("product_visible")
        assert chain is not None
        assert chain["label"] == "상품 노출"
        assert len(chain["requires"]) == 5

    def test_get_chain_unknown(self):
        assert get_chain("unknown_chain") is None

    def test_get_launch_checks(self):
        checks = get_launch_checks()
        assert len(checks) == 7
        assert checks[0]["id"] == "LC1"


# ── 값 접근 ──


class TestResolvePath:
    def test_simple(self):
        assert _resolve_path({"a": 1}, "a") == 1

    def test_nested(self):
        assert _resolve_path({"a": {"b": {"c": 3}}}, "a.b.c") == 3

    def test_missing(self):
        assert _resolve_path({"a": 1}, "b") is None

    def test_nested_missing(self):
        assert _resolve_path({"a": {"b": 1}}, "a.c") is None

    def test_non_dict(self):
        assert _resolve_path({"a": "string"}, "a.b") is None


class TestParseValue:
    def test_true(self):
        assert _parse_value("true") is True

    def test_false(self):
        assert _parse_value("false") is False

    def test_null(self):
        assert _parse_value("null") is None

    def test_quoted_string(self):
        assert _parse_value("'PUBLIC'") == "PUBLIC"

    def test_double_quoted(self):
        assert _parse_value('"ACTIVE"') == "ACTIVE"

    def test_int(self):
        assert _parse_value("42") == 42

    def test_float(self):
        assert _parse_value("3.14") == 3.14

    def test_bare_string(self):
        assert _parse_value("UNKNOWN") == "UNKNOWN"


# ── 표현식 평가 ──


class TestEvaluateCheck:
    def test_equal_string(self):
        ctx = {"master": {"clubPublicType": "PUBLIC"}}
        assert evaluate_check("master.clubPublicType == 'PUBLIC'", ctx) is True

    def test_not_equal_string(self):
        ctx = {"master": {"clubPublicType": "PUBLIC"}}
        assert evaluate_check("master.clubPublicType != 'PUBLIC'", ctx) is False

    def test_equal_bool_true(self):
        ctx = {"product": {"isDisplay": True}}
        assert evaluate_check("product.isDisplay == true", ctx) is True

    def test_equal_bool_false(self):
        ctx = {"is_display": False}
        assert evaluate_check("is_display == false", ctx) is True

    def test_equal_int(self):
        ctx = {"page": {"displayedProductCount": 1}}
        assert evaluate_check("page.displayedProductCount == 1", ctx) is True

    def test_greater_than(self):
        ctx = {"series": {"count": 3}}
        assert evaluate_check("series.count > 0", ctx) is True

    def test_slot_reference(self):
        ctx = {"product": {"isDisplay": True}, "is_display": False}
        assert evaluate_check("product.isDisplay != {is_display}", ctx) is True

    def test_slot_reference_same(self):
        ctx = {"product": {"isDisplay": False}, "is_display": False}
        assert evaluate_check("product.isDisplay != {is_display}", ctx) is False

    def test_missing_field(self):
        ctx = {"a": 1}
        assert evaluate_check("b.c == 'X'", ctx) is False

    def test_invalid_expression(self):
        assert evaluate_check("not a valid expression", {}) is False


# ── 복합 조건 ──


class TestEvaluateCondition:
    def test_and_both_true(self):
        ctx = {"is_display": False, "page": {"displayedProductCount": 1}}
        assert evaluate_condition(
            "is_display == false AND page.displayedProductCount == 1", ctx
        ) is True

    def test_and_one_false(self):
        ctx = {"is_display": True, "page": {"displayedProductCount": 1}}
        assert evaluate_condition(
            "is_display == false AND page.displayedProductCount == 1", ctx
        ) is False

    def test_or_one_true(self):
        ctx = {"a": 1, "b": 2}
        assert evaluate_condition("a == 1 OR b == 99", ctx) is True

    def test_or_both_false(self):
        ctx = {"a": 1, "b": 2}
        assert evaluate_condition("a == 99 OR b == 99", ctx) is False

    def test_single_expression(self):
        ctx = {"status": "ACTIVE"}
        assert evaluate_condition("status == 'ACTIVE'", ctx) is True


# ── 템플릿 치환 ──


class TestFormatTemplate:
    def test_simple(self):
        ctx = {"master_name": "조조형우", "page_title": "월간 투자"}
        assert format_template("대상: {master_name} > {page_title}", ctx) == "대상: 조조형우 > 월간 투자"

    def test_nested(self):
        ctx = {"master": {"clubPublicType": "PRIVATE"}}
        assert format_template("상태: {master.clubPublicType}", ctx) == "상태: PRIVATE"

    def test_missing_keeps_original(self):
        ctx = {"a": 1}
        assert format_template("{a} and {b}", ctx) == "1 and {b}"
