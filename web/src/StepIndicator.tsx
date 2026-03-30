import type { StepProgress } from './types'

interface StepIndicatorProps {
  step: StepProgress
}

export function StepIndicator({ step }: StepIndicatorProps) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '4px', padding: '8px 0', fontSize: '12px' }}>
      {step.steps.map((label, i) => {
        const isDone = i < step.current
        const isCurrent = i === step.current
        return (
          <div key={i} style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
            {i > 0 && <span style={{ color: '#ccc' }}>→</span>}
            <span
              style={{
                padding: '2px 8px',
                borderRadius: '12px',
                background: isCurrent ? '#1a1a2e' : isDone ? '#e8f5e9' : '#f5f5f5',
                color: isCurrent ? 'white' : isDone ? '#2e7d32' : '#999',
                fontWeight: isCurrent ? 600 : 400,
              }}
            >
              {isDone ? '✓' : ''} {label}
            </span>
          </div>
        )
      })}
    </div>
  )
}
