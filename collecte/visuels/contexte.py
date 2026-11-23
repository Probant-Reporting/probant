"""Visualisation v2 : ``Contexte``, les filtres résolus d'une vue et d'un visuel."""
import copy

from referentiel.models import Referentiel, Theme
from referentiel.plans import Plan

from .. import visualisation as V
from ..models import Campagne

from .formes import FILTRES_DEFAUT, MAX_PERIODES, MIN_PERIODES, MOIS, lib
from .filtres import filtres_depuis_adresse, nettoyer_filtres
from .perimetre import Perimetre, filtres_publics


class Contexte:
    """Filtres résolus d'une vue pour une personne. ``preparer(codes)`` crée la ``Source`` (une seule pour la vue)."""

    def __init__(self, utilisateur, filtres=None, parametres=None, campagne_choisie=None):
        self.utilisateur = utilisateur
        self.campagne_choisie = campagne_choisie
        self.filtres_vue = {**FILTRES_DEFAUT, **nettoyer_filtres(filtres or {})}
        self.temporaires = filtres_depuis_adresse(parametres)
        self.f = {**self.filtres_vue, **self.temporaires}
        self.avertissements = []
        self._plan = None
        self._campagnes = {}
        self._comptes = {}
        # référentiel (KPI proposés, thèmes, périodes, campagne du taux de remplissage)
        r = self.f["referentiel"]
        if r == "je_reponds_a":
            self.referentiel = campagne_choisie.referentiel if campagne_choisie and campagne_choisie.referentiel.actif else None
        elif r == "tous":
            self.referentiel = None
        else:
            self.referentiel = Referentiel.objects.filter(pk=r, actif=True).first()
        ids = [i for i in self.f.get("themes") or [] if isinstance(i, int)]
        qs = Theme.objects.filter(pk__in=ids, referentiel__actif=True)
        if self.referentiel is not None:
            qs = qs.filter(referentiel=self.referentiel)
        self.themes = list(qs)
        self.brouillons = self.f["valeurs"] == "brouillons"
        self.source = None

    # -- après lecture des KPI de la vue --------------------------------------------------------------------
    def preparer(self, codes):
        self.codes = set(codes)
        self.source = V.Source(self.utilisateur, self.codes, brouillons=self.brouillons)
        self._sources = {self.brouillons: self.source}
        self.calendrier = self.source.calendrier
        self.toutes_periodes = V.periodes(self.calendrier)
        self.periodes = (V.periodes(self.calendrier, self.referentiel) if self.referentiel else None) or self.toutes_periodes
        self.periode_auto = V.periode_par_defaut(self.periodes)
        self.periode = self._periode(self.f["periode"])
        self._periode_vue = self.periode
        self.comparaison = self.f["comparaison"]
        self.prec = self._prec(self.periode, self.comparaison)
        self.organisations = self.source.organisations()
        self.perim = Perimetre(self.utilisateur, self.source)  # rien de hors périmètre vers la page
        self.racines = self.source.racines()
        # la page envoie toujours l'organisation affichée : pour une vue qui suit le périmètre de chacun (organisation non
        # fixée), choisir celle qu'elle montre déjà n'est pas un changement (ni « différent », ni fixé en enregistrant)
        if "org" in self.temporaires and self.filtres_vue.get("org") is None \
                and self._org(self.temporaires["org"], signaler=False) == self._org(None, signaler=False):
            del self.temporaires["org"]
            self.f["org"] = None
        self.org, self.tout = self._org(self.f["org"])
        self.nb_periodes = None
        self.orgs_comparees = {"mode": "dessous"}
        self.fixes = []
        return self

    def _periode(self, demande, signaler=True):
        if demande == "je_reponds_a" and self.campagne_choisie is not None:
            p = next((p for p in self.toutes_periodes if p.pk == self.campagne_choisie.periode_id), None)
            if p is not None:
                return p
        if isinstance(demande, int):
            p = next((p for p in self.toutes_periodes if p.pk == demande), None)
            if p is not None:
                return p
            if signaler and self.periode_auto is not None:
                self.avertissements.append(lib("visu.filtres.periode_ignoree", periode=str(self.periode_auto)))
        return self.periode_auto

    def _prec(self, periode, comparaison):
        if periode is None or comparaison == "aucune":
            return None
        return self.calendrier.precedente(periode) if comparaison == "p1" else self.calendrier.meme_n1(periode)

    def _org(self, demande, signaler=True):
        """(organisation, tout le périmètre) ; « tout » n'a de sens qu'avec plusieurs sommets."""
        if isinstance(demande, int):
            o = next((o for o in self.organisations if o.id == demande), None)
            if o is not None:
                return o, False
        defaut = (self.racines[0], False) if len(self.racines) == 1 else (None, bool(self.racines))
        if isinstance(demande, int) and signaler and self.racines:
            self.avertissements.append(lib("visu.filtres.org_ignoree", org=defaut[0].nom if defaut[0] else lib("visu.filtres.tout_perimetre")))
        return defaut

    @property
    def plan(self):
        if self._plan is None:
            self._plan = Plan(self.referentiel)
        return self._plan

    @property
    def campagne(self):
        """Campagne du taux de remplissage : celle du référentiel et de la période, sinon « Je réponds à »."""
        cle = self.periode.pk if self.periode else None
        if cle not in self._campagnes:  # dictionnaire partagé avec les filtres propres des visuels (une requête par période)
            ref = self.referentiel or (self.campagne_choisie.referentiel if self.campagne_choisie else None)
            c = None
            if ref is not None and self.periode is not None:
                c = Campagne.objects.select_related("referentiel", "periode").filter(referentiel=ref, periode=self.periode).first()
            if c is None and self.campagne_choisie is None and self.periode is not None:  # hors requête : premier référentiel
                c = (Campagne.objects.select_related("referentiel", "periode").filter(periode=self.periode, referentiel__actif=True)
                     .order_by("referentiel__ordre", "referentiel_id").first())
            self._campagnes[cle] = c or self.campagne_choisie
        return self._campagnes[cle]

    def source_pour(self, brouillons):
        if brouillons not in self._sources:
            self._sources[brouillons] = V.Source(self.utilisateur, self.codes, brouillons=brouillons)
        return self._sources[brouillons]

    # -- filtres propres d'un visuel -------------------------------------------------------------------------
    def pour_visuel(self, v):
        c = copy.copy(self)
        c.fixes = []
        f = v.get("filtres") or {}
        if "periode" in f:
            c.periode = self._periode(f["periode"])
            if c.periode is not None:
                c.fixes.append(str(c.periode))
        if "comparaison" in f or "periode" in f:
            c.comparaison = f.get("comparaison", self.comparaison)
            c.prec = self._prec(c.periode, c.comparaison)
            if "comparaison" in f:
                c.fixes.append(lib("visu.filtres.comparer") + " : " + (str(c.prec) if c.prec else lib("visu.filtres.aucune")))
        if "org" in f:
            c.org, c.tout = self._org(f["org"])
            c.fixes.append(c.org.nom if c.org else lib("visu.filtres.tout_perimetre"))
        if "valeurs" in f:
            b = f["valeurs"] == "brouillons"
            c.brouillons, c.source = b, self.source_pour(b)
            c.fixes.append(lib("visu.filtres.brouillons" if b else "visu.filtres.validees"))
        if "nb_periodes" in f:
            c.nb_periodes = f["nb_periodes"]
            c.fixes.append(lib("visu.filtres.nb_periodes") + f" : {c.nb_periodes}")
        oc = f.get("orgs_comparees")
        if oc:
            c.orgs_comparees = oc
            if oc.get("mode") == "niveau":
                from parametres.models import NiveauHierarchique

                n = NiveauHierarchique.objects.filter(pk=oc.get("niveau")).first()
                c.fixes.append(lib("visu.filtres.niveau", niveau=n.tr("nom_pluriel") if n else oc.get("niveau")))
            elif oc.get("mode") == "choisies":
                c.fixes.append(lib("visu.filtres.choisies"))
        return c

    # -- points (comptés pour la phrase d'état) ---------------------------------------------------------------
    def point(self, code, org, periode):
        p = self.source.point(code, org, periode)
        if p is not None and org is not None and periode is not None and periode == self.periode_vue():
            self._comptes[(code, org.id, self.brouillons)] = p
        return p

    def periode_vue(self):
        return self._periode_vue

    def compter(self):
        p = [x for x in self._comptes.values()]
        return sum(1 for x in p if x.en_attente), sum(1 for x in p if x.provisoire)

    def periodes_serie(self, periode=None, nombre=None):
        """Périodes du même type, de la plus ancienne à ``periode`` (celles qui existent)."""
        periode = periode or self.periode
        if periode is None:
            return []
        nombre = max(MIN_PERIODES, min(MAX_PERIODES, nombre or self.nb_periodes or V.NB_EVOLUTION.get(periode.type, 6)))
        pas = MOIS[periode.type]
        sortie = []
        for i in range(nombre - 1, -1, -1):
            q = self.calendrier.decalee(periode, -pas * i) if i else periode
            if q is not None:
                sortie.append(q)
        return sortie

    def org_unique(self):
        """Organisation d'un visuel à une seule valeur ; avec « Tout mon périmètre », le premier sommet (signalé)."""
        if self.org is not None or not self.racines:
            return self.org
        return self.racines[0]

    def visible(self, code):
        """Le KPI se voit quelque part dans le périmètre de la personne."""
        return any(self.source.voit(code, o.id) for o in self.organisations)

    # -- réponse ------------------------------------------------------------------------------------------------
    def chemin(self):
        ids = {o.id for o in self.organisations}
        chemin, o = [], self.org
        while o is not None and o.id in ids:
            chemin.insert(0, {"id": o.id, "nom": o.nom})
            o = o.parent
        return chemin

    def filtres_json(self):
        p = self.periode
        return {
            "periode": {"id": p.pk if p else None, "libelle": str(p) if p else "",
                        "auto": self.f["periode"] == "auto" or not isinstance(self.f["periode"], int),
                        "demande": self.f["periode"]},
            "comparaison": {"mode": self.comparaison, "id": self.prec.pk if self.prec else None,
                            "libelle": str(self.prec) if self.prec else ""},
            "org": {"id": self.org.id if self.org else None, "nom": self.org.nom if self.org else lib("visu.filtres.tout_perimetre"),
                    "tout": self.tout},
            "chemin": self.chemin(),
            "valeurs": "brouillons" if self.brouillons else "validees",
            "referentiel": {"demande": self.f["referentiel"], "code": self.referentiel.code if self.referentiel else "",
                            "nom": str(self.referentiel) if self.referentiel else ""},
            "themes": [t.pk for t in self.themes],
            "brut": filtres_publics(self.f, self.perim),
            "vue": filtres_publics(self.filtres_vue, self.perim),
            "differents": bool(self.temporaires) and any(self.f.get(k) != self.filtres_vue.get(k) for k in self.temporaires),
        }

    def etat_json(self, masques=0):
        nb_attente, nb_provisoires = self.compter()
        if self.brouillons:
            phrase = lib("visu.etat.brouillons")
            if nb_provisoires:
                phrase += " " + lib("visu.etat.provisoires_nb", n=nb_provisoires)
        else:
            phrase = lib("visu.etat.validees")
            if nb_attente and self.periode:
                phrase += " " + lib("visu.etat.attente_nb", n=nb_attente, periode=str(self.periode))
        return {"nb_attente": nb_attente, "nb_provisoires": nb_provisoires, "phrase": phrase, "masques": masques,
                "phrase_masques": lib("visu.vue.masques", n=masques) if masques else "",
                "sans_periode": self.periode is None, "sans_org": not self.organisations}
