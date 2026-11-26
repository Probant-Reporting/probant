"""Full rehearsal of the update of an existing installation (version in production → version to install).

    python3 qa/migration_rehearsal.py --base /path/copy-of-production.sqlite3 [--media /path/media] \
        [--registry /path/shared.sqlite3] [--before /path/checkout-main] [--report rehearsal.md]
    python3 qa/migration_rehearsal.py --postgres postgres://user:password@host:5432/postgres --base SOURCE_DATABASE \
        --before /path/checkout-of-the-old-version [--media /path/media]

Options added for the check "update from every published version" (qa/update_from_published.py, which builds the
database with the code of each published version): ``--before-python`` (interpreter of the old version, when its
packages differ), ``--old-archive`` (an archive made by the old version: restored by the new version into an empty
database, the result must equal the database updated in place; PostgreSQL: an archive restores only with the version
that made it, so when the update applied migrations the documented refusal is the expected result), ``--health-port`` (starts the tool on the updated
database and checks ``/sante/``, then the sign-in with the demo accounts).

PostgreSQL (``--postgres``): ``--base`` is the name of a database of that server built with the old version; it is
copied (CREATE DATABASE … TEMPLATE …, never modified), and the restore goes into a new empty database. The user of the
URL must be allowed to create databases.

Everything is done on copies, in a temporary folder (deleted at the end, unless --keep); the file given is never
modified. Steps:
  1. copy of the database (and of the evidence files); checkout of main (git worktree) if --before is not given;
  2. "before" extraction with the code of main: KPI records, organisations, accounts, assignments, campaigns,
     answers, evidence, log, "Database" and "Cells still to fill in" exports; SQL fingerprint table by table;
  3. update with the new version, exactly as when the Docker image starts (manage.py startup: automatic backup
     before migrating, then migrations);
  4. "after" extraction with the new version, comparisons;
  5. backup of the migrated database, restore into an empty database, extraction and comparison;
  6. going back to the old version (docs/installation.md, "Going back to the previous version"): with the code of
     the old version, restore of the "before-update" archive made by step 3 into the updated database; PostgreSQL:
     "restore --rebuild" if the old version has it, otherwise the database changes of the update are first undone
     with the new version ("migrate <application> <target>"); extraction with the old version, compared with step 2;
  7. Markdown report: figures only (no name, e-mail, value or KPI identifier). Any differences are detailed on
     screen only, for a local investigation.
Exit code: 0 if everything is identical, 1 otherwise.

Memory: each extraction is written to disk one key per file (lists as JSON lines) by a child process, which also
computes a fingerprint of each key; the comparison of step 4 reads one key at a time and releases it; steps 5 and 6
compare the fingerprints, key by key. The process never holds a whole extraction in memory.
"""
# Messages et rapport en anglais ; commentaires et identifiants en français.
import argparse
import datetime
import hashlib
import json
import multiprocessing
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
EXTRAIRE = RACINE / "qa" / "extract.py"
COLONNES_VALEUR = ["Exercice", "ID KPI", "Indicateur", "Thème", "Sous-thème", "Type de KPI", "Unité", "Organisation", "Niveau",
                   "Pays", "Entité", "Site", "Valeur", "N/A", "Statut", "Origine", "Commentaire", "Saisi par", "Mis à jour le",
                   "Validé par", "Validé le", "Preuves"]
ECARTS = []  # détails pour l'écran seulement (en anglais)
CLE_SECRETE = "repetition-" + "x" * 40  # secret de l'installation, le même avant et après (les archives sont signées avec lui)
PYTHON_AVANT = sys.executable  # interpréteur du code de l'ancienne version (``--before-python``)
ATTENDUS = {  # tables dont le contenu change par construction
    "auth_permission": "Django technical: permissions of the new models (expected)",
    "django_content_type": "Django technical: new models (expected)",
    "collecte_reglageexport": "saved exports converted to the new format (expected)",
}
# Changements voulus, faits par une migration : ils ne comptent comme attendus que si cette migration passe pendant la
# répétition (absente de la base fournie). Le texte « avant » est alors transformé comme le fait la migration, puis la
# comparaison vérifie qu'elle n'a rien changé d'autre.
# Aucun aujourd'hui : referentiel/0014 ne renomme plus rien désormais (migration vidée).
RENOMMAGES_KPI = []  # (application, migration, champ de la fiche KPI, texte avant, texte après, explication pour le rapport)
# (referentiel/0016) : une unité « nombre entier » n'a pas de décimale ; dans une somme, une source
# N/A compte comme 0, d'où un recalcul unique des campagnes non clôturées au démarrage (les périodes clôturées restent figées).
DECISIONS = ("referentiel", "0016_na_compte_zero_entiers")
# collecte/0045 : cumul des mois seulement sur les mois où l'organisation est ouverte et
# le KPI demandé ; [X@N-1] d'une organisation pas ouverte : source manquante. Recalcul des campagnes non clôturées au
# démarrage : leurs cases calculées peuvent changer de valeur et passer d'« incomplet » à « calculé » ou l'inverse ; les
# périodes clôturées restent figées (``recalculees``).
RECALCUL_CUMULS = ("collecte", "0045_recalcul_cumuls_mois_ouverts")
COLONNES_ATTENDUES = {  # (table, colonne) : (application, migration, explication)
    ("parametres_instance", "palette"): ("parametres", "0009_palettes_enregistrees",
                                         "former provided palette turned into a saved palette (expected)"),
    ("parametres_unite", "famille"): ("parametres", "0010_thematique_pourcentage",
                                      "theme \"Percentage\" merged into \"Percentage and ratios\" (expected)"),
    ("referentiel_kpi", "decimales"): (*DECISIONS, "0 decimals for a \"whole number\" unit (checked record by record above)"),
    ("collecte_reponse", "valeur"): (*DECISIONS, "calculated cells of the current campaigns recalculated (checked row by row)"),
    ("collecte_reponse", "non_applicable"): (*DECISIONS, "calculated cells of the current campaigns recalculated (checked row by row)"),
    ("collecte_reponse", "message_calcul"): (*DECISIONS, "calculation details redone by the recalculation"),
    ("collecte_alerte", "message"): (*DECISIONS, "alerts rechecked after the recalculation (statuses and justifications unchanged)"),
    ("collecte_alerte", "valeur"): (*DECISIONS, "alerts rechecked after the recalculation (statuses and justifications unchanged)"),
    ("collecte_alerte", "reference"): (*DECISIONS, "alerts rechecked after the recalculation (statuses and justifications unchanged)"),
    ("collecte_alerte", "date_maj"): (*DECISIONS, "alerts rechecked after the recalculation (statuses and justifications unchanged)"),
    # : motif des alertes « calcul impossible » relu en clés de libellés, empreinte sans langue
    ("collecte_alerte", "empreinte"): ("collecte", "0040_alertes_calcul_recomposables",
                                       "\"calculation impossible\" alerts: fingerprint without language (statuses unchanged)"),
    ("collecte_alerte", "textes"): ("collecte", "0040_alertes_calcul_recomposables",
                                    "\"calculation impossible\" alerts: reason stored as label keys (statuses unchanged)"),
}
# Rangement des fichiers (collecte/0029 et 0030) : preuves et logo déplacés, leur nom enregistré suit (le
# contenu de chaque fichier est comparé à part, « Evidence (files) »)
RANGEMENT = ("collecte", "0029_rangement_fichiers")
COLONNES_ATTENDUES[("collecte_preuve", "fichier")] = (*RANGEMENT, "evidence files moved to evidence/<period>/<organisation>/<KPI>/ (expected; files compared above)")
COLONNES_ATTENDUES[("parametres_instance", "logo")] = (*RANGEMENT, "logo moved to settings/logo/ (expected)")
# (collecte/0027) : un KPI qui a des réponses décimales avec une unité « nombre entier » passe sur une
# copie non entière de son unité (même symbole) ; une unité est ajoutée et le changement est écrit dans le journal.
COMPTAGES = ("collecte", "0027_comptages_decimaux")
for _col in ("code", "symbole", "libelle", "entier", "decimales", "famille", "ordre", "traductions"):
    COLONNES_ATTENDUES[("parametres_unite", _col)] = (*COMPTAGES, "non-integer copy of a unit added (expected)")
COLONNES_COMPTAGES = {  # colonnes déjà attendues pour une autre migration : attendues aussi pour celle-ci
    ("referentiel_kpi", "unite"): "KPIs with decimal values moved to the copy (checked record by record)",
    ("referentiel_kpi", "decimales"): "decimals of these KPIs (1 or 2, checked record by record)",
}
for _col in ("id", "date", "utilisateur_id", "action", "objet", "objet_id", "champ", "avant", "apres"):
    COLONNES_ATTENDUES.setdefault(("collecte_journal", _col), (*COMPTAGES, "unit change written to the log (expected)"))
# (collecte/0035) : un mois ne calcule plus que les KPI du périmètre de ses campagnes ; la
# migration pose le recalcul des campagnes non clôturées, qui retire les cases sans objet des autres KPI. Seules sont
# attendues les cases supprimées qui étaient vides, calculées, « incomplet », d'un mois à campagne non clôturée, d'un KPI
# hors de son périmètre, sans commentaire, sans saisie ni validation, sans preuve (``cases_hors_perimetre``,
# ``ids_hors_perimetre``) ; toute autre ligne supprimée reste un écart. Le même recalcul revoit les alertes.
# (collecte/0039) : même règle pour les années, semestres et trimestres, même ménage
# des campagnes non clôturées (exercices clos : aucune ligne retirée) ; attendu si l'une des deux migrations passe.
MENAGE = ("collecte", "0035_menage_mois_hors_perimetre")
MENAGE_PERIODES = ("collecte", "0039_menage_periodes_hors_perimetre")


def menage_voulu(deja):
    """Vrai si une migration de ménage (collecte/0035 ou collecte/0039) passe pendant la répétition."""
    return MENAGE not in deja or MENAGE_PERIODES not in deja

# Réparation (collecte/0044, ``collecte.unites_mal_rapprochees``) : unité d'un KPI d'un modèle de la
# bibliothèque mal rangée à son installation (« €/h » rangée en « h ») corrigée, une ligne au journal par KPI, une unité
# ajoutée si elle manque ; aucune valeur. Attendu seulement fiche par fiche (``unites_corrigees``) : le KPI est celui
# d'un modèle du dépôt, l'unité d'après est celle que sa définition demande, l'unité d'avant est celle que l'ancien
# rapprochement (forme sans casse ni symboles) pouvait donner ; tout autre changement d'unité reste un écart.
UNITES = ("collecte", "0044_corriger_unites_mal_rapprochees")
COLONNES_UNITES = {("referentiel_kpi", "unite"): "unit of the KPIs put in the wrong unit at a template installation corrected "
                                                  "(checked record by record)"}
for _col in ("code", "symbole", "libelle", "entier", "decimales", "famille", "ordre", "traductions"):
    COLONNES_UNITES[("parametres_unite", _col)] = "unit asked by the template added (expected)"
for _col in ("id", "date", "utilisateur_id", "action", "objet", "objet_id", "champ", "avant", "apres"):
    COLONNES_UNITES[("collecte_journal", _col)] = "unit correction written to the log (expected)"


def _sans_symboles(texte):
    """Forme de l'ancien rapprochement (``collecte.fichiers.normaliser``) : sans accents, casse, ponctuation ni symboles."""
    import re
    import unicodedata

    texte = unicodedata.normalize("NFKD", str(texte or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", texte.lower())


def unites_des_modeles():
    """{code d'un KPI : [(code de l'unité voulue, symboles de l'unité voulue)]} des modèles de la bibliothèque du dépôt."""
    sortie = {}
    for chemin in sorted((RACINE / "referentiel" / "bibliotheque").glob("*.json")):
        p = json.loads(chemin.read_text(encoding="utf-8"))
        unites = {u["code"]: u for u in p.get("unites", [])}
        for k in p.get("kpis", []):
            u = unites.get(k.get("unite") or "")
            if u:
                sortie.setdefault(k["code"], []).append((u["code"], [s for s in (u.get("symbole") or {}).values() if s]))
    return sortie


def unites_corrigees(a, b, deja):
    """Fiches « avant » dont l'unité a été corrigée par collecte/0044 (règles ci-dessus) : l'unité d'après y est reprise.
    Renvoie les codes des KPI concernés."""
    if UNITES in deja:
        return set()
    modeles, faits = unites_des_modeles(), set()
    for code, f in a.items():
        g = b.get(code) or {}
        avant, apres = f.get("unite"), g.get("unite")
        if not avant or not apres or avant == apres:
            continue
        for voulu, symboles in modeles.get(code, []):
            bonne = apres == voulu or str(apres).startswith(voulu + "~")
            fautive = _sans_symboles(avant) in ({_sans_symboles(s) for s in symboles} or {_sans_symboles(voulu)})
            if bonne and fautive and avant not in symboles:
                f["unite"], f["unite_entiere"] = apres, g.get("unite_entiere")
                faits.add(code)
                break
    return faits


ORIGINES_CALCULEES = ("calcul", "agregation", "cumul")
COLONNES_MENAGE = {("collecte_alerte", c): "alerts rechecked by the recalculation of the current campaigns (collecte/0035, 0039; "
                   "statuses and justifications unchanged)" for c in ("message", "valeur", "reference", "date_maj")}


def etape(texte):
    print(f"\n== {texte}", flush=True)


def lancer(commande, cwd, env, sortie=None):
    debut = time.monotonic()
    r = subprocess.run(commande, cwd=cwd, env={**os.environ, **env}, capture_output=True, text=True)
    if r.returncode:
        print(r.stdout[-3000:], r.stderr[-6000:])
        raise SystemExit(f"Failed: {' '.join(map(str, commande))}")
    if sortie:
        print(r.stdout.strip()[-1500:])
    return time.monotonic() - debut


# ---------------------------------------------------------------- PostgreSQL (--postgres)
def url_base(url, nom):
    """Même serveur et même compte que ``url``, base ``nom``."""
    from urllib.parse import urlparse, urlunparse

    return urlunparse(urlparse(url)._replace(path="/" + nom))


def pg_admin(url, *ordres):
    import psycopg

    with psycopg.connect(url, autocommit=True) as c:
        for o in ordres:
            c.execute(o)


def empreinte_pg(url, exclure=None):
    """Comme ``empreinte_sql`` pour une base PostgreSQL (schéma public : la base de l'espace principal)."""
    import psycopg

    sortie = {}
    exclure = exclure or {}
    with psycopg.connect(url) as c:
        tables = [r[0] for r in c.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' "
                                          "AND table_type='BASE TABLE' ORDER BY table_name")]
        for tb in tables:
            colonnes = [r[0] for r in c.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='public' "
                                                "AND table_name=%s ORDER BY ordinal_position", (tb,))]
            ecartes = exclure.get(tb, set())
            par_colonne = {}
            for col in colonnes:
                lignes = c.execute(f'SELECT id::text, "{col}"::text FROM public."{tb}"' if ecartes else
                                   f'SELECT NULL, "{col}"::text FROM public."{tb}"')
                valeurs = sorted(repr(v) for i, v in lignes if i is None or int(i) not in ecartes)
                par_colonne[col] = hashlib.sha256("\n".join(valeurs).encode()).hexdigest()
            n = c.execute(f'SELECT COUNT(*) FROM public."{tb}"').fetchone()[0] - len(ecartes)
            sortie[tb] = {"lignes": n, "colonnes": par_colonne}
    return sortie


def lignes_reponses_pg(url):
    import psycopg

    with psycopg.connect(url) as c:
        cur = c.execute("SELECT * FROM public.collecte_reponse")
        noms = [d.name for d in cur.description]
        lignes = [dict(zip(noms, r)) for r in cur]
        preuves = {r[0] for r in c.execute("SELECT reponse_id FROM public.collecte_preuve")}
    return lignes, preuves


def lignes_reponses_sqlite(chemin):
    c = sqlite3.connect(f"file:{chemin}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    try:
        lignes = [dict(r) for r in c.execute("SELECT * FROM collecte_reponse")]
        preuves = {r[0] for r in c.execute("SELECT reponse_id FROM collecte_preuve")}
    finally:
        c.close()
    return lignes, preuves


def reponses_sqlite(chemin):
    """Lignes de collecte_reponse en flux (dictionnaires colonne → valeur), une à la fois."""
    c = sqlite3.connect(f"file:{chemin}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    try:
        for r in c.execute("SELECT * FROM collecte_reponse"):
            yield dict(r)
    finally:
        c.close()


def _ensemble_sqlite(chemin, requete):
    c = sqlite3.connect(f"file:{chemin}?mode=ro", uri=True)
    try:
        return {r[0] for r in c.execute(requete)}
    finally:
        c.close()


def preuves_sqlite(chemin):
    return _ensemble_sqlite(chemin, "SELECT reponse_id FROM collecte_preuve")


def ids_reponses_sqlite(chemin):
    return _ensemble_sqlite(chemin, "SELECT id FROM collecte_reponse")


def vide(v):
    return v is None or v == ""


def ids_hors_perimetre(avant, preuves, ids_apres, perimetres):
    """Numéros des lignes de collecte_reponse supprimées par le ménage voulu de collecte/0035 et 0039 (voir ``MENAGE``) :
    absentes après, vides, calculées, « incomplet », d'une période listée dans ``perimetres`` ({"#<numéro de période>":
    [KPI calculés]}, période à campagne non clôturée, de tout type) pour un KPI qui n'y figure pas, sans commentaire,
    saisie, validation ni preuve. ``avant`` : lignes (dictionnaires colonne → valeur) de la base d'avant."""
    sortie = set()
    for r in avant:
        codes = perimetres.get(f"#{r['periode_id']}")
        if (r["id"] in ids_apres or codes is None or r["kpi_id"] in codes or r["id"] in preuves
                or r["statut"] != "incomplet" or r["origine"] not in ORIGINES_CALCULEES or r["valeur"] is not None
                or r["non_applicable"] not in (False, 0) or not vide(r.get("texte")) or not vide(r.get("commentaire"))
                or r.get("saisi_par_id") is not None or r.get("valide_par_id") is not None):
            continue
        sortie.add(r["id"])
    return sortie


def cases_hors_perimetre(a, b):
    """Même ménage dans les extractions : retire de l'état « avant » les réponses absentes après qui en relèvent (voir
    ``ids_hors_perimetre`` ; ``b["perimetres_mois"]`` par libellé de période). Renvoie le nombre de cases retirées."""
    perimetres = b.get("perimetres_mois") or {}
    apres = {tuple(r[:3]) for r in b["reponses"]}
    avec_preuve = {(p[0], p[1]) for p in a.get("preuves", [])}
    gardees, n = [], 0
    for r in a["reponses"]:
        # colonnes : période, KPI, organisation, valeur, texte, N/A, commentaire, statut, origine, saisi par, validé par…
        codes = perimetres.get(r[0])
        if (tuple(r[:3]) not in apres and codes is not None and r[1] not in codes and (r[1], r[2]) not in avec_preuve
                and r[3] == "" and r[4] == "" and r[5] is False and r[6] == "" and r[7] == "incomplet"
                and r[8] in ORIGINES_CALCULEES and r[9] == "" and r[10] == ""):
            n += 1
            continue
        gardees.append(r)
    a["reponses"] = gardees
    return n


def migrations_pg(url):
    import psycopg

    try:
        with psycopg.connect(url) as c:
            return set(c.execute("SELECT app, name FROM public.django_migrations"))
    except psycopg.Error:
        return set()


# ---------------------------------------------------------------- retour à l'ancienne version (étape 6)
def cibles_retour(migrations_archive, migrations_base):
    """Commandes « migrate <application> <cible> » qui ramènent la base aux migrations de l'archive : pour chaque
    application qui a dans la base une migration absente de l'archive, la dernière migration de l'archive pour cette
    application (« zero » si elle n'y figure pas). Les noms des migrations commencent par leur numéro : l'ordre des noms
    est l'ordre des migrations d'une même application."""
    archive = {tuple(m) for m in migrations_archive}
    cibles = []
    for app in sorted({a for a, n in migrations_base if (a, n) not in archive}):
        siennes = sorted(n for a, n in archive if a == app)
        cibles.append((app, siennes[-1] if siennes else "zero"))
    return cibles


def retour_arriere(avant, env, pg, archive, travail):
    """Étape 6 : retour à l'ancienne version comme le guide l'indique à l'IT. Renvoie (durée, procédure suivie)."""
    import zipfile

    debut = time.monotonic()
    aide = subprocess.run([PYTHON_AVANT, "manage.py", "restore", "--help"], cwd=avant, env={**os.environ, **env},
                          capture_output=True, text=True).stdout
    options = []
    procedure = "restore"
    if pg:
        if "--rebuild" in aide:
            options, procedure = ["--rebuild"], "restore --rebuild"
        else:  # ancienne version sans --rebuild : la nouvelle défait d'abord ses migrations (tous les espaces)
            with zipfile.ZipFile(archive) as z:
                d = json.loads(z.read("backup.json"))
            for app, cible in cibles_retour(d["migrations"], migrations_pg(env["DATABASE_URL"])):
                lancer([sys.executable, "manage.py", "migrate", app, cible], RACINE, env)
            procedure = "migrate back (new version), then restore"
    lancer([PYTHON_AVANT, "manage.py", "restore", archive.name, "--yes", *options], avant, env, True)
    lancer([PYTHON_AVANT, str(EXTRAIRE), str(travail / "retour.json")], avant, env)
    return time.monotonic() - debut, procedure


# ---------------------------------------------------------------- empreinte SQL table par table
def empreinte_sql(chemin, exclure=None):
    """Empreinte de chaque colonne de chaque table (valeurs triées) ; ``exclure`` : {table: numéros de lignes écartées}."""
    c = sqlite3.connect(chemin)
    sortie = {}
    exclure = exclure or {}
    for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
        colonnes = [r[1] for r in c.execute(f'PRAGMA table_info("{t}")')]
        ecartes = exclure.get(t, set())
        par_colonne = {}
        for col in colonnes:
            lignes = c.execute(f'SELECT id, "{col}" FROM "{t}"' if ecartes else f'SELECT NULL, "{col}" FROM "{t}"')
            valeurs = sorted(repr(v) for i, v in lignes if i is None or i not in ecartes)
            par_colonne[col] = hashlib.sha256("\n".join(valeurs).encode()).hexdigest()
        sortie[t] = {"lignes": c.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] - len(ecartes), "colonnes": par_colonne}
    c.close()
    return sortie


def migrations_appliquees(chemin):
    """{(application, migration)} déjà passées sur la base fournie (les autres passeront pendant la répétition)."""
    cnx = sqlite3.connect(f"file:{chemin}?mode=ro", uri=True)
    try:
        return set(cnx.execute("SELECT app, name FROM django_migrations"))
    except sqlite3.Error:
        return set()
    finally:
        cnx.close()


def comparer_tables(avant, apres, deja=frozenset(), unites=False):
    """Tables de l'ancienne version : lignes avant / après, colonnes inchangées (contenu identique colonne par colonne).
    Une colonne changée par une migration voulue (COLONNES_ATTENDUES) qui passe pendant la répétition est attendue.
    ``unites`` : des unités de KPI ont été corrigées par collecte/0044, vérifiées fiche par fiche (COLONNES_UNITES)."""
    lignes = []
    for t, a in avant.items():
        if t == "django_migrations":
            continue
        b = apres.get(t)
        if b is None:
            lignes.append((t, a["lignes"], None, len(a["colonnes"]), 0, "table replaced (content taken over elsewhere)"))
            continue
        communes = [c for c in a["colonnes"] if c in b["colonnes"]]
        identiques = sum(a["colonnes"][c] == b["colonnes"][c] for c in communes)
        retirees = len(a["colonnes"]) - len(communes)
        remarque = [f"{retirees} column(s) moved (content compared above)"] if retirees else []
        if identiques < len(communes) and t in ATTENDUS:
            remarque.append(ATTENDUS[t])
        for c in communes:
            if a["colonnes"][c] == b["colonnes"][c] or t in ATTENDUS:
                continue
            voulu = COLONNES_ATTENDUES.get((t, c))
            if (t, c) in COLONNES_COMPTAGES and COMPTAGES not in deja:
                remarque.append(f"{c}: {COLONNES_COMPTAGES[(t, c)]}")
            elif voulu and voulu[:2] not in deja:
                remarque.append(f"{c}: {voulu[2]}")
            elif (t, c) in COLONNES_MENAGE and menage_voulu(deja):
                remarque.append(f"{c}: {COLONNES_MENAGE[(t, c)]}")
            elif (t, c) in COLONNES_UNITES and unites and UNITES not in deja:
                remarque.append(f"{c}: {COLONNES_UNITES[(t, c)]}")
            else:
                ECARTS.append(f"table {t}: column {c} modified")
        lignes.append((t, a["lignes"], b["lignes"], len(communes), identiques, "; ".join(remarque)))
    return lignes


# ---------------------------------------------------------------- extractions sur disque (mémoire)
# Une extraction de la grosse base générée tient plusieurs Go en mémoire : elle est découpée sur disque, une clé par
# fichier, par un processus enfant (qui rend sa mémoire en finissant), et lue clé par clé pendant la comparaison.
# L'empreinte d'une clé remplace la comparaison « a == b » des étapes 5 et 6 : même résultat (dictionnaires comparés
# sans ordre des clés, listes dans l'ordre), un peu plus stricte seulement si un nombre devenait un booléen (1 / True).
def _alimenter(h, v):
    """Écriture canonique de ``v`` dans l'empreinte ``h`` : clés des dictionnaires triées, listes dans l'ordre."""
    if isinstance(v, dict):
        h.update(b"{")
        for k in sorted(v):
            h.update(json.dumps(k, ensure_ascii=False).encode() + b":")
            _alimenter(h, v[k])
            h.update(b",")
        h.update(b"}")
    elif isinstance(v, list):
        h.update(b"[")
        for e in v:
            h.update(json.dumps(e, sort_keys=True, ensure_ascii=False).encode() + b",")
        h.update(b"]")
    else:
        h.update(json.dumps(v, ensure_ascii=False).encode())


def empreinte_valeur(v):
    h = hashlib.sha256()
    _alimenter(h, v)
    return h.hexdigest()


def _ecrire_lignes(chemin, lignes):
    with open(chemin, "w", encoding="utf-8", newline="\n") as f:
        for e in lignes:
            f.write(json.dumps(e, ensure_ascii=False))
            f.write("\n")


def _lire_lignes(chemin):
    with open(chemin, encoding="utf-8", newline="\n") as f:
        return [json.loads(x) for x in f]


def decouper(chemin, dossier=None):
    """Lit l'extraction ``chemin`` ; renvoie {clé : empreinte} dans l'ordre du fichier. Avec ``dossier`` : y écrit chaque
    clé dans son fichier (listes en JSON lignes, chaque export à part) et ``meta.json``."""
    with open(chemin, encoding="utf-8") as f:
        d = json.load(f)
    empreintes = {k: empreinte_valeur(v) for k, v in d.items()}
    if dossier is not None:
        dossier = Path(dossier)
        dossier.mkdir(parents=True, exist_ok=True)
        meta = {"cles": list(d), "listes": [], "exports": []}
        for i, (k, v) in enumerate(d.items()):
            if k == "exports" and isinstance(v, dict):
                meta["exports"] = list(v)
                for j, lignes in enumerate(v.values()):
                    _ecrire_lignes(dossier / f"exports.{j}.jsonl", lignes)
            elif isinstance(v, list):
                meta["listes"].append(k)
                _ecrire_lignes(dossier / f"{i}.jsonl", v)
            else:
                (dossier / f"{i}.json").write_text(json.dumps(v, ensure_ascii=False), encoding="utf-8")
        (dossier / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return empreintes


def dans_un_enfant(fonction, *args):
    """Appelle ``fonction(*args)`` dans un processus enfant (fork) : la mémoire qu'elle prend est rendue en finissant."""
    from concurrent.futures import ProcessPoolExecutor

    if multiprocessing.current_process().daemon:
        # Un processus « démon » (ouvrier des tests en parallèle) n'a pas le droit d'avoir d'enfant : même résultat, sans le gain de mémoire.
        return fonction(*args)
    with ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("fork")) as pool:
        return pool.submit(fonction, *args).result()


class Extraction:
    """Extraction découpée par ``decouper`` : chaque clé est lue à la demande et gardée jusqu'à ``liberer``. Les exports
    sont rendus en {nom : fonction qui lit ses lignes}, lus par ``comparer_export`` l'un après l'autre."""

    def __init__(self, dossier):
        self.dossier = Path(dossier)
        self.meta = json.loads((self.dossier / "meta.json").read_text(encoding="utf-8"))
        self._lues = {}

    def __contains__(self, k):
        return k in self.meta["cles"] or k in self._lues

    def __iter__(self):
        return iter(self.meta["cles"])

    def __getitem__(self, k):
        if k in self._lues:
            return self._lues[k]
        if k not in self.meta["cles"]:
            raise KeyError(k)
        if k == "exports":
            dossier = self.dossier
            v = {n: (lambda j=j: _lire_lignes(dossier / f"exports.{j}.jsonl")) for j, n in enumerate(self.meta["exports"])}
        elif k in self.meta["listes"]:
            v = _lire_lignes(self.dossier / f"{self.meta['cles'].index(k)}.jsonl")
        else:
            v = json.loads((self.dossier / f"{self.meta['cles'].index(k)}.json").read_text(encoding="utf-8"))
        self._lues[k] = v
        return v

    def __setitem__(self, k, v):
        self._lues[k] = v

    def get(self, k, defaut=None):
        return self[k] if k in self else defaut

    def liberer(self, k):
        self._lues.pop(k, None)


def sur_disque(chemin, dossier, garder=False):
    """Découpe l'extraction ``chemin`` dans ``dossier`` (ou calcule seulement ses empreintes si ``dossier`` est None) dans
    un processus enfant ; supprime ensuite le fichier, sauf ``garder``. Renvoie {clé : empreinte}."""
    empreintes = dans_un_enfant(decouper, str(chemin), None if dossier is None else str(dossier))
    if not garder:
        Path(chemin).unlink()
    return empreintes


def _liberer(extraction, *cles):
    """Rend la mémoire des clés d'une extraction découpée (sans effet sur un dictionnaire ordinaire)."""
    if isinstance(extraction, Extraction):
        for k in cles:
            extraction.liberer(k)


# ---------------------------------------------------------------- comparaisons des extractions
def renommer_kpis(a, deja):
    """Applique aux fiches « avant » les renommages voulus des migrations qui passent pendant la répétition.
    Renvoie {explication: nombre de fiches concernées}."""
    faits = Counter()
    for app, migration, champ, ancien, nouveau, explication in RENOMMAGES_KPI:
        if (app, migration) in deja:
            continue
        for f in a.values():
            v = f.get(champ)
            if isinstance(v, str) and ancien in v:
                f[champ] = v.replace(ancien, nouveau)
                faits[f"{explication} ({app}/{migration})"] += 1
    return dict(faits)


def decimales_entieres(a, b, deja):
    """Un KPI dont l'unité est « nombre entier » passe à 0 décimale (referentiel/0016)."""
    if DECISIONS in deja:
        return 0
    n = 0
    for code, f in a.items():
        g = b.get(code) or {}
        if g.get("unite_entiere") and g.get("decimales") == 0 and f.get("decimales") not in (0, None):
            f["decimales"] = 0
            n += 1
    return n


def comptages_decimaux(a, b, deja):
    """(collecte/0027) : un KPI à valeurs décimales et à unité entière passe sur une copie non
    entière (même symbole, au moins 1 décimale). Applique ce changement à la fiche « avant » ; renvoie le nombre de KPI."""
    if COMPTAGES in deja:
        return 0
    n = 0
    for code, f in a.items():
        g = b.get(code) or {}
        if f.get("unite_entiere") and not g.get("unite_entiere") and str(g.get("unite") or "").startswith(str(f.get("unite") or "") + "_decimal"):
            f["unite"], f["unite_entiere"] = g.get("unite"), False
            if g.get("decimales") in (1, 2):
                f["decimales"] = g["decimales"]
            n += 1
    return n


def recalculees(a, b, deja):
    """Cases calculées des campagnes non clôturées recalculées au démarrage (referentiel/0016 : N/A compté 0 dans une
    somme) : seules leur valeur et leur N/A peuvent changer. Les remplace dans l'état « avant » et renvoie leurs clés
    {(période, KPI, organisation)}. Une case d'une période clôturée, ou qui change autrement, reste un écart.
     (collecte/0045, cumul des mois et [X@N-1] d'une organisation pas ouverte) : une case calculée,
    agrégée ou cumulée d'une campagne non clôturée peut aussi passer de « incomplet » à « calculé » ou l'inverse (même
    origine, mêmes auteurs, même commentaire)."""
    na_zero, cumuls = DECISIONS not in deja, RECALCUL_CUMULS not in deja
    if not na_zero and not cumuls:
        return set()
    statuts = ("calcule", "incomplet") if cumuls else ("calcule",)
    fermees = {p for p, c in a["campagnes"].items() if c and c[0] == "cloturee"}
    apres = {tuple(r[:3]): r for r in b["reponses"]}
    cles, lignes = set(), []
    for r in a["reponses"]:
        s = apres.get(tuple(r[:3]))
        change = s is not None and s != r
        # colonnes : période, KPI, organisation, valeur, texte, N/A, commentaire, statut, origine, saisi par, validé par…
        if (change and r[0] not in fermees and r[7] in statuts and s[7] in statuts and r[8] == s[8]
                and (r[7] == s[7] == "calcule" or r[8] in ORIGINES_CALCULEES)
                and [r[i] for i in (2, 6, 9, 10, 11, 12)] == [s[i] for i in (2, 6, 9, 10, 11, 12)]):
            cles.add(tuple(r[:3]))
            lignes.append(s)
        else:
            lignes.append(r)
    a["reponses"] = sorted(lignes)
    return cles


def comparer_kpis(a, b):
    ecarts = Counter()
    for code, f in a.items():
        g = b.get(code)
        if g is None:
            ecarts["missing after"] += 1
            ECARTS.append(f"KPI {code} missing after")
            continue
        for champ, v in f.items():
            if g.get(champ) != v:
                ecarts[champ] += 1
                ECARTS.append(f"KPI {code}: {champ} {v!r} → {g.get(champ)!r}")
    return {"avant": len(a), "apres": len(b), "champs": len(next(iter(a.values()), {})), "ecarts": dict(ecarts),
            "identiques": sum(1 for c, f in a.items() if c in b and all(b[c].get(k) == v for k, v in f.items()))}  # champs d'avant


def comparer_listes(nom, a, b):
    sa, sb = Counter(map(json.dumps, a)), Counter(map(json.dumps, b))
    for x in list((sa - sb).elements())[:5]:
        ECARTS.append(f"{nom}: only before {x[:300]}")
    for x in list((sb - sa).elements())[:5]:
        ECARTS.append(f"{nom}: only after {x[:300]}")
    return {"avant": len(a), "apres": len(b), "identique": sa == sb}


def comparer_preuves(a, b):
    """Preuves : mêmes KPI, organisation, nom et taille ; le chemin rangé peut changer (rangement des fichiers,
    collecte/0029) ; après la mise à jour, chaque fichier doit être à sa place."""
    r = comparer_listes("evidence", [x[:4] for x in a], [x[:4] for x in b])
    absents = [x for x in b if len(x) > 5 and not x[5]]
    avant_absents = sum(1 for x in a if len(x) > 5 and not x[5])
    for x in absents[:5]:
        ECARTS.append(f"evidence: file missing after the update {json.dumps(x)[:300]}")
    r["identique"] = r["identique"] and len(absents) <= avant_absents
    return r


SEPARATEUR = "\x00"  # plus petit que tout autre caractère : une ligne jointe se trie comme le tuple de ses cellules


def _reduire(indices, lignes, trier=True):
    """Lignes réduites aux colonnes ``indices`` (triées si ``trier``). Une ligne de textes sans caractère nul est gardée en
    une seule chaîne (cellules jointes par SEPARATEUR) : même ordre de tri que le tuple, bien moins de mémoire ; sinon
    en tuple. ``_deplier`` rend les cellules."""
    sortie = []
    for l in lignes:
        t = tuple(l[i] for i in indices)
        if indices and all(isinstance(v, str) and SEPARATEUR not in v for v in t):
            sortie.append(SEPARATEUR.join(t))
        else:
            sortie.append(t)
    if trier:
        # chaînes et tuples ne se comparent pas : tri sur le tuple des cellules si les deux formes coexistent
        if any(isinstance(x, tuple) for x in sortie):
            sortie = [tuple(_deplier(x)) for x in sortie]
        sortie.sort()
    return sortie


def _deplier(x):
    return x.split(SEPARATEUR) if isinstance(x, str) else x


def comparer_export(nom, a, b, recalcules=frozenset(), unites=frozenset()):
    """Colonnes de l'ancien export retrouvées dans le nouveau (par leur nom), ligne par ligne dans le même ordre de tri.
    ``recalcules`` : {(exercice, KPI, organisation)} des cases recalculées voulues, dont la valeur et le N/A peuvent changer.
    ``unites`` : codes des KPI dont l'unité a été corrigée (collecte/0044) : seule leur colonne « Unité » peut changer.
    ``a`` et ``b`` : lignes (en-tête d'abord), ou fonctions qui les lisent (extraction découpée) : les lignes de l'ancien
    export sont réduites aux colonnes utiles avant de lire le nouveau."""
    a = a() if callable(a) else a
    ta, nb_a = a[0], len(a) - 1
    utiles = [c for c in COLONNES_VALEUR if c in ta]
    ra = _reduire([ta.index(c) for c in utiles], a[1:], trier=False)
    del a
    b = b() if callable(b) else b
    tb, nb_b = b[0], len(b) - 1
    colonnes = [c for c in COLONNES_VALEUR if c in ta and c in tb]
    lb = _reduire([tb.index(c) for c in colonnes], b[1:])
    del b
    la = _reduire([utiles.index(c) for c in colonnes], (_deplier(x) for x in ra))
    del ra
    cle = [colonnes.index(c) if c in colonnes else None for c in ("Exercice", "ID KPI", "Organisation")]
    differentes, voulues = Counter(), 0
    for x, y in zip(la, lb):
        x, y = _deplier(x), _deplier(y)
        recalculee = None not in cle and tuple(x[i] for i in cle) in recalcules
        unite_corrigee = cle[1] is not None and x[cle[1]] in unites
        for c, u, v in zip(colonnes, x, y):
            if u != v:
                if recalculee and c in ("Valeur", "N/A"):
                    voulues += 1
                    continue
                if unite_corrigee and c == "Unité":
                    voulues += 1
                    continue
                differentes[c] += 1
                if differentes[c] <= 3:
                    ECARTS.append(f"export {nom}, column {c}: {u!r} → {v!r}")
    nouvelles = [c for c in tb if c not in ta]
    return {"lignes_avant": nb_a, "lignes_apres": nb_b, "colonnes": len(colonnes),
            "cellules": len(la) * len(colonnes), "differences": dict(differentes), "nouvelles_colonnes": len(nouvelles),
            "recalculees": voulues, "identique": len(la) == len(lb) and not differentes}


def comparer_tableaux(a, b):
    """Tableaux de la Visualisation convertis en vues (migration 0023) : chacun a sa vue, avec autant de visuels."""
    tableaux = {pk: n for pk, n in a.get("tableaux", [])}
    vues = {v[3]: v[0] for v in b.get("vues", []) if v[3] is not None}
    convertis = [pk for pk in tableaux if pk in vues]
    tuiles = sum(tableaux.values())
    visuels = sum(vues[pk] for pk in convertis if vues[pk] == tableaux[pk])
    for pk in tableaux:
        if pk not in vues:
            ECARTS.append(f"dashboard {pk} not converted")
    return {"tableaux": len(tableaux), "convertis": len(convertis), "tuiles": tuiles, "tuiles_converties": visuels,
            "identique": len(convertis) == len(tableaux) and visuels == tuiles}


def comparer(a, b, deja=frozenset()):
    renommes = renommer_kpis(a["kpis"], deja)
    n = decimales_entieres(a["kpis"], b["kpis"], deja)
    if n:
        renommes["0 decimals for a \"whole number\" unit (referentiel/0016)"] = n
    n = comptages_decimaux(a["kpis"], b["kpis"], deja)
    if n:
        renommes["non-integer copy of the unit for decimal values (collecte/0027)"] = n
    unites = unites_corrigees(a["kpis"], b["kpis"], deja)
    if unites:
        renommes["unit of a library template KPI corrected (collecte/0044)"] = len(unites)
    recalcules = recalculees(a, b, deja)
    hors_perimetre = cases_hors_perimetre(a, b) if menage_voulu(deja) else 0
    # même ordre qu'avant pour les comparaisons (et donc pour le détail des écarts) ; chaque clé lourde d'une extraction
    # découpée est libérée dès qu'elle a été comparée
    tableaux = comparer_tableaux(a, b)
    kpis = comparer_kpis(a["kpis"], b["kpis"])
    listes = {}
    for n in ("organisations", "comptes", "attributions", "reponses"):
        listes[n] = comparer_listes(n, a[n], b[n])
        _liberer(a, n)
        _liberer(b, n)
    listes["preuves"] = comparer_preuves(a["preuves"], b["preuves"])
    resultat = {
        "unites_corrigees": sorted(unites),
        "hors_perimetre": hors_perimetre,
        "tableaux": tableaux,
        "renommages": renommes,
        "recalculees": len(recalcules),
        "kpis": kpis,
        "listes": listes,
        "campagnes": {"avant": len(a["campagnes"]), "apres": len(b["campagnes"]), "identique": a["campagnes"] == b["campagnes"]},
        "journal": {"avant": a["journal"], "apres": b["journal"], "identique": a["journal"] <= b["journal"]},
    }
    exports_a, exports_b = a["exports"], b["exports"]
    resultat["exports"] = {n: comparer_export(n, exports_a[n], exports_b[n], recalcules, unites) for n in exports_a}
    return resultat


def tout_identique(c):
    return (not c["kpis"]["ecarts"] and c["kpis"]["avant"] == c["kpis"]["apres"]
            and all(x["identique"] for x in c["listes"].values()) and c["campagnes"]["identique"]
            and c["journal"]["identique"] and all(x["identique"] for x in c["exports"].values())
            and c.get("tableaux", {"identique": True})["identique"])


# ---------------------------------------------------------------- démarrage de l'outil et archive de l'ancienne version
def verifier_demarrage(env, port, travail):
    """Démarre l'outil sur la base que décrit ``env`` (``runserver``), puis vérifie ``/sante/`` (état « ok », version du
    code), la page de connexion et la connexion d'un compte de la démo (``docker/check_sign_in.sh``, comme la tâche
    Docker). Renvoie (vrai si tout va bien, phrase pour le rapport). Le serveur est toujours arrêté."""
    import urllib.error
    import urllib.request

    adresse = f"http://127.0.0.1:{port}"
    journal = open(travail / "serveur.log", "w", encoding="utf-8")
    serveur = subprocess.Popen([sys.executable, "manage.py", "runserver", f"127.0.0.1:{port}", "--noreload"], cwd=RACINE,
                               env={**os.environ, **env}, stdout=journal, stderr=subprocess.STDOUT)
    version = (RACINE / "VERSION").read_text(encoding="utf-8").strip()
    try:
        etat = None
        for _ in range(90):
            if serveur.poll() is not None:
                break
            try:
                with urllib.request.urlopen(f"{adresse}/sante/", timeout=5) as r:
                    etat = json.load(r)
                break
            except urllib.error.HTTPError as e:  # 503 : l'outil répond, mais pas en bonne santé
                etat = json.load(e)
                break
            except (OSError, ValueError):
                time.sleep(1)
        if etat is None:
            ECARTS.append("start: the tool did not answer on /sante/ (see the server log)")
            return False, "the tool did not start"
        if etat.get("etat") != "ok" or etat.get("version") != version:
            ECARTS.append(f"/sante/: {json.dumps(etat, ensure_ascii=False)[:500]}")
            return False, f"/sante/ answered state \"{etat.get('etat')}\", version {etat.get('version')}"
        connexion = subprocess.run(["bash", str(RACINE / "docker" / "check_sign_in.sh"), adresse, "admin", "demo-probant-2026", version],
                                   capture_output=True, text=True)
        if connexion.returncode:
            ECARTS.append(f"sign-in after the update: {(connexion.stdout + connexion.stderr).strip()[-500:]}")
            return False, "/sante/ green, but the sign-in failed"
        return True, f"/sante/ green (state ok, version {version}), the demo account signs in and opens the home page"
    finally:
        serveur.terminate()
        try:
            serveur.wait(timeout=15)
        except subprocess.TimeoutExpired:
            serveur.kill()
        journal.close()


REFUS_PG_DOCUMENTE = "other database migrations"  # message de ``restore`` (docs/installation.md, « Going back… »)


def restaurer_archive_ancienne(archive, env_apres, pg, base, suffixe, travail, bases_pg, migrations_passees):
    """Archive faite par l'ancienne version, restaurée par la nouvelle version dans une base vide (comme un nouveau
    serveur) ; extraction, puis (durée, {clé : empreinte}, refus). PostgreSQL : base vide créée puis migrée par
    ``startup``. Une archive PostgreSQL (JSON) ne se restaure qu'avec la version qui l'a faite : quand la mise à jour a
    passé des migrations (``migrations_passees``), la nouvelle version la refuse, sans rien changer, avec un message qui
    renvoie au guide ; ce refus voulu est rendu (``refus`` : le message, ``{clé : empreinte}`` vide) au lieu d'un échec.
    Toute autre erreur, ou un refus alors qu'aucune migration n'a passé, arrête la répétition."""
    debut = time.monotonic()
    dossier = travail / "restauree-ancienne"
    (dossier / "backups").mkdir(parents=True)
    shutil.copy2(archive, dossier / "backups" / archive.name)
    env = {**env_apres, "DATA_DIR": str(dossier)}
    if pg:
        nom = (base + suffixe + "_ancienne")[:63]
        pg_admin(pg, f'CREATE DATABASE "{nom}"')
        bases_pg.append(nom)
        env["DATABASE_URL"] = url_base(pg, nom)
        lancer([sys.executable, "manage.py", "startup"], RACINE, env)
    commande = [sys.executable, "manage.py", "restore", archive.name, "--yes", *(["--other-space"] if pg else [])]
    r = subprocess.run(commande, cwd=RACINE, env={**os.environ, **env}, capture_output=True, text=True)
    if r.returncode:
        sortie = r.stdout + r.stderr
        if pg and migrations_passees and REFUS_PG_DOCUMENTE in sortie and "Nothing was changed" in sortie:
            return time.monotonic() - debut, {}, sortie.strip().splitlines()[-1][:300]
        print(r.stdout[-3000:], r.stderr[-6000:])
        raise SystemExit(f"Failed: {' '.join(map(str, commande))}")
    print(r.stdout.strip()[-1500:])
    lancer([sys.executable, str(EXTRAIRE), str(travail / "restauree-ancienne.json")], RACINE, env)
    return time.monotonic() - debut, sur_disque(travail / "restauree-ancienne.json", None), None


# ---------------------------------------------------------------- rapport
def oui(v):
    return "yes" if v else "**NO**"


def rapport(r):
    c, rest = r["comparaison"], r["restauration"]
    l = [f"## Update rehearsal – {r['date']}", "",
         f"Database: {r['source']} ({r['taille_mo']}{'' if r['taille_mo'] == 'PostgreSQL' else ' MB'}, {r['fichiers']} uploaded file(s)). Version before: {r['nom_avant']} ({r['commit_avant']}); "
         f"version installed: {r['version_apres']} ({r['commit_apres']}). Result: **{'everything identical' if r['ok'] else 'DIFFERENCES TO EXAMINE'}**.", "",
         "| Step | Duration |", "|---|---|"]
    l += [f"| {e} | {d:.1f} s |" for e, d in r["durees"].items()]
    l += ["", "**KPIs (full record, field by field)**", "", "| KPIs before | KPIs after | Fields compared | Identical records | Differences |",
          "|---|---|---|---|---|",
          f"| {c['kpis']['avant']} | {c['kpis']['apres']} | {c['kpis']['champs']} | {c['kpis']['identiques']} | "
          f"{sum(c['kpis']['ecarts'].values()) or 'none'} |", ""]
    if c.get("renommages"):
        l += ["Intended changes, made by the migrations (also applied to the \"before\" state before comparing):", ""]
        l += [f"- {texte}: {n} record(s)" for texte, n in c["renommages"].items()] + [""]
    if c.get("hors_perimetre"):
        l += [f"Empty calculated cells removed by the recalculation ("
              f"collecte/0035 and 0039: a period calculates only the KPIs of its campaigns): {c['hors_perimetre']}; each was "
              "empty, \"incomplete\", without comment or evidence, for a KPI outside the scope of a period with a campaign not "
              "yet closed. No row of a closed period is removed. Any other deleted row is a difference.", ""]
    if c.get("recalculees"):
        l += [f"Calculated cells of the current campaigns recalculated at startup (an N/A source counts "
              f"as 0 in a sum): {c['recalculees']}; only their value and their N/A changed, no closed period moved.", ""]
    l += ["**Data**", "", "| Content | Before | After | Identical |", "|---|---|---|---|"]
    noms = {"organisations": "Organisations", "comptes": "Accounts", "attributions": "Assignments (SPOC, validators)",
            "reponses": "Answers (all campaigns)", "preuves": "Evidence (files)"}
    l += [f"| {noms[n]} | {x['avant']} | {x['apres']} | {oui(x['identique'])} |" for n, x in c["listes"].items()]
    l += [f"| Campaigns | {c['campagnes']['avant']} | {c['campagnes']['apres']} | {oui(c['campagnes']['identique'])} |",
          f"| Log (entries) | {c['journal']['avant']} | {c['journal']['apres']} | {oui(c['journal']['identique'])} |", "",
          f"Dashboards converted into views: {c['tableaux']['convertis']} of {c['tableaux']['tableaux']}; "
          f"tiles converted: {c['tableaux']['tuiles_converties']} of {c['tableaux']['tuiles']} ({oui(c['tableaux']['identique'])}).", "",
          "**Exports** (columns of the old export, found by their name in the new one)", "",
          "| Export | Rows before | Rows after | Columns compared | Cells compared | Differences | Recalculated (intended) | Columns added |",
          "|---|---|---|---|---|---|---|---|"]
    nom_export = {"powerbi": "Database, all years", "manquantes": "Cells still to fill in"}
    for n, x in c["exports"].items():
        l.append(f"| {nom_export.get(n, n)} | {x['lignes_avant']} | {x['lignes_apres']} | {x['colonnes']} | {x['cellules']} | "
                 f"{sum(x['differences'].values()) or 'none'} | {x.get('recalculees') or 'none'} | {x['nouvelles_colonnes']} |")
    l += ["", "**Tables of the old version** (content compared column by column)", "",
          "| Table | Rows before | Rows after | Columns kept | Identical | Remark |", "|---|---|---|---|---|---|"]
    for t, la, lb, cc, ident, rem in r["tables"]:
        l.append(f"| {t} | {la} | {'—' if lb is None else lb} | {cc} | {ident} / {cc} | {rem} |")
    l += ["", "**Backup then restore into an empty database**", "",
          f"Archive {rest['taille_mo']} MB; restore {rest['duree']:.1f} s; extraction after restore identical to "
          f"that of the migrated database: {oui(rest['identique'])}. Automatic backup before migration (startup): "
          f"{'not needed (no migration to apply)' if r['sauvegarde_auto'] is None else oui(r['sauvegarde_auto'])}.", ""]
    if r.get("sante"):
        l += ["**Start of the tool on the updated database**", "", f"{r['sante']['texte']}: {oui(r['sante']['ok'])}.", ""]
    if r.get("archive_ancienne"):
        a = r["archive_ancienne"]
        l += ["**Archive made by the old version, restored by the new version**", ""]
        if a.get("refus"):
            l += [f"Archive {a['taille_mo']} MB made by the old version. PostgreSQL: the update applied migrations, and a "
                  "PostgreSQL archive restores only with the version that made it (docs/installation.md, \"Going back to "
                  f"the previous version\"): the new version refused it, changing nothing, with the documented message "
                  f"({a['duree']:.1f} s): {oui(a['identique'])}.", ""]
        else:
            l += [f"Archive {a['taille_mo']} MB made by the old version, restored into an empty database by the new version in "
                  f"{a['duree']:.1f} s; extraction identical to that of the database updated in place: {oui(a['identique'])}.", ""]
    ret = r.get("retour")
    l += ["**Going back to the old version** (\"before-update\" archive restored with the code of the old version)", "",
          (f"Procedure: {ret['procedure']}; {ret['duree']:.1f} s; extraction and {ret['tables']} tables identical to the "
           f"state before the update: {oui(ret['identique'])}." if ret else "Not done: no \"before-update\" archive."), ""]
    return "\n".join(l)


# ---------------------------------------------------------------- déroulé
def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    # noms anglais ; les anciens noms français restent acceptés
    p.add_argument("--base", required=True, help="Copy of the SQLite database to migrate (not modified); with --postgres: "
                   "name of the PostgreSQL database built with the old version (copied, not modified).")
    p.add_argument("--media", help="Folder of the uploaded files (evidence, logo) of this database, copied too.")
    p.add_argument("--registry", help="SQLite file of the shared account registry (shared.sqlite3) of this installation, "
                   "copied too (installations with spaces).")
    p.add_argument("--postgres", help="URL of the PostgreSQL server (user allowed to create databases): rehearsal under "
                   "PostgreSQL.")
    p.add_argument("--before-name", default="", help="Name of the old version in the report (e.g. 1.0.0).")
    p.add_argument("--before-commit", default="", help="Commit of the old version, when --before is not a git checkout.")
    p.add_argument("--before", "--avant", dest="avant", help="Folder of the code of the old version (default: git worktree of origin/main).")
    p.add_argument("--report", "--rapport", dest="rapport", help="Markdown file to which the report is added (figures only).")
    p.add_argument("--source", default="copy of the production database", help="Description of the database, for the report.")
    p.add_argument("--before-python", default="", help="Python interpreter of the old version (default: the one running this "
                   "script); needed when the packages of the old version differ from the current ones.")
    p.add_argument("--old-archive", help="Archive (.zip) made by the old version with its own backup command, same secret "
                   "key as this script (CLE_SECRETE): restored by the new version into an empty database; the result "
                   "must equal the database updated in place.")
    p.add_argument("--health-port", type=int, default=0, help="Port on which to start the tool on the updated database to "
                   "check /sante/ and the sign-in with a demo account (0: not done).")
    p.add_argument("--keep", "--garder", dest="garder", action="store_true", help="Keep the working folder (investigation of a difference).")
    o = p.parse_args()
    global PYTHON_AVANT
    if o.before_python:
        PYTHON_AVANT = o.before_python
    pg = o.postgres
    source = None if pg else Path(o.base).resolve()
    if source is not None and not source.is_file():
        raise SystemExit(f"Database not found: {source}")
    bases_pg = []
    travail = Path(tempfile.mkdtemp(prefix="repetition-"))
    print(f"Working folder: {travail}")
    durees, worktree = {}, None
    try:
        avant = Path(o.avant).resolve() if o.avant else None
        if avant is None:
            worktree = travail / "code-avant"
            subprocess.run(["git", "worktree", "add", "--detach", str(worktree), "origin/main"], cwd=RACINE, check=True,
                           capture_output=True)
            avant = worktree
        commit = lambda d: subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=d, capture_output=True, text=True).stdout.strip()

        etape("1. Copies")
        donnees = travail / "donnees"
        (donnees / "media").mkdir(parents=True)
        if o.media:
            shutil.copytree(o.media, donnees / "media", dirs_exist_ok=True)
        nb_fichiers = sum(1 for x in (donnees / "media").rglob("*") if x.is_file())
        # dossier des données de l'ancienne version (base, registre) : DOSSIER_DONNEES avant la mise à jour, DATA_DIR ensuite
        dossier_avant = travail / "donnees-avant"
        dossier_avant.mkdir()
        env_avant = {"DJANGO_DEBUG": "1", "MEDIA_ROOT": str(donnees / "media"), "DOSSIER_DONNEES": str(dossier_avant),
                     "DATA_DIR": str(dossier_avant), "DJANGO_SECRET_KEY": CLE_SECRETE}
        env_apres = {"DJANGO_DEBUG": "1", "DATA_DIR": str(donnees), "DJANGO_SECRET_KEY": CLE_SECRETE}
        suffixe = f"_rep{os.getpid()}"
        if pg:
            b_avant, b_apres = (o.base + suffixe + "_avant")[:63], (o.base + suffixe + "_apres")[:63]
            for b in (b_avant, b_apres):
                pg_admin(pg, f'CREATE DATABASE "{b}" TEMPLATE "{o.base}"')
                bases_pg.append(b)
            env_avant["DATABASE_URL"] = url_base(pg, b_avant)
            env_apres["DATABASE_URL"] = url_base(pg, b_apres)
            deja = migrations_pg(url_base(pg, b_avant))
            taille = 0.0
        else:
            shutil.copy2(source, donnees / "db.sqlite3")
            ancienne = dossier_avant / "db.sqlite3"
            shutil.copy2(source, ancienne)
            if o.registry:
                for d in (donnees, dossier_avant):
                    shutil.copy2(o.registry, d / "shared.sqlite3")
                shutil.copy2(o.registry, dossier_avant / "commun.sqlite3")  # nom du registre avant la mise à jour
            deja = migrations_appliquees(source)  # les autres migrations passeront pendant la mise à jour
            taille = source.stat().st_size / 1e6

        etape("2. Extraction before (old version)")
        durees["Extraction before (old version)"] = lancer([PYTHON_AVANT, str(EXTRAIRE), str(travail / "avant.json")], avant, env_avant)
        h_avant = sur_disque(travail / "avant.json", travail / "avant", o.garder)
        emp_avant = empreinte_pg(env_avant["DATABASE_URL"]) if pg else empreinte_sql(ancienne)

        etape("3. Update (manage.py startup: automatic backup, migrations)")
        durees["Update (automatic backup + migrations)"] = lancer([sys.executable, "manage.py", "startup"], RACINE, env_apres, True)
        sauvegarde_auto = any(x.name.endswith(("-before-update.zip", "-avant-mise-a-jour.zip")) for x in (donnees / "backups").glob("*.zip"))
        appliquees = (migrations_pg(env_apres["DATABASE_URL"]) if pg else migrations_appliquees(donnees / "db.sqlite3")) - deja
        if not appliquees and not sauvegarde_auto:
            sauvegarde_auto = None  # base déjà à jour : aucune migration, donc pas de sauvegarde avant (normal)

        etape("4. Extraction after (new version) and comparison")
        durees["Extraction after (new version)"] = lancer([sys.executable, str(EXTRAIRE), str(travail / "apres.json")], RACINE, env_apres)
        h_apres = sur_disque(travail / "apres.json", travail / "apres", o.garder)
        a, b = Extraction(travail / "avant"), Extraction(travail / "apres")
        comparaison = comparer(a, b, deja)
        perimetres = b.get("perimetres_mois")
        del a, b
        if not o.garder:
            for d in ("avant", "apres"):
                shutil.rmtree(travail / d, ignore_errors=True)
        emp_apres = empreinte_pg(env_apres["DATABASE_URL"]) if pg else empreinte_sql(donnees / "db.sqlite3")
        emp_comparee = emp_avant
        if menage_voulu(deja) and perimetres:  # ménage voulu de collecte/0035, 0039 : lignes écartées de l'avant
            if pg:
                lignes_av, preuves_av = lignes_reponses_pg(env_avant["DATABASE_URL"])
                ids_ap = {r["id"] for r in lignes_reponses_pg(env_apres["DATABASE_URL"])[0]}
            else:  # lues en flux : seuls les numéros et les preuves restent en mémoire
                lignes_av, preuves_av = reponses_sqlite(ancienne), preuves_sqlite(ancienne)
                ids_ap = ids_reponses_sqlite(donnees / "db.sqlite3")
            ecartees = ids_hors_perimetre(lignes_av, preuves_av, ids_ap, perimetres)
            del lignes_av
            if ecartees:
                exclure = {"collecte_reponse": ecartees}
                emp_comparee = empreinte_pg(env_avant["DATABASE_URL"], exclure) if pg else empreinte_sql(ancienne, exclure)
        tables = comparer_tables(emp_comparee, emp_apres, deja, unites=bool(comparaison["unites_corrigees"]))

        sante = None
        if o.health_port:
            # démarrage sur une COPIE de la base mise à jour : une connexion écrit (session, historique des connexions), ce
            # qui fausserait les comparaisons des étapes suivantes
            etape("4b. Start of the tool on a copy of the updated database (/sante/, sign-in)")
            env_sante = {**env_apres, "DATA_DIR": str(travail / "sante")}
            if pg:
                nom_sante = (o.base + suffixe + "_sante")[:63]
                pg_admin(pg, f'CREATE DATABASE "{nom_sante}" TEMPLATE "{b_apres}"')
                bases_pg.append(nom_sante)
                env_sante["DATABASE_URL"] = url_base(pg, nom_sante)
            shutil.copytree(donnees, travail / "sante")
            ok_sante, texte_sante = verifier_demarrage(env_sante, o.health_port, travail)
            print(texte_sante)
            sante = {"ok": ok_sante, "texte": texte_sante}

        etape("5. Backup, then restore into an empty database")
        durees["Backup of the migrated database"] = lancer([sys.executable, "manage.py", "backup", "--reason", "repetition"], RACINE, env_apres, True)
        archive = sorted((donnees / "backups").glob("*-repetition.zip"))[-1]
        restauree = travail / "restauree"
        (restauree / "backups").mkdir(parents=True)
        shutil.copy2(archive, restauree / "backups" / archive.name)
        env_rest = {**env_apres, "DATA_DIR": str(restauree)}
        if pg:  # archive JSON : se restaure dans une base vide de la même version (créée, puis migrée par startup)
            b_rest = (o.base + suffixe + "_restauree")[:63]
            pg_admin(pg, f'CREATE DATABASE "{b_rest}"')
            bases_pg.append(b_rest)
            env_rest["DATABASE_URL"] = url_base(pg, b_rest)
            lancer([sys.executable, "manage.py", "startup"], RACINE, env_rest)
        # base PostgreSQL neuve = nouvelle installation (autre identifiant) : l'IT force, comme sur un nouveau serveur
        forcer = ["--other-space"] if pg else []
        duree_rest = lancer([sys.executable, "manage.py", "restore", archive.name, "--yes", *forcer], RACINE, env_rest, True)
        durees["Restore into an empty database"] = duree_rest
        lancer([sys.executable, str(EXTRAIRE), str(travail / "restauree.json")], RACINE, env_rest)
        identique_rest = sur_disque(travail / "restauree.json", None, o.garder) == h_apres
        if not identique_rest:
            ECARTS.append("restore: extraction different from the migrated database")

        etape("6. Going back to the old version (\"before-update\" archive, code of the old version)")
        retour = None
        avant_maj = sorted((donnees / "backups").glob("*-before-update.zip"))
        if avant_maj:
            env_retour = {**env_apres, "DOSSIER_DONNEES": env_apres["DATA_DIR"]}  # nom d'avant la mise à jour aussi
            duree_retour, procedure = retour_arriere(avant, env_retour, pg, avant_maj[-1], travail)
            durees["Going back to the old version"] = duree_retour
            h_retour = sur_disque(travail / "retour.json", None, o.garder)
            identique_retour = h_retour == h_avant
            for k in h_avant:  # empreintes de l'extraction d'avant telle qu'écrite à l'étape 2 (non transformée)
                if h_avant[k] != h_retour.get(k):
                    ECARTS.append(f"going back: \"{k}\" different from the state before the update")
            emp_retour = empreinte_pg(env_retour["DATABASE_URL"]) if pg else empreinte_sql(donnees / "db.sqlite3")
            n_ecarts = len(ECARTS)
            tables_retour = comparer_tables(emp_avant, emp_retour, deja | appliquees)
            identique_retour = identique_retour and len(ECARTS) == n_ecarts
            retour = {"procedure": procedure, "duree": duree_retour, "identique": identique_retour,
                      "tables": len(tables_retour)}
        elif sauvegarde_auto is not None:
            ECARTS.append("going back: no \"before-update\" archive")

        archive_ancienne = None
        if o.old_archive:
            etape("7. Archive made by the old version, restored by the new version into an empty database")
            archive_a = Path(o.old_archive).resolve()
            duree_a, h_a, refus = restaurer_archive_ancienne(archive_a, env_apres, pg, o.base, suffixe, travail, bases_pg,
                                                              bool(appliquees))
            if refus is None:
                for k in h_apres:  # même résultat que la base mise à jour sur place
                    if h_apres[k] != h_a.get(k):
                        ECARTS.append(f"archive of the old version: \"{k}\" different from the database updated in place")
            archive_ancienne = {"taille_mo": f"{archive_a.stat().st_size / 1e6:.1f}", "duree": duree_a, "refus": refus,
                                "identique": refus is not None or h_a == h_apres}

        ok = (tout_identique(comparaison) and identique_rest and sauvegarde_auto is not False
              and (retour["identique"] if retour else sauvegarde_auto is None)
              and (sante["ok"] if sante else True) and (archive_ancienne["identique"] if archive_ancienne else True))
        resultat = {
            "date": datetime.date.today().strftime("%d/%m/%Y"), "source": o.source,
            "taille_mo": f"{taille:.1f}" if not pg else "PostgreSQL", "fichiers": nb_fichiers,
            "commit_avant": o.before_commit or commit(avant), "commit_apres": commit(RACINE),
            "nom_avant": o.before_name or ("main" if worktree else "old version"),
            "version_apres": (RACINE / "VERSION").read_text().strip(), "durees": durees, "comparaison": comparaison, "tables": tables,
            "restauration": {"taille_mo": f"{archive.stat().st_size / 1e6:.1f}", "duree": duree_rest,
                             "identique": identique_rest},
            "sauvegarde_auto": sauvegarde_auto, "retour": retour, "sante": sante, "archive_ancienne": archive_ancienne, "ok": ok,
        }
        texte = rapport(resultat)
        print("\n" + texte)
        if ECARTS:
            print("\nDifferences (detail, not to be published):")
            for e in ECARTS[:200]:
                print("  -", e)
        if o.rapport:
            with open(o.rapport, "a", encoding="utf-8") as f:
                f.write("\n" + texte + "\n")
            print(f"\nReport added to {o.rapport}")
        return 0 if ok else 1
    finally:
        if worktree is not None:
            subprocess.run(["git", "worktree", "remove", "--force", str(worktree)], cwd=RACINE, capture_output=True)
        if pg and not o.garder:
            for b in bases_pg:
                pg_admin(pg, f'DROP DATABASE IF EXISTS "{b}" WITH (FORCE)')
        if o.garder:
            print(f"Working folder kept: {travail}")
        else:
            shutil.rmtree(travail, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
