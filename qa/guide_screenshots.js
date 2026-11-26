#!/usr/bin/env node
// Screenshots of the role guides (docs/guides/, docs/<language>/guides/) and of the installation guide, made by a script: run
// it again after any change of the screens and the guides stay up to date. The installation guide exists in English and
// French only: its screens (login, health, setup-*) are made for these two languages, the others get only the screens of the role guides.
//
//   node qa/guide_screenshots.js [--out docs/screenshots] [--langs en,fr,es,de,it,nl,pt] [--port 8261] [--python python3]
//                                [--only name,name] [--keep] [--data-dir FOLDER]
//
// What it does:
//   1. creates throwaway databases in a temporary folder (never local-data/): one Exemplia demo PER LANGUAGE
//      (`load_demo --language <code>`, 2026 open: entry, validation, reminders; the texts of the demo are in the language of
//      the screenshots) on --port, and an empty installation on --port + 1 (setup wizard). A second server on --port + 2
//      serves the same demo with the guided tour switched on, for the screenshot `guided-tour` only;
//   2. seeds what the demo does not have: evidence files of a "Restricted" KPI in a closed year and a retention period
//      (page Evidence to delete); one backup and the data check; an installation in use rather than a fresh demo
//      (demo accounts with another password, email server, email alerts, copy outside the server, automatic updates,
//      all with example values: nothing is sent, no service is joined); company sign-in, switched on only for its two
//      screens, at the end;
//   3. for each language, signs in with the demo accounts and takes each screen at a fixed size (1,280 x 720 on a
//      computer, 390 x 844 on a phone), deviceScaleFactor 2, then compresses the PNG (Pillow, palette) under 300 KB;
//   4. writes docs/screenshots/<lang>/<name>.png. Fixed names: the guides and docs/installation*.md cite them.
// No real data: the demo is fictitious. Requirements: Node.js with `playwright` and Chromium (see
// qa/browser_journeys/README.md), and Python with the project requirements plus Pillow (requirements-dev.txt).
// Exit code 1 if a screenshot is missing or heavier than 300 KB.
'use strict';
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawn, execFileSync } = require('child_process');
const { chromium, config, signIn } = require('./browser_journeys/lib');

const ROOT = path.resolve(__dirname, '..');
const DESKTOP = { width: 1280, height: 720 };
const PHONE = { width: 390, height: 844 };
const MAX_BYTES = 300 * 1024;
const INSTALL_LANGS = ['en', 'fr'];  // languages of docs/installation*.md: the only ones that cite the `installOnly` screens
const wanted = (s, lang) => !s.installOnly || INSTALL_LANGS.includes(lang);
const SETUP_PASSWORD = 'Demo-guide-2026!';
const SETUP_EMAIL = 'alex.admin@exemple.test';
// password of the demo accounts once seeded: not the public one of the demo, so that Health shows no "Demo data" line
const SHOTS_PASSWORD = 'Guide-screens-2026!';

// {name, role (null = visitor), url, size, act(page)}: `blank` = the empty installation
const SHOTS = [
  { name: 'login', installOnly: true, role: null, url: '/connexion/' },
  { name: 'entry-assigned', role: 'contributeur', url: '/pour-moi/' },
  { name: 'entry-panel', role: 'contributeur', url: '/pour-moi/', act: openCell('GEN-IDENT-TYPE|1') },
  { name: 'entry-phone', role: 'contributeur', url: '/pour-moi/', size: PHONE },
  { name: 'entry-organisation', role: 'validateur', url: '/saisie/' },
  { name: 'consistency', role: 'contributeur', url: '/coherence/' },
  { name: 'consistency-audit', role: 'auditeur', url: '/coherence/' },
  { name: 'audit-entry', role: 'auditeur', url: '/saisie/' },
  { name: 'audit-history', role: 'auditeur', url: '/historique/' },
  { name: 'audit-sign-ins', role: 'auditeur', url: '/historique/connexions/' },
  { name: 'closing-certificate', role: 'auditeur', url: '/historique/', act: openCertificate },
  { name: 'export-audit-file', role: 'admin', url: '/import-export/exporter/?nouveau=1', act: chooseAuditFile, keepScroll: true },
  { name: 'guided-tour', role: 'admin', url: '/', tour: true },
  { name: 'dashboard', role: 'admin', url: '/tableau-de-bord/' },
  { name: 'consolidation', role: 'lecteur', url: '/tableau-de-bord/consolidation/' },
  { name: 'visualisation', role: 'lecteur', url: '/visualisation/' },
  { name: 'visualisation-phone', role: 'lecteur', url: '/visualisation/', size: PHONE },
  { name: 'reminders', role: 'admin', url: '/tableau-de-bord/relances/' },
  { name: 'admin-overview', role: 'admin', url: '/administration/' },
  { name: 'admin-accounts', role: 'admin', url: '/administration/comptes/' },
  { name: 'admin-assignments', role: 'admin', url: '/administration/attributions/' },
  { name: 'admin-campaigns', role: 'admin', url: '/administration/campagnes/' },
  { name: 'admin-health', role: 'admin', url: '/administration/parametres/sante/' },
  { name: 'admin-evidence', role: 'admin', url: '/administration/preuves/' },
  { name: 'admin-languages', role: 'admin', url: '/administration/parametres/langues/' },
  { name: 'admin-assistants', role: 'admin', url: '/administration/parametres/assistants/' },
  { name: 'admin-ai', role: 'admin', url: '/administration/parametres/ia/' },
  { name: 'hosting', role: 'admin', url: '/administration/parametres/hebergement/' },
  { name: 'hosting-emails', role: 'admin', url: '/administration/parametres/hebergement/', act: scrollTo('#emails'), keepScroll: true },
  { name: 'hosting-auto-updates', role: 'admin', url: '/administration/parametres/hebergement/', act: scrollTo('#mise-a-jour-auto'), keepScroll: true },
  { name: 'hosting-external-copy', role: 'admin', url: '/administration/parametres/hebergement/copie-externe/' },
  { name: 'admin-health-alerts', role: 'admin', url: '/administration/parametres/sante/', act: scrollTo('#alertes'), keepScroll: true },
  // company sign-in switched on (COMPANY_SEED) just before these two: with it, only the space managers keep their password
  { name: 'admin-company-sign-in', role: 'admin', url: '/administration/parametres/connexion-entreprise/', company: true },
  { name: 'login-company', role: null, url: '/connexion/', company: true },
  { name: 'health', installOnly: true, role: null, url: '/sante/', clip: { x: 0, y: 0, width: 900, height: 110 } },
  { name: 'setup-admin-account', installOnly: true, role: null, url: '/mise-en-place/', blank: 'before' },
  { name: 'setup-frameworks', installOnly: true, role: 'setup', url: '/mise-en-place/5/', blank: 'after' },
  { name: 'setup-campaign', installOnly: true, role: 'setup', url: '/mise-en-place/8/', blank: 'last' },
];

async function openCertificate(page) {
  await page.locator('a[href*="/certificat-de-cloture/"]').first().click();
  await page.waitForLoadState('networkidle');
}

async function chooseAuditFile(page) {
  await page.locator('input[name=presentation][value=audit]').first().check({ force: true });
  await page.locator('#l-presentation').scrollIntoViewIfNeeded();
  await page.evaluate(() => window.scrollBy(0, 60));
  await page.waitForTimeout(300);
}

function openCell(cle) {
  return async (page) => {
    await page.locator(`tr.ligne[data-cle="${cle}"]`).first().click();
    await page.waitForSelector('#panneau-contenu form', { timeout: 8000 });
    await page.waitForTimeout(600);
  };
}

// Seed run through `manage.py shell`: evidence files on a Restricted KPI of a closed year, retention period of 1 month.
const SEED = `
from django.core.files.base import ContentFile
from collecte.models import Preuve, Reponse
from parametres.models import Instance
from referentiel.models import KPI
kpi = KPI.objects.filter(code="SOC-REMU-H-FEMMES").first()
if kpi:
    KPI.objects.filter(pk=kpi.pk).update(confidentialite=KPI.Confidentialite.RESTREINT)
    rows = Reponse.objects.filter(kpi=kpi, statut="valide", periode__fin__lt="2026-01-01")[:3]
    for r in rows:
        nom = "justificatif-%s.pdf" % r.pk
        Preuve.objects.create(reponse=r, nom_fichier=nom, depose_par=r.saisi_par,
                              fichier=ContentFile(b"%PDF-1.4 demo", name=nom))
i = Instance.courante()
i.preuves_sensibles_mois = 1
i.save()

# An installation in use, not a fresh demo: no "Demo data" line (the demo accounts get another password), the email
# server, the alerts, the copy outside the server and the automatic updates set with example values. Nothing is sent and
# nothing is joined: the settings are written as the tool writes them, the copy and the server task are only noted done.
import datetime, os
from django.contrib.auth.hashers import make_password
from django.utils import timezone
from collecte.management.commands._exemplia import COMPTES
from espaces.models import Compte, EtatCopie
from referentiel.models import Utilisateur
from parametres import alertes, copie_externe, envoi_emails, mise_a_jour_auto
empreinte = make_password("${SHOTS_PASSWORD}")
noms = [c[0] for c in COMPTES]
Compte.objects.filter(username__in=noms).update(password=empreinte)
Utilisateur.objects.filter(username__in=noms).update(password=empreinte)
admin = Compte.objects.get(username="admin")
assert admin.gestionnaire, "the demo administrator must be a space manager"
envoi_emails.enregistrer(admin, "smtp.example.com", 587, "starttls", "probant@example.com", "probant@example.com",
                         mot_de_passe="example-password")
alertes.enregistrer(admin, True, True, "it-team@example.com")
copie_externe.enregistrer(admin, "s3", {"adresse": "https://backup.example.com", "region": "eu-west-1",
                                        "compartiment": "probant-backups", "style": "auto", "identifiant": "probant-copy",
                                        "chemin": "probant", "conserver": 0}, secret="example-secret-key")
d = copie_externe.ligne()
maintenant = timezone.now()
copiees = {rel: {"taille": ch.stat().st_size, "sha256": copie_externe.sha256_fichier(ch), "le": maintenant.isoformat()}
           for rel, ch in copie_externe.archives_locales()}
EtatCopie.objects.update_or_create(pk=1, defaults={"destination": copie_externe.empreinte_destination(d), "copiees": copiees,
                                                   "reussie_le": maintenant, "derniere_copie_le": maintenant})
mise_a_jour_auto.ecrire_choix("automatic", 3)
nuit = timezone.localtime().replace(hour=3, minute=2, second=0, microsecond=0)  # the last night run of the server task
nuit = nuit if nuit <= timezone.localtime() else nuit - datetime.timedelta(days=1)
verifie = nuit.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
resultat = mise_a_jour_auto.dossier() / "result"
resultat.write_text("format=1\\ntask=systemd\\ntime=03:00\\nchecked=%s\\nstate=up_to_date\\ninstalled=%s\\n"
                    % (verifie, open("VERSION").read().strip()), encoding="utf-8")
os.chmod(resultat, 0o600)
`;

// Company sign-in switched on with example values (no provider is joined: the screen and the button only read the setting)
const COMPANY_SEED = `
from connexion_entreprise.models import ReglageEntreprise
from connexion_entreprise.secret import chiffrer
from django.utils import timezone
ReglageEntreprise.objects.update_or_create(pk=1, defaults={
    "actif": True, "emetteur": "https://login.example.com/realms/example", "client_id": "probant",
    "secret_chiffre": chiffrer("example-client-secret"), "secret_le": timezone.now(), "libelle_bouton": "",
    "modifie_le": timezone.now()})
`;

function scrollTo(selector) {
  return async (page) => {
    // the block at the top of the screen, 16 px below the edge (no anchor offset of the page in between)
    await page.locator(selector).first().evaluate((el) => window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY - 16));
    await page.waitForTimeout(300);
  };
}

function sh(python, args, env) {
  execFileSync(python, args, { cwd: ROOT, env: { ...process.env, ...env }, stdio: ['ignore', 'pipe', 'pipe'] });
}

function serve(python, env, port, log) {
  const child = spawn(python, ['manage.py', 'runserver', String(port), '--noreload'], {
    cwd: ROOT, env: { ...process.env, ...env }, stdio: ['ignore', fs.openSync(log, 'a'), fs.openSync(log, 'a')],
  });
  return child;
}

async function waitFor(url) {
  for (let i = 0; i < 60; i++) {
    try { if ((await fetch(url)).status < 500) return; } catch (e) { /* not ready */ }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error('server not reachable: ' + url);
}

async function setLanguage(page, lang) {
  const menu = page.locator('details:has(form.liste-langues) > summary');
  if (await menu.count()) await menu.first().click().catch(() => {});
  const button = page.locator(`button[name=langue][value=${lang}]`).first();
  await button.click();
  await page.waitForLoadState('networkidle');
}

function compress(raw, final) {
  const code = [
    'import sys', 'from PIL import Image',
    'im = Image.open(sys.argv[1]).convert("RGB")',
    'for colors in (160, 96, 64, 32):',
    '    q = im.quantize(colors=colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)',
    '    q.save(sys.argv[2], optimize=True)',
    '    import os',
    '    if os.path.getsize(sys.argv[2]) <= 280 * 1024: break',
  ].join('\n');
  execFileSync(PYTHON, ['-I', '-c', code, raw, final]);
}

let PYTHON = 'python3';

async function main() {
  const argv = process.argv.slice(2);
  if (!argv.includes('--out')) argv.push('--out', path.join(ROOT, 'docs', 'screenshots'));
  const cfg = config(argv);
  const o = cfg.opts;
  PYTHON = o.python || process.env.PYTHON || 'python3';
  const out = path.resolve(o.out === undefined || o.out === true ? path.join(ROOT, 'docs', 'screenshots') : o.out);
  const langs = String(o.langs || 'en,fr,es,de,it,nl,pt').split(',');
  const port = Number(o.port || 8261);
  const only = o.only ? String(o.only).split(',') : null;
  const tmp = o['data-dir'] ? path.resolve(o['data-dir']) : fs.mkdtempSync(path.join(os.tmpdir(), 'guide_screenshots_'));
  const raw = path.join(tmp, 'raw');
  fs.mkdirSync(raw, { recursive: true });
  // DANS_DOCKER: the demo runs as in the Docker image, where the automatic updates exist (block of Settings › Hosting)
  const demoEnv = (lang) => ({ DATA_DIR: path.join(tmp, 'demo_' + lang), SQLITE_FILE: 'demo.sqlite3', DJANGO_DEBUG: '0', GUIDED_TOUR: 'off', DANS_DOCKER: '1' });
  const blank = { DATA_DIR: path.join(tmp, 'blank'), SQLITE_FILE: 'blank.sqlite3', DJANGO_DEBUG: '0', GUIDED_TOUR: 'off' };
  fs.mkdirSync(blank.DATA_DIR, { recursive: true });
  for (const k of ['DATABASE_URL', 'POSTGRESQL_ADDON_URI', 'SMTP_HOST', 'SMTP_HOTE']) delete process.env[k];
  console.log('Preparing the demo databases in ' + tmp);
  sh(PYTHON, ['manage.py', 'migrate', '--noinput'], blank);
  const servers = [serve(PYTHON, blank, port + 1, path.join(tmp, 'blank.log'))];
  const baseBlank = `http://127.0.0.1:${port + 1}`;
  const problems = [];
  const browser = await chromium.launch();
  try {
    await waitFor(baseBlank + '/mise-en-place/');
    const shots = SHOTS.filter((s) => !only || only.includes(s.name));
    let base = null;  // the demo server of the language being shot (set below)
    const take = async (page, s, lang) => {
      if (!s.tour) await page.goto((s.blank ? baseBlank : base) + s.url, { waitUntil: 'networkidle' });
      if (s.act) await s.act(page);
      if (!s.keepScroll) await page.evaluate(() => window.scrollTo(0, 0));
      const file = path.join(raw, `${lang}_${s.name}.png`);
      await page.screenshot(s.clip ? { path: file, clip: s.clip } : { path: file });
      const final = path.join(out, lang, `${s.name}.png`);
      fs.mkdirSync(path.dirname(final), { recursive: true });
      compress(file, final);
      const size = fs.statSync(final).size;
      console.log(`  ${lang}/${s.name}.png ${Math.round(size / 1024)} KB`);
      if (size > MAX_BYTES) problems.push(`${lang}/${s.name}.png is ${size} bytes`);
    };
    const newPage = async (size, base_) => {
      const ctx = await browser.newContext({ viewport: size || DESKTOP, deviceScaleFactor: 2, ...(size === PHONE ? { isMobile: true, hasTouch: true } : {}) });
      const page = await ctx.newPage();
      page.setDefaultTimeout(8000);
      return { ctx, page };
    };
    // 1. setup, first step: before the administrator account exists (visitor)
    for (const lang of langs) for (const s of shots.filter((x) => x.blank === 'before' && wanted(x, lang))) {
      const { ctx, page } = await newPage();
      await page.goto(baseBlank + '/mise-en-place/', { waitUntil: 'networkidle' });
      await setLanguage(page, lang);
      await take(page, s, lang);
      await ctx.close();
    }
    // 2. the administrator account of the empty installation (through the wizard), then the later steps
    const { ctx: cs, page: ps } = await newPage();
    await ps.goto(baseBlank + '/mise-en-place/', { waitUntil: 'networkidle' });
    await ps.fill('[name=prenom]', 'Alex');
    await ps.fill('[name=nom]', 'Admin');
    await ps.fill('[name=email]', SETUP_EMAIL);
    await ps.fill('[name=mot_de_passe]', SETUP_PASSWORD);
    await ps.fill('[name=confirmation]', SETUP_PASSWORD);
    await ps.click('button[name=action]');
    await ps.waitForLoadState('networkidle');
    for (const lang of langs) {
      await setLanguage(ps, lang);
      for (const s of shots.filter((x) => x.blank === 'after' && wanted(x, lang))) await take(ps, s, lang);
    }
    // a framework from the library, so that the last step has a period to suggest
    await ps.goto(baseBlank + '/administration/referentiels/modeles/VS_BASE/?depuis=mise_en_place&version=0', { waitUntil: 'networkidle' });
    await ps.locator('main form button[type=submit]').last().click();
    await ps.waitForLoadState('networkidle');
    await ps.locator('main form button[type=submit]').last().click();
    await ps.waitForLoadState('networkidle');
    for (const lang of langs) {
      await setLanguage(ps, lang);
      for (const s of shots.filter((x) => x.blank === 'last' && wanted(x, lang))) await take(ps, s, lang);
    }
    await cs.close();
    // 3. the demo: one database per language, loaded in that language (texts of the demo included)
    for (const lang of langs) {
      // the company sign-in screens last: company sign-in stays off for the others
      const lshots = shots.filter((x) => !x.blank && wanted(x, lang)).sort((a, b) => Number(!!a.company) - Number(!!b.company));
      if (!lshots.length) continue;
      const demo = demoEnv(lang);
      fs.mkdirSync(demo.DATA_DIR, { recursive: true });
      sh(PYTHON, ['manage.py', 'migrate', '--noinput'], demo);
      sh(PYTHON, ['manage.py', 'load_demo', '--language', lang], demo);
      sh(PYTHON, ['manage.py', 'backup'], demo);  // one backup, copied outside the server by the seed (no "No backup yet")
      sh(PYTHON, ['manage.py', 'shell', '-c', SEED], demo);
      sh(PYTHON, ['manage.py', 'check_data'], demo);  // the data check of the night, done (no "Data check: not done yet")
      cfg.password = SHOTS_PASSWORD;
      const demoServers = [serve(PYTHON, demo, port, path.join(tmp, `demo_${lang}.log`))];
      base = `http://127.0.0.1:${port}`;
      const baseTour = `http://127.0.0.1:${port + 2}`;
      if (lshots.some((x) => x.tour)) demoServers.push(serve(PYTHON, { ...demo, GUIDED_TOUR: 'on' }, port + 2, path.join(tmp, `demo_${lang}_tour.log`)));
      try {
        await waitFor(base + '/connexion/');
        if (demoServers.length > 1) await waitFor(baseTour + '/connexion/');
        let company = false;
        for (const s of lshots) {
          if (s.company && !company) { sh(PYTHON, ['manage.py', 'shell', '-c', COMPANY_SEED], demo); company = true; }
          if (s.role === null) {
            const { ctx, page } = await newPage();
            await page.goto(base + (s.url === '/sante/' ? '/sante/' : '/connexion/'), { waitUntil: 'networkidle' });
            if (s.url !== '/sante/') await setLanguage(page, lang);
            await take(page, s, lang);
            await ctx.close();
            continue;
          }
          if (s.tour) {
            // the tour opens once, on the home page, when arriving from the sign-in page: choose the language there first
            const { ctx, page } = await newPage();
            await page.goto(baseTour + '/connexion/', { waitUntil: 'networkidle' });
            await setLanguage(page, lang);
            await page.fill('#id_username', s.role);
            await page.fill('#id_password', cfg.password);
            await page.click('button[type=submit]:not([name=langue])');
            await page.waitForLoadState('networkidle');
            await page.waitForSelector('#visite:not([hidden])', { timeout: 8000 }).catch(() => problems.push(`${lang}/${s.name}: no tour bubble`));
            await page.waitForTimeout(800);
            await take(page, s, lang);
            await ctx.close();
            continue;
          }
          const size = s.size || DESKTOP;
          const { ctx, page, log } = await signIn(browser, { ...cfg, base }, s.role,
            { viewport: size, deviceScaleFactor: 2, ...(size === PHONE ? { isMobile: true, hasTouch: true } : {}) });
          await setLanguage(page, lang);
          await take(page, s, lang);
          if (log.pageerrors.length) problems.push(`${lang}/${s.name}: ${log.pageerrors[0]}`);
          await ctx.close();
        }
      } finally {
        for (const sv of demoServers) sv.kill();
        await new Promise((r) => setTimeout(r, 1500));
      }
    }
  } finally {
    await browser.close();
    for (const sv of servers) sv.kill();
    if (!o.keep && !o['data-dir']) fs.rmSync(tmp, { recursive: true, force: true });
  }
  const names = (lang) => SHOTS.filter((s) => wanted(s, lang) && (!only || only.includes(s.name))).map((s) => s.name);
  for (const lang of langs) for (const n of names(lang)) if (!fs.existsSync(path.join(out, lang, `${n}.png`))) problems.push(`missing ${lang}/${n}.png`);
  if (problems.length) { console.log('PROBLEMS:\n  ' + problems.join('\n  ')); return 1; }
  console.log(`Done: ${langs.map((l) => `${names(l).length} (${l})`).join(', ')} screenshots in ${out}`);
  return 0;
}

if (require.main === module) {
  main().then((c) => process.exit(c || 0)).catch((e) => { console.error('FAILED: ' + ((e && e.stack) || e)); process.exit(2); });
}
