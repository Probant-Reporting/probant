"""Dossier d'audit exportable : un fichier Excel pour un audit, présentation « audit » d'Import / Export.

Lecture seule : le fichier ne fait que relire ce que les écrans montrent déjà. Les lignes viennent du même moteur que les
autres exports (``exports.collecter`` : mêmes périmètre, arbre de la période, règle de N-1) ; chaque ligne (un KPI dans une
organisation, pour une période) y ajoute qui a saisi et validé, la valeur forcée, les preuves, les alertes de cohérence et
leurs justifications. Deux onglets de plus : l'historique des changements de ces cases (le journal) et la liste des
fichiers de preuve. Rien n'est écrit : la cohérence n'est pas recalculée (``coherence.controler_a_l_ouverture`` n'est
jamais appelé) et le journal n'est pas alimenté ; seule la tâche d'un gros export en arrière-plan
(``exports_arriere_plan``) laisse la trace technique des autres exports.

Droits : ceux des données lues. Les alertes, les noms des preuves et le journal d'une case ne sont réunis que pour
l'administrateur et l'auditeur : le journal n'est lu par aucun autre rôle dans l'outil, et les autres exports ne donnent à
un validateur ou à un contributeur ni les alertes, ni les noms des preuves, ni l'historique. Un auditeur limité à des
organisations n'a que leurs cases, leurs alertes (règle de la page Cohérence) et le journal de ces cases. Les KPI
« Restreint » et « Confidentiel » se lisent à l'écran par ces deux rôles : ils sont dans le fichier, avec leur mention de
confidentialité (aucune règle de masquage n'existe pour les écrans, ``sensibles.py`` ne vaut que pour les assistants).
"""
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.core.exceptions import PermissionDenied

from parametres import libelles as LB
from parametres.libelles import libelle
from referentiel.models import KPI

from . import dates_courtes as DC
from . import exports as E
from . import fichiers as X
from . import saisie as S
from .models import Alerte, DemandeForcage, Journal, Preuve, Reponse

PRESENTATION = "audit"
LOT = 800  # identifiants de réponses par lecture : sous le plafond de paramètres de SQLite
MAX_LIGNES_HISTORIQUE = E.MAX_LIGNES_EXCEL - E.LIGNES_ENTETE_EXCEL
ORDRE_GRAVITE = {Alerte.Gravite.BLOQUANTE: 0, Alerte.Gravite.ALERTE: 1, Alerte.Gravite.INFO: 2}
FORMAT_ECART = "+0.0 %;-0.0 %;0.0 %"

# (code, largeur, rôle de la colonne). Titre : « suivi.export.colonne.<code> » pour les colonnes de la base de données,
# « suivi.export.audit.col.<code> » pour les autres.
COLONNES = [
    ("exercice", 9, "cle"), ("periode", 13, "cle"), ("id", 11, "cle"), ("indicateur", 50, "info"), ("referentiel", 22, "info"),
    ("theme", 28, "info"), ("sous_theme", 30, "info"), ("code_org", 14, "cle"), ("organisation", 24, "info"),
    ("niveau", 10, "info"),
    ("valeur", 14, "info"), ("unite", 10, "info"), ("na", 6, "info"), ("n1", 14, "info"), ("comparaison", 16, "info"),
    ("ecart", 10, "info"), ("statut", 12, "info"), ("origine", 16, "info"),
    ("forcee", 9, "info"), ("forcage", 50, "info"), ("commentaire", 40, "info"),
    ("saisi_par", 26, "info"), ("date_maj", 16, "info"), ("valide_par", 26, "info"), ("date_validation", 16, "info"),
    ("nb_preuves", 9, "info"), ("preuves", 40, "info"),
    ("nb_alertes", 9, "info"), ("alertes", 50, "info"), ("justifications", 50, "info"), ("decisions", 40, "info"),
    ("confidentialite", 14, "info"),
]
COLONNES_COMMUNES = {"exercice", "periode", "id", "indicateur", "referentiel", "theme", "sous_theme", "code_org", "organisation",
                     "niveau", "valeur", "unite", "na", "n1", "comparaison", "statut", "origine", "commentaire", "saisi_par",
                     "date_maj", "valide_par", "date_validation"}


def permis(utilisateur):
    """Administrateur et auditeur seulement (voir l'en-tête du module)."""
    return bool(utilisateur.est_admin or utilisateur.est_auditeur)


def exiger(utilisateur):
    if not permis(utilisateur):
        raise PermissionDenied(libelle("suivi.export.audit.refus"))


def entetes(p):
    return [E.texte_fichier(p, f"suivi.export.colonne.{c}" if c in COLONNES_COMMUNES else f"suivi.export.audit.col.{c}")
            for c, _, _ in COLONNES]


def _qui(u):
    """La personne comme dans l'onglet Historique : son nom (à défaut son adresse e-mail), jamais l'adresse d'abord."""
    return str(u) if u else ""


def _statut(l, lg):
    """Statut de la case avec les mots de l'écran (« choix.reponse.statut.* »), dans la langue du fichier."""
    return LB.choix_valeur(Reponse, "statut", l.reponse.statut if l.reponse is not None else Reponse.Statut.A_SAISIR, lg)


def _qui_quand(u, d, lg):
    return ", ".join(x for x in (_qui(u), DC.date_heure_courte(d, lg)) if x)


def _numerote(textes):
    """« 1) … | 2) … » : une alerte par numéro, le même dans les colonnes des alertes, des justifications et des décisions."""
    return " | ".join(f"{i}) {t}" for i, t in textes if t)


def _nom_fichier(pr):
    return pr.nom_fichier or pr.fichier.name.rsplit("/", 1)[-1]


def _taille(octets):
    return f"{max(1, round(octets / 1024))} kB" if octets else "0 kB"


class Contexte:
    """Ce que le fichier lit en plus des lignes, par lots et une seule fois : preuves, alertes et valeurs forcées de leurs
    cases. Ces lectures ne font que lire."""

    def __init__(self, utilisateur, p, lignes):
        self.p, self.lg = p, p.langue
        ids = sorted({l.reponse.pk for l in lignes if l.reponse is not None})
        self.preuves = {}
        for i in range(0, len(ids), LOT):
            for pr in Preuve.objects.filter(reponse_id__in=ids[i:i + LOT]).select_related("depose_par").order_by("date_depot", "pk"):
                self.preuves.setdefault(pr.reponse_id, []).append(pr)
        periodes = {l.periode.pk for l in lignes}
        self.alertes = self._alertes(utilisateur, p, periodes)
        self.forcages = {}
        if periodes:
            for d in DemandeForcage.objects.filter(periode_id__in=periodes, statut=DemandeForcage.Statut.ACCEPTEE) \
                    .select_related("demandeur", "traite_par").order_by("date_traitement", "pk"):
                self.forcages[(d.periode_id, d.kpi_id, d.organisation_id)] = d  # la dernière acceptée est celle qui s'applique

    @staticmethod
    def _alertes(utilisateur, p, periodes):
        """{(période, KPI, organisation) : alertes que la personne voit} : la règle de la page Cohérence, la seule."""
        from . import coherence as CO

        par_case = {}
        for c in p.campagnes():
            if c.periode_id not in periodes:
                continue
            for a in CO.alertes_visibles(utilisateur, c):
                par_case.setdefault((c.periode_id, a.kpi_id, a.organisation_id), []).append(a)
        for liste in par_case.values():
            liste.sort(key=lambda a: (ORDRE_GRAVITE.get(a.gravite, 3), a.date_creation, a.pk))
        return par_case

    def ligne(self, l):
        """Valeurs d'une ligne, dans l'ordre de ``COLONNES``."""
        from . import coherence as CO

        p, lg, k, o, r = self.p, self.lg, l.kpi, l.org, l.reponse
        plan = p.plan().decrire(k.code)
        valide = r is not None and r.statut == Reponse.Statut.VALIDE and not l.calculee
        preuves = self.preuves.get(r.pk, []) if r is not None else []
        alertes = self.alertes.get((l.periode.pk, k.code, o.id), [])
        forcee = r is not None and r.origine == Reponse.Origine.FORCEE
        forcage = self.forcages.get((l.periode.pk, k.code, o.id)) if forcee else None
        if k.est_texte:  # réponse rédigée : un extrait en texte simple, comme le rapport de revue
            from .markdown import extrait

            def lire(x):
                return ("N/A" if x.non_applicable else extrait(x.texte)) if x else None
            valeur, n1 = lire(r), lire(l.n1)
        else:
            valeur, n1 = E.valeur_lisible(r, k), E.valeur_lisible(l.n1, k)
        numerotees = list(enumerate(alertes, 1))
        textes = [(i, f"{LB.choix_valeur(Alerte, 'controle', a.controle)} · {LB.choix_valeur(Alerte, 'gravite', a.gravite)} · "
                      f"{LB.choix_valeur(Alerte, 'statut', a.statut)} : {CO.texte_alerte(a, 'message')}") for i, a in numerotees]
        justifs = [(i, f"{_qui_quand(a.justifie_par, a.date_justification, lg)} : {a.justification}" if a.justification else "")
                   for i, a in numerotees]
        decisions = [(i, _qui_quand(a.traite_par, a.date_traitement, lg)) for i, a in numerotees]
        v = {
            "exercice": l.exercice, "periode": E.memo(p, "periode", l.periode.pk, lambda: str(l.periode)), "id": k.code,
            "indicateur": E.nom_kpi(k, lg), "referentiel": plan["referentiel"], "theme": plan["theme"],
            "sous_theme": plan["sous_theme"], "code_org": o.code, "organisation": o.nom,
            "niveau": o.niveau.tr("nom", lg), "valeur": valeur, "unite": k.symbole,
            "na": E.traduire("Oui" if r is not None and r.non_applicable else "Non", lg), "n1": n1,
            "comparaison": E.memo(p, "comparaison", l.campagne.pk if l.campagne else None,
                                   lambda: str(S.periode_comparaison(l.campagne) or "") if l.campagne else ""),
            "ecart": None if k.est_texte else E.ecart(l), "statut": _statut(l, lg),
            "origine": LB.choix_valeur(Reponse, "origine", r.origine) if r is not None else "",
            "forcee": E.traduire("Oui" if forcee else "Non", lg),
            "forcage": libelle("suivi.export.audit.forcage_texte", justification=forcage.justification,
                               demandeur=_qui(forcage.demandeur), date_demande=DC.date_heure_courte(forcage.date_demande, lg),
                               traite_par=_qui(forcage.traite_par), date_traitement=DC.date_heure_courte(forcage.date_traitement, lg),
                               calculee="—" if forcage.valeur_calculee is None else str(X.nombre(forcage.valeur_calculee)))
            if forcage is not None else "",
            "commentaire": r.commentaire if r is not None else "", "saisi_par": _qui(r.saisi_par) if r is not None else "",
            "date_maj": r.date_maj if r is not None and not l.calculee else None,
            "valide_par": _qui(r.valide_par) if valide else "", "date_validation": r.date_validation if valide else None,
            "nb_preuves": len(preuves), "preuves": " | ".join(f"{_nom_fichier(pr)} ({_taille(pr.taille)})" for pr in preuves),
            "nb_alertes": len(alertes), "alertes": _numerote(textes), "justifications": _numerote(justifs),
            "decisions": _numerote(decisions),
            "confidentialite": LB.choix_valeur(KPI, "confidentialite", k.confidentialite),
        }
        return [v[c] for c, _, _ in COLONNES]


def _nombre(brut):
    """Valeur du journal : un vrai nombre dans Excel quand c'en est un, sinon le texte."""
    try:
        d = Decimal(brut)
        return float(d) if d.is_finite() else brut
    except (InvalidOperation, ValueError, TypeError):
        return brut


def historique(lignes, limite=MAX_LIGNES_HISTORIQUE):
    """(entrées du journal des cases exportées, de la plus ancienne à la plus récente ; coupé ?), libellées comme la page
    Historique (``administration.libeller_journal``), par lots."""
    from .administration import libeller_journal

    ids = sorted({str(l.reponse.pk) for l in lignes if l.reponse is not None})
    entrees = []
    for i in range(0, len(ids), LOT):
        entrees += list(Journal.objects.filter(objet="Reponse", objet_id__in=ids[i:i + LOT]).select_related("utilisateur"))
    entrees.sort(key=lambda e: (e.date, e.pk))
    coupe = len(entrees) > limite
    entrees = entrees[:limite]
    for i in range(0, len(entrees), 5000):
        libeller_journal(entrees[i:i + 5000])
    return entrees, coupe


def classeur(lignes, p, utilisateur):
    """« À lire », puis l'onglet des cases, l'historique de ces cases et les fichiers de preuve."""
    exiger(utilisateur)
    lg = p.langue
    wb = X.classeur(ecriture_seule=True)
    contexte = Contexte(utilisateur, p, lignes)
    idx = {c: i for i, (c, _, _) in enumerate(COLONNES)}
    formats = {}

    def cases():
        for l in lignes:
            if l.kpi.code not in formats:
                f = X.format_nombre_du_kpi(l.kpi)
                formats[l.kpi.code] = {idx["valeur"]: f, idx["n1"]: f, idx["ecart"]: FORMAT_ECART,
                                       idx["date_maj"]: E.FORMAT_DATE_HEURE, idx["date_validation"]: E.FORMAT_DATE_HEURE}
            yield contexte.ligne(l), formats[l.kpi.code]
    E.onglet_flux(wb, E.texte_fichier(p, "suivi.export.audit.onglet.cases"), entetes(p), [r for _, _, r in COLONNES],
                   [w for _, w, _ in COLONNES], "J2", "Audit", cases,
                   bulle=(idx["valeur"], E.texte_fichier(p, "suivi.export.audit.bulle_valeur"), 90))

    entrees, coupe = historique(lignes)
    tetes = [E.texte_fichier(p, f"suivi.export.audit.hist.{c}") for c in (
        "numero", "date", "auteur", "action", "case", "periode", "id", "code_org", "champ", "avant", "apres")]
    systeme = libelle("admin.journal.systeme")

    def histoire():
        for e in entrees:
            champ = e.libelle_champ if e.champ else ""
            avant, apres = e.avant_lisible, e.apres_lisible
            if e.champ == "valeur":
                avant, apres = (_nombre(e.avant) if e.avant else ""), (_nombre(e.apres) if e.apres else "")
            yield [e.numero, e.date, str(e.utilisateur) if e.utilisateur else systeme, e.libelle_action, e.libelle_objet,
                   e.periode_texte, e.code_kpi, e.code_org, champ[:1].upper() + champ[1:], avant, apres], {1: E.FORMAT_DATE_HEURE}
    E.onglet_flux(wb, E.texte_fichier(p, "suivi.export.audit.onglet.historique"), tetes, ["cle"] + ["info"] * (len(tetes) - 1),
                   [10, 17, 26, 26, 50, 12, 11, 14, 24, 40, 40], "B2", "History", histoire)

    pieces = [(l, pr) for l in lignes if l.reponse is not None for pr in contexte.preuves.get(l.reponse.pk, [])]
    tetes = [E.texte_fichier(p, f"suivi.export.audit.preuve.{c}") for c in (
        "periode", "id", "indicateur", "code_org", "organisation", "fichier", "taille", "depose_par", "date_depot")]

    def preuves():
        for l, pr in pieces:
            yield [str(l.periode), l.kpi.code, E.nom_kpi(l.kpi, lg), l.org.code, l.org.nom, _nom_fichier(pr), pr.taille,
                   _qui(pr.depose_par), pr.date_depot], {6: "#,##0", 8: E.FORMAT_DATE_HEURE}
    E.onglet_flux(wb, E.texte_fichier(p, "suivi.export.audit.onglet.preuves"), tetes, ["cle"] * 2 + ["info"] * (len(tetes) - 2),
                   [13, 11, 50, 14, 24, 40, 12, 26, 17], "C2", "Evidence", preuves)

    def tt(cle, **kw):
        return E.texte_fichier(p, cle, **kw)
    paragraphes = [
        (tt("suivi.export.audit.lire.cases_titre"), tt("suivi.export.audit.lire.cases_texte")),
        (tt("suivi.export.audit.lire.historique_titre"), tt("suivi.export.audit.lire.historique_texte", n=len(entrees))),
        (tt("suivi.export.audit.lire.preuves_titre"), tt("suivi.export.audit.lire.preuves_texte", n=len(pieces))),
        (tt("suivi.export.audit.lire.alertes_titre"), tt("suivi.export.audit.lire.alertes_texte")),
        (tt("suivi.export.audit.lire.lecture_seule_titre"), tt("suivi.export.audit.lire.lecture_seule_texte")),
        (tt("suivi.export.audit.lire.version"), settings.VERSION),
    ]
    if coupe:
        paragraphes.insert(2, (tt("suivi.export.audit.lire.coupe_titre"), tt("suivi.export.audit.lire.coupe_texte", n=len(entrees))))
    E.a_lire(wb, p, utilisateur, len(lignes), paragraphes, exemples=[e[:7] for e in X.exemples_roles(lg)[1:]])
    return wb


def contenu_tabulaire(utilisateur, lignes, p, limite=None):
    """Onglet des cases en tableau simple (CSV, aperçu du constructeur) ; l'historique et les preuves ne sont que dans Excel."""
    exiger(utilisateur)
    gardees = lignes[:limite]
    contexte = Contexte(utilisateur, p, gardees)
    return [entetes(p)] + [contexte.ligne(l) for l in gardees]
