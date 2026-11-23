#!/usr/bin/env node
/*
Complete user journeys in a real browser (Node Playwright, Chromium), on a disposable copy of the demo, in French,
English and Spanish, on a computer (1,440 px) and a phone (390 px).

    python3 manage.py load_demo                       # once, in a folder of your choice (DATA_DIR=…): 2026 is open
    node qa/journeys.js --demo /folder/of/the/demo [--langs fr,en,es] [--viewports desktop,phone]
                        [--out /folder/for/screenshots] [--port 8041] [--smtp-port 1041] [--only step,step]

For each language × screen: the demo folder is copied into a temporary folder (the demo itself is never touched), the
current campaign is put back "in preparation", two servers are started (one without e-mail, one connected to the fake
e-mail server qa/fake_smtp.py) and the journey runs, step by step:

  1. admin       prepares the campaign (end date) and opens it
  2. admin       creates an account (provisional password); the person changes it at the first login
  3. admin       assigns boxes (an entered KPI to the new account, two calculated KPIs to "contributeur")
  4. contributeur enters a value, "1,234" (ambiguous separator: thousands chosen), N/A with a comment, a PDF evidence,
                 validates, justifies a consistency alert, asks for a forced value on two calculated KPIs
  5. validateur  accepts one forced value and refuses the other
  6. admin       reminders: without SMTP, clean refusal; with the fake SMTP server, e-mails received
  7. admin       closes the entry (review), closes the campaign, reopens it, reopens it to contributors
  8. admin       exports: each saved export in Excel, one in CSV, the "Stop" button
  9. contributeur imports values: preview, rejected rows downloaded, corrected and re-imported
 10. lecteur, auditeur: tries to write everywhere through the interface: nothing written
 11. admin       Visualisation: creates a view with a visual
 12. admin       Settings (identity, levels, languages), Hosting (backup, restore)

At each step: no JavaScript error, no server error (500), and the expected data is in the database (checked with
qa/journeys_probe.py, read only). Exit code 1 if a check fails; results.json and screenshots in --out.
Prerequisites: Node with the "playwright" package and Chromium; Python with the tool's requirements.
*/
'use strict';
const fs = require('fs');
const os = require('os');
const path = require('path');
const http = require('http');
const { spawn, execFileSync } = require('child_process');
const { chromium } = require('playwright');

const RACINE = path.dirname(__dirname);
const MDP = 'demo-probant-2026';
const PDF = Buffer.from('%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n');
// texte technique qui ne doit jamais s'afficher (erreur Python ou JavaScript, clé de libellé, gabarit non rendu)
const TECHNIQUE = /Traceback|Exception|KeyError|ValueError|TypeError|\bNone\b|undefined|NaN|\[object Object\]|\{\{|\{%|saisie\.js\.|suivi\.[a-z_]+\.|admin\.[a-z_]+\.[a-z_]/;
const TECHNIQUE_EN = new RegExp(TECHNIQUE.source.replace('|\\bNone\\b', ''));
const VUES = { desktop: { width: 1440, height: 900 }, phone: { width: 390, height: 844, mobile: true } };

function lireArguments() {
  const a = { langs: 'fr,en,es', viewports: 'desktop,phone', port: 8041, smtpPort: 1041, out: '', demo: '', only: '' };
  const v = process.argv.slice(2);
  for (let i = 0; i < v.length; i++) {
    const cle = v[i].replace(/^--/, '').replace(/-([a-z])/g, (_, l) => l.toUpperCase());
    if (cle === 'help' || cle === 'h') { console.log(fs.readFileSync(__filename, 'utf8').split('*/')[0]); process.exit(0); }
    a[cle] = v[++i];
  }
  if (!a.demo || !fs.existsSync(path.join(a.demo, 'db.sqlite3'))) {
    console.error('--demo: folder of a loaded demo (with db.sqlite3) is required, see --help');
    process.exit(2);
  }
  a.port = +a.port; a.smtpPort = +a.smtpPort;
  a.out = a.out || fs.mkdtempSync(path.join(os.tmpdir(), 'parcours-'));
  fs.mkdirSync(a.out, { recursive: true });
  return a;
}

// ---------------------------------------------------------------- serveurs, sonde
function attendrePort(port, chemin = '/sante/', delai = 60000) {
  const fin = Date.now() + delai;
  return new Promise((ok, ko) => {
    const essai = () => {
      const r = http.get({ host: '127.0.0.1', port, path: chemin, timeout: 2000 }, (rep) => { rep.resume(); ok(); });
      r.on('error', () => (Date.now() > fin ? ko(new Error(`port ${port} silent`)) : setTimeout(essai, 300)));
    };
    essai();
  });
}

function lancer(cmd, args, env, journal) {
  const sortie = fs.openSync(journal, 'a');
  return spawn(cmd, args, { cwd: RACINE, env: { ...process.env, ...env }, stdio: ['ignore', sortie, sortie] });
}

class Sonde {
  constructor(env) {
    this.p = spawn('python3', ['qa/journeys_probe.py'], { cwd: RACINE, env: { ...process.env, ...env }, stdio: ['pipe', 'pipe', 'inherit'] });
    this.tampon = ''; this.attente = [];
    this.p.stdout.on('data', (d) => {
      this.tampon += d.toString();
      let i;
      while ((i = this.tampon.indexOf('\n')) >= 0) {
        const ligne = this.tampon.slice(0, i); this.tampon = this.tampon.slice(i + 1);
        const f = this.attente.shift(); if (f) f(JSON.parse(ligne));
      }
    });
  }
  async q(q, args = {}) {
    const rep = await new Promise((ok) => { this.attente.push(ok); this.p.stdin.write(JSON.stringify({ q, args }) + '\n'); });
    if (!rep.ok) throw new Error(`probe ${q}: ${rep.error}`);
    return rep.r;
  }
  fin() { this.p.stdin.end(); }
}

// ---------------------------------------------------------------- un passage (langue × écran)
class Passage {
  constructor(opts, langue, ecran) {
    Object.assign(this, { opts, langue, ecran });
    this.nom = `${langue}-${ecran}`;
    this.resultats = []; this.etapeCourante = '';
    this.attendus = [];  // motifs de messages d'erreur de la console attendus pendant l'étape (refus 403 du lecteur)
  }

  echec(texte) { this.resultats.push({ etape: this.etapeCourante, ok: false, texte }); console.log(`  ✗ [${this.nom}] ${this.etapeCourante}: ${texte}`); }
  ok(texte) { this.resultats.push({ etape: this.etapeCourante, ok: true, texte }); }
  verifie(cond, texte) { if (cond) this.ok(texte); else this.echec(texte); return !!cond; }

  async etape(nom, fonction) {
    if (this.opts.only && !this.opts.only.split(',').some((x) => nom.startsWith(x))) return;
    this.etapeCourante = nom;
    const debut = Date.now();
    const avant = this.resultats.filter((r) => !r.ok).length;
    try { await fonction(); } catch (e) {
      const ligne = ((e && e.stack) || '').split('\n').find((l) => l.includes('journeys.js')) || '';
      this.echec(`exception: ${(e && e.message || String(e)).split('\n').slice(0, 3).join(' ')} ${ligne.trim()}`);
      for (const p of this.pages) await p.screenshot({ path: path.join(this.opts.out, `${this.nom}-${nom}-${this.pages.indexOf(p)}.png`) }).catch(() => {});
    }
    const n = this.resultats.filter((r) => !r.ok).length - avant;
    console.log(`${n ? '✗' : '✓'} [${this.nom}] ${nom} (${((Date.now() - debut) / 1000).toFixed(1)} s)`);
  }

  async page(nomCompte) {
    const v = VUES[this.ecran];
    const ctx = await this.navigateur.newContext({ viewport: { width: v.width, height: v.height }, isMobile: !!v.mobile, hasTouch: !!v.mobile,
                                                  acceptDownloads: true, locale: this.langue });
    const page = await ctx.newPage();
    page.setDefaultTimeout(20000);
    page.compte = nomCompte;
    page.on('pageerror', (e) => this.echec(`JavaScript error (${nomCompte}, ${page.url()}): ${e.message}`));
    page.on('console', (m) => {
      if (m.type() !== 'error') return;
      if (this.attendus.some((x) => x.test(m.text()))) return;
      this.echec(`console error (${nomCompte}, ${page.url()}): ${m.text().slice(0, 200)}`);
    });
    page.on('response', (r) => { if (r.status() >= 500) this.echec(`server error ${r.status()} (${nomCompte}): ${r.request().method()} ${r.url()}`); });
    page.on('dialog', (d) => d.accept());
    if (process.env.JOURNEYS_DEBUG) {
      page.on('request', (r) => { if (r.method() === 'POST') console.log(`    → ${nomCompte} POST ${r.url()}`); });
      page.on('response', (r) => { if (r.request().method() === 'POST') console.log(`    ← ${nomCompte} ${r.status()} ${r.url()}`); });
    }  // confirmations (« Envoyer les relances ? ») : oui
    this.pages.push(page);
    return page;
  }

  url(chemin, smtp = false) { return `http://127.0.0.1:${smtp ? this.opts.port + 1 : this.opts.port}${chemin}`; }

  async connecter(page, identifiant, mdp = MDP, smtp = false) {
    await page.goto(this.url('/connexion/', smtp));
    // langue choisie sur la page de connexion, comme une personne : menu « langue » puis la langue
    if ((await page.evaluate(() => document.documentElement.lang)) !== this.langue) {
      await page.locator('details.menu-langue > summary').first().click();
      await Promise.all([page.waitForNavigation(), page.locator(`details.menu-langue button[name=langue][value=${this.langue}]`).first().click()]);
    }
    await page.fill('input[name=username]', identifiant);
    await page.fill('input[name=password]', mdp);
    await Promise.all([page.waitForNavigation(), page.click('form:has(input[name=password]) button[type=submit]')]);
    const lang = await page.evaluate(() => document.documentElement.lang);
    this.verifie(lang.startsWith(this.langue), `${identifiant}: page in ${this.langue} (lang=${lang})`);
  }

  // clic sur un bouton d'un formulaire envoyé sans quitter la page (data-ajax) : attend la réponse du serveur
  async poster(page, selecteur, motif = null) {
    const [rep] = await Promise.all([
      page.waitForResponse((r) => r.request().method() === 'POST' && (!motif || motif.test(r.url())), { timeout: 30000 }),
      page.locator(selecteur).first().click(),
    ]);
    await page.waitForLoadState('load').catch(() => {});
    await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {});
    await page.waitForTimeout(300);
    return rep;
  }

  async messages(page) {
    return page.evaluate(() => [...document.querySelectorAll('.messages li, .message, .toast, .erreur, .succes, [role=alert], .erreur-champ')]
      .map((e) => e.textContent.trim()).filter(Boolean).join(' | '));
  }

  async aucunTexteTechnique(page) {
    let t;
    for (let essai = 0; ; essai++) {  // une navigation peut être en cours (enregistrement suivi d'une redirection)
      try { t = await page.evaluate(() => document.body.innerText); break; } catch (e) {
        if (essai >= 3 || !/context was destroyed|navigation/i.test(e.message)) throw e;
        await page.waitForLoadState('load').catch(() => {});
        await page.waitForTimeout(500);
      }
    }
    // « None » est un mot anglais (« Aucun ») : cherché seulement hors de l'anglais
    const motif = this.langue === "en" ? TECHNIQUE_EN : TECHNIQUE;
    const m = motif.exec(t);
    this.verifie(!m, `no technical text on ${new URL(page.url()).pathname}${m ? ` (« ${t.slice(Math.max(0, m.index - 40), m.index + 40)} »)` : ''}`);
  }

  async sansDefilementHorizontal(page) {
    if (this.ecran !== 'phone') return;
    const d = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    this.verifie(d <= 1, `no horizontal scroll on ${new URL(page.url()).pathname} (${d} px)`);
  }

  // ---------------------------------------------------------------- le parcours
  async lancer() {
    const o = this.opts;
    this.dossier = fs.mkdtempSync(path.join(os.tmpdir(), `parcours-${this.nom}-`));
    const donnees = path.join(this.dossier, 'donnees');
    fs.cpSync(o.demo, donnees, { recursive: true });
    const env = { DATA_DIR: donnees, DJANGO_DEBUG: '1', GUIDED_TOUR: 'off' };
    const prep = JSON.parse(execFileSync('python3', ['qa/journeys_probe.py', '--prepare'], { cwd: RACINE, env: { ...process.env, ...env } }).toString());
    this.campagne = prep.campagne; this.exercice = prep.exercice;
    this.courriels = path.join(this.dossier, 'emails.json');
    const journal = path.join(o.out, `${this.nom}-serveurs.log`);
    this.procs = [
      lancer('python3', ['manage.py', 'runserver', `127.0.0.1:${o.port}`, '--noreload'], env, journal),
      lancer('python3', ['manage.py', 'runserver', `127.0.0.1:${o.port + 1}`, '--noreload'],
             { ...env, SMTP_HOST: '127.0.0.1', SMTP_PORT: String(o.smtpPort), SMTP_SECURITY: 'none', SMTP_FROM: 'reporting@exemple.test' }, journal),
      lancer('python3', ['qa/fake_smtp.py', '--port', String(o.smtpPort), '--file', this.courriels], {}, journal),
    ];
    try {
      await attendrePort(o.port); await attendrePort(o.port + 1);
      this.sonde = new Sonde(env);
      this.navigateur = await chromium.launch();
      this.pages = [];
      await this.parcours();
    } finally {
      if (this.navigateur) await this.navigateur.close();
      if (this.sonde) this.sonde.fin();
      for (const p of this.procs) p.kill();
    }
    return this.resultats;
  }

  async parcours() {
    const S = this.sonde;
    const c = this.campagne;
    const admin = await this.page('admin');
    let nouveau = null;
    let calcules = [];

    await this.etape('01-admin-opens-campaign', async () => {
      await this.connecter(admin, 'admin');
      this.verifie((await S.q('campagne', { pk: c })).statut === 'preparation', 'campaign in preparation before the journey');
      await admin.goto(this.url('/administration/campagnes/'));
      await this.aucunTexteTechnique(admin);
      await admin.goto(this.url(`/administration/campagnes/${c}/`));
      await admin.fill('form[data-form-campagne] input[name=date_fin_saisie]', `${this.exercice + 1}-03-31`);
      await this.poster(admin, 'form[data-form-campagne] button[name=action][value=enregistrer]');
      const fin = (await S.q('campagne_dates', { pk: c })).date_fin_saisie;
      this.verifie(fin === `${this.exercice + 1}-03-31`, `end of entry saved (${fin})`);
      await this.poster(admin, 'button[name=action][value=ouvrir]');
      this.verifie((await S.q('campagne', { pk: c })).statut === 'ouverte', 'campaign open in the database');
      await this.aucunTexteTechnique(admin);
      await this.sansDefilementHorizontal(admin);
    });

    await this.etape('02-admin-creates-account', async () => {
      const email = `camille.${this.nom}@exemple.test`;
      await admin.goto(this.url('/administration/comptes/nouveau/'));
      await admin.fill('input[name=first_name]', 'Camille');
      await admin.fill('input[name=last_name]', `Essai ${this.nom}`);
      await admin.fill('input[name=email]', email);
      await admin.locator('input[name=role][value=contributeur]').check({ force: true });
      await admin.fill('input[name=mot_de_passe]', 'Provisoire-2026-xy');
      await this.poster(admin, 'button[name=action][value=enregistrer]');
      const u = await S.q('utilisateur', { email });
      this.verifie(u && u.doit_changer_mdp === true, `account created, password to change (${JSON.stringify(u)})`);
      this.verifie(await admin.locator('.message-acces').count() > 0, 'access message shown with the provisional password');
      await this.aucunTexteTechnique(admin);
      nouveau = { email, pk: u && u.pk };
      // première connexion : changement du mot de passe imposé
      const p = await this.page('nouveau');
      await this.connecter(p, email, 'Provisoire-2026-xy');
      this.verifie(/mon-compte/.test(p.url()), `first login sends to "My account" (${p.url()})`);
      await p.fill('input[name=old_password]', 'Provisoire-2026-xy');
      await p.fill('input[name=new_password1]', 'Nouveau-mot-2026-zz');
      await p.fill('input[name=new_password2]', 'Nouveau-mot-2026-zz');
      await Promise.all([p.waitForLoadState('load'), p.locator('input[name=new_password2]').press('Enter')]);
      await p.waitForTimeout(500);
      this.verifie((await S.q('utilisateur', { email })).doit_changer_mdp === false, 'password changed, no longer to change');
      await p.goto(this.url('/pour-moi/'));
      this.verifie(/pour-moi/.test(p.url()), 'the new account reaches the tool');
      await this.aucunTexteTechnique(p);
    });

    await this.etape('03-admin-assigns-boxes', async () => {
      await admin.goto(this.url('/administration/attributions/?niveau=Site'));
      const td = admin.locator('td.cellule-attr[data-cle]').first();
      const cle = await td.getAttribute('data-cle');
      await td.locator('.bouton-spoc').click();
      await admin.fill('#choix-spoc input[type=search]', nouveau.email);
      await this.poster(admin, `#choix-spoc button[data-id="${nouveau.pk}"]`, /attributions/);
      const a = await S.q('attributions', { user: nouveau.email });
      this.verifie(a.includes(cle), `box ${cle} assigned to the new account (${a.join(', ')})`);
      // deux KPI calculés de France au contributeur (responsable du résultat : il pourra demander une valeur forcée)
      calcules = await S.q('calcules', { campagne: c, org_nom: 'France', n: 2 });
      const contributeur = await S.q('utilisateur', { username: 'contributeur' });
      for (const k of calcules) {
        await admin.goto(this.url(`/administration/attributions/?niveau=${k.niveau}&calcules=1`));
        await admin.locator(`td[data-cle="${k.kpi}|${k.org}"] .bouton-spoc`).click();
        await admin.fill('#choix-spoc input[type=search]', 'contributeur@');
        await this.poster(admin, `#choix-spoc button[data-id="${contributeur.pk}"]`, /attributions/);
      }
      const a2 = await S.q('attributions', { user: 'contributeur' });
      this.verifie(calcules.every((k) => a2.includes(`${k.kpi}|${k.org}`)), `calculated KPIs ${calcules.map((k) => k.kpi).join(', ')} assigned to contributeur`);
      await this.aucunTexteTechnique(admin);
    });

    const contrib = await this.page('contributeur');
    await this.etape('04-contributor-enters', async () => {
      await this.connecter(contrib, 'contributeur');
      const cases = await S.q('cases', { user: 'contributeur', campagne: c, n: 8 });
      const [A, B, C, D] = cases;
      const ouvrir = async (x) => { await contrib.goto(this.url(`/saisie/${c}/${x.kpi}/${x.org}/`)); await contrib.waitForSelector('form[data-garde]'); };
      // séparateur ambigu : « 1,234 » → question → milliers
      await ouvrir(A);
      await contrib.fill('form[data-garde] input[name=valeur]', '1,234');
      await contrib.locator('form[data-garde] button[name=action][value=enregistrer]').first().click();
      await contrib.waitForSelector('.question-separateur [data-lecture=milliers]');
      const [rep] = await Promise.all([contrib.waitForResponse((r) => r.request().method() === 'POST'),
                                       contrib.click('.question-separateur [data-lecture=milliers]')]);
      await contrib.waitForTimeout(400);
      let r = await S.q('reponse', { campagne: c, kpi: A.kpi, org: A.org });
      this.verifie(r && r.valeur === '1234', `"1,234" read as thousands: ${r && r.valeur}`);
      // N/A et commentaire
      await ouvrir(B);
      await contrib.locator('form[data-garde] input[name=non_applicable]').check({ force: true });
      await contrib.fill('form[data-garde] textarea[name=commentaire]', 'Pas de site concerné cette année');
      await this.poster(contrib, 'form[data-garde] button[name=action][value=enregistrer]');
      r = await S.q('reponse', { campagne: c, kpi: B.kpi, org: B.org });
      this.verifie(r && r.na && r.commentaire === 'Pas de site concerné cette année', `N/A with comment saved (${JSON.stringify(r)})`);
      // valeur + preuve PDF, puis Valider
      await ouvrir(C);
      await contrib.fill('form[data-garde] input[name=valeur]', '250');
      await this.poster(contrib, 'form[data-garde] button[name=action][value=enregistrer]');
      await contrib.setInputFiles('form.depot-preuve input[type=file]', { name: 'facture énergie.pdf', mimeType: 'application/pdf', buffer: PDF });
      await contrib.locator('form.depot-preuve button[name=action][value=preuve]').waitFor({ state: 'visible' });
      await this.poster(contrib, 'form.depot-preuve button[name=action][value=preuve]');
      this.verifie((await S.q('preuves', { campagne: c, kpi: C.kpi, org: C.org })) === 1, 'PDF evidence attached');
      // un écart fort avec N-1 bloque la validation : la personne l'explique dans le commentaire, puis valide
      await contrib.fill('form[data-garde] textarea[name=commentaire]', 'Nouvelle méthode de mesure');
      await this.poster(contrib, 'form[data-garde] button[name=action][value=valider]');
      r = await S.q('reponse', { campagne: c, kpi: C.kpi, org: C.org });
      this.verifie(r && r.statut === 'valide' && r.valeur === '250', `value validated (${JSON.stringify(r)})`);
      await this.aucunTexteTechnique(contrib);
      await this.sansDefilementHorizontal(contrib);
      // séparateur ambigu, lecture décimale
      await ouvrir(D);
      await contrib.fill('form[data-garde] input[name=valeur]', this.langue === 'en' ? '2.500' : '2,500');
      await contrib.locator('form[data-garde] button[name=action][value=enregistrer]').first().click();
      await contrib.waitForSelector('.question-separateur [data-lecture=decimal]');
      await Promise.all([contrib.waitForResponse((x) => x.request().method() === 'POST'), contrib.click('.question-separateur [data-lecture=decimal]')]);
      await contrib.waitForTimeout(400);
      r = await S.q('reponse', { campagne: c, kpi: D.kpi, org: D.org });
      this.verifie(r && r.valeur === '2.5', `ambiguous separator read as decimal: ${r && r.valeur}`);
    });

    await this.etape('05-contributor-justifies-alert', async () => {
      const al = await S.q('alerte_justifiable', { user: 'contributeur', campagne: c });
      if (!this.verifie(al, 'an alert to justify exists for contributeur')) return;
      await contrib.goto(this.url(`/saisie/${c}/${al.kpi}/${al.org}/`));
      const f = contrib.locator(`form[data-justification]:has(input[name=alerte][value="${al.pk}"])`);
      await f.locator('textarea').fill('Changement de fournisseur en cours d\'année');
      await this.poster(contrib, `form[data-justification]:has(input[name=alerte][value="${al.pk}"]) button[name=action][value=justifier]`);
      const x = await S.q('alerte', { pk: al.pk });
      this.verifie(x && x.statut === 'justifiee' && /fournisseur/.test(x.justification), `alert justified (${JSON.stringify(x)})`);
      await this.aucunTexteTechnique(contrib);
    });

    await this.etape('06-contributor-asks-forced-value', async () => {
      for (const [i, k] of calcules.entries()) {
        await contrib.goto(this.url(`/saisie/${c}/${k.kpi}/${k.org}/`));
        await contrib.locator('details.forcage-demande summary').click();
        await contrib.fill('input[name=valeur_forcee]', String(1000 + i));
        await contrib.fill('textarea[name=justification]', 'Le calcul ne tient pas compte du site fermé');
        await this.poster(contrib, 'button[name=action][value=forcer]');
        const d = await S.q('demandes', { kpi: k.kpi, org: k.org });
        this.verifie(d.length === 1 && d[0].statut === 'en_attente', `forced value requested on ${k.kpi} (${JSON.stringify(d)})`);
      }
      await this.aucunTexteTechnique(contrib);
    });

    await this.etape('07-validator-accepts-refuses', async () => {
      const v = await this.page('validateur');
      await this.connecter(v, 'validateur');
      await v.goto(this.url('/valeurs-forcees/'));
      await this.aucunTexteTechnique(v);
      for (const [i, k] of calcules.entries()) {
        await v.goto(this.url(`/saisie/${c}/${k.kpi}/${k.org}/`));
        if (i === 1) await v.fill('textarea[name=motif]', 'Valeur non justifiée par une pièce');
        await this.poster(v, `button[name=action][value=${i === 0 ? 'accepter_forcage' : 'refuser_forcage'}]`);
        const d = await S.q('demandes', { kpi: k.kpi, org: k.org });
        this.verifie(d[0] && d[0].statut === (i === 0 ? 'acceptee' : 'refusee'), `forced value ${i === 0 ? 'accepted' : 'refused'} (${JSON.stringify(d)})`);
      }
      const r = await S.q('reponse', { campagne: c, kpi: calcules[0].kpi, org: calcules[0].org });
      this.verifie(r && r.valeur === '1000', `accepted forced value in place (${r && r.valeur})`);
      await this.sansDefilementHorizontal(v);
    });

    await this.etape('08-admin-reminders', async () => {
      // sans SMTP : pas de bouton d'envoi, explication ; un envoi forgé est refusé proprement, rien de noté
      await admin.goto(this.url('/tableau-de-bord/relances/'));
      this.verifie(await admin.locator('button[name=action][value=envoyer]').count() === 0, 'without SMTP: no "Send" button');
      const avant = (await S.q('relances', { n: 50 })).length;
      const [statut, msg] = await admin.evaluate(async () => {
        const f = new FormData();
        f.append('csrfmiddlewaretoken', document.querySelector('[name=csrfmiddlewaretoken]').value);
        f.append('action', 'envoyer'); f.append('personnes', '1');
        const r = await fetch(location.pathname, { method: 'POST', body: f });
        const doc = new DOMParser().parseFromString(await r.text(), 'text/html');
        return [r.status, [...doc.querySelectorAll('.messages li, [role=alert], .message')].map((e) => e.textContent.trim()).join(' | ')];
      });
      this.verifie(statut < 500, `forged send without SMTP refused (status ${statut})`);
      this.verifie(msg.length > 0, `refusal explained: ${msg.slice(0, 160)}`);
      this.verifie((await S.q('relances', { n: 50 })).length === avant, 'nothing recorded as sent without SMTP');
      await admin.goto(this.url('/administration/parametres/hebergement/'));
      await Promise.all([admin.waitForLoadState('load'), admin.click('button[name=action][value=tester_email]')]);
      await this.aucunTexteTechnique(admin);
      // avec le faux serveur SMTP
      const a2 = await this.page('admin-smtp');
      await this.connecter(a2, 'admin', MDP, true);
      await a2.goto(this.url('/tableau-de-bord/relances/', true));
      const cases = a2.locator('input[name=personnes]');
      const n = await cases.count();
      if (!this.verifie(n > 0, `with SMTP: ${n} person(s) to remind`)) return;
      for (let i = 0; i < n; i++) await cases.nth(i).uncheck({ force: true });
      await cases.first().check({ force: true });
      await Promise.all([a2.waitForLoadState('load'), a2.click('button[name=action][value=envoyer]')]);
      await a2.waitForTimeout(1500);
      const recus = fs.existsSync(this.courriels) ? JSON.parse(fs.readFileSync(this.courriels, 'utf8')) : [];
      this.verifie(recus.length >= 1, `e-mail received by the fake SMTP server (${recus.length})`);
      const rel = await S.q('relances', { n: 1 });
      this.verifie(rel[0] && rel[0].statut === 'envoyee', `reminder recorded as sent (${JSON.stringify(rel)})`);
      await this.aucunTexteTechnique(a2);
    });

    await this.etape('09-admin-closes-reopens', async () => {
      await admin.goto(this.url(`/administration/campagnes/${c}/`));
      for (const [action, statut] of [['revue', 'revue'], ['cloturer', 'cloturee'], ['rouvrir', 'revue'], ['rouvrir_contributeurs', 'ouverte']]) {
        await this.poster(admin, `button[name=action][value=${action}]`);
        const s = (await S.q('campagne', { pk: c })).statut;
        this.verifie(s === statut, `${action} → ${s}`);
        if (statut === 'cloturee') {  // le contributeur ne peut plus rien modifier
          await contrib.goto(this.url(`/saisie/${c}/${(await S.q('cases', { user: 'contributeur', campagne: c, n: 1 }))[0].kpi}/${(await S.q('cases', { user: 'contributeur', campagne: c, n: 1 }))[0].org}/`));
          this.verifie(await contrib.locator('form[data-garde] input[name=valeur]:not([disabled])').count() === 0, 'closed: the entry field is disabled for the contributor');
        }
        await admin.goto(this.url(`/administration/campagnes/${c}/`));
      }
      await this.aucunTexteTechnique(admin);
    });

    await this.etape('10-admin-exports', async () => {
      await admin.goto(this.url('/import-export/'));
      const liens = admin.locator('a[data-telechargement][href*="telecharger=1"]');
      const n = await liens.count();
      this.verifie(n >= 3, `${n} saved exports`);
      for (let i = 0; i < n; i++) {
        const [dl] = await Promise.all([admin.waitForEvent('download', { timeout: 120000 }), liens.nth(i).click()]);
        const f = path.join(this.dossier, `export-${i}-${dl.suggestedFilename()}`);
        await dl.saveAs(f);
        const debut = fs.readFileSync(f).subarray(0, 2).toString();
        this.verifie(fs.statSync(f).size > 500 && (debut === 'PK' || f.endsWith('.csv')), `export ${i + 1}: ${dl.suggestedFilename()} (${fs.statSync(f).size} bytes)`);
        await admin.waitForTimeout(600);
      }
      // en CSV : depuis les réglages du premier export
      const href = await liens.first().getAttribute('href');
      await admin.goto(this.url(href.replace('&telecharger=1', '')));
      await admin.locator('input[name=format][value=csv]').check({ force: true });
      const [dl] = await Promise.all([admin.waitForEvent('download', { timeout: 120000 }), admin.locator('button[value=telecharger]').first().click()]);
      this.verifie(/\.csv$/.test(dl.suggestedFilename()), `CSV export: ${dl.suggestedFilename()}`);
      // « Arrêter » : réponse retardée, l'export est arrêté, rien n'est téléchargé
      await admin.goto(this.url('/import-export/'));
      await admin.route('**/import-export/exporter/**', async (route) => { await new Promise((ok) => setTimeout(ok, 4000)); await route.continue().catch(() => {}); });
      this.attendus.push(/abort|ERR_ABORTED|net::/i);
      let telecharge = false;
      admin.once('download', () => { telecharge = true; });
      await admin.locator('a[data-telechargement][href*="telecharger=1"]').first().click();
      await admin.waitForSelector('.chargement-arreter');
      await admin.click('.chargement-arreter');
      await admin.waitForTimeout(5000);
      this.verifie(!telecharge && await admin.locator('.chargement').count() === 0, 'export stopped: no file, window closed');
      await admin.unroute('**/import-export/exporter/**');
      this.attendus.pop();
      await this.aucunTexteTechnique(admin);
    });

    await this.etape('11-contributor-imports', async () => {
      const cases = await S.q('cases', { user: 'contributeur', campagne: c, n: 8 });
      const [, , , , E, F, G] = cases;
      const csv = ['ID KPI;Organisation;Exercice;Valeur;Commentaire',
                   `${E.kpi};${E.org_nom};${this.exercice};321;import`,
                   `${F.kpi};${F.org_nom};${this.exercice};abc;import`,
                   `${G.kpi};${G.org_nom};${this.exercice};12 %;import`].join('\r\n');
      await contrib.goto(this.url('/import-export/importer/'));
      await contrib.setInputFiles('input[name=fichier]', { name: 'valeurs.csv', mimeType: 'text/csv', buffer: Buffer.from(csv, 'utf8') });
      await Promise.all([contrib.waitForNavigation(), contrib.click('button[name=action][value=verifier]')]);
      await this.aucunTexteTechnique(contrib);
      const lien = contrib.locator('a[href*="import-export/importer/rejets"]').first();
      this.verifie(await lien.count() === 1, 'preview: rejected rows can be downloaded');
      const [dl] = await Promise.all([contrib.waitForEvent('download'), lien.click()]);
      const brut = path.join(this.dossier, 'rejets.xlsx'), corrige = path.join(this.dossier, 'rejets-corriges.xlsx');
      await dl.saveAs(brut);
      execFileSync('python3', ['qa/journeys_probe.py', '--fix-xlsx', brut, corrige, 'abc=42', '12 %=12'], { cwd: RACINE });
      await contrib.waitForTimeout(500);
      await Promise.all([contrib.waitForNavigation(), contrib.click('button[name=action][value=confirmer]')]);
      let r = await S.q('reponse', { campagne: c, kpi: E.kpi, org: E.org });
      this.verifie(r && r.valeur === '321', `valid row imported (${r && r.valeur})`);
      r = await S.q('reponse', { campagne: c, kpi: F.kpi, org: F.org });
      this.verifie(!r || r.valeur !== 'abc', 'refused row not written');
      // les lignes refusées, corrigées, réimportées
      await contrib.goto(this.url('/import-export/importer/'));
      await contrib.setInputFiles('input[name=fichier]', corrige);
      await Promise.all([contrib.waitForNavigation(), contrib.click('button[name=action][value=verifier]')]);
      await Promise.all([contrib.waitForNavigation(), contrib.click('button[name=action][value=confirmer]')]);
      r = await S.q('reponse', { campagne: c, kpi: F.kpi, org: F.org });
      this.verifie(r && r.valeur === '42', `corrected row re-imported (${r && r.valeur})`);
      r = await S.q('reponse', { campagne: c, kpi: G.kpi, org: G.org });
      this.verifie(r && r.valeur === '12', `corrected row re-imported (${r && r.valeur})`);
      await this.aucunTexteTechnique(contrib);
      await this.sansDefilementHorizontal(contrib);
    });

    for (const [num, qui] of [['12', 'lecteur'], ['13', 'auditeur']]) {
      await this.etape(`${num}-${qui}-writes-nothing`, async () => {
        const p = await this.page(qui);
        await this.connecter(p, qui);
        const avant = await S.q('empreinte');
        this.attendus.push(/403|Forbidden/i);
        const cible = (await S.q('cases', { user: 'contributeur', campagne: c, n: 1 }))[0];
        const pages = ['/saisie/', `/saisie/${c}/${cible.kpi}/${cible.org}/`, '/tableau-de-bord/', '/visualisation/', '/coherence/',
                       '/import-export/', '/import-export/importer/', '/administration/', '/administration/campagnes/', '/tableau-de-bord/relances/',
                       '/valeurs-forcees/', '/historique/', '/mon-compte/'];
        for (const u of pages) {
          const rep = await p.goto(this.url(u));
          this.verifie(rep.status() < 500, `${qui} ${u}: ${rep.status()}`);
          // chaque bouton d'envoi actif de la page est essayé (sauf langue, déconnexion, recherche) : rien ne doit s'écrire
          const boutons = await p.locator('form[method=post] button[type=submit]:not([disabled]):visible, form[method=post] input[type=submit]:visible').count();
          for (let i = 0; i < Math.min(boutons, 6); i++) {
            const b = p.locator('form[method=post] button[type=submit]:not([disabled]):visible').nth(i);
            const action = await b.evaluate((x) => (x.form && x.form.action) || '').catch(() => '');
            if (/langue|deconnexion|mon-compte/.test(action)) continue;
            await b.click({ timeout: 3000 }).catch(() => {});
            await p.waitForTimeout(400);
            if (new URL(p.url()).pathname !== u) await p.goto(this.url(u));
          }
        }
        // envois forgés depuis la page (comme un script) : saisie, validation, attribution, campagne, import
        const statuts = await p.evaluate(async ({ c, k, o }) => {
          const jeton = document.cookie.split('; ').find((x) => x.startsWith('csrftoken='))?.split('=')[1] || '';
          const envoi = async (url, donnees, json) => {
            const r = await fetch(url, { method: 'POST', headers: json ? { 'X-CSRFToken': jeton, 'Content-Type': 'application/json' } : { 'X-CSRFToken': jeton },
                                         body: json ? JSON.stringify(donnees) : Object.entries(donnees).reduce((f, [a, b]) => (f.append(a, b), f), new FormData()) });
            return r.status;
          };
          return [
            await envoi(`/saisie/${c}/${k}/${o}/`, { action: 'enregistrer', valeur: '999' }),
            await envoi(`/saisie/${c}/${k}/${o}/`, { action: 'valider' }),
            await envoi('/attributions/', { cles: [`${k}|${o}`], utilisateur: 1 }, true),
            await envoi(`/administration/campagnes/${c}/`, { action: 'cloturer' }),
            await envoi('/import-export/importer/', { action: 'confirmer' }),
            await envoi(`/coherence/regles/nouvelle/`, { nom: 'x' }),
          ];
        }, { c, k: cible.kpi, o: cible.org });
        this.verifie(statuts.every((s) => s < 500), `${qui}: forged requests answered without error (${statuts.join(', ')})`);
        this.attendus.pop();
        const apres = await S.q('empreinte');
        const changees = Object.keys({ ...avant, ...apres }).filter((t) => avant[t] !== apres[t]);
        this.verifie(changees.length === 0, `${qui}: nothing written in the database${changees.length ? ` (changed: ${changees.join(', ')})` : ''}`);
        await this.aucunTexteTechnique(p);
      });
    }

    await this.etape('14-admin-visualisation', async () => {
      const avant = (await S.q('vues', { user: 'admin' })).length;
      await admin.goto(this.url('/visualisation/vues/nouvelle/'));
      if (this.ecran === 'phone') {
        const b = admin.locator('[data-ouvrir-panneau=kpi]');
        if (await b.isVisible().catch(() => false)) await b.click();
      }
      await admin.locator('[data-ajouter-autre=remplissage]').first().click();
      await admin.waitForTimeout(800);
      await admin.locator('[data-fermer-panneau]:visible').first().click().catch(() => {});
      const nom = `Vue ${this.nom}`;
      await admin.locator('input[name=nom]:visible, [data-nom-vue]:visible').first().fill(nom).catch(async () => {
        await admin.getByRole('textbox', { name: /Nom de la vue|View name|Nombre de la vista/i }).fill(nom);
      });
      await this.poster(admin, '[data-enregistrer-vue]:visible', /visualisation\/vues/);
      await admin.waitForURL(/visualisation\/vues\/\d+/, { timeout: 15000 }).catch(() => {});
      await admin.waitForLoadState('load');
      const vues = await S.q('vues', { user: 'admin' });
      this.verifie(vues.length === avant + 1 && vues[vues.length - 1].visuels >= 1, `view created with a visual (${JSON.stringify(vues.slice(-1))})`);
      await this.aucunTexteTechnique(admin);
    });

    await this.etape('15-admin-settings', async () => {
      await admin.goto(this.url('/administration/parametres/'));
      await admin.fill('input[name=sous_titre]', `Recette ${this.nom}`);
      await Promise.all([admin.waitForLoadState('load'), admin.locator('form.page-identite button[type=submit]:not([name])').first().click()]);
      await admin.waitForTimeout(500);
      this.verifie((await S.q('instance')).sous_titre === `Recette ${this.nom}`, 'identity saved');
      await admin.goto(this.url('/administration/parametres/niveaux/'));
      await admin.fill('input[name=nom_Site]', 'Site industriel');
      await Promise.all([admin.waitForLoadState('load'), admin.click('button[name=action][value=enregistrer]')]);
      await admin.waitForTimeout(500);
      const niv = await S.q('niveaux');
      this.verifie(niv.some((n) => n.code === 'Site' && n.nom === 'Site industriel'), `level renamed (${JSON.stringify(niv)})`);
      await admin.goto(this.url('/administration/parametres/langues/'));
      await admin.fill('form:has(button[name=action][value=ajouter]) input[name=code]', 'it');
      await admin.fill('form:has(button[name=action][value=ajouter]) input[name=libelle]', 'Italiano');
      await Promise.all([admin.waitForLoadState('load'), admin.click('button[name=action][value=ajouter]')]);
      await admin.waitForTimeout(500);
      const langues = await S.q('langues');
      this.verifie(langues.some((l) => l.code === 'it'), `language added (${langues.map((l) => l.code).join(', ')})`);
      await this.aucunTexteTechnique(admin);
      await this.sansDefilementHorizontal(admin);
      // Hébergement : sauvegarde, puis restauration de cette sauvegarde
      await admin.goto(this.url('/administration/parametres/hebergement/'));
      const [dl] = await Promise.all([admin.waitForEvent('download', { timeout: 120000 }), admin.click('button[name=action][value=sauvegarder]')]);
      const f = path.join(this.dossier, dl.suggestedFilename());
      await dl.saveAs(f);
      this.verifie(fs.statSync(f).size > 10000, `backup downloaded (${dl.suggestedFilename()}, ${fs.statSync(f).size} bytes)`);
      // une modification après la sauvegarde, que la restauration doit défaire
      await admin.goto(this.url('/administration/parametres/'));
      await admin.fill('input[name=sous_titre]', 'Après la sauvegarde');
      await Promise.all([admin.waitForLoadState('load'), admin.locator('form.page-identite button[type=submit]:not([name])').first().click()]);
      await admin.waitForTimeout(500);
      this.verifie((await S.q('instance')).sous_titre === 'Après la sauvegarde', 'identity changed after the backup');
      await admin.goto(this.url('/administration/parametres/hebergement/'));
      await admin.locator('details:has(form.depot-sauvegarde) > summary').click();
      await admin.setInputFiles('form.depot-sauvegarde input[type=file]', f);
      await Promise.all([admin.waitForNavigation(), admin.click('form.depot-sauvegarde button[type=submit]')]);
      await this.aucunTexteTechnique(admin);
      await admin.locator('input[name=compris]').check({ force: true });
      await admin.fill('input[name=confirmation]', await admin.locator('input[name=confirmation]').getAttribute('placeholder'));
      await Promise.all([admin.waitForNavigation({ timeout: 120000 }), admin.click('form.confirmation-restauration button[type=submit]')]);
      this.verifie(/connexion/.test(admin.url()), `after the restore, back to the login page (${admin.url()})`);
      this.verifie((await S.q('journal', { action: 'restauration' })) >= 1, 'restore recorded in the log');
      this.verifie((await S.q('instance')).sous_titre === `Recette ${this.nom}`, 'database restored as saved');
      await this.connecter(admin, 'admin');
      await this.aucunTexteTechnique(admin);
    });
  }
}

(async () => {
  const opts = lireArguments();
  const tous = [];
  for (const langue of opts.langs.split(',')) {
    for (const ecran of opts.viewports.split(',')) {
      console.log(`\n=== ${langue} · ${ecran}`);
      const p = new Passage(opts, langue, ecran);
      tous.push(...(await p.lancer()).map((r) => ({ passage: p.nom, ...r })));
    }
  }
  fs.writeFileSync(path.join(opts.out, 'results.json'), JSON.stringify(tous, null, 1));
  const echecs = tous.filter((r) => !r.ok);
  console.log(`\n${tous.length} checks, ${echecs.length} failed. Details: ${path.join(opts.out, 'results.json')}`);
  for (const e of echecs) console.log(`  ✗ [${e.passage}] ${e.etape}: ${e.texte}`);
  process.exit(echecs.length ? 1 : 0);
})();
