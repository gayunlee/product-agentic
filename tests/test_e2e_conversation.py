"""
E2E 대화 시나리오 테스트 — 실제 LLM 호출.

실제 Bedrock LLM을 호출하여 멀티턴 대화 품질을 검증한다.
contracts/ YAML의 invariant를 자동으로 체크.

실행 조건:
  - MOCK_MODE=true (admin API는 Mock)
  - Bedrock 인증 필요 (실제 LLM 호출)
  - 서버가 실행 중이어야 함 (별도 프로세스)

실행:
  # 1. 서버 시작 (별도 터미널)
  MOCK_MODE=true uv run python server.py

  # 2. 테스트 실행
  uv run pytest tests/test_e2e_conversation.py -v -s --timeout=120
"""

import os
import json
import time
import uuid
import pytest
import httpx

SERVER_URL = os.environ.get("TEST_SERVER_URL", "http://localhost:8000")
TIMEOUT = 60.0  # LLM 호출 타임아웃


def _chat(message: str, session_id: str, button: dict | None = None) -> dict:
    """서버에 채팅 요청을 보내고 응답을 반환."""
    body = {"message": message, "session_id": session_id}
    if button:
        body["button"] = button
        body["message"] = ""
    with httpx.Client(timeout=TIMEOUT) as client:
        resp = client.post(f"{SERVER_URL}/chat", json=body)
        resp.raise_for_status()
        return resp.json()


def _new_session() -> str:
    return f"e2e-{uuid.uuid4().hex[:8]}"


def _server_available() -> bool:
    try:
        with httpx.Client(timeout=5) as client:
            resp = client.get(SERVER_URL)
            return resp.status_code == 200
    except Exception:
        return False


# 서버가 없으면 전체 스킵
pytestmark = pytest.mark.skipif(
    not _server_available(),
    reason=f"서버가 {SERVER_URL}에서 실행 중이지 않습니다. MOCK_MODE=true uv run python server.py 로 시작하세요.",
)


# ══════════════════════════════════════════════════
# 1. request_action 플로우 (Harness 경유)
# ══════════════════════════════════════════════════


class TestRequestActionFlow:
    """채팅 → request_action → 확인 → 실행 전체 플로우."""

    def test_product_page_hide_full_flow(self):
        """상품페이지 비공개 전체 플로우.
        턴1: 슬롯 필링 (마스터+페이지 특정)
        턴2: 확인 메시지 (execute 모드, 버튼)
        턴3: [실행] 클릭 → 완료
        """
        sid = _new_session()

        # 턴1: 충분한 정보를 줘서 request_action까지 도달
        r1 = _chat("조조형우 월간 투자 리포트 상품페이지 비공개해줘", sid)
        print(f"턴1: mode={r1['mode']}, buttons={len(r1.get('buttons', []))}")

        # request_action이 호출되었으면 execute 모드
        if r1["mode"] == "execute":
            # 확인 버튼이 있어야 함
            exec_btn = next(
                (b for b in r1.get("buttons", []) if b.get("action") == "execute_confirmed"),
                None,
            )
            assert exec_btn is not None, "execute_confirmed 버튼이 없음"
            assert exec_btn.get("payload"), "payload가 없음"

            # [실행] 클릭
            r2 = _chat("", sid, button={
                "type": "action",
                "action": "execute_confirmed",
                "payload": exec_btn["payload"],
            })
            assert r2["mode"] == "done", f"실행 후 mode가 done이 아님: {r2['mode']}"
            assert "완료" in r2["message"]
        else:
            # 슬롯 필링 중 — LLM이 추가 질문. 허용.
            print(f"  슬롯 필링 중: {r1['message'][:100]}")

    def test_product_hide_with_slots(self):
        """상품 옵션 비공개 — 마스터+페이지+상품까지 특정."""
        sid = _new_session()
        r1 = _chat("조조형우의 월간 투자 리포트 페이지에 있는 월간 투자 리포트 상품 비공개해줘", sid)
        print(f"mode={r1['mode']}, msg={r1['message'][:100]}")
        # LLM이 request_action을 호출했다면 execute 모드
        # 아니면 슬롯 필링 중 (둘 다 허용)
        assert r1["mode"] in ("execute", "idle", "error", "done", "guide"), f"예상 외 mode: {r1['mode']}"


# ══════════════════════════════════════════════════
# 2. 진단 플로우
# ══════════════════════════════════════════════════


class TestDiagnoseFlow:
    """진단 → 결과 → 후속 요청."""

    def test_diagnose_basic(self):
        """기본 진단 — "왜 안 보여?"."""
        sid = _new_session()
        r = _chat("조조형우 왜 안 보여?", sid)
        print(f"mode={r['mode']}, msg={r['message'][:100]}")
        assert r["mode"] in ("diagnose", "idle"), f"진단 mode가 아님: {r['mode']}"
        # 진단 결과에 체크 항목이 있어야
        assert any(kw in r["message"] for kw in ("진단", "상태", "✅", "❌", "원인", "INACTIVE", "PUBLIC")), \
            f"진단 결과가 아닌 것 같음: {r['message'][:200]}"

    def test_diagnose_with_name(self):
        """이름으로 진단 — search_masters 없이."""
        sid = _new_session()
        r = _chat("조조형우 노출 진단해줘", sid)
        assert r["mode"] in ("diagnose", "idle")


# ══════════════════════════════════════════════════
# 3. 모호한 요청 (구분 질문 필요)
# ══════════════════════════════════════════════════


class TestAmbiguousRequests:
    """모호한 요청 시 구분 질문을 하는지."""

    def test_ambiguous_hide(self):
        """'비공개해줘'만 — 뭘 비공개? 물어봐야."""
        sid = _new_session()
        r = _chat("비공개해줘", sid)
        msg = r["message"].lower()
        print(f"mode={r['mode']}, msg={r['message'][:200]}")
        # 바로 실행하면 안 됨 — 질문이나 안내가 있어야
        assert r["mode"] != "done", "대상 없이 바로 완료하면 안 됨"
        assert any(kw in msg for kw in ("어떤", "오피셜클럽", "마스터", "상품", "선택", "어느")), \
            "대상을 물어보지 않음"

    def test_product_vs_page_ambiguity(self):
        """'조조형우 비공개해줘' — 상품인지 상품페이지인지 모호."""
        sid = _new_session()
        r = _chat("조조형우 비공개해줘", sid)
        msg = r["message"]
        print(f"mode={r['mode']}, msg={msg[:200]}")
        # 바로 실행하면 안 됨
        assert r["mode"] != "done", "모호한 요청에 바로 완료하면 안 됨"


# ══════════════════════════════════════════════════
# 4. 경계 밖 요청 (거부)
# ══════════════════════════════════════════════════


class TestBoundaryRequests:
    """범위 밖 요청에 대한 거부/안내."""

    def test_refund_rejected(self):
        """환불 요청 → 거부."""
        sid = _new_session()
        r = _chat("환불 처리해줘", sid)
        msg = r["message"]
        print(f"mode={r['mode']}, msg={msg[:200]}")
        assert any(kw in msg for kw in ("죄송", "도와드릴 수 없", "상품 세팅", "범위")), \
            "환불 요청을 거부하지 않음"

    def test_unrelated_rejected(self):
        """완전 무관한 질문 → 거부."""
        sid = _new_session()
        r = _chat("오늘 날씨 어때?", sid)
        msg = r["message"]
        print(f"mode={r['mode']}, msg={msg[:200]}")
        assert any(kw in msg for kw in ("죄송", "도와드릴 수 없", "상품 세팅", "관련")), \
            "무관한 질문을 거부하지 않음"

    def test_create_navigates(self):
        """생성 요청 → navigate 안내."""
        sid = _new_session()
        r = _chat("상품페이지 새로 만들려고", sid)
        msg = r["message"]
        print(f"mode={r['mode']}, msg={msg[:200]}")
        # navigate 안내 또는 가이드
        assert r["mode"] in ("guide", "idle", "error")
        assert any(kw in msg for kw in ("이동", "생성", "페이지", "관리자센터", "navigate")), \
            "생성 안내가 없음"


# ══════════════════════════════════════════════════
# 5. 맥락 전환 (멀티턴)
# ══════════════════════════════════════════════════


class TestContextSwitch:
    """맥락 유지/전환 테스트."""

    def test_diagnose_then_concept(self):
        """진단 후 개념 질문 → domain으로 전환."""
        sid = _new_session()
        r1 = _chat("조조형우 왜 안 보여?", sid)
        print(f"턴1: mode={r1['mode']}")

        r2 = _chat("메인 상품페이지가 뭐야?", sid)
        msg = r2["message"]
        print(f"턴2: mode={r2['mode']}, msg={msg[:200]}")
        # 개념 설명이 있어야
        assert any(kw in msg for kw in ("메인 상품", "설정", "ACTIVE", "노출", "구독")), \
            "개념 설명이 없음"

    def test_concept_then_execute(self):
        """개념 질문 후 실행 요청 → executor로 전환."""
        sid = _new_session()
        r1 = _chat("히든이 뭐야?", sid)
        print(f"턴1: mode={r1['mode']}")

        r2 = _chat("그럼 조조형우 월간 투자 리포트 히든 처리해줘", sid)
        msg = r2["message"]
        print(f"턴2: mode={r2['mode']}, msg={msg[:200]}")
        # 실행 또는 슬롯 필링
        assert r2["mode"] != "reject"


# ══════════════════════════════════════════════════
# 6. 위저드 플로우 (변경 없음 확인)
# ══════════════════════════════════════════════════


class TestWizardFlow:
    """위저드가 기존과 동일하게 동작하는지."""

    def test_wizard_diagnose(self):
        """위저드 진단 플로우."""
        sid = _new_session()
        # 위저드 시작
        body = {"wizard_action": "diagnose", "session_id": sid}
        with httpx.Client(timeout=TIMEOUT) as client:
            resp = client.post(f"{SERVER_URL}/chat", json=body)
            r = resp.json()
        print(f"mode={r['mode']}, buttons={len(r.get('buttons', []))}")
        assert r["mode"] == "wizard"
        assert len(r.get("buttons", [])) > 0, "위저드 버튼이 없음"

    def test_wizard_actions_endpoint(self):
        """위저드 액션 목록 API."""
        with httpx.Client(timeout=10) as client:
            resp = client.get(f"{SERVER_URL}/wizard/actions")
            actions = resp.json()
        print(f"위저드 액션: {[a['action'] for a in actions]}")
        assert len(actions) > 0
        action_ids = [a["action"] for a in actions]
        assert "diagnose" in action_ids or any("diagnose" in a for a in action_ids)


# ══════════════════════════════════════════════════
# 7. Harness 강제 검증 (E2E)
# ══════════════════════════════════════════════════


class TestHarnessEnforcement:
    """Harness가 실제 LLM 플로우에서 강제되는지."""

    def test_confirmation_required(self):
        """상태 변경 시 확인 없이 바로 실행 안 됨.
        invariant: no_auto_execute"""
        sid = _new_session()
        r = _chat("조조형우 월간 투자 리포트 상품페이지 비공개해줘", sid)
        # done이면 확인 없이 실행된 것 — 위반
        if r["mode"] == "done" and "완료" in r["message"]:
            pytest.fail("확인 없이 바로 실행됨 (no_auto_execute invariant 위반)")
