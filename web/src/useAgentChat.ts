/**
 * 에이전트 채팅 상태 관리 훅.
 */

import { useState, useCallback, useRef } from 'react'
import type { AgentResponse, AgentButton, ChatMessage, WizardAction, ButtonInput } from './types'
import type { AgentApiConfig } from './api'
import { sendMessage, sendButton, startWizard, resetSession, getWizardActions } from './api'

function createId(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 6)
}

function createUserMessage(content: string): ChatMessage {
  return { id: createId(), role: 'user', content }
}

function createAssistantMessage(response: AgentResponse): ChatMessage {
  return {
    id: createId(),
    role: 'assistant',
    content: response.message,
    buttons: response.buttons,
    mode: response.mode,
    step: response.step ?? undefined,
  }
}

export interface UseAgentChatOptions {
  config: AgentApiConfig
}

export function useAgentChat({ config }: UseAgentChatOptions) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [loading, setLoading] = useState(false)
  const [loadingText, setLoadingText] = useState('')
  const [wizardActions, setWizardActions] = useState<WizardAction[]>([])
  const [currentMode, setCurrentMode] = useState<string>('idle')
  const configRef = useRef(config)
  configRef.current = config

  const addMessage = useCallback((msg: ChatMessage) => {
    setMessages((prev) => [...prev, msg])
  }, [])

  const handleResponse = useCallback(
    (response: AgentResponse) => {
      addMessage(createAssistantMessage(response))
      setCurrentMode(response.mode)
    },
    [addMessage],
  )

  /** 텍스트 메시지 전송 */
  const send = useCallback(
    async (text: string) => {
      if (!text.trim() || loading) return

      addMessage(createUserMessage(text))
      setLoading(true)
      setLoadingText('요청 분석 중...')

      try {
        const response = await sendMessage(configRef.current, text)
        handleResponse(response)
      } catch (err) {
        addMessage({
          id: createId(),
          role: 'assistant',
          content: `오류가 발생했습니다: ${err instanceof Error ? err.message : '알 수 없는 오류'}`,
          mode: 'error',
        })
      } finally {
        setLoading(false)
        setLoadingText('')
      }
    },
    [loading, addMessage, handleResponse],
  )

  /** 버튼 클릭 처리 */
  const clickButton = useCallback(
    async (button: AgentButton, messageId: string) => {
      // navigate 버튼은 API 호출 안 함
      if (button.type === 'navigate') return

      // once 버튼 클릭 → 해당 메시지의 모든 once 버튼 비활성화
      if (button.clickable === 'once') {
        setMessages((prev) =>
          prev.map((msg) => (msg.id === messageId ? { ...msg, buttonsDisabled: true } : msg)),
        )
      }

      setLoading(true)

      try {
        const input: ButtonInput = { type: button.type as 'select' | 'action' }
        if (button.type === 'select') input.value = button.value
        if (button.type === 'action') input.action = button.action

        const response = await sendButton(configRef.current, input)
        handleResponse(response)
      } catch (err) {
        addMessage({
          id: createId(),
          role: 'assistant',
          content: `오류가 발생했습니다: ${err instanceof Error ? err.message : '알 수 없는 오류'}`,
          mode: 'error',
        })
      } finally {
        setLoading(false)
      }
    },
    [addMessage, handleResponse],
  )

  /** 위저드 시작 */
  const startWizardAction = useCallback(
    async (action: string) => {
      setLoading(true)
      try {
        const response = await startWizard(configRef.current, action)
        handleResponse(response)
      } catch (err) {
        addMessage({
          id: createId(),
          role: 'assistant',
          content: `위저드 시작 실패: ${err instanceof Error ? err.message : '알 수 없는 오류'}`,
          mode: 'error',
        })
      } finally {
        setLoading(false)
      }
    },
    [addMessage, handleResponse],
  )

  /** 위저드 액션 목록 로드 */
  const loadWizardActions = useCallback(async () => {
    try {
      const actions = await getWizardActions(configRef.current)
      setWizardActions(actions)
    } catch {
      // 실패해도 무시 — 위저드 메뉴만 안 보임
    }
  }, [])

  /** 세션 초기화 */
  const clear = useCallback(async () => {
    setMessages([])
    setCurrentMode('idle')
    try {
      await resetSession(configRef.current)
    } catch {
      // 실패해도 로컬은 초기화
    }
  }, [])

  return {
    messages,
    loading,
    loadingText,
    currentMode,
    wizardActions,
    send,
    clickButton,
    startWizardAction,
    loadWizardActions,
    clear,
  }
}
