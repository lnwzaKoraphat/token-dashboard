import { defineConfig, chromium } from '@playwright/test';
import { existsSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { homedir } from 'node:os';

// Reuse an already-installed Chromium (no downloads). Priority:
//   1. SUBSPLIT_CHROMIUM env var  2. the revision this Playwright expects  3. newest installed revision in the cache.
function findChromium() {
  if (process.env.SUBSPLIT_CHROMIUM) return process.env.SUBSPLIT_CHROMIUM;
  const expected = chromium.executablePath();
  if (expected && existsSync(expected)) return undefined; // default resolution works
  const base = process.env.PLAYWRIGHT_BROWSERS_PATH || join(process.env.LOCALAPPDATA || join(homedir(), 'AppData', 'Local'), 'ms-playwright');
  if (!existsSync(base)) return undefined;
  const newest = (prefix) => readdirSync(base).filter((d) => d.startsWith(prefix + '-')).sort((a, b) => Number(b.split('-').pop()) - Number(a.split('-').pop()));
  const candidates = [
    ...newest('chromium_headless_shell').map((d) => join(base, d, 'chrome-headless-shell-win64', 'chrome-headless-shell.exe')),
    ...newest('chromium').map((d) => join(base, d, 'chrome-win64', 'chrome.exe')),
  ];
  return candidates.find((p) => existsSync(p));
}

const executablePath = findChromium();

// Two viewports per spec: 390x844 (phone, primary) and 1280x800 (desktop).
export default defineConfig({
  testDir: '.',
  testMatch: '*.spec.mjs',
  timeout: 30_000,
  expect: { timeout: 7_000 },
  fullyParallel: true,
  retries: 0,
  reporter: 'list',
  outputDir: '../../test-results',
  use: {
    browserName: 'chromium',
    ignoreHTTPSErrors: true,
    locale: 'th-TH',
    timezoneId: 'Asia/Bangkok',
    launchOptions: executablePath ? { executablePath } : {},
  },
  projects: [
    { name: 'mobile-390x844', use: { viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true } },
    { name: 'desktop-1280x800', use: { viewport: { width: 1280, height: 800 } } },
  ],
});
