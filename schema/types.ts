/**
 * 에이전트 서버 ↔ 패널 공유 스키마.
 * Source of truth. Python 측은 Pydantic으로 미러링.
 */

// ─── Chat Mode ───

export type ChatMode =
  | 'idle'          // 기본 대화
  | 'diagnose'      // 진단 결과
  | 'guide'         // 페이지 이동 안내
  | 'execute'       // 실행 확인 대기
  | 'done'          // 작업 완료
  | 'wizard'        // 위저드 진행 중
  | 'launch_check'  // 런칭 체크 결과
  | 'select'        // 선택 대기 (채팅 내)
  | 'error'         // 오류
  | 'reject'        // 거부

// ─── Button ───

export type ButtonClickable = 'once' | 'always'
export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger'

export interface AgentButton {
  type: 'select' | 'action' | 'navigate'
  label: string

  /** select: 선택 값 */
  value?: string
  /** action: 실행 종류 ('execute' | 'cancel' | 'back' | 커스텀) */
  action?: string
  /** navigate: 이동 URL */
  url?: string

  /**
   * 클릭 동작 제어.
   * - 'once': 클릭 후 같은 메시지 내 모든 once 버튼 비활성화
   * - 'always': 항상 활성 (이전 메시지여도 클릭 가능)
   *
   * 기본값: select='once', action='once', navigate='always'
   */
  clickable: ButtonClickable

  variant: ButtonVariant

  /** 버튼 아래 부연 설명 */
  description?: string
}

// ─── Step Progress ───

export interface StepProgress {
  /** 현재 스텝 (0-indexed) */
  current: number
  /** 전체 스텝 수 */
  total: number
  /** 현재 스텝 이름 */
  label: string
  /** 전체 스텝 이름 배열 */
  steps: string[]
}

// ─── Agent Response ───

export interface AgentResponse {
  /** 마크다운 메시지 */
  message: string
  /** 버튼 배열 (빈 배열 가능) */
  buttons: AgentButton[]
  /** 현재 모드 */
  mode: ChatMode
  /** 위저드 진행 상태 (위저드가 아닐 때 null) */
  step: StepProgress | null
  /** 부가 정보 */
  meta: AgentResponseMeta
}

export interface AgentResponseMeta {
  /** Mock 모드 여부 */
  mock_mode?: boolean
}

// ─── SSE Events ───

export interface SSETextEvent {
  text: string
}

export interface SSEProgressEvent {
  message: string
  tool: string
  count: number
}

/** done 이벤트의 data는 AgentResponse 전체 */
export type SSEDoneEvent = AgentResponse

export interface SSEErrorEvent {
  message: string
  code?: string
}

// ─── Request ───

export interface ChatRequest {
  message?: string
  button?: ButtonInput
  wizard_action?: string
  session_id?: string
  context?: ChatContext
}

export interface ButtonInput {
  type: 'select' | 'action'
  value?: string
  action?: string
}

export interface ChatContext {
  token?: string
  currentPath?: string
  masterId?: string
  productPageId?: string
  role?: string
  permissions?: string[]
}

// ─── Wizard Action (GET /wizard/actions) ───

export interface WizardAction {
  action: string
  label: string
  description?: string
  icon?: string
}

// ─── Panel Props ───

export interface AgentPanelProps {
  /** 에이전트 서버 URL */
  apiUrl: string
  /** 인증 토큰 조회 (매 요청마다 호출) */
  getToken: () => string
  /** 페이지 이동 핸들러 (navigate 버튼 클릭 시) */
  onNavigate: (url: string) => void
  /** 현재 페이지 컨텍스트 */
  context?: Omit<ChatContext, 'token'>
  /** 패널 열림/닫힘 */
  open?: boolean
  onOpenChange?: (open: boolean) => void
  /** 테마 */
  theme?: 'light' | 'dark'
}
