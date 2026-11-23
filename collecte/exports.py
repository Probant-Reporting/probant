"""Export des valeurs (cahier des charges, section 6) : base de données pour Power BI, tableau lisible, rapport de revue.

Les réglages d'un export tiennent dans ``Parametres`` : ils s'enregistrent tels quels comme préréglage (``ReglageExport``).
Chacun n'exporte que son périmètre : l'admin tout, le validateur ses organisations, le contributeur ses cases.
"""
from dataclasses import asdict, dataclass, field
from decimal import Decimal

from django.db.models import Count
from django.utils import timezone
from openpyxl.formatting.rule import DataBarRule

from parametres import langues as L
from parametres import niveaux as N
from parametres.libelles import libelle
from referentiel.models import KPI, Attribution
from referentiel.plans import Plan

from . import dates_courtes as DC
from . import fichiers as X
from . import saisie as S
from .calcul import figes_partiels, ouverte
from .models import Campagne, Reponse
from .styles_excel import Alignment, Font, PatternFill
from .templatetags.collecte import arrondi

# Codes seulement : les textes sont dans libelles/suivi.*.json (suivi.export.presentation.*, .contenu.*, .comportement.*,
# .periode.*) et se lisent par les fonctions ci-dessous, dans la langue de l'interface (``langue`` absente) ou celle d'un fichier.
CODES_PRESENTATIONS = ("base", "tableau", "revue", "audit")
CODES_CONTENUS = ("valide", "brouillon", "a_saisir", "calcule")
# Filtre par comportement du type de saisie (les types eux-mêmes sont réglables : Référentiels › Unités et formats)
CODES_COMPORTEMENTS = ("saisie", "herite", "calcul")
CODES_PERIODES = ("annee", "semestre", "trimestre", "mois")
CODES_VALEURS = ("chiffres", "formules")  # valeurs calculées en chiffres, ou en formules Excel (tableau lisible)
SEUIL_GROS_EXPORT = 50_000  # au-delà, le constructeur conseille le CSV (plus rapide et plus léger qu'Excel)


def _t(langue, cle, n=None, **valeurs):
    """Texte dans la langue d'un fichier ; ``langue`` absente : langue de l'interface (pages de l'outil)."""
    return libelle(cle, n=n, **valeurs) if langue is None else X.t(langue, cle, n, **valeurs)


def presentations(langue=None, utilisateur=None):
    """[(code, nom, description)] des présentations ; ``utilisateur`` : sans lui toutes, avec lui celles qu'il peut demander
    (le dossier d'audit est pour l'administrateur et l'auditeur : ``export_audit.permis``)."""
    from . import export_audit as EA

    return [(c, _t(langue, f"suivi.export.presentation.{c}"), _t(langue, f"suivi.export.presentation.{c}_aide"))
            for c in CODES_PRESENTATIONS if c != EA.PRESENTATION or utilisateur is None or EA.permis(utilisateur)]


def contenus(langue=None):
    return [(c, _t(langue, f"suivi.export.contenu.{c}")) for c in CODES_CONTENUS]


def types_periodes(langue=None):
    return [(c, _t(langue, f"suivi.export.periode.{c}")) for c in CODES_PERIODES]


def types_periodes_phrase(langue=None):
    """Types de période au milieu d'une phrase : la casse vient du libellé de chaque langue (``suivi.export.periode_phrase.*``)."""
    return [(c, _t(langue, f"suivi.export.periode_phrase.{c}")) for c in CODES_PERIODES]


def types_export(langue=None):
    """[(comportement, libellé)] : le libellé reprend le nom des types concernés (ex. « Facteur d'émission »)."""
    from parametres.models import TypeSaisie

    noms = {}
    for ts in TypeSaisie.objects.all():
        noms.setdefault(ts.comportement, []).append(ts.tr("libelle", langue) if langue else ts.libelle)
    return [(c, ", ".join(noms[c]) if c == "herite" and noms.get(c) else _t(langue, f"suivi.export.comportement.{c}"))
            for c in CODES_COMPORTEMENTS]


def liste_et(elements, langue=None):
    """« A », « A et B », « A, B et C »."""
    elements = [str(e) for e in elements]
    if len(elements) < 2:
        return "".join(elements)
    return _t(langue, "suivi.export.liste.et", debut=", ".join(elements[:-1]), fin=elements[-1])

# Préréglages fournis avec l'outil (les exercices « courant » et « tous » suivent les campagnes)
PRESETS = {
    "powerbi": ("Power BI – toutes les années", "Base de données Excel, tous les exercices, valeurs saisies, calculées et agrégées.",
                dict(presentation="base", format="xlsx", exercices=["tous"], contenus=["valide", "brouillon", "calcule"])),
    "tableau": ("Tableau de l'exercice avec N-1", "Une ligne par KPI, une colonne par organisation, valeur N-1 à côté.",
                dict(presentation="tableau", format="xlsx", exercices=["courant"], contenus=["valide", "brouillon", "calcule"], n1=True)),
    "manquantes": ("Cases restant à saisir", "Ce qui manque encore pour l'exercice en cours : cases vides et brouillons.",
                   dict(presentation="base", format="xlsx", exercices=["courant"], contenus=["a_saisir", "brouillon"],
                        types=["saisie", "herite"])),
    "revue": ("Rapport de revue de l'exercice", "Par organisation : valeur, N-1, écart, statut, commentaire, avec la synthèse.",
              dict(presentation="revue", format="xlsx", exercices=["courant"], contenus=["valide", "brouillon", "a_saisir"],
                   types=["saisie", "herite"])),
    "csv": ("CSV pour Power BI", "Base de données en CSV standard (séparateur virgule, point décimal), tous les exercices.",
            dict(presentation="base", format="csv", csv="intl", exercices=["tous"], contenus=["valide", "brouillon", "calcule"])),
}


def texte_fourni(reglage, champ):
    """Nom (« nom ») ou description (« description ») d'un export enregistré, dans la langue de la personne qui lit quand
    c'est un modèle fourni resté tel quel (même nom et même texte qu'à sa création) ; sinon le texte enregistré, celui
    qu'a écrit l'administrateur ou la personne (jamais traduit)."""
    from parametres.libelles import libelle

    for code, (nom, description, _) in PRESETS.items():
        if reglage.nom == nom:
            if getattr(reglage, champ) == (nom if champ == "nom" else description):
                return libelle(f"suivi.echanges.fourni.{code}.{champ}")
            break
    return getattr(reglage, champ)


def code_fourni(reglage):
    """Code du modèle fourni dont l'export enregistré porte le nom (« powerbi », « revue »…), sinon vide : son nom se lit
    alors dans la langue de qui regarde (``texte_fourni``)."""
    return next((code for code, (nom, _, _) in PRESETS.items() if reglage.nom == nom), "")


def creer_modeles_fournis():
    """Crée les modèles fournis absents (partagés avec tous). Renvoie le nombre créé."""
    from .models import ReglageExport

    existants = set(ReglageExport.objects.values_list("nom", flat=True))
    n = 0
    for nom, description, parametres in PRESETS.values():
        if nom not in existants:
            ReglageExport.objects.create(nom=nom, description=description, parametres=parametres, partage=True)
            n += 1
    return n


@dataclass
class Parametres:
    presentation: str = "base"
    format: str = "xlsx"
    csv: str = "fr"  # fr : « ; » et virgule décimale (Excel français) ; intl : « , » et point (Power BI, outils anglais)
    exercices: list = field(default_factory=lambda: ["courant"])  # années, « courant » ou « tous »
    periodes: list = field(default_factory=list)  # types de période (année, mois…) ; vide : tous
    contenus: list = field(default_factory=lambda: ["valide", "brouillon", "calcule"])
    types: list = field(default_factory=lambda: list(CODES_COMPORTEMENTS))
    niveaux: list = field(default_factory=lambda: N.codes())  # codes des niveaux (Paramètres › Niveaux)
    organisations: list = field(default_factory=list)  # vide : toutes celles des niveaux choisis (suit l'arbre)
    referentiel: str = ""  # code du référentiel ; vide : tous (chaque KPI une fois)
    themes: list = field(default_factory=list)  # identifiants des thèmes du sommet ; vide : tous
    selection: str = ""  # identifiant d'une liste de KPI sauvegardée (SelectionKPI) ; vide : pas de liste
    kpis: list = field(default_factory=list)  # codes des KPI cochés un à un (« Choisir les KPI ») ; vide : pas de choix
    n1: bool = False
    langue: str = ""  # langue des contenus (parmi les langues actives) ; vide : celle de la personne qui exporte
    # Valeurs calculées : « chiffres » (par défaut) ou « formules » Excel qui citent les cases de leurs sources (tableau
    # lisible en Excel seulement : ``formules_excel``) ; ``sources`` : ajouter les KPI cités par les formules
    valeurs: str = "chiffres"
    sources: bool = False

    @classmethod
    def depuis(cls, donnees):
        """Depuis un formulaire (QueryDict) ou un préréglage (dict). Les valeurs inconnues sont écartées."""
        p = cls()

        def liste(cle):
            v = donnees.getlist(cle) if hasattr(donnees, "getlist") else donnees.get(cle)
            return [str(x) for x in v] if isinstance(v, (list, tuple)) else None

        def un(cle, choix):
            v = donnees.get(cle)
            return v if v in choix else getattr(p, cle)

        p.presentation = un("presentation", CODES_PRESENTATIONS)
        p.format = un("format", ["xlsx", "csv"])
        p.csv = un("csv", ["fr", "intl"])
        from referentiel.models import Referentiel

        p.referentiel = un("referentiel", [""] + list(Referentiel.objects.filter(actif=True).values_list("code", flat=True)))
        # « » : la langue de l'interface de la personne qui télécharge (proposée quand ce n'est pas une langue des contenus)
        p.langue = un("langue", [""] + L.codes_actifs())
        p.valeurs = un("valeurs", CODES_VALEURS)
        for cle in ("n1", "sources"):
            v = donnees.get(cle)
            setattr(p, cle, v in (True, "on", "1", "true") if v is not None else getattr(p, cle))
        for cle, permis in (("contenus", CODES_CONTENUS), ("types", CODES_COMPORTEMENTS), ("niveaux", N.codes()),
                            ("periodes", CODES_PERIODES)):
            v = liste(cle)
            if v is not None:
                setattr(p, cle, [x for x in v if x in permis])
        v = liste("exercices")
        if v is not None:
            p.exercices = [x for x in v if x in ("courant", "tous") or x.isdecimal()] or ["courant"]
        v = liste("organisations")
        if v is not None:
            p.organisations = [int(x) for x in v if x.isdecimal()]
        v = liste("themes")
        if v is not None:
            p.themes = [x for x in v if x.isdecimal()]
        v = str(donnees.get("selection") or "")
        if "selection" in donnees:
            from .models import SelectionKPI

            p.selection = v if v.isdecimal() and SelectionKPI.objects.filter(pk=v).exists() else ""
        v = liste("kpis")
        if v is not None:
            from referentiel.models import KPI

            p.kpis = sorted(set(KPI.objects.filter(code__in=v).values_list("code", flat=True)))
        choix = donnees.get("choix_kpi")  # formulaire : « Tous les KPI », « Une liste sauvegardée » ou « Choisir les KPI »
        if choix in ("tous", "liste", "choix"):
            if choix != "liste":
                p.selection = ""
            if choix != "choix":
                p.kpis = []
            if choix != "tous":
                p.themes = []
        return p

    def en_dict(self):
        return {k: v for k, v in asdict(self).items() if not k.startswith("_")}

    def formules(self):
        """Vrai si les valeurs calculées s'écrivent en formules Excel : option choisie, tableau lisible en Excel."""
        return self.valeurs == "formules" and self.format == "xlsx" and self.presentation == "tableau"

    def selection_kpi(self):
        """Sélection de KPI choisie (ou None si aucune, ou supprimée depuis)."""
        if not hasattr(self, "_selection"):
            from .models import SelectionKPI

            self._selection = SelectionKPI.objects.filter(pk=self.selection).first() if self.selection else None
        return self._selection

    def codes_kpi(self):
        """Codes des KPI retenus : ceux cochés un à un, sinon ceux de la liste sauvegardée ; None : pas de restriction."""
        return set(self.kpis) if self.kpis else self.codes_selection()

    def codes_selection(self):
        """Codes des KPI de la sélection choisie ; None sans sélection."""
        s = self.selection_kpi()
        if s is None:
            return None
        if not hasattr(self, "_codes_selection"):
            self._codes_selection = set(s.kpis.values_list("code", flat=True))
        return self._codes_selection

    def plan(self):
        """Plan du référentiel choisi (ou de tous), lu une fois par export."""
        if not hasattr(self, "_plan"):
            self._plan = Plan(self.referentiel or None)
        return self._plan

    def annees(self):
        if "tous" in self.exercices:
            return sorted(set(Campagne.objects.values_list("exercice", flat=True)))
        annees = {int(x) for x in self.exercices if x.isdecimal()}
        if "courant" in self.exercices:
            annees |= {c.exercice for c in S.campagnes_en_cours()} or ({S.campagne_courante().exercice} if S.campagne_courante() else set())
        return sorted(annees)

    def campagnes(self):
        """Campagnes exportées : exercices, référentiel et types de période choisis."""
        qs = Campagne.objects.filter(exercice__in=self.annees()).select_related("referentiel", "periode")
        if self.referentiel:
            qs = qs.filter(referentiel_id=self.referentiel)
        if self.periodes:
            qs = qs.filter(periode__type__in=self.periodes)
        return list(qs.order_by("periode__debut", "-periode__fin", "referentiel__ordre", "referentiel_id"))

    def resume(self):
        """Réglages en une ligne (liste « Mes exports »), dans la langue de l'interface."""
        pres = _t(None, f"suivi.export.presentation.{self.presentation}")
        en_cours = sorted({c.exercice for c in S.campagnes_en_cours()} or (
            {S.campagne_courante().exercice} if S.campagne_courante() else set())) if "courant" in self.exercices else []
        courant = (libelle("suivi.export.periode.en_cours_annees", annees=", ".join(str(a) for a in en_cours)) if en_cours
                   else libelle("suivi.export.periode.en_cours"))
        ex = libelle("suivi.export.periode.tous") if "tous" in self.exercices else ", ".join(
            courant if x == "courant" else x for x in self.exercices)
        fmt = "Excel" if self.format == "xlsx" else "CSV"
        ref = self.plan().referentiel
        types = ", ".join(l for c, l in types_periodes_phrase() if c in self.periodes)
        sel = self.selection_kpi()
        morceaux = [pres, fmt, ex] + ([types] if types else []) + ([str(ref)] if ref else [])
        if self.kpis:
            morceaux.append(libelle("suivi.export.resume.kpis_choisis", n=len(self.kpis)))
        elif sel:
            morceaux.append(libelle("suivi.export.resume.liste", liste=sel))
        return " · ".join(morceaux)

    def phrase(self):
        """Ce que l'export contiendra, en une phrase (constructeur d'export), dans la langue de l'interface."""
        pres = _t(None, f"suivi.export.presentation.{self.presentation}")
        fmt = "Excel" if self.format == "xlsx" else "CSV"
        contenus_ = [libelle(f"suivi.export.phrase.{c}") for c in CODES_CONTENUS if c in self.contenus]
        valeurs = liste_et(contenus_) if contenus_ else libelle("suivi.export.phrase.aucune_valeur")
        if "tous" in self.exercices:
            periode = libelle("suivi.export.periode.tous")
        else:
            annees = self.annees()
            liste_annees = ", ".join(str(a) for a in annees)
            if not annees:
                periode = libelle("suivi.export.periode.aucun")
            elif self.exercices == ["courant"]:
                periode = (libelle("suivi.export.periode.en_cours_annees", annees=liste_annees) if len(annees) == 1
                           else libelle("suivi.export.periode.en_cours"))
            else:
                periode = libelle("suivi.export.periode.exercices", n=len(annees), annees=liste_annees)
        types = [l for c, l in types_periodes_phrase() if c in self.periodes]
        if types:
            periode = libelle("suivi.export.periode.avec_types", periode=periode, types=", ".join(types))
        noms_niveaux = [n.tr("nom") for n in N.tous() if n.code in self.niveaux]
        if self.organisations:
            orgs = libelle("suivi.export.phrase.orgs_choisies", n=len(self.organisations))
        elif not noms_niveaux:
            orgs = libelle("suivi.export.phrase.aucune_org")
        elif len(noms_niveaux) < len(N.codes()):
            orgs = libelle("suivi.export.phrase.orgs_niveaux", niveaux=", ".join(noms_niveaux))
        else:
            orgs = libelle("suivi.export.phrase.toutes_orgs")
        sel, ref = self.selection_kpi(), self.plan().referentiel
        if self.kpis:
            kpis = libelle("suivi.export.phrase.kpis_choisis_ref" if ref else "suivi.export.phrase.kpis_choisis",
                           n=len(self.kpis), referentiel=ref)
        elif sel:
            kpis = libelle("suivi.export.phrase.kpis_liste", n=len(self.codes_selection()), liste=sel)
        elif self.themes:
            kpis = libelle("suivi.export.phrase.kpis_themes_ref" if ref else "suivi.export.phrase.kpis_themes",
                           n=len(self.themes), referentiel=ref)
        elif ref:
            kpis = libelle("suivi.export.phrase.kpis_referentiel", referentiel=ref)
        else:
            kpis = libelle("suivi.export.phrase.tous_kpis")
        options = []
        if self.n1:
            options.append(libelle("suivi.export.phrase.avec_n1"))
        if self.formules():
            options.append(libelle("suivi.export.phrase.formules_sources" if self.sources else "suivi.export.phrase.formules"))
        if self.langue and self.langue != L.defaut():
            options.append(libelle("suivi.export.phrase.contenus_en", nom_langue=L.libelle(self.langue)))
        return libelle("suivi.export.phrase.gabarit", presentation=pres, format=fmt, valeurs=valeurs, periode=periode,
                       organisations=orgs, kpis=kpis, options="".join(", " + o for o in options))


@dataclass
class LigneExport:
    exercice: int
    kpi: KPI
    org: object
    reponse: Reponse | None
    n1: Reponse | None = None
    calculee: bool = False
    periode: object = None
    campagne: Campagne | None = None
    attendue: bool = True  # compte dans l'avancement (comme au tableau de bord : ni total, ni case couverte par le dessus)


# ---------------------------------------------------------------- collecte des lignes
def perimetre(utilisateur, arbre):
    """(cases saisissables visibles, organisations dont on voit les résultats) ; None = sans restriction (admin)."""
    if utilisateur.voit_tout and utilisateur.orgs_permises() is None:
        return None, None
    paires = {(k.code, o.id) for k, o in S.cellules(utilisateur)}
    if utilisateur.lecture_seule:  # lecteur, auditeur limités à des organisations : leurs résultats aussi
        return paires, set(utilisateur.orgs_permises())
    attribuees = set(Attribution.objects.filter(utilisateur=utilisateur, role=Attribution.Role.VALIDATEUR)
                     .values_list("organisation_id", flat=True))
    resultats = {o.id for o in arbre.values() if attribuees & ({o.id} | {a.id for a in o.ancetres()})}
    return paires, resultats


def organisations_retenues(p, arbre):
    """Identifiants des organisations exportées : celles cochées (toutes si aucune liste), dans les niveaux choisis."""
    choisies = set(p.organisations)
    return {o.id for o in arbre.values() if o.niveau_id in p.niveaux and (not choisies or o.id in choisies)}


def collecter(utilisateur, p):
    if p.presentation == "audit":
        from . import export_audit as EA

        EA.exiger(utilisateur)  # dossier d'audit : administrateur et auditeur
    arbre = S.arbre_organisations()
    kpis = {k.code: k for k in KPI.objects.select_related("granularite")}
    paires, resultats = perimetre(utilisateur, arbre)
    themes, plan = set(p.themes), p.plan()
    selection = p.codes_kpi()

    def kpi_retenu(k):
        if p.referentiel and not plan.contient(k.code):
            return False
        if selection is not None and k.code not in selection:
            return False
        racine = plan.theme_racine(k.code) if themes else None
        return k.comportement in p.types and (not themes or (racine is not None and str(racine.pk) in themes))

    retenus = {c for c, k in kpis.items() if kpi_retenu(k)}
    if p.formules() and p.sources:  # formules Excel : les KPI cités par les formules, pour que les formules s'écrivent
        from .formules_excel import sources_transitives

        retenus |= sources_transitives(retenus)
    lignes = []
    par_periode = {}
    from parametres import niveaux as N

    rangs = N.rangs()
    for c in p.campagnes():  # chaque période une fois, même si plusieurs référentiels la collectent
        par_periode.setdefault(c.periode_id, []).append(c)
    for campagnes in par_periode.values():
        c, periode = campagnes[0], campagnes[0].periode
        dans = set()  # KPI des référentiels collectés sur cette période (et sources de leurs formules) ; None : tous
        for x in campagnes:
            codes = S.codes_campagne(x)
            dans = None if codes is None or dans is None else dans | codes[1]
        n1 = {}
        if p.n1 or p.presentation in ("revue", "audit"):  # le dossier d'audit donne toujours N-1 et l'écart
            prec = S.periode_comparaison(c)
            n1 = {(r.kpi_id, r.organisation_id): r for r in Reponse.objects.filter(periode=prec)} if prec else {}
            comparables = S.cases_comparables(prec, set(n1))  # organisation ouverte, KPI demandé (la règle de la saisie)
            n1 = {cle: r for cle, r in n1.items() if cle in comparables}
        existantes, debut = set(), len(lignes)
        # arbre de la période : celui de sa clôture pour un exercice clos ou rouvert en gardant
        # les chiffres de l'époque (rattachements et colonnes de la hiérarchie de l'époque ; une organisation créée depuis
        # n'y a pas de ligne) ; les droits (``perimetre``) restent ceux d'aujourd'hui
        # un KPI figé par une campagne clôturée de la période suit l'arbre du jour où il l'a été 
        partiels = figes_partiels(periode) or {"kpis": {}}
        arbres_p = {}

        def arbre_de(code):
            """(arbre, organisations retenues) que suit le KPI sur la période ; lus une fois par arbre."""
            cle = partiels["kpis"].get(code)
            if cle not in arbres_p:
                a = S.arbre_organisations(periode, None if cle is None else code)
                # niveaux choisis lus dans le même arbre que les lignes (une organisation qui a
                # changé de niveau depuis la clôture disparaissait de l'export de l'exercice clos filtré sur son niveau)
                arbres_p[cle] = (a, organisations_retenues(p, a))
            return arbres_p[cle]

        reponses = Reponse.objects.filter(periode=periode).select_related("saisi_par", "valide_par").annotate(nb_preuves=Count("preuves"))
        for r in reponses:
            cle = (r.kpi_id, r.organisation_id)
            existantes.add(cle)
            arbre_p, orgs = arbre_de(r.kpi_id)
            k, o = kpis.get(r.kpi_id), arbre_p.get(r.organisation_id)
            if k is None or o is None or o.id not in orgs or k.code not in retenus or (dans is not None and k.code not in dans):
                continue
            if not ouverte(o, periode, arbre_p):
                # pas encore ouverte pendant la période (date d'ouverture, la sienne ou celle d'un ancêtre) : comme les
                # écrans et les totaux, pas dans l'export de cette période ; les valeurs gardées après « Je confirme »
                # restent en base et dans l'historique de la case 
                continue
            calculee = S.est_calculee(k, o, r)
            if calculee:
                if "calcule" not in p.contenus or (resultats is not None and o.id not in resultats):
                    continue
            elif (paires is not None and cle not in paires) or r.statut not in p.contenus:
                continue
            lignes.append(LigneExport(c.exercice, k, o, r, n1.get(cle), calculee, periode, c))
        if "a_saisir" in p.contenus:
            vues = set()
            for x in campagnes:
                for k, o in S.cellules(utilisateur, campagne=x):
                    cle = (k.code, o.id)
                    if cle not in existantes and cle not in vues and o.id in arbre_de(k.code)[1] and k.code in retenus:
                        vues.add(cle)
                        lignes.append(LigneExport(c.exercice, k, o, None, n1.get(cle), periode=periode, campagne=c))
        # comme au tableau de bord : une valeur saisie au-dessus de la granularité (le détail manque) n'est pas une case
        # attendue, et les cases qu'elle couvre en dessous non plus, ni celles d'un KPI facultatif dans les référentiels de
        # la période (elles restent exportées si elles ont une valeur)
        de_la_periode = lignes[debut:]
        couv = S.couvertes(periode, [(l.kpi, l.org) for l in de_la_periode if not l.calculee])
        facultatifs = {}
        gardees = []
        for l in de_la_periode:
            if l.kpi.code not in facultatifs:
                facultatifs[l.kpi.code] = S.facultatif_partout(campagnes, l.kpi)
            if not l.calculee and (S.au_dessus(l.kpi, l.org, rangs) or (l.kpi.code, l.org.id) in couv or facultatifs[l.kpi.code]):
                l.attendue = False
                if l.reponse is None or l.reponse.statut == Reponse.Statut.A_SAISIR:
                    continue  # rien à saisir ici
            gardees.append(l)
        lignes[debut:] = gardees
    cles = {}

    def tri(l):
        cle = (l.org.id, l.periode.pk)  # l'arbre peut différer d'une période à l'autre
        if cle not in cles:
            cles[cle] = S.cle_arbre(l.org)
        return (l.periode.debut, -l.periode.fin.toordinal(), plan.position(l.kpi.code, l.kpi.ordre), cles[cle])

    lignes.sort(key=tri)
    return lignes


# ---------------------------------------------------------------- valeurs et libellés
# Termes de l'interface qui sortent dans les fichiers (statuts, origines, oui / non…) : le texte français d'origine → la clé de
# son libellé (suivi.export.terme.*), traduit dans la langue du fichier par ``traduire``.
TERMES = {
    "Saisi": "saisi", "Calculé": "calcule", "Facteur d'émission": "facteur_emission", "Groupe": "groupe", "Pays": "pays",
    "Entité": "entite", "Site": "site", "À saisir": "a_saisir", "Brouillon": "brouillon", "Validé": "valide",
    "Incomplet": "incomplet", "Erreur de calcul": "erreur_calcul", "Saisie": "saisie", "Import": "import",
    "Calcul": "calcul", "Agrégation": "agregation", "Cumul des périodes": "cumul", "Oui": "oui", "Non": "non",
    "Décompte": "decompte", "Somme": "somme", "Formule": "formule", "Aucune": "aucune",
}


def traduire(texte, langue):
    """Termes de l'interface (statuts, origines, oui / non) dans la langue du fichier (libelles/suivi.*.json). Les contenus
    (noms, unités, niveaux…) suivent la langue de l'export par leurs traductions."""
    cle = TERMES.get(texte)
    return X.t(langue, f"suivi.export.terme.{cle}") if cle else texte


def valeur_fichier(r, kpi):
    """Valeur exportée : pourcentage de 0 à 100 (comme à l'écran), sans arrondi ; None si vide ou N/A.
    Oui / non et liste : la réponse en texte (sur un agrégat, le décompte « Oui : 3 · Non : 1 »)."""
    if r is None or r.non_applicable:
        return None
    if not kpi.est_numerique:
        return kpi.reponse_affichee(r.texte) or None
    if r.valeur is None:
        return None
    v = r.valeur * 100 if kpi.est_pourcentage else r.valeur
    return X.nombre(v)


def champs_export(p):
    """Champs personnalisés des KPI (lus une fois par export) : une colonne chacun."""
    if not hasattr(p, "_champs"):
        from parametres.models import ChampPersonnalise

        p._champs = list(ChampPersonnalise.objects.all())
    return p._champs


def valeur_champ(k, c, langue):
    v = k.champs.get(c.code)
    if c.type == "case":
        return traduire("Oui" if v else "Non", langue)
    if c.type == "date" and v:
        import datetime

        return datetime.date.fromisoformat(v)
    if c.type == "liste" and v:
        return dict(c.valeurs_traduites(langue)).get(v, v)
    return v or ""


def nom_kpi(k, langue):
    return k.tr("libelle", langue)


def hierarchie(o):
    """{code du niveau: nom} de l'organisation et de ses ancêtres."""
    d = {}
    while o:
        d[o.niveau_id] = o.nom
        o = o.parent
    return d


def statut_libelle(l):
    if l.reponse is None:
        return "À saisir"
    return l.reponse.get_statut_display()


def personne(u):
    return u.email if u else ""


# ---------------------------------------------------------------- textes communs des fichiers
def _nombre_texte(v, decimales, langue):
    """Nombre écrit dans la langue du fichier (1 234 · 1,234 · 1.234)."""
    from .templatetags.collecte import nombre

    return nombre(v, decimales, langue)


def _t_fichier(p, cle, n=None, **valeurs):
    """Texte d'un fichier dans la langue de l'export (libelles/suivi.*.json)."""
    return X.t(p.langue, cle, n, **valeurs)


def outil():
    """Nom de l'outil (Paramètres › Identité), en tête des fichiers."""
    from parametres.models import Instance

    return Instance.courante().titre


def _format_lisible(k, fraction=False):
    """Format d'une valeur à lire (tableau, revue) : décimales de l'unité ; pourcentage de 0 à 100 suivi de « % ».
    ``fraction`` (tableau en formules Excel) : pourcentage en fraction, au format % d'Excel (0,25 affiché 25 %), pour que
    les formules qui le citent calculent comme l'outil."""
    fmt = X.format_nombre_du_kpi(k)
    if k.est_pourcentage:
        return fmt + "%" if fraction else fmt + '" %"'
    return fmt


def _valeur_lisible(r, k, fraction=False):
    """Valeur d'une case à lire : nombre (pourcentage de 0 à 100, ou en fraction avec ``fraction``), réponse en texte,
    « N/A », ou None si vide."""
    if r is None:
        return None
    if r.non_applicable:
        return "N/A"
    if fraction and k.est_pourcentage and r.valeur is not None and not r.texte:
        return X.nombre(r.valeur)
    return valeur_fichier(r, k)


def titre_periode(periode, langue="fr"):
    return X.t(langue, "suivi.export.periode.titre_exercice", periode=periode) if periode.annuelle else str(periode)


# ---------------------------------------------------------------- présentation « base de données »
# (code de la colonne, clé du libellé) ; les colonnes « hierarchie » et « champs » sont remplacées par une colonne par niveau
# et par champ personnalisé (leurs noms sont des contenus)
COLONNES_BASE = [
    "exercice", "periode", "debut", "id", "indicateur", "referentiel", "theme", "sous_theme", "type", "unite", "code_org",
    "organisation", "niveau",
    "hierarchie",  # une colonne par niveau de l'arbre (Paramètres › Niveaux), nommée comme le niveau
    "valeur", "na", "n1",
    "comparaison",  # celle de « Valeur N-1 » (le mois précédent, selon le référentiel)
    "statut", "origine", "commentaire", "saisi_par", "date_maj", "valide_par", "date_validation", "preuves",
    "champs",  # une colonne par champ personnalisé des KPI (Référentiels › Unités et formats)
]
# Rôle des colonnes (légende commune) : clés grises pour relire le fichier, valeur, N/A et commentaire modifiables avant
# un réimport, le reste pour information
ROLES_BASE = {"exercice": "cle", "periode": "cle", "id": "cle", "code_org": "cle", "organisation": "cle",
              "valeur": "remplir", "na": "remplir", "commentaire": "remplir"}
LARGEURS_BASE = {"exercice": 9, "periode": 13, "debut": 12, "id": 11, "indicateur": 55, "referentiel": 22, "theme": 28, "sous_theme": 30, "type": 13, "unite": 12,
                 "code_org": 14, "organisation": 24, "niveau": 10, "valeur": 14, "na": 6, "n1": 14, "comparaison": 16, "statut": 11, "origine": 10,
                 "commentaire": 40, "saisi_par": 26, "date_maj": 16, "valide_par": 26, "date_validation": 16, "preuves": 8}
FORMAT_DATE_HEURE = "DD/MM/YYYY HH:MM"


def niveaux_export(p):
    """Niveaux de l'arbre (lus une fois par export)."""
    if not hasattr(p, "_niveaux"):
        p._niveaux = N.tous()
    return p._niveaux


def niveaux_nom(p, code):
    return next((n.tr("nom", p.langue) for n in niveaux_export(p) if n.code == code), code)


def colonnes_base(p):
    """[(code, titre dans la langue de l'export, clé du libellé ou « »)] des colonnes de l'onglet de valeurs."""
    cols = []
    for c in COLONNES_BASE:
        if c == "hierarchie":
            cols += [(f"niv:{n.code}", n.tr("nom", p.langue), "") for n in niveaux_export(p)]
        elif c == "champs":
            cols += [(f"champ:{ch.code}", ch.tr("libelle", p.langue), "") for ch in champs_export(p)]
        elif p.n1 or c not in ("n1", "comparaison"):
            cle = f"suivi.export.colonne.{c}"
            cols.append((c, _t_fichier(p, cle), cle))
    # un niveau ou un champ personnalisé qui porte le nom d'une colonne (ex. champ « Origine ») : en-têtes uniques pour
    # Power BI et les tableaux croisés
    vus, uniques = set(), []
    for code, titre, cle in cols:
        if code.startswith(("niv:", "champ:")) and titre in vus:
            titre = _t_fichier(p, "suivi.export.colonne.niveau_homonyme" if code.startswith("niv:")
                               else "suivi.export.colonne.champ_homonyme", nom=titre)
        vus.add(titre)
        uniques.append((code, titre, cle))
    return uniques


def _memo(p, nom, cle, calcul):
    """Mémoire d'un export (``p``) : ce qui ne dépend que du KPI, de l'organisation ou de la période n'est calculé qu'une
    fois, et non pour chacune des dizaines de milliers de lignes."""
    cache = p.__dict__.setdefault("_memo", {}).setdefault(nom, {})
    if cle not in cache:
        cache[cle] = calcul()
    return cache[cle]


def _colonnes(p):
    return _memo(p, "colonnes", None, lambda: [c for c, _, _ in colonnes_base(p)])


def ligne_base(l, p):
    k, o, r, lg = l.kpi, l.org, l.reponse, p.langue
    v = dict(_memo(p, "kpi", k.code, lambda: {
        **{f"champ:{c.code}": valeur_champ(k, c, lg) for c in champs_export(p)}, **p.plan().decrire(k.code),
        "id": k.code, "indicateur": nom_kpi(k, lg), "type": k.type_saisie.tr("libelle", lg), "unite": k.symbole}))
    v.update(_memo(p, "org", o.id, lambda: {**{f"niv:{c}": nom for c, nom in hierarchie(o).items()},
                                           "code_org": o.code, "organisation": o.nom, "niveau": o.niveau.tr("nom", lg)}))
    v.update({
        "exercice": l.exercice, "periode": _memo(p, "periode", l.periode.pk, lambda: str(l.periode)), "debut": l.periode.debut,
        "valeur": valeur_fichier(r, k),
        "na": _memo(p, "terme", bool(r and r.non_applicable), lambda: traduire("Oui" if r and r.non_applicable else "Non", lg)),
        "n1": valeur_fichier(l.n1, k),
        "comparaison": _memo(p, "comparaison", l.campagne.pk if l.campagne else None,
                             lambda: str(S.periode_comparaison(l.campagne) or "") if l.campagne else ""),
        # statut et origine : quelques valeurs possibles, traduites une fois par export
        "statut": _memo(p, "statut", r.statut if r else None, lambda: traduire(statut_libelle(l), lg)),
        "origine": _memo(p, "origine", r.origine, lambda: traduire(r.get_origine_display(), lg)) if r else "",
        "commentaire": r.commentaire if r else "", "saisi_par": personne(r.saisi_par) if r else "",
        "date_maj": r.date_maj if r else None, "valide_par": personne(r.valide_par) if r else "",
        "date_validation": r.date_validation if r else None, "preuves": getattr(r, "nb_preuves", 0) if r else 0,
    })
    return [v.get(c, "") for c in _colonnes(p)]


def entetes_base(p):
    return [titre for _, titre, _ in colonnes_base(p)]


def _onglet_flux(wb, titre, entetes, roles, tailles, figer, nom_table, lignes, bulle=None):
    """Onglet de données d'un classeur en écriture seule (``X.classeur(ecriture_seule=True)``) : réglages d'abord
    (largeurs, volets figés, mise en page, hauteur des en-têtes), puis les en-têtes aux couleurs de la légende (rôle de
    chaque colonne), puis les lignes, écrites directement en XML (``X.LignesRapides``) sans garder les cellules en
    mémoire. ``lignes()`` : (valeurs, {indice de colonne : format Excel} ou None) de chaque ligne ; ``bulle`` : (colonne
    à partir de 0, texte, hauteur) d'une bulle sur un en-tête."""
    ws = wb.create_sheet(titre)
    X.largeurs(ws, tailles)
    ws.freeze_panes = figer
    X.mise_en_page(ws, 1)
    ws.row_dimensions[1].height = 32
    tete = X.entetes_flux(ws, entetes, roles)
    if bulle:
        X.bulle(tete[bulle[0]], bulle[1], hauteur=bulle[2])
    ws.append(tete)
    flux = X.LignesRapides(ws, 2)
    for valeurs, formats in lignes():
        flux.ecrire(valeurs, formats)
    X.table(ws, nom_table, len(entetes), flux.nb, entetes=entetes)
    return ws


def classeur_base(lignes, p, utilisateur):
    """Onglet de valeurs en vrai tableau Excel (une ligne d'en-têtes, en ligne 1, pour Power BI), plus les tables KPI et
    Organisations ; « À lire » en premier. Classeur en écriture seule : toutes les années d'une grosse installation
    (près de 100 000 lignes) tiennent dans quelques dizaines de Mo de mémoire, au lieu de plus d'un Go."""
    wb = X.classeur(ecriture_seule=True)
    cols = colonnes_base(p)
    idx = {c: i for i, (c, _, _) in enumerate(cols)}
    formats = {}

    def valeurs():
        for l in lignes:  # nombres aux décimales de l'unité, dates au format date
            if l.kpi.code not in formats:
                f = X.format_nombre_du_kpi(l.kpi)
                formats[l.kpi.code] = {idx["valeur"]: f, idx["debut"]: X.FORMAT_DATE, idx["date_maj"]: FORMAT_DATE_HEURE,
                                       idx["date_validation"]: FORMAT_DATE_HEURE, **({idx["n1"]: f} if "n1" in idx else {})}
            yield ligne_base(l, p), formats[l.kpi.code]
    _onglet_flux(wb, _t_fichier(p, "suivi.export.onglet.valeurs"), entetes_base(p), [ROLES_BASE.get(c, "info") for c, _, _ in cols],
                 [LARGEURS_BASE.get(c, 20) for c, _, _ in cols], "E2",
                 "Valeurs", valeurs,  # nom fixe, quelle que soit la langue : les requêtes Power BI le gardent
                 bulle=(idx["valeur"], _t_fichier(p, "suivi.export.base.bulle_valeur"), 110))
    _dimensions(wb, lignes, p)
    _a_lire(wb, p, utilisateur, len(lignes), [
        (_t_fichier(p, "suivi.export.base.powerbi_titre"), _t_fichier(p, "suivi.export.base.powerbi_texte")),
        (_t_fichier(p, "suivi.export.base.reimporter_titre"), _t_fichier(p, "suivi.export.base.reimporter_texte")),
        (_t_fichier(p, "suivi.export.base.dates_titre"), _t_fichier(p, "suivi.export.base.dates_texte")),
    ])
    return wb


def _dimensions(wb, lignes, p):
    """Onglets KPI et Organisations : tables de référence liées aux valeurs par « ID KPI » et « Code organisation »."""
    lg = p.langue
    plan = p.plan()
    tt = lambda cle: _t_fichier(p, cle)  # noqa: E731
    kpis = sorted({l.kpi.code: l.kpi for l in lignes}.values(), key=lambda k: plan.position(k.code, k.ordre))
    tetes = [tt(f"suivi.export.{c}") for c in ("colonne.id", "colonne.indicateur", "kpi.referentiels", "colonne.theme",
                                              "colonne.sous_theme", "kpi.ordre", "colonne.type", "kpi.type_reponse",
                                              "colonne.unite", "kpi.decimales", "kpi.granularite", "kpi.agregation", "kpi.formule")]
    tetes += [c.tr("libelle", lg) for c in champs_export(p)]

    def lignes_kpi():
        for k in kpis:
            place = plan.decrire(k.code)
            yield ([k.code, nom_kpi(k, lg), " ; ".join(str(r) for r in plan.referentiels_de(k.code)), place["theme"],
                    place["sous_theme"], k.ordre, k.type_saisie.tr("libelle", lg), k.type_reponse.tr("libelle", lg), k.symbole,
                    k.decimales, niveaux_nom(p, k.granularite_id), traduire(k.methode_agregation, lg), k.formule]
                   + [valeur_champ(k, c, lg) for c in champs_export(p)]), None
    _onglet_flux(wb, "KPI", tetes, ["cle"] + ["info"] * (len(tetes) - 1),
                 [11, 60, 26, 28, 30, 8, 14, 14, 12, 10, 12, 12, 40] + [14] * len(champs_export(p)), "C2", "Indicateurs", lignes_kpi)
    orgs = sorted({l.org.id: l.org for l in lignes}.values(), key=S.cle_arbre)
    niveaux = niveaux_export(p)
    tetes = ([tt(f"suivi.export.{c}") for c in ("colonne.code_org", "colonne.organisation", "colonne.niveau", "orgs.rattachee_a",
                                               "orgs.code_rattachement")]
             + [n.tr("nom", lg) for n in niveaux] + [tt("suivi.export.orgs.active")])

    def lignes_orgs():
        for o in orgs:
            h = hierarchie(o)
            yield ([o.code, o.nom, o.niveau.tr("nom", lg), o.parent.nom if o.parent else "", o.parent.code if o.parent else ""]
                   + [h.get(n.code, "") for n in niveaux] + [traduire("Oui" if o.actif else "Non", lg)]), None
    _onglet_flux(wb, tt("suivi.export.onglet.organisations"), tetes,
                 ["cle"] + ["info"] * (len(tetes) - 1), [16, 28, 10, 24, 16] + [20] * len(niveaux) + [8], "C2", "Organisations",
                 lignes_orgs)


def _a_lire(wb, p, utilisateur, nb, propres, exemples=None):
    """Onglet « À lire » en premier : ce que contient le fichier, comment le lire (``propres`` : paragraphes propres à
    la présentation, puis ce qu'il faut savoir), enfin les réglages de l'export (la lecture
    d'abord, les métadonnées ensuite). ``exemples`` : légende propre au fichier (cases d'exemple)."""
    lg = p.langue
    tt = lambda cle, **kw: _t_fichier(p, cle, **kw)  # noqa: E731
    description = tt(f"suivi.export.presentation.{p.presentation}_aide")
    titre = getattr(p, "_titre", "") or tt(f"suivi.export.presentation.{p.presentation}")
    formules = p.formules()
    if p.organisations:
        organisations = tt("suivi.export.lire.organisations_choisies", n=len(p.organisations))
    else:
        organisations = tt("suivi.export.lire.organisations_toutes")
    X.feuille_a_lire(wb, f"{titre} – {outil()}", [
        (tt("suivi.export.lire.contenu"), description),
        "# " + tt("suivi.export.lire.comment_lire"),
    ] + propres + [
        (tt("suivi.export.lire.pourcentages"), tt("suivi.export.lire.pourcentages_formules" if formules
                                                   else "suivi.export.lire.pourcentages_texte")),
        (tt("suivi.export.lire.nombres"), tt("suivi.export.lire.nombres_texte")),
        ("N/A", tt("suivi.export.lire.na_texte")),
        (tt("suivi.export.lire.perimetre"), tt("suivi.export.lire.perimetre_texte")),
        "# " + tt("suivi.export.lire.reglages"),
        (tt("suivi.export.lire.exporte_le"), DC.date_heure_courte(timezone.localtime()) + f" · {utilisateur}"),
        (tt("suivi.export.lire.exercices"), ", ".join(str(a) for a in p.annees()) or "—"),
        (tt("suivi.export.lire.periodes"), ", ".join(l for c, l in types_periodes(lg) if c in p.periodes)
         or tt("suivi.export.lire.periodes_toutes")),
        (tt("suivi.export.lire.valeurs"), ", ".join(l for c, l in contenus(lg) if c in p.contenus)),
        (tt("suivi.export.lire.types_kpi"), ", ".join(l for c, l in types_export(lg) if c in p.types)),
        (tt("suivi.export.lire.niveaux"), ", ".join(n.tr("nom", lg) for n in niveaux_export(p) if n.code in p.niveaux)),
        (tt("suivi.export.lire.organisations"), organisations),
        (tt("suivi.export.lire.referentiel"), str(p.plan().referentiel or tt("suivi.export.lire.referentiel_tous"))),
        (tt("suivi.export.lire.langue"), L.libelle(lg)),
        (tt("suivi.export.lire.valeurs_exportees"), _nombre_texte(nb, 0, lg)),
    ], lg, index=0, exemples=exemples)


def _exemple(texte, fond="FFFFFF", encre="1E2A38", gras=False, italique=False, motif=None, aide=""):
    return (texte, fond, encre, gras, italique, motif, aide)


def _exemples_tableau(p, seuil, comparaison):
    """Légende du tableau lisible : cases d'exemple dans les vraies couleurs du fichier (palette de l'installation)."""
    tt = lambda cle, **kw: _t_fichier(p, cle, **kw)  # noqa: E731
    sortie = [_exemple(tt("suivi.export.legende.saisie"), aide=tt("suivi.export.legende.saisie_aide")),
              _exemple(tt("suivi.export.legende.calculee"), encre=X.VIOLET, aide=tt(
                  "suivi.export.legende.calculee_formules_aide" if p.formules() else "suivi.export.legende.calculee_aide")),
              _exemple(tt("suivi.export.legende.brouillon"), italique=True, aide=tt("suivi.export.legende.brouillon_aide"))]
    if p.n1:
        sortie.append(_exemple(tt("suivi.export.legende.comparaison", comparaison=comparaison), X.GRIS, X.GRIS_TEXTE,
                               aide=tt("suivi.export.legende.comparaison_aide")))
    if seuil is not None:
        sortie.append(_exemple(tt("suivi.export.legende.ecart", seuil=f"{seuil * 100:.0f}"), X.ORANGE_ALERTE, X.ORANGE_TEXTE, True,
                               aide=tt("suivi.export.legende.ecart_aide", comparaison=comparaison)))
    sortie.append(_exemple(tt("suivi.export.legende.sans_objet"), motif=HACHURE, encre=X.GRIS_TEXTE,
                           aide=tt("suivi.export.legende.sans_objet_aide")))
    return sortie


def _statut_couleurs():
    """Fond et texte des statuts (rapport de revue) : mêmes pastilles qu'à l'écran ; « calculé » aux couleurs d'accent de
    la palette de l'installation (comme le texte des valeurs calculées)."""
    return {**STATUT_COULEURS, "calcule": (X.VIOLET_PALE, X.VIOLET)}


def _exemples_revue(p, seuil):
    """Légende du rapport de revue : statuts, valeur calculée, écart au-delà du seuil."""
    tt = lambda cle, **kw: _t_fichier(p, cle, **kw)  # noqa: E731
    couleurs = _statut_couleurs()
    sortie = [_exemple(traduire(Reponse.Statut(s).label, p.langue), *couleurs[s], True,
                       aide=tt(f"suivi.export.legende.statut_{s}_aide"))
              for s in (Reponse.Statut.VALIDE, Reponse.Statut.BROUILLON, Reponse.Statut.A_SAISIR)]
    if "calcule" in p.contenus:  # statuts des KPI calculés : pastille « Calculé », « Incomplet » si une source manque
        sortie += [_exemple(traduire(Reponse.Statut(s).label, p.langue), *couleurs[s], True,
                            aide=tt(f"suivi.export.legende.statut_{s}_aide"))
                   for s in (Reponse.Statut.CALCULE, Reponse.Statut.INCOMPLET)]
    sortie.append(_exemple(tt("suivi.export.legende.calculee"), encre=X.VIOLET, gras=True, aide=tt("suivi.export.legende.calculee_aide")))
    if seuil is not None:
        sortie.append(_exemple(tt("suivi.export.legende.ecart", seuil=f"{seuil * 100:.0f}"), X.ORANGE_ALERTE, X.ORANGE_TEXTE, True,
                               aide=tt("suivi.export.legende.ecart_revue_aide")))
    return sortie


# ---------------------------------------------------------------- présentation « tableau lisible »
def par_periode(lignes):
    """{période: lignes}, dans l'ordre chronologique (les lignes arrivent déjà triées)."""
    groupes = {}
    for l in lignes:
        groupes.setdefault(l.periode, []).append(l)
    return groupes


def nom_onglet(periode):
    """Nom d'onglet Excel d'une période (« 2026 », « mars 2026 », « 2026-27 ») : sans « / », 31 caractères au plus."""
    return str(periode).replace("/", "-").replace(":", " ")[:31]


def classeur_tableau(lignes, p, utilisateur):
    """Un onglet par période : KPI en lignes (regroupés par thème et sous-thème), organisations en colonnes."""
    wb = X.classeur()
    groupes = par_periode(lignes)
    if p.formules():
        from .formules_excel import Contexte

        p._formules = Contexte()  # KPI, organisations et formules lus une fois pour tous les onglets
    for periode, ls in groupes.items():
        chiffres = [l for l in ls if not l.kpi.est_texte]
        if chiffres:
            _onglet_tableau(wb.create_sheet(nom_onglet(periode)), periode, chiffres, p)
    _onglet_redige(wb, lignes, p)
    campagne = next((l.campagne for l in lignes if l.campagne), None)
    seuil = campagne.seuil_ecart if campagne and p.n1 else None
    comparaison = S.libelle_comparaison(campagne) if campagne else "N-1"
    if not groupes:
        wb.create_sheet(_t_fichier(p, "suivi.export.tableau.aucune_donnee"))["A1"] = _t_fichier(p, "suivi.export.tableau.aucune_valeur")
    _a_lire(wb, p, utilisateur, len(lignes), [
        (_t_fichier(p, "suivi.export.tableau.lecture_titre"), _t_fichier(p, "suivi.export.tableau.lecture_texte")),
        (_t_fichier(p, "suivi.export.tableau.ecarts_titre"), _t_fichier(p, "suivi.export.tableau.ecarts_texte")),
        (_t_fichier(p, "suivi.export.tableau.themes_titre"), _t_fichier(p, "suivi.export.tableau.themes_texte")),
        (_t_fichier(p, "suivi.export.tableau.impression_titre"), _t_fichier(p, "suivi.export.tableau.impression_texte")),
    ] + _a_lire_redige(p, lignes) + (_a_lire_formules(p) if p.formules() else []),
        exemples=_exemples_tableau(p, seuil, comparaison))
    return wb


def _a_lire_redige(p, lignes):
    """Paragraphe de l'« À lire » quand le fichier a un onglet « Réponses rédigées »."""
    if not any(l.kpi.est_texte for l in lignes):
        return []
    return [(_t_fichier(p, "suivi.export.redige.titre"), _t_fichier(p, "suivi.export.redige.a_lire"))]


def _onglet_redige(wb, lignes, p):
    """Réponses rédigées (KPI qualitatifs) dans un onglet à part, en texte simple et en pleine largeur : elles n'élargissent
    plus les colonnes chiffrées du tableau ni de la revue. Une ligne par KPI, organisation et
    période ; la réponse de la période de comparaison à côté si l'export la demande."""
    from .markdown import texte_lisible

    ls = [l for l in lignes if l.kpi.est_texte]
    if not ls:
        return
    lg = p.langue
    ws = wb.create_sheet(_t_fichier(p, "suivi.export.redige.onglet")[:31])
    C = X.Colonne
    colonnes = [C("periode", "suivi.export.colonne.periode", 12, "cle"), C("id", "suivi.export.colonne.id", 11, "cle"),
                C("indicateur", "suivi.export.colonne.indicateur", 40, retour=True),
                C("organisation", "suivi.export.colonne.organisation", 22),
                C("reponse", "suivi.export.redige.col.reponse", 80, retour=True), C("statut", "suivi.export.revue.col.statut", 12)]
    if p.n1:
        colonnes.append(C("n1", "suivi.export.redige.col.n1", 60, retour=True))
    debut = X.bandeau(ws, f"{outil()} – " + _t_fichier(p, "suivi.export.redige.onglet"),
                      [_t_fichier(p, "suivi.export.redige.bandeau")], lg, roles=False)
    plan = p.plan()
    tri = sorted(ls, key=lambda l: (l.periode.debut, S.cle_arbre(l.org), plan.position(l.kpi.code, l.kpi.ordre)))
    texte = lambda r: ("N/A" if r.non_applicable else texte_lisible(r.texte)) if r else ""  # noqa: E731
    lignes_ws = []
    for l in tri:
        v = {"periode": str(l.periode), "id": l.kpi.code, "indicateur": nom_kpi(l.kpi, lg), "organisation": l.org.nom,
             "reponse": texte(l.reponse), "statut": traduire(statut_libelle(l), lg), "n1": texte(l.n1)}
        lignes_ws.append([v[c.cle] for c in colonnes])
    fin = X.ecrire_tableau(ws, colonnes, lignes_ws, lg, debut=debut, figer="reponse")
    for n in range(debut + 1, fin + 1):
        for c in ("reponse", "n1"):
            if any(x.cle == c for x in colonnes):
                ws.cell(n, [x.cle for x in colonnes].index(c) + 1).alignment = Alignment(wrap_text=True, vertical="top")
        ws.cell(n, [x.cle for x in colonnes].index("statut") + 1).font = Font(size=9, color=X.GRIS_TEXTE)


def _a_lire_formules(p):
    """Paragraphes de l'onglet « À lire » d'un tableau en formules Excel : les règles, les cases restées en valeur et
    pourquoi, le bilan."""
    from .formules_excel import RAISONS

    tt = lambda cle, **kw: _t_fichier(p, cle, **kw)  # noqa: E731
    compte = p._formules.compte
    detail = "; ".join(tt("suivi.export.formules.bilan_raison", n=_nombre_texte(compte[r], 0, p.langue),
                          raison=tt(f"suivi.export.formules.court.{r}")) for r in RAISONS if compte[r])
    return [
        "# " + tt("suivi.export.formules.titre"),
        (tt("suivi.export.formules.principe_titre"), tt("suivi.export.formules.principe_texte")),
        (tt("suivi.export.formules.regles_titre"), tt("suivi.export.formules.regles_texte")),
        (tt("suivi.export.formules.valeurs_titre"), tt("suivi.export.formules.valeurs_texte")),
        (tt("suivi.export.formules.ouverture_titre"), tt("suivi.export.formules.ouverture_texte")),
        (tt("suivi.export.formules.bilan_titre"), tt("suivi.export.formules.bilan_texte", n=_nombre_texte(compte["formules"], 0, p.langue),
                                                     m=_nombre_texte(sum(compte[r] for r in RAISONS), 0, p.langue))
         + (f" ({detail})" if detail else "")),
    ]


def grille(ls):
    """(KPI dans l'ordre, organisations dans l'ordre de l'arbre, {(kpi, org): ligne})."""
    kpis = list({l.kpi.code: l.kpi for l in ls}.values())
    orgs = sorted({l.org.id: l.org for l in ls}.values(), key=S.cle_arbre)
    return kpis, orgs, {(l.kpi.code, l.org.id): l for l in ls}


def _depasse(l, seuil):
    """Écart avec la période de comparaison au-delà du seuil de la campagne."""
    return S.depasse_seuil(_ecart(l), seuil)


HACHURE = PatternFill(fill_type="lightUp", fgColor="D9D9D9", bgColor="F7F7F7")  # case sans objet à ce niveau (discrète)


def _hex(couleur, defaut):
    """Couleur réglée dans l'outil (« #RRGGBB ») pour openpyxl (« RRGGBB »), sinon la couleur par défaut."""
    c = (couleur or "").lstrip("#")
    return c.upper() if len(c) == 6 else defaut


def sans_objet(k, o):
    """Vrai si le KPI ne peut pas avoir de valeur pour l'organisation : sous son niveau de saisie (sauf paramètre hérité,
    repris en dessous), ou au-dessus quand il ne s'additionne pas (agrégation « Aucune », sans saisie au-dessus)."""
    if not k.granularite_id or not o.niveau_id:
        return False
    rang_k, rang_o = k.granularite.rang, o.niveau.rang
    if rang_o > rang_k:
        return not k.est_herite
    if rang_o < rang_k:
        return k.methode_agregation == k.Agregation.AUCUNE and not k.est_herite and not k.saisissable_au_dessus
    return False


def _onglet_tableau(ws, periode, ls, p):
    """Une seule ligne d'en-têtes (sans cellules fusionnées) : ID KPI, Indicateur, Unité, puis une colonne par
    organisation (et sa valeur de comparaison) ; thèmes et sous-thèmes en lignes de groupe repliables."""
    lg = p.langue
    kpis, orgs, cases = grille(ls)
    campagne = ls[0].campagne
    comparaison = S.libelle_comparaison(campagne) if campagne else "N-1"
    seuil = campagne.seuil_ecart if campagne and p.n1 else None
    C = X.Colonne
    colonnes = [C("id", "suivi.export.colonne.id", 11, "cle"), C("indicateur", "suivi.export.colonne.indicateur", 50, retour=True),
                C("type", "suivi.export.colonne.type_court", 9), C("unite", "suivi.export.colonne.unite", 9)]
    PREMIERE = 5  # première colonne d'organisation (après ID, indicateur, type, unité)
    for o in orgs:  # réponses rédigées : dans leur propre onglet, les colonnes restent étroites
        colonnes.append(C(f"org:{o.id}", largeur=14, texte=o.nom))
        if p.n1:
            colonnes.append(C(f"n1:{o.id}", largeur=12, texte=f"{o.nom} – {comparaison}"))
    formules = p.formules()
    debut = X.bandeau(ws, f"{outil()} – {titre_periode(periode, lg)}", [
        _t_fichier(p, "suivi.export.tableau.legende_formules" if formules else "suivi.export.tableau.legende"),
        _t_fichier(p, "suivi.export.tableau.dimensions_formules" if formules else "suivi.export.tableau.dimensions",
                   n=len(orgs), kpis=len(kpis)),
    ], lg, roles=False, exemples=[e[:6] for e in _exemples_tableau(p, seuil, comparaison)])
    X.ecrire_tableau(ws, colonnes, [], lg, debut=debut, figer=colonnes[PREMIERE - 1].cle if orgs else None, filtre=False)
    for j, c in enumerate(colonnes[PREMIERE - 1:], start=PREMIERE):  # organisations : couleur de leur niveau ; comparaison en gris
        cell = ws.cell(debut, j)
        o = next(o for o in orgs if c.cle.endswith(f":{o.id}"))
        if c.cle.startswith("n1:"):
            cell.fill, cell.font = PatternFill("solid", fgColor=X.GRIS), Font(bold=True, size=9, color=X.GRIS_TEXTE)
        else:
            fond, encre = X.NIVEAU_COULEURS.get(o.niveau_id, (X.VIOLET, "FFFFFF"))
            cell.fill, cell.font = PatternFill("solid", fgColor=fond), Font(bold=True, color=encre)
            X.bulle(cell, _t_fichier(p, "suivi.export.tableau.bulle_org", nom=o.nom, niveau=o.niveau.tr("nom", lg), code=o.code), hauteur=50)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[debut].height = 44
    nb, par_org = len(colonnes), 2 if p.n1 else 1
    ligne, theme, sous = debut + 1, None, None
    plan = p.plan()
    orange, encre_orange = PatternFill("solid", fgColor=X.ORANGE_ALERTE), X.ORANGE_TEXTE
    rangees = {}  # ligne de chaque KPI (formules Excel)
    for k in kpis:
        titre, sous_titre = plan.titres(k.code)
        if titre != theme:
            theme, sous = titre, None
            for col in range(1, nb + 1):
                ws.cell(ligne, col).fill = PatternFill("solid", fgColor=X.ROSE)
            X.ecrire_cellule(ws, ligne, 1, titre).font = Font(bold=True, size=12, color=X.MAGENTA)
            ligne += 1
        if sous_titre and sous_titre != sous:
            sous = sous_titre
            for col in range(1, nb + 1):
                ws.cell(ligne, col).fill = PatternFill("solid", fgColor=X.ROSE_PALE)
            X.ecrire_cellule(ws, ligne, 1, sous).font = Font(bold=True, color=X.VIOLET)
            ws.row_dimensions[ligne].outline_level = 1
            ligne += 1
        code = X.ecrire_cellule(ws, ligne, 1, k.code)
        code.fill, code.font = PatternFill("solid", fgColor=X.GRIS_CELLULE), Font(size=9, color=X.GRIS_ENTETE_TEXTE)
        X.ecrire_cellule(ws, ligne, 2, nom_kpi(k, lg)).alignment = Alignment(wrap_text=True, vertical="top")
        # type de saisie (Saisi, Calculé, paramètre hérité…) : étiquette courte aux couleurs réglées dans l'outil
        ts = k.type_saisie
        t = X.ecrire_cellule(ws, ligne, 3, ts.tr("abrege", lg) or ts.tr("libelle", lg))
        t.alignment = Alignment(horizontal="center", vertical="top")
        t.font = Font(size=9, bold=True, color=_hex(ts.couleur_texte, X.GRIS_TEXTE))
        t.fill = PatternFill("solid", fgColor=_hex(ts.couleur_fond, X.GRIS_CELLULE))
        X.bulle(t, ts.tr("libelle", lg), hauteur=30)
        X.ecrire_cellule(ws, ligne, 4, k.symbole).font = Font(size=9, color=X.GRIS_TEXTE)
        fmt = _format_lisible(k, formules)
        rangees[k.code] = ligne
        for j, o in enumerate(orgs):
            l = cases.get((k.code, o.id))
            col = PREMIERE + j * par_org
            if l is None:
                if sans_objet(k, o):  # pas de valeur possible à ce niveau : hachuré gris (valeur et comparaison)
                    for c2 in range(col, col + par_org):
                        ws.cell(ligne, c2).fill = HACHURE
                continue
            cell = ws.cell(ligne, col)
            _case(cell, l.reponse, k, fmt, l.calculee, fraction=formules)
            if p.n1:
                _case(ws.cell(ligne, col + 1), l.n1, k, fmt, l.calculee, n1=True, fraction=formules)
                if _depasse(l, seuil):
                    cell.fill = orange
                    cell.font = Font(bold=True, color=encre_orange, italic=cell.font.italic)
        for c2 in range(1, nb + 1):  # libellé sur deux lignes : toute la ligne calée en haut (sinon ID et valeurs en bas)
            c_ = ws.cell(ligne, c2)
            if c_.value is not None and c_.alignment.vertical != "top":
                a = c_.alignment
                c_.alignment = Alignment(horizontal=a.horizontal, vertical="top", wrap_text=a.wrap_text, indent=a.indent)
        ws.row_dimensions[ligne].outline_level = 2 if sous_titre else 1
        ligne += 1
    ws.sheet_properties.outlinePr.summaryBelow = False
    # impression : au-delà de 8 organisations, plusieurs pages de large (une page de large serait illisible), avec ID,
    # indicateur, type et unité répétés à gauche de chaque page
    if len(orgs) > 8:
        ws.page_setup.fitToWidth = 0
        ws.print_title_cols = "A:D"
    if formules:
        _poser_formules(ws, periode, cases, rangees, {o.id: PREMIERE + j * par_org for j, o in enumerate(orgs)}, p)


def _poser_formules(ws, periode, cases, rangees, colonnes, p):
    """Tableau en formules Excel : chaque case calculée par l'outil devient une formule qui cite ses sources quand elle
    redonne exactement le chiffre de l'outil ; sinon elle garde sa valeur, avec une bulle qui dit pourquoi."""
    from .formules_excel import FormulesOnglet, Impossible

    ctx = p._formules
    fo = FormulesOnglet(periode, {cle: l.reponse for cle, l in cases.items()}, rangees, colonnes, ctx)
    titre = _t_fichier(p, "suivi.export.formules.bulle_titre")
    for (code, org_id), l in cases.items():
        try:
            texte, raison, _ = fo.decision(code, org_id)
        except Impossible as e:
            texte, raison = None, e.args[0]
        if texte:
            ws.cell(rangees[code], colonnes[org_id]).value = "=" + texte
            ctx.compte["formules"] += 1
        elif raison:
            X.bulle(ws.cell(rangees[code], colonnes[org_id]),
                    f"{titre}\n{_t_fichier(p, f'suivi.export.formules.raison.{raison}')}", largeur=300, hauteur=90)
            ctx.compte[raison] += 1




def _case(cell, r, k, fmt, calculee, n1=False, fraction=False):
    """Valeur d'une case du tableau : pourcentage de 0 à 100 (en fraction avec ``fraction``), N/A en texte, couleur selon
    l'origine."""
    v = _valeur_lisible(r, k, fraction)
    if v is None:
        return
    cell.value = X.sans_controle(v)
    if isinstance(v, str) and v.startswith(X.DANGEREUX):  # réponse en texte (liste, texte rédigé) : jamais une formule
        cell.data_type = "s"
    if k.est_texte and v != "N/A":  # texte rédigé (Markdown brut) : retours à la ligne gardés, cellule renvoyée à la ligne
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        cell.font = Font(color=X.GRIS_TEXTE if n1 else "1E2A38", italic=r.statut == Reponse.Statut.BROUILLON and not n1, size=9 if n1 else 11)
        if n1:
            cell.fill = PatternFill("solid", fgColor=X.GRIS)
        return
    if v == "N/A":
        cell.alignment = Alignment(horizontal="center")
        cell.font = Font(color=X.GRIS_TEXTE)
        return
    cell.number_format = fmt
    couleur = X.GRIS_TEXTE if n1 else X.VIOLET if calculee else "1E2A38"
    cell.font = Font(color=couleur, italic=r.statut == Reponse.Statut.BROUILLON and not n1, size=9 if n1 else 11)
    if n1:
        cell.fill = PatternFill("solid", fgColor=X.GRIS)


def lignes_tableau_csv(lignes, p):
    """Version CSV du tableau : une ligne par KPI et période, une colonne par organisation (et sa comparaison)."""
    kpis, orgs, _ = grille(lignes)
    tete = [_t_fichier(p, f"suivi.export.colonne.{c}") for c in ("exercice", "periode", "id", "indicateur", "theme", "type", "unite")]
    campagnes = {l.campagne.pk: l.campagne for l in lignes if l.campagne}
    toutes_n1 = all(c.periode.annuelle or c.referentiel.comparaison != "P-1" for c in campagnes.values())
    comparaison = "N-1" if toutes_n1 else _t_fichier(p, "suivi.export.tableau.periode_comparaison")
    for o in orgs:
        tete += [o.nom] + ([f"{o.nom} ({comparaison})"] if p.n1 else [])
    sortie = [tete]
    for periode, ls in par_periode(lignes).items():
        cases = {(l.kpi.code, l.org.id): l for l in ls}
        for k in kpis:
            if not any((k.code, o.id) in cases for o in orgs):
                continue
            ligne = [ls[0].exercice, str(periode), k.code, nom_kpi(k, p.langue), p.plan().titres(k.code)[0],
                     k.type_saisie.tr("libelle", p.langue), k.symbole]
            for o in orgs:
                l = cases.get((k.code, o.id))
                # sans objet à ce niveau (CSV : pas de couleur) : « – », à distinguer d'une case vide à saisir
                vide = "–" if l is None and sans_objet(k, o) else None
                ligne.append(_valeur_lisible(l.reponse, k) if l else vide)
                if p.n1:
                    ligne.append(_valeur_lisible(l.n1, k) if l else vide)
            sortie.append(ligne)
    return sortie


# ---------------------------------------------------------------- présentation « rapport de revue »
_C = X.Colonne
COLONNES_REVUE = [
    _C("id", "suivi.export.revue.col.id", 11, "cle"), _C("indicateur", "suivi.export.revue.col.indicateur", 50, retour=True),
    _C("valeur", "suivi.export.revue.col.valeur", 14), _C("unite", "suivi.export.revue.col.unite", 9),
    _C("n1", "suivi.export.revue.col.n1", 13),
    _C("ecart", "suivi.export.revue.col.ecart", 10, format='+0.0 %;-0.0 %;0.0 %'), _C("statut", "suivi.export.revue.col.statut", 12),
    _C("commentaire", "suivi.export.revue.col.commentaire", 44, retour=True),
    _C("saisi_par", "suivi.export.revue.col.saisi_par", 22),
    _C("date_maj", "suivi.export.revue.col.date_maj", 12, format=X.FORMAT_DATE),
    # qui a validé et quand : la trace qu'attend un audit 
    _C("valide_par", "suivi.export.revue.col.valide_par", 22),
    _C("date_validation", "suivi.export.revue.col.date_validation", 12, format=X.FORMAT_DATE),
    _C("preuves", "suivi.export.revue.col.preuves", 8),
    # organisation sur chaque ligne : elle reste lisible quand on filtre (le bandeau de l'organisation disparaît alors)
    _C("organisation", "suivi.export.colonne.organisation", 20), _C("code_org", "suivi.export.colonne.code_org", 12),
]
STATUT_COULEURS = {  # fond, texte : mêmes pastilles qu'à l'écran
    "valide": ("D7F3E6", "0B6644"), "brouillon": ("FFF5C2", "6A5A00"), "a_saisir": ("EAE7EA", "77727C"),
    "calcule": ("E7E3F3", "6A4FB3"), "incomplet": ("EAE7EA", "77727C"), "erreur": ("FDECEC", "9B1C1C"),
}


def _ecart(l):
    r, n1 = l.reponse, l.n1
    if not r or not n1 or r.non_applicable or n1.non_applicable or not l.kpi.est_numerique:
        return None  # pas d'écart sur un décompte de réponses oui / non ou liste
    return S.ecart(r.valeur, n1.valeur)


def ligne_revue(l, p):
    k, r = l.kpi, l.reponse
    if k.est_texte:  # réponse rédigée : un extrait en texte simple (la réponse entière est dans « Réponses rédigées »)
        from .markdown import extrait

        lire = lambda x: ("N/A" if x.non_applicable else extrait(x.texte)) if x else None  # noqa: E731
        valeur, n1 = lire(r), lire(l.n1)
    else:
        valeur, n1 = _valeur_lisible(r, k), _valeur_lisible(l.n1, k)
    valide = r is not None and r.statut == Reponse.Statut.VALIDE and not l.calculee
    v = {"id": k.code, "indicateur": nom_kpi(k, p.langue), "valeur": valeur,
         "unite": k.symbole, "n1": n1,
         "ecart": _ecart(l), "statut": traduire(statut_libelle(l), p.langue), "commentaire": r.commentaire if r else "",
         "saisi_par": str(r.saisi_par) if r and r.saisi_par else "", "date_maj": r.date_maj if r and not l.calculee else None,
         "valide_par": str(r.valide_par) if valide and r.valide_par else "",
         "date_validation": r.date_validation if valide else None,
         "preuves": getattr(r, "nb_preuves", 0) if r else 0, "organisation": l.org.nom, "code_org": l.org.code}
    return [v[c.cle] for c in COLONNES_REVUE]


def entetes_revue(p, csv=False):
    """En-têtes de la revue ; en CSV, l'écart est en pourcentage (« Écart (%) »)."""
    return [_t_fichier(p, "suivi.export.revue.col.ecart_pourcent") if csv and c.cle == "ecart" else c.titre(p.langue)
            for c in COLONNES_REVUE]


def classeur_revue(lignes, p, utilisateur):
    """« À lire », synthèse de l'avancement, puis un onglet par période : organisation › thème › KPI, prêt à relire et
    à imprimer (une organisation par page)."""
    wb = X.classeur()
    groupes = par_periode(lignes)
    _synthese(wb, groupes, p)
    for periode, ls in groupes.items():
        _onglet_revue(wb.create_sheet(nom_onglet(periode)), periode, ls, p)
    _onglet_redige(wb, lignes, p)
    campagne = next((l.campagne for l in lignes if l.campagne), None)
    _a_lire(wb, p, utilisateur, len(lignes), _a_lire_redige(p, lignes) + [
        (_t_fichier(p, "suivi.export.revue.synthese_titre"), _t_fichier(p, "suivi.export.revue.synthese_texte")),
        (_t_fichier(p, "suivi.export.revue.liens_titre"), _t_fichier(p, "suivi.export.revue.liens_texte")),
        (_t_fichier(p, "suivi.export.revue.ecarts_titre"), _t_fichier(p, "suivi.export.revue.ecarts_texte")),
        (_t_fichier(p, "suivi.export.revue.impression_titre"), _t_fichier(p, "suivi.export.revue.impression_texte")),
    ], exemples=_exemples_revue(p, campagne.seuil_ecart if campagne else None))
    return wb


def _avancement(ls):
    """{organisation: [cases, validées, brouillons]} des cases saisissables (hors KPI calculés et totaux)."""
    compte = {}
    for l in ls:
        if l.calculee or not l.attendue:
            continue
        c = compte.setdefault(l.org, [0, 0, 0])
        c[0] += 1
        statut = l.reponse.statut if l.reponse else "a_saisir"
        c[1] += statut == Reponse.Statut.VALIDE
        c[2] += statut == Reponse.Statut.BROUILLON
    return compte


def _phrase_avancement(p, total, valides, brouillons):
    taux = f"{arrondi(valides / total * 100, 0)}" if total else "0"
    return _t_fichier(p, "suivi.export.revue.avancement", n=brouillons, valides=valides, total=total, taux=taux,
                      brouillons=brouillons, a_saisir=total - valides - brouillons)


def _synthese(wb, groupes, p):
    lg = p.langue
    ws = wb.create_sheet(_t_fichier(p, "suivi.export.revue.synthese_onglet"))
    ws.sheet_view.showGridLines = False
    C = X.Colonne
    cle = "suivi.export.revue.synthese_col."
    colonnes = [C("periode", cle + "periode", 12, "cle"), C("organisation", cle + "organisation", 36),
                C("niveau", cle + "niveau", 12), C("total", cle + "total", 12),
                C("valides", cle + "valides", 11), C("brouillons", cle + "brouillons", 11),
                C("a_saisir", cle + "a_saisir", 11), C("avancement", cle + "avancement", 16, format="0 %")]
    lignes, orgs, totaux = [], [], [0, 0, 0]
    for periode, ls in groupes.items():
        for o, (total, valides, brouillons) in sorted(_avancement(ls).items(), key=lambda c: S.cle_arbre(c[0])):
            lignes.append([str(periode), o.nom, o.niveau.tr("nom", lg), total, valides, brouillons,
                           total - valides - brouillons, valides / total if total else 0])
            orgs.append(o)
            totaux = [totaux[0] + total, totaux[1] + valides, totaux[2] + brouillons]
    debut = X.bandeau(ws, f"{outil()} – {_t_fichier(p, "suivi.export.revue.synthese_sous_titre")}", [
        _phrase_avancement(p, *totaux),
        _t_fichier(p, "suivi.export.revue.synthese_aide"),
    ], lg, roles=False)  # synthèse en lecture : pas de légende « à remplir / clé » (rien ne s'y remplit)
    fin = X.ecrire_tableau(ws, colonnes, lignes, lg, debut=debut, figer="total")
    for n, o in enumerate(orgs, start=debut + 1):
        fond, encre = X.NIVEAU_COULEURS.get(o.niveau_id, (X.GRIS, "000000"))
        ws.cell(n, 3).fill, ws.cell(n, 3).font = PatternFill("solid", fgColor=fond), Font(bold=True, size=9, color=encre)
        ws.cell(n, 2).alignment = Alignment(horizontal="left", vertical="top", indent=2 * (len(S.cle_arbre(o)) - 1))  # arbre
    if fin > debut:
        ws.conditional_formatting.add(f"H{debut + 1}:H{fin}", DataBarRule(start_type="num", start_value=0, end_type="num",
                                                                          end_value=1, color="3CC98F"))


def _lien_case(p, l):
    """Adresse de la case dans l'outil (panneau de saisie), si l'adresse de l'outil est connue."""
    from django.urls import reverse

    adresse = getattr(p, "_adresse", "")
    if not adresse or l.campagne is None:
        return None
    return adresse.rstrip("/") + reverse("collecte:cellule", args=[l.campagne.pk, l.kpi.code, l.org.id])


def _onglet_revue(ws, periode, ls, p):
    from openpyxl.worksheet.pagebreak import Break

    lg = p.langue
    campagne = ls[0].campagne
    seuil = campagne.seuil_ecart if campagne else None
    prec = S.periode_comparaison(campagne) if campagne else None
    colonnes = list(COLONNES_REVUE)
    i = {c.cle: j for j, c in enumerate(colonnes)}
    # réponses rédigées : un extrait en texte simple ici, la réponse entière dans l'onglet « Réponses rédigées »
    colonnes[i["valeur"]] = X.Colonne("valeur", "", 14, texte=_t_fichier(p, "suivi.export.revue.col.valeur_periode", periode=periode))
    if prec:
        colonnes[i["n1"]] = X.Colonne("n1", "", 13, texte=f"{S.libelle_comparaison(campagne)} ({prec})")
    compte = _avancement(ls)
    statuts = _statut_couleurs()
    totaux = [sum(c[x] for c in compte.values()) for x in range(3)]
    sans_seuil = "" if seuil is not None else " · " + _t_fichier(p, "suivi.export.revue.sans_seuil")
    debut = X.bandeau(ws, f"{outil()} – " + _t_fichier(p, "suivi.export.revue.titre_periode", titre=_t_fichier(p, "suivi.export.revue.titre"), periode=titre_periode(periode, lg)), [
        _phrase_avancement(p, *totaux),
        _t_fichier(p, "suivi.export.revue.legende") + sans_seuil,
    ], lg, roles=False, exemples=[e[:6] for e in _exemples_revue(p, seuil)])
    X.ecrire_tableau(ws, colonnes, [], lg, debut=debut, figer="valeur")
    for c in ("valeur", "n1", "ecart", "preuves"):
        ws.cell(debut, i[c] + 1).alignment = Alignment(horizontal="right", vertical="center", wrap_text=True)
    nb = len(colonnes)
    org, theme, premiere = None, None, True
    plan = p.plan()
    n = debut
    for l in sorted(ls, key=lambda l: (S.cle_arbre(l.org), plan.position(l.kpi.code, l.kpi.ordre))):
        if l.org != org:
            org, theme = l.org, None
            n += 1
            if not premiere:
                ws.row_breaks.append(Break(id=n - 1))  # une organisation par page imprimée
            premiere = False
            total, valides, _ = compte.get(org, (0, 0, 0))
            suite = ("  ·  " + _t_fichier(p, "suivi.export.revue.validees", valides=valides, total=total)) if total else ""
            X.ecrire_cellule(ws, n, 1, f"{org.nom}  ·  {org.niveau.tr('nom', lg)}{suite}")
            fond, encre = X.NIVEAU_COULEURS.get(org.niveau_id, (X.GRIS, "000000"))
            for col in range(1, nb + 1):
                ws.cell(n, col).fill = PatternFill("solid", fgColor=fond)
            ws.cell(n, 1).font = Font(bold=True, size=13, color=encre)
            ws.row_dimensions[n].height = 24
        if plan.titres(l.kpi.code)[0] != theme:
            theme = plan.titres(l.kpi.code)[0]
            n += 1
            X.ecrire_cellule(ws, n, 2, theme).font = Font(bold=True, color=X.MAGENTA)
            ws.row_dimensions[n].outline_level = 1
        n += 1
        for j, (c, v) in enumerate(zip(colonnes, ligne_revue(l, p)), start=1):
            cell = X.ecrire_cellule(ws, n, j, X.date_locale(v))
            X.style_cellule(cell, c)
            cell.alignment = Alignment(vertical="top", wrap_text=c.retour,  # calé en haut, comme le tableau (DESIGN.md)
                                       horizontal="right" if c.cle in ("valeur", "n1") and v == "N/A" else None)
        ws.row_dimensions[n].outline_level = 2
        lien = _lien_case(p, l)
        if lien:
            ind = ws.cell(n, i["indicateur"] + 1)
            ind.hyperlink = lien
            ind.font = Font(color="1F3A93", underline="single")
        fmt = _format_lisible(l.kpi)
        valeur = ws.cell(n, i["valeur"] + 1)
        valeur.number_format = fmt
        valeur.font = Font(bold=True, color=X.VIOLET if l.calculee else "1E2A38")
        n1 = ws.cell(n, i["n1"] + 1)
        n1.number_format, n1.font, n1.fill = fmt, Font(color=X.GRIS_TEXTE), PatternFill("solid", fgColor=X.GRIS)
        if l.kpi.est_texte:  # texte rédigé : extrait sur une ligne, en texte normal
            valeur.font = Font(color="1E2A38")
        if _depasse(l, seuil):
            for cell in (ws.cell(n, i["ecart"] + 1), valeur):
                cell.fill = PatternFill("solid", fgColor=X.ORANGE_ALERTE)
                cell.font = Font(bold=True, color=X.ORANGE_TEXTE)
        statut = l.reponse.statut if l.reponse else "a_saisir"
        fond, encre = statuts.get(statut, (X.GRIS, "000000"))
        st = ws.cell(n, i["statut"] + 1)
        st.fill, st.font = PatternFill("solid", fgColor=fond), Font(bold=True, size=9, color=encre)
        st.alignment = Alignment(horizontal="center", vertical="top")
        for c in ("unite", "organisation", "code_org", "saisi_par", "date_maj", "valide_par", "date_validation", "preuves"):
            ws.cell(n, i[c] + 1).font = Font(size=9, color=X.GRIS_TEXTE)
    ws.auto_filter.ref = f"A{debut}:{X.get_column_letter(nb)}{max(n, debut + 1)}"
    ws.sheet_properties.outlinePr.summaryBelow = False


# ---------------------------------------------------------------- point d'entrée
def nom_fichier(p):
    """Nom explicite : titre (modèle d'export ou présentation), exercices, référentiel, organisation, date du jour.
    Ex. « Revue_Exercice-2026_FR-LOG_2026-10-27 »."""
    annees = p.annees()
    if len(annees) == 1:
        exercices = _t_fichier(p, "suivi.export.fichier.exercice", annee=annees[0])
    elif annees:
        exercices = _t_fichier(p, "suivi.export.fichier.exercices", premiere=annees[0], derniere=annees[-1])
    else:
        exercices = ""
    org = ""
    if len(p.organisations) == 1:
        from referentiel.models import Organisation

        org = Organisation.objects.filter(pk=p.organisations[0]).values_list("code", flat=True).first() or ""
    titre = getattr(p, "_titre", "") or _t_fichier(p, f"suivi.export.fichier.nom_{p.presentation}")
    return X.nom_fichier(titre, exercices, p.referentiel, org)


def langue_export(code):
    """Langue d'un export : celle choisie (langue active des contenus) ; sinon celle de la personne. Si sa langue
    d'interface n'est pas une langue des contenus (espagnol sans traduction des KPI…), le fichier est écrit dans cette
    langue (en-têtes, onglets, statuts) et les contenus suivent leur repli habituel (langue par défaut, référence)."""
    if code in L.codes_actifs():
        return code
    interface = L.interface()
    if not code and interface != L.courante() and interface not in L.codes_actifs():
        return interface
    return L.courante()


def exporter(utilisateur, p, titre="", adresse=""):
    """Réponse HTTP avec le fichier demandé, contenus dans la langue choisie (celle de la personne à défaut).
    ``titre`` : nom du modèle d'export (nom du fichier, onglet « À lire ») ; ``adresse`` : adresse de l'outil (liens du
    rapport de revue ; à défaut URL_PUBLIQUE)."""
    from django.conf import settings

    p._titre = titre
    p._adresse = adresse or getattr(settings, "URL_PUBLIQUE", "") or ""
    with L.session():
        p.langue = langue_export(p.langue)
        with L.activer(p.langue):
            return _exporter(utilisateur, p)


def contenu_tabulaire(lignes, p, limite=None, utilisateur=None):
    """Lignes du fichier en tableau simple (CSV, aperçu) : en-têtes puis lignes ; ``limite`` : nombre de lignes de données."""
    if p.presentation == "audit":
        from . import export_audit as EA

        return EA.contenu_tabulaire(utilisateur, lignes, p, limite)
    if p.presentation == "tableau":
        contenu = lignes_tableau_csv(lignes, p)
    elif p.presentation == "revue":
        tete = [_t_fichier(p, f"suivi.export.colonne.{c}") for c in ("exercice", "periode", "theme")]
        tri = sorted(lignes, key=lambda l: (l.periode.debut, -l.periode.fin.toordinal(), S.cle_arbre(l.org),
                                            p.plan().position(l.kpi.code, l.kpi.ordre)))
        rang_ecart = [c.cle for c in COLONNES_REVUE].index("ecart")

        def en_pourcent(ligne):  # CSV : écart en pourcentage de 0 à 100 arrondi (-4,1), comme dans le reste des fichiers
            e = ligne[rang_ecart]
            ligne[rang_ecart] = round(e * 100, 1) if e is not None else None
            return ligne
        contenu = [tete + entetes_revue(p, csv=True)] + [[l.exercice, str(l.periode), p.plan().titres(l.kpi.code)[0]] + en_pourcent(ligne_revue(l, p))
                                                         for l in tri[:limite]]
    else:
        contenu = [entetes_base(p)] + [ligne_base(l, p) for l in lignes[:limite]]
    return contenu if limite is None else contenu[:limite + 1]


def apercu(utilisateur, p, limite=10):
    """Aperçu du constructeur d'export : (en-têtes, ``limite`` premières lignes en texte, nombre total de lignes)."""
    with L.session():
        p.langue = langue_export(p.langue)
        with L.activer(p.langue):
            lignes = collecter(utilisateur, p)
            contenu = contenu_tabulaire(lignes, p, limite, utilisateur)
            total = len(lignes) if p.presentation != "tableau" else len(lignes_tableau_csv(lignes, p)) - 1
    return contenu[0], [[_texte_apercu(v) for v in r] for r in contenu[1:]], total


def _texte_apercu(v):
    """Case de l'aperçu du constructeur, comme on la lira : nombre arrondi à 2 décimales au format de la langue
    (« 66,66 », pas « 66,65957447 »), réponse rédigée en extrait de texte simple (jamais le Markdown brut). Le fichier,
    lui, garde toute la précision et le texte d'origine."""
    from .markdown import extrait
    from .templatetags.collecte import nombre

    if isinstance(v, Decimal) or (isinstance(v, float) and not isinstance(v, bool)):
        d = Decimal(str(v))
        decimales = min(max(-d.normalize().as_tuple().exponent, 0), 2)
        return nombre(d, decimales)
    if isinstance(v, str) and ("\n" in v or len(v) > 80):
        return extrait(v)
    return X.valeur_csv(v, "fr")


# Limite d'une feuille Excel : 1 048 576 lignes (en-têtes compris). Au-delà, le fichier serait invalide : l'export est refusé
# avant d'être construit (le CSV n'a pas cette limite). Seules les présentations « une ligne par valeur » sont concernées
# (« tableau » : une ligne par KPI, quelques milliers au plus).
MAX_LIGNES_EXCEL = 1_048_576
LIGNES_ENTETE_EXCEL = 20  # marge pour les lignes d'en-tête et de bandeau au-dessus des valeurs


class ExportTropGros(Exception):
    """L'export ne tient pas dans une feuille Excel ; le message (dans la langue en cours) propose le CSV ou un seul exercice."""


def _une_ligne_par_valeur(p):
    return p.format == "xlsx" and p.presentation in ("base", "revue", "audit")


def _refuser_trop_gros(n, p):
    if _une_ligne_par_valeur(p) and n + LIGNES_ENTETE_EXCEL > MAX_LIGNES_EXCEL:
        from .templatetags.collecte import entier

        raise ExportTropGros(libelle("suivi.export.erreur.trop_de_lignes", max=entier(MAX_LIGNES_EXCEL)))


def _borne_lignes(utilisateur, p):
    """Nombre de réponses qui seront sûrement exportées (une requête ``count()``, avant de les lire) : borne BASSE des
    lignes (sans les cases « à saisir » ni les sources ajoutées pour les formules), pour ne jamais refuser un export qui
    tiendrait. Elle tient compte des périodes, des niveaux, des organisations cochées, des KPI choisis, des types, des KPI
    collectés par chaque période et des statuts. 0 (pas de contrôle ici) quand une réponse comptée pourrait ne pas être
    exportée sans que SQL le sache : périmètre limité (contributeur, validateur, personne limitée à des organisations),
    KPI calculés exclus, filtre par référentiel ou par thème. Le contrôle sur les lignes réellement collectées reste fait
    après."""
    if not _une_ligne_par_valeur(p) or p.referentiel or p.themes or "calcule" not in p.contenus:
        return 0
    if not (utilisateur.voit_tout and utilisateur.orgs_permises() is None):  # même règle que ``perimetre``
        return 0
    compte = getattr(p, "_reponses_comptees", None)  # déjà compté par ``estimer_cellules`` (même requête) : pas deux fois
    return _reponses_exportees(p).count() if compte is None else compte


def _reponses_exportees(p):
    """Réponses que les réglages ``p`` retiennent, en une requête (sans le périmètre de la personne) : périodes, KPI
    collectés par chaque période, statuts, types, niveaux, organisations cochées, KPI choisis."""
    from django.db.models import Q

    par_periode = {}
    for c in p.campagnes():
        par_periode.setdefault(c.periode_id, []).append(c)
    periodes = Q(pk__in=[])
    for periode_id, campagnes in par_periode.items():
        dans = set()  # comme ``collecter`` : KPI des référentiels collectés sur la période ; None : tous
        for x in campagnes:
            codes = S.codes_campagne(x)
            dans = None if codes is None or dans is None else dans | codes[1]
        periodes |= Q(periode_id=periode_id) if dans is None else Q(periode_id=periode_id, kpi_id__in=sorted(dans))
    # une réponse calculée est exportée quel que soit son statut (« calcule » coché) ; une autre si son statut est coché
    qs = Reponse.objects.filter(periodes, statut__in=list(p.contenus), kpi__type_saisie__comportement__in=list(p.types))
    if set(p.niveaux) != set(N.codes()):
        qs = qs.filter(organisation__niveau_id__in=list(p.niveaux))
    if p.organisations:
        qs = qs.filter(organisation_id__in=sorted(set(p.organisations)))
    codes = p.codes_kpi()
    if codes is not None:
        qs = qs.filter(kpi_id__in=sorted(codes))
    return qs


def _entetes_audit(p):
    from . import export_audit as EA

    return EA.entetes(p)


def estimer_cellules(utilisateur, p):
    """Nombre de cellules (lignes × colonnes) du fichier, estimé par une requête ``count()`` avant de lire les réponses :
    il décide si l'export se fabrique en arrière-plan (``exports_arriere_plan``). Borne HAUTE des lignes pour qui voit
    tout (sans les cases « à saisir » sans réponse) ; pour un périmètre limité, les réponses de ses organisations
    seulement (cases et résultats, comme ``perimetre``)."""
    if p.presentation == "audit":
        from . import export_audit as EA

        EA.exiger(utilisateur)  # pas de tâche en arrière-plan pour un rôle qui n'y a pas droit
    qs = _reponses_exportees(p)
    tout = utilisateur.voit_tout and utilisateur.orgs_permises() is None
    if not tout:
        paires, resultats = perimetre(utilisateur, S.arbre_organisations())
        qs = qs.filter(organisation_id__in=sorted({o for _, o in paires} | set(resultats or ())))
    lignes = qs.count()
    if tout:
        p._reponses_comptees = lignes  # la borne de la limite d'Excel (``_borne_lignes``) est ce même compte
    if "a_saisir" in p.contenus:  # cases encore sans réponse : au plus les cases de la personne (sans lire les réponses)
        lignes += sum(len(S.cellules(utilisateur, campagne=c)) for c in p.campagnes())
    choisie = p.langue  # rendue telle quelle : ``exporter`` la résout de nouveau
    try:
        with L.session():
            p.langue = langue_export(choisie)
            with L.activer(p.langue):
                colonnes = len(entetes_revue(p)) if p.presentation == "revue" else len(entetes_base(p)) \
                    if p.presentation == "base" else len(_entetes_audit(p)) if p.presentation == "audit" \
                    else 2 if p.n1 else 1  # tableau lisible : une case par valeur
    finally:
        p.langue = choisie
        p.__dict__.pop("_memo", None)
    return lignes * colonnes


def refuser_si_trop_gros(utilisateur, p):
    """Avant de mettre un export en arrière-plan : refus tout de suite (``ExportTropGros``) s'il ne tient sûrement pas
    dans une feuille Excel (mêmes règles que le téléchargement immédiat)."""
    _refuser_trop_gros(_borne_lignes(utilisateur, p), p)


def _exporter(utilisateur, p):
    _refuser_trop_gros(_borne_lignes(utilisateur, p), p)
    lignes = collecter(utilisateur, p)
    _refuser_trop_gros(len(lignes), p)
    nom = nom_fichier(p)
    if p.format == "csv":
        return X.reponse_csv(contenu_tabulaire(lignes, p, utilisateur=utilisateur), nom, p.csv)
    from . import export_audit as EA

    fabrique = {"base": classeur_base, "tableau": classeur_tableau, "revue": classeur_revue, "audit": EA.classeur}[p.presentation]
    return X.reponse_excel(fabrique(lignes, p, utilisateur), nom)


# Noms publics des aides que le dossier d'audit (``export_audit``) réemploie : un module n'utilise pas les noms privés d'un autre
memo, ecart, onglet_flux, texte_fichier, a_lire, valeur_lisible = _memo, _ecart, _onglet_flux, _t_fichier, _a_lire, _valeur_lisible
