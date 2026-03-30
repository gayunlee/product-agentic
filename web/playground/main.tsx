import { createRoot } from 'react-dom/client'
import { AgentPanel } from '../src'

function App() {
  return (
    <div style={{ height: '100vh', background: '#e8e8e8', position: 'relative' }}>
      <div style={{ padding: '40px', maxWidth: '600px' }}>
        <h1 style={{ fontSize: '24px', marginBottom: '16px' }}>Agent Panel Playground</h1>
        <p style={{ color: '#666' }}>
          에이전트 서버를 <code>localhost:8000</code>에 띄운 뒤 패널을 테스트하세요.
        </p>
        <p style={{ color: '#666', marginTop: '8px' }}>
          우측 하단 💬 버튼을 클릭하면 패널이 열립니다.
        </p>
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
