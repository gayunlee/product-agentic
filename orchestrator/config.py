"""레포 경로 및 에이전트 설정."""

from pathlib import Path

# 레포 경로
PRODUCT_AGENT_DIR = Path.home() / "Documents/ai/us-product-agent"
EXPLORER_AGENT_DIR = Path.home() / "Documents/ai/us-explorer-agent"
WEB_DIR = Path.home() / "Documents/us/us-web"

# us-web 워크트리 (동시 작업 충돌 방지 — 항상 이 경로에서 작업)
WEB_WORKTREE_DIR = WEB_DIR / ".claude/worktrees/orchestrator"
WEB_WORKTREE_BRANCH = "orchestrator-web-mcp"

# 에이전트 공통 도구
READ_TOOLS = ["Read", "Glob", "Grep", "Bash"]
WRITE_TOOLS = ["Read", "Edit", "Write", "Glob", "Grep", "Bash"]

# 비용 제한
MAX_BUDGET_PER_AGENT = 5.0  # USD
MAX_TURNS_PER_AGENT = 50
