## Why

상품 에이전트가 프로덕션에 올라가면 운영 매니저가 실시간으로 사용하면서 에러가 발생하고, 동시에 개발 중에도 리팩토링/기능 추가 시 기존 구조가 흐트러질 수 있다. 현재는 에러 발생 → 사람이 발견 → 수동 디버깅 → 수동 테스트의 루프인데, 이를 **에이전트가 감지 → 분석 → 수정 → 테스트 → 리포트 → 승인** 자율 루프로 전환한다.

개발과 운영이 같은 루프를 공유하고(트리거만 다름), 돌 때마다 테스트 케이스와 규칙이 축적되어 하네스가 강화되는 구조를 만든다.

## What Changes

- **스킬 간 상태 전달 구조** 도입 (gstack `~/.gstack/projects/` 패턴 참고) — 각 에이전트/스킬이 결과를 구조화된 파일로 저장하고 다음 단계가 읽는 방식. 현재 `last_action_context`의 확장
- **단계별 강제 검증 프롬프트** 구성 (gstack `/plan-ceo-review` 8,500줄, `/qa` 11단계 패턴 참고) — 체크리스트가 아닌 의사결정 플레이북 수준의 프롬프트. 구현 시 gstack `/qa` 스킬 상세 분석 필요
- 하네스 에러 메시지에 **에이전트용 수정 지침(fix_hint)** 추가 — 사용자용 메시지와 별도로, 수정 에이전트가 바로 활용할 수 있는 코드 수준 가이드
- 테스트 실패 시 **실패 패턴을 contracts/*.yaml에 자동 축적**하는 구조 — 실패 로그 → 새 invariant → 테스트 케이스 추가
- **아키텍처 가디언 검증** — request_action 단일 게이트, YAML SSOT, LLM/코드 분리 등 선언적 구조 불변 규칙을 코드로 검증
- **few-shot 드리프트 감지** — 라우팅 실패 패턴 분석 → few-shot 커버리지 부족 자동 판단
- Langfuse 에러 로그 → 분석 → 수정 → 테스트 → 리포트 **파이프라인 구축** (운영 트리거)
- 개발 시 코드 변경 후 → 아키텍처 검증 → 테스트 → 구조 확인 **스킬/훅 체인** (개발 트리거)

## Capabilities

### New Capabilities
- `agent-state-relay`: 에이전트/스킬 간 결과 전달 구조. 각 단계가 구조화된 결과 파일을 저장하고 다음 단계가 읽음 (gstack projects/ 패턴 + 현재 last_action_context 확장). 아키텍처 검증 결과 → 수정 에이전트, 테스트 실패 로그 → 리포트 에이전트 등
- `guardian-playbook`: 아키텍처 가디언의 단계별 강제 검증 프롬프트. 체크리스트가 아닌 의사결정 플레이북 (gstack /qa 11단계, /plan-ceo-review 10단계 구조 참고). 구현 시 gstack 레포 상세 분석하여 프롬프트 깊이 참고
- `error-fix-hints`: 하네스/API 에러 메시지에 에이전트용 수정 지침(fix_hint) 이중화. 사용자 메시지와 별도로 코드 수준 수정 가이드 포함
- `test-failure-accumulation`: 테스트 실패 시 실패 패턴을 contracts/*.yaml에 자동 추가하고, 해당 invariant 기반 테스트 케이스 생성
- `architecture-guardian`: 선언적 아키텍처 불변 규칙(request_action 단일 게이트, YAML SSOT 참조 무결성, orchestrator 직접 응답 금지 등)을 자동 검증하는 체커
- `fewshot-drift-detection`: 라우팅 실패 로그 분석 → few-shot 커버리지 부족 패턴 감지 → 추가 제안. 두 가지 수집 경로: (A) "executor 진입 → harness 에러" 패턴에서 입력을 자동 수집하여 "이 패턴은 executor로 오면 안 됨" few-shot 후보 생성 (하네스 로그만으로 가능), (B) 운영 매니저 사후 피드백("이거 아닌데?")을 정답 라벨로 활용
- `tacit-knowledge-accumulation`: 암묵지 자동 명시화 구조. 에이전트 실행 루프에서 "기대 vs 실제" 불일치를 자동 수집하고 문서/규칙/테스트로 변환. harness 에러 로그에 입력 컨텍스트 동반 저장 → 패턴 분석 → contracts/few-shot/YAML 규칙 축적 제안. doc-gardening(오래된 문서 자동 정리 PR)도 이 구조의 일부
- `maintenance-pipeline`: Langfuse 에러 수집 → 분석 → 패치 생성 → 테스트 → 리포트 → 승인 대기의 운영 자율 루프
- `dev-validation-chain`: 코드 변경 후 아키텍처 검증 → 테스트 → 구조 확인의 개발 자동화 체인

### Modified Capabilities
- `harness`: _error() 응답에 fix_hint 필드 추가, 에러 메시지 구조 확장

## Impact

- `src/harness.py` — _error() 메서드 시그니처 확장, AgentResponse data 필드에 fix_hint 추가
- `src/agents/response.py` — AgentResponse에 fix_hint 옵셔널 필드
- `contracts/*.yaml` — 자동 추가 구조 도입, 스키마 확장 가능
- `tests/` — 실패 패턴 축적 스크립트/훅 추가
- `actions/registry.yaml`, `domain/visibility_chain.yaml` — 참조 무결성 검증 대상
- Langfuse 연동 — 에러 로그 구조화 수집 파이프라인, 라우팅 로그에 입력 컨텍스트 동반 저장
- 새 스크립트/스킬 — architecture-check, test-accumulate, maintenance-report, doc-gardening
- 암묵지 명시화 — "에이전트가 읽을 수 없는 것은 존재하지 않는 것" 원칙. Slack/구두 합의도 리포지터리에 커밋되어야 에이전트가 활용 가능

## References

- [하네스 엔지니어링 — 에이전트 우선 세계에서 Codex 활용하기](https://openai.com/ko-KR/index/harness-engineering/) (2026-03-15) — OpenAI Codex 팀: 3명×5개월 100만 줄, 린트 에러에 수정 지침 주입, doc-gardening 에이전트, AGENTS.md 목차 패턴, Types→Config→Repo→Service→Runtime→UI 계층 강제, "읽을 수 없는 것은 존재하지 않는 것", 암묵지 좁히기
- [하네스 엔지니어링 — 에이전트 팀 구축의 시대](https://news.hada.io/weekly/202613) (2026-03-30) — gstack(고정 스킬 체인) vs Harness 황민호(동적 팀 자동 생성), 토큰=생산 단위
- [하네스 엔지니어링 — AI 에이전트 시대의 경쟁력은 모델이 아니라 마구에서 나온다](https://wikidocs.net/blog/@jaehong/9481/) (2026-03-20) — "실수할 때마다 재발 방지 구조 설계", 모델 변경 없이 하네스만 개선 → LangChain 30위→5위
- [하네스 엔지니어링 따라하기](https://youtube.com/watch?v=kSlYNeEkdAM) (2026-03-31) — 4요소(레포 하네스, 앱 하네스, 헌법, 암묵지), 암묵지 좁히기 실습 플로우
- [gstack](https://github.com/garrytan/gstack) — Garry Tan(YC CEO) 23개 스킬, /qa 11단계 테스트→수정→리그레션 루프, /plan-ceo-review 8,500줄 플레이북, ~/.gstack/projects/ 스킬 간 상태 전달
