"""아키텍처 불변 규칙 검증 — 코드로 강제.

"프롬프트는 참고, Tool은 강제" 원칙.
에이전트가 이 체커를 도구로 실행하여 위반을 잡는다.

Usage:
    python -m checks.architecture          # 전체 검증
    python -m checks.architecture --fix    # 위반 리포트만 (수정은 에이전트가)
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ACTIONS_DIR = ROOT / "actions"
CONTRACTS_DIR = ROOT / "contracts"
SRC_DIR = ROOT / "src"


# ─── helpers ────────────────────────────────────────────────────────

def _grep(pattern: str, path: Path, exclude: list[str] | None = None) -> list[dict]:
    """ripgrep wrapper. Returns list of {file, line, text}."""
    cmd = ["rg", "--no-heading", "-n", pattern, str(path)]
    if exclude:
        for ex in exclude:
            cmd.extend(["--glob", f"!{ex}"])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    except FileNotFoundError:
        # rg not available, fallback to grep
        cmd = ["grep", "-rn", pattern, str(path)]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

    hits = []
    for line in result.stdout.strip().splitlines():
        parts = line.split(":", 2)
        if len(parts) >= 3:
            hits.append({"file": parts[0], "line": int(parts[1]), "text": parts[2].strip()})
    return hits


def _load_yaml(path: Path) -> dict:
    """YAML 파일 로드."""
    import yaml

    with open(path) as f:
        return yaml.safe_load(f) or {}


# ─── checks ─────────────────────────────────────────────────────────

class CheckResult:
    def __init__(self, name: str, passed: bool, message: str, violations: list[dict] | None = None):
        self.name = name
        self.passed = passed
        self.message = message
        self.violations = violations or []

    def __str__(self):
        status = "✅" if self.passed else "❌"
        s = f"{status} {self.name}: {self.message}"
        for v in self.violations:
            s += f"\n   - {v.get('file', '?')}:{v.get('line', '?')} {v.get('text', '')}"
        return s


def check_yaml_ssot() -> CheckResult:
    """registry.yaml에 없는 액션명이 코드에 하드코딩되어 있으면 실패.

    규칙: 모든 액션은 registry.yaml의 actions 섹션에 정의되어야 하며,
    코드에서 action_id를 직접 문자열로 사용하면 안 된다.
    """
    registry = _load_yaml(ACTIONS_DIR / "registry.yaml")

    # registry에 정의된 액션 목록 수집 (contracts/*.yaml 파일명 기반)
    registered_actions = set()
    for contract_file in CONTRACTS_DIR.glob("*.yaml"):
        contract = _load_yaml(contract_file)
        if contract and "action" in contract:
            registered_actions.add(contract["action"])

    # 코드에서 request_action 호출 시 하드코딩된 action_id 찾기
    hits = _grep(r'request_action\(.*action_id\s*=\s*["\']', SRC_DIR)

    violations = []
    for hit in hits:
        # action_id="..." 에서 값 추출
        match = re.search(r'action_id\s*=\s*["\']([^"\']+)["\']', hit["text"])
        if match:
            action_id = match.group(1)
            if action_id not in registered_actions:
                violations.append({**hit, "action_id": action_id})

    if violations:
        return CheckResult(
            "YAML SSOT",
            passed=False,
            message=f"contracts/에 없는 액션 {len(violations)}개 발견",
            violations=violations,
        )
    return CheckResult("YAML SSOT", passed=True, message="모든 액션이 contracts/에 정의됨")


def check_single_gate() -> CheckResult:
    """harness 외부에서 직접 write API 호출이 있으면 실패.

    규칙: 모든 상태 변경(create/update/delete)은 ActionHarness를 통해서만.
    """
    # write 패턴의 API 호출 찾기
    write_patterns = r"(set_product_page_hidden|set_product_display|update_product|create_product|delete_product)"
    hits = _grep(
        write_patterns,
        SRC_DIR,
        exclude=["harness.py", "__pycache__/*", "*.pyc"],
    )

    # import 문이나 docstring/주석은 제외
    violations = []
    for hit in hits:
        text = hit["text"]
        if text.strip().startswith("#") or text.strip().startswith('"""') or "import" in text:
            continue
        # tool decorator 내부의 API 호출도 허용 (읽기 API는 OK)
        if "def " in text:
            continue
        violations.append(hit)

    if violations:
        return CheckResult(
            "Single Gate",
            passed=False,
            message=f"harness 외부에서 write API 호출 {len(violations)}건",
            violations=violations,
        )
    return CheckResult("Single Gate", passed=True, message="모든 write 작업이 harness 경유")


def check_contract_integrity() -> CheckResult:
    """contracts/*.yaml 정의와 실제 코드 구현의 정합성 검증.

    규칙: contracts/에 정의된 required_context, invariants 등이
    harness에서 실제로 사용되고 있어야 한다.
    """
    violations = []

    for contract_file in CONTRACTS_DIR.glob("*.yaml"):
        contract = _load_yaml(contract_file)
        if not contract:
            violations.append({
                "file": str(contract_file),
                "line": 0,
                "text": "빈 contract 파일",
            })
            continue

        # 필수 필드 존재 확인
        required_fields = ["action", "label"]
        for field in required_fields:
            if field not in contract:
                violations.append({
                    "file": str(contract_file),
                    "line": 0,
                    "text": f"필수 필드 '{field}' 누락",
                })

    # registry.yaml의 actions와 contracts/ 파일 매핑 확인
    registry = _load_yaml(ACTIONS_DIR / "registry.yaml")
    if "actions" in registry:
        for action_entry in registry.get("actions", []):
            action_id = action_entry if isinstance(action_entry, str) else action_entry.get("id", "")
            contract_file = CONTRACTS_DIR / f"{action_id}.yaml"
            if not contract_file.exists():
                violations.append({
                    "file": str(ACTIONS_DIR / "registry.yaml"),
                    "line": 0,
                    "text": f"액션 '{action_id}'의 contract 파일 없음: {contract_file.name}",
                })

    if violations:
        return CheckResult(
            "Contract Integrity",
            passed=False,
            message=f"계약 정합성 위반 {len(violations)}건",
            violations=violations,
        )
    return CheckResult("Contract Integrity", passed=True, message="모든 계약 파일 정합성 확인")


def check_prompt_enforcement() -> CheckResult:
    """프롬프트에서 강제 표현이 있으면 경고 (실패가 아닌 경고).

    규칙: '반드시', '절대', '무조건' 같은 표현은 Tool/Harness로 강제해야 한다.
    프롬프트에 있으면 코드 강제로 전환할 후보.
    """
    hits = _grep(
        r"(반드시|절대로?[^가-힣]|무조건|MUST NOT|NEVER)",
        SRC_DIR / "agents",
        exclude=["__pycache__/*"],
    )

    # 프롬프트 문자열 내부만 필터
    prompt_hits = [h for h in hits if '"""' in h["text"] or "'" in h["text"] or '"' in h["text"]]

    if prompt_hits:
        return CheckResult(
            "Prompt Enforcement (경고)",
            passed=True,  # 경고이므로 통과
            message=f"프롬프트 강제 표현 {len(prompt_hits)}건 — Tool/Harness 전환 후보",
            violations=prompt_hits,
        )
    return CheckResult("Prompt Enforcement (경고)", passed=True, message="프롬프트 강제 표현 없음")


def check_visibility_chain_apis() -> CheckResult:
    """visibility_chain.yaml에서 참조하는 API 함수가 admin_api.py에 존재하는지.

    규칙: 선언된 API가 코드에 없으면 선언이 무의미.
    """
    chain_file = ROOT / "domain" / "visibility_chain.yaml"
    if not chain_file.exists():
        return CheckResult("Visibility Chain APIs", passed=True, message="visibility_chain.yaml 없음 (스킵)")

    chain_data = _load_yaml(chain_file)
    violations = []

    # chain의 requires에서 api 필드 추출
    api_names = set()
    for chain_name, chain_def in chain_data.get("chains", {}).items():
        for req in chain_def.get("requires", []):
            api = req.get("api")
            if api:
                api_names.add(api)

    # admin_api.py에 해당 함수가 있는지 (@tool 데코레이터 포함)
    api_file = SRC_DIR / "tools" / "admin_api.py"
    for api_name in sorted(api_names):
        hits = _grep(rf"def {api_name}\b", api_file)
        if not hits:
            violations.append({
                "file": str(chain_file),
                "line": 0,
                "text": f"API 함수 '{api_name}' 없음 — visibility_chain에서 참조하지만 admin_api.py에 미구현",
            })

    if violations:
        return CheckResult(
            "Visibility Chain APIs",
            passed=False,
            message=f"누락 API {len(violations)}건",
            violations=violations,
        )
    return CheckResult("Visibility Chain APIs", passed=True, message="모든 chain API 함수 존재")


def check_visibility_chain_used() -> CheckResult:
    """harness.py에서 visibility_chain을 실제로 사용하는지.

    규칙: 로드만 하고 안 쓰면 선언이 무의미.
    """
    harness_file = SRC_DIR / "harness.py"
    if not harness_file.exists():
        return CheckResult("Visibility Chain Usage", passed=True, message="harness.py 없음 (스킵)")

    # self.chains 로드 여부
    load_hits = _grep(r"self.chains", harness_file)
    # validate_and_confirm에서 chains 사용 여부
    use_hits = _grep(r"chain_name", harness_file)

    if load_hits and not use_hits:
        return CheckResult(
            "Visibility Chain Usage",
            passed=False,
            message="visibility_chain을 로드하지만 사용하지 않음",
            violations=[{"file": str(harness_file), "line": 0, "text": "self.chains 로드 후 validate_and_confirm()에서 미사용"}],
        )
    if not load_hits:
        return CheckResult(
            "Visibility Chain Usage",
            passed=False,
            message="visibility_chain 로드 자체가 없음",
            violations=[{"file": str(harness_file), "line": 0, "text": "visibility_chain.yaml 미로드"}],
        )
    return CheckResult("Visibility Chain Usage", passed=True, message="visibility_chain 로드 및 사용 확인")


def check_knowledge_api_exists() -> CheckResult:
    """knowledge/*.md에서 참조하는 API 함수가 admin_api.py에 존재하는지.

    규칙: 문서에서 정의한 플로우가 실제로 실행 가능해야 함.
    """
    knowledge_dir = ROOT / "knowledge"
    if not knowledge_dir.exists():
        return CheckResult("Knowledge API Exists", passed=True, message="knowledge/ 없음 (스킵)")

    api_file = SRC_DIR / "tools" / "admin_api.py"
    violations = []

    # knowledge md에서 update_*, get_* 함수명 추출
    for md_file in knowledge_dir.glob("*.md"):
        hits = _grep(r"\b(update_\w+|get_\w+|create_\w+|delete_\w+)\b", md_file)
        for hit in hits:
            # 함수명 추출
            import re
            funcs = re.findall(r"\b((?:update|get|create|delete)_\w+)\b", hit["text"])
            for func in funcs:
                # admin_api.py에 존재하는지
                exists = _grep(rf"def {func}\b", api_file)
                if not exists:
                    violations.append({
                        "file": str(md_file),
                        "line": hit["line"],
                        "text": f"API 함수 '{func}' 없음 — knowledge에서 참조하지만 미구현",
                    })

    # 중복 제거
    seen = set()
    unique = []
    for v in violations:
        key = v["text"]
        if key not in seen:
            seen.add(key)
            unique.append(v)

    if unique:
        return CheckResult(
            "Knowledge API Exists",
            passed=False,
            message=f"누락 API {len(unique)}건 (knowledge 참조)",
            violations=unique,
        )
    return CheckResult("Knowledge API Exists", passed=True, message="knowledge 참조 API 모두 존재")


# ─── runner ─────────────────────────────────────────────────────────

ALL_CHECKS = [
    check_yaml_ssot,
    check_single_gate,
    check_contract_integrity,
    check_visibility_chain_apis,
    check_visibility_chain_used,
    check_knowledge_api_exists,
    check_prompt_enforcement,
]


def run_all() -> list[CheckResult]:
    """모든 체커 실행."""
    results = []
    for check_fn in ALL_CHECKS:
        try:
            results.append(check_fn())
        except Exception as e:
            results.append(CheckResult(check_fn.__name__, passed=False, message=f"체커 실행 오류: {e}"))
    return results


def main():
    results = run_all()
    print("=" * 60)
    print("  아키텍처 검증 리포트")
    print("=" * 60)

    passed = 0
    failed = 0
    warnings = 0

    for r in results:
        print(f"\n{r}")
        if r.passed and not r.violations:
            passed += 1
        elif r.passed and r.violations:
            warnings += 1
        else:
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"  결과: ✅ {passed} 통과 | ❌ {failed} 실패 | ⚠️ {warnings} 경고")
    print(f"{'=' * 60}")

    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
