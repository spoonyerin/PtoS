import { defineConfig } from '@playwright/test'

// Windows는 webServer 명령을 cmd로 실행하므로 venv 경로와 구분자가 다르다.
const python = process.platform === 'win32' ? '..\\.venv\\Scripts\\python.exe' : '../.venv/bin/python'

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  use: {
    baseURL: 'http://127.0.0.1:5173',
    launchOptions: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH
      ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH }
      : {},
    trace: 'retain-on-failure',
  },
  webServer: [
    {
      command: `${python} -m uvicorn app.main:app --app-dir ../backend --host 127.0.0.1 --port 8000 --no-access-log`,
      url: 'http://127.0.0.1:8000/api/v1/health/ready',
      // 기본 e2e는 모델 없이 규칙 결과를 검증한다. 모델을 켠 서버를 재사용하면 기대값이 달라진다.
      env: { PTOS_MODEL_PATH: '' },
      reuseExistingServer: !process.env.CI,
    },
    {
      command: 'npm run dev -- --host 127.0.0.1',
      url: 'http://127.0.0.1:5173',
      reuseExistingServer: !process.env.CI,
    },
  ],
})
