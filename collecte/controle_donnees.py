"""Contrôle de cohérence de la base (commande ``check_data``, chaque nuit) : des invariants vérifiés sans rien modifier,
pour qu'un problème se voie tout de suite (Paramètres › Hébergement, « À traiter », /sante/).

Chaque contrôle renvoie des constats {check, severity, count, message, examples} :
- « error » : la base contredit une règle de l'outil (à corriger) ;
- « warning » : à regarder (souvent une donnée à reprendre dans l'outil) ;
- « info » : signalé seulement (ex. écart de calcul dans une période clôturée, figée telle qu'elle a été publiée).
Les messages sont pour l'IT, en anglais ; la page Hébergement affiche les titres dans la langue de la personne.

Le résultat de chaque contrôle est gardé hors de la base, dans le dossier des sauvegardes de l'espace
(``data-checks.json``, les derniers résultats), comme l'historique des restaurations : il survit aux restaurations et
se lit même si la base ne répond plus.
"""
import datetime
import json
import logging
import os
import time
import zipfile
from collections import Counter
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.db.models import Count
from django.utils import timezone

from espaces import contexte as ESP
from parametres import langues as L
from parametres import niveaux as N

journal = logging.getLogger("reporting.controle")

FICHIER = "data-checks.json"  # dans le dossier des sauvegardes de l'espace
GARDES = 10  # résultats gardés
EXEMPLES = 5
RETARD = datetime.timedelta(hours=48)  # deux nuits sans contrôle : le planificateur ne tourne plus
POURCENT_MIN, POURCENT_MAX = Decimal(-1), Decimal(10)  # -100 % à 1 000 % (fractions)
ERREUR, AVERTISSEMENT, INFO = "error", "warning", "info"
# déjà signalés ailleurs dans « À traiter » (ligne « Formules à corriger ») : pas comptés deux fois
DEJA_SIGNALES = {"broken_formulas", "units_suspect"}  # « Unités à vérifier » : ligne à part


def _constat(code, gravite, exemples, message, total=None):
    exemples = list(exemples)
    n = len(exemples) if total is None else total
    return {"check": code, "severity": gravite, "count": n, "message": message.format(n=n), "examples": exemples[:EXEMPLES]}


def _proches(a, b):
    """Deux décimaux égaux aux arrondis de stockage près (SQLite garde ~15 chiffres significatifs)."""
    if a is None or b is None:
        return a is b
    return abs(a - b) <= max(Decimal("1e-9"), abs(b) * Decimal("1e-13"))


def _texte_valeur(valeur, texte, na):
    if na:
        return "N/A"
    if texte:
        return texte
    return "empty" if valeur is None else format(valeur.normalize(), "f")


# ---------------------------------------------------------------- calculs
def _calculs(constats):
    """Chaque case calculée, agrégée ou cumulée enregistrée = ce que donne un recalcul en mémoire (sans écrire)."""
    from . import calcul as C
    from . import periodes as P
    from .models import Periode, Reponse

    calendrier, frequences = P.Calendrier(), C.frequences_de_saisie()
    ouvertes, fermees = [], []
    champs = ("valeur", "texte", "non_applicable", "statut", "origine")
    for p in Periode.objects.order_by("debut", "type"):
        calc = C.Calculateur(p, calendrier, frequences)
        figee = calc.figee(p)
        if not figee and not Reponse.objects.filter(periode=p).exists() and not p.campagnes.exists():
            continue
        cellules, sans_objet = C.prevoir(calc)
        ecarts = ouvertes if not figee else fermees
        for r, kid, org, ch, _ in cellules:
            if r is None:
                if ch["statut"] == Reponse.Statut.INCOMPLET and ch["valeur"] is None and not ch["texte"] and not ch["non_applicable"]:
                    continue  # case vide attendue, pas encore écrite (campagne créée sans recalcul) : même chose qu'une absence
                ecarts.append(f"{p} · {kid} · {org.nom}: missing (expected {_texte_valeur(ch['valeur'], ch['texte'], ch['non_applicable'])})")
                continue
            differe = [c for c in champs if not (_proches(getattr(r, c), ch[c]) if c == "valeur" else getattr(r, c) == ch[c])]
            if differe:
                ecarts.append(f"{p} · {kid} · {org.nom}: stored {_texte_valeur(r.valeur, r.texte, r.non_applicable)} ({r.statut}), "
                              f"expected {_texte_valeur(ch['valeur'], ch['texte'], ch['non_applicable'])} ({ch['statut']})")
        for r in sans_objet:
            ecarts.append(f"{p} · {r.kpi_id} · {calc.orgs[r.organisation_id].nom}: calculated cell no longer produced by the settings")
    if ouvertes:
        constats.append(_constat("calculated_mismatch", ERREUR, ouvertes,
                                 "{n} calculated or aggregated cell(s) differ from a recalculation (non-closed periods): "
                                 "run \"python manage.py recalculate <year>\" or the \"Recalculate\" action of the campaign"))
    if fermees:
        constats.append(_constat("calculated_mismatch_closed", INFO, fermees,
                                 "{n} cell(s) of closed periods differ from a recalculation with today's settings "
                                 "(closed periods stay as published: reported only)"))


# ---------------------------------------------------------------- réponses
def _reponses(constats):
    from referentiel.models import KPI, Organisation

    from .models import Campagne, Reponse

    R = Reponse
    kpis = {k.code: k for k in KPI.objects.select_related("type_saisie", "type_reponse")}
    orgs = dict(Organisation.objects.values_list("id", "nom"))
    periodes_campagne = set(Campagne.objects.values_list("periode_id", flat=True))
    statuts, gardees = {}, set()
    for pid, st, gardes in Campagne.objects.values_list("periode_id", "statut", "chiffres_gardes"):
        statuts.setdefault(pid, set()).add(st)
        if gardes and st != Campagne.Statut.CLOTUREE:
            gardees.add(pid)
    # toutes clôturées, ou une rouverte en gardant les chiffres de l'époque (vaut pour la période, ``calcul.figee``)
    figees = {pid for pid, s in statuts.items() if s == {Campagne.Statut.CLOTUREE}} | gardees
    from .models import Periode

    noms_periodes = {p.pk: str(p) for p in Periode.objects.all()}

    orphelines, sans_campagne, statut_faux, pourcent, importees = [], [], [], [], []
    calculees = (R.Origine.CALCUL, R.Origine.AGREGATION, R.Origine.CUMUL)
    saisies = (R.Origine.SAISIE, R.Origine.IMPORT, R.Origine.FORCEE)
    lignes = R.objects.values_list("periode_id", "kpi_id", "organisation_id", "valeur", "texte", "non_applicable", "statut", "origine")
    for pid, kid, oid, val, texte, na, statut, origine in lignes.iterator(chunk_size=5000):
        ou = f"{noms_periodes.get(pid, pid)} · {kid} · {orgs.get(oid, oid)}"
        kpi = kpis.get(kid)
        if kpi is None or oid not in orgs:
            orphelines.append(f"{ou}: {'KPI' if kpi is None else 'organisation'} no longer exists")
            continue
        if pid not in periodes_campagne and origine in saisies and (val is not None or texte or na):
            sans_campagne.append(f"{ou}: value in a period without any campaign")
        probleme = None
        if statut == R.Statut.VALIDE and val is None and not texte and not na:
            probleme = "validated without a value or N/A"
        elif na and val is not None:
            probleme = "N/A with a value"
        elif origine in calculees and statut not in (R.Statut.CALCULE, R.Statut.INCOMPLET, R.Statut.ERREUR):
            probleme = f"calculated cell with status \"{statut}\""
        elif origine in saisies and statut in (R.Statut.CALCULE, R.Statut.INCOMPLET, R.Statut.ERREUR):
            probleme = f"{origine} cell with status \"{statut}\""
        elif statut == R.Statut.CALCULE and val is None and not texte and not na:
            probleme = "status \"calculated\" without a value"
        elif pid not in figees and origine == R.Origine.CALCUL and not kpi.est_calcule:
            probleme = "calculated origin on an entered KPI"
        elif pid not in figees and origine == R.Origine.CUMUL and kpi.est_calcule:
            probleme = "cumulative origin on a calculated KPI"
        if probleme:
            statut_faux.append(f"{ou}: {probleme}")
        if val is not None and kpi.est_pourcentage and not POURCENT_MIN <= val <= POURCENT_MAX:
            pourcent.append(f"{ou}: {format((val * 100).normalize(), 'f')} % ({origine})")
        if origine == R.Origine.IMPORT and kpi.est_calcule and pid not in figees:
            importees.append(f"{ou}: imported as is ({_texte_valeur(val, texte, na)}), the formula is not applied")
    doubles = _doublons()
    if orphelines or sans_campagne:
        constats.append(_constat("orphan_answers", ERREUR if orphelines else AVERTISSEMENT, orphelines + sans_campagne,
                                 "{n} answer(s) attached to a deleted KPI or organisation, or to a period without any campaign"))
    if doubles:
        constats.append(_constat("duplicate_answers", ERREUR,
                                 [f"{noms_periodes.get(p, p)} · {k} · {orgs.get(o, o)}: {n} answers" for p, k, o, n in doubles],
                                 "{n} KPI × organisation × period with more than one answer"))
    if statut_faux:
        constats.append(_constat("inconsistent_status", ERREUR, statut_faux, "{n} answer(s) with a status that contradicts their content"))
    if pourcent:
        constats.append(_constat("percentage_out_of_range", AVERTISSEMENT, pourcent,
                                 "{n} percentage(s) below -100 % or above 1,000 % (stored as fractions: a value typed 25 instead of 25 %?)"))
    if importees:
        constats.append(_constat("imported_calculated_open", AVERTISSEMENT, importees,
                                 "{n} figure(s) of a calculated KPI imported as is in a non-closed period: they are never "
                                 "recalculated (check that this is intended)"))


def _doublons():
    """[(période, KPI, organisation, nombre)] des cases qui ont plus d'une réponse (la contrainte d'unicité l'empêche ;
    filet pour une base restaurée ou modifiée hors de l'outil)."""
    from .models import Reponse

    return list(Reponse.objects.values("periode_id", "kpi_id", "organisation_id").annotate(n=Count("id")).filter(n__gt=1)
                .values_list("periode_id", "kpi_id", "organisation_id", "n"))


# ---------------------------------------------------------------- attributions
def _attributions(constats):
    """Attributions vers des comptes inactifs ou en lecture seule, ou des organisations fermées, pour les KPI des
    campagnes non clôturées."""
    from referentiel.models import Attribution, ElementReferentiel

    from .calcul import arbre_ouverture, ouverte
    from .models import Campagne

    campagnes = list(Campagne.objects.exclude(statut=Campagne.Statut.CLOTUREE).select_related("periode"))
    if not campagnes:
        return
    periodes_par_ref = {}
    for c in campagnes:
        periodes_par_ref.setdefault(c.referentiel_id, []).append(c.periode)
    periodes_par_kpi = {}
    for kid, rid in ElementReferentiel.objects.filter(referentiel_id__in=periodes_par_ref).values_list("kpi_id", "referentiel_id"):
        periodes_par_kpi.setdefault(kid, []).extend(periodes_par_ref[rid])
    comptes, fermees = [], []
    arbre = arbre_ouverture()
    for a in Attribution.objects.filter(kpi_id__in=periodes_par_kpi).select_related("utilisateur", "organisation").order_by("kpi_id", "id"):
        u, o = a.utilisateur, a.organisation
        ou = f"{a.kpi_id} · {o.nom} → {u.username}"
        if not u.is_active:
            comptes.append(f"{ou}: inactive account")
        elif u.lecture_seule:
            comptes.append(f"{ou}: read-only account ({u.role})")
        elif not any(ouverte(arbre[o.pk], p, arbre) for p in periodes_par_kpi[a.kpi_id]):
            fermees.append(f"{ou}: organisation closed")
    if comptes:
        constats.append(_constat("assignments_inactive_account", AVERTISSEMENT, comptes,
                                 "{n} assignment(s) of open campaigns to an inactive or read-only account: nobody will enter "
                                 "these values (assign them to someone else)"))
    if fermees:  # normal après la fermeture d'un site (il n'est plus demandé) : signalé seulement
        constats.append(_constat("assignments_closed_organisation", INFO, fermees,
                                 "{n} assignment(s) on an organisation closed before the open campaigns (not requested any "
                                 "more: they can be removed)"))


# ---------------------------------------------------------------- preuves
def _preuves(constats):
    from parametres.rangement import PREUVES

    from .models import Preuve

    racine = ESP.dossier_medias()
    manquantes, connues = [], set()
    for pk, nom, nom_fichier, kid, oid in Preuve.objects.values_list("pk", "fichier", "nom_fichier", "reponse__kpi_id",
                                                                     "reponse__organisation__nom").order_by("pk"):
        connues.add(os.path.normpath(nom or ""))
        if not nom or not (racine / nom).is_file():
            manquantes.append(f"{kid} · {oid}: {nom or nom_fichier or pk}")
    if manquantes:
        constats.append(_constat("evidence_missing", ERREUR, manquantes,
                                 "{n} evidence file(s) recorded in the database but missing from the disk (" + str(racine) + ")"))
    orphelins = []
    dossier = racine / PREUVES
    if dossier.is_dir():
        for chemin, _, fichiers in os.walk(dossier):
            for f in fichiers:
                rel = os.path.normpath(os.path.relpath(os.path.join(chemin, f), racine))
                if rel not in connues:
                    orphelins.append(Path(rel).as_posix())
    if orphelins:
        constats.append(_constat("evidence_orphan_files", AVERTISSEMENT, sorted(orphelins),
                                 "{n} file(s) in files/evidence that no evidence of the database points to (left over: "
                                 "they can be archived then deleted)"))


# ---------------------------------------------------------------- formules
def _formules(constats):
    from referentiel import formule as F
    from referentiel.models import KPI, KPIFormule

    from . import formules as FM

    cassees = [f"{e['kpi'].code}: {e['probleme']}" for e in FM.dans_la_formule()]
    cassees += [f"{e['kpi'].code}: {e['n']} cell(s) in error ({e['message']})" for e in FM.au_calcul()]
    if cassees:
        constats.append(_constat("broken_formulas", AVERTISSEMENT, cassees,
                                 "{n} formula problem(s): see Administration > Frameworks > Formulas to fix"))
    enregistrees = {}
    for c, s, d in KPIFormule.objects.values_list("kpi_calcule_id", "kpi_source_id", "decalage"):
        enregistrees.setdefault(c, set()).add((s, d))
    ecarts = []
    for k in KPI.objects.select_related("type_saisie").order_by("code"):
        attendues = set()
        if k.est_calcule and (k.formule or "").strip():
            try:
                attendues = {(r.kpi, r.decalage) for r in F.references(k.formule)}
            except F.FormuleInvalide:
                attendues = set()
        avoir = enregistrees.pop(k.code, set())
        if avoir != attendues:
            manque, trop = sorted(attendues - avoir), sorted(avoir - attendues)
            ecarts.append(f"{k.code}: " + "; ".join(
                ([f"missing {', '.join(s if d == 'N' else f'{s}@{d}' for s, d in manque)}"] if manque else [])
                + ([f"extra {', '.join(s if d == 'N' else f'{s}@{d}' for s, d in trop)}"] if trop else [])))
    for c in sorted(enregistrees):
        ecarts.append(f"{c}: dependencies of a KPI that no longer exists")
    if ecarts:
        constats.append(_constat("formula_dependencies", ERREUR, ecarts,
                                 "{n} KPI(s) whose stored formula dependencies do not match the formula text (recalculation "
                                 "triggers would be missed): save the KPI again"))


# ---------------------------------------------------------------- arbre
def _arbre(constats):
    from parametres.models import NiveauHierarchique
    from referentiel.models import Organisation

    rangs = N.rangs()
    sortie = []
    doublons = [r for r, n in Counter(rangs.values()).items() if n > 1]
    if doublons:
        sortie.append(f"levels: rank(s) {', '.join(map(str, sorted(doublons)))} used by several levels")
    if rangs and sorted(rangs.values()) != list(range(1, len(rangs) + 1)):
        sortie.append(f"levels: ranks {sorted(rangs.values())} are not 1 to {len(rangs)}")
    orgs = {o.id: o for o in Organisation.objects.all()}
    noms_niveaux = dict(NiveauHierarchique.objects.values_list("code", "nom"))
    for o in sorted(orgs.values(), key=lambda o: o.nom):
        vus, x = {o.id}, orgs.get(o.parent_id)
        while x is not None:
            if x.id in vus:
                sortie.append(f"{o.nom}: loop in the tree (an ancestor is attached below it)")
                break
            vus.add(x.id)
            x = orgs.get(x.parent_id)
        r = rangs.get(o.niveau_id)
        p = orgs.get(o.parent_id)
        if o.parent_id and p is None:
            sortie.append(f"{o.nom}: parent no longer exists")
        elif r == 1 and p is not None:
            sortie.append(f"{o.nom}: top-level ({noms_niveaux.get(o.niveau_id)}) attached to {p.nom}")
        elif r is not None and r > 1 and p is None:
            sortie.append(f"{o.nom}: not attached to any organisation")
        elif p is not None and rangs.get(p.niveau_id, 0) >= (r or 0):
            sortie.append(f"{o.nom} ({noms_niveaux.get(o.niveau_id)}): attached to {p.nom} ({noms_niveaux.get(p.niveau_id)}), "
                          "which is not at a higher level")
        if p is not None and o.actif and not p.actif:
            sortie.append(f"{o.nom}: collected but attached to {p.nom}, which is not collected any more")
    if sortie:
        constats.append(_constat("tree", ERREUR, sortie, "{n} problem(s) in the tree of organisations or its levels"))


# ---------------------------------------------------------------- unités
def _unites(constats):
    """KPI dont l'unité ressemble au rapprochement fautif d'avant la mise à jour (``unites_mal_rapprochees.douteux``) :
    rien n'est corrigé ici ; l'administrateur vérifie la fiche du KPI."""
    from .unites_mal_rapprochees import douteux

    cas = douteux()
    if cas:
        constats.append(_constat("units_suspect", AVERTISSEMENT,
                                 [f"{c.kpi.code}: unit \"{c.actuelle.symbole}\", template {c.modele} asks for "
                                  f"\"{c.symbole_voulu}\"" for c in cas],
                                 "{n} KPI(s) whose unit looks like a matching error made when a file or a library template "
                                 "was imported (by an earlier version of the tool): check the unit on the KPI sheet (no value is changed)"))


# ---------------------------------------------------------------- sauvegarde
def _sauvegarde(constats):
    from parametres import sauvegardes as SV

    try:
        liste = SV.archives()
    except OSError as e:
        constats.append(_constat("backup_unreadable", ERREUR, [str(e)], "The backup folder cannot be read"))
        return
    if not liste:
        constats.append(_constat("backup_none", INFO, [str(SV.dossier())], "No backup yet: nothing to check"))
        return
    a = liste[0]
    try:
        d = SV.lire_descriptif(a.chemin)
        with zipfile.ZipFile(a.chemin) as z:
            abime = z.testzip()
        if abime:
            raise SV.ErreurSauvegarde(f"damaged file in the archive: {abime}")
        if (d.get("espace") or ESP.PRINCIPAL) != ESP.code_courant():
            raise SV.ErreurSauvegarde(f"archive of another space ({d.get('espace')})")
    except (SV.ErreurSauvegarde, zipfile.BadZipFile, OSError, RuntimeError) as e:
        constats.append(_constat("backup_unreadable", ERREUR, [f"{a.nom}: {e}"], "The most recent backup cannot be read: it could not be restored"))


CONTROLES = [("calculations", _calculs), ("answers", _reponses), ("assignments", _attributions), ("evidence", _preuves),
             ("formulas", _formules), ("tree", _arbre), ("units", _unites), ("backup", _sauvegarde)]


# ---------------------------------------------------------------- contrôle complet
@contextmanager
def _lecture_seule():
    """Transaction de lecture, annulée à la fin : un instantané cohérent de la base (même si quelqu'un saisit pendant le
    contrôle) et la garantie que rien n'est écrit. SQLite : transaction différée (les réglages de l'outil ouvrent les
    transactions en IMMEDIATE, qui bloquerait les saisies pendant tout le contrôle ; en WAL, une lecture ne bloque
    personne). PostgreSQL : REPEATABLE READ, READ ONLY. Dans une transaction déjà ouverte (tests) : un point de
    sauvegarde."""
    from django.db import transaction

    cx = ESP.connexion()
    externe = not cx.in_atomic_block
    if externe and cx.vendor == "sqlite":
        cx.ensure_connection()  # le mode est relu des réglages à l'ouverture de la connexion : l'ouvrir avant de le changer
    mode = getattr(cx, "transaction_mode", None)
    if externe and cx.vendor == "sqlite":
        cx.transaction_mode = "DEFERRED"
    try:
        with transaction.atomic(using=ESP.alias_courant()):
            if externe and cx.vendor == "postgresql":
                with cx.cursor() as c:
                    c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            yield
            transaction.set_rollback(True, using=ESP.alias_courant())
    finally:
        if externe and cx.vendor == "sqlite":
            cx.transaction_mode = mode


def controler():
    """Tous les contrôles de l'espace courant, sans rien modifier (``_lecture_seule``). Renvoie le résultat (dict)."""
    from django.db import transaction

    debut = time.monotonic()
    constats, durees = [], {}
    # messages pour l'IT en anglais, quelle que soit la langue de l'interface ; état des langues lu avant la transaction
    with L.session(), L.activer_interface("en"), _lecture_seule():
        for nom, controle in CONTROLES:
            t = time.monotonic()
            try:
                with transaction.atomic(using=ESP.alias_courant()):  # une erreur de base n'interrompt pas les suivants
                    controle(constats)
            except Exception as e:  # noqa: BLE001 - un contrôle en défaut n'empêche pas les autres
                journal.exception("Data check \"%s\" failed", nom)
                constats.append(_constat("check_failed", ERREUR, [f"{nom}: {e.__class__.__name__}: {e}"],
                                         "A check could not run (see the server log)"))
            durees[nom] = round(time.monotonic() - t, 2)
    total = Counter(c["severity"] for c in constats if c["count"])
    return {"date": timezone.localtime().isoformat(), "space": ESP.code_courant(), "version": settings.VERSION,
            "seconds": round(time.monotonic() - debut, 1), "durations": durees,
            "errors": total[ERREUR], "warnings": total[AVERTISSEMENT], "infos": total[INFO], "problems": constats}


# ---------------------------------------------------------------- résultats gardés
def fichier(code=None):
    from parametres import sauvegardes as SV

    return (ESP.dossier_sauvegardes(code) if code else SV.dossier()) / FICHIER


def resultats():
    """Derniers résultats gardés de l'espace courant, le plus récent d'abord ([] si aucun ou illisible)."""
    try:
        donnees = json.loads(fichier().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    liste = [r for r in donnees.get("results", []) if isinstance(r, dict) and r.get("date")] if isinstance(donnees, dict) else []
    return sorted(liste, key=lambda r: r["date"], reverse=True)


def dernier():
    r = resultats()
    return r[0] if r else None


def enregistrer(resultat):
    """Ajoute un résultat au fichier de l'espace (les ``GARDES`` derniers), écrit d'un coup (fichier partiel puis
    renommé : jamais à moitié écrit)."""
    f = fichier()
    f.parent.mkdir(parents=True, exist_ok=True)
    liste = [resultat] + resultats()
    partiel = f.with_name(f".{f.name}.{os.getpid()}.partiel")
    partiel.write_text(json.dumps({"results": liste[:GARDES]}, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    os.replace(partiel, f)


def date_de(resultat):
    try:
        return datetime.datetime.fromisoformat(resultat["date"])
    except (KeyError, TypeError, ValueError):
        return None


CODES = ["calculated_mismatch", "calculated_mismatch_closed", "orphan_answers", "duplicate_answers", "inconsistent_status",
         "percentage_out_of_range", "imported_calculated_open", "assignments_inactive_account",
         "assignments_closed_organisation", "evidence_missing", "evidence_orphan_files", "broken_formulas",
         "formula_dependencies", "tree", "units_suspect", "backup_unreadable", "backup_none",
         "check_failed"]  # titres : admin.controle.check.<code>


def titre(constat):
    """Titre d'un constat dans la langue de l'interface (Hébergement, « À traiter »)."""
    from parametres.libelles import libelle

    code = constat.get("check") if constat.get("check") in CODES else "check_failed"
    return libelle(f"admin.controle.check.{code}", n=constat.get("count", 0))


def a_signaler(resultat):
    """Constats d'erreur ou d'avertissement à montrer dans « À traiter » (sans ceux déjà signalés ailleurs)."""
    return [c for c in (resultat or {}).get("problems", [])
            if c.get("count") and c.get("severity") in (ERREUR, AVERTISSEMENT) and c.get("check") not in DEJA_SIGNALES]


def etat(maintenant=None):
    """Pour /sante/, la page Hébergement et « À traiter » : {etat, date, erreurs, avertissements, resultat}.
    etat (en anglais, comme les détails de /sante/) : « never » (aucun contrôle encore), « late » (aucun depuis 48 h :
    le planificateur ne tourne plus), « problems » (erreurs ou avertissements) ou « ok »."""
    maintenant = maintenant or timezone.now()
    r = dernier()
    if r is None:
        return {"etat": "never", "date": None, "erreurs": 0, "avertissements": 0, "resultat": None}
    quand = date_de(r)
    sortie = {"etat": "ok", "date": quand, "erreurs": r.get("errors", 0), "avertissements": r.get("warnings", 0), "resultat": r}
    if quand is None or maintenant - quand > RETARD:
        sortie["etat"] = "late"
    elif sortie["erreurs"] or sortie["avertissements"]:
        sortie["etat"] = "problems"
    return sortie


def pour_sante():
    """Clé « controle_donnees » de /sante/ (détail) : {etat, date, erreurs, avertissements}."""
    try:
        e = etat()
    except Exception:  # noqa: BLE001 - la santé répond toujours
        return {"etat": "unreadable", "date": None, "erreurs": None, "avertissements": None}
    return {"etat": e["etat"], "date": e["date"].isoformat() if e["date"] else None, "erreurs": e["erreurs"],
            "avertissements": e["avertissements"]}


def controler_et_enregistrer():
    r = controler()
    enregistrer(r)
    journal.info("Data check (space \"%s\"): %s error(s), %s warning(s), %.1f s", r["space"], r["errors"], r["warnings"], r["seconds"])
    return r


# ---------------------------------------------------------------- ménage de la nuit
def effacer_sessions_expirees(codes=()):
    """Sessions terminées effacées (comme ``manage.py clearsessions``) : celles du registre commun, où vivent les
    sessions de tous les espaces (espaces/routeur.py), et les restes d'une table de sessions d'avant les espaces dans la
    base d'un espace (``codes``). Renvoie le nombre de sessions effacées ; sans danger : une session encore valide n'est
    jamais touchée."""
    from django.contrib.sessions.models import Session
    from django.db import connections

    maintenant = timezone.now()
    n = Session.objects.filter(expire_date__lt=maintenant).delete()[0]  # routé vers le registre commun
    for code in codes:
        try:
            with ESP.activer(code):
                base = connections[ESP.alias_courant()]
                if base.alias == ESP.COMMUN or "django_session" not in base.introspection.table_names():
                    continue
                with base.cursor() as c:
                    c.execute("DELETE FROM django_session WHERE expire_date < %s", [maintenant])
                    n += max(c.rowcount, 0)
        except Exception:  # noqa: BLE001 - un espace injoignable n'empêche pas les autres
            journal.exception("Expired sessions not erased (space \"%s\")", code)
    return n


def menage_nocturne(codes):
    """Chaque nuit (et au lancement du planificateur) : sessions terminées effacées, corbeille purgée dans chaque espace
    (ce qui y est depuis plus que le délai de Paramètres › Hébergement), et connexions plus anciennes que la durée de
    l'historique des connexions effacées. Une ligne au journal du serveur."""
    from parametres import sauvegardes as SV

    from .models import purger_corbeille

    sessions = effacer_sessions_expirees(codes)
    elements = 0
    for code in codes:
        try:
            with ESP.activer(code):
                if not SV.base_vide():
                    elements += purger_corbeille()
        except Exception:  # noqa: BLE001
            journal.exception("Purge of deleted items failed (space \"%s\")", code)
    connexions = 0
    for code in codes:  # historique des connexions : au-delà du nombre de jours réglé (Paramètres › Hébergement)
        try:
            with ESP.activer(code):
                if not SV.base_vide():
                    from referentiel.historique_connexions import purger

                    connexions += purger()
        except Exception:  # noqa: BLE001
            journal.exception("Purge of the sign-in history failed (space \"%s\")", code)
    journal.info("Nightly clean-up: %s expired session(s), %s deleted item(s) and %s old sign-in(s) erased for good",
                 sessions, elements, connexions)
    return sessions, elements


# ---------------------------------------------------------------- planification
def planifier(heure=None):
    """Boucle sans fin (image Docker, worker Clever Cloud) : chaque jour à ``heure`` (DATA_CHECK_TIME, 03:30 par défaut),
    un contrôle de chaque espace actif ; un espace jamais contrôlé l'est tout de suite, une échéance manquée (serveur
    arrêté) est rattrapée au démarrage. Au même moment, le ménage de la nuit (``menage_nocturne`` : sessions terminées,
    corbeille), fait aussi au lancement de la boucle."""
    from django.db import connections

    from parametres import alertes
    from parametres import sauvegardes as SV
    from parametres import taches_fond

    heure = heure or settings.CONTROLE_HEURE
    journal.info("Data check scheduler started: every day at %s", heure)
    taches_fond.demarrer("data_check")
    dernier_menage = None
    def controler_si_echeance():
        if SV.base_vide():
            return
        r = dernier()
        quand = date_de(r) if r else None
        if quand is None or SV.echeance_suivante("jour", heure, quand) <= timezone.localtime():
            controler_et_enregistrer()

    while True:
        codes = ESP.codes_planifies(journal)
        if dernier_menage is None or SV.echeance_suivante("jour", heure, dernier_menage) <= timezone.localtime():
            dernier_menage = timezone.localtime()
            try:
                menage_nocturne(codes)
            except Exception:  # noqa: BLE001 - on réessaiera la nuit suivante
                journal.exception("Nightly clean-up failed")
        ESP.pour_chaque_espace(controler_si_echeance, journal, "Data check failed (space \"%s\")", codes)
        alertes.passage_planifie()  # alertes par e-mail, toutes les 15 minutes au plus (aussi lancées par backup --schedule)
        connections.close_all()
        time.sleep(300)
