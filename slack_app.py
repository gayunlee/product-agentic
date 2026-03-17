"""
Slack 연동 엔트리포인트.
Socket Mode로 Slack 앱과 연결하여 에이전트를 실행.

Usage:
    uv run python slack_app.py

필요한 환경변수:
    SLACK_BOT_TOKEN: xoxb-... Bot User OAuth Token
    SLACK_APP_TOKEN: xapp-... App-Level Token (Socket Mode)
"""

import os
from dotenv import load_dotenv

load_dotenv()

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from src.agent.product_agent import create_product_agent

app = App(token=os.environ["SLACK_BOT_TOKEN"])

# 유저별 에이전트 세션 관리
_sessions: dict[str, object] = {}


def get_or_create_agent(user_id: str):
    """유저별 에이전트 세션을 관리합니다."""
    if user_id not in _sessions:
        _sessions[user_id] = create_product_agent()
    return _sessions[user_id]


@app.event("app_mention")
def handle_mention(event, say):
    """에이전트 멘션 시 상품 세팅 대화를 시작합니다."""
    user_id = event["user"]
    text = event.get("text", "").strip()

    # 멘션 태그 제거
    text = text.split(">", 1)[-1].strip() if ">" in text else text

    if not text:
        say("상품 세팅을 시작하려면 마스터 이름이나 요청을 입력해주세요.")
        return

    agent = get_or_create_agent(user_id)

    try:
        response = agent(text)
        say(str(response))
    except Exception as e:
        say(f"오류가 발생했습니다: {e}")


@app.message("")
def handle_dm(message, say):
    """DM으로 대화를 계속합니다."""
    # 봇 자신의 메시지는 무시
    if message.get("bot_id"):
        return

    user_id = message["user"]
    text = message.get("text", "").strip()

    if not text:
        return

    # 세션 리셋
    if text.lower() in ("리셋", "reset", "새로시작"):
        _sessions.pop(user_id, None)
        say("세션이 초기화되었습니다. 새로운 상품 세팅을 시작해주세요.")
        return

    agent = get_or_create_agent(user_id)

    try:
        response = agent(text)
        say(str(response))
    except Exception as e:
        say(f"오류가 발생했습니다: {e}")


def main():
    print("상품 세팅 에이전트 Slack 앱 시작...")
    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    handler.start()


if __name__ == "__main__":
    main()
