import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import { ServiceStatusProvider } from './hooks/useServiceStatus'
import './styles.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode><ServiceStatusProvider><App /></ServiceStatusProvider></React.StrictMode>,
)
