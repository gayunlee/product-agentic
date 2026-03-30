import { useState } from 'react'
import { createRoot } from 'react-dom/client'
import { AgentPanel } from '../src'

function TokenInput() {
  const [value, setValue] = useState(localStorage.getItem('agent_token') || '')
  const saved = !!localStorage.getItem('agent_token')

  function save() {
    const trimmed = value.trim()
    if (trimmed) {
      localStorage.setItem('agent_token', trimmed)
      window.location.reload()
    }
  }

  function clear() {
    localStorage.removeItem('agent_token')
    setValue('')
    window.location.reload()
  }

  return (
    <div style={{ marginTop: '16px' }}>
      <div style={{ fontSize: '13px', color: '#666', marginBottom: '4px' }}>
        Access Token {saved ? '(저장됨)' : '(없음)'}
      </div>
      <div style={{ display: 'flex', gap: '8px' }}>
        <input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="eyJhbGci..."
          style={{
            flex: 1,
            padding: '8px 12px',
            border: '1px solid #ccc',
            borderRadius: '6px',
            fontSize: '12px',
            fontFamily: 'monospace',
          }}
        />
        <button
          onClick={save}
          style={{
            padding: '8px 16px',
            background: '#1a1a2e',
            color: 'white',
            border: 'none',
            borderRadius: '6px',
            cursor: 'pointer',
            fontSize: '12px',
          }}
        >
          저장
        </button>
        {saved && (
          <button
            onClick={clear}
            style={{
              padding: '8px 12px',
              background: '#e94560',
              color: 'white',
              border: 'none',
              borderRadius: '6px',
              cursor: 'pointer',
              fontSize: '12px',
            }}
          >
            삭제
          </button>
        )}
      </div>
    </div>
  )
}

function App() {
  return (
    <div style={{ height: '100vh', background: '#e8e8e8', position: 'relative' }}>
      <div style={{ padding: '40px', maxWidth: '600px' }}>
        <h1 style={{ fontSize: '24px', marginBottom: '16px' }}>Agent Panel Playground</h1>
        <p style={{ color: '#666' }}>
          에이전트 서버를 <code>localhost:8000</code>에 띄운 뒤 패널을 테스트하세요.
        </p>
        <TokenInput />
      </div>
      <AgentPanel
        apiUrl="http://localhost:8000"
        getToken={() => localStorage.getItem('agent_token') || ''}
        onNavigate={(url) => {
          console.log('Navigate:', url)
          alert(`Navigate to: ${url}`)
        }}
      />
    </div>
  )
}

createRoot(document.getElementById('root')!).render(<App />)
