#!/bin/bash
# 테스트 환경 자동 셋업 — 세팅 에이전트 + QA 에이전트 + us-plus (web-mcp)
#
# Usage:
#   ./scripts/start-test-env.sh          # 전체 시작
#   ./scripts/start-test-env.sh stop     # 전체 종료
#   ./scripts/start-test-env.sh status   # 상태 확인

set -e

PRODUCT_AGENT_DIR="$HOME/Documents/ai/us-product-agent"
EXPLORER_AGENT_DIR="$HOME/Documents/ai/us-explorer-agent"
US_WEB_DIR="$HOME/Documents/us/us-web"

LOG_DIR="/tmp/test-env-logs"
mkdir -p "$LOG_DIR"

# 색상
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
NC='\033[0m'

wait_for_port() {
    local port=$1
    local name=$2
    local max_wait=${3:-30}
    local elapsed=0
    while ! curl -s "http://localhost:$port" > /dev/null 2>&1; do
        sleep 1
        elapsed=$((elapsed + 1))
        if [ $elapsed -ge $max_wait ]; then
            echo -e "${RED}✗ $name (port $port) — $max_wait초 내 시작 실패${NC}"
            return 1
        fi
    done
    echo -e "${GREEN}✓ $name (port $port) — ${elapsed}초${NC}"
}

stop_all() {
    echo "서비스 종료 중..."
    lsof -ti:8000 2>/dev/null | xargs kill -9 2>/dev/null && echo "  세팅 에이전트 종료" || true
    lsof -ti:8001 2>/dev/null | xargs kill -9 2>/dev/null && echo "  QA 에이전트 종료" || true
    lsof -ti:3000 2>/dev/null | xargs kill -9 2>/dev/null && echo "  us-plus 종료" || true
    echo -e "${GREEN}전체 종료 완료${NC}"
}

status() {
    echo "테스트 환경 상태:"
    curl -s http://localhost:8000/mode > /dev/null 2>&1 \
        && echo -e "  ${GREEN}✓ 세팅 에이전트 :8000${NC}" \
        || echo -e "  ${RED}✗ 세팅 에이전트 :8000${NC}"
    curl -s http://localhost:8001/health > /dev/null 2>&1 \
        && echo -e "  ${GREEN}✓ QA 에이전트 :8001${NC}" \
        || echo -e "  ${RED}✗ QA 에이전트 :8001${NC}"
    curl -s http://localhost:3000 > /dev/null 2>&1 \
        && echo -e "  ${GREEN}✓ us-plus :3000${NC}" \
        || echo -e "  ${RED}✗ us-plus :3000${NC}"
}

start_all() {
    echo "========================================="
    echo "  테스트 환경 시작"
    echo "========================================="

    # 기존 프로세스 정리
    stop_all 2>/dev/null

    # 1. us-plus (web-mcp 브랜치)
    echo ""
    echo -e "${YELLOW}[1/3] us-plus (web-mcp) 시작...${NC}"
    (
        cd "$US_WEB_DIR"
        git checkout web-mcp 2>/dev/null || git checkout feature/web-mcp 2>/dev/null
        npx turbo dev --filter=us-plus > "$LOG_DIR/us-plus.log" 2>&1
    ) &
    wait_for_port 3000 "us-plus" 60

    # 2. QA 에이전트
    echo -e "${YELLOW}[2/3] QA 에이전트 시작...${NC}"
    (
        cd "$EXPLORER_AGENT_DIR"
        uv run python server.py > "$LOG_DIR/explorer-agent.log" 2>&1
    ) &
    wait_for_port 8001 "QA 에이전트" 30

    # 3. 세팅 에이전트 (라이브 모드)
    echo -e "${YELLOW}[3/3] 세팅 에이전트 시작...${NC}"
    (
        cd "$PRODUCT_AGENT_DIR"
        uv run python server.py > "$LOG_DIR/product-agent.log" 2>&1
    ) &
    wait_for_port 8000 "세팅 에이전트" 30

    echo ""
    echo "========================================="
    echo -e "${GREEN}  테스트 환경 준비 완료${NC}"
    echo "========================================="
    echo ""
    echo "  세팅 에이전트: http://localhost:8000"
    echo "  QA 에이전트:   http://localhost:8001"
    echo "  us-plus:       http://localhost:3000"
    echo ""
    echo "  로그: $LOG_DIR/"
    echo "  종료: ./scripts/start-test-env.sh stop"
    echo ""
}

case "${1:-start}" in
    stop)   stop_all ;;
    status) status ;;
    start)  start_all ;;
    *)      echo "Usage: $0 {start|stop|status}" ;;
esac
