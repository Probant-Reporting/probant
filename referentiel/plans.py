"""Plan d'un référentiel : quels KPI, dans quel ordre, sous quels thèmes. Sert à l'affichage (sections des pages),
au tri et aux filtres, aux exports.

Plan d'un seul référentiel : ses éléments, rangés par l'arbre de ses thèmes puis par ordre.
Plan de tous les référentiels actifs : chaque KPI une seule fois, à sa place dans le premier référentiel (par ordre)
qui le contient ; les KPI d'aucun référentiel viennent à la fin (« Hors référentiel »).
"""
import re

from parametres.libelles import libelle

from .models import ElementReferentiel, Referentiel, Theme

HORS = 10 ** 6  # rang des KPI hors du plan


def referentiels_actifs():
    return list(Referentiel.objects.filter(actif=True))


def classe_referentiel(code):
    return "rf-" + re.sub(r"[^A-Za-z0-9_-]", "_", code)


def _regles(r, fond, texte, _pale, trait):
    return [(f".{classe_referentiel(r.code)}", f"background:{fond};color:{texte};--c-ref:{trait}")]


def css(referentiels=None):
    """Pastilles colorées des référentiels (fond et texte lisibles dérivés de la couleur)."""
    from parametres import couleurs as CO

    return CO.css_etiquettes(referentiels if referentiels is not None else Referentiel.objects.all(), _regles,
                             lambda r: (*CO.couleurs_niveau(r.couleur)[:2], None, r.couleur))


def regles_sombres(fond, referentiels=None):
    """Pastilles des référentiels dans l'apparence sombre [(sélecteur, déclarations)]."""
    from parametres import couleurs as CO

    return CO.etiquettes_sombres(referentiels if referentiels is not None else Referentiel.objects.all(), _regles, fond)


class Plan:
    def __init__(self, referentiel=None, tous=None, kpis=None):
        """``referentiel`` : un référentiel (objet ou code), ou None pour tous les référentiels actifs. ``kpis`` : codes
        des seuls KPI à placer (panneau de saisie : la place d'un KPI, sans lire les 800 éléments des référentiels) ;
        None : tous."""
        tous = referentiels_actifs() if tous is None else tous
        if referentiel is not None and not isinstance(referentiel, Referentiel):
            referentiel = Referentiel.objects.filter(pk=referentiel).first()
        self.referentiel = referentiel
        self.referentiels = [referentiel] if referentiel is not None else tous
        self.multiple = len(self.referentiels) > 1
        ids = [r.pk for r in self.referentiels]
        self.themes = {t.id: t for t in Theme.objects.filter(referentiel_id__in=ids)}
        self._chemins = {}
        self._pos, self._elt, self.appartenances = {}, {}, {}
        par_ref = {}
        self.facultatifs = set()  # (référentiel, KPI) des éléments facultatifs
        self._elements = {}  # KPI → ses éléments dans les référentiels du plan
        refs = {r.pk: r for r in [*tous, *self.referentiels]}
        elements = ElementReferentiel.objects.filter(referentiel_id__in=[r.pk for r in tous])
        for e in elements if kpis is None else elements.filter(kpi_id__in=list(kpis)):
            e.referentiel = refs[e.referentiel_id]  # déjà lu : str(e.referentiel) sans requête (exports, titres)
            self.appartenances.setdefault(e.kpi_id, []).append(e.referentiel_id)
            if e.referentiel_id in ids:
                self._elements.setdefault(e.kpi_id, []).append(e)
            if not e.obligatoire:
                self.facultatifs.add((e.referentiel_id, e.kpi_id))
            if e.referentiel_id in ids:
                par_ref.setdefault(e.referentiel_id, []).append(e)
        for i, r in enumerate(self.referentiels):
            for e in sorted(par_ref.get(r.pk, []), key=lambda e: (self.cle_theme(e.theme_id), e.ordre, e.kpi_id)):
                if e.kpi_id not in self._pos:
                    self._pos[e.kpi_id] = (i, self.cle_theme(e.theme_id), e.ordre, e.kpi_id)
                    self._elt[e.kpi_id] = e
        self.codes = set(self._pos)
        self._noms_refs = {r.pk: r for r in tous}

    # -- arbre des thèmes ------------------------------------------------------
    def chemin(self, theme_id):
        """Thèmes du sommet jusqu'au thème donné."""
        if theme_id not in self._chemins:
            chemin, t = [], self.themes.get(theme_id)
            while t is not None:
                chemin.insert(0, t)
                t = self.themes.get(t.parent_id)
            self._chemins[theme_id] = chemin
        return self._chemins[theme_id]

    def cle_theme(self, theme_id):
        return tuple((t.ordre, t.id) for t in self.chemin(theme_id)) if theme_id else ()

    def arbre(self, referentiel):
        """[(thème, profondeur)] d'un référentiel, dans l'ordre de l'arbre."""
        enfants = {}
        for t in self.themes.values():
            if t.referentiel_id == referentiel.pk:
                enfants.setdefault(t.parent_id, []).append(t)
        sortie = []

        def parcourir(parent, prof):
            for t in sorted(enfants.get(parent, []), key=lambda t: (t.ordre, t.id)):
                sortie.append((t, prof))
                parcourir(t.id, prof + 1)
        parcourir(None, 0)
        return sortie

    # -- place des KPI ---------------------------------------------------------
    def contient(self, code):
        return code in self._pos

    def position(self, code, ordre_catalogue=0):
        """Clé de tri d'un KPI : référentiel, chemin des thèmes, ordre de l'élément ; hors plan à la fin."""
        return self._pos.get(code) or (HORS, (), ordre_catalogue, code)

    def element(self, code):
        return self._elt.get(code)

    def titres(self, code):
        """(titre de section, sous-titre) d'un KPI, dans la langue courante : thème du sommet ; thèmes en dessous."""
        e = self._elt.get(code)
        if e is None:
            # catalogue : titre unique quand aucun référentiel n'est actif
            return (libelle("messages.plans.hors_referentiel") if self._pos else libelle("messages.plans.catalogue")), ""
        chemin = self.chemin(e.theme_id)
        titre = chemin[0].tr("nom") if chemin else libelle("messages.plans.sans_theme")
        if self.multiple:
            titre = f"{e.referentiel} · {titre}" if chemin else str(e.referentiel)
        return titre, " › ".join(t.tr("nom") for t in chemin[1:])

    def decrire(self, code):
        """Pour les exports : référentiel, thème du sommet, thèmes en dessous (langue courante)."""
        e = self._elt.get(code)
        if e is None:
            return {"referentiel": "", "theme": "", "sous_theme": ""}
        chemin = self.chemin(e.theme_id)
        return {"referentiel": str(e.referentiel), "theme": chemin[0].tr("nom") if chemin else "",
                "sous_theme": " › ".join(t.tr("nom") for t in chemin[1:])}

    def theme_racine(self, code):
        e = self._elt.get(code)
        chemin = self.chemin(e.theme_id) if e else []
        return chemin[0] if chemin else None

    def places(self, code):
        """[(référentiel, chemin de thèmes, élément)] du KPI dans les référentiels du plan, dans leur ordre."""
        refs = {r.pk: r for r in self.referentiels}
        return [(refs[e.referentiel_id], self.chemin(e.theme_id), e)
                for e in sorted(self._elements.get(code, []), key=lambda e: (refs[e.referentiel_id].ordre, e.referentiel_id))]

    def referentiels_de(self, code):
        """Référentiels actifs qui contiennent le KPI (objets, dans l'ordre)."""
        return [self._noms_refs[c] for c in sorted(self.appartenances.get(code, []), key=lambda c: (self._noms_refs[c].ordre, c))
                if c in self._noms_refs]
