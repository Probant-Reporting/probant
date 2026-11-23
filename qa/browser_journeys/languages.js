#!/usr/bin/env node
// Interface languages: the switch works, and no page shows a raw key, a text left in another language or a sideways scroll.
//
//   node qa/browser_journeys/languages.js [--base URL] [--out FOLDER] [--roles admin,lecteur] [--langs de,it]
//       [--pages /a/,/b/] [--routes routes.json] [--labels FOLDER] [--data FILE] [--no-narrow] [--keep-languages]
//
// Languages: every COMPLETE language of the interface, read from the label files (`libelles/`, or --labels): a language is
// complete when it has every zone file of English and exactly the keys of English. --langs picks some of them.
// Roles: admin, validateur, contributeur, lecteur, auditeur (--roles picks some). The reader and the auditor start from
// the page they land on after signing in, not from Data entry; a page that a role cannot open (not 200, or redirected)
// is skipped for this role.
// For each role and each language, switches the language with the buttons of the top bar, then for each page (a built-in
// list of the main pages, or --pages, or the routes without parameters of --routes) checks:
//   - <html lang> that does not follow the switch: ANOMALY;
//   - a raw key (admin.kpi.inconnu), a template tag ({{ }}, {% %}), "undefined", "NaN": ANOMALY;
//   - a text of the interface left in another language: ANOMALY. A visible text (text, placeholder, title, aria-label,
//     button value) that is, word for word, the French or the English value of a label key whose value in the current
//     language is different. Left out: a text that is also a text of the current language under another key (« Type »
//     in French), the name of each language in its own language, the catalogue of units and themes, the example texts and
//     the library models, the default reminder text, and the demo data listed in --data FILE (one text per line, default
//     `languages_demo_data.txt`: names of levels and of types stored in the database, translated by the installation);
//   - a JavaScript error: ANOMALY;
//   - the page scrolls sideways at 1 440 px and at 390 px (phone width, same page, window resized): ANOMALY, with a
//     screenshot in --out (--no-narrow skips 390 px);
//   - texts that look French on a page that is not French, without being in the label files at all (a hard-coded text):
//     warning only (a French word can be demo content).
// The languages of the run that are off in Administration > Settings > Languages are turned on first (the demo contents, names
// of levels and types, are shown in the default language for a language that is off, by design) and turned off again at the end
// (--keep-languages: no change to the settings). The language of the account (it is saved on the account by the switch) is put
// back as it was found when the run ends, even after an error. The switch writes one line to the history of the account each time: use a throwaway demo
// (`load_demo`: Exemplia, 2026 open). Exit code 1 if there is an anomaly.
'use strict';
const { chromium, config, report, run, signIn } = require('./lib');
const fs = require('fs');
const path = require('path');

const ROLES = ['admin', 'validateur', 'contributeur', 'lecteur', 'auditeur'];
const MAIN_PAGES = ['/saisie/', '/pour-moi/', '/tableau-de-bord/', '/tableau-de-bord/consolidation/', '/tableau-de-bord/relances/',
  '/visualisation/', '/historique/', '/coherence/', '/coherence/regles/', '/import-export/', '/import-export/listes-kpi/', '/referentiel/',
  '/mon-compte/', '/administration/', '/administration/campagnes/', '/administration/organisations/', '/administration/comptes/',
  '/administration/attributions/', '/administration/journal/', '/administration/formules/', '/administration/fichiers/',
  '/administration/parametres/', '/administration/parametres/niveaux/', '/administration/parametres/seuils/',
  '/administration/parametres/visualisation/', '/administration/parametres/referentiel/', '/administration/parametres/langues/',
  '/administration/parametres/hebergement/', '/administration/referentiels/', '/administration/referentiels/modeles/',
  '/administration/espaces/', '/confidentialite/'];
const RAW = /(\{\{|\}\}|\{%|%\(|%s\b|\[\[|\bundefined\b|\bNaN\b|\b[a-z_]+\.[a-z_]+\.[a-z_]+\b(?!\.))/;
// Words and letters of French that the language does not have: a hint for hard-coded text (warning only).
const FR_WORDS = 'les|des|du|une|pour|avec|sans|vous|votre|vos|sont|dans|aux|nouveau|nouvelle|enregistrer|ajouter|supprimer|modifier|valider|fermer|annuler|aucun|aucune|tous|toutes|choisir|rechercher|résultats?|saisie|campagne|paramètres|référentiels?';
const FALSE_FRIENDS = { it: ['campagne'], nl: ['campagne'], de: ['des'] };
const FR_LETTERS = { en: 'éèêàçùôî', de: 'éèêàçùôî', nl: 'èêàçùôî', es: 'èêàçùôî', it: 'êçôî', pt: 'èùî' };

// ---------------------------------------------------------------- label files
const norm = (t) => String(t).replace(/[  ]/g, ' ').replace(/\s+/g, ' ').trim();
const forms = (v) => (typeof v === 'string' ? [v] : Object.values(v || {}).filter((x) => typeof x === 'string'));

// {lang: {key: [forms]}} for every language that has files; complete: same zones and same keys as English.
function readLabels(dir) {
  const files = fs.readdirSync(dir).filter((f) => /^[a-z_]+\.[a-z]{2,3}\.json$/.test(f));
  const labels = {};
  for (const f of files) {
    const [zone, lang] = f.split('.');
    labels[lang] = labels[lang] || { zones: new Set(), keys: {} };
    labels[lang].zones.add(zone);
    for (const [k, v] of Object.entries(JSON.parse(fs.readFileSync(path.join(dir, f), 'utf8')))) labels[lang].keys[k] = forms(v);
  }
  const en = labels.en;
  if (!en) throw new Error('no English label files in ' + dir);
  const complete = Object.keys(labels).filter((l) => {
    const x = labels[l];
    if (x.zones.size !== en.zones.size || [...en.zones].some((z) => !x.zones.has(z))) return false;
    const a = Object.keys(x.keys), b = Object.keys(en.keys);
    return a.length === b.length && b.every((k) => k in x.keys);
  }).sort((a, b) => (a === 'fr' ? -1 : b === 'fr' ? 1 : a.localeCompare(b)));
  return { labels, complete };
}

// Pieces of a value between its {parameters} and tags (what a text node of the page holds), long enough to be a sentence
// and not a code, a file name or a setting (no space: SMTP_PORT, docs/installation.md).
const pieces = (v) => String(v).split(/\{[^}]*\}|<[^>]*>|\\n/).map(norm).filter((x) => x.length >= 12 && /\s/.test(x) && !/[{<]/.test(x));
// Keys that are the names of data installed in the language of the installation (the catalogue of units and themes): a
// page shows them as data (demo contents), not as interface text.
const DATA_KEYS = /^(admin\.catalogue_unites\.|admin\.reprise\.format\.ex_|referentiels\.mep\.organisation\.exemple\.|referentiels\.socle\.|cadre\.langue\.nom$|commun\.langue_nom\.|messages\.relances\.(message|sujet)_defaut$)/;
// (also: the names of the languages, each in its own language, and the default reminder text stored per language)

// For the language `lang`: texts that are the French or English value of a key with another value in `lang`.
//   exact: normalised text -> "key (fr|en)"; patterns: [{re, from}] for values with {parameters} or tags.
function foreignTable(labels, lang) {
  const exact = new Map(), patterns = [];
  const mine = labels[lang].keys;
  // every text of the current language, whatever the key: a word that is a legitimate text of this language elsewhere
  // (« Type » in French, « Organisation » in English) is not a leftover
  const ownAll = new Set(Object.values(mine).flatMap((fs_) => fs_.flatMap((v) => [norm(v), ...pieces(v)])));
  for (const ref of ['fr', 'en']) {
    if (ref === lang || !labels[ref]) continue;
    for (const [k, refForms] of Object.entries(labels[ref].keys)) {
      if (DATA_KEYS.test(k)) continue;
      const own = new Set((mine[k] || []).flatMap((v) => [norm(v), ...pieces(v)]));
      for (const v of refForms) {
        const n = norm(v);
        if (n.length < 4 || own.has(n) || ownAll.has(n) || /^[\d\s.,:%–·+\-/()]+$/.test(n)) continue;
        const from = `${k} (${ref})`;
        if (/[{<]/.test(n)) {
          // pieces between parameters and tags: the text nodes of the page hold such pieces or the whole text
          for (const piece of pieces(n)) if (!own.has(piece) && !ownAll.has(piece)) exact.set(piece, from);
          const re = n.split(/(\{[^}]*\})/).map((p) => (/^\{[^}]*\}$/.test(p) ? '.+?' : p.replace(/<[^>]*>/g, '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))).join('');
          if (/\{/.test(n) && n.replace(/\{[^}]*\}/g, '').replace(/<[^>]*>/g, '').trim().length >= 15) patterns.push({ re: new RegExp('^' + re + '$'), from });
        } else if (!exact.has(n)) exact.set(n, from);
      }
    }
  }
  return { exact, patterns };
}

// Normalised texts that appear in the label files of ANY language other than `lang` and are shared by every language:
// not needed here. A text is an interface text only if it is in the label files; demo content never is.

// ---------------------------------------------------------------- browser
// Switches the language with the buttons of the top bar. False if there is no button for this language.
async function switchTo(page, lang) {
  const button = page.locator(`button[name=langue][value=${lang}]`).first();
  const menu = page.locator('details:has(form.liste-langues) > summary');
  if (await menu.count()) await menu.click().catch(() => {});
  if (!(await button.count())) return false;
  await button.click();
  await page.waitForLoadState('networkidle');
  return true;
}

// Turns on, in Administration > Settings > Languages, the languages of the run that are off, and gives back the list of those it
// turned on (``setLanguagesActive(browser, cfg, codes, false)`` turns them off again). A language that is off shows the default
// language for the data of the installation (names of levels, types, units: ``parametres/0036``): the run would report the demo
// contents as texts left in another language. The administrator account of the demo does it, like a person would.
async function setLanguagesActive(browser, cfg, codes, on = true) {
  const { page, ctx } = await signIn(browser, cfg, 'admin');
  const changed = [], absent = [];
  try {
    await page.goto(cfg.base + '/administration/parametres/langues/', { waitUntil: 'networkidle' });
    for (const l of codes) {
      const box = page.locator(`input[type=checkbox][name="active__${l}"]`);
      if (!(await box.count())) { if (on) absent.push(l); continue; }  // not in the list of the installation at all
      if ((await box.isDisabled()) || (await box.isChecked()) === on) continue;
      await box.setChecked(on);
      changed.push(l);
    }
    if (changed.length) {
      await Promise.all([page.waitForNavigation({ waitUntil: 'networkidle' }), page.click('.barre-enregistrement button[type=submit]')]);
    }
  } finally {
    await ctx.close();
  }
  changed.absent = absent;
  return changed;
}

async function readTexts(page) {
  return page.evaluate(() => {
    const out = [];
    const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    while (w.nextNode()) {
      const n = w.currentNode, p = n.parentElement;
      if (!p || ['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEXTAREA'].includes(p.tagName)) continue;
      const t = n.textContent.trim();
      if (t.length > 2) out.push(t);
    }
    for (const e of document.querySelectorAll('[placeholder],[title],[aria-label],input[type=submit],input[type=button]')) {
      for (const a of ['placeholder', 'title', 'aria-label', 'value']) {
        if (a === 'value' && !/^(submit|button)$/.test(e.type || '')) continue;
        const v = e.getAttribute(a);
        if (v) out.push(v);
      }
    }
    return { texts: out, lang: document.documentElement.lang };
  });
}

async function overflow(page, width) {
  return page.evaluate((W) => {
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
    return { sw: de.scrollWidth, cw: de.clientWidth, out: out.slice(0, 4) };
  }, width);
}

async function main() {
  const cfg = config();
  const rep = report('languages');
  const roles = cfg.roles.length ? cfg.roles : ROLES;
  const labelsDir = path.resolve(cfg.opts.labels || path.join(__dirname, '..', '..', 'libelles'));
  const { labels, complete } = readLabels(labelsDir);
  const langs = cfg.opts.langs ? String(cfg.opts.langs).split(',') : complete;
  for (const l of langs) if (!complete.includes(l)) throw new Error(`"${l}" is not a complete language of ${labelsDir} (complete: ${complete.join(', ')})`);
  rep.note(`languages: ${langs.join(', ')}; roles: ${roles.join(', ')}`);
  const autonyms = new Set(Object.values(labels).flatMap((x) => x.keys['cadre.langue.nom'] || []).map(norm));  // « Français », « Deutsch »...
  const tables = Object.fromEntries(langs.map((l) => [l, foreignTable(labels, l)]));
  const everyLabel = new Set();  // every text of every label file of every language: what is not here is data
  for (const x of Object.values(labels)) for (const forms_ of Object.values(x.keys)) for (const f of forms_) everyLabel.add(norm(f));
  const dataPath = cfg.opts.data || path.join(__dirname, 'languages_demo_data.txt');
  const dataFile = new Set(fs.existsSync(dataPath) ? fs.readFileSync(dataPath, 'utf8').split('\n').filter((l) => !l.startsWith('#')).map(norm).filter(Boolean) : []);
  const narrow = !cfg.opts['no-narrow'];
  let pages = MAIN_PAGES;
  if (cfg.opts.pages) pages = String(cfg.opts.pages).split(',');
  else if (cfg.routes) pages = JSON.parse(fs.readFileSync(cfg.routes, 'utf8')).routes.filter((r) => !/[<>]/.test(r.route) && !r.free).map((r) => r.url);
  // anomalies of text are listed once per (language, text), with the pages where it shows
  const left = new Map();
  let shots = 0;
  const browser = await chromium.launch();
  // languages turned on for the run, turned off again at the end (--keep-languages: leave things as found, no change)
  const turnedOn = cfg.opts['keep-languages'] ? [] : await setLanguagesActive(browser, cfg, langs.filter((l) => l !== 'fr' && l !== 'en')).catch((e) => {
    rep.warning('languages', 'could not turn the languages on in Settings > Languages (' + String(e.message).split('\n')[0] + '): demo contents may be reported');
    return [];
  });
  if (turnedOn.length) rep.note(`turned on in Settings > Languages for the run: ${turnedOn.join(', ')} (put back at the end)`);
  if (turnedOn.absent && turnedOn.absent.length) {
    rep.warning('languages', `not in the list of Settings > Languages at all: ${turnedOn.absent.join(', ')}. Add them there first: the names of levels, types and units of the demo are shown in the default language until the installation holds their translation (parametres/0036), and are then reported as texts left in another language`);
  }
  try {
  for (const role of roles) {
    console.log(`== ${role}`);
    const { page, log } = await signIn(browser, cfg, role);
    const landing = page.url();
    const initial = await page.evaluate(() => document.documentElement.lang);  // the language of the account, as found
    const rolePages = [...new Set([landing.replace(cfg.base, ''), ...pages])];
    const texts = {};  // language -> page -> texts
    try {
      for (const lang of langs) {
        if (!(await switchTo(page, lang))) { rep.anomaly(`${role} ${lang}`, 'no language button for this language'); continue; }
        const now = await page.evaluate(() => document.documentElement.lang);
        if (now !== lang) rep.anomaly(`${role} ${lang}`, `<html lang> is "${now}" after the switch`);
        texts[lang] = {};
        let seen = 0;
        for (const u of rolePages) {
          log.reset();
          const r = await page.goto(cfg.base + u, { waitUntil: 'networkidle', timeout: 30000 }).catch(() => null);
          if (!r || r.status() !== 200 || !page.url().startsWith(cfg.base + u.split('?')[0])) continue;  // not a page of this role
          if (!/text\/html/.test(r.headers()['content-type'] || '')) continue;
          seen++;
          const res = await readTexts(page);
          texts[lang][u] = res.texts;
          const where = `${role} ${lang} ${u}`;
          if (res.lang !== lang) rep.anomaly(where, `<html lang> is "${res.lang}"`);
          const raw = [...new Set(res.texts.filter((t) => RAW.test(t) && !/^[A-Z]{2,}-?\d/.test(t) && !/@\S+\.(test|com|invalid)/.test(t) && !/\bhttps?:|\.(csv|xlsx|json|pdf|png|sqlite3?|zip)\b|\d\.\d/.test(t)))];
          for (const t of raw.slice(0, 5)) rep.anomaly(where, 'raw key or leftover: ' + t.slice(0, 120).replace(/\s+/g, ' '));
          for (const e of log.pageerrors) rep.anomaly(where, 'JavaScript error: ' + e.slice(0, 160));
          // a text of the interface left in French or English
          const { exact, patterns } = tables[lang];
          for (const t of new Set(res.texts.map(norm))) {
            if (t.length < 4 || dataFile.has(t) || autonyms.has(t)) continue;  // the name of a language, in its own language, is not a leftover
            let from = exact.get(t);
            if (!from) { const p = patterns.find((x) => x.re.test(t)); if (p) from = p.from; }
            if (!from) continue;
            const id = `${lang}\u0000${t}`;
            if (!left.has(id)) left.set(id, { lang, text: t, from, where: [] });
            left.get(id).where.push(`${role} ${u}`);
          }
          // sideways scroll at 1 440 px and at 390 px
          for (const width of narrow ? [1440, 390] : [1440]) {
            if (width !== 1440) { await page.setViewportSize({ width, height: 844 }); await page.waitForTimeout(150); }
            const m = await overflow(page, width);
            if (m.sw > m.cw) {
              rep.anomaly(`${where} @${width}px`, `scrolls sideways (scrollWidth ${m.sw} > ${m.cw}); sticking out: ${JSON.stringify(m.out)}`);
              if (shots++ < 40) await page.screenshot({ path: path.join(cfg.out, `languages_${role}_${lang}_${width}_${u.replace(/\W+/g, '_')}.png`) }).catch(() => {});
            }
            if (width !== 1440) await page.setViewportSize({ width: 1440, height: 900 });
          }
        }
        if (!seen) rep.anomaly(`${role} ${lang}`, 'no page could be read');
      }
    } finally {
      if (initial && (await page.evaluate(() => document.documentElement.lang)) !== initial) {
        await page.goto(landing, { waitUntil: 'networkidle' }).catch(() => {});
        if (!(await switchTo(page, initial))) rep.anomaly(`${role}`, `could not put the language "${initial}" of the account back`);
      }
    }
    // Hard-coded text that looks French: not in any label file, and not the same word in every other language (data)
    for (const lang of langs.filter((l) => texts[l] && l !== 'fr')) for (const u of Object.keys(texts[lang])) {
      // words that are also words of the language: « campagne » (Italian, Dutch), « des » (German)
      const words_ = FR_WORDS.split('|').filter((w) => !(FALSE_FRIENDS[lang] || []).includes(w)).join('|');
      const test = new RegExp(`\\b(${words_})\\b|[${FR_LETTERS[lang] || 'èêàçùôî'}]`, 'i');
      const words = (list) => new Set(list.flatMap((t) => t.split(/[\s–·:,;()«»“”"'’/]+/)).filter(Boolean));
      const others = langs.filter((l) => l !== lang && texts[l] && texts[l][u]).map((l) => words(texts[l][u]));
      const rest = (t) => t.split(/([\s–·:,;()«»“”"'’/]+)/).map((w) => (w && others.length && others.every((s) => s.has(w)) ? '' : w)).join('');
      const fr = [...new Set(texts[lang][u].map(norm).filter((t) => !/^\d/.test(t) && !everyLabel.has(t) && !dataFile.has(t) && test.test(rest(t))))];
      if (fr.length) rep.warning(`${role} ${lang} ${u}`, `${fr.length} text(s) not in the label files that look French, e.g. ${JSON.stringify(fr.slice(0, 3).map((t) => t.slice(0, 50)))}`);
    }
    await page.context().close();
  }
  } finally {
    if (turnedOn.length) {
      const back = await setLanguagesActive(browser, cfg, turnedOn, false).catch(() => []);
      if (back.length !== turnedOn.length) rep.anomaly('languages', `could not turn off again: ${turnedOn.filter((l) => !back.includes(l)).join(', ')} (Settings > Languages)`);
    }
  }
  await browser.close();
  // One line per text left in another language, with the pages where it shows
  for (const x of [...left.values()].sort((a, b) => a.lang.localeCompare(b.lang) || b.where.length - a.where.length)) {
    rep.anomaly(`${x.lang} (${x.where.length} page${x.where.length > 1 ? 's' : ''}: ${[...new Set(x.where)].slice(0, 3).join(', ')})`,
      `text left in another language: ${JSON.stringify(x.text.slice(0, 110))} = ${x.from}`);
  }
  return rep.finish(cfg);
}

run(main);
