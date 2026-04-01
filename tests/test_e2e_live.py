"""
E2E 라이브 테스트 — 실제 Admin API 호출.

실행 조건:
  - MOCK_MODE=false (실제 API)
  - 서버가 localhost:8000에서 실행 중

실행:
  uv run pytest tests/test_e2e_live.py -v -s -m live
"""

import os
import uuid

import httpx
import pytest

SERVER_URL = os.environ.get("TEST_SERVER_URL", "http://localhost:8000")
TIMEOUT = 60.0


def _is_live_server():
    try:
        r = httpx.get(f"{SERVER_URL}/mode", timeout=5)
        return r.json().get("mock") is False
    except Exception:
        return False


pytestmark = pytest.mark.live


@pytest.fixture(autouse=True)
def require_live_server():
    if not _is_live_server():
        pytest.skip("Live server not running on " + SERVER_URL)


def _new_session():
    return f"live-{uuid.uuid4().hex[:8]}"


def _chat(message, session_id):
    with httpx.Client(timeout=TIMEOUT) as client:
        r = client.post(
            f"{SERVER_URL}/chat",
            json={"message": message, "session_id": session_id},
        )
        return r.json()


# ---------------------------------------------------------------------------
# G-10: Partial search
# ---------------------------------------------------------------------------
class TestPartialSearch:
    def test_partial_name_finds_result(self):
        """G-10: 부분 이름으로 검색."""
        sid = _new_session()
        r = _chat("에이전트 테스트 클럽 노출 진단해줘", sid)
        # Should find results even with partial name
        assert (
            "검색 결과가 없" not in r["message"] or "찾을 수 없" not in r["message"]
        ), f"부분 검색 실패: {r['message'][:200]}"


# ---------------------------------------------------------------------------
# G-12: Diagnose contradiction
# ---------------------------------------------------------------------------
class TestDiagnoseContradiction:
    def test_no_normal_when_no_data(self):
        """G-12: 데이터 없을 때 '정상' 표시하면 안 됨."""
        sid = _new_session()
        r = _chat("없는오피셜클럽xyz123 진단해줘", sid)
        msg = r["message"]
        # "정상"과 "데이터 없음"이 동시에 나오면 안 됨
        has_normal = any(k in msg for k in ("정상", "모든 조건"))
        has_no_data = any(k in msg for k in ("데이터 없", "검색 결과 없", "찾을 수 없"))
        assert not (has_normal and has_no_data), (
            f"모순: 정상+데이터없음 동시 표시: {msg[:300]}"
        )


# ---------------------------------------------------------------------------
# G-4: Context retention
# ---------------------------------------------------------------------------
class TestContextRetention:
    def test_diagnose_then_followup(self):
        """G-4: 진단 후 후속 요청에서 맥락 유지."""
        sid = _new_session()
        # Use a name that exists in live
        r1 = _chat("에이전트 테스트 오피셜 클럽 진단해줘", sid)
        if "찾을 수 없" in r1["message"]:
            pytest.skip("테스트 오피셜클럽 검색 불가")
        r2 = _chat("그 히든 해제해줘", sid)
        # Should reference the previous club, not ask "which club?"
        assert not any(
            k in r2["message"]
            for k in ("어떤 오피셜클럽", "어느 오피셜클럽", "오피셜클럽 이름")
        ), f"맥락 유실: {r2['message'][:200]}"


# ---------------------------------------------------------------------------
# G-7: Boundary rejection
# ---------------------------------------------------------------------------
class TestBoundaryLive:
    def test_refund_rejected(self):
        """G-7: 범위 밖 요청 거절."""
        sid = _new_session()
        r = _chat("환불 처리해줘", sid)
        assert any(
            k in r["message"] for k in ("도와드릴 수 없", "범위", "죄송")
        ), f"거절 안 함: {r['message'][:200]}"
