"""Import des valeurs depuis Excel ou CSV (cahier des charges, section 4.6) et modèles d'import pré-remplis.

Tout import passe par un aperçu : ``analyser`` ne modifie rien et classe chaque ligne (à créer, à modifier, inchangée,
vide, rejetée avec son motif). ``appliquer`` refait l'analyse puis enregistre les lignes valides.

Règles :
- reconnus : le modèle de l'outil, l'export « base de données » et le format historique (Id, Organisation, Résultat…) ;
- organisations reconnues par leur nom ou un libellé d'import (alias) ;
- une cellule vide n'efface rien : ni la valeur, ni le commentaire ;
- la période vient de la colonne « Période » (« 2026 », « T1 2026 », « mars 2026 »…), sinon de la colonne « Exercice »
  (période annuelle), sinon de la campagne choisie à l'envoi ; la campagne est celle de cette période qui contient le KPI
  (la campagne ouverte d'abord quand deux campagnes de la période le contiennent ; une colonne Référentiel désigne la sienne) ;
- campagne ouverte : mêmes droits et mêmes règles qu'à l'écran (les valeurs passent en brouillon, ou sont validées
  si demandé et si les contrôles le permettent) ; une valeur cumulée à partir de périodes plus courtes ne s'importe pas ;
- campagne clôturée : réservé à l'admin, pour l'historique ; les valeurs sont marquées « import » et ne remplacent
  jamais une valeur saisie dans l'outil ;
- KPI calculé : ignoré dans une période clôturée (ou figé par une campagne clôturée de la période) ; dans une période
  non clôturée, un chiffre différent de la case devient une valeur forcée (``forcage.demander``), seulement pour qui
  peut forcer la case et seulement si la personne l'a confirmé dans l'aperçu (``appliquer(forcer=…)``) : aucun chiffre
  importé ne reste « en sommeil » sur une case calculée d'une période ouverte.
"""
from types import SimpleNamespace
import datetime
import re
from dataclasses import dataclass, field

from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone
from openpyxl.formatting.rule import FormulaRule  # noqa: F401
from openpyxl.utils import get_column_letter  # noqa: F401
from openpyxl.worksheet.datavalidation import DataValidation  # noqa: F401

from parametres import niveaux as N
from parametres import libelles as LB
from parametres.libelles import libelle
from referentiel.models import KPI, ElementReferentiel, Frequence, Organisation, OrgAlias, Referentiel
from referentiel.plans import Plan

from . import dates_courtes as DC
from . import fichiers as X
from . import periodes as P
from . import saisie as S
from .exports import langue_export, nom_kpi, traduire, valeur_fichier
from .lots import par_lots
from .models import VALEUR_MAX, Campagne, Journal, Reponse, valeur_enregistree
from .signals import en_lot, signaler
from .statistiques_postgresql import statistiques_a_jour
# Fichier à remplir : déplacé dans imports_modele.py ; ces noms restent accessibles ici (appelants, tests).
from .imports_modele import (  # noqa: F401
    LARGEUR_VALEUR_TEXTE, LIRE, a_lire, nombre_affiche,
    campagnes_en_cours_de, colonnes_a_remplir, format_nombre_kpi, lignes_modele, lignes_modele_en_cours, modele, modele_vierge,
    TOUS, choix_modele, estimer_cellules, fichier_a_remplir,
)
from .styles_excel import Alignment, Font, PatternFill  # noqa: F401
from espaces import contexte as ESP

# En-têtes reconnus à la lecture : ceux d'avant les fichiers de langue (anciens modèles, format historique) et, pour chaque
# colonne, le texte de son libellé dans TOUTES les langues (français, anglais, espagnol…), quelle que soit la langue du fichier.
_ALIAS = {
    "kpi": (["ID KPI", "Code KPI", "ID", "Id", "KPI ID", "KPI code", "Indicator ID"],
            ("suivi.remplir.colonne.kpi", "suivi.export.colonne.id")),
    "organisation": (["Organisation", "Organization"], ("suivi.remplir.colonne.organisation", "suivi.export.colonne.organisation")),
    "code_org": (["Code organisation", "Organisation code", "Organization code"], ("suivi.export.colonne.code_org",)),
    "exercice": (["Exercice", "Year", "Année", "Exercise"], ("suivi.remplir.colonne.exercice", "suivi.export.colonne.exercice")),
    "periode": (["Période", "Period", "Mois", "Month"], ("suivi.remplir.colonne.periode", "suivi.export.colonne.periode")),
    "valeur": (["Valeur", "Value", "Résultat", "Result"], ("suivi.remplir.colonne.valeur", "suivi.export.colonne.valeur")),
    "na": (["N/A", "NA", "Non applicable"], ("suivi.remplir.colonne.na", "suivi.export.colonne.na")),
    "commentaire": (["Commentaire", "Comment", "Commentaire réseau"],
                    ("suivi.remplir.colonne.commentaire", "suivi.export.colonne.commentaire")),
    "referentiel": (["Référentiel", "Framework"], ("suivi.remplir.colonne.referentiel", "suivi.export.colonne.referentiel")),
    "origine": (["Ligne d'origine", "Original line"], ()),  # repère dans le fichier d'origine (rapport des rejets, reprise)
}
REQUISES = ("kpi", "organisation", "valeur")
ACTIONS = ("creer", "modifier", "forcer", "inchange", "ignore", "rejet")


def colonnes_import():
    """{clé: [en-têtes acceptés]} de l'import, dans toutes les langues."""
    sortie = {}
    for cle, (anciens, cles) in _ALIAS.items():
        alias = list(anciens)
        for c in cles:
            alias += [t for t in X.tous_les_textes(c) if t not in alias]
        sortie[cle] = alias
    return sortie


def onglets_prioritaires():
    """Noms d'onglets (normalisés) lus en premier : « Saisie », « Valeurs »… dans toutes les langues."""
    noms = {"saisie", "input", "valeurs", "values", "extract", "csv"}
    for cle in ("suivi.remplir.onglet_saisie", "suivi.export.onglet.valeurs"):
        noms |= {X.normaliser(t) for t in X.tous_les_textes(cle)}
    return noms


@dataclass
class LigneImport:
    numero: int
    kpi_id: str
    organisation: str
    exercice: int | None
    periode: str = ""  # libellé affiché dans l'aperçu
    action: str = "rejet"
    motif: str = ""
    avant: str = ""
    apres: str = ""
    # résolu pendant l'analyse
    kpi: KPI | None = None
    org: Organisation | None = None
    campagne: Campagne | None = None
    valeur: object = None
    texte: str = ""  # réponse oui / non ou liste
    na: bool = False
    commentaire: str | None = None
    onglet: str = ""  # onglet d'origine, quand le fichier en a plusieurs (un onglet par organisation)
    brut: dict = field(default_factory=dict)  # cellules telles qu'écrites (rapport des rejets)
    echec: str = ""  # refusée à l'enregistrement (droits, contrôles)
    ecrite: bool = False  # enregistrée (un import arrêté avant la fin laisse des lignes valides non écrites)
    origine: str = ""  # repère dans le fichier d'origine (colonne « Ligne d'origine »)
    cle: str = ""  # « onglet|numéro » : identifie la ligne pour les corrections faites dans l'aperçu
    corrigee: bool = False
    ecart: object = None  # écart avec N-1 au-delà du seuil de la campagne (fraction), signalé dans l'aperçu
    ambigu: str = ""  # remarque de l'aperçu : texte « 1,234 » lu avec des décimales (S.separateur_ambigu), à vérifier
    non_forcee: bool = False  # KPI calculé à forcer, sans la confirmation de la personne : ignorée à l'import
    langue_nombres: str = ""  # langue dans laquelle un nombre écrit en texte est lu (``langue_des_nombres``)

    @property
    def repere(self):
        if self.origine:
            return self.origine
        return f"{self.onglet} · {self.numero}" if self.onglet else str(self.numero)


@dataclass
class Analyse:
    onglet: str = ""
    lignes: list = field(default_factory=list)
    campagnes_a_creer: list = field(default_factory=list)  # libellés (aperçu)
    nouvelles: dict = field(default_factory=dict)  # (référentiel, type, début) → (référentiel, début)
    erreur: str = ""
    arrete: bool = False  # import arrêté par la personne entre deux paquets (import en arrière-plan)
    # langues dans lesquelles des nombres écrits en texte ont été lus : {langue: (langue, raison, en-tête, séparateur)}
    langues_nombres: dict = field(default_factory=dict)

    def compte(self, action):
        return sum(1 for l in self.lignes if l.action == action)

    @property
    def comptes(self):
        return [(a, libelle(f"suivi.importer.action.{a}"), self.compte(a)) for a in ACTIONS]

    @property
    def nombres(self):
        """{action: nombre de lignes} (aperçu : tuiles « À enregistrer » et « Rejetées », le reste en une phrase)."""
        n = {a: self.compte(a) for a in ACTIONS}
        n["a_enregistrer"] = n["creer"] + n["modifier"]
        return n

    @property
    def a_ecrire(self):
        return [l for l in self.lignes if l.action in ("creer", "modifier")]

    @property
    def a_forcer(self):
        """Lignes de KPI calculés d'une période non clôturée, à forcer si la personne le confirme."""
        return [l for l in self.lignes if l.action == "forcer"]

    @property
    def non_forcees(self):
        """Lignes de KPI calculés que la personne n'a pas confirmé vouloir forcer : ignorées à l'import."""
        return sum(1 for l in self.lignes if l.non_forcee)

    def apercu(self, limite=400):
        """Lignes à montrer : rejets d'abord, puis modifications, créations (les inchangées et ignorées sont comptées)."""
        ordre = {"rejet": 0, "forcer": 1, "modifier": 2, "creer": 3}
        visibles = sorted((l for l in self.lignes if l.action in ordre), key=lambda l: (ordre[l.action], l.numero))
        return visibles[:limite]

    @property
    def ambigus(self):
        """Lignes à écrire dont la valeur est un texte au séparateur ambigu (« 1,234 ») : avertissement, jamais un refus."""
        return sum(1 for l in self.a_ecrire if l.ambigu)

    @property
    def rejets(self):
        return [l for l in self.lignes if l.action == "rejet"]

    @property
    def lectures_nombres(self):
        """Phrases de l'aperçu : comment les nombres écrits en texte ont été lus, et pourquoi (séparateur du CSV, en-tête
        de la colonne « Valeur », ou langue de l'interface faute de mieux). Vide si le fichier n'a que des nombres d'Excel."""
        from .templatetags.collecte import separateurs

        sortie = []
        for langue, raison, entete, separateur in self.langues_nombres.values():
            nom, decimale = libelle(f"commun.langue_nom.{langue.split('-')[0]}"), separateurs(langue)[1]
            if raison == "csv":
                sortie.append(libelle("suivi.echanges.importer.apercu.nombres_csv", decimale=decimale, separateur=separateur))
            elif raison == "entete":
                sortie.append(libelle("suivi.echanges.importer.apercu.nombres_entete", nom_langue=nom, decimale=decimale,
                                      entete=entete))
            else:
                sortie.append(libelle("suivi.echanges.importer.apercu.nombres_interface", nom_langue=nom, decimale=decimale))
        return list(dict.fromkeys(sortie))

    def apercu_ecrits(self, limite=400):
        """Lignes à écrire (modifications puis créations) : les rejets sont montrés à part, à corriger."""
        return [l for l in self.apercu(limite) if l.action != "rejet"]


def correspondance_organisations():
    """Nom ou libellé d'import (sans tenir compte de la casse) → organisation."""
    d = {}
    for a in OrgAlias.objects.select_related("organisation__niveau"):
        d[a.libelle.strip().lower()] = a.organisation
    toutes = list(Organisation.objects.select_related("niveau"))
    for o in toutes:
        d[o.nom.strip().lower()] = o
        if o.nom_court:
            d.setdefault(o.nom_court.strip().lower(), o)
    for o in toutes:
        d.setdefault(o.code.lower(), o)  # code stable des exports (« Code organisation »)
    return d


def _onglets(onglets):
    """Onglets de données : tous ceux qui contiennent les colonnes attendues (« Saisie », « Valeurs »… d'abord ; un
    fichier à remplir peut avoir un onglet par organisation) : [(nom, ligne d'en-têtes, colonnes)]."""
    noms = onglets_prioritaires()
    prioritaires = [n for n in onglets if X.normaliser(n) in noms]
    colonnes = colonnes_import()
    trouves = []
    for nom in prioritaires + [n for n in onglets if n not in prioritaires]:
        i, cols = X.trouver_colonnes(onglets[nom], colonnes, REQUISES)
        if i is not None:
            trouves.append((nom, i, cols))
    return trouves


# En-têtes « Valeur » d'avant les fichiers de langue (``_ALIAS``) : leur langue
_ENTETES_VALEUR_ANCIENS = {"valeur": "fr", "resultat": "fr", "value": "en", "result": "en"}


def langue_des_nombres(entete, separateur=None):
    """Langue dans laquelle se lisent les nombres écrits en texte d'un onglet importé : (langue, raison), raison
    « csv », « entete » ou « interface » (l'aperçu la dit).

    1. CSV séparé par « ; » ou « , » (``separateur``) : le séparateur décide de la décimale. L'outil écrit ses CSV en
       style « ; » avec la virgule décimale ou en style « , » avec le point, quelle que soit la langue des en-têtes
       (un export anglais en style « ; » écrit « 12,345 ») ; un tableur fait de même selon sa langue. Langue : celle de
       l'en-tête, sinon de l'interface, sinon la première langue qui a cette décimale.
    2. Sinon (classeur Excel, CSV à tabulations), l'en-tête de la colonne « Valeur » : un fichier exporté par l'outil
       l'écrit dans la langue de l'export (« Value », « Valeur », « Wert »…). Si toutes les langues qui l'écrivent ainsi
       ont le même séparateur décimal, c'est la langue du fichier (celle de l'interface quand elle en fait partie).
    3. Sinon, la langue de l'interface de la personne qui importe."""
    from parametres.libelles import langues_disponibles

    from .templatetags.collecte import separateurs

    interface = S.langue_ecran()
    n = X.normaliser(entete)
    langues = [l for l in langues_disponibles() if n in {X.normaliser(libelle(c, l)) for c in
                                                       ("suivi.remplir.colonne.valeur", "suivi.export.colonne.valeur")}]
    if n in _ENTETES_VALEUR_ANCIENS and _ENTETES_VALEUR_ANCIENS[n] not in langues:
        langues.append(_ENTETES_VALEUR_ANCIENS[n])
    if separateur in (";", ","):
        decimale = "," if separateur == ";" else "."
        return next(l for l in [*langues, interface, *langues_disponibles(), "en" if decimale == "." else "fr"]
                    if separateurs(l)[1] == decimale), "csv"
    if langues and len({separateurs(l)[1] for l in langues}) == 1:
        return (interface if interface.split("-")[0] in langues else langues[0]), "entete"
    return interface, "interface"


def _exercice(v):
    """Exercice d'une cellule « Exercice » : 2026, « 2026 », « FY2026 », « 2026-2027 » (l'année où il commence), une date
    (son année). None si la cellule n'en contient pas : « abc », « 0000 », « FY26 » ne sont pas lus (jamais une autre
    campagne prise à la place, voir ``analyser``)."""
    if isinstance(v, (datetime.date, datetime.datetime)):
        return v.year
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return int(v) if float(v).is_integer() and 1900 <= v <= 2200 else None
    m = re.search(r"(?<!\d)(19\d\d|2[01]\d\d)(?!\d)", X.texte(v))
    return int(m.group(1)) if m else None


def _referentiels_par_nom():
    """{code, nom ou traduction normalisés: référentiel}."""
    d = {}
    for r in Referentiel.objects.all():
        for t in [r.code, r.nom] + [v.get("nom", "") for v in (r.traductions or {}).values()]:
            if t:
                d.setdefault(X.normaliser(t), r)
    return d


def _affiche(valeur, na, kpi, texte=""):
    if na:
        return "N/A"
    if texte:
        if kpi.est_texte:  # réponse rédigée : son début, en texte brut
            from .markdown import extrait

            return extrait(texte)
        return kpi.reponse_affichee(texte)
    if valeur is None:
        return "—"
    from .templatetags.collecte import formater

    return formater(valeur, kpi)


LIGNES_MAX = 50_000  # lignes d'un import (hors admin) : borne le temps de traitement d'un seul fichier


SUIVI_LECTURE = 1000  # lignes lues entre deux nouvelles de l'avancement (import en arrière-plan)


def analyser(utilisateur, fichier, campagne_defaut=None, creer_campagnes=False, onglets=None, corrections=None, suivi=None,
             langue_nombres=None):
    """Classe chaque ligne du fichier sans rien enregistrer. ``campagne_defaut`` : campagne (ou son identifiant) des
    lignes sans colonne « Période » ni « Exercice ». ``onglets`` : {nom: lignes} déjà lues (assistant de reprise), à la
    place du fichier. ``corrections`` : {« onglet|numéro »: {colonne: texte}} saisies dans l'aperçu, qui remplacent les
    cellules du fichier. ``suivi`` : avancement d'un import en arrière-plan (``suivi.lecture(n)`` toutes les
    ``SUIVI_LECTURE`` lignes lues). Nombres écrits en texte : lus dans la langue de chaque onglet
    (``langue_des_nombres``), ou dans ``langue_nombres`` si elle est donnée (assistant de reprise : fichier d'un autre
    système) ; une valeur corrigée dans l'aperçu, tapée à l'écran, se lit comme à l'écran."""
    a = Analyse()
    try:
        onglets = X.lire(fichier) if onglets is None else onglets
    except X.FichierInvalide as e:
        a.erreur = str(e)
        return a
    feuilles = _onglets(onglets)
    if not feuilles:
        # un export « Tableau » ou « Revue » de l'outil (onglet « À lire » et colonne « ID KPI », sans « Valeur » ni
        # « Organisation » en colonnes) : le dire plutôt que « colonnes introuvables » (il se lit, il ne se réimporte pas)
        cles, a_lire = colonnes_import(), {X.normaliser(n) for n in X.tous_les_textes("suivi.fichier.a_lire")}
        lisible = any(X.normaliser(n) in a_lire for n in onglets) and any(
            X.trouver_colonnes(lignes, cles, ("kpi",))[0] is not None for lignes in onglets.values())
        a.erreur = libelle("suivi.importer.erreur.export_lisible" if lisible else "suivi.importer.erreur.colonnes")
        return a
    a.onglet = ", ".join(f[0] for f in feuilles)
    langues_onglets = {}  # onglet → (langue des nombres écrits en texte, raison, en-tête « Valeur », séparateur du CSV)
    separateur = getattr(onglets, "separateur", None)
    for nom_, entete_, cols_ in feuilles:
        ligne_ = onglets[nom_][entete_]
        texte_ = X.texte(ligne_[cols_["valeur"]]) if cols_["valeur"] < len(ligne_) else ""
        langues_onglets[nom_] = ((langue_nombres, "interface", texte_, separateur) if langue_nombres
                                 else (*langue_des_nombres(texte_, separateur), texte_, separateur))
    plusieurs = len(feuilles) > 1
    cols = {}
    if campagne_defaut is not None and not isinstance(campagne_defaut, Campagne):
        campagne_defaut = Campagne.objects.select_related("referentiel", "periode").filter(pk=campagne_defaut).first()
    kpis = {k.code: k for k in KPI.objects.select_related("granularite")}
    kpis_casse = {}
    for k in kpis.values():
        kpis_casse.setdefault(k.code.lower(), []).append(k)
    kpis_casse = {c: ks[0] for c, ks in kpis_casse.items() if len(ks) == 1}
    orgs = correspondance_organisations()
    rangs = N.rangs()
    referentiels = _referentiels_par_nom()
    membres = set(ElementReferentiel.objects.values_list("referentiel_id", "kpi_id"))
    calendrier = P.Calendrier()
    campagnes = {}  # identifiant de période → campagnes (par ordre des référentiels)
    for c in Campagne.objects.select_related("referentiel", "periode").order_by("referentiel__ordre", "referentiel_id"):
        campagnes.setdefault(c.periode_id, []).append(c)
    perimetres = {}
    annuelles = {}
    for per in calendrier.par_cle.values():
        if per.annuelle:
            annuelles.setdefault(per.debut.year, per)
    vues, existantes, libelles = {}, {}, {}
    periodes_lues = {}  # cellule « Période » → (type, début) ou None

    def rangees():
        for nom_, entete_, cols_ in feuilles:
            for n_, row_ in enumerate(onglets[nom_][entete_ + 1:], start=entete_ + 2):
                yield nom_, n_, row_, cols_

    corr = {}

    fichier = {}

    def codes_du_fichier():
        """Codes des KPI cités par les lignes du fichier (corrections de l'aperçu comprises), comme la boucle les résout."""
        codes = set()
        for onglet_, n_, row_, cols_ in rangees():
            c_ = (corrections or {}).get(f"{onglet_}|{n_}", {})
            i_ = cols_.get("kpi")
            kid_ = X.texte(c_["kpi"] if "kpi" in c_ else row_[i_] if i_ is not None and i_ < len(row_) else None)
            k_ = kpis.get(kid_) or kpis_casse.get(kid_.lower())
            if k_ is not None:
                codes.add(k_.code)
        return codes

    def existante(periode, l):
        """Réponse déjà enregistrée pour la case de la ligne (lues une fois par période)."""
        if periode is None:
            return None
        if periode.pk not in existantes:
            if "codes" not in fichier:  # KPI cités par le fichier : seules leurs réponses sont lues (pas toute la période)
                fichier["codes"] = codes_du_fichier()
            existantes[periode.pk] = {(r.kpi_id, r.organisation_id): r for lot in par_lots(sorted(fichier["codes"]))
                                      for r in Reponse.objects.filter(periode=periode, kpi_id__in=lot)}
        return existantes[periode.pk].get((l.kpi.code, l.org.id))

    def en_base(periode, l):
        r = existante(periode, l)
        return r.valeur if r is not None else None

    def cell(row, cle):
        if cle in corr:
            return corr[cle]
        i = cols.get(cle)
        return row[i] if i is not None and i < len(row) else None

    def lue(cle):
        return cle in cols or cle in corr

    def perimetre(c):
        if c.pk not in perimetres:
            codes = S.codes_campagne(c)
            perimetres[c.pk] = None if codes is None else codes[1]
        return perimetres[c.pk]

    limite = None if utilisateur.est_admin else LIGNES_MAX
    for lues, (onglet, n, row, cols) in enumerate(rangees(), start=1):
        if suivi is not None and lues % SUIVI_LECTURE == 0:
            suivi.lecture(lues)
        corr = (corrections or {}).get(f"{onglet}|{n}", {})
        kid, org_nom = X.texte(cell(row, "kpi")), X.texte(cell(row, "organisation"))
        if not kid and not org_nom:
            continue
        brut_exercice = cell(row, "exercice") if lue("exercice") else None
        exercice = _exercice(brut_exercice) if X.texte(brut_exercice) else None
        brut_periode = cell(row, "periode") if lue("periode") else None
        l = LigneImport(n, kid, org_nom, exercice, onglet=onglet if plusieurs else "",
                        origine=X.texte(cell(row, "origine")) if "origine" in cols else "", cle=f"{onglet}|{n}",
                        corrigee=bool(corr))
        if limite is not None and len(a.lignes) >= limite:  # au-delà : refusé avant tout travail (serveur partagé)
            a.lignes, a.erreur = [], libelle("suivi.importer.erreur.trop_long", limite=nombre_affiche(limite, 0))
            return a
        l.brut = {c: X.texte(cell(row, c)) for c in ("kpi", "organisation", "periode", "exercice", "valeur", "na", "commentaire",
                                                         "referentiel") if lue(c)}
        a.lignes.append(l)
        brut = cell(row, "valeur")
        # langue des nombres écrits en texte : celle de l'onglet ; une valeur corrigée dans l'aperçu se lit comme à l'écran
        langue_ligne = l.langue_nombres = S.langue_ecran() if "valeur" in corr else langues_onglets[onglet][0]
        l.na = X.oui(cell(row, "na")) or X.normaliser(brut) == "na"
        com = X.texte(cell(row, "commentaire")) if lue("commentaire") else ""
        l.commentaire = com or None  # vide : le commentaire existant est gardé
        # KPI, organisation, période
        l.kpi = kpis.get(kid) or kpis_casse.get(kid.lower())  # « fe0001 » pour « FE0001 » (un seul KPI s'écrit ainsi)
        if l.kpi is None:
            l.motif = libelle("suivi.importer.motif.kpi_inconnu", kpi=kid)
            continue
        kid = l.kpi_id = l.kpi.code
        ref_nom = X.texte(cell(row, "referentiel")) if "referentiel" in cols else ""
        ref_colonne = None
        if ref_nom:  # colonne de contrôle : le KPI doit être dans ce référentiel (la valeur reste unique)
            ref_colonne = referentiels.get(X.normaliser(ref_nom))
            if ref_colonne is None:
                l.motif = libelle("suivi.importer.motif.referentiel_inconnu", referentiel=ref_nom)
                continue
            if (ref_colonne.code, kid) not in membres:
                l.motif = libelle("suivi.importer.motif.pas_dans_referentiel", referentiel=ref_colonne)
                continue
        code_org = X.texte(cell(row, "code_org")) if "code_org" in cols else ""
        l.org = (orgs.get(code_org.lower()) if code_org else None) or orgs.get(org_nom.lower())
        if l.org is None:
            l.motif = libelle("suivi.importer.motif.organisation_inconnue", organisation=org_nom)
            continue
        if l.kpi.est_calcule:  # case d'un KPI calculé : son niveau, ou un total au-dessus s'il s'agrège (``cellules_calculees``)
            rang_o, rang_k = rangs[l.org.niveau_id], rangs[l.kpi.granularite_id]
            if rang_o > rang_k:
                l.motif = libelle("suivi.importer.motif.autre_niveau", niveau=l.kpi.granularite.nom, autre=l.org.niveau.nom)
                continue
            if rang_o < rang_k and l.kpi.methode_agregation == KPI.Agregation.AUCUNE:
                l.action, l.motif = "ignore", libelle("suivi.importer.motif.kpi_calcule")
                continue
        # sinon : saisie au-dessus, ou paramètre hérité porté par l'organisation faute d'ancêtre de son niveau (CALC-09)
        elif not l.kpi.se_saisit_a(l.org, rangs) and not S.au_dessus(l.kpi, l.org, rangs):
            if rangs[l.org.niveau_id] < rangs[l.kpi.granularite_id]:  # au-dessus de la granularité (rang 1 = sommet)
                l.action, l.motif = "ignore", libelle("suivi.importer.motif.total_agrege")
            else:
                l.motif = libelle("suivi.importer.motif.autre_niveau", niveau=l.kpi.granularite.nom, autre=l.org.niveau.nom)
            continue
        if X.texte(brut_exercice) and exercice is None and not X.texte(brut_periode):
            # « Exercice » rempli mais illisible (« abc », « FY26 ») : refusé, jamais rangé dans la campagne par défaut
            l.motif = libelle("suivi.importer.motif.exercice_illisible", exercice=X.texte(brut_exercice))
            continue
        if X.texte(brut_periode):
            if brut_periode not in periodes_lues:  # même libellé sur des milliers de lignes : lu une fois
                periodes_lues[brut_periode] = P.lire(brut_periode)
            cle_p = periodes_lues[brut_periode]
            if cle_p is None:
                l.motif = libelle("suivi.importer.motif.periode_illisible", periode=X.texte(brut_periode))
                continue
        elif exercice:
            per = annuelles.get(exercice)
            cle_p = (per.type, per.debut) if per else (Frequence.ANNEE, datetime.date(exercice, 1, 1))
        elif campagne_defaut is not None:
            cle_p = (campagne_defaut.periode.type, campagne_defaut.periode.debut)
        else:
            l.motif = libelle("suivi.importer.motif.periode_manquante")
            continue
        periode = calendrier.trouver(*cle_p)
        if periode is not None and periode.pk not in libelles:  # libellé traduit : lu une fois par période
            libelles[periode.pk] = str(periode)
        l.periode = libelles[periode.pk] if periode else P.libelle(*cle_p)
        l.exercice = l.exercice or (cle_p[1].year if cle_p[0] == Frequence.ANNEE else None)
        candidates = campagnes.get(periode.pk, []) if periode else []
        if ref_colonne is not None:
            candidates = [c for c in candidates if c.referentiel_id == ref_colonne.pk] or candidates
        # KPI commun à deux campagnes de la période : la campagne ouverte d'abord, puis
        # l'ordre des référentiels (deux ouvertes, ou deux closes : comme avant) ; tri stable
        candidates = sorted(candidates, key=lambda c: c.statut != Campagne.Statut.OUVERTE)
        l.campagne = next((c for c in candidates if perimetre(c) is None or kid in perimetre(c)), None) or next(iter(candidates), None)
        if l.campagne is None:
            if not (creer_campagnes and utilisateur.est_admin):
                l.motif = libelle("suivi.importer.motif.aucune_campagne", periode=l.periode)
                continue
            ref = _referentiel_pour(kid, cle_p[0], ref_colonne, membres)
            if ref is None:
                l.motif = libelle("suivi.importer.motif.aucun_referentiel", frequence=LB.choix_valeur_phrase(Referentiel, "frequence", cle_p[0]),
                                  periode=l.periode)
                continue
            cle_n = (ref.pk, *cle_p)
            if cle_n not in a.nouvelles:
                a.nouvelles[cle_n] = (ref, cle_p[1])
                a.campagnes_a_creer.append(f"{ref} · {l.periode}")
            l.campagne = Campagne(referentiel=ref, statut=Campagne.Statut.CLOTUREE, exercice=P.exercice_de(cle_p[1], ref.mois_debut))
            l.campagne.cle_nouvelle = cle_n
            # période pas encore créée : ses dates, pour le contrôle d'ouverture des organisations (``organisation_pas_ouverte``)
            l.campagne.periode_a_creer = SimpleNamespace(pk=None, debut=cle_p[1], fin=P.fin_de(cle_p[0], cle_p[1]), libelle=l.periode)
        # valeur
        if not l.na and not l.kpi.est_numerique:  # oui / non, liste
            try:
                with S.nombres_lus_en(langue_ligne):  # colonnes nombre d'un tableau
                    _, l.texte = S.lire_reponse(X.texte(brut), l.kpi)
            except ValidationError as e:
                l.motif = " ".join(e.messages)
                continue
            if not l.texte:
                l.action, l.motif = "ignore", libelle("suivi.importer.motif.valeur_vide")
                continue
        elif not l.na:
            pourcent_excel = isinstance(brut, X.PourcentExcel)  # « 12,5 % » tapé dans Excel : rangé 0,125
            if (pourcent_excel or isinstance(brut, str) and brut.strip().endswith("%") and brut.strip() != "%") \
                    and not l.kpi.est_pourcentage:
                l.motif = S.motif_signe_pourcent(l.kpi)
                continue
            try:
                v = X.lire_nombre_importe(brut, langue_ligne)
            except ValueError:
                l.motif = libelle("suivi.importer.motif.non_numerique", valeur=X.texte(brut))
                continue
            if v is None:
                l.action, l.motif = "ignore", libelle("suivi.importer.motif.valeur_vide")
                continue
            if pourcent_excel:
                v = v * 100
            if abs(v) >= VALEUR_MAX:
                l.motif = libelle("suivi.importer.motif.trop_grand")
                continue
            if l.kpi.est_entier and v != v.to_integral_value() and v != en_base(periode, l):
                # comptage : pas de décimale ; sauf la valeur déjà enregistrée, relue telle
                # quelle (export « Base de données » réimporté sans changement : « identique », pas rejetée)
                l.motif = libelle("suivi.importer.motif.entier", unite=l.kpi.symbole, valeur=X.texte(brut))
                continue
            if l.kpi.est_pourcentage:
                if not 0 <= v <= 100 and not l.kpi.est_calcule:  # valeur forcée d'un calcul : sans borne, comme à l'écran
                    l.motif = libelle("suivi.importer.motif.pourcentage")
                    continue
                v = v / 100
            l.valeur = valeur_enregistree(v)
            if isinstance(brut, str) and brut.strip():  # nombre écrit en texte : l'aperçu dit dans quelle langue il est lu
                a.langues_nombres.setdefault(langue_ligne, langues_onglets[onglet] if "valeur" not in corr
                                             else (langue_ligne, "interface", "", None))
            l.ambigu = remarque_ambigu(brut, langue_ligne)
        cle = (*cle_p, l.kpi.code, l.org.id)
        if cle in vues:  # seules les lignes valides comptent
            l.motif = libelle("suivi.importer.motif.doublon", ligne=vues[cle])
            continue
        vues[cle] = l.repere
        _comparer(utilisateur, l, existante(periode, l))
    return a


def remarque_ambigu(brut, langue):
    """Remarque de l'aperçu pour un texte au séparateur ambigu (« 1,234 » : S.separateur_ambigu), lu dans ``langue`` :
    « lu 1 234, pas 1,234 : à vérifier » (en anglais), « lu 1,234, pas 1 234 » ailleurs ; "" sinon. Jamais un refus."""
    lectures = S.lectures_ambigues(brut)
    if not lectures:
        return ""
    entier, decimales = re.split(r"[.,]", brut.strip().lstrip("+-"))
    milliers = X.lire_nombre_importe(brut, langue).copy_abs() == int(entier + decimales)
    lu, autre = lectures if milliers else lectures[::-1]
    return libelle("suivi.echanges.importer.a_importer.ambigu", saisie=brut.strip(), lu=lu, autre=autre)


def _referentiel_pour(kid, type_, ref_colonne, membres):
    """Référentiel actif de cette fréquence pour créer une campagne d'historique : celui de la colonne Référentiel, sinon
    le premier qui contient le KPI, sinon le premier de cette fréquence."""
    qs = Referentiel.objects.filter(actif=True, frequence=type_)
    if ref_colonne is not None:
        return qs.filter(pk=ref_colonne.pk).first()
    return next((r for r in qs if (r.code, kid) in membres), None) or qs.first()


def _comparer_calcule(utilisateur, l, r):
    """Ligne d'un KPI calculé. Période clôturée, ou KPI figé par une campagne clôturée de la période : ignorée, comme
    avant (l'outil le calcule ; l'import d'historique ne touche pas aux calculs). Période non clôturée : la valeur
    importée deviendra une valeur forcée (action « forcer »), si elle diffère de la case et si la personne peut forcer
    cette case aujourd'hui (``forcage.peut_trancher``, mêmes droits que le panneau de saisie) ; sinon, refusée."""
    from . import forcage as FO

    c = l.campagne
    if (c.statut == Campagne.Statut.CLOTUREE or not c.pk or not l.kpi.est_numerique
            or S.motif_cloturee_ailleurs(c, l.kpi)):
        l.action, l.motif = "ignore", libelle("suivi.importer.motif.kpi_calcule")
        return
    if not S.dans_la_campagne(c, l.kpi):
        l.motif = S.motif_pas_demande(utilisateur, c, l.kpi)[0] or libelle("suivi.importer.motif.hors_perimetre")
        return
    pas_ouverte, _ = S.organisation_pas_ouverte(utilisateur, c, l.org)
    if pas_ouverte:
        l.motif = pas_ouverte
        return
    remplie = r is not None and (r.valeur is not None or r.non_applicable)
    if remplie and (r.valeur, r.non_applicable) == (None if l.na else l.valeur, l.na):
        # même chiffre que la case (export « Base de données » relu tel quel) : rien à forcer
        if r.origine == Reponse.Origine.FORCEE:
            l.avant = l.apres = _affiche(r.valeur, r.non_applicable, l.kpi)
            l.action = "inchange"
        else:
            l.action, l.motif = "ignore", libelle("suivi.importer.motif.kpi_calcule")
        return
    if not FO.peut_trancher(utilisateur, c, l.kpi, l.org):
        # organisation fermée (désactivée) : personne ne force sa case ; sinon, le droit manque à la personne
        l.motif = libelle("suivi.importer.motif.calcule_org_fermee" if not l.org.actif else "suivi.importer.motif.calcule_sans_droit")
        return
    l.avant = _affiche(r.valeur, r.non_applicable, l.kpi) if remplie else "—"
    l.apres = _affiche(l.valeur, l.na, l.kpi)
    l.action, l.motif = "forcer", libelle("suivi.importer.motif.calcule_forcer")


def _comparer(utilisateur, l, r):
    """Droits et comparaison avec la réponse existante ``r``."""
    if l.kpi.est_calcule:
        _comparer_calcule(utilisateur, l, r)
        return
    cloturee = l.campagne.statut == Campagne.Statut.CLOTUREE
    commentaire = l.commentaire if l.commentaire is not None else (r.commentaire if r else "")
    identique = r is not None and (r.valeur, r.texte, r.non_applicable, r.commentaire) == (
        None if l.na else l.valeur, "" if l.na else l.texte, l.na, commentaire)
    if not cloturee and S.cumule(l.campagne, l.kpi):
        # valeur cumulée identique à celle en base (export « Base de données » relu tel quel) : inchangée, rien à écrire ;
        # seulement pour qui voit cette valeur (sinon l'aperçu dirait si un chiffre deviné est le bon). Différente : refusée.
        if identique and S.droits(utilisateur, l.campagne, l.kpi, l.org, r).voir:
            l.avant = l.apres = _affiche(r.valeur, r.non_applicable, l.kpi, r.texte)
            l.action = "inchange"
            return
        l.motif = libelle("suivi.importer.motif.cumulee")
        return
    if cloturee:
        if not utilisateur.est_admin:
            l.motif = l.campagne.motif_lecture_seule
            return
        if l.campagne.pk and not S.dans_la_campagne(l.campagne, l.kpi):  # KPI pas demandé dans cette période : rien à y corriger
            l.motif = S.motif_pas_demande(utilisateur, l.campagne, l.kpi)[0] or libelle("suivi.importer.motif.hors_perimetre")
            return
        pas_ouverte, _ = S.organisation_pas_ouverte(utilisateur, l.campagne, l.org)
        if pas_ouverte:  # correction dans un exercice clos : refusée aussi (la valeur ne compterait nulle part)
            l.motif = pas_ouverte
            return
        if r and r.origine == Reponse.Origine.SAISIE and (r.valeur is not None or r.texte or r.non_applicable) and not identique:
            l.motif = libelle("suivi.importer.motif.deja_saisie")  # identique : export relu tel quel
            return
    else:
        d = S.droits(utilisateur, l.campagne, l.kpi, l.org, r)
        if not d.modifier:
            l.motif = d.motif or libelle("suivi.importer.motif.hors_perimetre")
            return
    l.avant = _affiche(r.valeur, r.non_applicable, l.kpi, r.texte) if r else "—"
    l.apres = _affiche(l.valeur, l.na, l.kpi, l.texte)
    if r is None or (r.valeur is None and not r.texte and not r.non_applicable):
        l.action = "creer"
    elif identique:
        l.action = "inchange"
    else:
        l.action = "modifier"
        if r.statut == Reponse.Statut.VALIDE and not cloturee:
            l.motif = libelle("suivi.importer.motif.repassera_brouillon")
        elif l.commentaire is not None and l.commentaire != r.commentaire and l.apres == l.avant:
            l.motif = libelle("suivi.importer.motif.commentaire_modifie")
    if l.action != "inchange" and l.na and not commentaire:  # importée, mais « Valider » la refusera : le dire dans l'aperçu
        l.motif = " ".join(m for m in (l.motif, libelle("suivi.importer.motif.na_sans_commentaire")) if m)


def _modifiees_depuis(lignes, vu_le):
    """{(période, KPI, organisation) : réponse} des cases saisies que quelqu'un a modifiées (valeur, statut…) après
    l'aperçu ``vu_le`` (les totaux recalculés ne comptent pas)."""
    if vu_le is None or not lignes:
        return {}
    qs = (Reponse.objects.filter(periode_id__in={l.campagne.periode_id for l in lignes}, date_maj__gt=vu_le)
          .exclude(origine__in=[Reponse.Origine.CALCUL, Reponse.Origine.AGREGATION, Reponse.Origine.CUMUL])
          .select_related("saisi_par", "valide_par"))
    return {(r.periode_id, r.kpi_id, r.organisation_id): r for r in qs}


PAQUET_IMPORT = 100  # lignes écrites par transaction quand l'import se fait par paquets


def appliquer(utilisateur, fichier, nom_fichier="", campagne_defaut=None, creer_campagnes=False, valider=False, onglets=None,
              transformer=None, corrections=None, vu_le=None, par_paquets=False, suivi=None, forcer=None, langue_nombres=None):
    """Enregistre les lignes valides. Renvoie (analyse, nombre écrit, avertissements). ``transformer`` : retouche de
    l'analyse avant l'écriture (motifs de la reprise). ``vu_le`` : date de l'aperçu ; une case modifiée depuis n'est pas
    écrasée (avertissement), comme dans le panneau de saisie.

    ``forcer`` : clés (« onglet|numéro ») des lignes de KPI calculés que la personne a confirmé vouloir forcer dans
    l'aperçu. Seules celles-là deviennent des valeurs forcées (``forcage.demander`` : droits revérifiés, journal, page
    « Valeurs forcées ») ; toute autre ligne à forcer (pas de confirmation, envoi direct du formulaire, ligne apparue
    depuis l'aperçu) est ignorée, et comptée (``analyse.non_forcees``).

    ``par_paquets`` (import de la page Import / Export, pendant que d'autres saisissent) : une transaction par paquet de
    ``PAQUET_IMPORT`` lignes, avec ses recalculs, au lieu d'une seule pour tout le fichier. Sous SQLite, une transaction
    tient le verrou d'écriture : un gros fichier faisait attendre toutes les saisies jusqu'à l'erreur « database is
    locked » (essai de charge). Sans ``par_paquets`` (reprise) : tout ou rien.

    ``suivi`` (import en arrière-plan, par paquets seulement) : ``suivi.lecture(n)`` pendant l'analyse,
    ``suivi.ecriture(faites, total, ecrites)`` après chaque paquet, et ``suivi.arreter()`` demandé avant chaque paquet :
    vrai, l'import s'arrête là (``analyse.arrete``) ; ce qui est écrit reste écrit."""
    a = analyser(utilisateur, fichier, campagne_defaut, creer_campagnes, onglets=onglets, corrections=corrections, suivi=suivi,
                 langue_nombres=langue_nombres)
    if transformer is not None:
        transformer(a)
    if a.erreur:
        return a, 0, []
    confirmees = set(forcer or ())
    for l in a.a_forcer:
        if l.cle not in confirmees:  # rien n'est forcé sans la confirmation de l'aperçu
            l.action, l.non_forcee, l.motif = "ignore", True, libelle("suivi.importer.motif.calcule_non_force")
    avertissements, ecrites = [], 0
    from contextlib import nullcontext

    from .calcul import kpis_lus_avant

    def ecrire(lignes):
        nonlocal ecrites
        # relu dans la transaction qui écrit : une saisie faite pendant l'aperçu (ou pendant un paquet précédent) est vue
        modifiees = _modifiees_depuis([l for l in lignes if l.campagne.pk and l.campagne.statut != Campagne.Statut.CLOTUREE],
                                      vu_le)
        for l in lignes:
            if l.campagne.statut == Campagne.Statut.CLOTUREE:
                _ecrire_historique(utilisateur, l)
            else:
                r = modifiees.get((l.campagne.periode_id, l.kpi.code, l.org.id))
                if r is not None:  # modifiée par quelqu'un pendant l'aperçu : sa saisie n'est pas écrasée
                    qui = r.valide_par if r.statut == Reponse.Statut.VALIDE and r.valide_par else r.saisi_par
                    l.echec = libelle("suivi.importer.avert.modifiee", qui=qui or libelle("suivi.importer.avert.autre_personne"),
                                      valeur=_affiche(r.valeur, r.non_applicable, l.kpi, r.texte),
                                      statut=LB.choix_phrase(r, "statut"))
                    avertissements.append(libelle("suivi.importer.avert.ligne_case", repere=l.repere, kpi=l.kpi_id,
                                                  organisation=l.org.nom, detail=l.echec))
                    continue
                if l.action == "forcer":
                    try:
                        _forcer(utilisateur, l, nom_fichier)
                    except (ValidationError, PermissionDenied) as e:
                        l.echec = " ".join(getattr(e, "messages", [str(e)]))
                        avertissements.append(libelle("suivi.importer.avert.ligne", repere=l.repere, detail=l.echec))
                        continue
                    l.ecrite = True
                    ecrites += 1
                    continue
                try:
                    saisie = l.texte or ("" if l.valeur is None else format(X.nombre(_saisie(l)), "f"))
                    S.enregistrer(utilisateur, l.campagne, l.kpi, l.org, saisie, l.na,
                                  l.commentaire if l.commentaire is not None else _commentaire_existant(l))
                except (ValidationError, PermissionDenied) as e:
                    l.echec = " ".join(getattr(e, "messages", [str(e)]))
                    avertissements.append(libelle("suivi.importer.avert.ligne", repere=l.repere, detail=l.echec))
                    continue
                if valider:
                    try:
                        S.valider(utilisateur, l.campagne, l.kpi, l.org)
                    except (ValidationError, PermissionDenied) as e:
                        avertissements.append(libelle("suivi.importer.avert.gardee_brouillon", repere=l.repere, kpi=l.kpi_id,
                                                      organisation=l.org.nom, detail=" ".join(getattr(e, "messages", [str(e)]))))
            l.ecrite = True
            ecrites += 1

    a_ecrire = [l for l in a.lignes if l.action in ("creer", "modifier", "forcer")]
    taille = PAQUET_IMPORT if par_paquets else max(1, len(a_ecrire))
    with kpis_lus_avant(), (nullcontext() if par_paquets else ESP.atomic()):
        with ESP.atomic():
            for cle, (ref, debut) in a.nouvelles.items():
                c, _ = P.campagne(ref, debut, statut=Campagne.Statut.CLOTUREE)
                Journal.ecrire(utilisateur, "creation_campagne", c, "statut", "", "clôturée (import d'historique)")
                for l in a.lignes:
                    if l.campagne is not None and getattr(l.campagne, "cle_nouvelle", None) == cle:
                        l.campagne = c
        if suivi is not None:
            suivi.ecriture(0, len(a_ecrire), 0)
        for i in range(0, len(a_ecrire), taille):
            if suivi is not None and par_paquets and suivi.arreter():
                a.arrete = True
                break
            with ESP.atomic(), en_lot():
                ecrire(a_ecrire[i:i + taille])
            if suivi is not None:
                suivi.ecriture(min(i + taille, len(a_ecrire)), len(a_ecrire), ecrites)
        if ecrites:  # tout refusé : rien n'est écrit, pas même le journal
            cible = next((l.campagne for l in a_ecrire), None) or utilisateur  # le journal affiche la campagne
            Journal.ecrire(utilisateur, "import_valeurs", cible, "fichier", "",
                           f"{nom_fichier} : {ecrites} valeur(s)" + (" (arrêté avant la fin)" if a.arrete else ""))
            if not par_paquets:  # reprise, tout ou rien : une seule transaction (par paquets : chacun est validé à part)
                # PostgreSQL : ANALYZE après la validation (test : collecte/test_statistiques_a_jour_reprise_postgresql.py)
                statistiques_a_jour()
    return a, ecrites, avertissements


def signaler_ecarts(analyse):
    """Avant l'import : marque (``l.ecart``) les lignes dont la valeur s'écarte de N-1 au-delà du seuil de leur campagne
    (campagnes ouvertes seulement), comme la Saisie le fait. Renvoie (nombre de lignes, seuils en % rencontrés)."""
    par_campagne = {}
    for l in analyse.a_ecrire:
        c = l.campagne
        if (c is not None and c.pk and c.statut != Campagne.Statut.CLOTUREE and c.seuil_ecart is not None
                and l.kpi is not None and l.kpi.est_numerique and l.valeur is not None and not l.na):
            par_campagne.setdefault(c, []).append(l)
    n, seuils = 0, set()
    for c, lignes in par_campagne.items():
        n1 = S.valeurs_n1(c, {(l.kpi.code, l.org.id) for l in lignes})
        for l in lignes:
            r = n1.get((l.kpi.code, l.org.id))
            e = S.ecart(X.nombre(l.valeur), r.valeur) if r is not None and not r.non_applicable else None
            if S.depasse_seuil(e, c.seuil_ecart):
                l.ecart = e
                n += 1
                seuils.add(int(c.seuil_ecart * 100))
    return n, sorted(seuils)


def point_a_completer(campagne, kpi, org, detail):
    """Une valeur importée qui ne pourra pas être validée telle quelle : nom du KPI, organisation, raison et lien vers sa
    case (fin d'import: des codes seuls obligeaient à les rechercher dans la Saisie). Un dict
    (gardé tel quel dans le résultat d'un import en arrière-plan) ; les anciens résultats en texte restent lisibles."""
    from django.urls import reverse

    return {"kpi": kpi.code, "nom": kpi.nom, "organisation": org.nom, "detail": detail,
            "url": reverse("collecte:cellule", args=[campagne.pk, kpi.code, org.id])}


def etat_importees(analyse):
    """Après l'import : combien de valeurs sont validées, combien restent en brouillon (``validables`` : [campagne, KPI,
    organisation] qui passeront « Valider ces N valeurs » ; ``a_completer`` : ce qui ne passera pas, et pourquoi),
    combien sont allées dans l'historique (campagnes clôturées). Seules les lignes écrites comptent."""
    ecrites = [l for l in analyse.a_ecrire if l.ecrite and l.campagne is not None]
    ouvertes = [l for l in ecrites if l.campagne.statut != Campagne.Statut.CLOTUREE]
    statuts = {(r.periode_id, r.kpi_id, r.organisation_id): r.statut for r in Reponse.objects.filter(
        periode_id__in={l.campagne.periode_id for l in ouvertes}, kpi_id__in={l.kpi.code for l in ouvertes},
        organisation_id__in={l.org.id for l in ouvertes})}
    brouillons = [l for l in ouvertes if statuts.get((l.campagne.periode_id, l.kpi.code, l.org.id)) == Reponse.Statut.BROUILLON]
    validables, a_completer = [], []
    for l in brouillons:  # mêmes contrôles que « Valider » : ce qui ne passera pas est dit tout de suite
        r = S.reponse_de(l.campagne, l.kpi, l.org)
        motifs = S.controles_validation(r, l.campagne) if r is not None else [libelle("suivi.echanges.msg.saisir_ou_na")]
        if motifs:
            a_completer.append(point_a_completer(l.campagne, l.kpi, l.org, " ".join(motifs)))
        else:
            validables.append([l.campagne.pk, l.kpi.code, l.org.id])
    return {"nb_brouillon": len(brouillons), "nb_validables": len(validables), "validables": validables,
            "a_completer": a_completer, "nb_validees": len(ouvertes) - len(brouillons), "nb_historique": len(ecrites) - len(ouvertes),
            # KPI calculés : valeurs forcées (confirmées dans l'aperçu), et lignes ignorées faute de confirmation
            "nb_forcees": sum(1 for l in analyse.a_forcer if l.ecrite), "nb_non_forcees": analyse.non_forcees}


def _saisie(l):
    """Valeur au format de la saisie (pourcentage de 0 à 100) pour passer par les mêmes contrôles qu'à l'écran."""
    return l.valeur * 100 if l.kpi.est_pourcentage else l.valeur


def _forcer(utilisateur, l, nom_fichier):
    """Ligne confirmée d'un KPI calculé : valeur forcée par le mécanisme du panneau (``forcage.demander`` : droits
    revérifiés à l'écriture, demande acceptée aussitôt, journal, recalcul ciblé ; dans un paquet, en fin de paquet).
    Justification : le commentaire de la ligne, sinon le nom du fichier."""
    from . import forcage as FO

    if not FO.peut_trancher(utilisateur, l.campagne, l.kpi, l.org):  # droit perdu depuis l'aperçu : jamais une simple demande
        raise PermissionDenied(libelle("suivi.importer.motif.calcule_sans_droit"))
    saisie = "" if l.na or l.valeur is None else format(X.nombre(_saisie(l)), "f")
    justification = l.commentaire or libelle("suivi.importer.forcer.justification", fichier=nom_fichier or "—")
    FO.demander(utilisateur, l.campagne, l.kpi, l.org, saisie, l.na, justification)


def _commentaire_existant(l):
    r = S.reponse_de(l.campagne, l.kpi, l.org)
    return r.commentaire if r else ""


def _ecrire_historique(utilisateur, l):
    r = S.reponse_de(l.campagne, l.kpi, l.org) or Reponse(periode=l.campagne.periode, kpi=l.kpi, organisation=l.org)
    avant = "N/A" if r.non_applicable else r.texte or ("" if r.valeur is None else str(r.valeur))
    r.valeur, r.texte, r.non_applicable = (None if l.na or l.valeur is None else X.nombre(l.valeur)), ("" if l.na else l.texte), l.na
    if l.commentaire is not None:
        r.commentaire = l.commentaire
    r.statut, r.origine, r.saisi_par = Reponse.Statut.VALIDE, Reponse.Origine.IMPORT, utilisateur
    r.save()
    Journal.ecrire(utilisateur, "import", r, "valeur", avant, "N/A" if r.non_applicable else r.texte or r.valeur)
    signaler(r)


# ---------------------------------------------------------------- rapport des rejets
REJETS_GARDES = 500  # lignes rejetées gardées en session pour le rapport (l'aperçu en montre 200)


def lignes_rejetees(analyse, utilisateur):
    """Lignes rejetées à l'aperçu (ou refusées à l'enregistrement), telles qu'écrites dans le fichier (corrections de
    l'aperçu comprises), avec le motif et ce que l'outil sait de la case : [dict] simples, gardés en session le temps
    de télécharger le rapport (les REJETS_GARDES premières, sauf pour l'admin). La valeur N-1 et le statut ne sont
    donnés que pour une case que ``utilisateur`` peut voir."""
    from parametres import langues as L

    limite = None if utilisateur.est_admin else REJETS_GARDES
    sortie, plans, cases = [], {}, {}
    for l in analyse.lignes:
        if l.action != "rejet" and not l.echec:
            continue
        if limite is not None and len(sortie) >= limite:
            break
        b = l.brut or {}
        d = {"repere": l.repere, "cle": l.cle, "motif": l.echec or l.motif, "organisation": b.get("organisation", l.organisation),
             "kpi": b.get("kpi", l.kpi_id), "periode": b.get("periode", "") or l.periode, "exercice": b.get("exercice", ""),
             "valeur": b.get("valeur", ""), "na": b.get("na", ""), "commentaire": b.get("commentaire", ""),
             "referentiel": b.get("referentiel", ""), "indicateur": "", "unite": "", "n1": "", "theme": "", "statut": "",
             "langue_nombres": l.langue_nombres}
        k, c = l.kpi, l.campagne
        if k is not None:
            cle = (c.pk if c is not None else None, k.code, l.org.id if l.org is not None else None)
            if cle not in cases:  # une même case n'est décrite qu'une fois (lignes répétées)
                cases[cle] = _case_rejetee(utilisateur, k, c, l.org, plans, L.courante())
            sup = dict(cases[cle])
            sup["referentiel"] = d["referentiel"] or sup["referentiel"]
            d.update(sup)
        sortie.append(d)
    return sortie


def _case_rejetee(utilisateur, k, c, org, plans, langue):
    """Ce que l'outil sait de la case d'une ligne rejetée : nom, unité, thème ; valeur N-1 et statut seulement si
    ``utilisateur`` voit la case."""
    d = {"indicateur": nom_kpi(k, langue), "unite": k.symbole, "n1": "", "statut": ""}
    ref = c.referentiel_id if c is not None and c.pk else None
    if ref not in plans:  # un plan par référentiel, pas un par ligne
        plans[ref] = Plan(c.referentiel if ref is not None else None)
    place = plans[ref].decrire(k.code)
    d["theme"] = " › ".join(t for t in (place["theme"], place["sous_theme"]) if t)
    d["referentiel"] = place["referentiel"]
    if c is not None and c.pk and org is not None and (utilisateur.est_admin or S.droits(utilisateur, c, k, org).voir):
        r1 = S.valeurs_n1(c, {(k.code, org.id)}).get((k.code, org.id))
        v1 = "N/A" if r1 and r1.non_applicable else valeur_fichier(r1, k)
        d["n1"] = "" if v1 is None else str(v1)
        if r1 is not None and not r1.non_applicable and r1.valeur is not None and k.est_numerique:
            # à l'écran : au format de la langue (« 18,47 », « 4 631 »), comme le reste de la page
            from .templatetags.collecte import formater

            d["n1_affiche"] = formater(r1.valeur, k, avec_unite=False)
        r = Reponse.objects.filter(periode_id=c.periode_id, kpi=k, organisation=org).first()
        d["statut"] = Reponse.Statut(r.statut).label if r else Reponse.Statut.A_SAISIR.label
    return d


def fichier_rejets(utilisateur, rejets, nom_source="", format="xlsx", style="fr", langue=None):
    """Lignes rejetées, avec exactement les colonnes du fichier à remplir : « État » vaut « Rejetée » et « À vérifier »
    donne le motif. Organisation, ID KPI, Période et Exercice sont à remplir aussi (souvent la cause du rejet). Le fichier
    se corrige puis se réimporte tel quel."""
    langue = langue or langue_export("")  # comme le fichier à remplir
    tt = lambda cle, n=None, **kw: X.t(langue, cle, n, **kw)  # noqa: E731
    colonnes = colonnes_a_remplir()
    for c in colonnes:
        if c.cle in ("organisation", "kpi", "periode", "exercice", "code_org"):
            c.role = "remplir"
    nom = X.nom_fichier(tt("suivi.rejets.nom_fichier"), (nom_source or "").rsplit(".", 1)[0])
    rejetee = tt("suivi.rejets.etat")

    def donnees(r):
        d = dict(r)
        d["etat"] = rejetee
        repere = str(r["repere"])
        repere = tt("suivi.rejets.ligne", repere=repere) if repere[:1].isdecimal() else repere  # reprise : « ligne 5 · 2022 »
        d["verifier"] = f"{repere} : {r['motif']}"
        d["statut"] = traduire(r["statut"], langue) if r.get("statut") else ""
        for cle in ("valeur", "n1", "exercice"):  # nombres lisibles comme nombres dans Excel
            if cle == "valeur" and "%" in str(d.get(cle) or ""):
                continue  # « 12 % » refusé (KPI qui n'est pas un pourcentage) : gardé tel qu'écrit, à corriger par la personne
            try:
                if d.get(cle) in (None, "", "N/A"):
                    continue
                # la valeur : relue comme à l'import (langue de son onglet), jamais autrement
                d[cle] = X.lire_nombre_importe(d[cle], r.get("langue_nombres") or None) if cle == "valeur" else X.lire_decimal(d[cle])
            except ValueError:
                pass
        if d.get("exercice") not in (None, ""):
            try:
                d["exercice"] = int(d["exercice"])
            except (TypeError, ValueError):
                pass
        return [d.get(c.cle, "") for c in colonnes]

    lignes = [donnees(r) for r in rejets]
    if format == "csv":
        return X.reponse_csv([[c.titre(langue) for c in colonnes]] + lignes, nom, style)
    wb = X.classeur()
    ws = wb.create_sheet(tt("suivi.rejets.onglet"))
    # légende sans « Clé : ne pas modifier » : ici l'organisation, l'ID KPI et la période se corrigent aussi (en jaune)
    cle_grise = X.t(langue, "suivi.fichier.legende.cle")
    roles_rejets = [e for e in X.exemples_roles(langue) if e[0] != cle_grise]
    ws.sheet_view.showGridLines = False
    ws.sheet_view.zoomScale = 90
    entete = X.bandeau(ws, tt("suivi.rejets.onglet") + (f" – {nom_source}" if nom_source else ""), [
        tt("suivi.rejets.bandeau1"),
        tt("suivi.rejets.bandeau2", len(rejets)),
    ], langue, exemples=[e[:6] for e in roles_rejets])  # bandeau : cases d'exemple sans leur aide
    fin = X.ecrire_tableau(ws, colonnes, lignes, langue, debut=entete, figer="indicateur")
    rang = {c.cle: i + 1 for i, c in enumerate(colonnes)}
    for n in range(entete + 1, fin + 1):
        ws.cell(n, rang["verifier"]).font = Font(bold=True, color=X.ORANGE_TEXTE)
        ws.cell(n, rang["etat"]).font = Font(bold=True, color=X.MAGENTA)
    X.feuille_a_lire(wb, tt("suivi.rejets.onglet"), [
        (tt("suivi.rejets.fichier_origine"), nom_source or "—"),
        (tt("suivi.remplir.lire.genere_le"), DC.date_heure_courte(timezone.localtime()) + f" · {utilisateur}"),
    ] + a_lire(langue, 4), langue, exemples=roles_rejets)
    wb.active = 1
    return X.reponse_excel(wb, nom)
