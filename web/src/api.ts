/**
 * 에이전트 서버 API 클라이언트.
 */

import type { AgentResponse, ChatContext, WizardAction, ButtonInput } from './types'

export interface AgentApiConfig {
  apiUrl: string
  getToken: () => string
  context?: Omit<ChatContext, 'token'>
}

function buildContext(config: AgentApiConfig): ChatContext {
  return {
    token: config.getToken(),
    ...config.context,
  }
}

async function post<T>(config: AgentApiConfig, path: string, body: Record<string, unknown>): Promise<T> {
  const res = await fetch(`${config.apiUrl}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...body, context: buildContext(config) }),
  })
  if (!res.ok) {
    throw new Error(`Agent API error: ${res.status} ${res.statusText}`)
  }
  return res.json()
}

/** 텍스트 메시지 전송 */
export async function sendMessage(config: AgentApiConfig, message: string): Promise<AgentResponse> {
  return post(config, '/chat', { message })
}

/** 버튼 클릭 전송 */
export async function sendButton(config: AgentApiConfig, button: ButtonInput): Promise<AgentResponse> {
  return post(config, '/chat', { button })
}

/** 위저드 시작 */
export async function startWizard(config: AgentApiConfig, wizardAction: string): Promise<AgentResponse> {
  return post(config, '/chat', { wizard_action: wizardAction })
}

/** 세션 초기화 */
export async function resetSession(config: AgentApiConfig): Promise<void> {
  await post(config, '/reset', {})
}

/** 위저드 액션 목록 조회 */
export async function getWizardActions(config: AgentApiConfig): Promise<WizardAction[]> {
  const res = await fetch(`${config.apiUrl}/wizard/actions`)
  if (!res.ok) throw new Error(`Failed to fetch wizard actions: ${res.status}`)
  return res.json()
}

/** SSE 스트리밍 */
export function streamMessage(
  config: AgentApiConfig,
  message: string,
  handlers: {
    onText?: (text: string) => void
    onProgress?: (message: string, tool: string, count: number) => void
    onDone?: (response: AgentResponse) => void
    onError?: (message: string) => void
  },
): AbortController {
  const controller = new AbortController()
  const context = buildContext(config)

  fetch(`${config.apiUrl}/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, context }),
    signal: controller.signal,
  })
    .then(async (res) => {
      if (!res.ok || !res.body) {
        handlers.onError?.(`Stream error: ${res.status}`)
        return
      }

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        let currentEvent = ''
        for (const line of lines) {
          if (line.startsWith('event: ')) {
            currentEvent = line.slice(7).trim()
          } else if (line.startsWith('data: ') && currentEvent) {
            try {
              const data = JSON.parse(line.slice(6))
              switch (currentEvent) {
                case 'text':
                  handlers.onText?.(data.text)
                  break
                case 'progress':
                  handlers.onProgress?.(data.message, data.tool, data.count)
                  break
                case 'done':
                  handlers.onDone?.(data)
                  break
                case 'error':
                  handlers.onError?.(data.message)
                  break
              }
            } catch {
              // JSON 파싱 실패 무시
            }
            currentEvent = ''
          }
        }
      }
    })
    .catch((err) => {
      if (err.name !== 'AbortError') {
        handlers.onError?.(err.message)
      }
    })

  return controller
}
