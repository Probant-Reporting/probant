"""Fifty people at the same moment on the big database: response times, errors, and correctness afterwards.

    python3 qa/load/concurrent_users.py prepare --plan plan.json [--contributors 38 --validators 5 --admins 3 --readers 4]
    python3 qa/load/concurrent_users.py run     --plan plan.json --url http://127.0.0.1:8031 --log run.jsonl \
        [--duration 300] [--think 4] [--server-pid <gunicorn master>] [--watch-pid <other process> ...]
    python3 qa/load/concurrent_users.py check   --plan plan.json --log run.jsonl [--server-log gunicorn.log] \
        [--postgres-log /var/log/postgresql/postgresql-16-main.log] [--json result.json]

For the generic big database of ``make_big_data.py`` (fictitious group "Grandgroupe", open 2026 campaign, open month),
served as in production (gunicorn as in docker/entrypoint.sh, DJANGO_DEBUG=0, ``manage.py run_imports --schedule`` for
the background exports). ``prepare`` and ``check`` open the database given by the environment (DATA_DIR / SQLITE_FILE
or DATABASE_URL), like manage.py; ``run`` only talks HTTP (standard library, no extra package), and reads the database
only to count its connections (PostgreSQL). Its own accounts are those of the big database (password demo-probant-2026).

- prepare: picks the accounts (contributors whose sites are side by side in the tree, so several of them write in the
  same subsidiary at the same time, plus the contributors of these subsidiaries; validators of the first countries;
  administrators; readers), and their cells of the open campaign and of the open month (number cells with a value last
  year, so a new value stays close to it and can be validated). To make several people write in the SAME organisation,
  it gives three more contributors a few cells of the first site (assignments added: fictitious database only). Writes
  the plan (JSON).
- run: every account signs in (spread over --ramp seconds) and works with a think time until --duration: contributors
  open the Data entry grid of their organisation, open a cell, type (automatic draft), then validate or save, sometimes
  upload evidence, open For me; two contributors import an Excel file of their cells; validators open the grid of their
  scope, correct a value or send a validated cell back to draft; administrators read Consolidation, Visualisation, the
  History and the Dashboard, start large exports (made in the background) and wait for them, import a file, and one of
  them makes a backup half-way; readers read the Dashboard and the Visualisation. Every request goes to the log
  (JSONL), and every few seconds a sample of the server: processor and memory of the processes given by --server-pid
  (and their children) and --watch-pid, connections to the database and their state (PostgreSQL).
- check: per page, median, 95th percentile and maximum; HTTP errors and time-outs; in the server log, "database is
  locked", tracebacks, worker time-outs; in the PostgreSQL log, deadlocks and lock time-outs since the run started.
  Then the database: every save acknowledged by the server is in the History once (not lost, not twice), the final value
  of each cell is one of the last acknowledged saves, and a full recalculation of the open campaign and of the open month
  gives exactly the stored totals. Exit code 0 when nothing is lost, doubled or wrong and there is no 5xx.
"""
# Messages en anglais (outil pour l'IT et la recette) ; commentaires et identifiants en français.
import argparse
import http.cookiejar
import io
import json
import os
import random
import re
import statistics
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent.parent
MOT_DE_PASSE = "demo-probant-2026"
PDF = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj "
       b"3 0 obj<</Type/Page/MediaBox[0 0 200 200]/Parent 2 0 R>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n")
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def django_pret():
    sys.path.insert(0, str(RACINE))
    os.chdir(RACINE)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()


# ---------------------------------------------------------------- prepare
def preparer(args):
    django_pret()
    from collecte import saisie as S
    from collecte.models import Campagne, ReglageExport, Reponse
    from referentiel.models import Attribution, Niveau, Organisation, Utilisateur

    if Utilisateur.objects.exclude(email__iendswith="@exemple.test").exists():
        sys.exit("Accounts with a real-looking e-mail address: this is not the fictitious big database. Refused.")
    ouvertes = Campagne.objects.filter(statut=Campagne.Statut.OUVERTE).select_related("periode", "referentiel")
    annuelle = next((c for c in ouvertes if c.periode.type == "annee"), None)
    mois = max((c for c in ouvertes if c.periode.type == "mois"), key=lambda c: c.periode.debut, default=None)
    if annuelle is None or not Utilisateur.objects.filter(username="contrib000").exists():
        sys.exit("No open annual campaign or no account contrib000: build the database with qa/load/make_big_data.py first.")
    sites = list(Organisation.objects.filter(niveau_id=Niveau.SITE, actif=True).order_by("parent_id", "rang"))
    noms = dict(Organisation.objects.values_list("pk", "nom"))

    def cases_de(u, campagne, n_max, orgs=None):
        """Cases numériques saisissables de la personne dans la campagne, avec une valeur l'an dernier (ou le mois d'avant)
        assez grande pour qu'une valeur nouvelle, proche, passe le contrôle d'écart."""
        if campagne is None:
            return []
        attrs = Attribution.objects.filter(utilisateur=u, role="contributeur").select_related(
            "kpi__type_reponse", "kpi__unite", "kpi__type_saisie", "organisation__niveau")
        if orgs is not None:
            attrs = attrs.filter(organisation__in=orgs)
        sortie = []
        for a in attrs.order_by("organisation__parent_id", "organisation__rang", "kpi__code"):
            k, o = a.kpi, a.organisation
            if not k.est_numerique or k.est_pourcentage or k.est_herite or not S.dans_la_campagne(campagne, k) \
                    or not o.actif or S.est_calculee(k, o, None, campagne):
                continue
            sortie.append((k, o))
        refs = {(r.kpi_id, r.organisation_id): r.valeur for r in Reponse.objects.filter(
            periode__in=_periodes_avant(campagne), kpi_id__in={k.code for k, _ in sortie},
            organisation_id__in={o.pk for _, o in sortie}, valeur__isnull=False).order_by("periode__debut")}
        retenues = [(k, o, refs[(k.code, o.pk)]) for k, o in sortie if refs.get((k.code, o.pk), 0) >= 1000]
        return [[k.code, o.pk, int(v)] for k, o, v in retenues[:n_max]]

    # contributeurs : ceux des premiers sites (4 sites chacun, voisins dans l'arbre : plusieurs par filiale), puis les
    # contributeurs des filiales de ces sites (cases au niveau filiale, au-dessus des sites saisis en même temps)
    comptes = {u.username: u for u in Utilisateur.objects.filter(is_active=True)}
    nc = args.contributors
    par_sites = [comptes[f"contrib{i:03d}"] for i in range(max(1, nc - nc // 5))]
    filiales = {s.parent_id for i, s in enumerate(sites) if i // 4 < len(par_sites)}
    de_filiale = [u for u in Utilisateur.objects.filter(attributions__organisation_id__in=filiales,
                                                        attributions__role="contributeur").distinct().order_by("username")
                  if u not in par_sites]
    contributeurs = (par_sites + de_filiale)[:nc]
    for i in range(len(par_sites), nc):  # pas assez de contributeurs de filiale : la suite des contributeurs de sites
        if len(contributeurs) >= nc:
            break
        u = comptes[f"contrib{i:03d}"]
        if u not in contributeurs:
            contributeurs.append(u)
    # même organisation : trois personnes de plus reçoivent chacune quelques cases du premier site du premier contributeur
    premier_site = Organisation.objects.get(pk=Attribution.objects.filter(
        utilisateur=contributeurs[0], role="contributeur", organisation__niveau_id=Niveau.SITE)
        .order_by("organisation__parent_id", "organisation__rang").values_list("organisation_id", flat=True)[0])
    cases_site = [c for c in cases_de(contributeurs[0], annuelle, 400, [premier_site])]
    meme_org = {}
    for n, u in enumerate(contributeurs[1:4], start=1):
        part = cases_site[n * 6:(n + 1) * 6]
        Attribution.objects.bulk_create([Attribution(kpi_id=c[0], organisation_id=c[1], utilisateur=u, role="contributeur")
                                         for c in part], ignore_conflicts=True)
        meme_org[u.username] = part
    plan = {"campagne": annuelle.pk, "mois": mois.pk if mois else None, "mot_de_passe": MOT_DE_PASSE, "comptes": [],
            "meme_organisation": premier_site.pk, "orgs": {str(k): v for k, v in noms.items()}}
    for n, u in enumerate(contributeurs, start=1):
        propres = cases_de(u, annuelle, args.cells)
        if n == 1:  # le premier contributeur garde ses propres cases du site partagé (pas celles données aux trois autres)
            donnees = {(c[0], c[1]) for part in meme_org.values() for c in part}
            propres = [c for c in cases_site if (c[0], c[1]) not in donnees][:args.cells]
        plan["comptes"].append({"username": u.username, "role": "contributeur", "n": n,
                                "cases": propres + meme_org.get(u.username, []),
                                "mois": cases_de(u, mois, 4)})
    # validateurs : ceux des pays des premiers sites (rôle sur le pays : toutes les cases de ses sites et filiales)
    pays = sorted({s.parent.parent_id for i, s in enumerate(sites) if i // 4 < len(par_sites)})
    validateurs = [u for u in Utilisateur.objects.filter(role="validateur", is_active=True, attributions__organisation_id__in=pays)
                   .distinct().order_by("username")][:args.validators]
    toutes = [c for x in plan["comptes"] for c in x["cases"]]
    for n, u in enumerate(validateurs, start=1):
        perimetre = set(Attribution.objects.filter(utilisateur=u, role="validateur").values_list("organisation_id", flat=True))
        visibles = [c for c in toutes if _ancetres(c[1], perimetre)]
        plan["comptes"].append({"username": u.username, "role": "validateur", "n": n, "cases": visibles})
    admins = [u.username for u in Utilisateur.objects.filter(role="admin", is_active=True, username__startswith="adm").order_by("username")]
    for n, nom in enumerate((["admin"] + admins)[:args.admins], start=1):
        plan["comptes"].append({"username": nom, "role": "admin", "n": n})
    lecteurs = ["lecteur"] + [u for u in Utilisateur.objects.filter(role="lecteur", username__startswith="lect")
                              .order_by("username").values_list("username", flat=True)]
    for n, nom in enumerate(lecteurs[:args.readers], start=1):
        plan["comptes"].append({"username": nom, "role": "lecteur", "n": n})
    plan["exports"] = {nom: pk for pk, nom in ReglageExport.objects.filter(partage=True).values_list("pk", "nom")}
    plan["autres_cases"] = _cases_libres(annuelle, {(c[0], c[1]) for c in toutes}, 150)
    Path(args.plan).write_text(json.dumps(plan, indent=1), encoding="utf-8")
    roles = Counter(x["role"] for x in plan["comptes"])
    print(f"Plan written: {args.plan} — campaign {annuelle} and {mois}; {dict(roles)}; "
          f"{len(toutes)} cells for the contributors, 4 people in organisation {noms[premier_site.pk]}, "
          f"subsidiaries shared: {len(filiales)}.")


def _periodes_avant(campagne):
    from collecte.models import Periode

    return Periode.objects.filter(type=campagne.periode.type, debut__lt=campagne.periode.debut).order_by("-debut")[:1]


_PARENTS = {}


def _ancetres(org_id, perimetre):
    from referentiel.models import Organisation

    if not _PARENTS:
        _PARENTS.update(Organisation.objects.values_list("pk", "parent_id"))
    while org_id is not None:
        if org_id in perimetre:
            return True
        org_id = _PARENTS.get(org_id)
    return False


def _cases_libres(campagne, prises, n):
    """Cases de sites saisissables attribuées à personne de la simulation, pour l'import de l'administrateur."""
    from collecte import saisie as S
    from collecte.models import Reponse
    from referentiel.models import Attribution, Niveau

    sortie = []
    vues = set()
    for a in Attribution.objects.filter(role="contributeur", organisation__niveau_id=Niveau.SITE, organisation__actif=True) \
            .select_related("kpi__type_reponse", "kpi__unite", "kpi__type_saisie", "organisation").order_by("-organisation_id", "kpi_id")[:20000]:
        k, o = a.kpi, a.organisation
        cle = (k.code, o.pk)
        if cle in prises or cle in vues or not k.est_numerique or k.est_pourcentage or k.est_herite \
                or not S.dans_la_campagne(campagne, k) or S.est_calculee(k, o, None, campagne):
            continue
        vues.add(cle)
        sortie.append(cle)
        if len(sortie) >= n * 3:
            break
    refs = {(r.kpi_id, r.organisation_id): r.valeur for r in Reponse.objects.filter(
        periode__in=_periodes_avant(campagne), kpi_id__in={c[0] for c in sortie}, organisation_id__in={c[1] for c in sortie},
        valeur__isnull=False)}
    return [[c, o, int(refs[(c, o)])] for c, o in sortie if refs.get((c, o), 0) >= 1000][:n]


# ---------------------------------------------------------------- run : client HTTP (bibliothèque standard)
class Journal:
    def __init__(self, chemin):
        self.f = open(chemin, "w", encoding="utf-8")
        self.verrou = threading.Lock()
        self.t0 = time.time()

    def ecrire(self, **ligne):
        with self.verrou:
            self.f.write(json.dumps(ligne, ensure_ascii=False, default=str) + "\n")
            self.f.flush()


class SansRedirection(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):
        return None


def _multipart(champs, fichiers):
    limite = uuid.uuid4().hex
    corps = io.BytesIO()
    for nom, valeur in champs.items():
        corps.write(f'--{limite}\r\nContent-Disposition: form-data; name="{nom}"\r\n\r\n{valeur}\r\n'.encode())
    for nom, (fichier, contenu, type_) in fichiers.items():
        corps.write(f'--{limite}\r\nContent-Disposition: form-data; name="{nom}"; filename="{fichier}"\r\n'
                    f"Content-Type: {type_}\r\n\r\n".encode())
        corps.write(contenu + b"\r\n")
    corps.write(f"--{limite}--\r\n".encode())
    return corps.getvalue(), f"multipart/form-data; boundary={limite}"


class Reponse:
    def __init__(self, statut, entetes, corps):
        self.status, self.headers, self.content = statut, entetes, corps

    @property
    def text(self):
        return self.content.decode("utf-8", errors="replace")


class Personne:
    """Une personne connectée (cookies de session) qui journalise chacune de ses requêtes."""

    def __init__(self, url, username, mdp, journal, timeout, role):
        self.url, self.username, self.mdp, self.journal, self.timeout, self.role = url.rstrip("/"), username, mdp, journal, timeout, role
        self.cookies = http.cookiejar.CookieJar()
        self.suivre = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))
        self.rester = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies), SansRedirection())

    def jeton(self):
        return next((c.value for c in self.cookies if c.name == "csrftoken"), "")

    def requete(self, page, methode, chemin, fetch=False, data=None, fichiers=None, redirects=True):
        entetes = {"User-Agent": "probant-load-test", "Accept-Encoding": "identity"}
        if fetch:
            entetes["X-Requested-With"] = "fetch"
        corps = None
        if methode == "POST":
            entetes["X-CSRFToken"] = self.jeton()
            entetes["Referer"] = self.url + "/"
            data = {"csrfmiddlewaretoken": self.jeton(), **(data or {})}
            if fichiers:
                corps, entetes["Content-Type"] = _multipart(data, fichiers)
            else:
                corps = urllib.parse.urlencode(data).encode()
                entetes["Content-Type"] = "application/x-www-form-urlencoded"
        req = urllib.request.Request(self.url + chemin, data=corps, headers=entetes, method=methode)
        debut = time.time()
        statut, erreur, rep = 0, "", None
        try:
            with (self.suivre if redirects else self.rester).open(req, timeout=self.timeout) as r:
                rep = Reponse(r.status, r.headers, r.read())
        except urllib.error.HTTPError as e:
            try:
                rep = Reponse(e.code, e.headers, e.read())
            except Exception:  # noqa: BLE001 - corps illisible : le statut suffit
                rep = Reponse(e.code, e.headers, b"")
        except Exception as e:  # noqa: BLE001 - délai dépassé, connexion refusée ou coupée : noté, la personne continue
            erreur = type(e).__name__ + ": " + str(e)[:200]
        fin = time.time()
        statut = rep.status if rep is not None else 0
        self.journal.ecrire(t=round(debut - self.journal.t0, 3), d=round(fin - debut, 4), u=self.username, role=self.role,
                            page=page, m=methode, path=chemin, status=statut, size=len(rep.content) if rep else 0, err=erreur)
        return rep, debut, fin

    def connexion(self):
        self.requete("login_form", "GET", "/connexion/")
        rep, *_ = self.requete("login", "POST", "/connexion/", data={"username": self.username, "password": self.mdp},
                               redirects=False)
        return rep is not None and rep.status == 302


def _html(rep):
    """Texte de la page ; en mode « fetch », le panneau arrive en JSON ({"html": ...})."""
    if rep is None:
        return ""
    if (rep.headers.get("content-type") or "").startswith("application/json"):
        try:
            d = json.loads(rep.text)
            return d.get("html", "") or rep.text
        except ValueError:
            return rep.text
    return rep.text


def _version(html):
    m = re.search(r'name="version" value="([^"]*)"', html or "")
    return m.group(1) if m else None


def _issue_panneau(rep):
    """Issue d'un envoi depuis le panneau : « ok », « conflit », « refus » (motif métier), « 403 », « http » ou
    « reseau »."""
    if rep is None:
        return "reseau"
    if rep.status == 403:
        return "403"
    if rep.status != 200:
        return "http"
    html = _html(rep)
    if "data-conflit" in html:
        return "conflit"
    if "data-non-enregistre" in html:
        return "refus"
    return "ok"


class Simulation:
    def __init__(self, args, plan):
        self.args, self.plan = args, plan
        self.journal = Journal(args.log)
        self.c, self.m = plan["campagne"], plan.get("mois")
        self.fin = time.time() + args.ramp + args.duration
        self.seq = Counter()
        self.verrou = threading.Lock()
        self.sauvegarde_faite = threading.Event()

    def encore(self):
        return time.time() < self.fin

    def personne(self, compte):
        return Personne(self.args.url, compte["username"], self.plan["mot_de_passe"], self.journal, self.args.timeout, compte["role"])

    def pause(self, h, facteur=1.0):
        time.sleep(h.uniform(0.5, 1.5) * self.args.think * facteur)

    def valeur(self, base, cle):
        """Valeur nouvelle et unique pour la case : la valeur de l'an dernier plus un numéro (moins de 30 %) ; décalée de
        40 par passage (``--run``), pour qu'un passage n'écrive pas une valeur déjà en place (rien à écrire, rien au
        journal : le contrôle la compterait perdue)."""
        with self.verrou:
            self.seq[cle] += 1
            return str(base + 40 * (self.args.run - 1) + self.seq[cle])

    def ouvrir(self, p, campagne, code, org):
        rep, *_ = p.requete("panel_open", "GET", f"/saisie/{campagne}/{code}/{org}/", fetch=True)
        return _version(_html(rep)) if rep is not None and rep.status == 200 else None

    def envoyer(self, p, page, campagne, code, org, valeur, action, version, auto=False, meme=""):
        donnees = {"action": action, "valeur": valeur, "commentaire": "load test", "version": version or ""}
        if auto:
            donnees["auto"] = "1"
        rep, debut, fin = p.requete(page, "POST", f"/saisie/{campagne}/{code}/{org}/", fetch=True, data=donnees)
        nouvelle = None
        if auto:
            try:
                d = json.loads(rep.text) if rep is not None and rep.status == 200 else {}
            except ValueError:
                d = {}
            issue = "ok" if d.get("ok") else ("conflit" if d.get("conflit") else ("refus" if rep is not None and rep.status == 200
                                                                                   else _issue_panneau(rep)))
            nouvelle = d.get("version")
            detail = d.get("motif", "") or (rep.text[:200] if rep is not None and rep.status != 200 else "")
        else:
            issue = _issue_panneau(rep)
            if rep is not None and rep.status == 200:
                nouvelle = _version(_html(rep))
            m = re.search(r'class="[^"]*erreur[^"]*"[^>]*>\s*(?:<[^>]+>\s*)*([^<]{3,200})', _html(rep)) if issue == "refus" else None
            detail = "version conflict" if issue == "conflit" else m.group(1).strip() if m else (
                rep.text[:200] if rep is not None and issue == "403" else "")
        valide = action == "valider" and issue == "ok" and 'class="statut statut-valide"' in _html(rep)
        self.journal.ecrire(kind="save", step=page, u=p.username, campagne=campagne, kpi=code, org=org, value=valeur,
                            action=action, outcome=issue, saved=issue == "ok", validated=valide, version=version or "", detail=detail,
                            same=meme, t0=round(debut - self.journal.t0, 3), t1=round(fin - self.journal.t0, 3))
        return issue, nouvelle or version  # refusé : la personne garde la version qu'elle a vue

    # -- contributeur : la grille de son organisation, le panneau, le brouillon automatique, la validation
    def contributeur(self, compte):
        h = random.Random(compte["n"])
        p = self.personne(compte)
        time.sleep(h.uniform(0, self.args.ramp))
        if not p.connexion():
            self.journal.ecrire(kind="login_failed", u=p.username)
            return
        p.requete("pour_moi", "GET", "/pour-moi/")
        cases = [(self.c, *c) for c in compte["cases"]] + [(self.m, *c) for c in compte.get("mois", []) if self.m]
        if not cases:
            return
        meme = {(c[0], c[1]) for c in compte["cases"] if c[1] == self.plan["meme_organisation"]}
        org_vue, tour, importe, preuves = None, 0, False, 0
        while self.encore():
            h.shuffle(cases)
            for campagne, code, org, base in cases:
                if not self.encore():
                    break
                if org != org_vue:  # la grille de l'organisation (vue « une organisation à la fois »)
                    p.requete("data_entry_grid", "GET", f"/saisie/?campagne={campagne}&org={org}")
                    org_vue = org
                version = self.ouvrir(p, campagne, code, org)
                self.pause(h)
                etiquette = "same_org" if (code, org) in meme else ""
                v = self.valeur(base, (campagne, code, org))
                issue, version = self.envoyer(p, "autosave_draft", campagne, code, org, v, "enregistrer", version, auto=True, meme=etiquette)
                self.pause(h, 0.5)
                action = "valider" if h.random() < 0.6 else "enregistrer"
                if h.random() < 0.3:  # la personne corrige encore avant de valider ou d'enregistrer
                    v = self.valeur(base, (campagne, code, org))
                self.envoyer(p, "panel_validate" if action == "valider" else "panel_save", campagne, code, org, v, action,
                             version, meme=etiquette)
                if preuves < 1 and h.random() < 0.2:
                    rep, *_ = p.requete("evidence_upload", "POST", f"/saisie/{campagne}/{code}/{org}/", fetch=True,
                                        data={"action": "preuve"},
                                        fichiers={"fichier": (f"evidence-{compte['n']}.pdf", PDF, "application/pdf")})
                    self.journal.ecrire(kind="evidence", u=p.username, kpi=code, org=org, outcome=_issue_panneau(rep))
                    preuves += 1
                self.pause(h)
            tour += 1
            p.requete("pour_moi", "GET", "/pour-moi/")
            if compte["n"] in (5, 6) and not importe:  # deux contributeurs importent un fichier de leurs cases
                self.importer(p, compte["cases"], self.c, "import_contributor")
                importe = True
            if compte["n"] % 10 == 7:
                p.requete("dashboard", "GET", f"/tableau-de-bord/?campagne={self.c}")

    def importer(self, p, cases, campagne, page):
        """Fichier de valeurs (Excel) : aperçu puis confirmation ; les valeurs écrites sont gardées pour le contrôle."""
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.title = "Valeurs"
        ws.append(["ID KPI", "Organisation", "Valeur", "Commentaire"])
        lignes = []
        for code, org, base in cases:
            v = self.valeur(base, (campagne, code, org))
            lignes.append([code, org, v])
            ws.append([code, self.plan["orgs"].get(str(org), str(org)), float(v), "load test import"])
        flux = io.BytesIO()
        wb.save(flux)
        p.requete(f"{page}_page", "GET", "/import-export/importer/")
        p.requete(f"{page}_preview", "POST", "/import-export/importer/", data={"action": "verifier", "campagne": str(campagne)},
                  fichiers={"fichier": (f"import-{p.username}.xlsx", flux.getvalue(), XLSX)})
        rep, debut, fin = p.requete(f"{page}_confirm", "POST", "/import-export/importer/", data={"action": "confirmer"})
        ok = rep is not None and rep.status == 200 and "resultat-import" in rep.text
        self.journal.ecrire(kind="import", u=p.username, campagne=campagne, outcome="ok" if ok else "error", lines=len(lignes),
                            t0=round(debut - self.journal.t0, 3), t1=round(fin - self.journal.t0, 3), values=lignes)

    # -- validateur : la grille d'une organisation de son périmètre, correction ou retour en brouillon
    def validateur(self, compte):
        h = random.Random(100 + compte["n"])
        p = self.personne(compte)
        time.sleep(h.uniform(0, self.args.ramp))
        if not p.connexion():
            self.journal.ecrire(kind="login_failed", u=p.username)
            return
        cases = list(compte["cases"])
        while self.encore():
            p.requete("pour_moi", "GET", "/pour-moi/")
            if not cases:
                self.pause(h, 3)
                continue
            for code, org, base in h.sample(cases, min(4, len(cases))):
                if not self.encore():
                    break
                p.requete("data_entry_grid", "GET", f"/saisie/?campagne={self.c}&org={org}")
                version = self.ouvrir(p, self.c, code, org)
                self.pause(h)
                tirage = h.random()
                if tirage < 0.25:  # corrige la valeur (même case qu'un contributeur, peut-être au même moment)
                    self.envoyer(p, "validator_correct", self.c, code, org, self.valeur(base, (self.c, code, org)),
                                 "enregistrer", version)
                elif tirage < 0.45:  # renvoie une case validée en brouillon (refusée si elle ne l'est pas)
                    p.requete("validator_back_to_draft", "POST", f"/saisie/{self.c}/{code}/{org}/", fetch=True,
                              data={"action": "brouillon"})
                self.pause(h)
            p.requete("dashboard", "GET", f"/tableau-de-bord/?campagne={self.c}")
            self.pause(h, 2)

    # -- administrateurs : lecture des pages lourdes, gros exports, import, une sauvegarde
    def admin(self, compte):
        h = random.Random(200 + compte["n"])
        p = self.personne(compte)
        time.sleep(h.uniform(0, self.args.ramp))
        if not p.connexion():
            self.journal.ecrire(kind="login_failed", u=p.username)
            return
        n = compte["n"]
        exports = [pk for _, pk in sorted(self.plan["exports"].items())]
        importe = False
        while self.encore():
            p.requete("admin_home", "GET", "/administration/")
            p.requete("consolidation", "GET", f"/tableau-de-bord/consolidation/?campagne={self.c}")
            self.pause(h, 2)
            p.requete("visualisation", "GET", "/visualisation/")
            p.requete("history_admin", "GET", "/administration/journal/")
            self.pause(h, 2)
            if exports:
                self.exporter(p, exports[(n + int(time.time())) % len(exports)], h)
            if n == 2 and not importe and self.plan.get("autres_cases"):
                self.importer(p, self.plan["autres_cases"][:100], self.c, "import_admin")
                importe = True
            if n == 3 and not self.sauvegarde_faite.is_set() and time.time() > self.fin - self.args.duration / 2:
                self.sauvegarde_faite.set()
                rep, debut, fin = p.requete("backup", "POST", "/administration/parametres/hebergement/",
                                            data={"action": "sauvegarder"}, redirects=False)
                self.journal.ecrire(kind="backup", u=p.username, status=rep.status if rep is not None else 0,
                                    location=(rep.headers.get("Location") or "") if rep is not None else "",
                                    t0=round(debut - self.journal.t0, 3), t1=round(fin - self.journal.t0, 3))
            p.requete("dashboard", "GET", f"/tableau-de-bord/?campagne={self.c}")
            self.pause(h, 3)

    def exporter(self, p, pk, h):
        """Un export partagé : fichier tout de suite, ou tâche en arrière-plan suivie jusqu'au fichier (Mes exports)."""
        rep, debut, _ = p.requete("export_request", "GET", f"/import-export/exporter/?modele={pk}&telecharger=1", redirects=False)
        if rep is None or rep.status != 302:
            self.journal.ecrire(kind="export", u=p.username, modele=pk, mode="direct", status=rep.status if rep else 0,
                                seconds=round(time.time() - debut, 2))
            return
        page, *_ = p.requete("my_exports", "GET", "/import-export/")
        taches = re.findall(r"/import-export/exports/(\d+)/etat/", page.text if page is not None else "")
        if not taches:
            self.journal.ecrire(kind="export", u=p.username, modele=pk, mode="background", status="no_task",
                                seconds=round(time.time() - debut, 2))
            return
        tache, statut = max(int(t) for t in taches), ""
        while time.time() - debut < self.args.export_wait:
            time.sleep(3)
            r, *_ = p.requete("export_state", "GET", f"/import-export/exports/{tache}/etat/")
            try:
                d = json.loads(r.text) if r is not None and r.status == 200 else {}
            except ValueError:
                d = {}
            statut = d.get("statut", "")
            if d.get("fini"):
                break
        if statut == "pret":
            p.requete("export_download", "GET", f"/import-export/exports/{tache}/fichier/")
        self.journal.ecrire(kind="export", u=p.username, modele=pk, mode="background", task=tache, status=statut,
                            seconds=round(time.time() - debut, 2))

    def lecteur(self, compte):
        h = random.Random(300 + compte["n"])
        p = self.personne(compte)
        time.sleep(h.uniform(0, self.args.ramp))
        if not p.connexion():
            self.journal.ecrire(kind="login_failed", u=p.username)
            return
        while self.encore():
            p.requete("dashboard", "GET", "/tableau-de-bord/")
            self.pause(h, 2)
            p.requete("visualisation", "GET", "/visualisation/")
            self.pause(h, 3)

    # -- échantillons du serveur : processeur, mémoire, connexions à la base
    def echantillonner(self):
        pids_racines = [int(x) for x in [self.args.server_pid, *self.args.watch_pid] if x]
        compteur = None
        if os.environ.get("DATABASE_URL"):
            import psycopg

            from urllib.parse import urlparse
            u = urlparse(os.environ["DATABASE_URL"])
            base = u.path.lstrip("/")
            try:
                compteur = psycopg.connect(os.environ["DATABASE_URL"].replace("postgres://", "postgresql://"), autocommit=True)
            except Exception as e:  # noqa: BLE001
                self.journal.ecrire(kind="sample_error", err=str(e)[:200])
        precedent = {}
        tic = os.sysconf("SC_CLK_TCK")
        while time.time() < self.fin + 5:
            ech = {"kind": "sample", "t": round(time.time() - self.journal.t0, 1)}
            pids = _descendants(pids_racines)
            pg = []
            if compteur is not None:
                try:
                    lignes = compteur.execute("select pid, state, wait_event_type from pg_stat_activity where datname = %s "
                                              "and pid <> pg_backend_pid()", (base,)).fetchall()
                    ech["db_connections"] = len(lignes)
                    ech["db_states"] = dict(Counter(s or "?" for _, s, _ in lignes))
                    ech["db_waiting_lock"] = sum(1 for *_, w in lignes if w == "Lock")
                    pg = [p for p, *_ in lignes]
                except Exception as e:  # noqa: BLE001
                    ech["db_error"] = str(e)[:200]
            cpu, rss, cpu_pg, rss_pg = 0.0, 0, 0.0, 0
            for pid, groupe in [(x, "app") for x in pids] + [(x, "pg") for x in pg]:
                t, r = _stat(pid)
                if t is None:
                    continue
                avant = precedent.get(pid)
                precedent[pid] = (t, time.time())
                d = (t - avant[0]) / tic / max(0.001, time.time() - avant[1]) if avant else 0.0
                if groupe == "app":
                    cpu, rss = cpu + d, rss + r
                else:
                    cpu_pg, rss_pg = cpu_pg + d, rss_pg + r
            ech.update(app_cpu=round(cpu, 2), app_rss_mb=round(rss / 1024, 1), app_processes=len(pids),
                       db_cpu=round(cpu_pg, 2), db_rss_mb=round(rss_pg / 1024, 1), load1=os.getloadavg()[0])
            self.journal.ecrire(**ech)
            time.sleep(self.args.sample)

    def lancer(self):
        fils = [threading.Thread(target=getattr(self, c["role"]), args=(c,), name=c["username"], daemon=True)
                for c in self.plan["comptes"]]
        echantillons = threading.Thread(target=self.echantillonner, daemon=True)
        debut = time.time()
        self.journal.ecrire(kind="start", wall=debut, people=len(fils))
        echantillons.start()
        for t in fils:
            t.start()
        for t in fils:
            t.join(timeout=max(1, self.fin - time.time()) + self.args.export_wait + 60)
        self.journal.ecrire(kind="end", duration=round(time.time() - debut, 1))
        echantillons.join(timeout=10)
        print(f"Run finished in {time.time() - debut:.0f} s with {len(fils)} people; log: {self.args.log}")


def _descendants(racines):
    enfants = defaultdict(list)
    for d in os.listdir("/proc"):
        if d.isdigit():
            try:
                ppid = int(Path(f"/proc/{d}/stat").read_text().rsplit(")", 1)[1].split()[1])
            except (OSError, IndexError, ValueError):
                continue
            enfants[ppid].append(int(d))
    vus, pile = set(), list(racines)
    while pile:
        p = pile.pop()
        if p in vus or not Path(f"/proc/{p}").exists():
            continue
        vus.add(p)
        pile += enfants.get(p, [])
    return sorted(vus)


def _stat(pid):
    """Temps processeur (tics) et mémoire résidente (ko) d'un processus."""
    try:
        champs = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        rss = next((int(x.split()[1]) for x in Path(f"/proc/{pid}/status").read_text().splitlines() if x.startswith("VmRSS:")), 0)
        return int(champs[11]) + int(champs[12]), rss
    except (OSError, IndexError, ValueError):
        return None, 0


def lancer(args):
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    Simulation(args, plan).lancer()


# ---------------------------------------------------------------- check
def centile(valeurs, q):
    v = sorted(valeurs)
    if not v:
        return 0
    return v[min(len(v) - 1, max(0, int(round(q * (len(v) - 1)))))]


def controler(args):
    lignes = [json.loads(x) for x in Path(args.log).read_text(encoding="utf-8").splitlines() if x.strip()]
    requetes = [x for x in lignes if "page" in x]
    debut_mur = next((x["wall"] for x in lignes if x.get("kind") == "start"), None)
    sortie = {"requests": len(requetes), "duration_s": next((x["duration"] for x in lignes if x.get("kind") == "end"), None)}
    par_page = defaultdict(list)
    statuts = Counter()
    for r in requetes:
        par_page[r["page"]].append(r["d"])
        statuts[r["status"] or r["err"].split(":")[0]] += 1
    sortie["status"] = dict(statuts)
    sortie["pages"] = {p: {"n": len(d), "median": round(statistics.median(d), 3), "p95": round(centile(d, 0.95), 3),
                           "max": round(max(d), 3)} for p, d in sorted(par_page.items())}
    erreurs = [r for r in requetes if r["status"] >= 500 or r["err"]]
    sortie["n_5xx_or_network"] = len(erreurs)
    sortie["errors_examples"] = erreurs[:20]
    tout = [r["d"] for r in requetes] or [0]
    sortie["all"] = {"median": round(statistics.median(tout), 3), "p95": round(centile(tout, 0.95), 3), "max": round(max(tout), 3),
                     "rps": round(len(requetes) / sortie["duration_s"], 1) if sortie["duration_s"] else None}
    ech = [x for x in lignes if x.get("kind") == "sample"]
    if ech:
        def pic(cle):
            return max((x.get(cle) or 0) for x in ech)

        def moy(cle):
            v = [x.get(cle) or 0 for x in ech]
            return round(sum(v) / len(v), 2)
        sortie["server"] = {"app_cpu_mean": moy("app_cpu"), "app_cpu_max": pic("app_cpu"), "app_rss_mb_max": pic("app_rss_mb"),
                            "db_cpu_mean": moy("db_cpu"), "db_cpu_max": pic("db_cpu"), "db_rss_mb_max": pic("db_rss_mb"),
                            "db_connections_max": pic("db_connections"), "db_waiting_lock_max": pic("db_waiting_lock"),
                            "load1_max": pic("load1"), "app_processes_max": pic("app_processes")}
    sortie["exports"] = [x for x in lignes if x.get("kind") == "export"]
    sortie["backup"] = [x for x in lignes if x.get("kind") == "backup"]
    sortie["imports"] = [{k: v for k, v in x.items() if k != "values"} for x in lignes if x.get("kind") == "import"]
    enreg = [x for x in lignes if x.get("kind") == "save"]
    sortie["saves"] = dict(Counter(f"{x['step']}:{x['outcome']}" for x in enreg))
    sortie["validated"] = sum(1 for x in enreg if x.get("validated"))
    sortie["refusal_reasons"] = Counter(f"{x['step']}:{x['outcome']}: {(x.get('detail') or '')[:90]}" for x in enreg
                                        if x["outcome"] != "ok").most_common(12)
    meme_org = [r["d"] for r in requetes if r["page"] in ("autosave_draft", "panel_validate", "panel_save")]
    sortie["save_times"] = {
        "all_saves": {"median": round(statistics.median(meme_org), 3), "p95": round(centile(meme_org, 0.95), 3)} if meme_org else {},
    }
    if args.server_log and Path(args.server_log).exists():
        texte = Path(args.server_log).read_text(encoding="utf-8", errors="replace")
        sortie["server_log"] = {k: texte.count(m) for k, m in (
            ("database_is_locked", "database is locked"), ("tracebacks", "Traceback (most recent call last)"),
            ("worker_timeouts", "WORKER TIMEOUT"), ("deadlocks", "deadlock detected"), ("killed", "was sent SIGKILL"),
            ("serialization", "could not serialize"), ("too_many_connections", "too many clients"))}
        sortie["server_log_errors"] = sorted({ligne.strip()[:240] for ligne in texte.splitlines()
                                              if re.search(r"Error|Exception|WORKER TIMEOUT", ligne)
                                              and "Traceback" not in ligne})[:20]
    if args.postgres_log and Path(args.postgres_log).exists() and debut_mur:
        import datetime

        limite = datetime.datetime.fromtimestamp(debut_mur).strftime("%Y-%m-%d %H:%M:%S")
        base = urllib.parse.urlparse(os.environ.get("DATABASE_URL", "")).path.lstrip("/")
        # lignes de cette base seulement (préfixe « utilisateur@base » ; le serveur peut servir d'autres bases)
        pg = [x for x in Path(args.postgres_log).read_text(encoding="utf-8", errors="replace").splitlines()
              if x[:19] >= limite and (not base or f"@{base} " in x)]
        sortie["postgres_log"] = {"deadlocks": sum("deadlock detected" in x for x in pg),
                                  "lock_timeouts": sum("lock timeout" in x for x in pg),
                                  "errors": sum(" ERROR: " in x for x in pg), "fatal": sum(" FATAL: " in x for x in pg),
                                  "examples": [x[:240] for x in pg if " ERROR: " in x or " FATAL: " in x][:10]}

    # ---- base : saisies perdues ou en double, valeurs finales, totaux
    django_pret()
    import datetime

    from django.db import transaction
    from django.utils import timezone

    from collecte.calcul import recalculer
    from collecte.models import Campagne, Journal, Reponse
    from referentiel.models import Utilisateur

    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    campagnes = {c.pk: c for c in Campagne.objects.select_related("periode").filter(pk__in=[plan["campagne"], plan.get("mois")])}
    ids = dict(Utilisateur.objects.values_list("username", "pk"))
    ecritures = [x for x in enreg if x["saved"]]
    for imp in (x for x in lignes if x.get("kind") == "import" and x["outcome"] == "ok"):
        for code, org, v in imp["values"]:
            ecritures.append({"u": imp["u"], "campagne": imp["campagne"], "kpi": code, "org": org, "value": v, "import": True,
                              "t0": imp["t0"], "t1": imp["t1"]})
    codes = {x["kpi"] for x in ecritures}
    periode_de = {pk: c.periode_id for pk, c in campagnes.items()}
    reponses = {}
    for r in Reponse.objects.filter(periode_id__in=set(periode_de.values()), kpi_id__in=codes):
        reponses[(r.periode_id, r.kpi_id, r.organisation_id)] = r
    depuis = timezone.make_aware(datetime.datetime.fromtimestamp(debut_mur - 5)) if debut_mur else None
    traces = defaultdict(Counter)  # id de la réponse → (utilisateur, valeur) → nombre de lignes du journal
    suivies = {str(r.pk) for r in reponses.values()}
    qs = Journal.objects.filter(objet="Reponse", champ="valeur")  # filtrées ici : SQLite limite le nombre de paramètres
    if depuis:
        qs = qs.filter(date__gte=depuis)
    for j in qs.values("objet_id", "utilisateur_id", "apres").iterator():
        if j["objet_id"] in suivies and j["apres"] not in ("", "None", None):
            traces[j["objet_id"]][(j["utilisateur_id"], Decimal(j["apres"]))] += 1
    perdues, doubles, finales_fausses, chevauchements = [], [], [], 0
    par_case = defaultdict(list)
    for x in ecritures:
        cle = (periode_de.get(x["campagne"]), x["kpi"], x["org"])
        par_case[cle].append(x)
    for cle, essais in par_case.items():
        r = reponses.get(cle)
        if r is None:
            perdues += essais
            continue
        t = traces.get(str(r.pk), Counter())
        vus = Counter((ids.get(x["u"]), Decimal(str(x["value"]))) for x in essais)
        for (u, v), n in vus.items():
            trouve = t.get((u, v), 0)
            if trouve == 0:
                perdues.append({"case": cle, "user": u, "value": str(v)})
            elif trouve > n:
                doubles.append({"case": cle, "user": u, "value": str(v), "log_lines": trouve, "acknowledged": n})
        ok = sorted(essais, key=lambda x: x["t1"])
        derniere = ok[-1]
        possibles = [x for x in ok if x["t1"] >= derniere["t0"]]  # requêtes qui se chevauchent : ordre serveur inconnu
        chevauchements += len(possibles) > 1
        if not any(r.valeur == Decimal(str(x["value"])) for x in possibles):
            finales_fausses.append({"case": cle, "db": str(r.valeur), "db_user": r.saisi_par_id,
                                    "expected": [(x["u"], x["value"], x["t1"]) for x in possibles]})
    # deux enregistrements explicites acceptés à partir de la même version : le second a écrasé le premier sans le voir.
    # Un enregistrement de la valeur déjà en place ne change rien, ni la version : il ne compte pas
    precedente, changeants = {}, []
    for x in sorted((x for x in enreg if x["saved"]), key=lambda x: x["t1"]):
        cle = (x["campagne"], x["kpi"], x["org"])
        if precedente.get(cle) != x["value"]:
            changeants.append(x)
        precedente[cle] = x["value"]
    meme_version = Counter((x["campagne"], x["kpi"], x["org"], x["version"]) for x in changeants
                           if x.get("version") and x["step"] != "autosave_draft")
    sortie["accepted_on_stale_version"] = sum(n - 1 for n in meme_version.values() if n > 1)
    sortie["acknowledged_writes"] = len(ecritures)
    sortie["lost_writes"] = len(perdues)
    sortie["lost_examples"] = perdues[:10]
    sortie["doubled_log_lines"] = len(doubles)
    sortie["doubled_examples"] = doubles[:10]
    sortie["wrong_final_values"] = len(finales_fausses)
    sortie["wrong_final_examples"] = finales_fausses[:10]
    sortie["overlapping_final_writes"] = chevauchements
    # doublons dans la base : contraintes uniques, et lignes de réponse multiples par case (aucune attendue)
    from django.db.models import Count

    sortie["duplicate_answers"] = Reponse.objects.values("periode_id", "kpi_id", "organisation_id").annotate(
        n=Count("id")).filter(n__gt=1).count()
    # totaux : recalcul complet de chaque campagne ouverte, dans une transaction annulée, comparé aux valeurs stockées
    champs = ("valeur", "texte", "non_applicable", "statut", "origine")
    periodes = {c.periode_id for c in campagnes.values()}
    for c in campagnes.values():  # le cumul annuel des mois est écrit dans les périodes plus longues qui les contiennent
        periodes |= set(type(c.periode).objects.filter(debut__lte=c.periode.debut, fin__gte=c.periode.fin).values_list("pk", flat=True))

    def calculees():
        return {(r["periode_id"], r["kpi_id"], r["organisation_id"]): tuple(r[c] for c in champs)
                for r in Reponse.objects.filter(periode_id__in=periodes, origine__in=["calcul", "agregation", "cumul"])
                .values("periode_id", "kpi_id", "organisation_id", *champs)}

    t = time.time()
    avant = calculees()
    with transaction.atomic():
        for c in sorted(campagnes.values(), key=lambda c: c.periode.fin - c.periode.debut):
            recalculer(c)
        apres = calculees()
        transaction.set_rollback(True)
    ecarts = [k for k in set(avant) | set(apres) if avant.get(k) != apres.get(k)]
    sortie["recalculation_seconds"] = round(time.time() - t, 1)
    sortie["calculated_cells"] = len(avant)
    sortie["totals_differences"] = len(ecarts)
    sortie["totals_differences_examples"] = [(k, avant.get(k), apres.get(k)) for k in ecarts[:10]]
    texte = json.dumps(sortie, indent=1, default=str, ensure_ascii=False)
    if args.json:
        Path(args.json).write_text(texte, encoding="utf-8")
    afficher(sortie)
    probleme = sortie["n_5xx_or_network"] or sortie["lost_writes"] or sortie["doubled_log_lines"] or sortie["wrong_final_values"] \
        or sortie["totals_differences"] or sortie["accepted_on_stale_version"] or sortie["duplicate_answers"] \
        or (sortie.get("server_log") or {}).get("database_is_locked") or (sortie.get("postgres_log") or {}).get("deadlocks")
    sys.exit(1 if probleme else 0)


def afficher(s):
    print(f"Requests: {s['requests']} in {s['duration_s']} s ({s['all']['rps']} req/s); status {s['status']}")
    print(f"All pages: median {s['all']['median']} s, p95 {s['all']['p95']} s, max {s['all']['max']} s")
    print(f"{'page':32} {'n':>6} {'median':>8} {'p95':>8} {'max':>8}")
    for p, v in s["pages"].items():
        print(f"{p:32} {v['n']:>6} {v['median']:>8} {v['p95']:>8} {v['max']:>8}")
    print(f"Saves: {s['saves']}; validated: {s['validated']}")
    for motif, n in s["refusal_reasons"]:
        print(f"  {n:>5} x {motif}")
    print(f"5xx / network errors: {s['n_5xx_or_network']}; server log: {s.get('server_log')}; PostgreSQL log: "
          f"{ {k: v for k, v in (s.get('postgres_log') or {}).items() if k != 'examples'} }")
    print(f"Server: {s.get('server')}")
    for x in s["exports"]:
        print(f"Export {x.get('modele')} by {x['u']}: {x.get('mode')} {x.get('status')} in {x.get('seconds')} s")
    for x in s["backup"]:
        print(f"Backup by {x['u']}: status {x['status']} in {round(x['t1'] - x['t0'], 1)} s")
    for x in s["imports"]:
        print(f"Import by {x['u']}: {x['outcome']}, {x['lines']} lines in {round(x['t1'] - x['t0'], 1)} s (confirmation)")
    print(f"Acknowledged writes: {s['acknowledged_writes']}; lost: {s['lost_writes']}; doubled in the History: "
          f"{s['doubled_log_lines']}; wrong final value: {s['wrong_final_values']} (overlaps: {s['overlapping_final_writes']}); "
          f"accepted on a stale version: {s['accepted_on_stale_version']}; duplicate answers: {s['duplicate_answers']}")
    print(f"Totals: {s['calculated_cells']} calculated cells, {s['totals_differences']} difference(s) after a full "
          f"recalculation ({s['recalculation_seconds']} s)")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sous = ap.add_subparsers(dest="commande", required=True)
    a = sous.add_parser("prepare")
    a.add_argument("--plan", required=True)
    a.add_argument("--contributors", type=int, default=38)
    a.add_argument("--validators", type=int, default=5)
    a.add_argument("--admins", type=int, default=3)
    a.add_argument("--readers", type=int, default=4)
    a.add_argument("--cells", type=int, default=12, help="cells of the open campaign per contributor")
    b = sous.add_parser("run")
    b.add_argument("--plan", required=True)
    b.add_argument("--url", required=True)
    b.add_argument("--log", required=True)
    b.add_argument("--duration", type=float, default=300, help="seconds of work after the logins")
    b.add_argument("--ramp", type=float, default=20, help="logins spread over this many seconds")
    b.add_argument("--think", type=float, default=4.0, help="think time between two actions (seconds, x0.5 to x1.5)")
    b.add_argument("--timeout", type=float, default=180.0, help="seconds before a request counts as timed out")
    b.add_argument("--export-wait", type=float, default=300.0, help="seconds to wait for a background export")
    b.add_argument("--server-pid", help="process of the server (gunicorn master): its children are sampled too")
    b.add_argument("--watch-pid", action="append", default=[], help="another process to sample (scheduler of the background tasks)")
    b.add_argument("--sample", type=float, default=2.0, help="seconds between two samples of the server")
    b.add_argument("--run", type=int, default=1, choices=range(1, 8), help="number of this run on the same database (1 to 7): "
                   "the values written differ from one run to the next")
    c = sous.add_parser("check")
    c.add_argument("--plan", required=True)
    c.add_argument("--log", required=True)
    c.add_argument("--server-log")
    c.add_argument("--postgres-log")
    c.add_argument("--json")
    args = ap.parse_args()
    {"prepare": preparer, "run": lancer, "check": controler}[args.commande](args)


if __name__ == "__main__":
    main()
