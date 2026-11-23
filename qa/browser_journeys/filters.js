#!/usr/bin/env node
// The filter bar (.barre-filtres, rules in DESIGN.md "Filters"): search, check-list panels, "Display" menu, "Clear filters".
//
//   node qa/browser_journeys/filters.js [--base URL] [--out FOLDER] [--roles admin] [--width 1440] [--pages /a/,/b/]
//
// On each page that has a filter bar (default: the pages of the administrator and of the contributor that have one;
// --pages replaces the list), checks:
//   - search: a text that matches nothing hides every row; clearing it brings every row back;
//   - "Clear filters" is visible as soon as a filter is active, and brings back the initial rows and an empty search;
//   - each check-list panel: opens (aria-expanded="true", panel visible), Escape closes it, a click outside closes it
//     (anomalies); the focus goes back to its button, "Clear filters" shows and restores the initial rows (warnings, only
//     when the option chosen changes the list: each panel is tested on the page as first loaded, and a single-choice group,
//     which switches a view, does not ask for "Clear filters");
//   - the "Display" menu: opens, each switch can be toggled and put back, Escape and a click outside close it;
//   - no JavaScript error on the page.
// Nothing is saved: only filters in the page and in the address bar. Anomaly = one check that fails. Exit code 1 if any.
'use strict';
const { chromium, config, report, run, signIn } = require('./lib');

const DEFAULT_PAGES = {
  admin: ['/administration/comptes/', '/administration/attributions/', '/administration/journal/', '/administration/organisations/',
    '/pour-moi/', '/referentiel/', '/coherence/', '/saisie/', '/administration/referentiels/VS_BASE/?ajouter=1'],
};

async function main() {
  const cfg = config();
  const rep = report('filters');
  const roles = cfg.roles.length ? cfg.roles : ['admin'];
  const width = parseInt(cfg.opts.width || '1440', 10);
  const browser = await chromium.launch();
  for (const role of roles) {
    const pages = cfg.opts.pages ? String(cfg.opts.pages).split(',') : (DEFAULT_PAGES[role] || DEFAULT_PAGES.admin);
    const { page, log } = await signIn(browser, cfg, role, { viewport: { width, height: 900 } });
    // a page either filters in the browser (rows hidden, button [data-reinitialiser-filtres]) or by the server (the page is
    // loaded again, link .lien-effacer, rows are "div role=row" in the history)
    const state = () => page.evaluate(() => {
      const vis = (e) => e && !e.hidden && e.getClientRects().length > 0;
      const reset = document.querySelector('[data-reinitialiser-filtres], .lien-effacer');
      const search = document.querySelector('.barre-filtres input[type=search]');
      return {
        rows: [...document.querySelectorAll('tbody tr, .entree-journal:not(.entete-journal)')].filter(vis).length,
        reset: !!reset && vis(reset), search: search ? search.value : null,
        server: !!document.querySelector('.etat-filtres[data-serveur]'),
      };
    });
    // (a server-filtered page may load again at any moment: wait, and try once more if the page changed under the call)
    const panel = async (id, again = true) => { try { await page.waitForLoadState('load'); return await panel0(id); } catch (e) { if (!again) throw e; await page.waitForTimeout(800); return panel(id, false); } };
    const panel0 = (id) => { return page.evaluate((id) => {
      const b = document.getElementById(id); const p = b.parentElement.querySelector('.panneau-filtre');
      return { expanded: b.getAttribute('aria-expanded'), open: !!p && p.getClientRects().length > 0, focusOnButton: document.activeElement === b };
    }, id); };
    const settle = async (ms = 500) => { await page.waitForLoadState('load'); await page.waitForTimeout(ms); };
    for (const u of pages) {
      const where = `${role} ${u}`;
      log.reset();
      const r = await page.goto(cfg.base + u, { waitUntil: 'networkidle' });
      if (!(await page.$('.barre-filtres'))) { rep.note(`${where}: no filter bar (status ${r && r.status()})`); continue; }
      const initial = await state();
      console.log(`${where}: ${initial.rows} rows`);
      const clear = async () => { const b = await page.$('.barre-filtres [data-reinitialiser-filtres], .barre-filtres .lien-effacer'); if (b && await b.isVisible()) { await b.click(); await page.waitForTimeout(300); await settle(900); return true; } return false; };

      const search = await page.$('.barre-filtres input[type=search]');
      if (search) {
        const sl = page.locator('.barre-filtres input[type=search]').first(); // a locator: the page may be loaded again
        await sl.fill('zzzqqq'); if (initial.server) await sl.press('Enter'); await settle();
        let s = await state();
        if (initial.rows > 0 && s.rows !== 0) rep.anomaly(where, `search "zzzqqq": ${s.rows} rows still visible (expected 0)`);
        if (!s.reset) rep.anomaly(where, 'search active but "Clear filters" is not visible');
        await sl.fill(''); if (initial.server) await sl.press('Enter'); await settle();
        s = await state();
        if (s.rows !== initial.rows) rep.anomaly(where, `search cleared: ${s.rows} rows instead of ${initial.rows}`);
        await sl.fill('a'); if (initial.server) await sl.press('Enter'); await settle();
        if (!(await clear())) rep.anomaly(where, '"Clear filters" not visible after a search');
        s = await state();
        if (s.rows !== initial.rows || s.search) rep.anomaly(where, `"Clear filters" did not reset the search (${s.rows} rows, search "${s.search}")`);
      }

      const nPanels = (await page.$$('.barre-filtres button.liste-filtre')).length;
      for (let i = 0; i < nPanels; i++) {
        // each panel starts from the page as first loaded: a choice kept from the previous panel (a server filter, a saved
        // choice) would make this panel's "default" option a different one and give false findings
        if (i > 0) await page.goto(cfg.base + u, { waitUntil: 'networkidle' });
        const btn = (await page.$$('.barre-filtres button.liste-filtre'))[i];
        if (!btn || !(await btn.isVisible())) continue;
        const id = await btn.getAttribute('id');
        const name = `${where} panel #${id}`;
        const toggle = async () => { await page.waitForLoadState('load'); await page.click('#' + id); await page.waitForTimeout(200); };
        await toggle();
        const open = await panel(id);
        if (open.expanded !== 'true' || !open.open) rep.anomaly(name, `does not open (aria-expanded=${open.expanded}, visible=${open.open})`);
        // choose an option that is not selected yet (the first one is often "All"): the filter becomes active
        const option = await page.$('.panneau-filtre label:not(.tout-panneau) input:not(:checked)');
        if (option) {
          // "Clear filters" is expected when the choice narrows the list. Not for a single-choice group (it switches a view:
          // Data entry / Administration changes of the History). When the server filters (data-envoyer), the form is sent only
          // when the panel closes (DESIGN.md, "Filters"): close it before looking, then open it again for the next checks
          const single = (await option.getAttribute('type')) === 'radio';
          await option.check({ force: true }).catch(() => {}); await settle(600);
          if ((await panel(id)).open) { // (a server-filtered page is not always marked: close the panel in every case, wait for a page that may come back)
            // the form is sent as the panel closes: wait for the page that comes back (a slow server needs more than a pause)
            await Promise.all([page.waitForNavigation({ timeout: initial.server ? 8000 : 2500 }).catch(() => {}), page.keyboard.press('Escape')]);
            await settle(500);
          }
          const s = await state();
          if (!s.reset && !single) rep.warning(name, '"Clear filters" not visible after choosing an option (the page was reloaded from its first state: look by hand)');
          if (!(await panel(id)).open) await toggle(); // the page was reloaded by the choice: open the panel again
        }
        await page.keyboard.press('Escape'); await page.waitForTimeout(200);
        let after = await panel(id);
        if (after.open) rep.anomaly(name, 'Escape does not close the panel');
        else if (!after.focusOnButton) rep.warning(name, 'Escape closes the panel but the focus is not back on its button');
        await toggle(); // open again: a click outside must close it
        await page.mouse.click(5, 5); await page.waitForTimeout(200);
        after = await panel(id);
        if (after.open) rep.anomaly(name, 'a click outside does not close the panel');
        if (option) {
          if (await clear()) {
            const s = await state();
            if (s.rows !== initial.rows) rep.warning(name, `"Clear filters": ${s.rows} rows instead of ${initial.rows}`);
          }
        }
      }

      const menu = await page.$('.barre-filtres details.menu-affichage');
      if (menu) {
        const isOpen = () => page.evaluate(() => document.querySelector('.menu-affichage').open);
        await page.evaluate(() => document.querySelector('.menu-affichage summary').click()); await page.waitForTimeout(200);
        if (!(await isOpen())) rep.anomaly(`${where} Display menu`, 'does not open');
        const n = (await page.$$('.menu-affichage input[type=checkbox]')).length;
        for (let k = 0; k < n; k++) {
          const cb = (await page.$$('.menu-affichage input[type=checkbox]'))[k];
          if (!cb || !(await cb.isVisible())) continue;
          const was = await cb.isChecked();
          await cb.click({ force: true }).catch(() => {}); await settle(900);
          const cb2 = (await page.$$('.menu-affichage input[type=checkbox]'))[k];
          if (!cb2) { rep.anomaly(`${where} Display menu`, `switch ${k} disappears after a click`); continue; }
          if ((await cb2.isChecked()) === was) rep.anomaly(`${where} Display menu`, `switch ${k} did not change state`);
          else { await cb2.click({ force: true }).catch(() => {}); await settle(900); }
          if (!(await isOpen())) await page.evaluate(() => document.querySelector('.menu-affichage summary').click());
        }
        await page.keyboard.press('Escape'); await page.waitForTimeout(200);
        if (await isOpen()) rep.anomaly(`${where} Display menu`, 'Escape does not close it');
        await page.evaluate(() => document.querySelector('.menu-affichage summary').click()); await page.waitForTimeout(150);
        await page.mouse.click(5, 5); await page.waitForTimeout(200);
        if (await isOpen()) rep.anomaly(`${where} Display menu`, 'a click outside does not close it');
      }
      for (const e of log.pageerrors.concat(log.console.filter((c) => !/Failed to load resource/.test(c)))) rep.anomaly(where, 'JavaScript: ' + e.slice(0, 160));
    }
  }
  await browser.close();
  return rep.finish(cfg);
}

run(main);
