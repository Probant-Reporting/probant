// Shared helpers of the browser journeys: options, sign-in by role, anomaly report, exit code.
//
// Every script reads the same options (command line first, then environment variable, then default):
//   --base URL        BASE_URL   address of the tool                      http://127.0.0.1:8000
//   --password TEXT   PASSWORD   password of the demo accounts            demo-probant-2026
//   --out FOLDER      OUT_DIR    where the reports are written            ./journeys-output
//   --roles a,b,c     ROLES      roles to run (account name = role name)  (depends on the script)
//   --routes FILE     ROUTES     JSON written by routes.py                (crawl.js and readonly_writes.js)
// Run against a throwaway demo only (see README.md): some scripts click and post.
'use strict';
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

function parseArgs(argv) {
  const opts = { _: [] };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith('--')) {
      const next = argv[i + 1];
      if (next === undefined || next.startsWith('--')) opts[a.slice(2)] = true;
      else { opts[a.slice(2)] = next; i++; }
    } else opts._.push(a);
  }
  return opts;
}

function config(argv = process.argv.slice(2)) {
  const o = parseArgs(argv);
  const pick = (name, env, dflt) => (o[name] !== undefined ? o[name] : (process.env[env] !== undefined ? process.env[env] : dflt));
  const cfg = {
    base: String(pick('base', 'BASE_URL', 'http://127.0.0.1:8000')).replace(/\/+$/, ''),
    password: pick('password', 'PASSWORD', 'demo-probant-2026'),
    out: pick('out', 'OUT_DIR', 'journeys-output'),
    roles: String(pick('roles', 'ROLES', '')).split(',').filter(Boolean),
    routes: pick('routes', 'ROUTES', ''),
    opts: o,
  };
  fs.mkdirSync(cfg.out, { recursive: true });
  return cfg;
}

// Collects what went wrong. An anomaly makes the exit code non-zero; a warning is only listed.
function report(name) {
  const r = { name, anomalies: [], warnings: [], notes: [] };
  r.anomaly = (where, what) => { r.anomalies.push({ where, what }); console.log('  ANOMALY  ' + where + ' : ' + what); };
  r.warning = (where, what) => { r.warnings.push({ where, what }); console.log('  warning  ' + where + ' : ' + what); };
  r.note = (text) => { r.notes.push(text); console.log(text); };
  r.finish = (cfg) => {
    fs.writeFileSync(path.join(cfg.out, name + '.json'), JSON.stringify(r, null, 1));
    console.log(`\n${name}: ${r.anomalies.length} anomaly(ies), ${r.warnings.length} warning(s). Report: ${path.join(cfg.out, name + '.json')}`);
    return r.anomalies.length ? 1 : 0;
  };
  return r;
}

// Runs the main function of a script: a crash gives exit code 2, anomalies give exit code 1.
function run(main) {
  main().then((code) => process.exit(code || 0)).catch((e) => { console.error('FAILED: ' + ((e && e.stack) || e)); process.exit(2); });
}

async function signIn(browser, cfg, user, ctxOptions = {}) {
  const ctx = await browser.newContext(Object.assign({ viewport: { width: 1440, height: 900 }, acceptDownloads: true }, ctxOptions));
  const page = await ctx.newPage();
  page.setDefaultTimeout(8000);
  const log = { console: [], pageerrors: [], failed: [], bad: [] };
  page.on('console', (m) => { if (m.type() === 'error') log.console.push(m.text() + ' @' + page.url()); });
  page.on('pageerror', (e) => log.pageerrors.push(String(e) + ' @' + page.url()));
  page.on('requestfailed', (r) => log.failed.push(r.method() + ' ' + r.url() + ' ' + ((r.failure() || {}).errorText || '')));
  page.on('response', (r) => { if (r.status() >= 400) log.bad.push(r.status() + ' ' + r.request().method() + ' ' + r.url()); });
  log.reset = () => { log.console.length = log.pageerrors.length = log.failed.length = log.bad.length = 0; };
  await page.goto(cfg.base + '/connexion/');
  await page.fill('#id_username', user);
  await page.fill('#id_password', cfg.password);
  await page.click('button[type=submit]:not([name=langue])');
  await page.waitForLoadState('networkidle');
  if (page.url().includes('/connexion/')) throw new Error(`sign-in refused for "${user}" (account name or password wrong?)`);
  log.reset();
  return { ctx, page, log };
}

function loadRoutes(cfg) {
  if (!cfg.routes) throw new Error('--routes FILE is required: python3 qa/browser_journeys/routes.py > routes.json (see README.md)');
  return JSON.parse(fs.readFileSync(cfg.routes, 'utf8'));
}

module.exports = { chromium, config, report, run, signIn, loadRoutes, parseArgs };
