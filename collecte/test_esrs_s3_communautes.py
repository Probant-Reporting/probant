"""Modèle « ESRS S3 – Communautés affectées » (ESRS révisées, lot E) : contrôle et couverture de l'inventaire, « si et comment »
du dialogue (oui / non + texte, note explicative §63), éléments conditionnels des peuples autochtones (N/A quand aucune
communauté n'est concernée), incidents en texte avec les litiges fonciers (S3 AR 8), une réponse pour l'entreprise,
installation sans conflit à côté de S2 et S4 (aucun KPI en commun)."""
from django.test import SimpleTestCase, TestCase

from parametres.models import TypeReponse
from referentiel.bibliotheque import controle as C
from referentiel.bibliotheque import socles as S
from referentiel.bibliotheque.definitions import couverture, esrs_s2, esrs_s3, esrs_s4
from referentiel.models import KPI, ElementReferentiel, Referentiel

from . import paquets as P
from .aides_tests.paquets import vider

AUTOCHTONES = ("SOC-COMMU-AUTOCHTONES-CLPE", "SOC-COMMU-AUTOCHTONES-CONS", "SOC-COMMU-AUTOCHT-CONS-DESC")


def installer(fichier):
    a = P.analyser(P.fourni(fichier).paquet, source=fichier, fourni=True)
    assert a.erreur == "" and a.compteurs["rejet"] == 0 and a.compteurs["conflit"] == 0, (a.erreur, a.compteurs)
    P.appliquer(None, a)


class ModeleCommunautesTests(SimpleTestCase):
    def test_controle_et_couverture(self):
        socle = next(s for s in S.SOCLES if s["code"] == "ESRS_S3")
        r = C.controler(socle, couverture=couverture(esrs_s3), propres=set(esrs_s3.KPIS), regles_propres=set())
        self.assertEqual(r.erreurs, [])
        self.assertEqual((r.chiffres["couverture"]["total"], r.chiffres["couverture"]["taux"]), (16, 100))

    def test_vingt_sept_kpi_tous_nouveaux_et_places(self):
        placés = {c for c, *_ in C.elements(esrs_s3.SOCLE)}
        self.assertEqual(len(esrs_s3.KPIS), 30)  # + indicateurs propres facultatifs (ESRS 2 AR 42)
        self.assertEqual(placés, set(esrs_s3.KPIS))
        self.assertTrue(all(c.startswith("SOC-COMMU-") for c in esrs_s3.KPIS))
        # indicateurs propres à l'entreprise (ESRS 2 §48, AR 42) : tableau et GDR-M, facultatifs
        for code in ("SOC-COMMU-INDICATEURS", "SOC-COMMU-METHODES", "SOC-COMMU-EVOLUTION"):
            self.assertIn(code, esrs_s3.KPIS)
            self.assertFalse(next(o for c, _, _, o in C.elements(esrs_s3.SOCLE) if c == code))

    def test_dialogue_si_et_comment(self):
        """§11 « whether and how » : un oui / non et un texte (note explicative §63)."""
        self.assertIn("SOC-COMMU-DIALOGUE-DIRECT", esrs_s3.KPIS)
        self.assertIn("SOC-COMMU-DIALOGUE", esrs_s3.KPIS)
        self.assertIn("N/A", esrs_s3.KPIS["SOC-COMMU-DIALOGUE"]["description"][0])

    def test_elements_autochtones_conditionnels(self):
        for code in AUTOCHTONES:
            with self.subTest(code=code):
                fr, en = esrs_s3.KPIS[code]["description"][:2]
                self.assertIn("S3-2 §12", fr)
                self.assertIn("N/A", fr)
                self.assertIn("N/A", en)

    def test_incidents_et_litiges_fonciers(self):
        fr, en = esrs_s3.KPIS["SOC-COMMU-INCIDENTS-DH"]["description"][:2]
        self.assertIn("S3-3 §17", fr)
        self.assertIn("droits fonciers", fr)
        self.assertIn("land rights", en)

    def test_description_en_deux_langues_et_contraction(self):
        for code, d in esrs_s3.KPIS.items():
            with self.subTest(code=code):
                self.assertTrue(d["fr"] and d["en"] and all(d["description"]))
                self.assertNotIn(" à les ", d["description"][0])
                self.assertIn("ESRS 1 §125(a)", d["description"][0])
        self.assertIn("liés aux communautés affectées", esrs_s3.KPIS["SOC-COMMU-ACTIONS"]["description"][0])


class InstallationCommunautesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        vider()
        for fichier in ("esrs_s2.json", "esrs_s3.json", "esrs_s4.json"):
            installer(fichier)

    def test_trois_normes_sociales_sans_kpi_en_commun(self):
        codes = [set(m.KPIS) for m in (esrs_s2, esrs_s3, esrs_s4)]
        self.assertEqual(len(set.union(*codes)), 30 + 30 + 25)
        for code in ("ESRS_S2", "ESRS_S3", "ESRS_S4"):
            r = Referentiel.objects.get(code=code)
            self.assertEqual(set(ElementReferentiel.objects.filter(referentiel=r).values_list("kpi__code", flat=True)),
                             set({"ESRS_S2": esrs_s2, "ESRS_S3": esrs_s3, "ESRS_S4": esrs_s4}[code].KPIS))
        self.assertEqual(KPI.objects.filter(code__startswith="SOC-COMMU-").count(), 30)

    def test_types_partages_sans_doublon(self):
        # les mêmes tableaux et listes sont déclarés dans les trois fichiers : une seule définition chacun
        self.assertEqual(TypeReponse.objects.filter(code="ESRS-TAB-ACTIONS").count(), 1)
        self.assertEqual(TypeReponse.objects.filter(code="ESRS-TAB-CIBLES").count(), 1)

    def test_formats_et_niveau(self):
        for code in ("SOC-COMMU-DIALOGUE-DIRECT", "SOC-COMMU-AUTOCHTONES-CONS", "SOC-COMMU-PLAINTES"):
            with self.subTest(code=code):
                k = KPI.objects.get(code=code)
                self.assertEqual(TypeReponse.objects.get(code=k.type_reponse_id).format, TypeReponse.Format.OUI_NON)
        self.assertEqual(set(KPI.objects.filter(code__startswith="SOC-COMMU-").values_list("granularite_id", flat=True)), {"Group"})
