"""Visualisation à gros volume : ``Source.point`` lit les réponses enregistrées en tuples, et
seulement quand elles changent le point, le calculateur lit les réponses d'une période figée KPI par KPI ; il donne
exactement les points de l'ancienne construction (réponses lues en objets complets, toujours ; toute la période d'un
coup), sur des données tirées au hasard (graine fixe), pour chaque rôle, avec et sans brouillons. La vue de départ
arrête sa recherche plus tôt : mêmes visuels."""
import types
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase

from referentiel.models import Utilisateur

from . import calcul as C
from . import visualisation as V
from .aides_tests.donnees_tirees import Donnees
from .models import Reponse


class SourceAvant(V.Source):
    """``officielles``, ``point`` et réponses enregistrées du calculateur d'avant le lot B2 (copie du commit 539519f)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.calc.enregistrees = types.MethodType(C.Calculateur.enregistrees, self.calc)  # toute la période d'un coup

    def officielles(self, periode):
        if periode.pk not in self._officielles:
            qs = Reponse.objects.filter(periode=periode)
            if self.codes is not None:
                qs = qs.filter(kpi_id__in=self.codes)
            self._officielles[periode.pk] = {(r.kpi_id, r.organisation_id): r for r in qs}
        return self._officielles[periode.pk]

    def point(self, code, org, periode):
        # seul ajout à la copie : la règle de ``calcul.ouverte`` (arbre gardé à chaque clôture :
        # la Visualisation ne montre pas de point pour une organisation pas ouverte pendant la période), sans rapport
        # avec la lecture des réponses que ce test compare
        if periode is None or org is None or not self.voit(code, org.id) or not self.present(org.id, periode):
            return None
        kpi = self.kpis[code]
        valide = self.calc.valeur(code, org.id, periode)
        officielle = V.valeur_officielle(self.officielles(periode).get((code, org.id)), kpi)
        if not self.brouillons:
            return V.Point(valide) if valide is not None else V.Point(en_attente=officielle is not None)
        if officielle is None:
            return V.Point(valide)
        return V.Point(officielle, provisoire=not V._egales(valide, officielle, kpi))


class EquivalencePoints(Donnees):
    def points(self, classe, utilisateur, brouillons, codes):
        source = classe(Utilisateur.objects.get(pk=utilisateur.pk), codes, brouillons=brouillons)
        periodes = [c.periode for c in self.anciennes] + [self.c.periode]
        return [(k, o.pk, p.pk, source.point(k, o, p)) for p in periodes for k in sorted(source.kpis) for o in self.orgs]

    def test_memes_points_pour_chaque_role(self):
        # brouillons et réponses à valider dans l'exercice ouvert et dans le dernier exercice clos
        for p in (self.c.periode, self.anciennes[-1].periode):
            for r in Reponse.objects.filter(periode=p):
                if self.h.random() < 0.3:
                    Reponse.objects.filter(pk=r.pk).update(statut=self.h.choice([Reponse.Statut.BROUILLON, Reponse.Statut.A_SAISIR]))
        vus = set()
        cas = [(u, b, c, m) for u in (self.admin, self.contrib, self.valid, self.lect) for b in (False, True)
               for c in (None, ["CAL"]) for m in (20, 2)]  # m = 2 : au-delà de 2 KPI, le reste de la période lu d'un coup
        for u, brouillons, codes, par_kpi in cas:
            with self.subTest(utilisateur=u.username, brouillons=brouillons, codes=codes, par_kpi=par_kpi), \
                    mock.patch.object(V.EnregistreesParKpi, "PAR_KPI_MAX", par_kpi):
                avant = self.points(SourceAvant, u, brouillons, codes)
                self.assertEqual(avant, self.points(V.Source, u, brouillons, codes))
                vus |= {("valeur" if p.valeur is not None else "attente" if p.en_attente else "vide", p.provisoire)
                        for *_, p in avant if p is not None}
        # le tirage produit des points de toutes les sortes
        self.assertTrue({("valeur", False), ("valeur", True), ("attente", False), ("vide", False)} <= vus, vus)

    def test_memes_reponses_enregistrees(self):
        """Réponses lues KPI par KPI (puis le reste d'un coup) : les mêmes que celles du moteur, case par case."""
        for p in [c.periode for c in self.anciennes] + [self.c.periode]:
            moteur = C.Calculateur(p).enregistrees(p)
            cles = set(moteur) | {(k.code, o.pk) for k in self.kpis for o in self.orgs} | {("ABSENT", self.orgs[0].pk)}
            for maximum in (20, 2, 0):
                with self.subTest(periode=str(p), maximum=maximum), mock.patch.object(V.EnregistreesParKpi, "PAR_KPI_MAX", maximum):
                    lues = V.CalculateurValide().enregistrees(p)
                    self.assertEqual({c: moteur.get(c) for c in cles}, {c: lues.get(c) for c in sorted(cles, key=str)})


def vue_de_depart_avant(utilisateur, campagne):
    """``vues_visu.vue_de_depart`` d'avant le lot B2 (copie du commit 539519f) : les 60 premiers KPI tous calculés."""
    from referentiel.models import KPI, Referentiel, Theme
    from referentiel.plans import Plan

    from . import visuels as VS

    ref = campagne.referentiel if campagne else Referentiel.objects.filter(actif=True).order_by("ordre", "code").first()
    visuels = []
    if ref is not None:
        plan = Plan(ref)
        codes = VS.codes_du_plan(plan)
        visibles = VS.codes_visibles(utilisateur)
        kpis = {k.code: k for k in KPI.objects.filter(code__in=[c for c in codes if c in visibles])}
        numeriques = [c for c in codes if c in kpis and kpis[c].est_numerique]
        source = V.Source(utilisateur, numeriques[:60])
        periode = V.periode_par_defaut(V.periodes(source.calendrier, ref) or V.periodes(source.calendrier))
        racines = source.racines()
        avec_valeur = [c for c in numeriques[:60] if periode and any(
            (p := source.point(c, o, periode)) is not None and p.valeur is not None for o in racines)]
        for c in avec_valeur[:4]:
            visuels.append({"id": f"d{len(visuels) + 1}", "type": "chiffre", "kpis": [c], "largeur": 3})
        visuels.append({"id": "d5", "type": "remplissage", "kpis": [], "largeur": 6})
        additionnable = next((c for c in avec_valeur if VS.additionnable(kpis[c]) and racines and any(
            source.organisations_comparees(c, racines[0]))), None)
        if additionnable:
            visuels.append({"id": "d6", "type": "organisations", "kpis": [additionnable], "largeur": 6})
        theme = Theme.objects.filter(referentiel=ref, parent=None).order_by("ordre", "id").first()
        if theme is not None:
            visuels.append({"id": "d7", "type": "tableau", "kpis": [], "source": f"theme:{theme.pk}", "largeur": 12})
    propre, _ = VS.valider_vue({"nom": VS.lib("visu.vue.depart"), "visuels": visuels}, utilisateur)
    return {"nom": VS.lib("visu.vue.depart"), "genre": "depart", "description": VS.lib("visu.vue.depart_aide"),
            "filtres": {}, "visuels": propre.get("visuels", [])}


class VueDeDepartIdentique(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("load_demo", "--language", "fr", stdout=StringIO())  # Exemplia : exercice 2026 ouvert

    def test_memes_visuels_pour_chaque_role(self):
        from parametres import langues as L

        from . import saisie as S
        from . import vues_visu as VV

        from . import visuels as VS

        vus = set()
        additionnable = VS.additionnable
        # tel quel, puis seulement les derniers KPI additionnables (le premier additionnable vient après les 4 chiffres)
        tardifs = lambda k: additionnable(k) and k.code > "M"  # noqa: E731
        for nom in ("admin", "validateur", "contributeur", "lecteur", "auditeur"):
            u = Utilisateur.objects.get(username=nom)
            for campagne in (S.campagne_par_defaut(u), None):
                for regle in (additionnable, tardifs):
                    with self.subTest(utilisateur=nom, campagne=campagne, tardifs=regle is tardifs), L.session(), \
                            mock.patch.object(VS, "additionnable", regle):
                        avant = vue_de_depart_avant(u, campagne)
                        self.assertEqual(avant, VV.vue_de_depart(u, campagne))
                        vus |= {v["type"] for v in avant["visuels"]}
        self.assertTrue({"chiffre", "organisations"} <= vus, vus)
