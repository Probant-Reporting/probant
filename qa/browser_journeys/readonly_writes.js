#!/usr/bin/env node
// The read-only roles (reader, auditor) must never write; nobody may post without the CSRF token.
//
//   python3 qa/browser_journeys/routes.py > routes.json
//   node qa/browser_journeys/readonly_writes.js --routes routes.json [--base URL] [--out FOLDER] [--roles lecteur,auditeur]
//
// Signs in as each role (default: lecteur and auditeur) and sends a POST, with a valid CSRF token, to every route of
// routes.json. The expected answer comes from routes.json (written from collecte/lecture_seule.py):
//   - a route that is not in ECRITURES_PERMISES (own password, own views and lists, downloads) must answer 403;
//   - a route that a read-only role may post to (its own preferences) must not answer 5xx;
//   - on the entry cell, a real "save" and a real "validate" (value, comment) must answer 403.
// Then, for every role given and a few routes, a POST WITHOUT the CSRF token must answer 403.
// Anomaly = a write accepted, a 5xx, a CSRF token not required. Exit code 1 if there is an anomaly.
// Run on a throwaway demo: a post that is allowed (own views) can create or change a personal object. Posts that are
// refused write nothing; browser_check.py proves it with a fingerprint of the business tables.
'use strict';
const { chromium, config, report, run, signIn, loadRoutes } = require('./lib');

const READONLY_KEY = { lecteur: 'reader', auditeur: 'auditor' };

async function main() {
  const cfg = config();
  const rep = report('readonly_writes');
  const { routes } = loadRoutes(cfg);
  const roles = cfg.roles.length ? cfg.roles : ['lecteur', 'auditeur'];
  const browser = await chromium.launch();
  const cell = routes.find((r) => r.name === 'cellule');
  for (const role of roles) {
    console.log('== ' + role);
    const { page, ctx } = await signIn(browser, cfg, role);
    const cookies = await ctx.cookies();
    const token = (cookies.find((c) => c.name === 'csrftoken') || {}).value;
    const post = async (url, form, withToken = true) => {
      const headers = withToken ? { 'X-CSRFToken': token, Referer: cfg.base + '/' } : { Referer: cfg.base + '/' };
      const r = await page.request.post(cfg.base + url, { form, headers, maxRedirects: 0 });
      return r.status();
    };
    for (const r of routes) {
      if (r.name === 'login' || r.name === 'langue') continue; // free pages: the language button writes only a cookie
      const st = await post(r.url, {});
      const readonly = READONLY_KEY[role];
      if (st >= 500) rep.anomaly(`${role} POST ${r.url}`, `status ${st}`);
      else if (readonly && !r.write_allowed && st !== 403) rep.anomaly(`${role} POST ${r.url}`, `write not refused: status ${st} (expected 403)`);
    }
    if (cell && READONLY_KEY[role]) {
      for (const action of ['enregistrer', 'valider']) {
        const st = await post(cell.url, { action, valeur: '123', commentaire: 'test', version: '' });
        if (st !== 403) rep.anomaly(`${role} POST ${cell.url} (${action})`, `entry accepted: status ${st} (expected 403)`);
      }
    }
    // no CSRF token: refused for everybody, whatever the page
    const sample = routes.filter((r) => ['cellule', 'mon_compte', 'admin_compte_nouveau', 'echanges_importer', 'choisir_campagne'].includes(r.name));
    for (const r of sample) {
      const st = await post(r.url, {}, false);
      if (st !== 403) rep.anomaly(`${role} POST ${r.url} without CSRF token`, `status ${st} (expected 403)`);
    }
    rep.note(`  ${role}: ${routes.length} routes posted, ${sample.length} posted without token`);
    await ctx.close();
  }
  await browser.close();
  return rep.finish(cfg);
}

run(main);
