// Capture real screenshots of the Taskrivet workspace renderer.
//
// The renderer is the same file the desktop app loads. A synthetic bridge
// stands in for the Electron preload so the capture never touches a real
// ledger, a real shell, or a real session service.
//
//   npm i -D playwright && npx playwright install chromium
//   node scripts/capture-screenshots.mjs
//
// Screenshots are written to ../docs/screenshots. They show a synthetic
// workspace; they are not evidence of a live run.

import {createServer} from 'node:http';
import {readFile} from 'node:fs/promises';
import {existsSync, mkdirSync} from 'node:fs';
import {extname, join, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';

const here = fileURLToPath(new URL('.', import.meta.url));
const desktopRoot = resolve(here, '..');
const outputDir = resolve(desktopRoot, '..', 'docs', 'screenshots');

const MIME = {'.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.png': 'image/png', '.json': 'application/json'};

function serve(root) {
  return new Promise(resolveServer => {
    const server = createServer(async (req, res) => {
      const path = decodeURIComponent((req.url || '/').split('?')[0]);
      const file = join(root, path === '/' ? 'ui/index.html' : path.replace(/^\/+/, ''));
      if (!file.startsWith(root) || !existsSync(file)) { res.writeHead(404); res.end('not found'); return; }
      try {
        const body = await readFile(file);
        res.writeHead(200, {'content-type': MIME[extname(file)] || 'application/octet-stream'});
        res.end(body);
      } catch { res.writeHead(500); res.end('error'); }
    });
    server.listen(0, '127.0.0.1', () => resolveServer({server, port: server.address().port}));
  });
}

const TASK = {
  id: 'search-empty-state',
  objective: 'Fix the empty search result state so it shows useful guidance.',
  acceptance: 'Empty search shows guidance; the regression check passes.',
  kind: 'code',
  scope: ['taskrivet/desktop/search'],
  status: 'running',
  token_budget: 8000,
  created: 1792670000,
};

const SESSION = {
  id: '3f9c1d0ab41e47c8b2156ad39f0c7e21',
  task_id: TASK.id,
  owner: 'desktop-terminal',
  status: 'active',
  lease_until: 1792673600,
  tokens: 4820,
  progress: 'a'.repeat(64),
  stagnant: 0,
  created: 1792670100,
  lease_remaining_seconds: 780,
};

const DETAIL = {
  task: {
    ...TASK,
    reported_tokens: 4820,
    remaining_tokens: 3180,
  },
  session: SESSION,
  sessions: [SESSION],
  checkpoints: [
    {session_id: SESSION.id, summary: 'Empty state renders with guidance', evidence: 'diff 4f21ab · unit test green', next_step: 'Review the copy against the acceptance wording', tokens: 4820, created: 1792671200},
    {session_id: SESSION.id, summary: 'Regression test added', evidence: 'tests/test_search.py::test_empty_state', next_step: 'Wire the guidance copy', tokens: 2100, created: 1792670600},
  ],
  context: [
    {hash: '5f1c0b8e2a', source: 'repository README at a known revision', priority: 10, expires: null, bytes: 1840, expired: false},
    {hash: '9ab3d41c07', source: 'issue #418 acceptance criteria', priority: 5, expires: 1792774600, bytes: 612, expired: false},
  ],
  failures: [
    {session_id: SESSION.id, category: 'tool_error', summary: 'Editor tool call returned a truncated diff', fingerprint: '6d2f9a0b1c4e8f77', created: 1792670000, occurrences: 2},
  ],
  events: [
    {seq: 7, type: 'session.checkpoint', created: 1792671200, data: {session: SESSION.id, tokens: 4820, stagnant: 0}},
    {seq: 6, type: 'context.attached', created: 1792670900, data: {hash: '9ab3d41c07', source: 'issue #418 acceptance criteria'}},
    {seq: 5, type: 'failure.recorded', created: 1792670000, data: {category: 'tool_error', fingerprint: '6d2f9a0b1c4e8f77'}},
    {seq: 4, type: 'session.checkpoint', created: 1792669500, data: {session: SESSION.id, tokens: 2100, stagnant: 0}},
    {seq: 3, type: 'session.started', created: 1792670100, data: {owner: 'desktop-terminal', session: SESSION.id}},
  ],
  claims: [{task: 'release-notes-0-4', status: 'blocked', shared_keys: ['taskrivet/desktop/search']}],
  pack: {bytes: 9214, items: 2, omitted: [{hash: 'c81f0a7e44', reason: 'byte_budget'}], error: null},
  provenance: 'Ledger records only.',
};

const SHELL_OUTPUT = [
  'Last login: Tue Oct 21 22:14:03 on ttys002',
  'zsh: you have running jobs',
  '',
  'operator@taskrivet ~/Projects/taskrivet % git status --short',
  ' M desktop/ui/app.js',
  ' M desktop/ui/index.html',
  ' M desktop/ui/style.css',
  ' M taskrivet/core.py',
  ' M taskrivet/cli.py',
  ' M tests/test_core.py',
  'operator@taskrivet ~/Projects/taskrivet % python3 -m unittest discover -s tests -v',
  'test_detail_reports_session_context_and_evidence ... ok',
  'test_detail_claims_show_shared_resource_keys ... ok',
  'test_cli_detail_reads_one_task ... ok',
  '',
  'Ran 81 tests in 2.203s',
  '',
  'OK',
  'operator@taskrivet ~/Projects/taskrivet % ',
].join('\r\n');

const SECOND_OUTPUT = [
  'operator@taskrivet ~/Projects/taskrivet % rg -n "empty state" desktop/ui',
  'desktop/ui/app.js:412:  empty search shows useful guidance',
  'desktop/ui/app.js:418:  the regression check passes',
  'operator@taskrivet ~/Projects/taskrivet % ',
].join('\r\n');

function terminal(id, cwd, chunks, extra = {}) {
  return {
    id, cwd, task: TASK.id, session: SESSION.id, shell: '/bin/zsh', state: 'running', exitCode: null,
    pid: 4242, title: null, kind: 'shell', ref: null, chunks: [{seq: 1, data: chunks}], ...extra,
  };
}

const TERMINALS = [terminal('t-1', '/Users/operator/Projects/taskrivet', SHELL_OUTPUT)];

const bridge = `
window.workspace = (() => {
  const listeners = {data: [], exit: [], disconnect: [], error: []};
  const terminals = ${JSON.stringify(TERMINALS)};
  const status = {
    tasks: [${JSON.stringify(TASK)}, {id: 'release-notes-0-4', objective: 'Write the 0.4 release notes', acceptance: 'Notes match the shipped behavior', kind: 'code', scope: ['taskrivet/desktop/search'], status: 'blocked', token_budget: 4000, created: 1792660000}],
    sessions: [${JSON.stringify(SESSION)}],
    failures: [{fingerprint: '6d2f9a0b1c4e8f77', category: 'tool_error', summary: 'Editor tool call returned a truncated diff', occurrences: 2}],
    metrics: {accepted: 12, reported_tokens: 184920, measured_cash_cost: null, measured_token_savings: null},
  };
  let counter = 1;
  return {
    bootstrap: async () => ({home: '/Users/operator', terminals: terminals.map(t => ({...t})), version: '0.3.0', githubRepo: 'hamanakam1/taskrivet'}),
    opencodeSessions: async () => ({available: true, session_count: 0, sessions: [], observed_at: Math.floor(Date.now() / 1000), reason: null}),
    ledger: async (action, data) => {
      if (action === 'status') return status;
      if (action === 'detail') return ${JSON.stringify(DETAIL)};
      if (action === 'pack') return {packet: ${JSON.stringify(DETAIL.task)}, packet_bytes: 9214, omitted: [], note: 'Synthetic capture.'};
      if (action === 'tools') return {installed: 2088, agent_profiles: 26, tools: []};
      if (action === 'dashboard') return {returned: 0, tickets: [], projects: [], has_more: false, observed_at: Math.floor(Date.now() / 1000), coverage: 'Synthetic capture.'};
      if (action === 'github-status') return {last_poll: null, coverage: {}, responses: [], recent: []};
      if (action === 'create') return {id: data.id};
      return {status: 'ok'};
    },
    chooseDirectory: async () => '/Users/operator/Projects/taskrivet',
    createTerminal: async (options) => {
      const id = 't-' + (++counter);
      const info = {
        id, cwd: options.cwd || '/Users/operator/Projects/taskrivet', task: options.task || null, session: options.session || null,
        shell: '/bin/zsh', state: 'running', exitCode: null, pid: 4300 + counter, title: null, kind: 'shell', ref: null,
        chunks: [{seq: 1, data: counter > 1 ? ${JSON.stringify(SECOND_OUTPUT)} : ''}],
      };
      terminals.push(info);
      return info;
    },
    write: async () => true,
    resize: async () => true,
    stop: async () => true,
    remove: async () => true,
    onData: cb => {listeners.data.push(cb); return () => {};},
    onExit: cb => {listeners.exit.push(cb); return () => {};},
    onDisconnect: cb => {listeners.disconnect.push(cb); return () => {};},
    onIntegrationError: cb => {listeners.error.push(cb); return () => {};},
  };
})();
`;

async function openBrowser(chromium) {
  const attempts = [
    {name: 'bundled chromium', options: {}},
    {name: 'installed Google Chrome', options: {channel: 'chrome'}},
  ];
  const failures = [];
  for (const attempt of attempts) {
    try {
      return await chromium.launch({headless: true, ...attempt.options});
    } catch (error) {
      failures.push(`${attempt.name}: ${error.message.split('\n')[0]}`);
    }
  }
  throw new Error(`No browser could be started.\n  ${failures.join('\n  ')}\n  Run: npx playwright install chromium`);
}

async function main() {
  let chromium;
  try {
    ({chromium} = await import('playwright'));
  } catch {
    throw new Error('Playwright is not installed. Run: npm i -D playwright && npx playwright install chromium');
  }
  if (!existsSync(outputDir)) mkdirSync(outputDir, {recursive: true});
  const {server, port} = await serve(desktopRoot);
  const browser = await openBrowser(chromium);
  const context = await browser.newContext({viewport: {width: 1440, height: 900}, deviceScaleFactor: 2});
  await context.addInitScript(bridge);
  const page = await context.newPage();
  const problems = [];
  page.on('pageerror', error => problems.push(`pageerror: ${error.message}`));
  page.on('console', message => {
    if (message.type() !== 'error') return;
    const at = message.location()?.url || '';
    if (at.endsWith('/favicon.ico')) return;
    problems.push(`console: ${message.text()} (${at || 'unknown source'})`);
  });
  page.on('response', response => {
    if (response.status() >= 400) {
      const note = `http ${response.status()}: ${response.url()}`;
      if (response.url().endsWith('/favicon.ico')) console.log(`ignored ${note}`);
      else problems.push(note);
    }
  });
  await page.goto(`http://127.0.0.1:${port}/ui/index.html`, {waitUntil: 'networkidle'});
  try {
    await page.waitForSelector('.terminal-pane.active .xterm-screen', {timeout: 15000});
  } catch (error) {
    console.error('renderer diagnostics:');
    console.error(await page.evaluate(() => JSON.stringify({
      panes: document.querySelectorAll('.terminal-pane').length,
      tabs: document.querySelectorAll('.tab').length,
      banner: document.getElementById('error')?.textContent || '',
      status: document.getElementById('ledger-status')?.textContent || '',
      terminalLoaded: typeof window.Terminal,
    }, null, 2)));
    for (const problem of problems) console.error(`  ${problem}`);
    throw error;
  }
  await page.waitForTimeout(1200);

  const shot = async (name, target) => {
    const file = join(outputDir, `${name}.png`);
    if (target) await page.locator(target).screenshot({path: file});
    else await page.screenshot({path: file});
    console.log(`wrote ${file}`);
  };

  const check = async (label, fn) => {
    const value = await page.evaluate(fn);
    if (!value) throw new Error(`renderer check failed: ${label}`);
    console.log(`check ok: ${label}`);
  };

  await check('the inspector names the focused task', () => document.getElementById('session-title')?.textContent === 'search-empty-state');
  await check('the inspector shows the session identifier', () => document.getElementById('insp-session')?.textContent.includes('3f9c1d0a'));
  await check('the inspector shows the objective', () => document.getElementById('insp-task')?.textContent.includes('useful guidance'));
  await check('the inspector shows recorded usage as reported', () => document.getElementById('insp-task')?.textContent.includes('4,820 / 8,000'));
  await check('the inspector lists checkpoints', () => document.getElementById('insp-checkpoints')?.textContent.includes('Empty state renders with guidance'));
  await check('the inspector lists failures', () => document.getElementById('insp-failures')?.textContent.includes('tool_error'));
  await check('the inspector lists ledger events', () => document.getElementById('insp-events')?.textContent.includes('session.checkpoint'));
  await check('the inspector shows bounded context', () => document.getElementById('insp-context')?.textContent.includes('9,214 bytes'));
  await check('the inspector names the resource claim', () => document.getElementById('insp-task')?.textContent.includes('release-notes-0-4'));

  await shot('workspace-session-inspector');
  await shot('workspace-session-inspector-panel', '.inspector');

  await page.click('#split-right');
  await page.waitForSelector('.split-h .terminal-pane', {timeout: 10000});
  await page.waitForTimeout(900);
  await check('splitting adds a second pane', () => document.querySelectorAll('.terminal-pane').length === 2);
  await check('the split keeps the same session', () => document.querySelectorAll('.pane-title').length === 2);
  await shot('workspace-split-panes');

  await page.click('#find-toggle');
  await page.fill('#find-input', 'empty state');
  await page.waitForTimeout(500);
  await check('the find bar reports matches', () => /\d+ (of|match)/.test(document.getElementById('find-count')?.textContent || ''));
  await shot('workspace-find-in-scrollback');
  await page.click('#find-close');

  await page.click('#palette-toggle');
  await page.waitForTimeout(400);
  await check('the command palette lists commands', () => document.querySelectorAll('#palette-list li').length > 5);
  await shot('workspace-command-palette');
  await page.keyboard.press('Escape');

  await page.click('#tools-nav');
  await page.waitForTimeout(400);
  await shot('tool-catalog');
  await page.click('#failures-nav');
  await page.waitForTimeout(400);
  await shot('failure-ledger');

  await browser.close();
  server.close();
  if (problems.length) {
    console.error('renderer problems:');
    for (const problem of problems) console.error(`  ${problem}`);
    process.exit(1);
  }
  console.log('captured with no renderer errors');
}

main().catch(error => { console.error(error.message); process.exit(1); });
