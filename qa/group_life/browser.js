#!/usr/bin/env node
/*
Main journeys of the group-life scenario in a real browser (Node Playwright, Chromium), on the database left by
qa/group_life/run.py (never on real data).

    DATA_DIR=/folder/of/the/run python3 manage.py runserver 8205 --noreload &
    DATA_DIR=/folder/of/the/run node qa/group_life/browser.js --base http://127.0.0.1:8205 --py /path/to/python [--out DIR]

Journeys (French interface of the accounts, computer screen):
  1. administrator  creates the 2026 campaign of the annual framework (campaign panel) and opens it
  2. contributor    enters a value in the entry panel, keeps it as a draft, then validates it with a comment
  3. contributor    imports a file: preview (one line rejected), then import
  4. validator      validates the imported draft
  5. administrator  puts the validated value back to draft (reopening of a cell); the contributor validates again
  6. administrator  closes the entry (review) then closes the campaign (confirmation dialogs)
At each step: no JavaScript error, no 5xx answer, and the database says what the screen said (probe.py, read only).
Exit code 1 if a check fails; results.json and screenshots in --out.
*/
'use strict';
const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync } = require('child_process');
const { chromium } = require('playwright');

const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, all) => {
  if (a.startsWith('--')) acc.push([a.slice(2), all[i + 1] && !all[i + 1].startsWith('--') ? all[i + 1] : '1']);
  return acc;
}, []));
const BASE = (args.base || 'http://127.0.0.1:8205').replace(/\/$/, '');
const PY = args.py || 'python3';
const OUT = args.out || fs.mkdtempSync(path.join(os.tmpdir(), 'group-life-browser-'));
const PASSWORD = 'Group-life-2026';
const ROOT = path.dirname(path.dirname(__dirname));
const results = [];

function probe(...a) {
  return JSON.parse(execFileSync(PY, [path.join(__dirname, 'probe.py'), ...a.map(String)], { cwd: ROOT, env: process.env }).toString());
}

function check(step, ok, detail) {
  results.push({ step, ok: !!ok, detail: detail || '' });
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${step}${detail ? ' – ' + detail : ''}`);
}

async function session(browser, username) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: 'fr-FR' });
  const page = await context.newPage();
  const problems = [];
  page.on('pageerror', (e) => problems.push(`JavaScript error: ${e.message}`));
  page.on('console', (m) => { if (m.type() === 'error' && !/favicon/.test(m.text())) problems.push(`console: ${m.text()}`); });
  page.on('response', (r) => { if (r.status() >= 500) problems.push(`${r.status()} ${r.url()}`); });
  page.on('dialog', (d) => d.accept());
  await page.goto(`${BASE}/connexion/`);
  await page.fill('input[name=username]', username);
  await page.fill('input[name=password]', PASSWORD);
  await Promise.all([page.waitForNavigation(), page.click('form:has(input[name=username]) button[type=submit]')]);
  return { context, page, problems, username };
}

async function confirmIfAsked(page) {
  // confirmation dialog of the tool (<dialog> with [data-confirmer-ok]) or of the browser (accepted by the handler)
  const ok = page.locator('dialog[open] [data-confirmer-ok]');
  try {
    await ok.first().waitFor({ state: 'visible', timeout: 1500 });
    await ok.first().click();
  } catch (e) { /* no dialog */ }
}

async function clickAction(page, value, scope = 'body') {
  const b = page.locator(`${scope} button[name=action][value=${value}]`).first();
  await b.click();
  await confirmIfAsked(page);
  await page.waitForLoadState('networkidle');
}

function done(s, step) {
  check(`${step}: no JavaScript error, no 5xx (${s.username})`, s.problems.length === 0, s.problems.slice(0, 3).join(' | '));
  s.problems.length = 0;
}

(async () => {
  const browser = await chromium.launch();
  let ids = probe('ids');
  try {
    // 1. administrator: campaign 2026 created and opened
    const adm = await session(browser, 'gl-admin');
    if (!ids.campaign2026) {
      await adm.page.goto(`${BASE}/administration/campagnes/nouvelle/?referentiel=GROUPREP`);
      await adm.page.fill('input[name=exercice]', '2026');
      await clickAction(adm.page, 'enregistrer', 'form');
      ids = probe('ids');
    }
    check('1 campaign 2026 created from the panel', ids.campaign2026, JSON.stringify(ids));
    await adm.page.goto(`${BASE}/administration/campagnes/${ids.campaign2026}/`);
    // end date in the future: contributors can write
    const fin = new Date(Date.now() + 30 * 86400000).toISOString().slice(0, 10);
    const debut = new Date(Date.now() - 2 * 86400000).toISOString().slice(0, 10);
    await adm.page.fill('input[name=date_ouverture]', debut);
    await adm.page.fill('input[name=date_fin_saisie]', fin);
    await clickAction(adm.page, 'enregistrer', 'form');
    await adm.page.goto(`${BASE}/administration/campagnes/${ids.campaign2026}/`);
    await clickAction(adm.page, 'ouvrir');
    check('1 campaign opened', probe('campaign', ids.campaign2026).statut === 'ouverte', JSON.stringify(probe('campaign', ids.campaign2026)));
    await adm.page.screenshot({ path: path.join(OUT, '1-campaign.png') });
    done(adm, '1');

    // 2. contributor: entry panel, draft then validation
    const con = await session(browser, 'gl-con-1-1');
    const cell = `${BASE}/saisie/${ids.campaign2026}/WATER/${ids.site}/`;
    await con.page.goto(cell);
    await con.page.fill('#valeur', '1234');
    await clickAction(con.page, 'enregistrer', 'form.carte-saisie');
    let c = probe('cell', ids.campaign2026, 'WATER', ids.site);
    check('2 draft saved', c.statut === 'brouillon' && c.valeur && Number(c.valeur) === 1234, JSON.stringify(c));
    await con.page.goto(cell);
    await con.page.fill('#commentaire', 'Read on the meter in December.');
    await clickAction(con.page, 'valider', 'form.carte-saisie');
    c = probe('cell', ids.campaign2026, 'WATER', ids.site);
    check('2 value validated', c.statut === 'valide', JSON.stringify(c));
    await con.page.screenshot({ path: path.join(OUT, '2-entry.png') });
    done(con, '2');

    // 3. contributor: import with one rejected line
    const fichier = path.join(OUT, 'import.xlsx');
    probe('file', fichier, 'WATER', ids.second_site, '2500');
    await con.page.goto(`${BASE}/import-export/importer/`);
    await con.page.setInputFiles('input[type=file][name=fichier]', fichier);
    await clickAction(con.page, 'verifier');
    const apercu = await con.page.content();
    check('3 preview shows the rejected line', /NOPE/.test(apercu), '');
    await clickAction(con.page, 'confirmer');
    c = probe('cell', ids.campaign2026, 'WATER', ids.second_site);
    check('3 import written as a draft', c.statut === 'brouillon' && Number(c.valeur) === 2500, JSON.stringify(c));
    await con.page.screenshot({ path: path.join(OUT, '3-import.png') });
    done(con, '3');

    // 4. validator validates the imported draft
    const val = await session(browser, 'gl-val-1');
    await val.page.goto(`${BASE}/saisie/${ids.campaign2026}/WATER/${ids.second_site}/`);
    await clickAction(val.page, 'valider', 'form.carte-saisie');
    c = probe('cell', ids.campaign2026, 'WATER', ids.second_site);
    check('4 validator validated', c.statut === 'valide', JSON.stringify(c));
    done(val, '4');

    // 5. administrator reopens the cell (back to draft); the contributor validates again
    await adm.page.goto(cell);
    await clickAction(adm.page, 'brouillon', 'form.carte-saisie');
    c = probe('cell', ids.campaign2026, 'WATER', ids.site);
    check('5 back to draft by the administrator', c.statut === 'brouillon', JSON.stringify(c));
    await con.page.goto(cell);
    await clickAction(con.page, 'valider', 'form.carte-saisie');
    c = probe('cell', ids.campaign2026, 'WATER', ids.site);
    check('5 validated again by the contributor', c.statut === 'valide', JSON.stringify(c));
    done(adm, '5');
    done(con, '5');

    // 6. closure: review, then final closure
    await adm.page.goto(`${BASE}/administration/campagnes/${ids.campaign2026}/`);
    await clickAction(adm.page, 'revue');
    check('6 review', probe('campaign', ids.campaign2026).statut === 'revue', '');
    await adm.page.goto(`${BASE}/administration/campagnes/${ids.campaign2026}/`);
    await clickAction(adm.page, 'cloturer');
    check('6 closed', probe('campaign', ids.campaign2026).statut === 'cloturee', '');
    await adm.page.screenshot({ path: path.join(OUT, '6-closed.png') });
    // a contributor can no longer write: the field is disabled
    await con.page.goto(cell);
    check('6 field read-only after closure', await con.page.locator('#valeur').isDisabled(), '');
    done(adm, '6');
    done(con, '6');
  } catch (e) {
    check('journey crashed', false, e.message.split('\n')[0]);
  } finally {
    await browser.close();
    fs.writeFileSync(path.join(OUT, 'results.json'), JSON.stringify(results, null, 1));
    const failed = results.filter((r) => !r.ok);
    console.log(`\n${results.length - failed.length}/${results.length} checks passed; screenshots in ${OUT}`);
    process.exit(failed.length ? 1 : 0);
  }
})();
