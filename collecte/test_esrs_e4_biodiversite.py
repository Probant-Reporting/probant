"""Modèle « ESRS E4 – Biodiversité et écosystèmes » : contrôle et couverture (dont la ligne de l'E4 AR 9, absente de la liste de
l'EFRAG), KPI de la norme volontaire VS non repris (autre définition), installation avec la VS dans une base neuve, niveaux
(plan, politiques, compensations et indicateurs pour l'entreprise ; site concerné, zones sensibles et activités au site),
décompte des sites concernés, mesure transitoire de toute la norme écrite dans chaque description, exigences d'application
E4 AR 3 et AR 6 ajoutées aux textes communs."""
import datetime

from django.test import SimpleTestCase, TestCase

from referentiel.bibliotheque import controle as C
from referentiel.bibliotheque import socles as S
from referentiel.bibliotheque.definitions import couverture, esrs_e4
from referentiel.models import KPI, ElementReferentiel, Organisation, Referentiel

from . import paquets as P
from .aides_tests.paquets import vider
from .calcul import Calculateur, recalculer
from .models import Campagne, Periode, Reponse


def installer(fichier):
    a = P.analyser(P.fourni(fichier).paquet, source=fichier, fourni=True)
    assert a.erreur == "" and a.compteurs["rejet"] == 0 and a.compteurs["conflit"] == 0, (a.erreur, a.compteurs)
    P.appliquer(None, a)


class ModeleBiodiversiteTests(SimpleTestCase):
    def test_controle_et_couverture(self):
        socle = next(s for s in S.SOCLES if s["code"] == "ESRS_E4")
        r = C.controler(socle, couverture=couverture(esrs_e4), propres=set(esrs_e4.KPIS), regles_propres=set())
        self.assertEqual(r.erreurs, [])
        self.assertEqual((r.chiffres["couverture"]["total"], r.chiffres["couverture"]["taux"]), (13, 100))  # 12 + E4 AR 9
        self.assertEqual((r.chiffres["kpi"], r.chiffres["calcules"], r.chiffres["regles"]), (27, 0, 0))

    def test_la_ligne_de_l_ar9_est_une_exigence_du_reglement_hors_de_la_liste(self):
        _, lignes, _ = C.lire_couverture(couverture(esrs_e4), "ESRS_E4")
        ar9 = next(ligne for ligne in lignes if ligne["reference"] == "E4 · E4-5 §20 (2)")  # E4-5 §20 et AR 9
        self.assertEqual((ar9["status"], ar9["kpi_codes"]), ("covered", "BIO-IMPACT-SOLS BIO-IMPACT-ESPECES"))
        self.assertEqual(len(lignes), 13)  # 12 points de la liste de l'EFRAG + l'AR 9

    def test_kpi_vs_non_repris_car_autre_definition(self):
        codes = {c for c, *_ in C.elements(esrs_e4.SOCLE)}
        self.assertFalse({"BIO-SITES", "BIO-SITE-ZONE", "BIO-SITE-ZONE-NOM"} & codes)

    def test_mesure_transitoire_dans_chaque_description(self):
        for code, d in esrs_e4.KPIS.items():
            with self.subTest(code):
                self.assertIn("§125(a)", d["description"][1])
                self.assertIn("2027", d["description"][0])
                self.assertIn("first two financial years", d["description"][1])

    def test_exigences_d_application_ajoutees_aux_textes_communs(self):
        self.assertIn("E4 AR 3", esrs_e4.KPIS["BIO-POLIT-CONTENU"]["description"][1])
        self.assertIn("deforestation", esrs_e4.KPIS["BIO-POLIT-CONTENU"]["description"][1])
        self.assertIn("E4 AR 6", esrs_e4.KPIS["BIO-ACT-DESC"]["description"][1])
        self.assertNotIn("E4 AR 3", esrs_e4.KPIS["BIO-POLIT-PERIMETRE"]["description"][1])
        with self.assertRaises(KeyError):
            esrs_e4._ajouter([], "BIO-INCONNU", "", "")


class InstallationBiodiversiteTests(TestCase):
    """Base neuve : la VS de base (qui a ses KPI de biodiversité), puis ESRS E4 ; deux sites."""

    @classmethod
    def setUpTestData(cls):
        vider()
        installer("vs_base.json")
        cls.vs = list(KPI.objects.filter(code__startswith="BIO-").order_by("code").values())
        installer("esrs_e4.json")
        cls.g = Organisation.objects.create(nom="Groupe", niveau_id="Group")
        fr = Organisation.objects.create(nom="France", niveau_id="Country", parent=cls.g)
        e = Organisation.objects.create(nom="Entité", niveau_id="Entity", parent=fr)
        cls.a = Organisation.objects.create(nom="Usine A", niveau_id="Site", parent=e)
        cls.b = Organisation.objects.create(nom="Usine B", niveau_id="Site", parent=e)
        cls.p = Periode.objects.create(type="annee", debut=datetime.date(2026, 1, 1), fin=datetime.date(2026, 12, 31),
                                       libelle="2026")
        cls.c = Campagne.objects.create(referentiel=Referentiel.objects.get(code="ESRS_E4"), periode=cls.p, exercice=2026,
                                        statut=Campagne.Statut.OUVERTE)
        for org, texte in ((cls.a, "Oui"), (cls.b, "Non")):
            Reponse.objects.create(periode=cls.p, kpi_id="BIO-SITE-IRO", organisation=org, texte=texte, statut=Reponse.Statut.VALIDE)
        recalculer(cls.c)

    def test_kpi_biodiversite_de_la_vs_intacts_et_non_partages(self):
        apres = list(KPI.objects.filter(code__in=[k["code"] for k in self.vs]).order_by("code").values())
        self.assertEqual(apres, self.vs)
        for code in ("BIO-SITES", "BIO-SITE-ZONE", "BIO-SITE-ZONE-NOM"):
            self.assertFalse(ElementReferentiel.objects.filter(referentiel__code="ESRS_E4", kpi_id=code).exists())
        for code in ("BIO-SITE-ZONE-IMPACT", "BIO-SITE-IRO", "BIO-PLAN"):
            self.assertEqual(set(ElementReferentiel.objects.filter(kpi_id=code).values_list("referentiel__code", flat=True)),
                             {"ESRS_E4"})

    def test_niveaux_choisis_par_l_outil(self):
        for code in ("BIO-PLAN", "BIO-PLAN-TRANSITION", "BIO-POLIT-SITES", "BIO-COMPENSATIONS", "BIO-LIEUX-DESC",
                     "BIO-INDICATEURS", "BIO-IMPACT-SOLS", "BIO-IMPACT-ESPECES", "BIO-ACT-TAB"):
            self.assertEqual(KPI.objects.get(code=code).granularite_id, "Group", code)  # une réponse pour l'entreprise
        for code in ("BIO-SITE-IRO", "BIO-SITE-ZONE-IMPACT", "BIO-SITE-ACTIVITES"):
            self.assertEqual(KPI.objects.get(code=code).granularite_id, "Site", code)  # une réponse par site

    def test_sites_concernes_comptes_au_niveau_superieur(self):
        v = Calculateur(self.c).valeur("BIO-SITE-IRO", self.g.id)
        self.assertEqual((v["Oui"], v["Non"]), (1, 1))

    def test_formats_des_kpi(self):
        from parametres.models import TypeReponse

        formats = {c: TypeReponse.objects.get(code=KPI.objects.get(code=c).type_reponse_id).format
                   for c in ("BIO-PLAN", "BIO-SITE-IRO", "BIO-LIEUX-DESC", "BIO-INDICATEURS", "BIO-CIB-TAB", "BIO-IMPACT-SOLS")}
        F = TypeReponse.Format
        self.assertEqual(formats, {"BIO-PLAN": F.OUI_NON, "BIO-SITE-IRO": F.OUI_NON, "BIO-LIEUX-DESC": F.TEXTE,
                                   "BIO-INDICATEURS": F.TABLEAU, "BIO-CIB-TAB": F.TABLEAU, "BIO-IMPACT-SOLS": F.OUI_NON})
