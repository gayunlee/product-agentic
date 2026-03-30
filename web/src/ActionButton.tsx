import type { AgentButton } from './types'

interface ActionButtonProps {
  button: AgentButton
  disabled: boolean
  onClickButton: () => void
  onNavigate: (url: string) => void
}

const VARIANT_STYLES: Record<string, string> = {
  primary: 'background: #1a1a2e; color: white; border: none;',
  secondary: 'background: white; color: #333; border: 1px solid #ddd;',
  ghost: 'background: transparent; color: #666; border: 1px solid transparent;',
  danger: 'background: #e94560; color: white; border: none;',
}

export function ActionButton({ button, disabled, onClickButton, onNavigate }: ActionButtonProps) {
  const style = VARIANT_STYLES[button.variant] || VARIANT_STYLES.secondary

  function handleClick() {
    if (disabled) return

    if (button.type === 'navigate' && button.url) {
      onNavigate(button.url)
      return
    }

    onClickButton()
  }

  const isDisabled = disabled && button.clickable === 'once'

  return (
    <button
      onClick={handleClick}
      disabled={isDisabled}
      style={{
        padding: '6px 12px',
        borderRadius: '6px',
        fontSize: '13px',
        cursor: isDisabled ? 'not-allowed' : 'pointer',
        opacity: isDisabled ? 0.5 : 1,
        ...parseStyle(style),
      }}
    >
      {button.label}
    </button>
  )
}

function parseStyle(css: string): Record<string, string> {
  const result: Record<string, string> = {}
  css.split(';').forEach((rule) => {
    const [key, value] = rule.split(':').map((s) => s.trim())
    if (key && value) {
      const camelKey = key.replace(/-([a-z])/g, (_, c) => c.toUpperCase())
      result[camelKey] = value
    }
  })
  return result
}
