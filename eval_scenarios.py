"""
에이전트 평가 시나리오.
mock 모드로 여러 시나리오를 실행하고 Langfuse에 trace를 쌓은 뒤,
strands-evals로 Tool 호출 순서/파라미터를 자동 평가.

Usage:
    MOCK_MODE=true uv run python eval_scenarios.py
"""

from dotenv import load_dotenv

load_dotenv()

import os
import json

# OTEL 초기화 (Langfuse 연결)
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry import trace

LANGFUSE_HOST = os.environ.get("LANGFUSE_HOST", "")
exporter = OTLPSpanExporter(
    endpoint=f"{LANGFUSE_HOST}/api/public/otel/v1/traces",
    headers={
        "x-langfuse-public-key": os.environ.get("LANGFUSE_PUBLIC_KEY", ""),
        "x-langfuse-secret-key": os.environ.get("LANGFUSE_SECRET_KEY", ""),
    },
)
provider = TracerProvider()
provider.add_span_processor(SimpleSpanProcessor(exporter))
trace.set_tracer_provider(provider)

from src.agent.product_agent import create_product_agent


# ──────────────────────────────────────────────
# 시나리오 정의
# ──────────────────────────────────────────────

SCENARIOS = [
    {
        "name": "구독상품 전체 세팅",
        "session_id": "eval-subscription-full",
        "messages": [
            "김영익 마스터로 구독상품 세팅해줘. 상품명은 '월간 투자 리포트', 금액 29900원, 1개월 결제주기, 시리즈는 있는거 다 포함해줘. 상품 구성은 '투자 기초 시리즈 이용권'으로.",
        ],
        "expected_tools": [
            "search_masters",
            "get_master_groups",
            "get_series_list",
            "get_product_page_list",
            "create_product_page",
            "get_product_page_list",
            "create_product",
        ],
    },
    {
        "name": "마스터 단순 조회",
        "session_id": "eval-master-lookup",
        "messages": [
            "김영익 마스터 있는지 확인해줘",
        ],
        "expected_tools": [
            "search_masters",
            "get_master_groups",
        ],
    },
    {
        "name": "없는 마스터 검색",
        "session_id": "eval-master-not-found",
        "messages": [
            "아무개 마스터 있어?",
        ],
        "expected_tools": [
            "search_masters",
            "get_master_groups",
        ],
    },
]


# ──────────────────────────────────────────────
# 시나리오 실행 + 결과 수집
# ──────────────────────────────────────────────

def run_scenario(scenario: dict) -> dict:
    """시나리오를 실행하고 결과를 반환."""
    print(f"\n{'='*60}")
    print(f"시나리오: {scenario['name']}")
    print(f"{'='*60}")

    agent, guard = create_product_agent(session_id=scenario["session_id"])

    results = []
    for msg in scenario["messages"]:
        print(f"\n>> {msg}")
        try:
            response = agent(msg)
            results.append({
                "input": msg,
                "output": str(response),
                "phase": guard.current_phase,
                "collected_data": dict(guard.collected_data),
                "tool_history": list(guard.tool_history),
                "error": None,
            })
        except Exception as e:
            results.append({
                "input": msg,
                "output": None,
                "error": str(e),
            })
            print(f"에러: {e}")

    return {
        "scenario": scenario["name"],
        "results": results,
        "final_phase": guard.current_phase,
        "collected_data": dict(guard.collected_data),
        "tool_history": guard.tool_history,
        "actual_tools": [t["tool"] for t in guard.tool_history if "tool" in t],
        "expected_tools": scenario["expected_tools"],
    }


def evaluate_result(result: dict) -> dict:
    """결과를 평가."""
    actual = result["actual_tools"]
    expected = result["expected_tools"]

    # 1. 순서 일치 (in-order match)
    in_order = True
    expected_idx = 0
    for tool in actual:
        if expected_idx < len(expected) and tool == expected[expected_idx]:
            expected_idx += 1
    in_order_score = expected_idx / len(expected) if expected else 1.0

    # 2. 전체 포함 (all expected tools were called)
    coverage = sum(1 for t in expected if t in actual) / len(expected) if expected else 1.0

    # 3. 불필요한 호출 (actual에는 있지만 expected에 없는 것)
    unnecessary = [t for t in actual if t not in expected]
    efficiency = 1.0 - (len(unnecessary) / max(len(actual), 1))

    # 4. cmsId 사용 여부 확인
    cms_id_used = "master_cms_id" in result.get("collected_data", {})

    return {
        "scenario": result["scenario"],
        "in_order_score": round(in_order_score, 2),
        "coverage_score": round(coverage, 2),
        "efficiency_score": round(max(efficiency, 0), 2),
        "cms_id_used": cms_id_used,
        "actual_tools": actual,
        "expected_tools": expected,
        "unnecessary_tools": unnecessary,
        "final_phase": result["final_phase"],
        "tool_call_count": len(actual),
    }


def main():
    # Mock 모드 확인
    if os.environ.get("MOCK_MODE", "").lower() not in ("true", "1", "yes"):
        print("⚠️  MOCK_MODE가 꺼져 있습니다. 실제 API가 호출됩니다!")
        confirm = input("계속할까요? (y/N): ")
        if confirm.lower() != "y":
            return

    print("🚀 에이전트 평가 시나리오 실행")
    print(f"📊 Langfuse에서 trace 확인: {os.environ.get('LANGFUSE_HOST', '')}")

    all_results = []
    all_evals = []

    for scenario in SCENARIOS:
        result = run_scenario(scenario)
        all_results.append(result)

        evaluation = evaluate_result(result)
        all_evals.append(evaluation)

    # 결과 출력
    print(f"\n\n{'='*60}")
    print("📊 평가 결과")
    print(f"{'='*60}\n")

    for ev in all_evals:
        print(f"■ {ev['scenario']}")
        print(f"  순서 일치: {ev['in_order_score']}")
        print(f"  커버리지: {ev['coverage_score']}")
        print(f"  효율성:   {ev['efficiency_score']}")
        print(f"  cmsId:   {'✅' if ev['cms_id_used'] else '❌'}")
        print(f"  Phase:   {ev['final_phase']}")
        print(f"  호출 수:  {ev['tool_call_count']}회")
        if ev['unnecessary_tools']:
            print(f"  불필요:   {ev['unnecessary_tools']}")
        print()

    # 종합 점수
    avg_order = sum(e["in_order_score"] for e in all_evals) / len(all_evals)
    avg_coverage = sum(e["coverage_score"] for e in all_evals) / len(all_evals)
    avg_efficiency = sum(e["efficiency_score"] for e in all_evals) / len(all_evals)

    print(f"{'─'*40}")
    print(f"종합 순서 일치:  {avg_order:.2f}")
    print(f"종합 커버리지:   {avg_coverage:.2f}")
    print(f"종합 효율성:     {avg_efficiency:.2f}")

    # JSON 저장
    with open("eval_results.json", "w") as f:
        json.dump({"results": all_results, "evaluations": all_evals}, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n💾 결과 저장: eval_results.json")


if __name__ == "__main__":
    main()
