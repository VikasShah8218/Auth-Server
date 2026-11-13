import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end tests against the real Auth Server on a throwaway database (see tests/e2e/serve_api.py).
 *
 *   AUTH_PYTHON=../server/.venv/Scripts/python npm run e2e
 *
 * AUTH_PYTHON is the Python that has the auth-server's requirements installed. The browser is the locally
 * installed Microsoft Edge (PW_CHANNEL=chrome for Chrome), so no browser download is needed.
 */
const python = process.env.AUTH_PYTHON ?? "python";

export default defineConfig({
  testDir: "tests/e2e",
  fullyParallel: false,
  workers: 1,
  timeout: 30_000,
  expect: { timeout: 7_000 },
  reporter: [["list"]],
  use: {
    baseURL: "http://localhost:5182",
    channel: process.env.PW_CHANNEL ?? "msedge",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Edge"], viewport: { width: 1440, height: 900 } } },
  ],
  webServer: [
    {
      command: `"${python}" tests/e2e/serve_api.py`,
      url: "http://127.0.0.1:8010/health/ready",
      timeout: 120_000,
      reuseExistingServer: false,
      stdout: "pipe",
    },
    {
      command: "npx vite --port 5182",
      url: "http://localhost:5182/login",
      env: { API_TARGET: "http://127.0.0.1:8010", PORT: "5182" },
      timeout: 60_000,
      reuseExistingServer: false,
    },
  ],
});
