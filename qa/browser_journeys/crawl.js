#!/usr/bin/env node
// Visits every route of the tool with every role and checks the matrix of accesses.
//
//   python3 qa/browser_journeys/routes.py > routes.json
//   node qa/browser_journeys/crawl.js --routes routes.json [--base URL] [--out FOLDER] [--roles admin,lecteur]
//        [--baseline matrix.json] [--write-baseline matrix.json]
//
// For each role (default: admin, validateur, contributeur, lecteur, auditeur; the account name is the role name) and
// for each route of routes.json, opens the page in Chromium (so the JavaScript runs) and records the final status, the
// final address after redirects, the JavaScript errors and the failed requests. An anomaly is:
//   - a 5xx status, a page that cannot be loaded, a JavaScript error (uncaught) or a script / style that fails to load;
//   - a visitor who is not signed in and gets something else than the sign-in page (free pages excepted; a page that
//     answers to POST only, /mcp/, is expected to answer 405 to a GET, for every role and for a visitor);
//   - the reader or the auditor who opens a page that lecture_seule.py does not give them, or who is refused a page it
//     gives them (the expected matrix of these two roles comes from routes.json, itself read in lecture_seule.py);
//   - the administrator refused (403) on a page;
//   - another role (validateur, contributeur) that opens a page the administrator cannot open;
//   - with --baseline: a cell of the matrix that differs from a saved one (to pin the accesses of the validator and of
//     the contributor, which no file declares: save the matrix once with --write-baseline when it is right).
// Written in --out: access_matrix.tsv (one line per route, one column per role: status, ">" final address when it
// redirects) and crawl.json (all the details). Exit code 1 if there is an anomaly, 2 if the script itself fails.
'use strict';
const fs = require('fs');
const path = require('path');
const { chromium, config, report, run, signIn, loadRoutes } = require('./lib');

const ALL_ROLES = ['admin', 'validateur', 'contributeur', 'lecteur', 'auditeur'];
const READONLY_KEY = { lecteur: 'reader', auditeur: 'auditor' };

async function visit(page, log, cfg, url) {
  log.reset();
  let status = null, dl = false, err = null;
  try {
    const r = await page.goto(cfg.base + url, { waitUntil: 'networkidle', timeout: 30000 });
    status = r && r.status();
  } catch (e) {
    if (/Download is starting/.test(e.message)) dl = true;
    else err = e.message.split('\n')[0];
  }
  return {
    status: dl ? 'download' : (err ? 'ERROR' : status), final: dl ? url : page.url().replace(cfg.base, ''), error: err,
    console: [...log.console], pageerrors: [...log.pageerrors], failed: [...log.failed], bad: [...log.bad],
  };
}

const ok = (s) => s === 200 || s === 'download';
const label = (c) => (c.status === 'ERROR' ? 'ERR' : c.status) + (c.final && c.final !== c.url ? '>' + c.final.slice(0, 40) : '');

async function main() {
  const cfg = config();
  const rep = report('crawl');
  const { routes } = loadRoutes(cfg);
  const roles = cfg.roles.length ? cfg.roles : ALL_ROLES;
  const browser = await chromium.launch();
  const cells = {}; // cells[url][role] = result

  // visitor: not signed in
  {
    const ctx = await browser.newContext();
    const page = await ctx.newPage();
    const log = { console: [], pageerrors: [], failed: [], bad: [], reset() { this.console.length = this.pageerrors.length = this.failed.length = this.bad.length = 0; } };
    page.on('pageerror', (e) => log.pageerrors.push(String(e)));
    for (const r of routes) {
      const c = await visit(page, log, cfg, r.url); c.url = r.url;
      (cells[r.url] = cells[r.url] || {}).visitor = c;
      if (r.free || (r.get_status && c.status === r.get_status)) continue;  // free page, or POST only (/mcp/: 405 is the right answer)
      if (!/^\/connexion\//.test(c.final) && !(c.status === 403)) rep.anomaly('visitor ' + r.url, `not signed in, got ${c.status} at ${c.final} (expected the sign-in page)`);
    }
    await ctx.close();
  }

  for (const role of roles) {
    console.log('== ' + role);
    const { page, log, ctx } = await signIn(browser, cfg, role);
    for (const r of routes) {
      const c = await visit(page, log, cfg, r.url); c.url = r.url;
      (cells[r.url] = cells[r.url] || {})[role] = c;
      const where = `${role} ${r.url}`;
      if (c.status === 'ERROR') rep.anomaly(where, 'page not loaded: ' + c.error);
      else if (typeof c.status === 'number' && c.status >= 500) rep.anomaly(where, `status ${c.status}`);
      for (const e of c.pageerrors) rep.anomaly(where, 'JavaScript error: ' + e.slice(0, 160));
      for (const e of c.failed) if (!/net::ERR_ABORTED/.test(e)) rep.anomaly(where, 'request failed: ' + e.slice(0, 160));
      for (const e of c.console) if (!/Failed to load resource/.test(e) && !/the server responded with a status of (40[345])/.test(e)) rep.warning(where, 'console error: ' + e.slice(0, 160));
      const asset = c.bad.filter((b) => /\/static\//.test(b));
      for (const b of asset) rep.anomaly(where, 'static file not served: ' + b);
      const denied = c.status === 403;
      if (r.get_status && c.status === r.get_status) continue;  // POST only (/mcp/): a GET answers 405 for every role, there is no page to open or to refuse
      if (READONLY_KEY[role]) {
        const may = r.readonly[READONLY_KEY[role]];
        if (!may && !denied) rep.anomaly(where, `${role} must be refused (403) on this page, got ${c.status} at ${c.final}`);
        if (may && denied) rep.anomaly(where, `${role} is refused (403) on a page that lecture_seule.py gives them`);
      } else if (role === 'admin' && denied) rep.anomaly(where, 'the administrator is refused (403)');
    }
    await ctx.close();
  }
  await browser.close();

  // another role must never open what the administrator cannot
  if (roles.includes('admin')) {
    for (const r of routes) {
      const a = cells[r.url].admin;
      for (const role of roles) {
        const c = cells[r.url][role];
        if (role !== 'admin' && c && ok(c.status) && a.status === 403) rep.anomaly(`${role} ${r.url}`, 'opens a page that the administrator cannot open');
      }
    }
  }

  // matrix, then comparison with a saved one
  const cols = ['visitor', ...roles];
  const lines = ['url\t' + cols.join('\t')];
  const matrix = {};
  for (const r of routes) {
    matrix[r.url] = {};
    for (const col of cols) matrix[r.url][col] = label(cells[r.url][col]);
    lines.push(r.url + '\t' + cols.map((c) => matrix[r.url][c]).join('\t'));
  }
  fs.writeFileSync(path.join(cfg.out, 'access_matrix.tsv'), lines.join('\n') + '\n');
  fs.writeFileSync(path.join(cfg.out, 'crawl.json'), JSON.stringify(cells, null, 1));
  if (cfg.opts['write-baseline']) { fs.writeFileSync(cfg.opts['write-baseline'], JSON.stringify(matrix, null, 1)); rep.note('Matrix saved in ' + cfg.opts['write-baseline']); }
  if (cfg.opts.baseline) {
    const old = JSON.parse(fs.readFileSync(cfg.opts.baseline, 'utf8'));
    for (const [url, row] of Object.entries(matrix)) {
      if (!old[url]) { rep.warning(url, 'new route, not in the saved matrix'); continue; }
      for (const col of cols) if (old[url][col] !== undefined && old[url][col] !== row[col]) rep.anomaly(`${col} ${url}`, `access changed: was "${old[url][col]}", now "${row[col]}"`);
    }
    for (const url of Object.keys(old)) if (!matrix[url]) rep.warning(url, 'route of the saved matrix that no longer exists');
  }
  rep.note(`${routes.length} routes x ${cols.length} accounts. Matrix: ${path.join(cfg.out, 'access_matrix.tsv')}`);
  return rep.finish(cfg);
}

run(main);
