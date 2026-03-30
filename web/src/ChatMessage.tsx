import { marked } from 'marked'
import type { ChatMessage as ChatMessageData, AgentButton } from './types'
import { ActionButton } from './ActionButton'
import { StepIndicator } from './StepIndicator'

marked.setOptions({ breaks: true })

interface ChatMessageProps {
  message: ChatMessageData
  isLatest: boolean
  onClickButton: (button: AgentButton) => void
  onNavigate: (url: string) => void
}

const MODE_COLORS: Record<string, string> = {
  guide: '#4caf50',
  execute: '#2196f3',
  diagnose: '#ff9800',
  error: '#f44336',
  reject: '#f44336',
  select: '#9c27b0',
  wizard: '#673ab7',
  launch_check: '#00bcd4',
  done: '#4caf50',
}

export function ChatMessage({ message, isLatest, onClickButton, onNavigate }: ChatMessageProps) {
  const isUser = message.role === 'user'
  const borderColor = !isUser && message.mode ? MODE_COLORS[message.mode] : undefined

  return (
    <div
      style={{
        alignSelf: isUser ? 'flex-end' : 'flex-start',
        maxWidth: '85%',
        display: 'flex',
        flexDirection: 'column',
        gap: '8px',
      }}
    >
      {/* 스텝 인디케이터 */}
      {!isUser && message.step && <StepIndicator step={message.step} />}

      {/* 메시지 본문 */}
      <div
        className="agent-message"
        style={{
          padding: '12px 16px',
          borderRadius: '12px',
          borderBottomRightRadius: isUser ? '4px' : '12px',
          borderBottomLeftRadius: isUser ? '12px' : '4px',
          background: isUser ? '#1a1a2e' : 'white',
          color: isUser ? 'white' : '#333',
          boxShadow: isUser ? 'none' : '0 1px 3px rgba(0,0,0,0.1)',
          borderLeft: borderColor ? `3px solid ${borderColor}` : undefined,
          fontSize: '14px',
          lineHeight: '1.6',
          wordBreak: 'break-word',
        }}
        dangerouslySetInnerHTML={
          !isUser ? { __html: renderMarkdown(message.content) } : undefined
        }
      >
        {isUser ? message.content : undefined}
      </div>

      {/* 버튼 */}
      {!isUser && message.buttons && message.buttons.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
          {message.buttons.map((btn, i) => (
            <ActionButton
              key={i}
              button={btn}
              disabled={message.buttonsDisabled ?? false}
              onClickButton={() => onClickButton(btn)}
              onNavigate={onNavigate}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function renderMarkdown(text: string): string {
  return marked.parse(text) as string
}
