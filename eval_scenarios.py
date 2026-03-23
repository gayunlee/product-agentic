"""
에이전트 평가 시나리오.

LangGraph 기반 에이전트를 mock 모드로 멀티턴 실행하고,
Phase 방문 순서 + API 호출 패턴 + 버튼 유효성을 자동 평가.

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

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from src.agent.graph import create_app, reset_api_log, get_api_log, get_phase_log


# ──────────────────────────────────────────────
# 시나리오 로드
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
    scenario_id = path.stem

    input_match = re.search(r'## 사용자 입력\s*\n+>\s*"(.+?)"', text)
    if not input_match:
        input_match = re.search(r'> 변형 1:\s*"(.+?)"', text)
    if not input_match:
        print(f"  ⚠️ {path.name}: 사용자 입력 파싱 실패")
        return None

    user_input = input_match.group(1)

    # expected_phases 추출 (LangGraph용)
    phases_match = re.search(r'"expected_phases":\s*\[([^\]]*)\]', text)
    expected_phases = []
    if phases_match:
        expected_phases = [t.strip().strip('"').strip("'") for t in phases_match.group(1).split(",") if t.strip()]

    # expected_tools (레거시 호환 + LangGraph)
    tools_match = re.search(r'"expected_tools":\s*\[([^\]]*)\]', text)
    expected_tools = []
    if tools_match:
        expected_tools = [t.strip().strip('"').strip("'") for t in tools_match.group(1).split(",") if t.strip()]

    # forbidden_tools
    forbidden_match = re.search(r'"forbidden_tools":\s*\[([^\]]*)\]', text)
    forbidden_tools = []
    if forbidden_match:
        forbidden_tools = [t.strip().strip('"').strip("'") for t in forbidden_match.group(1).split(",") if t.strip()]

    # max_turns (멀티턴 시나리오)
    turns_match = re.search(r'"max_turns":\s*(\d+)', text)
    max_turns = int(turns_match.group(1)) if turns_match else 8

    # should_complete (플로우가 완주해야 하는지)
    complete_match = re.search(r'"should_complete":\s*(true|false)', text, re.IGNORECASE)
    should_complete = complete_match.group(1).lower() == "true" if complete_match else None

    # expected_final_phase
    final_phase_match = re.search(r'"expected_final_phase":\s*"([^"]+)"', text)
    expected_final_phase = final_phase_match.group(1) if final_phase_match else None

    difficulty_match = re.search(r'\*\*난이도\*\*:\s*(\w+)', text)
    difficulty = difficulty_match.group(1) if difficulty_match else "medium"

    return {
        "name": scenario_id,
        "category": category,
        "session_id": f"eval-{scenario_id}",
        "messages": [user_input],
        "expected_phases": expected_phases,
        "expected_tools": expected_tools,
        "forbidden_tools": forbidden_tools,
        "max_turns": max_turns,
        "should_complete": should_complete,
        "expected_final_phase": expected_final_phase,
        "difficulty": difficulty,
    }


# API path → Tool name 매핑
def _api_calls_to_tools(api_log: list[dict]) -> list[str]:
    """API 호출 로그를 Tool name으로 변환."""
    tools = []
    for call in api_log:
        path = call.get("path", "")
        method = call.get("method", "GET")

        if "/main-product-group" in path:
            tools.append("update_main_product_setting" if method == "PATCH" else "get_master_detail")
        elif "/v1/product-group/status" in path:
            tools.append("update_product_page_status")
        elif "/v1/product/display" in path:
            tools.append("update_product_display")
        elif "/sequence" in path:
            tools.append("update_product_sequence")
        elif "/v1/product/group/" in path:
            tools.append("get_product_list_by_page")
        elif "/v1/product-group/" in path and path.count("/") > 2:
            tools.append("get_product_page_detail")
        elif "/v1/product-group" in path:
            tools.append("update_product_page_status" if method == "PATCH" else "get_product_page_list")
        elif "/v1/masters" in path:
            tools.append("search_masters")
        elif "/with-series" in path:
            tools.append("get_series_list")
        elif "/v1/master-groups" in path:
            tools.append("get_master_groups")
    return tools


# ──────────────────────────────────────────────
# 멀티턴 시나리오 실행
# ──────────────────────────────────────────────

def run_scenario(scenario: dict) -> dict:
    """시나리오를 멀티턴으로 실행. interrupt마다 자동 resume."""
    print(f"\n{'='*60}")
    print(f"🧪 [{scenario['category']}] {scenario['name']}")
    print(f"   입력: \"{scenario['messages'][0][:60]}...\"")
    print(f"{'='*60}")

    graph_app = create_app()
    config = {"configurable": {"thread_id": scenario["session_id"]}}
    reset_api_log()
    max_turns = scenario.get("max_turns", 8)

    # Turn 1: 초기 메시지
    msg = scenario["messages"][0]
    try:
        result = graph_app.invoke({
            "messages": [HumanMessage(content=msg)],
            "collected": {},
            "phase": "idle",
            "action": "",
            "response_message": "",
            "response_buttons": [],
            "response_mode": "idle",
            "response_step": None,
            "context": {},
        }, config)
    except Exception as e:
        print(f"  ❌ Turn 1 에러: {e}")
        return _error_result(scenario, str(e))

    turn_results = [_extract_turn_result(graph_app, config, result, 1)]
    print(f"  Turn 1: phase={turn_results[-1]['phase']}, interrupted={turn_results[-1]['interrupted']}")

    # Auto-resume: interrupt 상태면 "완료했어"로 resume
    for turn_num in range(2, max_turns + 1):
        state = graph_app.get_state(config)
        if not state.tasks:
            break  # 완료

        try:
            result = graph_app.invoke(Command(resume="완료했어"), config)
        except Exception as e:
            print(f"  ❌ Turn {turn_num} 에러: {e}")
            break

        turn_result = _extract_turn_result(graph_app, config, result, turn_num)
        turn_results.append(turn_result)
        print(f"  Turn {turn_num}: phase={turn_result['phase']}, interrupted={turn_result['interrupted']}")

        # 같은 phase에서 3회 연속 interrupt → 무한루프 방지
        if len(turn_results) >= 3:
            last3 = turn_results[-3:]
            if (all(t["interrupted"] for t in last3)
                and last3[0]["phase"] == last3[1]["phase"] == last3[2]["phase"]):
                print(f"  ⚠️ 같은 phase에서 3회 연속 interrupt → 중단")
                break

    # 결과 수집
    api_log = get_api_log()
    phase_log = get_phase_log()
    actual_tools = _api_calls_to_tools(api_log)
    total_turns = len(turn_results)
    completed = not turn_results[-1]["interrupted"] if turn_results else False

    last = turn_results[-1] if turn_results else {}
    last_buttons = last.get("buttons", [])
    collected = last.get("collected_data", {})
    final_phase = last.get("phase", "")

    print(f"  총 {total_turns}턴, completed={completed}")
    print(f"  Phases: {phase_log}")
    print(f"  Tools: {actual_tools}")
    if last_buttons:
        print(f"  Buttons: {[b.get('label', '') for b in last_buttons]}")

    return {
        "scenario": scenario["name"],
        "category": scenario["category"],
        "turn_results": turn_results,
        "total_turns": total_turns,
        "completed": completed,
        "final_phase": final_phase,
        "collected_data": collected,
        "phase_log": phase_log,
        "api_log": api_log,
        "actual_tools": actual_tools,
        "expected_tools": scenario["expected_tools"],
        "expected_phases": scenario.get("expected_phases", []),
        "forbidden_tools": scenario.get("forbidden_tools", []),
        "should_complete": scenario.get("should_complete"),
        "expected_final_phase": scenario.get("expected_final_phase"),
        "buttons": last_buttons,
    }


def _extract_turn_result(graph_app, config, result, turn_num) -> dict:
    """턴 실행 결과 추출."""
    state = graph_app.get_state(config)
    interrupted = bool(state.tasks)

    if interrupted:
        iv = state.tasks[0].interrupts[0].value
        if isinstance(iv, dict):
            return {
                "turn": turn_num,
                "phase": result.get("phase", ""),
                "interrupted": True,
                "message": iv.get("message", "")[:300],
                "buttons": iv.get("buttons", []),
                "mode": iv.get("mode", ""),
                "collected_data": {k: v for k, v in result.get("collected", {}).items() if not k.startswith("_")},
            }
        return {"turn": turn_num, "phase": result.get("phase", ""), "interrupted": True, "message": str(iv)[:300], "buttons": [], "mode": "", "collected_data": {}}

    return {
        "turn": turn_num,
        "phase": result.get("phase", ""),
        "interrupted": False,
        "message": result.get("response_message", "")[:300],
        "buttons": result.get("response_buttons", []),
        "mode": result.get("response_mode", ""),
        "collected_data": {k: v for k, v in result.get("collected", {}).items() if not k.startswith("_")},
    }


def _error_result(scenario, error_msg) -> dict:
    return {
        "scenario": scenario["name"],
        "category": scenario["category"],
        "turn_results": [],
        "total_turns": 0,
        "completed": False,
        "final_phase": "",
        "collected_data": {},
        "phase_log": [],
        "api_log": [],
        "actual_tools": [],
        "expected_tools": scenario["expected_tools"],
        "expected_phases": scenario.get("expected_phases", []),
        "forbidden_tools": scenario.get("forbidden_tools", []),
        "should_complete": scenario.get("should_complete"),
        "expected_final_phase": scenario.get("expected_final_phase"),
        "buttons": [],
        "error": error_msg,
    }


# ──────────────────────────────────────────────
# 평가
# ──────────────────────────────────────────────

def evaluate_result(result: dict) -> dict:
    """결과를 평가."""
    actual_tools = result["actual_tools"]
    expected_tools = result["expected_tools"]
    forbidden = result.get("forbidden_tools", [])
    phase_log = result.get("phase_log", [])
    expected_phases = result.get("expected_phases", [])

    # 1. Phase 순서 일치 (in-order subsequence)
    phase_idx = 0
    for phase in phase_log:
        if phase_idx < len(expected_phases) and phase == expected_phases[phase_idx]:
            phase_idx += 1
    phase_order_score = phase_idx / len(expected_phases) if expected_phases else 1.0

    # 2. Phase 커버리지
    phase_coverage = sum(1 for p in expected_phases if p in phase_log) / len(expected_phases) if expected_phases else 1.0

    # 3. Tool 커버리지 (레거시 호환)
    tool_coverage = sum(1 for t in expected_tools if t in actual_tools) / len(expected_tools) if expected_tools else 1.0

    # 4. 금지 Tool 위반
    violations = [t for t in actual_tools if t in forbidden]
    no_violations = len(violations) == 0

    # 5. 완주 여부
    completed = result.get("completed", False)
    should_complete = result.get("should_complete")
    completion_ok = True
    if should_complete is True and not completed:
        completion_ok = False
    if should_complete is False and completed:
        completion_ok = False  # 중단해야 하는데 완주했으면 문제

    # 6. 최종 phase 체크
    expected_final = result.get("expected_final_phase")
    final_phase_ok = True
    if expected_final and result.get("final_phase") != expected_final:
        final_phase_ok = False

    # 7. cmsId 사용 여부
    cms_id_used = "master_cms_id" in result.get("collected_data", {})

    # 8. buttons 검증
    buttons = result.get("buttons", [])
    buttons_valid = True
    button_issues = []
    for btn in buttons:
        btn_type = btn.get("type", "")
        if btn_type == "navigate" and not btn.get("url"):
            buttons_valid = False
            button_issues.append(f"navigate 버튼 '{btn.get('label', '')}'에 url 없음")
        if btn_type == "action" and not btn.get("actionId") and not btn.get("action"):
            buttons_valid = False
            button_issues.append(f"action 버튼 '{btn.get('label', '')}'에 actionId/action 없음")

    # 종합 pass/fail
    passed = (
        phase_coverage >= 0.8
        and no_violations
        and completion_ok
        and final_phase_ok
    )

    return {
        "scenario": result["scenario"],
        "category": result["category"],
        "passed": passed,
        "phase_order_score": round(phase_order_score, 2),
        "phase_coverage": round(phase_coverage, 2),
        "tool_coverage": round(tool_coverage, 2),
        "no_violations": no_violations,
        "violations": violations,
        "completion_ok": completion_ok,
        "completed": completed,
        "final_phase_ok": final_phase_ok,
        "cms_id_used": cms_id_used,
        "buttons_valid": buttons_valid,
        "button_count": len(buttons),
        "button_issues": button_issues,
        "total_turns": result.get("total_turns", 0),
        "phase_log": phase_log,
        "expected_phases": expected_phases,
        "actual_tools": actual_tools,
        "expected_tools": expected_tools,
        "final_phase": result.get("final_phase", ""),
        "expected_final_phase": expected_final,
    }


def main():
    if os.environ.get("MOCK_MODE", "").lower() not in ("true", "1", "yes"):
        print("⚠️  MOCK_MODE가 꺼져 있습니다. 실제 API가 호출됩니다!")
        confirm = input("계속할까요? (y/N): ")
        if confirm.lower() != "y":
            return

    filter_id = None
    if "--scenario" in sys.argv:
        idx = sys.argv.index("--scenario")
        if idx + 1 < len(sys.argv):
            filter_id = sys.argv[idx + 1]

    scenarios = load_scenarios_from_files()
    if not scenarios:
        print("❌ scenarios/ 폴더에 시나리오가 없습니다.")
        return

    if filter_id:
        scenarios = [s for s in scenarios if filter_id in s["name"]]
        if not scenarios:
            print(f"❌ '{filter_id}' 시나리오를 찾을 수 없습니다.")
            return

    print(f"🚀 에이전트 평가 시나리오 실행 ({len(scenarios)}개, 멀티턴)")
    print(f"📊 Langfuse: {LANGFUSE_HOST}")

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
    print(f"\n⏱️ 전체 소요: {elapsed:.1f}초")

    all_evals = [evaluate_result(r) for r in all_results]

    # 결과 출력
    print(f"\n\n{'='*60}")
    print(f"📊 평가 결과 ({len(all_evals)}개 시나리오)")
    print(f"{'='*60}\n")

    passed_count = 0
    for ev in sorted(all_evals, key=lambda x: x["scenario"]):
        status = "✅ PASS" if ev["passed"] else "❌ FAIL"
        passed_count += 1 if ev["passed"] else 0

        print(f"{'─'*50}")
        print(f"  {status}  [{ev['category']}] {ev['scenario']}")
        print(f"  Phase순서: {ev['phase_order_score']}  Phase커버: {ev['phase_coverage']}  Tool커버: {ev['tool_coverage']}")
        print(f"  턴: {ev['total_turns']}  완주: {'✅' if ev['completed'] else '⏸️'}  최종: {ev['final_phase']}")
        print(f"  Phases: {ev['phase_log']}")
        if ev["violations"]:
            print(f"  ⛔ 금지 Tool 위반: {ev['violations']}")
        if not ev["completion_ok"]:
            print(f"  ⛔ 완주 기대 불일치")
        if not ev["final_phase_ok"]:
            print(f"  ⛔ 최종 phase 불일치 (기대: {ev['expected_final_phase']})")
        if ev.get("button_count", 0) > 0:
            print(f"  🔘 Buttons: {ev['button_count']}개 {'✅' if ev['buttons_valid'] else '❌'}")
        if ev.get("button_issues"):
            print(f"  ⛔ Button 이슈: {ev['button_issues']}")

    # 종합
    print(f"\n{'='*60}")
    print(f"📋 종합: {passed_count}/{len(all_evals)} PASS")

    if all_evals:
        avg_phase = sum(e["phase_order_score"] for e in all_evals) / len(all_evals)
        avg_coverage = sum(e["phase_coverage"] for e in all_evals) / len(all_evals)
        avg_tool = sum(e["tool_coverage"] for e in all_evals) / len(all_evals)
        print(f"   평균 Phase순서: {avg_phase:.2f}  Phase커버: {avg_coverage:.2f}  Tool커버: {avg_tool:.2f}")

    # JSON 저장
    save_data = {"results": all_results, "evaluations": all_evals}
    for r in save_data["results"]:
        r.pop("api_log", None)
    with open("eval_results.json", "w") as f:
        json.dump(save_data, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n💾 결과 저장: eval_results.json")


if __name__ == "__main__":
    main()
