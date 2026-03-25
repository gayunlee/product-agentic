"""
AgentSystem 아키텍처 시나리오 테스트.

새 아키텍처: classifier(분류) → executor/domain 직접 호출 → 포맷팅 레이어

Usage:
    MOCK_MODE=true uv run python tests/test_agent_system.py
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["MOCK_MODE"] = "true"

from dotenv import load_dotenv
load_dotenv()

from src.agents import create_agent_system
from src.agents.response import ExecutorOutput, AgentResponse, render_response


SCENARIOS = [
    # 도메인 (14개)
    (4, "마스터는 뭐고 오피셜클럽은 뭐야?", "DOMAIN", ["마스터", "오피셜클럽"]),
    (11, "오피셜클럽명 필드에 뭐가 많은데 다 뭐야?", "DOMAIN", ["고객", "관리자"]),
    (13, "상품페이지 하나 설정할때 뭐가 필요해?", "DOMAIN", ["시리즈", "오피셜클럽"]),
    (14, "상시랑 기간 설정 뭐가 먼저 노출돼?", "DOMAIN", ["기간", "상시"]),
    (15, "상품 페이지 히든 처리 기능이 뭐야?", "DOMAIN", ["URL", "숨"]),
    (17, "노출은 하는데 구매는 막고 싶은데", "DOMAIN", ["신청", "기간"]),
    (18, "단건 상품은 상품 변경 못해?", "DOMAIN", ["단건", "변경"]),
    (19, "상품 변경 못하게 하려면?", "DOMAIN", ["변경"]),
    (20, "상품 삭제하고 싶은데 왜 삭제 버튼이 안떠?", "DOMAIN", ["삭제"]),
    (21, "한 행에 이미지 여러개 입력하는 거 뭐야?", "DOMAIN", ["이미지"]),
    (22, "구독 페이지에서 노출되는 건 마스터야 오피셜클럽이야?", "DOMAIN", ["오피셜클럽"]),
    (26, "상품페이지만 비공개하고 메인 공개면 오류나?", "DOMAIN", ["오류", "비공개"]),
    (30, "대표이미지 대표비디오는 뭐야?", "DOMAIN", ["이미지", "비디오"]),
    (31, "상품 결제 수단이 상품유형에 따라 다른가?", "DOMAIN", ["구독", "단건"]),

    # 수행 — 진단/가이드/실행 (15개)
    (1, "상품페이지 새로 만들려고", "EXECUTOR", ["오피셜클럽"]),
    (2, "상품페이지 수정할려고", "EXECUTOR", ["오피셜클럽"]),
    (5, "조조형우 상품이 왜 안나오지?", "EXECUTOR", ["조조형우"]),
    (6, "조조형우 상품페이지가 왜 노출이 안돼?", "EXECUTOR", ["INACTIVE"]),
    (7, "왜 마스터가 안보여? 조조형우", "EXECUTOR", ["조조형우"]),
    (8, "조조형우 오피셜클럽 게시판이 왜 안 보여?", "EXECUTOR", ["게시판"]),
    (9, "조조형우 상품페이지에 왜 편지글이 안보여?", "EXECUTOR", ["편지"]),
    (10, "편지글 세팅 바꾸고 싶어", "EXECUTOR", ["편지"]),
    (12, "시리즈가 필요하다는데 어디서 만들어야돼?", "EXECUTOR", ["파트너센터"]),
    (16, "조조형우 상품페이지 URL로만 접근가능하고 다른데서 안 보이게", "EXECUTOR", ["히든"]),
    (23, "조조형우 상품 비공개해줘", "EXECUTOR", ["비공개"]),
    (24, "조조형우 상품페이지 비공개해줘", "EXECUTOR", ["비공개"]),
    (28, "왜 조조형우 오피셜클럽에서 응원하기 메뉴가 안보여?", "EXECUTOR", ["응원"]),
    (36, "조조형우 상품페이지 공개해줘", "EXECUTOR", ["공개"]),
    (37, "조조형우 새 마스터 상품 런칭하는데 빠진거 없는지 체크해줘", "EXECUTOR", ["조조형우"]),

    # 거부 (1개)
    (-1, "환불 처리해줘", "REJECT", ["상품 세팅"]),
]


def run_test(system, num, message, expected_class, keywords):
    start = time.time()
    try:
        # 1. 분류
        cr = system.classifier(message)
        classification = str(cr).strip().upper()

        # 2. 분류에 따라 호출
        if "EXECUTOR" in classification:
            system.executor(message)
            try:
                output = system.executor.structured_output(
                    ExecutorOutput, "위 결과를 response_type, summary, data로 정리해줘"
                )
                resp = AgentResponse.from_executor_output(output)
                text, buttons, mode = render_response(resp)
            except Exception:
                text = str(system.executor.messages[-1]) if system.executor.messages else ""
                buttons, mode = [], "error"
        elif "DOMAIN" in classification:
            result = system.domain(message)
            text = str(result)
            buttons, mode = [], "domain"
        elif "REJECT" in classification:
            text = "상품 세팅 관련 요청만 도와드릴 수 있습니다."
            buttons, mode = [], "reject"
        else:
            text = str(cr)
            buttons, mode = [], "self"

        elapsed = time.time() - start
        missing = [k for k in keywords if k.lower() not in text.lower()]
        status = "PASS" if not missing else "PARTIAL"

        return {
            "num": num, "status": status, "elapsed": round(elapsed, 1),
            "classification": classification, "mode": mode,
            "buttons": len(buttons), "missing": missing,
        }
    except Exception as e:
        return {
            "num": num, "status": "ERROR", "elapsed": round(time.time() - start, 1),
            "error": str(e)[:100],
        }


def main():
    print("=" * 60)
    print("AgentSystem 시나리오 테스트 (30개)")
    print("=" * 60)

    system = create_agent_system()
    pass_count = partial_count = error_count = 0

    for num, msg, expected_class, keywords in SCENARIOS:
        label = f"#{num:>2}" if num > 0 else " REJ"
        print(f"[{label}] {msg[:40]}...", end=" ", flush=True)

        r = run_test(system, num, msg, expected_class, keywords)

        if r["status"] == "PASS":
            print(f"✅ PASS ({r['elapsed']}s) [{r.get('classification','')}] btn={r.get('buttons',0)}")
            pass_count += 1
        elif r["status"] == "PARTIAL":
            print(f"⚠️  PARTIAL ({r['elapsed']}s) missing={r['missing']}")
            partial_count += 1
        else:
            print(f"❌ ERROR ({r['elapsed']}s) {r.get('error','')}")
            error_count += 1

    total = len(SCENARIOS)
    print(f"\n{'='*60}")
    print(f"결과: {pass_count}/{total} PASS, {partial_count} PARTIAL, {error_count} ERROR")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
