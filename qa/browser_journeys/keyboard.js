#!/usr/bin/env node
// Keyboard use of the entry panel and of the dialogs, as the contributor.
//
//   node qa/browser_journeys/keyboard.js [--base URL] [--out FOLDER] [--roles contributeur]
//
// On "For me" (/pour-moi/) then on Data entry (/saisie/), without writing anything:
//   - Enter on a row (focused with the keyboard) opens the entry panel and moves the focus into it;
//   - Tab (30 times) and Shift+Tab never leave the panel (focus trap);
//   - Escape closes the panel (nothing was changed, so no question), the panel leaves the screen and the focus goes back
//     to the row;
//   - the "I answer to" button opens a dialog with the focus inside it; Escape closes it and gives the focus back;
//   - Tab (60 times) on Data entry: every element that gets the focus has a visible focus mark, is on screen and the
//     focus never falls back on the page body before the last element that can be reached with Tab (after the last one, the
//     focus leaves the page and comes back on the body: that is normal and is not reported);
//   - no JavaScript error.
// qa/browser_check.py already opens a cell with Enter and checks the focus mark on its list of pages; this script
// adds the focus trap, the return of the focus and the dialog. Exit code 1 if there is an anomaly.
'use strict';
const { chromium, config, report, run, signIn } = require('./lib');

const where = () => {
  const a = document.activeElement;
  return a ? a.tagName + '#' + a.id + '.' + String(a.className || '').slice(0, 25) + ' "' + (a.innerText || a.getAttribute('aria-label') || '').trim().slice(0, 25) + '"' : 'none';
};

async function main() {
  const cfg = config();
  const rep = report('keyboard');
  const role = cfg.roles[0] || 'contributeur';
  const browser = await chromium.launch();
  const { page, log } = await signIn(browser, cfg, role);
  await page.goto(cfg.base + '/pour-moi/', { waitUntil: 'networkidle' });
  const rows = page.locator('tr.ligne[data-statut=a_saisir]');
  if (await rows.count() === 0) {
    rep.warning('/pour-moi/', 'no row to enter for this account: panel checks skipped');
  } else {
    const row = rows.nth(Math.min(1, (await rows.count()) - 1));
    await row.focus();
    await page.keyboard.press('Enter'); await page.waitForTimeout(800);
    if (!(await page.evaluate(() => !!document.activeElement.closest('#panneau')))) rep.anomaly('/pour-moi/', 'Enter on a row does not move the focus into the entry panel: ' + await page.evaluate(where));
    let outside = 0;
    for (let i = 0; i < 30; i++) { await page.keyboard.press('Tab'); if (!(await page.evaluate(() => !!document.activeElement.closest('#panneau')))) outside++; }
    if (outside) rep.anomaly('/pour-moi/', `Tab left the entry panel ${outside} time(s) out of 30 (focus trap)`);
    for (let i = 0; i < 5; i++) await page.keyboard.press('Shift+Tab');
    if (!(await page.evaluate(() => !!document.activeElement.closest('#panneau')))) rep.anomaly('/pour-moi/', 'Shift+Tab left the entry panel');
    await page.keyboard.press('Escape'); await page.waitForTimeout(600);
    if (!(await page.evaluate(() => document.querySelector('#panneau').getBoundingClientRect().left >= innerWidth - 1))) rep.anomaly('/pour-moi/', 'Escape does not close the entry panel');
    else if (await page.evaluate(() => !!document.activeElement.closest('#panneau'))) rep.anomaly('/pour-moi/', 'the panel is closed but the focus stayed in it');
    else if (await page.evaluate(() => document.activeElement === document.body)) rep.warning('/pour-moi/', 'after Escape the focus is on the page body, not on the row');
  }
  const choose = page.locator('.bouton-choix-reponse').first();
  if (await choose.count()) {
    await choose.click(); await page.waitForTimeout(800);
    if (!(await page.locator('#choix-reponse').isVisible())) rep.anomaly('/pour-moi/', '"I answer to" does not open its dialog');
    else if (!(await page.evaluate(() => !!document.activeElement.closest('#choix-reponse')))) rep.anomaly('/pour-moi/', 'the focus is not inside the "I answer to" dialog: ' + await page.evaluate(where));
    await page.keyboard.press('Escape'); await page.waitForTimeout(400);
    if (await page.locator('#choix-reponse').isVisible()) rep.anomaly('/pour-moi/', 'Escape does not close the "I answer to" dialog');
    else if (!(await page.evaluate(() => document.activeElement.classList.contains('bouton-choix-reponse')))) rep.warning('/pour-moi/', 'after closing the dialog the focus is not back on its button: ' + await page.evaluate(where));
  }
  await page.goto(cfg.base + '/saisie/', { waitUntil: 'networkidle' });
  const bad = [];
  // the last element that can be reached with Tab, in the order of the page (marked once, read back in the loop)
  await page.evaluate(() => {
    const tabbable = [...document.querySelectorAll('a[href],button,input,select,textarea,summary,[tabindex]')]
      .filter((e) => e.tabIndex >= 0 && !e.disabled && !e.closest('[hidden],[inert]') && getComputedStyle(e).visibility !== 'hidden' && (e.offsetParent !== null || getComputedStyle(e).position === 'fixed'));
    if (tabbable.length) tabbable[tabbable.length - 1].setAttribute('data-clavier-dernier', '');
  });
  let apresLeDernier = false;
  for (let i = 0; i < 60 && !apresLeDernier; i++) {
    await page.keyboard.press('Tab');
    const r = await page.evaluate(() => {
      const a = document.activeElement;
      if (a === document.body) return { body: true };
      const cs = getComputedStyle(a), b = a.getBoundingClientRect();
      const mark = (cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0) || cs.boxShadow !== 'none';
      return { t: a.tagName + '.' + String(a.className || '').slice(0, 20) + ' "' + (a.innerText || a.getAttribute('aria-label') || '').trim().slice(0, 20) + '"', mark, shown: b.width > 0 && b.height > 0, top: Math.round(b.top), bottom: Math.round(b.bottom), h: innerHeight, dernier: a.hasAttribute('data-clavier-dernier') };
    });
    if (r.body) bad.push(i + ': focus fell back on the page body');
    else if (!r.mark) bad.push(i + ': no visible focus mark on ' + r.t);
    else if (!r.shown || r.bottom < 0 || r.top > r.h) bad.push(i + ': focused element off screen: ' + r.t);
    if (r.dernier) apresLeDernier = true;  // the next Tab leaves the page and the focus comes back on the body: not reported
  }
  for (const b of bad.slice(0, 8)) rep.anomaly('/saisie/ Tab', b);
  for (const e of log.pageerrors) rep.anomaly('JavaScript', e.slice(0, 160));
  await browser.close();
  return rep.finish(cfg);
}

run(main);
