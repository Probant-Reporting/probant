"""Simulated campaign with many simultaneous users (load and reliability test).

    python3 qa/load_test.py prepare --plan plan.json [--contributors 50 --validators 5 --admins 3]
    python3 qa/load_test.py run     --plan plan.json --url http://127.0.0.1:8020 --log run.jsonl [--rounds 2]
    python3 qa/load_test.py check   --plan plan.json --log run.jsonl [--server-log gunicorn.log] [--json result.json]

Run against a DEMO database only (``load_demo``: Exemplia, open 2026 campaign; fictitious data), served as in production (gunicorn, DJANGO_DEBUG=0):
``prepare`` and ``check`` open the database given by the environment (DATA_DIR / SQLITE_FILE or DATABASE_URL), like
manage.py. Capacity figures: docs/installation.md, "Capacity".

- prepare: creates the test accounts (``charge-c01``… contributors, ``charge-v1``… validators, ``charge-a1``…
  admins, password ``Charge-test-2026``), assigns each contributor its own cells of the open campaign plus cells shared
  by two contributors (to provoke version conflicts), and writes the plan (JSON).
- run: every account logs in at the same time and works: Data entry, For me, panels, drafts, validation, evidence,
  imports, exports (Power BI Excel, CSV), dashboard, visualisation; admins close / reopen data entry, recalculate,
  back up. Two people save the SAME cell at the same moment (synchronised). Every request is written to the log (JSONL).
- check: response times per page (median, 95th percentile, max), HTTP errors, "database is locked" in the server
  log, lost entries (every entry acknowledged by the server must be in the database and in the log), consistent totals
  (full recalculation = stored values). Exit code 0 if nothing is lost or inconsistent and there is no 5xx.
"""
# Messages en anglais (outil pour l'IT et la recette) ; commentaires et identifiants en français.
import argparse
import io
import json
import os
import random
import re
import statistics
import sys
import threading
import time
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
MOT_DE_PASSE = "Charge-test-2026"
PREFIXE = "charge-"
PDF = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj "
       b"3 0 obj<</Type/Page/MediaBox[0 0 200 200]/Parent 2 0 R>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n")


def django_pret():
    sys.path.insert(0, str(RACINE))
    os.chdir(RACINE)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()


# ---------------------------------------------------------------- prepare
def preparer(args):
    django_pret()
    from django.db import transaction

    from collecte import saisie as S
    from collecte.models import Campagne, ReglageExport
    from referentiel.models import Attribution, Organisation, Utilisateur

    # comptes au mot de passe connu : jamais dans une vraie installation (démo : adresses en @exemple.test)
    reels = Utilisateur.objects.exclude(email__iendswith="@exemple.test").count()
    if reels and not args.force:
        sys.exit(f"{reels} account(s) with a real-looking e-mail address: this is not a demo database. Refused "
                 "(the test creates accounts with a known password). --force to go on anyway.")
    campagne = Campagne.objects.filter(statut=Campagne.Statut.OUVERTE).select_related("periode").order_by("-periode__debut").first()
    if campagne is None:
        sys.exit("No open campaign: load the demo first (manage.py load_demo).")
    rangs = None
    orgs = [o for o in Organisation.objects.filter(actif=True).select_related("niveau")]
    cases = []
    for k in S.kpis_collectes(campagne.referentiel).select_related("type_saisie", "type_reponse", "unite").order_by("code"):
        if not k.est_numerique or k.est_herite or not S.dans_la_campagne(campagne, k):
            continue
        for o in orgs:
            if o.niveau_id == k.granularite_id and not S.est_calculee(k, o, None, campagne, rangs):
                cases.append((k, o))
    h = random.Random(2026)
    h.shuffle(cases)
    nc, nv, na = args.contributors, args.validators, args.admins
    par_personne, partagees = args.cells, nc // 2
    besoin = nc * par_personne + partagees
    if len(cases) < besoin:
        sys.exit(f"Only {len(cases)} cells to enter, {besoin} needed: fewer contributors or cells.")

    def compte(ident, role, prenom):
        u, _ = Utilisateur.objects.update_or_create(username=ident, defaults={
            "email": f"{ident}@exemple.test", "first_name": prenom, "last_name": "(load test)", "role": role,
            "is_staff": role == Utilisateur.Role.ADMIN, "is_superuser": role == Utilisateur.Role.ADMIN, "is_active": True,
            "doit_changer_mdp": False})
        u.set_password(MOT_DE_PASSE)
        u.save()
        return u

    plan = {"campagne": campagne.pk, "periode": campagne.periode_id, "mot_de_passe": MOT_DE_PASSE, "comptes": []}
    with transaction.atomic():
        Attribution.objects.filter(utilisateur__username__startswith=PREFIXE).delete()
        contributeurs = [compte(f"{PREFIXE}c{i:02d}", Utilisateur.Role.CONTRIBUTEUR, f"Contributor {i}") for i in range(1, nc + 1)]
        validateurs = [compte(f"{PREFIXE}v{i}", Utilisateur.Role.VALIDATEUR, f"Validator {i}") for i in range(1, nv + 1)]
        admins = [compte(f"{PREFIXE}a{i}", Utilisateur.Role.ADMIN, f"Admin {i}") for i in range(1, na + 1)]
        liens, propres = [], {}
        for n, u in enumerate(contributeurs):
            propres[u.pk] = cases[n * par_personne:(n + 1) * par_personne]
        communes = cases[nc * par_personne:besoin]
        for n, u in enumerate(contributeurs):
            mes = list(propres[u.pk])
            paire = n % partagees  # case partagée par c(n) et c(n + partagees)
            mes_communes = [communes[paire]] if n < 2 * partagees else []
            for k, o in mes + mes_communes:
                liens.append(Attribution(kpi=k, organisation=o, utilisateur=u, role=Attribution.Role.CONTRIBUTEUR))
            plan["comptes"].append({"username": u.username, "pk": u.pk, "role": "contributeur", "n": n + 1,
                                    "cases": [[k.code, o.pk, k.est_pourcentage] for k, o in mes],
                                    "communes": [[k.code, o.pk, k.est_pourcentage, paire] for k, o in mes_communes]})
        groupe = next(o for o in orgs if o.parent_id is None)
        tranche = max(1, -(-nc // max(1, nv)))
        for i, v in enumerate(validateurs):
            suivis = contributeurs[i * tranche:(i + 1) * tranche]
            codes = {k.code for u in suivis for k, _ in propres[u.pk]}
            for code in codes:
                liens.append(Attribution(kpi_id=code, organisation=groupe, utilisateur=v, role=Attribution.Role.VALIDATEUR))
            plan["comptes"].append({"username": v.username, "pk": v.pk, "role": "validateur", "n": i + 1,
                                    "cases": [[k.code, o.pk, k.est_pourcentage] for u in suivis for k, o in propres[u.pk]]})
        Attribution.objects.bulk_create(liens, ignore_conflicts=True)
        for i, a in enumerate(admins):
            plan["comptes"].append({"username": a.username, "pk": a.pk, "role": "admin", "n": i + 1})
    plan["orgs"] = {str(o.pk): o.nom for o in orgs}
    plan["autres_cases"] = [[k.code, o.pk, k.est_pourcentage] for k, o in cases[besoin:]]  # attribuées à personne ici
    plan["exports"] = {nom: pk for pk, nom in ReglageExport.objects.filter(partage=True).values_list("pk", "nom")}
    plan["lecteurs"] = [u for u in ("lecteur", "auditeur") if Utilisateur.objects.filter(username=u, is_active=True).exists()]
    Path(args.plan).write_text(json.dumps(plan, indent=1), encoding="utf-8")
    print(f"Plan written: {args.plan} — campaign {campagne}, {nc} contributors ({par_personne} own cells each, "
          f"{partagees} cells shared by two), {nv} validators, {na} admins; {len(cases)} cells available.")


# ---------------------------------------------------------------- run
class Journal:
    def __init__(self, chemin):
        self.f = open(chemin, "w", encoding="utf-8")
        self.verrou = threading.Lock()
        self.t0 = time.time()

    def ecrire(self, **ligne):
        with self.verrou:
            self.f.write(json.dumps(ligne, ensure_ascii=False) + "\n")
            self.f.flush()


class Personne:
    """Une personne connectée (session requests) qui journalise chacune de ses requêtes."""

    def __init__(self, url, username, mot_de_passe, journal, timeout):
        import requests

        self.url, self.username, self.mdp, self.journal, self.timeout = url.rstrip("/"), username, mot_de_passe, journal, timeout
        self.s = requests.Session()
        self.s.headers["User-Agent"] = "load-test"

    def requete(self, page, methode, chemin, fetch=False, **kw):
        import requests

        entetes = kw.pop("headers", {})
        if fetch:
            entetes["X-Requested-With"] = "fetch"
        if methode == "POST":
            entetes["X-CSRFToken"] = self.s.cookies.get("csrftoken", "")
            entetes["Referer"] = self.url + "/"
        debut = time.time()
        statut, taille, erreur, rep = 0, 0, "", None
        try:
            rep = self.s.request(methode, self.url + chemin, headers=entetes, timeout=self.timeout, allow_redirects=kw.pop("redirects", True), **kw)
            statut, taille = rep.status_code, len(rep.content)
        except requests.RequestException as e:
            erreur = type(e).__name__ + ": " + str(e)[:200]
        fin = time.time()
        self.journal.ecrire(t=round(debut - self.journal.t0, 3), d=round(fin - debut, 4), u=self.username, page=page,
                            m=methode, path=chemin, status=statut, size=taille, err=erreur)
        return rep, debut, fin

    def connexion(self):
        self.requete("login_form", "GET", "/connexion/")
        rep, *_ = self.requete("login", "POST", "/connexion/", data={
            "username": self.username, "password": self.mdp, "csrfmiddlewaretoken": self.s.cookies.get("csrftoken", "")},
            redirects=False)
        return rep is not None and rep.status_code == 302


def _html(rep):
    """Texte de la page ; en mode « fetch », le panneau arrive en JSON ({"html": ...})."""
    if rep is None:
        return ""
    if rep.headers.get("content-type", "").startswith("application/json"):
        try:
            return rep.json().get("html", "") or rep.text
        except ValueError:
            return rep.text
    return rep.text


def _version(html):
    m = re.search(r'name="version" value="([^"]*)"', html or "")
    return m.group(1) if m else None


def _resultat_panneau(rep):
    """Issue d'un envoi depuis le panneau : « ok », « conflit », « refus » (motif métier), « 403 », « http » ou
    « reseau »."""
    if rep is None:
        return "reseau", ""
    if rep.status_code == 403:
        return "403", rep.text[:200]
    if rep.status_code != 200:
        return "http", str(rep.status_code)
    html = _html(rep)
    if "question-fermeture-conflit" in html:
        return "conflit", ""
    if "data-non-enregistre" in html:
        m = re.search(r'class="[^"]*erreur[^"]*"[^>]*>(.*?)<', html, re.S)
        return "refus", (m.group(1).strip()[:200] if m else "")
    return "ok", ""


class Simulation:
    def __init__(self, args, plan):
        self.args, self.plan = args, plan
        self.journal = Journal(args.log)
        self.c = plan["campagne"]
        self.mdp = plan["mot_de_passe"]
        self.arret = threading.Event()
        self.barrieres = {}
        self.verrou = threading.Lock()
        self.fin_contributeurs = threading.Event()

    def personne(self, username, mdp=None):
        return Personne(self.args.url, username, mdp or self.mdp, self.journal, self.args.timeout)

    def pause(self, h, facteur=1.0):
        time.sleep(h.uniform(0.3, 1.0) * self.args.think * facteur)

    def saisie(self, p, page, code, org, valeur, action="enregistrer", version=None, commentaire="load test"):
        chemin = f"/saisie/{self.c}/{code}/{org}/"
        rep, debut, fin = p.requete(page, "POST", chemin, fetch=True, data={
            "action": action, "valeur": valeur, "commentaire": commentaire, "version": version or "",
            "csrfmiddlewaretoken": p.s.cookies.get("csrftoken", "")})
        issue, detail = _resultat_panneau(rep)
        enregistre = issue == "ok"
        self.journal.ecrire(kind="save", step=page, u=p.username, kpi=code, org=org, value=valeur, action=action, outcome=issue,
                            saved=enregistre, detail=detail, version=version or "", t0=round(debut - self.journal.t0, 3), t1=round(fin - self.journal.t0, 3))
        return issue, (_version(_html(rep)) if rep is not None and rep.status_code == 200 else None)

    def ouvrir(self, p, code, org):
        rep, *_ = p.requete("panel_open", "GET", f"/saisie/{self.c}/{code}/{org}/", fetch=True)
        return _version(_html(rep)) if rep is not None and rep.status_code == 200 else None

    @staticmethod
    def valeur(compte, seq, pourcent):
        if pourcent:
            return str((compte["n"] * 7 + seq) % 101)
        return str(compte["n"] * 10000 + seq)

    # -- contributeur
    def contributeur(self, compte):
        h = random.Random(compte["n"])
        p = self.personne(compte["username"])
        time.sleep(h.uniform(0, self.args.ramp))
        if not p.connexion():
            self.journal.ecrire(kind="login_failed", u=compte["username"])
            return
        p.requete("saisie", "GET", f"/saisie/?campagne={self.c}")
        p.requete("pour_moi", "GET", "/pour-moi/")
        seq = 0
        n = compte["n"]
        for tour in range(self.args.rounds):
            cases = list(compte["cases"])
            h.shuffle(cases)
            for i, (code, org, pourcent) in enumerate(cases):
                version = self.ouvrir(p, code, org)
                self.pause(h)
                seq += 1
                action = "valider" if (tour == self.args.rounds - 1 and i % 2 == 0) else "enregistrer"
                issue, version = self.saisie(p, "panel_save" if action == "enregistrer" else "panel_validate", code, org,
                                             self.valeur(compte, seq, pourcent), action, version)
                if i < 2 and tour == 0:  # deux preuves par personne
                    rep, *_ = p.requete("evidence_upload", "POST", f"/saisie/{self.c}/{code}/{org}/", fetch=True,
                                        data={"action": "preuve", "csrfmiddlewaretoken": p.s.cookies.get("csrftoken", "")},
                                        files={"fichier": (f"preuve-{n}-{i}.pdf", PDF, "application/pdf")})
                    self.journal.ecrire(kind="evidence", u=p.username, kpi=code, org=org, outcome=_resultat_panneau(rep)[0])
                self.pause(h)
            # cases partagées : les deux personnes ouvrent la case puis enregistrent au même moment
            for code, org, pourcent, paire in compte.get("communes", []):
                version = self.ouvrir(p, code, org)
                seq += 1
                with self.verrou:
                    barriere = self.barrieres.setdefault((tour, paire), threading.Barrier(2, timeout=120))
                try:
                    barriere.wait()
                except threading.BrokenBarrierError:
                    pass
                self.saisie(p, "panel_save_same_cell", code, org, self.valeur(compte, seq, pourcent), "enregistrer", version)
            if n % 10 == 3:
                p.requete("dashboard", "GET", f"/tableau-de-bord/?campagne={self.c}")
            if n % 10 == 4:
                p.requete("visualisation", "GET", "/visualisation/")
            p.requete("saisie", "GET", f"/saisie/?campagne={self.c}")
        if n <= self.args.importers:
            self.importer(p, compte, h, seq + 1000)
        if self.args.importers < n <= self.args.importers + self.args.exporters:
            self.exporter(p, "Power BI – toutes les années", "export_powerbi_xlsx")
            self.exporter(p, "CSV pour Power BI", "export_csv")

    def importer(self, p, compte, h, seq, cases=None, page="import"):
        """Fichier de valeurs (Excel) pour les cases de la personne (ou ``cases``) : aperçu puis confirmation."""
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.title = "Valeurs"
        lignes = []
        for i, (code, org, pourcent) in enumerate(compte["cases"] if cases is None else cases):
            v = self.valeur(compte, seq + i, pourcent)
            lignes.append((code, org, v))
        noms = self.plan["orgs"]
        ws.append(["ID KPI", "Organisation", "Valeur", "Commentaire"])
        for code, org, v in lignes:
            ws.append([code, noms.get(str(org), str(org)), float(v), "load test import"])
        flux = io.BytesIO()
        wb.save(flux)
        p.requete(f"{page}_page", "GET", "/import-export/importer/")
        jeton = p.s.cookies.get("csrftoken", "")
        rep, *_ = p.requete(f"{page}_preview", "POST", "/import-export/importer/", data={
            "action": "verifier", "campagne": str(self.c), "csrfmiddlewaretoken": jeton},
            files={"fichier": (f"import-{compte['n']}.xlsx", flux.getvalue(),
                               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
        self.pause(h)
        rep, debut, fin = p.requete(f"{page}_confirm", "POST", "/import-export/importer/", data={
            "action": "confirmer", "csrfmiddlewaretoken": jeton})
        ok = rep is not None and rep.status_code == 200 and "resultat-import" in rep.text
        m = re.search(r"(\d+)\s*(?:valeur|value)", rep.text if rep is not None else "")
        self.journal.ecrire(kind="import", u=p.username, outcome="ok" if ok else "error", lines=len(lignes),
                            detail=m.group(0) if m else "", t0=round(debut - self.journal.t0, 3), t1=round(fin - self.journal.t0, 3),
                            values=[[c, o, v] for c, o, v in lignes])

    def exporter(self, p, nom, page):
        pk = self.plan["exports"].get(nom)
        if pk:
            p.requete(page, "GET", f"/import-export/exporter/?modele={pk}&telecharger=1")

    # -- validateur
    def validateur(self, compte):
        h = random.Random(100 + compte["n"])
        p = self.personne(compte["username"])
        time.sleep(h.uniform(0, self.args.ramp))
        if not p.connexion():
            self.journal.ecrire(kind="login_failed", u=compte["username"])
            return
        cases = list(compte["cases"])
        while not self.fin_contributeurs.is_set():
            p.requete("pour_moi", "GET", "/pour-moi/")
            p.requete("saisie", "GET", f"/saisie/?campagne={self.c}")
            for code, org, _ in h.sample(cases, min(5, len(cases))):
                self.ouvrir(p, code, org)
                self.pause(h)
                if h.random() < 0.3:  # renvoie une case validée en brouillon (refusée si elle ne l'est pas)
                    rep, *_ = p.requete("panel_back_to_draft", "POST", f"/saisie/{self.c}/{code}/{org}/", fetch=True,
                                        data={"action": "brouillon", "csrfmiddlewaretoken": p.s.cookies.get("csrftoken", "")})
            p.requete("dashboard", "GET", f"/tableau-de-bord/?campagne={self.c}")
            self.pause(h, 3)

    # -- administrateurs
    def admin(self, compte):
        h = random.Random(200 + compte["n"])
        p = self.personne(compte["username"])
        time.sleep(h.uniform(0, self.args.ramp))
        if not p.connexion():
            self.journal.ecrire(kind="login_failed", u=compte["username"])
            return
        role = compte["n"] % 3
        fiche = f"/administration/campagnes/{self.c}/"
        if role == 0 and self.args.big_import:  # gros import de l'administrateur pendant que les autres saisissent
            time.sleep(20)
            self.importer(p, {"n": 99}, h, 0, self.plan["autres_cases"][:self.args.big_import], "big_import")
        while not self.fin_contributeurs.is_set():
            jeton = p.s.cookies.get("csrftoken", "")
            if role == 1:  # ferme la saisie aux contributeurs quelques secondes, puis la rouvre
                time.sleep(self.args.admin_period)
                p.requete("admin_campaign", "GET", fiche, fetch=True)
                rep, *_ = p.requete("admin_close_contributors", "POST", fiche, fetch=True, data={"action": "revue", "csrfmiddlewaretoken": jeton})
                self.journal.ecrire(kind="admin", u=p.username, action="revue", status=rep.status_code if rep is not None else 0)
                time.sleep(2)
                rep, *_ = p.requete("admin_reopen", "POST", fiche, fetch=True, data={"action": "rouvrir_contributeurs", "csrfmiddlewaretoken": jeton})
                self.journal.ecrire(kind="admin", u=p.username, action="rouvrir_contributeurs", status=rep.status_code if rep is not None else 0)
            elif role == 2:  # recalcul complet et sauvegarde
                time.sleep(self.args.admin_period)
                p.requete("admin_recalculate", "POST", fiche, fetch=True, data={"action": "recalculer", "csrfmiddlewaretoken": jeton})
                time.sleep(self.args.admin_period / 2)
                p.requete("admin_backup", "POST", "/administration/parametres/hebergement/",
                          data={"action": "sauvegarder", "csrfmiddlewaretoken": jeton}, redirects=False)
            else:  # suivi : tableau de bord, journal, administration, export
                p.requete("admin_home", "GET", "/administration/")
                p.requete("dashboard", "GET", f"/tableau-de-bord/?campagne={self.c}")
                p.requete("admin_log", "GET", "/administration/journal/")
                p.requete("visualisation", "GET", "/visualisation/")
                self.pause(h, 5)
                self.exporter(p, "Power BI – toutes les années", "export_powerbi_xlsx")
                self.pause(h, 5)

    def lecteur(self, username, n):
        h = random.Random(300 + n)
        p = self.personne(username, self.args.reader_password)
        time.sleep(h.uniform(0, self.args.ramp))
        if not p.connexion():
            self.journal.ecrire(kind="login_failed", u=username)
            return
        while not self.fin_contributeurs.is_set():
            p.requete("dashboard", "GET", f"/tableau-de-bord/?campagne={self.c}")
            p.requete("visualisation", "GET", "/visualisation/")
            self.pause(h, 4)

    def lancer(self):
        fils, contributeurs = [], []
        for compte in self.plan["comptes"]:
            cible = {"contributeur": self.contributeur, "validateur": self.validateur, "admin": self.admin}[compte["role"]]
            t = threading.Thread(target=cible, args=(compte,), name=compte["username"], daemon=True)
            (contributeurs if compte["role"] == "contributeur" else fils).append(t)
        for i, u in enumerate(self.plan.get("lecteurs", [])):
            fils.append(threading.Thread(target=self.lecteur, args=(u, i), name=u, daemon=True))
        debut = time.time()
        for t in contributeurs + fils:
            t.start()
        for t in contributeurs:
            t.join()
        self.fin_contributeurs.set()
        for t in fils:
            t.join(timeout=300)
        # fin : la saisie est rouverte si un admin l'a laissée fermée
        admin = next((c["username"] for c in self.plan["comptes"] if c["role"] == "admin"), None)
        p = self.personne(admin) if admin else None
        if p is not None and p.connexion():
            p.requete("admin_reopen", "POST", f"/administration/campagnes/{self.c}/", fetch=True,
                      data={"action": "rouvrir_contributeurs", "csrfmiddlewaretoken": p.s.cookies.get("csrftoken", "")})
        self.journal.ecrire(kind="end", duration=round(time.time() - debut, 1))
        print(f"Run finished in {time.time() - debut:.0f} s; log: {self.args.log}")


def lancer(args):
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    Simulation(args, plan).lancer()


# ---------------------------------------------------------------- check
def centile(valeurs, q):
    v = sorted(valeurs)
    if not v:
        return 0
    i = min(len(v) - 1, max(0, int(round(q * (len(v) - 1)))))
    return v[i]


def controler(args):
    lignes = [json.loads(x) for x in Path(args.log).read_text(encoding="utf-8").splitlines() if x.strip()]
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    requetes = [x for x in lignes if "page" in x]
    sortie = {"requests": len(requetes)}
    duree = next((x["duration"] for x in lignes if x.get("kind") == "end"), None)
    sortie["duration_s"] = duree
    par_page = defaultdict(list)
    statuts = Counter()
    for r in requetes:
        par_page[r["page"]].append(r["d"])
        statuts[r["status"] or r["err"].split(":")[0]] += 1
    sortie["status"] = dict(statuts)
    sortie["pages"] = {p: {"n": len(d), "median": round(statistics.median(d), 3), "p95": round(centile(d, 0.95), 3),
                           "max": round(max(d), 3)} for p, d in sorted(par_page.items())}
    sortie["errors_5xx"] = [r for r in requetes if r["status"] >= 500 or r["err"]][:50]
    sortie["n_5xx"] = sum(1 for r in requetes if r["status"] >= 500 or r["err"])
    tout = [r["d"] for r in requetes]
    sortie["all"] = {"median": round(statistics.median(tout), 3), "p95": round(centile(tout, 0.95), 3), "max": round(max(tout), 3),
                     "rps": round(len(requetes) / duree, 1) if duree else None}
    enreg = [x for x in lignes if x.get("kind") == "save"]
    sortie["saves"] = dict(Counter(x["outcome"] for x in enreg))
    sortie["same_cell"] = dict(Counter(x["outcome"] for x in enreg if x["step"] == "panel_save_same_cell"))
    communes = defaultdict(list)
    for x in enreg:
        communes[(x["kpi"], x["org"])].append(x)
    if args.server_log and Path(args.server_log).exists():
        texte = Path(args.server_log).read_text(encoding="utf-8", errors="replace")
        sortie["database_is_locked"] = texte.count("database is locked")
        sortie["server_tracebacks"] = texte.count("Traceback (most recent call last)")
        sortie["worker_timeouts"] = texte.count("WORKER TIMEOUT")
    # ---- base : saisies perdues, totaux
    django_pret()
    from django.db import transaction

    from collecte.calcul import recalculer
    from collecte.models import Campagne, Journal, Reponse
    from referentiel.models import KPI, Utilisateur

    campagne = Campagne.objects.select_related("periode").get(pk=plan["campagne"])
    ids = dict(Utilisateur.objects.filter(username__startswith=PREFIXE).values_list("username", "pk"))
    imports = [x for x in lignes if x.get("kind") == "import" and x["outcome"] == "ok"]
    codes = {x["kpi"] for x in enreg} | {code for imp in imports for code, _, _ in imp["values"]}
    kpis = {k.code: k for k in KPI.objects.filter(code__in=codes).select_related("type_reponse", "unite")}

    def nombre(kpi, texte):
        v = Decimal(str(texte))
        return v / 100 if kpi.est_pourcentage else v

    perdues, absentes_journal, finales_fausses, ambigues = [], [], [], 0
    reponses = {(r.kpi_id, r.organisation_id): r for r in Reponse.objects.filter(periode=campagne.periode, kpi_id__in=list(kpis))}
    journal = defaultdict(list)
    for j in Journal.objects.filter(objet="Reponse", champ="valeur", objet_id__in=[str(r.pk) for r in reponses.values()]):
        journal[j.objet_id].append(j)
    # imports : une ligne compte comme une saisie (au moment de la confirmation) si le journal de l'outil la contient ;
    # une ligne refusée (saisie fermée aux contributeurs pendant l'import…) est annoncée dans la page de résultat
    for imp in imports:
        for code, org, v in imp["values"]:
            r = reponses.get((code, org))
            ecrite = r is not None and any(j.utilisateur_id == ids.get(imp["u"]) and j.apres not in ("", "None")
                                           and Decimal(j.apres) == nombre(kpis[code], v) for j in journal.get(str(r.pk), []))
            enreg.append({"kind": "save", "u": imp["u"], "kpi": code, "org": org, "value": v, "saved": ecrite,
                          "outcome": "ok" if ecrite else "import_refused", "t0": imp["t0"], "t1": imp["t1"], "import": True})
            communes[(code, org)].append(enreg[-1])
    for (code, org), essais in communes.items():
        ok = sorted((x for x in essais if x["saved"]), key=lambda x: x["t1"])
        if not ok:
            continue
        r = reponses.get((code, org))
        if r is None:
            perdues.extend(ok)
            continue
        traces = journal.get(str(r.pk), [])
        for x in ok:
            attendu = nombre(kpis[code], x["value"])
            if not any(j.utilisateur_id == ids.get(x["u"]) and j.apres not in ("", "None") and Decimal(j.apres) == attendu for j in traces):
                # même valeur que l'état précédent : rien à écrire, rien au journal (pas une perte)
                if not x.get("import"):
                    absentes_journal.append(x)
        derniere = ok[-1]
        # requêtes qui se chevauchent : l'ordre côté serveur n'est pas connu, toutes sont des fins possibles
        possibles = [x for x in ok if x["t1"] >= derniere["t0"]]
        ambigues += len(possibles) > 1
        if not any(r.valeur == nombre(kpis[code], x["value"]) and r.saisi_par_id == ids.get(x["u"]) for x in possibles):
            finales_fausses.append({"kpi": code, "org": org, "db": str(r.valeur), "db_user": r.saisi_par_id,
                                    "expected": [(x["u"], x["value"], x["t1"]) for x in possibles]})
    # deux enregistrements acceptés à partir de la même version de la case : le second a écrasé le premier sans le voir
    # (le contrôle de version, collecte/saisie.verifier_version, aurait dû le refuser)
    meme_version = Counter((x["kpi"], x["org"], x["version"]) for x in enreg if x["saved"] and "version" in x)
    sortie["accepted_on_stale_version"] = sum(n - 1 for n in meme_version.values() if n > 1)
    sortie["acknowledged_saves"] = sum(1 for x in enreg if x["saved"])
    sortie["import_lines"] = dict(Counter(x["outcome"] for x in enreg if x.get("import")))
    sortie["lost_saves"] = len(perdues)
    sortie["lost_saves_examples"] = perdues[:10]
    sortie["saves_without_log_entry"] = len(absentes_journal)
    sortie["saves_without_log_entry_examples"] = absentes_journal[:10]
    sortie["wrong_final_values"] = len(finales_fausses)
    sortie["wrong_final_values_examples"] = finales_fausses[:10]
    sortie["final_value_ambiguous_overlaps"] = ambigues
    # totaux : recalcul complet dans une transaction annulée, comparé aux valeurs stockées
    champs = ("valeur", "texte", "non_applicable", "statut", "origine")

    def calculees():
        return {(r["periode_id"], r["kpi_id"], r["organisation_id"]): tuple(r[c] for c in champs)
                for r in Reponse.objects.filter(origine__in=["calcul", "agregation", "cumul"]).values("periode_id", "kpi_id", "organisation_id", *champs)}

    avant = calculees()
    with transaction.atomic():
        recalculer(campagne)
        apres = calculees()
        transaction.set_rollback(True)
    ecarts = [k for k in set(avant) | set(apres) if avant.get(k) != apres.get(k)]
    sortie["calculated_cells"] = len(avant)
    sortie["totals_differences"] = len(ecarts)
    sortie["totals_differences_examples"] = [(k, avant.get(k), apres.get(k)) for k in ecarts[:10]]
    texte = json.dumps(sortie, indent=1, default=str, ensure_ascii=False)
    if args.json:
        Path(args.json).write_text(texte, encoding="utf-8")
    afficher(sortie)
    probleme = sortie["n_5xx"] or sortie["lost_saves"] or sortie["wrong_final_values"] or sortie["totals_differences"] \
        or sortie["accepted_on_stale_version"] \
        or sortie["saves_without_log_entry"] or sortie.get("database_is_locked")
    sys.exit(1 if probleme else 0)


def afficher(s):
    print(f"Requests: {s['requests']} in {s['duration_s']} s ({s['all']['rps']} req/s); status {s['status']}")
    print(f"All pages: median {s['all']['median']} s, p95 {s['all']['p95']} s, max {s['all']['max']} s")
    print(f"{'page':28} {'n':>6} {'median':>8} {'p95':>8} {'max':>8}")
    for p, v in s["pages"].items():
        print(f"{p:28} {v['n']:>6} {v['median']:>8} {v['p95']:>8} {v['max']:>8}")
    print(f"Saves: {s['saves']}; same cell: {s.get('same_cell')}")
    print(f"5xx / network errors: {s['n_5xx']}; 'database is locked': {s.get('database_is_locked', '?')}; "
          f"server tracebacks: {s.get('server_tracebacks', '?')}; worker timeouts: {s.get('worker_timeouts', '?')}")
    print(f"Acknowledged saves: {s['acknowledged_saves']}; lost: {s['lost_saves']}; without log entry: {s['saves_without_log_entry']}; "
          f"wrong final value: {s['wrong_final_values']} (overlaps: {s['final_value_ambiguous_overlaps']}); "
          f"accepted on a stale version: {s['accepted_on_stale_version']}")
    print(f"Totals: {s['calculated_cells']} calculated cells, {s['totals_differences']} difference(s) after a full recalculation")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sous = ap.add_subparsers(dest="commande", required=True)
    a = sous.add_parser("prepare")
    a.add_argument("--plan", required=True)
    a.add_argument("--contributors", type=int, default=50)
    a.add_argument("--validators", type=int, default=5)
    a.add_argument("--admins", type=int, default=3)
    a.add_argument("--cells", type=int, default=10, help="own cells per contributor")
    a.add_argument("--force", action="store_true", help="accept a database whose accounts do not look like the demo")
    b = sous.add_parser("run")
    b.add_argument("--plan", required=True)
    b.add_argument("--url", required=True)
    b.add_argument("--log", required=True)
    b.add_argument("--rounds", type=int, default=2, help="passes over each contributor's cells")
    b.add_argument("--think", type=float, default=1.0, help="think time between actions (seconds, x0.3 to x1)")
    b.add_argument("--ramp", type=float, default=5.0, help="logins spread over this many seconds")
    b.add_argument("--importers", type=int, default=5)
    b.add_argument("--exporters", type=int, default=5)
    b.add_argument("--big-import", type=int, default=0, help="lines of a file imported by an admin during the run")
    b.add_argument("--admin-period", type=float, default=20.0)
    b.add_argument("--timeout", type=float, default=180.0)
    b.add_argument("--reader-password", default="demo-probant-2026")
    c = sous.add_parser("check")
    c.add_argument("--plan", required=True)
    c.add_argument("--log", required=True)
    c.add_argument("--server-log")
    c.add_argument("--json")
    args = ap.parse_args()
    {"prepare": preparer, "run": lancer, "check": controler}[args.commande](args)


if __name__ == "__main__":
    main()
