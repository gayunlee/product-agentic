import { useState, useEffect, useRef, type FormEvent } from 'react'
import type { AgentPanelProps, AgentButton } from './types'
import { useAgentChat } from './useAgentChat'
import { ChatMessage } from './ChatMessage'

export function AgentPanel({
  apiUrl,
  getToken,
  onNavigate,
  context,
  open: controlledOpen,
  onOpenChange,
  theme = 'light',
}: AgentPanelProps) {
  const [internalOpen, setInternalOpen] = useState(false)
  const isOpen = controlledOpen ?? internalOpen
  const setOpen = onOpenChange ?? setInternalOpen

  const {
    messages,
    loading,
    loadingText,
    currentMode,
    wizardActions,
    queueCount,
    queuedMessages,
    send,
    clickButton,
    startWizardAction,
    loadWizardActions,
    clear,
  } = useAgentChat({
    config: { apiUrl, getToken, context },
  })

  const [input, setInput] = useState('')
  const [wizardMenuOpen, setWizardMenuOpen] = useState(false)
  const chatEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (isOpen) loadWizardActions()
  }, [isOpen, loadWizardActions])

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  const isWizardMode = currentMode === 'wizard'

  function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (!input.trim() || isWizardMode) return
    send(input.trim())
    setInput('')
  }

  function handleButtonClick(button: AgentButton, messageId: string) {
    if (button.type === 'navigate' && button.url) {
      onNavigate(button.url)
      return
    }
    clickButton(button, messageId)
  }

  if (!isOpen) {
    return (
      <button
        onClick={() => setOpen(true)}
        style={{
          position: 'fixed',
          right: '24px',
          bottom: '24px',
          width: '48px',
          height: '48px',
          borderRadius: '50%',
          background: '#1a1a2e',
          color: 'white',
          border: 'none',
          cursor: 'pointer',
          fontSize: '20px',
          boxShadow: '0 2px 8px rgba(0,0,0,0.2)',
          zIndex: 50,
        }}
      >
        💬
      </button>
    )
  }

  const isDark = theme === 'dark'

  return (
    <div
      style={{
        position: 'fixed',
        right: 0,
        top: 0,
        bottom: 0,
        width: '400px',
        background: isDark ? '#1a1a2e' : '#f5f5f5',
        borderLeft: '1px solid #e0e0e0',
        display: 'flex',
        flexDirection: 'column',
        zIndex: 50,
        fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
      }}
    >
      {/* 헤더 */}
      <div
        style={{
          padding: '12px 16px',
          background: '#1a1a2e',
          color: 'white',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}
      >
        <span style={{ fontWeight: 600, fontSize: '14px' }}>상품 세팅 에이전트</span>
        <div style={{ display: 'flex', gap: '8px' }}>
          <button
            onClick={clear}
            style={{ background: 'transparent', color: '#aaa', border: 'none', cursor: 'pointer', fontSize: '12px' }}
          >
            초기화
          </button>
          <button
            onClick={() => setOpen(false)}
            style={{ background: 'transparent', color: '#aaa', border: 'none', cursor: 'pointer', fontSize: '16px' }}
          >
            ✕
          </button>
        </div>
      </div>

      {/* 위저드 메뉴 */}
      {wizardActions.length > 0 && (
        <div style={{ borderBottom: '1px solid #e0e0e0' }}>
          <button
            onClick={() => setWizardMenuOpen(!wizardMenuOpen)}
            style={{
              width: '100%',
              padding: '8px 16px',
              background: 'white',
              border: 'none',
              cursor: 'pointer',
              fontSize: '13px',
              textAlign: 'left',
              color: '#666',
            }}
          >
            {wizardMenuOpen ? '▾' : '▸'} 빠른 실행
          </button>
          {wizardMenuOpen && (
            <div style={{ padding: '0 16px 8px', display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
              {wizardActions.map((wa) => (
                <button
                  key={wa.action}
                  onClick={() => {
                    startWizardAction(wa.action)
                    setWizardMenuOpen(false)
                  }}
                  disabled={loading}
                  style={{
                    padding: '6px 12px',
                    borderRadius: '6px',
                    border: '1px solid #ddd',
                    background: 'white',
                    cursor: loading ? 'not-allowed' : 'pointer',
                    fontSize: '12px',
                  }}
                >
                  {wa.icon ?? ''} {wa.label}
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {/* 채팅 영역 */}
      <div
        style={{
          flex: 1,
          overflowY: 'auto',
          padding: '16px',
          display: 'flex',
          flexDirection: 'column',
          gap: '12px',
        }}
      >
        {messages.length === 0 && (
          <div style={{ textAlign: 'center', color: '#999', fontSize: '13px', marginTop: '40px' }}>
            상품 세팅을 시작하려면 요청을 입력하세요.
          </div>
        )}
        {messages.map((msg, i) => (
          <ChatMessage
            key={msg.id}
            message={msg}
            isLatest={i === messages.length - 1}
            onClickButton={(btn) => handleButtonClick(btn, msg.id)}
            onNavigate={onNavigate}
          />
        ))}
        {loading && (
          <div style={{ alignSelf: 'flex-start', color: '#666', fontSize: '13px', padding: '8px' }}>
            {loadingText || '처리 중...'}
          </div>
        )}
        {queuedMessages.length > 0 && queuedMessages.map((msg, i) => (
          <div key={`q-${i}`} style={{
            alignSelf: 'flex-end',
            background: '#e8e8e8',
            padding: '8px 14px',
            borderRadius: '12px',
            fontSize: '14px',
            color: '#999',
            maxWidth: '75%',
          }}>
            {msg}
            <span style={{ fontSize: '11px', marginLeft: '8px', color: '#bbb' }}>대기 중</span>
          </div>
        ))}
        <div ref={chatEndRef} />
      </div>

      {/* 입력 영역 */}
      <form
        onSubmit={handleSubmit}
        style={{
          padding: '12px 16px',
          borderTop: '1px solid #e0e0e0',
          background: 'white',
          display: 'flex',
          gap: '8px',
        }}
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          disabled={isWizardMode}
          placeholder={isWizardMode ? '위저드 진행 중 — 버튼을 선택하세요' : loading ? '메시지 입력 → 큐에 추가됩니다' : '메시지 입력...'}
          style={{
            flex: 1,
            padding: '10px 14px',
            border: '1px solid #ddd',
            borderRadius: '8px',
            fontSize: '14px',
            outline: 'none',
          }}
        />
        <button
          type="submit"
          disabled={!input.trim() || isWizardMode}
          style={{
            padding: '10px 20px',
            background: '#1a1a2e',
            color: 'white',
            border: 'none',
            borderRadius: '8px',
            cursor: 'pointer',
            fontSize: '14px',
            opacity: !input.trim() || isWizardMode ? 0.5 : 1,
          }}
        >
          전송
        </button>
      </form>
    </div>
  )
}
