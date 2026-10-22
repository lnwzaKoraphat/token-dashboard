// AC-05 smoke: the real server serves the page (empty profiles dir); /api/usage is mocked per test.
import { test, expect } from '@playwright/test';
import { spawn } from 'node:child_process';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const PY = process.env.PYTHON || 'C:/Users/DcF/AppData/Local/Microsoft/WindowsApps/python.exe';
const ROOT = fileURLToPath(new URL('../../', import.meta.url));
const PORT = 8790 + Math.floor(Math.random() * 50);
let proc;

test.beforeAll(async () => {
  proc = spawn(PY, [join(ROOT, 'server.py'), '--port', String(PORT), '--base', mkdtempSync(join(tmpdir(), 'td-'))], { stdio: 'ignore' });
  for (let i = 0; i < 50; i++) {
    // drain the body: undici asserts if the server closes the socket on an unread >16 KB response
    try { const r = await fetch(`http://127.0.0.1:${PORT}/`); await r.text(); if (r.ok) return; } catch { /* not up yet */ }
    await new Promise((r) => setTimeout(r, 100));
  }
  throw new Error('server did not start');
});
test.afterAll(() => proc && proc.kill());

const z = (o = {}) => ({ input: 0, output: 0, cache_read: 0, cache_write: 0, reasoning: 0, calls: 0, cost: 0, ...o });
const WIN = (pct, used, mins, idle = false) => idle
  ? { idle: true, start_iso: '', reset_iso: '', minutes_left: 0, used_tokens_est: 0, cost_est: 0, limit: 2_000_000, pct: 0 }
  : { idle: false, start_iso: new Date(Date.now() - (300 - mins) * 60000).toISOString(), reset_iso: new Date(Date.now() + mins * 60000 + 5000).toISOString(), minutes_left: mins, used_tokens_est: used, cost_est: 1.25, limit: 2_000_000, pct };
function payload(tag = 1) {
  return {
    window5h: { claude: WIN(70.0, 1_400_000, 134), gpt: WIN(0, 0, 0, true), bots: { sol: WIN(70.0, 1_400_000, 134), astra: WIN(0, 0, 0, true), flash: WIN(95.5, 1_910_000, 20), luna: WIN(0, 0, 0, true) } },
    generated_at: '2026-10-22T12:00:00+07:00',
    profiles: [{ name: 'sol', family: 'claude', model: 'm', available: true }, { name: 'astra', family: 'gpt', model: 'g', available: true },
      { name: 'flash', family: 'claude', model: 'm', available: false, error: 'database is locked' }, { name: 'luna', family: 'gpt', model: 'g', available: true }],
    totals: { claude: z({ input: 1_200_000 * tag, output: 34_500, cache_read: 10, calls: 9, cost: 12.34 }), gpt: z({ input: 2_000, output: 500, calls: 3, cost: 4.5 }), all: z({ input: 1_202_000 * tag, output: 35_000, calls: 12, cost: 16.84 }) },
    by_bot: [{ bot: 'sol', model: 'claude-opus', family: 'claude', session_limit: { session_id_short: 'abcd1234', used_est: 700_000, limit: 1_000_000, pct: 70.0, basis: 'estimate' }, ...z({ input: 1_200_000 * tag, output: 34_500, calls: 9, cost: 12.34 }) },
      { bot: 'astra', model: 'openai/gpt-6', family: 'gpt', session_limit: { session_id_short: 'ef567890', used_est: 20_000, limit: 400_000, pct: 5.0, basis: 'estimate' }, ...z({ input: 2_000, output: 500, calls: 3, cost: 4.5 }) }],
    series: { bucket: 'day', labels: ['2026-10-20', '2026-10-21', '2026-10-22'], bots: { sol: [100, 200, 300], astra: [50, 0, 25], flash: [0, 0, 0], luna: [10, 10, 10] } },
    top_sessions: [{ bot: 'sol', session_id_short: 'abcd1234', source: 'local', title: '<img src=x onerror="window.__pwn=1">', model: 'claude-opus', total_tokens: 1_234_500, cost: 12.34, last_seen_iso: '2026-10-22T11:59:00+07:00' }],
  };
}

test('AC-05: renders cards, per-bot table, chart and top sessions; hostile text stays inert', async ({ page }) => {
  await page.route('**/api/usage*', (r) => r.fulfill({ contentType: 'application/json', body: JSON.stringify(payload()) }));
  await page.goto(`http://127.0.0.1:${PORT}/`);
  await expect(page.getByTestId('card-claude-tokens')).toHaveText('1.2M');
  await expect(page.getByTestId('card-gpt-tokens')).toHaveText('2.5K');
  await expect(page.getByTestId('card-claude-cost')).toContainText('$12.34');
  await expect(page.getByText('ประมาณการ ไม่ใช่ยอดเรียกเก็บจริง')).toBeVisible();
  await expect(page.getByTestId('by-bot').locator('tbody tr')).toHaveCount(2);
  const bars = page.getByTestId('model-bars').getByTestId('model-bar');
  await expect(bars).toHaveCount(2);
  await expect(bars.first()).toContainText('claude-opus'); // sorted by tokens, largest first
  await expect(bars.first()).toContainText('1.2M');
  await expect(bars.nth(1)).toContainText('openai/gpt-6');
  await expect(page.getByTestId('chart').locator('rect')).toHaveCount(8); // non-zero bars only
  await expect(page.getByText('กิจกรรมตามเวลา (token ของข้อความ — ประมาณ)')).toBeVisible();
  await expect(page.getByTestId('top-sessions').locator('tbody tr')).toHaveCount(1);
  await expect(page.getByTestId('top-sessions')).toContainText('<img src=x onerror="window.__pwn=1">');
  expect(await page.evaluate(() => window.__pwn)).toBeUndefined();
  await expect(page.getByTestId('profile-flash-off')).toContainText('database is locked');
  await expect(page.getByTestId('updated')).toHaveText(/^อัปเดตล่าสุด \d\d:\d\d:\d\d$/);
  await expect(page.getByTestId('banner')).toBeHidden();
});

test('AC-05: auto-refreshes every ~30 s and day/hour toggle re-queries', async ({ page }) => {
  const calls = [];
  let n = 0;
  await page.clock.install();
  await page.route('**/api/usage*', (r) => { calls.push(new URL(r.request().url()).searchParams.get('bucket')); n++; r.fulfill({ contentType: 'application/json', body: JSON.stringify(payload(n)) }); });
  await page.goto(`http://127.0.0.1:${PORT}/`);
  await expect(page.getByTestId('card-claude-tokens')).toHaveText('1.2M');
  expect(calls).toEqual(['day']);
  await page.clock.fastForward(29_000);
  expect(calls.length).toBe(1);
  await page.clock.fastForward(2_000);
  await expect(page.getByTestId('card-claude-tokens')).toHaveText('2.4M'); // second response (tag=2)
  expect(calls.length).toBe(2);
  await page.getByTestId('toggle-hour').click();
  await expect.poll(() => calls[calls.length - 1]).toBe('hour');
  await expect(page.getByTestId('toggle-hour')).toHaveAttribute('aria-pressed', 'true');
});

test('AC-05: fetch error shows a banner, keeps the last data, and recovers on the next tick', async ({ page }) => {
  let fail = false;
  await page.clock.install();
  await page.route('**/api/usage*', (r) => (fail ? r.abort() : r.fulfill({ contentType: 'application/json', body: JSON.stringify(payload()) })));
  await page.goto(`http://127.0.0.1:${PORT}/`);
  await expect(page.getByTestId('card-claude-tokens')).toHaveText('1.2M');
  fail = true;
  await page.clock.fastForward(31_000);
  await expect(page.getByTestId('banner')).toBeVisible();
  await expect(page.getByTestId('banner')).toContainText('โหลดข้อมูลไม่สำเร็จ');
  await expect(page.getByTestId('card-claude-tokens')).toHaveText('1.2M'); // not blanked
  await expect(page.getByTestId('by-bot').locator('tbody tr')).toHaveCount(2);
  fail = false;
  await page.clock.fastForward(31_000);
  await expect(page.getByTestId('banner')).toBeHidden();
});

test('AC-05: HTTP 500 from the API also shows the banner without blanking', async ({ page }) => {
  let bad = false;
  await page.clock.install();
  await page.route('**/api/usage*', (r) => (bad ? r.fulfill({ status: 500, body: 'x' }) : r.fulfill({ contentType: 'application/json', body: JSON.stringify(payload()) })));
  await page.goto(`http://127.0.0.1:${PORT}/`);
  await expect(page.getByTestId('card-all-tokens')).toHaveText('1.2M');
  bad = true;
  await page.clock.fastForward(31_000);
  await expect(page.getByTestId('banner')).toContainText('HTTP 500');
  await expect(page.getByTestId('card-all-tokens')).toHaveText('1.2M');
});

test('AC-05: the page makes no requests outside 127.0.0.1', async ({ page }) => {
  const external = [];
  page.on('request', (r) => { if (!r.url().startsWith(`http://127.0.0.1:${PORT}`) && !r.url().startsWith('data:')) external.push(r.url()); });
  await page.route('**/api/usage*', (r) => r.fulfill({ contentType: 'application/json', body: JSON.stringify(payload()) }));
  await page.goto(`http://127.0.0.1:${PORT}/`);
  await expect(page.getByTestId('card-claude-tokens')).toBeVisible();
  expect(external).toEqual([]);
});

test('UI2: KPI tiles, 4 bot cards with limit bars (green/amber/red bands), layout order and no overflow', async ({ page }) => {
  const d = payload();
  d.by_bot.push({ bot: 'luna', model: 'openai/gpt-6.1', family: 'gpt', session_limit: { session_id_short: 'l1', used_est: 380_000, limit: 400_000, pct: 95.0, basis: 'estimate' }, ...z({ input: 1, calls: 1 }) });
  await page.route('**/api/usage*', (r) => r.fulfill({ contentType: 'application/json', body: JSON.stringify(d) }));
  await page.goto(`http://127.0.0.1:${PORT}/`);
  await expect(page.getByTestId('bot-card')).toHaveCount(4);
  await expect(page.getByTestId('cards').locator('.card')).toHaveCount(3);
  // astra 5% green, sol 70% amber, luna 95% red, flash (unavailable) has no bar
  const lvl = (bot) => page.getByTestId('limit-bar-' + bot).locator('.fillbar').getAttribute('data-level');
  expect(await lvl('astra')).toBe('ok');
  expect(await lvl('sol')).toBe('warn');
  expect(await lvl('luna')).toBe('bad');
  await expect(page.getByTestId('limit-pct-sol')).toContainText('70.0%');
  await expect(page.getByTestId('limit-bar-sol')).toHaveAttribute('aria-valuenow', '70');
  await expect(page.getByTestId('bot-card').first()).toContainText('บริบท session ปัจจุบัน (ประมาณ)');
  await expect(page.locator('.bot[data-bot=flash]')).toContainText('ใช้ไม่ได้');
  await expect(page.locator('.bot[data-bot=flash] [data-testid^=limit-bar]')).toHaveCount(0);
  // fill width follows pct
  const w = await page.getByTestId('limit-bar-sol').evaluate((t) => t.firstElementChild.getBoundingClientRect().width / t.getBoundingClientRect().width);
  expect(w).toBeGreaterThan(0.65); expect(w).toBeLessThan(0.75);
  // first-screen order: KPI tiles above bot cards above the time chart above the details tables
  const y = async (id) => (await page.getByTestId(id).boundingBox()).y;
  const ys = [await y('cards'), await y('bots'), await y('chart'), await y('by-bot'), await y('top-sessions')];
  expect(ys).toEqual([...ys].sort((a, b) => a - b));
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
  // readable: no text glow, large numerals
  expect(await page.getByTestId('card-claude-tokens').evaluate((e) => [getComputedStyle(e).textShadow, parseFloat(getComputedStyle(e).fontSize)])).toEqual(['none', expect.any(Number)]);
  expect(await page.getByTestId('card-claude-tokens').evaluate((e) => parseFloat(getComputedStyle(e).fontSize))).toBeGreaterThanOrEqual(36);
});

test('UI2: missing session_limit degrades gracefully; page stays rendered', async ({ page }) => {
  const d = payload();
  d.by_bot.forEach((b) => { delete b.session_limit; });
  await page.route('**/api/usage*', (r) => r.fulfill({ contentType: 'application/json', body: JSON.stringify(d) }));
  await page.goto(`http://127.0.0.1:${PORT}/`);
  await expect(page.locator('.bot[data-bot=sol]')).toContainText('ไม่มีข้อมูล session');
  await expect(page.getByTestId('card-claude-tokens')).toHaveText('1.2M');
});

test('WIN5H: hero shows Claude/GPT session-limit bars with pct, used/limit, reset time; idle says ยังไม่เริ่มรอบ; honesty note', async ({ page }) => {
  const d = payload(); d.profiles[2].available = true; delete d.profiles[2].error;
  await page.route('**/api/usage*', (r) => r.fulfill({ contentType: 'application/json', body: JSON.stringify(d) }));
  await page.goto(`http://127.0.0.1:${PORT}/`);
  await expect(page.getByTestId('win-claude-pct')).toHaveText('70.0%');
  await expect(page.getByTestId('win-claude-used')).toHaveText('1.4M / 2.0M token');
  await expect(page.getByTestId('win-claude-reset')).toContainText(/รีเซ็ตเวลา \d\d:\d\d น\./);
  await expect(page.getByTestId('win-claude-countdown')).toHaveText(/^รีเซ็ตใน 2:1[34]:\d\d$/);
  expect(await page.getByTestId('win-claude-bar').locator('.fillbar').getAttribute('data-level')).toBe('warn');
  await expect(page.getByTestId('win-gpt-countdown')).toHaveText('ยังไม่เริ่มรอบ');
  await expect(page.getByTestId('win-gpt-pct')).toHaveText('0.0%');
  await expect(page.getByTestId('winbot-flash-pct')).toHaveText('95.5%');
  expect(await page.getByTestId('winbot-flash-bar').locator('.fillbar').getAttribute('data-level')).toBe('bad');
  await expect(page.getByTestId('winbot-astra-countdown')).toHaveText('ยังไม่เริ่มรอบ');
  await expect(page.getByTestId('win-note')).toHaveText('ประมาณจากข้อมูลในเครื่อง — ไม่ใช่โควตาจริงของผู้ให้บริการ ปรับเพดานได้ใน limits.json');
  // black / white / gold palette, hero first, no glow on text
  expect(await page.evaluate(() => getComputedStyle(document.body).backgroundColor)).toBe('rgb(0, 0, 0)');
  expect(await page.getByTestId('win-claude').evaluate((e) => getComputedStyle(e).borderColor)).toBe('rgb(212, 175, 55)');
  expect(await page.getByTestId('win-claude-pct').evaluate((e) => getComputedStyle(e).textShadow)).toBe('none');
  const y = async (id) => (await page.getByTestId(id).boundingBox()).y;
  const ys = [await y('hero'), await y('minis'), await y('cards'), await y('bots'), await y('chart')];
  expect(ys).toEqual([...ys].sort((a, b) => a - b));
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
});

test('WIN5H: countdown ticks every second on the client and expires gracefully', async ({ page }) => {
  await page.clock.install();
  await page.route('**/api/usage*', (r) => r.fulfill({ contentType: 'application/json', body: JSON.stringify(payload()) }));
  await page.goto(`http://127.0.0.1:${PORT}/`);
  const cd = page.getByTestId('win-claude-countdown');
  const secs = async () => { const m = (await cd.textContent()).match(/(\d+):(\d\d):(\d\d)$/); return +m[1] * 3600 + +m[2] * 60 + +m[3]; };
  await expect(cd).toHaveText(/^รีเซ็ตใน \d+:\d\d:\d\d$/);
  const a = await secs();
  await page.clock.fastForward(5_000);
  await expect.poll(async () => a - (await secs())).toBeGreaterThanOrEqual(4);
  await page.clock.fastForward(3 * 3600 * 1000); // past the reset moment (API calls are mocked identically)
  await expect(page.getByTestId('win-claude-countdown')).toBeVisible();
});

test('WIN5H: old/static data without window5h still renders the page', async ({ page }) => {
  const d = payload(); delete d.window5h;
  await page.route('**/api/usage*', (r) => r.fulfill({ contentType: 'application/json', body: JSON.stringify(d) }));
  await page.goto(`http://127.0.0.1:${PORT}/`);
  await expect(page.getByTestId('win-claude')).toContainText('ไม่มีข้อมูลหน้าต่าง 5 ชั่วโมง');
  await expect(page.getByTestId('card-claude-tokens')).toHaveText('1.2M');
});
