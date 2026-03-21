"""
에이전트 평가 시나리오.
mock 모드로 여러 시나리오를 실행하고 Langfuse에 trace를 쌓은 뒤,
Tool 호출 순서/파라미터를 자동 평가.

Usage:
    MOCK_MODE=true uv run python eval_scenarios.py
    MOCK_MODE=true uv run python eval_scenarios.py --scenario S001
"""

from dotenv import load_dotenv

load_dotenv()

import os
import sys
import json
import base64
import re
from pathlib import Path

# OTEL 초기화 (Langfuse Basic Auth)
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry import trace

LANGFUSE_HOST = os.environ.get("LANGFUSE_HOST", os.environ.get("LANGFUSE_BASE_URL", "https://us.cloud.langfuse.com")).strip('"')
LANGFUSE_PK = os.environ.get("LANGFUSE_PUBLIC_KEY", "").strip('"')
LANGFUSE_SK = os.environ.get("LANGFUSE_SECRET_KEY", "").strip('"')

if LANGFUSE_PK and LANGFUSE_SK:
    _auth = base64.b64encode(f"{LANGFUSE_PK}:{LANGFUSE_SK}".encode()).decode()
    exporter = OTLPSpanExporter(
        endpoint=f"{LANGFUSE_HOST}/api/public/otel/v1/traces",
        headers={"Authorization": f"Basic {_auth}"},
    )
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    print(f"✅ Langfuse OTEL 연결: {LANGFUSE_HOST}")
else:
    print("⚠️  Langfuse 키 없음. 트레이싱 없이 실행합니다.")

from src.agent.product_agent import create_product_agent
from server import _extract_buttons


# ──────────────────────────────────────────────
# 시나리오 로드 (scenarios/ 폴더에서)
# ──────────────────────────────────────────────

def load_scenarios_from_files() -> list[dict]:
    """scenarios/ 폴더의 .md 파일에서 시나리오를 파싱."""
    scenarios = []
    scenarios_dir = Path(__file__).parent / "scenarios"

    for category_dir in sorted(scenarios_dir.iterdir()):
        if not category_dir.is_dir():
            continue
        for md_file in sorted(category_dir.glob("S*.md")):
            scenario = parse_scenario_file(md_file, category_dir.name)
            if scenario:
                scenarios.append(scenario)

    return scenarios


def parse_scenario_file(path: Path, category: str) -> dict | None:
    """시나리오 .md 파일에서 핵심 정보를 추출."""
    text = path.read_text(encoding="utf-8")

    # 시나리오 ID 추출 (파일명에서)
    scenario_id = path.stem  # S001_구독상품_전체_세팅

    # 사용자 입력 추출
    input_match = re.search(r'## 사용자 입력\s*\n+>\s*"(.+?)"', text)
    if not input_match:
        # 변형이 여러 개인 경우 (S200 탈옥)
        input_match = re.search(r'> 변형 1:\s*"(.+?)"', text)
    if not input_match:
        print(f"  ⚠️ {path.name}: 사용자 입력 파싱 실패")
        return None

    user_input = input_match.group(1)

    # required_tools 추출 (strands-evals Case 블록에서)
    tools_match = re.search(r'"required_tools":\s*\[([^\]]*)\]', text)
    required_tools = []
    if tools_match:
        required_tools = [t.strip().strip('"').strip("'") for t in tools_match.group(1).split(",") if t.strip()]

    # forbidden_tools 추출
    forbidden_match = re.search(r'"forbidden_tools":\s*\[([^\]]*)\]', text)
    forbidden_tools = []
    if forbidden_match:
        forbidden_tools = [t.strip().strip('"').strip("'") for t in forbidden_match.group(1).split(",") if t.strip()]

    # 난이도 추출
    difficulty_match = re.search(r'\*\*난이도\*\*:\s*(\w+)', text)
    difficulty = difficulty_match.group(1) if difficulty_match else "medium"

    return {
        "name": scenario_id,
        "category": category,
        "session_id": f"eval-{scenario_id}",
        "messages": [user_input],
        "expected_tools": required_tools,
        "forbidden_tools": forbidden_tools,
        "difficulty": difficulty,
    }


# ──────────────────────────────────────────────
# 시나리오 실행 + 결과 수집
# ──────────────────────────────────────────────

def run_scenario(scenario: dict) -> dict:
    """시나리오를 실행하고 결과를 반환."""
    print(f"\n{'='*60}")
    print(f"🧪 [{scenario['category']}] {scenario['name']}")
    print(f"   입력: \"{scenario['messages'][0][:60]}...\"")
    print(f"{'='*60}")

    agent, guard = create_product_agent(session_id=scenario["session_id"])

    results = []
    for msg in scenario["messages"]:
        try:
            response = agent(msg)
            results.append({
                "input": msg,
                "output": str(response)[:500],
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
            print(f"  ❌ 에러: {e}")

    actual_tools = [t["tool"] for t in guard.tool_history if "tool" in t]
    print(f"  Tool 호출: {actual_tools}")

    # 사이드패널 buttons 생성 (마지막 응답 기준)
    last_output = results[-1]["output"] if results and results[-1].get("output") else ""
    buttons = _extract_buttons(last_output, guard.current_phase, dict(guard.collected_data))
    button_data = [{"type": b.type, "label": b.label, "url": b.url, "actionId": b.actionId} for b in buttons]
    if button_data:
        print(f"  Buttons: {[b['label'] for b in button_data]}")

    return {
        "scenario": scenario["name"],
        "category": scenario["category"],
        "results": results,
        "final_phase": guard.current_phase,
        "collected_data": dict(guard.collected_data),
        "tool_history": guard.tool_history,
        "actual_tools": actual_tools,
        "expected_tools": scenario["expected_tools"],
        "forbidden_tools": scenario.get("forbidden_tools", []),
        "buttons": button_data,
    }


def evaluate_result(result: dict) -> dict:
    """결과를 평가."""
    actual = result["actual_tools"]
    expected = result["expected_tools"]
    forbidden = result.get("forbidden_tools", [])

    # 1. 순서 일치 (in-order subsequence match)
    expected_idx = 0
    for tool in actual:
        if expected_idx < len(expected) and tool == expected[expected_idx]:
            expected_idx += 1
    in_order_score = expected_idx / len(expected) if expected else 1.0

    # 2. 커버리지 (expected tools 중 실제 호출된 비율)
    coverage = sum(1 for t in expected if t in actual) / len(expected) if expected else 1.0

    # 3. 효율성 (불필요한 호출 비율)
    unnecessary = [t for t in actual if t not in expected]
    efficiency = 1.0 - (len(unnecessary) / max(len(actual), 1))

    # 4. 금지 Tool 위반 여부
    violations = [t for t in actual if t in forbidden]
    no_violations = len(violations) == 0

    # 5. cmsId 사용 여부
    cms_id_used = "master_cms_id" in result.get("collected_data", {})

    # 6. buttons 검증 (사이드패널 시나리오)
    buttons = result.get("buttons", [])
    buttons_valid = True
    button_issues = []
    for btn in buttons:
        if btn["type"] == "navigate" and not btn.get("url"):
            buttons_valid = False
            button_issues.append(f"navigate 버튼 '{btn['label']}'에 url 없음")
        if btn["type"] == "action" and not btn.get("actionId"):
            buttons_valid = False
            button_issues.append(f"action 버튼 '{btn['label']}'에 actionId 없음")
        if btn["type"] == "navigate" and btn.get("url") and not btn["url"].startswith("/") and not btn["url"].startswith("http"):
            buttons_valid = False
            button_issues.append(f"navigate 버튼 '{btn['label']}'의 url이 유효하지 않음: {btn['url']}")

    # 종합 pass/fail
    passed = (
        coverage >= 0.8
        and no_violations
        and (in_order_score >= 0.7 or not expected)
    )

    return {
        "scenario": result["scenario"],
        "category": result["category"],
        "passed": passed,
        "in_order_score": round(in_order_score, 2),
        "coverage_score": round(coverage, 2),
        "efficiency_score": round(max(efficiency, 0), 2),
        "no_violations": no_violations,
        "violations": violations,
        "cms_id_used": cms_id_used,
        "buttons_valid": buttons_valid,
        "button_count": len(buttons),
        "button_issues": button_issues,
        "actual_tools": actual,
        "expected_tools": expected,
        "forbidden_tools": forbidden,
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

    # 특정 시나리오만 실행
    filter_id = None
    if "--scenario" in sys.argv:
        idx = sys.argv.index("--scenario")
        if idx + 1 < len(sys.argv):
            filter_id = sys.argv[idx + 1]

    # 시나리오 로드
    scenarios = load_scenarios_from_files()
    if not scenarios:
        print("❌ scenarios/ 폴더에 시나리오가 없습니다.")
        return

    if filter_id:
        scenarios = [s for s in scenarios if filter_id in s["name"]]
        if not scenarios:
            print(f"❌ '{filter_id}' 시나리오를 찾을 수 없습니다.")
            return

    print(f"🚀 에이전트 평가 시나리오 실행 ({len(scenarios)}개, 병렬)")
    print(f"📊 Langfuse: {LANGFUSE_HOST}")

    # 병렬 실행 (각 시나리오는 독립 에이전트 인스턴스)
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import time

    start = time.time()
    all_results = []
    with ThreadPoolExecutor(max_workers=min(len(scenarios), 5)) as executor:
        futures = {executor.submit(run_scenario, s): s["name"] for s in scenarios}
        for future in as_completed(futures):
            name = futures[future]
            try:
                result = future.result()
                all_results.append(result)
            except Exception as e:
                print(f"  ❌ {name} 실행 실패: {e}")

    elapsed = time.time() - start
    print(f"\n⏱️ 전체 소요: {elapsed:.1f}초 (병렬)")

    all_evals = [evaluate_result(r) for r in all_results]

    # 결과 출력
    print(f"\n\n{'='*60}")
    print(f"📊 평가 결과 ({len(all_evals)}개 시나리오)")
    print(f"{'='*60}\n")

    passed_count = 0
    for ev in all_evals:
        status = "✅ PASS" if ev["passed"] else "❌ FAIL"
        passed_count += 1 if ev["passed"] else 0

        print(f"{'─'*50}")
        print(f"  {status}  [{ev['category']}] {ev['scenario']}")
        print(f"  순서: {ev['in_order_score']}  커버리지: {ev['coverage_score']}  효율: {ev['efficiency_score']}")
        print(f"  Tool: {ev['tool_call_count']}회  Phase: {ev['final_phase']}")
        if ev["violations"]:
            print(f"  ⛔ 금지 Tool 위반: {ev['violations']}")
        if ev["unnecessary_tools"]:
            print(f"  ⚠️  불필요: {ev['unnecessary_tools']}")
        if ev.get("button_count", 0) > 0:
            print(f"  🔘 Buttons: {ev['button_count']}개 {'✅' if ev['buttons_valid'] else '❌'}")
        if ev.get("button_issues"):
            print(f"  ⛔ Button 이슈: {ev['button_issues']}")

    # 종합
    print(f"\n{'='*60}")
    print(f"📋 종합: {passed_count}/{len(all_evals)} PASS")

    if all_evals:
        avg_order = sum(e["in_order_score"] for e in all_evals) / len(all_evals)
        avg_coverage = sum(e["coverage_score"] for e in all_evals) / len(all_evals)
        avg_efficiency = sum(e["efficiency_score"] for e in all_evals) / len(all_evals)
        print(f"   평균 순서: {avg_order:.2f}  커버리지: {avg_coverage:.2f}  효율: {avg_efficiency:.2f}")

    # JSON 저장
    with open("eval_results.json", "w") as f:
        json.dump({"results": all_results, "evaluations": all_evals}, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n💾 결과 저장: eval_results.json")


if __name__ == "__main__":
    main()
