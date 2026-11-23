"""Export vers un format officiel (classeur d'une autorité, par exemple le classeur VS de l'EFRAG).

Les valeurs viennent des réponses enregistrées de l'organisation exportée pour l'exercice choisi : valeur saisie au niveau
le plus haut, ou résultat de l'agrégation et des calculs (enregistrés comme réponses). La liste des sites et leurs
réponses propres (adresse, pays, zone sensible, effectif) viennent des organisations du niveau le plus bas sous
l'organisation exportée, ouvertes pendant l'exercice. Le format (referentiel/bibliotheque/formats/) dit quelle valeur va
dans quelle cellule ; collecte.classeur_officiel remplit le classeur sans rien en perdre.
"""
import datetime
import functools
import uuid
from dataclasses import dataclass, field

from django.db.models import Q

from parametres import monnaies as MO
from parametres import niveaux as N
from parametres.libelles import libelle
from parametres.models import TypeReponse
from referentiel.bibliotheque import formats as FO
from referentiel.bibliotheque.socles import ESPACE
from referentiel.models import KPI, Organisation, Referentiel

from . import classeur_officiel as K
from .calcul import arbre_commun, arbre_ouverture, ouverte
from .markdown import texte_lisible
from .models import Journal, Periode, Reponse


def identifiant_modele(code):
    """Identifiant stable d'un modèle de la bibliothèque (le même que dans son paquet)."""
    return uuid.uuid5(ESPACE, code)


def referentiels_du_format(fmt):
    """Référentiels de l'installation issus des modèles que le format exporte (reconnus par leur identifiant)."""
    return Referentiel.objects.filter(identifiant__in=[identifiant_modele(c) for c in fmt.REFERENTIELS])


def formats_disponibles():
    """Formats dont au moins un modèle est installé."""
    return [f for f in FO.formats().values() if referentiels_du_format(f).exists()]


@dataclass
class Valeur:
    nombre: object = None
    texte: str = ""
    statut: str = ""


class Lecteur:
    """Réponses d'organisations pour une période, chargées en une requête."""

    def __init__(self, periode, organisations, codes):
        self.par_org = {}
        if periode is None:
            return
        for r in Reponse.objects.filter(periode=periode, organisation__in=organisations, kpi_id__in=codes, non_applicable=False):
            self.par_org.setdefault(r.organisation_id, {})[r.kpi_id] = Valeur(r.valeur, r.texte or "", r.statut)

    def de(self, org_id):
        return self.par_org.get(org_id, {})


class _Lectures:
    """Lecture typée des valeurs d'une organisation (nombre, oui / non, texte, rang dans une liste de choix)."""

    def __init__(self, valeurs, kpis, contexte):
        self._v, self._kpis, self._c = valeurs, kpis, contexte

    def nombre(self, code):
        v = self._v.get(code)
        return v.nombre if v is not None else None

    def oui(self, code):
        v = self._v.get(code)
        if v is None or not v.texte:
            return None
        if v.texte in (TypeReponse.OUI, TypeReponse.NON):
            return v.texte == TypeReponse.OUI
        self._c.message("suivi.officiel.msg.oui_non", kpi=code, valeur=v.texte[:40])
        return None

    def texte(self, code):
        v = self._v.get(code)
        return texte_lisible(v.texte) or None if v is not None and v.texte else None

    def choix(self, code):
        v, k = self._v.get(code), self._kpis.get(code)
        if v is None or not v.texte or k is None:
            return None
        valeurs = list(k.type_reponse.valeurs or [])
        if v.texte in valeurs:
            return valeurs.index(v.texte)
        self._c.message("suivi.officiel.msg.liste", kpi=code, valeur=v.texte[:40])
        return None


class Site(_Lectures):
    """Un site de la liste B1 : son numéro (ID dans le classeur), son organisation, ses réponses."""

    def __init__(self, numero, organisation, valeurs, kpis, contexte):
        _Lectures.__init__(self, valeurs, kpis, contexte)
        self.numero, self.organisation = numero, organisation


class Contexte(_Lectures):
    """Ce que voit un format : valeurs de l'organisation exportée, exercice précédent, sites, réglages de l'export."""

    def __init__(self, fmt, organisation, periode, langue="fr"):
        self.fmt, self.organisation, self.periode, self.langue, self.messages = fmt, organisation, periode, langue, []
        refs = referentiels_du_format(fmt)
        self.option_b = refs.filter(identifiant=identifiant_modele("VS_COMPLET"), actif=True).exists()
        codes = sorted({k for cel in fmt.CELLULES for k in cel.codes} | {k for b in fmt.BLOCS for k in b.codes})
        self.kpis = {k.code: k for k in KPI.objects.filter(code__in=codes).select_related("type_reponse", "unite")}
        self.monnaie = MO.reference()  # devise du rapport : la monnaie de référence de l'espace
        lecteur = Lecteur(periode, [organisation], self.kpis)
        _Lectures.__init__(self, lecteur.de(organisation.pk), self.kpis, self)
        self.precedente = Periode.objects.filter(type=periode.type, fin__lt=periode.debut).order_by("-debut").first()
        self._avant = Lecteur(self.precedente, [organisation], self.kpis).de(organisation.pk)
        self.sites = self._sites()
        self._tableaux = {}

    @property
    def debut(self):
        return self.periode.debut

    @property
    def fin(self):
        return self.periode.fin

    @property
    def nom_entreprise(self):
        return self.organisation.nom

    def connait(self, codes):
        """Vrai si l'installation a ces KPI (un KPI du module complet absent n'est pas « manquant »)."""
        return any(c in self.kpis for c in codes)

    def unite_hors_monnaie(self, code, unite_modele):
        """Symbole de l'unité du KPI de montant ``code`` quand elle n'est pas l'unité du modèle (``unite_modele``, en
        euros) écrite dans la devise du rapport (« k€ », « € » dans un rapport en dollars) ; ``None`` si elle l'est, ou si
        l'installation n'a pas ce KPI. Le format n'écrit alors pas la valeur : aucune conversion."""
        k = self.kpis.get(code)
        if k is None:
            return None
        symbole = k.unite.symbole if k.unite else ""
        return None if MO.dans_la_monnaie(symbole, unite_modele, self.monnaie) else (symbole or "—")

    def precedent(self, code):
        v = self._avant.get(code)
        return v.nombre if v is not None else None

    def message(self, cle, **valeurs):
        """Remarque pour le rapport : clé d'un texte des fichiers de langue (libelles/suivi.*.json) et ses valeurs."""
        m = (cle, tuple(sorted(valeurs.items())))
        if m not in self.messages:
            self.messages.append(m)

    @functools.cached_property
    def statuts(self):
        """Statut des réponses de l'organisation exportée lues par le format (brouillon, validé, calculé…)."""
        return {code: v.statut for code, v in self._v.items()}

    def _sites(self):
        niveaux = sorted(N.tous(), key=lambda n: n.rang)
        if not niveaux:
            return []
        bas = niveaux[-1].code
        if self.organisation.niveau_id == bas:
            orgs = [self.organisation]
        else:
            arbre = arbre_ouverture(self.periode, arbre_commun(self.periode, list(self.kpis)))  # KPI figés : le leur
            orgs = [o for o in descendants(self.organisation, arbre)
                    if arbre[o.pk].niveau_id == bas and ouverte(arbre[o.pk], self.periode, arbre)]
        lecteur = Lecteur(self.periode, orgs, self.kpis)
        return [Site(i + 1, o, lecteur.de(o.pk), self.kpis, self) for i, o in enumerate(orgs)]

    def liste_officielle(self, nom):
        return liste_officielle(self.fmt.CODE, nom)

    def tableau(self, code):
        """Lignes d'une réponse en tableau, rassemblées sur l'organisation exportée et toutes celles en dessous ouvertes
        pendant l'exercice (lignes de même clé additionnées) ; une valeur de liste est remplacée par son rang dans la liste
        (le format le traduit dans les termes du classeur)."""
        from parametres.models import TypeReponse

        from . import tableaux as T

        k = self.kpis.get(code)
        if k is None or not k.est_tableau:
            return []
        if code not in self._tableaux:
            arbre = arbre_ouverture(self.periode, code)  # arbre que suit le KPI (figé par une campagne clôturée : le sien)
            orgs = [self.organisation] + [o for o in descendants(self.organisation, arbre)
                                          if ouverte(arbre[o.pk], self.periode, arbre)]
            lecteur = Lecteur(self.periode, orgs, [code])
            listes_de_lignes = [T.lignes(lecteur.de(o.pk)[code].texte, k.type_reponse) for o in orgs if code in lecteur.de(o.pk)]
            lignes = T.fusionner(listes_de_lignes, k.type_reponse)
            cols = T.colonnes(k.type_reponse)
            valeurs = {t.code: list(t.valeurs or []) for t in TypeReponse.objects.filter(code__in={c.liste for c in cols if c.liste})}
            for ligne in lignes:
                for col in cols:
                    v = ligne.get(col.code)
                    if col.type == "liste" and v is not None:
                        ligne[col.code] = valeurs.get(col.liste, []).index(v) if v in valeurs.get(col.liste, []) else None
            self._tableaux[code] = lignes
        return self._tableaux[code]


def descendants(org, arbre=None):
    """Organisations sous ``org`` (tous niveaux), dans l'ordre d'affichage. ``arbre`` : {identifiant: organisation} de
    la période (``calcul.arbre_ouverture(periode)`` : celui de sa clôture pour un exercice clos ou rouvert en gardant les
    chiffres de l'époque) ; les parents sont lus dedans, une organisation qui n'y est pas est laissée de côté."""
    toutes = list(Organisation.objects.order_by("rang", "nom"))
    enfants = {}
    for o in toutes:
        if arbre is None:
            enfants.setdefault(o.parent_id, []).append(o)
        elif o.pk in arbre:
            enfants.setdefault(arbre[o.pk].parent_id, []).append(o)
    sortie, pile = [], list(reversed(enfants.get(org.pk, [])))
    while pile:
        o = pile.pop()
        sortie.append(o)
        pile.extend(reversed(enfants.get(o.pk, [])))
    return sortie


def chemin_modele(fmt):
    return FO.DOSSIER / fmt.FICHIER


@functools.lru_cache(maxsize=8)
def liste_officielle(code_format, nom):
    """Valeurs d'une liste du classeur officiel (plage nommée), lues une fois par processus."""
    from openpyxl import load_workbook

    fmt = FO.format_de(code_format)
    wb = load_workbook(chemin_modele(fmt), read_only=True, data_only=True)
    try:
        defn = wb.defined_names[nom]
        onglet, plage = next(iter(defn.destinations))
        return tuple(str(c.value) for ligne in wb[onglet][plage.replace("$", "")] for c in ligne if c.value not in (None, ""))
    finally:
        wb.close()


@dataclass
class Rapport:
    remplies: int = 0
    manquantes: list = field(default_factory=list)  # [(module, [noms des KPI])]
    non_validees: list = field(default_factory=list)  # [codes des KPI lus dont la réponse n'est pas validée ou calculée]
    messages: list = field(default_factory=list)
    option_b: bool = False


STATUTS_FINALISES = (Reponse.Statut.VALIDE, Reponse.Statut.CALCULE)


def ordre_module(module):
    """Ordre de la norme : informations sur le rapport, B1 à B11, puis C1 à C9."""
    if module == "Rapport":
        return (0, 0)
    return ({"B": 1, "C": 2}.get(module[:1], 3), int(module[1:]) if module[1:].isdigit() else 0)


def exporter(code_format, organisation, periode, langue="fr", utilisateur=None):
    """(octets du classeur rempli, Rapport) pour l'organisation et l'exercice donnés."""
    fmt = FO.format_de(code_format)
    c = Contexte(fmt, organisation, periode, langue)
    resultat = fmt.construire(c)
    donnees = K.remplir(chemin_modele(fmt), resultat.ecritures, resultat.formules)
    lus = {k for _, _, _, codes in resultat.remplies for k in codes}
    noms = {k: c.kpis[k].tr("libelle") if k in c.kpis else k for k in {x for _, codes in resultat.manquantes for x in codes} | lus}
    par_module = {}
    for module, codes in resultat.manquantes:  # une ligne par rubrique de la norme
        liste = par_module.setdefault(module, [])
        liste.extend(noms[k] for k in codes if noms[k] not in liste)
    rapport = Rapport(
        remplies=len(resultat.ecritures), option_b=c.option_b,
        messages=[libelle(cle, **dict(valeurs)) for cle, valeurs in resultat.messages],
        manquantes=[(libelle("suivi.officiel.module_rapport") if m == "Rapport" else m, noms_m)
                    for m, noms_m in sorted(par_module.items(), key=lambda x: ordre_module(x[0]))],
        non_validees=sorted(noms[k] for k in lus if c.statuts.get(k) and c.statuts[k] not in STATUTS_FINALISES))
    if utilisateur is not None:
        Journal.ecrire(utilisateur, "export_officiel", organisation, fmt.CODE, "",
                       f"{periode} : {rapport.remplies} cellules, {len(rapport.manquantes)} valeurs attendues absentes")
    return donnees, rapport


def nom_fichier(fmt, organisation, periode):
    from django.utils.text import slugify

    return f"{fmt.CODE}_{slugify(organisation.nom)[:40] or 'organisation'}_{periode.libelle}_{datetime.date.today():%Y%m%d}.xlsx"


def periodes_exportables(fmt):
    """Exercices (périodes annuelles) d'une campagne d'un référentiel du format, du plus récent au plus ancien."""
    refs = referentiels_du_format(fmt)
    return list(Periode.objects.filter(Q(campagnes__referentiel__in=refs), type=Periode.Type.ANNEE).distinct().order_by("-debut"))


def organisations_exportables():
    """Organisations du niveau le plus haut (racines), proposées pour l'export."""
    return list(Organisation.objects.filter(parent__isnull=True).order_by("rang", "nom"))
