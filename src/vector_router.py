"""
벡터 기반 라우팅 — 시나리오 임베딩으로 유사도 기반 즉시 라우팅.

오케스트레이터 LLM 호출 없이 라우팅 결정.
유사도가 낮으면 오케스트레이터 LLM fallback.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

SCENARIOS_DIR = Path(__file__).parent.parent / "scenarios" / "multi-agent"
EMBEDDINGS_CACHE = Path(__file__).parent.parent / "benchmarks" / "scenario_embeddings.json"
SIMILARITY_THRESHOLD = 0.75  # 이 이상이면 즉시 라우팅


@dataclass
class ScenarioPattern:
    """시나리오에서 추출한 라우팅 패턴."""
    file: str
    user_message: str
    route: str  # "executor" | "domain" | "reject"
    embedding: list[float] = field(default_factory=list)


def _extract_patterns_from_scenario(filepath: Path) -> list[ScenarioPattern]:
    """시나리오 파일에서 유저 메시지 + 라우팅 정보를 추출."""
    content = filepath.read_text(encoding="utf-8")
    patterns = []

    # 라우팅 결정: "수행 에이전트" → executor, "도메인" → domain
    route = "executor"
    if "도메인 지식 에이전트" in content or "도메인 질문" in content:
        route = "domain"
    if "거부" in content or "범위 밖" in content:
        route = "reject"

    # 유저 메시지 추출: "유저: ..." 패턴
    for match in re.finditer(r'유저:\s*(.+)', content):
        msg = match.group(1).strip().strip('"').strip("'")
        if msg and len(msg) > 3:
            patterns.append(ScenarioPattern(
                file=filepath.name,
                user_message=msg,
                route=route,
            ))

    # 제목에서도 추출: "# #N 제목"
    title_match = re.search(r'#\s*#?\d+\s*(.+)', content)
    if title_match:
        title = title_match.group(1).strip()
        if title and len(title) > 3:
            patterns.append(ScenarioPattern(
                file=filepath.name,
                user_message=title,
                route=route,
            ))

    return patterns


def load_all_patterns() -> list[ScenarioPattern]:
    """모든 시나리오 파일에서 패턴 추출."""
    patterns = []
    if SCENARIOS_DIR.exists():
        for f in sorted(SCENARIOS_DIR.glob("*.md")):
            patterns.extend(_extract_patterns_from_scenario(f))
    logger.info(f"시나리오 패턴 {len(patterns)}개 로드")
    return patterns


def _get_embedding(text: str, client=None) -> list[float]:
    """Bedrock Titan으로 텍스트 임베딩."""
    import boto3

    if client is None:
        client = boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "ap-northeast-2"))

    body = json.dumps({"inputText": text})
    response = client.invoke_model(
        modelId="amazon.titan-embed-text-v2:0",
        contentType="application/json",
        accept="application/json",
        body=body,
    )
    result = json.loads(response["body"].read())
    return result["embedding"]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """코사인 유사도 계산."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class VectorRouter:
    """벡터 유사도 기반 라우터. 오케스트레이터 LLM 호출 없이 라우팅."""

    def __init__(self):
        self.patterns: list[ScenarioPattern] = []
        self._client = None
        self._initialized = False

    def initialize(self):
        """패턴 로드 + 임베딩 생성 (또는 캐시 로드)."""
        if self._initialized:
            return

        import boto3
        self._client = boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "ap-northeast-2"))

        # 캐시 확인
        if EMBEDDINGS_CACHE.exists():
            try:
                with open(EMBEDDINGS_CACHE) as f:
                    cached = json.load(f)
                self.patterns = [ScenarioPattern(**p) for p in cached]
                if self.patterns and self.patterns[0].embedding:
                    self._initialized = True
                    logger.info(f"임베딩 캐시 로드: {len(self.patterns)}개")
                    return
            except Exception as e:
                logger.warning(f"캐시 로드 실패: {e}")

        # 패턴 추출 + 임베딩 생성
        self.patterns = load_all_patterns()
        for p in self.patterns:
            try:
                p.embedding = _get_embedding(p.user_message, self._client)
            except Exception as e:
                logger.warning(f"임베딩 실패: {p.user_message[:30]}: {e}")

        # 캐시 저장
        EMBEDDINGS_CACHE.parent.mkdir(parents=True, exist_ok=True)
        with open(EMBEDDINGS_CACHE, "w") as f:
            json.dump([{
                "file": p.file,
                "user_message": p.user_message,
                "route": p.route,
                "embedding": p.embedding,
            } for p in self.patterns if p.embedding], f, ensure_ascii=False)

        self._initialized = True
        logger.info(f"임베딩 생성 완료: {len(self.patterns)}개")

    def classify(self, message: str) -> tuple[str | None, float, str]:
        """메시지의 유사도 기반 라우팅.

        Returns:
            (route, similarity, matched_message)
            route가 None이면 유사도 부족 → 오케스트레이터 fallback
        """
        if not self._initialized:
            self.initialize()

        if not self.patterns:
            return None, 0.0, ""

        try:
            query_embedding = _get_embedding(message, self._client)
        except Exception as e:
            logger.warning(f"쿼리 임베딩 실패: {e}")
            return None, 0.0, ""

        best_sim = 0.0
        best_pattern = None

        for p in self.patterns:
            if not p.embedding:
                continue
            sim = _cosine_similarity(query_embedding, p.embedding)
            if sim > best_sim:
                best_sim = sim
                best_pattern = p

        if best_pattern and best_sim >= SIMILARITY_THRESHOLD:
            logger.info(f"벡터 라우팅: '{message[:30]}' → {best_pattern.route} "
                       f"(유사도 {best_sim:.3f}, 매칭: '{best_pattern.user_message[:30]}')")
            return best_pattern.route, best_sim, best_pattern.user_message

        logger.info(f"벡터 유사도 부족: '{message[:30]}' → 최고 {best_sim:.3f} (임계값 {SIMILARITY_THRESHOLD})")
        return None, best_sim, best_pattern.user_message if best_pattern else ""
