"""Modèle « ESRS S4 – Consommateurs et utilisateurs finaux » (ESRS révisées, lot E) : contrôle et couverture de l'inventaire,
22 KPI nouveaux (pas de dialogue « si et comment », pas de peuples autochtones, pas de transition bas carbone dans les
actions), une réponse pour l'entreprise, installation dans une base neuve."""
from django.test import SimpleTestCase, TestCase

from parametres.models import TypeReponse
from referentiel.bibliotheque import controle as C
from referentiel.bibliotheque import socles as S
from referentiel.bibliotheque.definitions import couverture, esrs_s4
from referentiel.models import KPI, ElementReferentiel, Referentiel

from . import paquets as P
from .aides_tests.paquets import vider

FICHIER = "esrs_s4.json"


def installer(fichier=FICHIER):
    a = P.analyser(P.fourni(fichier).paquet, source=fichier, fourni=True)
    assert a.erreur == "" and a.compteurs["rejet"] == 0 and a.compteurs["conflit"] == 0, (a.erreur, a.compteurs)
    P.appliquer(None, a)


class ModeleConsommateursTests(SimpleTestCase):
    def test_controle_et_couverture(self):
        socle = next(s for s in S.SOCLES if s["code"] == "ESRS_S4")
        r = C.controler(socle, couverture=couverture(esrs_s4), propres=set(esrs_s4.KPIS), regles_propres=set())
        self.assertEqual(r.erreurs, [])
        self.assertEqual((r.chiffres["couverture"]["total"], r.chiffres["couverture"]["taux"]), (13, 100))

    def test_vingt_deux_kpi_tous_nouveaux_et_places(self):
        placés = {c for c, *_ in C.elements(esrs_s4.SOCLE)}
        self.assertEqual(len(esrs_s4.KPIS), 25)  # + indicateurs propres facultatifs (ESRS 2 AR 42)
        self.assertEqual(placés, set(esrs_s4.KPIS))
        self.assertTrue(all(c.startswith("SOC-CONSO-") for c in esrs_s4.KPIS))
        # indicateurs propres à l'entreprise (ESRS 2 §48, AR 42) : tableau et GDR-M, facultatifs
        for code in ("SOC-CONSO-INDICATEURS", "SOC-CONSO-METHODES", "SOC-CONSO-EVOLUTION"):
            self.assertIn(code, esrs_s4.KPIS)
            self.assertFalse(next(o for c, _, _, o in C.elements(esrs_s4.SOCLE) if c == code))

    def test_textes_propres_a_la_norme(self):
        actions = esrs_s4.KPIS["SOC-CONSO-ACTIONS-IMPACTS"]["description"]
        self.assertIn("marketing", actions[1])  # exemple de tension de S4-3 §15(a)
        self.assertNotIn("bas carbone", actions[0])  # pas d'exigence sur la transition climatique dans S4
        incidents = esrs_s4.KPIS["SOC-CONSO-INCIDENTS-DH"]["description"]
        self.assertIn("S4-3 §16", incidents[0])
        self.assertIn("S4 AR 5", incidents[1])
        for code, d in esrs_s4.KPIS.items():
            with self.subTest(code=code):
                self.assertNotIn(" à les ", d["description"][0])
        self.assertIn("liés aux consommateurs", esrs_s4.KPIS["SOC-CONSO-POLITIQUES"]["description"][0])


class InstallationConsommateursTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        vider()
        installer()

    def test_referentiel_installe(self):
        r = Referentiel.objects.get(code="ESRS_S4")
        self.assertEqual(ElementReferentiel.objects.filter(referentiel=r).count(), 25)

    def test_formats_et_niveau(self):
        for code in ("SOC-CONSO-POLITIQUES", "SOC-CONSO-PLAINTES"):
            k = KPI.objects.get(code=code)
            self.assertEqual(TypeReponse.objects.get(code=k.type_reponse_id).format, TypeReponse.Format.OUI_NON)
        self.assertEqual(KPI.objects.get(code="SOC-CONSO-CIB-TAB").type_reponse_id, "ESRS-TAB-CIBLES")
        self.assertEqual(set(KPI.objects.filter(code__startswith="SOC-CONSO-").values_list("granularite_id", flat=True)), {"Group"})
