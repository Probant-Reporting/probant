#!/usr/bin/env node
// Clicks every harmless control of some pages and reports what breaks: JavaScript errors, requests that fail, 5xx.
//
//   node qa/browser_journeys/click_all.js --roles contributeur --pages /pour-moi/,/saisie/ [--base URL] [--out FOLDER]
//                                         [--page-budget SECONDS (default 90)] [--click-timeout MS (default 1000)]
//
// For each page and each role given (default: admin; account name = role name), loads the page, then for each link,
// button, summary, tab, checkbox and radio of the main area (and of the header menus; first 60) reloads the page,
// clicks it and watches for half a second. Skipped: anything that writes, deletes, sends, signs out or downloads (by
// its text, in French or English, and by its address), and a button that submits a form that is not a GET form. A
// request other than GET during a click is reported as a warning (nothing should be written by a harmless click).
// ANOMALY: JavaScript error, console error, 5xx answer.
// A control that cannot be clicked within --click-timeout (hidden, covered, moving) is skipped and counted, not waited for;
// each page has a total time budget (--page-budget): when it is spent, the rest of the page is left and said so. A summary
// of every page (controls, clicked, skipped by reason, budget reached) is printed at the end and recorded as a warning.
// Warning: a click that cannot be done (control hidden or covered), a 4xx answer, a native dialog, a change of address (listed so that you look at where the click leads).
// Throwaway demo only: the skip list is a safety net, not a guarantee. Exit code 1 if there is an anomaly.
'use strict';
const { chromium, config, report, run, signIn } = require('./lib');

const SKIP = /supprim|retirer|effacer|restaur|réinitialis|desactiv|désactiv|clôtur|cloturer|envoyer|importer|valider|rouvrir|déconnect|delete|remove|logout|sign out|duplicate|dupliquer|créer|create|enregistrer|save|appliquer|apply|installer|install|ajouter|add|vider|purger|archiver|partager|share|send|import|restore|reset|close|reopen/i;
const SKIP_HREF = /^(mailto|tel):|logout|deconnexion|telecharger|download|export|excel|\.csv|\/modele|\/paquets\/|\/sauvegardes\//i;

async function main() {
  const cfg = config();
  const rep = report('click_all');
  const roles = cfg.roles.length ? cfg.roles : ['admin'];
  const pages = cfg.opts.pages ? String(cfg.opts.pages).split(',') : ['/saisie/', '/pour-moi/', '/tableau-de-bord/', '/coherence/', '/visualisation/', '/import-export/', '/mon-compte/'];
  const browser = await chromium.launch();
  const budget = (Number(cfg.opts['page-budget']) || 90) * 1000;
  const clickMs = Number(cfg.opts['click-timeout']) || 1000;
  const summary = [];
  const open = async (page, url) => { try { await page.goto(url, { waitUntil: 'networkidle', timeout: 8000 }); } catch (e) { await page.goto(url, { waitUntil: 'load', timeout: 15000 }).catch(() => {}); } };
  const sel = 'main a[href], main button, main summary, main [role=tab], main [role=button], main input[type=checkbox], main input[type=radio], header summary, header .bouton-choix-reponse';
  for (const role of roles) {
    const { page, log } = await signIn(browser, cfg, role);
    page.setDefaultTimeout(15000);
    const dialogs = []; page.on('dialog', (d) => { dialogs.push(d.type() + ':' + d.message().slice(0, 80)); d.dismiss(); });
    const writes = []; page.on('request', (r) => { if (r.method() !== 'GET') writes.push(r.method() + ' ' + r.url().replace(cfg.base, '')); });
    for (const u of pages) {
      await open(page, cfg.base + u);
      const n = await page.locator(sel).count();
      let done = 0;
      const skipped = { 'skip list': 0, 'hidden or disabled': 0, 'not clickable': 0 };
      const debut = Date.now();
      let budgetAtteint = false;
      for (let i = 0; i < Math.min(n, 60); i++) {
        if (Date.now() - debut > budget) { budgetAtteint = i; break; }
        await open(page, cfg.base + u);
        const el = page.locator(sel).nth(i);
        const info = await el.evaluate((e) => ({ tag: e.tagName, text: (e.innerText || e.getAttribute('aria-label') || e.title || e.name || '').trim().replace(/\s+/g, ' ').slice(0, 40), href: e.getAttribute('href') || '', visible: !!(e.offsetWidth || e.offsetHeight), submits: e.type === 'submit' || (e.tagName === 'BUTTON' && !e.type), getForm: e.form ? e.form.method === 'get' : true, disabled: e.disabled })).catch(() => null);
        if (!info || !info.visible || info.disabled) { skipped['hidden or disabled']++; continue; }
        if (SKIP.test(info.text) || SKIP_HREF.test(info.href) || (info.submits && !info.getForm)) { skipped['skip list']++; continue; }
        log.reset(); dialogs.length = 0; writes.length = 0;
        const before = page.url();
        const name = `${role} ${u} [${i}] ${info.tag} "${info.text}"`;
        try { await el.click({ timeout: clickMs }); await page.waitForTimeout(500); } catch (e) { skipped['not clickable']++; summary.push(`  not clickable: ${name}`); continue; }
        done++;
        for (const e of log.pageerrors) rep.anomaly(name, 'JavaScript error: ' + e.slice(0, 160));
        for (const e of log.console.filter((c) => !/Failed to load resource/.test(c))) rep.anomaly(name, 'console error: ' + e.slice(0, 160));
        for (const b of log.bad) (/^5\d\d /.test(b) ? rep.anomaly : rep.warning)(name, 'HTTP ' + b.slice(0, 120));
        if (writes.length) rep.warning(name, 'request that writes: ' + writes.join(', '));
        if (dialogs.length) rep.warning(name, 'native dialog: ' + dialogs.join(' | '));
        if (page.url() !== before) rep.warning(name, 'leads to ' + page.url().replace(cfg.base, ''));
      }
      const ligne = `${role} ${u}: ${n} controls, ${done} clicked, skipped ${Object.entries(skipped).map(([k, v]) => `${v} ${k}`).join(', ')}`
        + (budgetAtteint !== false ? `; page budget (${budget / 1000} s) reached at control ${budgetAtteint} of ${Math.min(n, 60)}` : '');
      console.log(ligne);
      summary.unshift(ligne);
      if (skipped['not clickable'] || budgetAtteint !== false) rep.warning(`${role} ${u}`, ligne.slice(ligne.indexOf(': ') + 2));
    }
  }
  await browser.close();
  console.log('\nSummary\n' + summary.join('\n'));
  return rep.finish(cfg);
}

run(main);
