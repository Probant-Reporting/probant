#!/usr/bin/env node
// Phone display (390 px wide, touch): no horizontal scrolling, nothing sticking out of the screen, no JavaScript error.
//
//   python3 qa/browser_journeys/routes.py > routes.json
//   node qa/browser_journeys/mobile.js --routes routes.json [--base URL] [--out FOLDER] [--roles admin,lecteur]
//        [--width 390] [--pages /a/,/b/]
//
// For each role (default: admin, contributeur, lecteur, auditeur) opens each route of routes.json that the role can open
// (a page that answers something else than 200 is skipped; --pages replaces the list of routes) and measures:
//   - the page itself scrolls sideways (scrollWidth > clientWidth): ANOMALY, with a screenshot in --out;
//   - an element ends beyond the right edge without a scrolling ancestor that contains it: warning (look at it by hand,
//     a table in its own scrolling frame is fine);
//   - a JavaScript error: ANOMALY.
// qa/browser_check.py measures the same overflow at 768 and 390 px on its own list of main pages; this script covers
// every route and every role. Takes a few minutes. Exit code 1 if there is an anomaly.
'use strict';
const path = require('path');
const { chromium, config, report, run, signIn, loadRoutes } = require('./lib');

async function main() {
  const cfg = config();
  const rep = report('mobile');
  const width = parseInt(cfg.opts.width || '390', 10);
  const roles = cfg.roles.length ? cfg.roles : ['admin', 'contributeur', 'lecteur', 'auditeur'];
  const urls = cfg.opts.pages ? String(cfg.opts.pages).split(',') : loadRoutes(cfg).routes.map((r) => r.url);
  const browser = await chromium.launch();
  for (const role of roles) {
    console.log('== ' + role);
    const { page, log } = await signIn(browser, cfg, role, { viewport: { width, height: 844 }, hasTouch: true, isMobile: true });
    let seen = 0;
    for (const u of urls) {
      log.reset();
      let r = null;
      try { r = await page.goto(cfg.base + u, { waitUntil: 'networkidle', timeout: 30000 }); } catch (e) { continue; } // download or redirect loop: not a page
      if (!r || r.status() !== 200 || !page.url().startsWith(cfg.base + u.split('?')[0])) continue; // refused or redirected: not a page of this role
      if (!/text\/html/.test(r.headers()['content-type'] || '')) continue; // a JSON or a file: no layout to measure
      seen++;
      const m = await page.evaluate((W) => {
        const de = document.documentElement;
        const out = [];
        for (const e of document.querySelectorAll('body *')) {
          const cs = getComputedStyle(e);
          if (cs.visibility === 'hidden' || cs.display === 'none' || (e.offsetParent === null && cs.position !== 'fixed')) continue;
          const b = e.getBoundingClientRect();
          if (b.width === 0 || b.height === 0 || b.right <= W + 1) continue;
          let p = e.parentElement, contained = false;
          while (p && p !== document.body) {
            const s = getComputedStyle(p);
            if (/(auto|scroll|hidden)/.test(s.overflowX) && p.getBoundingClientRect().right <= W + 1) { contained = true; break; }
            p = p.parentElement;
          }
          if (!contained) out.push(e.tagName + '.' + String(e.className || '').slice(0, 30) + ' right=' + Math.round(b.right));
        }
        return { sw: de.scrollWidth, cw: de.clientWidth, out: out.slice(0, 4), n: out.length };
      }, width);
      const where = `${role} ${u}`;
      if (m.sw > m.cw) {
        rep.anomaly(where, `scrolls sideways (scrollWidth ${m.sw} > ${m.cw}); sticking out: ${JSON.stringify(m.out)}`);
        await page.screenshot({ path: path.join(cfg.out, `mobile_${role}_${u.replace(/\W+/g, '_')}.png`) }).catch(() => {});
      } else if (m.n) rep.warning(where, `${m.n} element(s) end beyond the right edge: ${JSON.stringify(m.out)}`);
      for (const e of log.pageerrors) rep.anomaly(where, 'JavaScript error: ' + e.slice(0, 160));
    }
    rep.note(`  ${role}: ${seen} pages measured at ${width} px`);
  }
  await browser.close();
  return rep.finish(cfg);
}

run(main);
