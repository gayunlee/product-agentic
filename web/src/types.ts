/**
 * 패널 내부 타입. 서버 스키마(schema/types.ts) re-export + UI 전용 타입.
 */

// 서버 스키마 re-export
export type {
  AgentResponse,
  AgentButton,
  ButtonClickable,
  ButtonVariant,
  ChatMode,
  StepProgress,
  AgentResponseMeta,
  ChatRequest,
  ButtonInput,
  ChatContext,
  WizardAction,
  AgentPanelProps,
  SSETextEvent,
  SSEProgressEvent,
  SSEDoneEvent,
  SSEErrorEvent,
} from '../../schema/types'

// UI 전용 타입

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  buttons?: import('../../schema/types').AgentButton[]
  mode?: import('../../schema/types').ChatMode
  step?: import('../../schema/types').StepProgress
  /** 이 메시지의 once 버튼이 클릭되었는지 */
  buttonsDisabled?: boolean
}
