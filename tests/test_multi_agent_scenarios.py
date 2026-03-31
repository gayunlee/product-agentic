"""
멀티 에이전트 시나리오 테스트 — 32개 시나리오 전체 검증.

각 시나리오에 대해:
1. 오케스트레이터가 올바른 에이전트로 라우팅하는지
2. 기대한 Tool이 호출되는지 (가능한 경우)
3. 응답에 핵심 키워드가 포함되는지

Usage:
    MOCK_MODE=true uv run python tests/test_multi_agent_scenarios.py
"""

import os
import sys
import time

# 프로젝트 루트를 path에 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ["MOCK_MODE"] = "true"

from dotenv import load_dotenv
load_dotenv()

from src.agents import create_agent_system


# 시나리오 정의: (번호, 유저 메시지, 기대 라우팅, 기대 키워드)
SCENARIOS = [
    # 도메인 질문 (14개) — domain_expert 호출, API 없이 답변
    (4, "마스터는 뭐고 오피셜클럽은 뭐야?", "domain", ["마스터", "오피셜클럽"]),
    (11, "오피셜클럽명 필드에 뭐가 많은데 다 뭐야?", "domain", ["고객", "관리자"]),
    (13, "상품페이지 하나 설정할때 뭐가 필요해?", "domain", ["시리즈", "오피셜클럽"]),
    (14, "상시랑 기간 설정 뭐가 먼저 노출돼?", "domain", ["기간", "상시"]),
    (15, "상품 페이지 히든 처리 기능이 뭐야?", "domain", ["URL", "숨"]),
    (17, "노출은 하는데 구매는 막고 싶은데", "domain", ["신청", "기간"]),
    (18, "단건 상품은 상품 변경 못해?", "domain", ["단건", "변경"]),
    (19, "상품 변경 못하게 하려면?", "domain", ["변경"]),
    (20, "상품 삭제하고 싶은데 왜 삭제 버튼이 안떠?", "domain", ["삭제"]),
    (21, "한 행에 이미지 여러개 입력하는 거 뭐야?", "domain", ["이미지"]),
    (22, "구독 페이지에서 노출되는 건 마스터야 오피셜클럽이야?", "domain", ["오피셜클럽"]),
    (26, "상품페이지만 비공개하고 메인 공개면 오류나?", "domain", ["오류", "비공개"]),
    (30, "대표이미지 대표비디오는 뭐야?", "domain", ["이미지", "동영상"]),
    (31, "상품 결제 수단이 상품유형에 따라 다른가?", "domain", ["구독", "단건"]),

    # 수행 — 가이드 (4개) — executor 호출
    (1, "상품페이지 새로 만들려고", "executor", ["오피셜클럽", "구독"]),
    (2, "상품페이지 수정할려고", "executor", ["오피셜클럽"]),
    (10, "편지글 세팅 바꾸고 싶어", "executor", ["편지"]),
    (12, "시리즈가 필요하다는데 어디서 만들어야돼?", "executor", ["파트너센터"]),

    # 수행 — 진단 (7개) — executor 호출 + validator
    (5, "조조형우 상품이 왜 안나오지?", "executor", ["조조형우"]),
    (6, "조조형우 상품페이지가 왜 노출이 안돼?", "executor", ["INACTIVE"]),
    (7, "왜 마스터가 안보여? 조조형우", "executor", ["조조형우"]),
    (8, "조조형우 오피셜클럽 게시판이 왜 안 보여?", "executor", ["게시판"]),
    (9, "조조형우 상품페이지에 왜 편지글이 안보여?", "executor", ["편지"]),
    (28, "왜 조조형우 오피셜클럽에서 응원하기 메뉴가 안보여?", "executor", ["응원"]),
    (37, "조조형우 새 마스터 상품 런칭하는데 빠진거 없는지 체크해줘", "executor", ["조조형우"]),

    # 수행 — 실행 (4개) — executor 호출 + 상태 변경
    (16, "조조형우 상품페이지 URL로만 접근가능하고 다른데서 안 보이게", "executor", ["히든"]),
    (23, "조조형우 상품 비공개해줘", "executor", ["비공개"]),
    (24, "조조형우 상품페이지 비공개해줘", "executor", ["비공개"]),
    (36, "조조형우 상품페이지 공개해줘", "executor", ["공개"]),

    # 범위 밖 — 오케스트레이터 거부
    (-1, "환불 처리해줘", "reject", ["상품 세팅"]),
]


def run_scenario(agent, num, message, expected_route, expected_keywords):
    """단일 시나리오 실행 + 검증."""
    start = time.time()
    try:
        result = str(agent(message))
        elapsed = time.time() - start

        # 키워드 체크
        found = []
        missing = []
        for kw in expected_keywords:
            if kw.lower() in result.lower():
                found.append(kw)
            else:
                missing.append(kw)

        passed = len(missing) == 0
        status = "PASS" if passed else "PARTIAL"

        return {
            "num": num,
            "status": status,
            "elapsed": round(elapsed, 1),
            "missing_keywords": missing,
            "response_preview": result[:200],
        }
    except Exception as e:
        elapsed = time.time() - start
        return {
            "num": num,
            "status": "ERROR",
            "elapsed": round(elapsed, 1),
            "error": str(e)[:200],
        }


def main():
    print("=" * 60)
    print("멀티 에이전트 시나리오 테스트 (32개)")
    print("=" * 60)

    system = create_agent_system()
    agent = system.orchestrator
    results = []
    pass_count = 0
    partial_count = 0
    error_count = 0

    for num, message, expected_route, expected_keywords in SCENARIOS:
        label = f"#{num:>2}" if num > 0 else " REJ"
        route_label = {"domain": "도메인", "executor": "수행", "reject": "거부"}[expected_route]
        print(f"\n[{label}] ({route_label}) {message[:40]}...", end=" ", flush=True)

        r = run_scenario(agent, num, message, expected_route, expected_keywords)
        results.append(r)

        if r["status"] == "PASS":
            print(f"✅ PASS ({r['elapsed']}s)")
            pass_count += 1
        elif r["status"] == "PARTIAL":
            print(f"⚠️  PARTIAL ({r['elapsed']}s) missing: {r['missing_keywords']}")
            partial_count += 1
        else:
            print(f"❌ ERROR ({r['elapsed']}s) {r.get('error', '')[:80]}")
            error_count += 1

    # 요약
    total = len(SCENARIOS)
    print("\n" + "=" * 60)
    print(f"결과: {pass_count}/{total} PASS, {partial_count} PARTIAL, {error_count} ERROR")
    print("=" * 60)

    # 실패 상세
    if partial_count > 0 or error_count > 0:
        print("\n[실패 상세]")
        for r in results:
            if r["status"] != "PASS":
                print(f"  #{r['num']}: {r['status']}")
                if "missing_keywords" in r:
                    print(f"    missing: {r['missing_keywords']}")
                    print(f"    response: {r.get('response_preview', '')[:150]}")
                if "error" in r:
                    print(f"    error: {r['error'][:150]}")


if __name__ == "__main__":
    main()
