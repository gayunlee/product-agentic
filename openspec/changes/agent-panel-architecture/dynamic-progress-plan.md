# 진행 상황 메시지 — 랜덤 펀 메시지

## 문제

현재 `TOOL_PROGRESS` 딕셔너리가 tool_name → 고정 문자열 매핑이라:
- 실제 파라미터와 무관한 메시지 표시 ("도메인 지식 검색 중" — 실제로는 검색 안 함)
- 모든 호출이 동일 메시지 → 단계 전환이 안 느껴짐
- 잘못된 정보를 주느니 차라리 안 주는 게 나음

## 제안

Tool 호출마다 **랜덤 펀 메시지**를 표시. Claude Code의 jazzing/buzzing 스타일.
매 tool 호출마다 다른 메시지가 나오므로 단계 전환이 느껴짐.

### 예시 메시지 풀

```python
PROGRESS_MESSAGES = [
    "상품 세팅 살펴보는 중...",
    "데이터 뒤적뒤적...",
    "관리자센터 탐험 중...",
    "설정값 확인하는 중...",
    "꼼꼼히 체크하는 중...",
    "정보 수집 중...",
    "열심히 일하는 중...",
    "거의 다 됐어요...",
    "조금만 기다려주세요...",
    "열심히 찾고 있어요...",
    "세팅 분석 중...",
    "노출 조건 확인 중...",
]
```

## 구현

### 서버 (`server.py`)

```python
import random

PROGRESS_MESSAGES = [...]  # 위 메시지 풀

# StreamingCallbackHandler에서:
progress = random.choice(PROGRESS_MESSAGES)
```

- 기존 `TOOL_PROGRESS` 딕셔너리 제거
- tool_name 매핑 불필요 — 랜덤 선택만
- 연속 같은 메시지 방지: 직전 메시지와 다른 것 선택

### 프론트

변경 불필요. 서버가 보내는 메시지만 바뀜.

## 스코프

- [ ] `PROGRESS_MESSAGES` 리스트 작성
- [ ] `StreamingCallbackHandler` 수정 (random.choice)
- [ ] 기존 `TOOL_PROGRESS` 딕셔너리 제거
- [ ] 연속 중복 방지 로직
