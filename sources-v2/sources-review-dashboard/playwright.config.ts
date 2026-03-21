import type { PlaywrightTestConfig } from "@playwright/test";

const config: PlaywrightTestConfig = {
  testDir: "./tests",
  timeout: 300_000,
  expect: {
    timeout: 10_000,
  },
  use: {
    baseURL: "http://127.0.0.1:3100",
    viewport: {
      width: 1480,
      height: 1080,
    },
    ignoreHTTPSErrors: true,
  },
  webServer: {
    command: "npm run start -- --hostname 127.0.0.1 --port 3100",
    port: 3100,
    reuseExistingServer: true,
    timeout: 120_000,
  },
};

export default config;
