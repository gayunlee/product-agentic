"""
오케스트레이터 응답 속도 벤치마크.

동일한 시나리오를 N회 실행하여 응답 시간을 측정.
캐싱/few-shot 도입 전후 비교용.

Usage:
    uv run python benchmarks/response_time.py
    uv run python benchmarks/response_time.py --runs 5
"""

import argparse
import json
import time
import httpx
import statistics

BASE_URL = "http://localhost:8000"

# 벤치마크 시나리오 — 다양한 라우팅 케이스
SCENARIOS = [
    {
        "name": "단순 진단",
        "messages": [
            "조조형우 노출 진단해줘",
        ],
    },
    {
        "name": "개념 질문",
        "messages": [
            "히든 처리가 뭐야?",
        ],
    },
    {
        "name": "맥락 전환 (진단 → 개념)",
        "messages": [
            "조조형우 노출 진단해줘",
            "메인 상품페이지가 뭔데?",
        ],
    },
    {
        "name": "맥락 유지 (진단 → 다른 대상)",
        "messages": [
            "조조형우 노출 진단해줘",
            "홍춘욱은?",
        ],
    },
    {
        "name": "실행 요청",
        "messages": [
            "에이전트 테스트 오피셜 클럽 상품페이지 목록 보여줘",
        ],
    },
]


def run_scenario(scenario: dict, token: str) -> dict:
    """시나리오 실행 + 각 턴별 응답 시간 측정."""
    results = []

    # 세션 초기화
    httpx.post(f"{BASE_URL}/reset")
    time.sleep(0.5)

    for i, message in enumerate(scenario["messages"]):
        start = time.perf_counter()

        resp = httpx.post(
            f"{BASE_URL}/chat",
            json={"message": message, "context": {"token": token}},
            timeout=120.0,
        )

        elapsed = time.perf_counter() - start
        data = resp.json()

        results.append({
            "turn": i + 1,
            "message": message,
            "elapsed_sec": round(elapsed, 2),
            "mode": data.get("mode", "unknown"),
            "response_preview": data.get("message", "")[:80],
        })

    return {
        "scenario": scenario["name"],
        "turns": results,
        "total_sec": round(sum(r["elapsed_sec"] for r in results), 2),
    }


def run_benchmark(token: str, runs: int = 3, scenarios: list | None = None):
    """벤치마크 실행."""
    target_scenarios = scenarios or SCENARIOS
    all_results = []

    for scenario in target_scenarios:
        scenario_runs = []
        print(f"\n{'='*60}")
        print(f"시나리오: {scenario['name']}")
        print(f"{'='*60}")

        for run_idx in range(runs):
            print(f"  Run {run_idx + 1}/{runs}...", end=" ", flush=True)
            result = run_scenario(scenario, token)
            scenario_runs.append(result)
            print(f"{result['total_sec']}s")

        # 통계
        totals = [r["total_sec"] for r in scenario_runs]
        per_turn = {}
        for turn_idx in range(len(scenario["messages"])):
            turn_times = [r["turns"][turn_idx]["elapsed_sec"] for r in scenario_runs]
            per_turn[f"턴{turn_idx + 1}"] = {
                "mean": round(statistics.mean(turn_times), 2),
                "median": round(statistics.median(turn_times), 2),
                "min": round(min(turn_times), 2),
                "max": round(max(turn_times), 2),
            }

        summary = {
            "scenario": scenario["name"],
            "runs": runs,
            "total": {
                "mean": round(statistics.mean(totals), 2),
                "median": round(statistics.median(totals), 2),
                "min": round(min(totals), 2),
                "max": round(max(totals), 2),
            },
            "per_turn": per_turn,
            "raw": scenario_runs,
        }
        all_results.append(summary)

        print(f"\n  평균: {summary['total']['mean']}s | "
              f"중앙값: {summary['total']['median']}s | "
              f"범위: {summary['total']['min']}~{summary['total']['max']}s")
        for turn_name, stats in per_turn.items():
            print(f"    {turn_name}: 평균 {stats['mean']}s (범위 {stats['min']}~{stats['max']}s)")

    # 결과 저장
    output_path = f"benchmarks/results_{time.strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_path, "w") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    print(f"\n결과 저장: {output_path}")

    return all_results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="오케스트레이터 응답 속도 벤치마크")
    parser.add_argument("--runs", type=int, default=3, help="시나리오당 실행 횟수")
    parser.add_argument("--token", type=str, required=True, help="admin API 토큰")
    parser.add_argument("--scenario", type=str, help="특정 시나리오만 실행 (이름)")
    args = parser.parse_args()

    target = None
    if args.scenario:
        target = [s for s in SCENARIOS if args.scenario in s["name"]]
        if not target:
            print(f"시나리오 '{args.scenario}'를 찾을 수 없습니다.")
            print(f"사용 가능: {[s['name'] for s in SCENARIOS]}")
            exit(1)

    run_benchmark(args.token, args.runs, target)
