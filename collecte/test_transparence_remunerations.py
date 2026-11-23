"""Modèle « Transparence des rémunérations » (directive (UE) 2023/970) : une réponse par employeur (niveau
conseillé « entite »), écart du groupe recalculé sur les totaux et non moyenne des écarts, médianes et quartiles sans
valeur au-dessus de l'entité, rémunérations moyennes sensibles."""
import datetime
from decimal import Decimal

from django.test import TestCase

from parametres.models import NiveauHierarchique
from referentiel.formule import NA
from referentiel.models import KPI, Organisation, Referentiel

from . import paquets as P
from .aides_tests.paquets import vider
from .calcul import Calculateur, recalculer
from .models import Campagne, Periode, Reponse

D = Decimal
FICHIER = "transparence_remunerations.json"


def installer():
    a = P.analyser(P.fourni(FICHIER).paquet, source=FICHIER, fourni=True)
    assert a.erreur == "" and a.compteurs["rejet"] == 0 and a.compteurs["conflit"] == 0, (a.erreur, a.compteurs)
    P.appliquer(None, a)


class NiveauEntiteTests(TestCase):
    """Le niveau conseillé « entite » : le niveau Entité ou Filiale, reconnu par son code ou son nom dans une langue."""

    def niveaux(self, noms):
        vider()
        NiveauHierarchique.objects.all().delete()
        for rang, (code, nom) in enumerate(noms, 1):
            NiveauHierarchique.objects.create(code=code, nom=nom, nom_pluriel=nom, rang=rang)
        installer()
        return KPI.objects.get(code="SOC-REMU-NB-F").granularite_id, KPI.objects.get(code="SOC-ECART-MOY-HOR").granularite_id

    def test_niveaux_de_depart(self):  # Groupe › Pays › Entité › Site
        self.assertEqual(self.niveaux([("Group", "Groupe"), ("Country", "Pays"), ("Entity", "Entité"), ("Site", "Site")]),
                         ("Entity", "Entity"))

    def test_nom_reconnu(self):
        for noms, attendu in (
                ([("G", "Holding"), ("S", "Société"), ("U", "Usine")], "S"),
                ([("G", "Konzern"), ("T", "Tochtergesellschaft"), ("W", "Werk")], "T"),
                ([("H", "Holding"), ("F", "Filiale")], "F")):  # modèle « Holding › Filiale » : la filiale est le plus bas
            with self.subTest(noms=noms):
                self.assertEqual(self.niveaux(noms)[0], attendu)

    def test_sans_nom_reconnu(self):
        """Trois niveaux ou plus : celui juste au-dessus du plus bas ; deux niveaux : le plus haut (l'entreprise)."""
        self.assertEqual(self.niveaux([("A", "Alpha"), ("B", "Bêta"), ("C", "Gamma"), ("E", "Epsilon")])[0], "C")
        self.assertEqual(self.niveaux([("A", "Entreprise"), ("B", "Atelier")])[0], "A")


class EcartDuGroupeTests(TestCase):
    """L'exemple de référence : 10 % et 15 % dans les deux filiales, −4,38 % pour le groupe (pas 12,5 %)."""

    @classmethod
    def setUpTestData(cls):
        vider()
        installer()
        cls.g = Organisation.objects.create(nom="Groupe", niveau_id="Group")
        fr = Organisation.objects.create(nom="France", niveau_id="Country", parent=cls.g)
        cls.a = Organisation.objects.create(nom="Filiale A", niveau_id="Entity", parent=fr)
        cls.b = Organisation.objects.create(nom="Filiale B", niveau_id="Entity", parent=fr)
        Organisation.objects.create(nom="Usine", niveau_id="Site", parent=cls.a)  # aucune case au niveau du site
        p = Periode.objects.create(type="annee", debut=datetime.date(2026, 1, 1), fin=datetime.date(2026, 12, 31), libelle="2026")
        cls.c = Campagne.objects.create(referentiel=Referentiel.objects.get(code="TRANSPARENCE_REMU"), periode=p, exercice=2026,
                                        statut=Campagne.Statut.OUVERTE)

        def r(org, code, valeur):
            Reponse.objects.create(periode=p, kpi_id=code, organisation=org, valeur=None if valeur is None else D(str(valeur)),
                                   non_applicable=valeur is None, statut=Reponse.Statut.VALIDE)
        for org, h, f, moy_h, moy_f, med in ((cls.a, 100, 50, 40000, 36000, "0.08"), (cls.b, 20, 80, 60000, 51000, "0.12")):
            r(org, "SOC-REMU-NB-H", h)
            r(org, "SOC-REMU-NB-F", f)
            r(org, "SOC-REMU-MOY-AN-H", moy_h)
            r(org, "SOC-REMU-MOY-AN-F", moy_f)
            r(org, "SOC-ECART-MED-AN", med)
            r(org, "SOC-QUARTILE-1-F", "0.6")
        for code, valeur in (("SOC-REMU-VAR-NB-H", 10), ("SOC-REMU-VAR-NB-F", 0), ("SOC-REMU-VAR-MOY-H", 5000),
                             ("SOC-REMU-VAR-MOY-F", None)):
            r(cls.a, code, valeur)
        for code, valeur in (("SOC-REMU-VAR-NB-H", 10), ("SOC-REMU-VAR-NB-F", 20), ("SOC-REMU-VAR-MOY-H", 4000),
                             ("SOC-REMU-VAR-MOY-F", 3000)):
            r(cls.b, code, valeur)
        recalculer(cls.c)

    def val(self, code, org):
        return Calculateur(self.c).valeur(code, org.id)

    def test_ecart_moyen_par_entite_et_du_groupe(self):
        self.assertEqual(self.val("SOC-ECART-MOY-AN", self.a), D("0.1"))
        self.assertEqual(self.val("SOC-ECART-MOY-AN", self.b), D("0.15"))
        groupe = self.val("SOC-ECART-MOY-AN", self.g)
        self.assertAlmostEqual(float(groupe), 1 - (5880000 / 130) / (5200000 / 120), places=9)  # −4,38 %
        self.assertLess(groupe, 0)  # et non 12,5 %, la moyenne des écarts
        self.assertEqual(self.val("SOC-REMU-TOT-AN-H", self.g), D(5200000))  # totaux additionnés
        cellule = Reponse.objects.get(periode=self.c.periode, kpi_id="SOC-ECART-MOY-AN", organisation=self.g)
        self.assertAlmostEqual(float(cellule.valeur), float(groupe), places=6)  # enregistré par le recalcul

    def test_part_variable(self):
        self.assertEqual(self.val("SOC-REMU-VAR-PART-F", self.a), D(0))
        self.assertAlmostEqual(float(self.val("SOC-REMU-VAR-PART-F", self.g)), 20 / 130, places=9)  # (0 + 20) / (50 + 80)
        self.assertAlmostEqual(float(self.val("SOC-REMU-VAR-PART-H", self.g)), 20 / 120, places=9)
        # aucune femme avec une part variable dans A : son total est N/A et ne compte pas, l'écart du groupe vient de B
        self.assertIs(self.val("SOC-REMU-VAR-TOT-F", self.a), NA)
        self.assertAlmostEqual(float(self.val("SOC-ECART-VAR-MOY", self.g)), 1 - 3000 / ((50000 + 40000) / 20), places=9)

    def test_mediane_et_quartiles_sans_valeur_au_dessus(self):
        self.assertEqual(self.val("SOC-ECART-MED-AN", self.a), D("0.08"))
        self.assertIsNone(self.val("SOC-ECART-MED-AN", self.g))
        self.assertEqual(self.val("SOC-QUARTILE-1-H", self.a), D("0.4"))
        self.assertIsNone(self.val("SOC-QUARTILE-1-H", self.g))
        self.assertFalse(Reponse.objects.filter(kpi_id__in=["SOC-ECART-MED-AN", "SOC-QUARTILE-1-H"], organisation=self.g).exists())

    def test_remunerations_moyennes_sensibles(self):
        self.assertEqual(set(KPI.objects.filter(confidentialite=KPI.Confidentialite.RESTREINT).values_list("code", flat=True)),
                         {"SOC-REMU-MOY-AN-F", "SOC-REMU-MOY-AN-H", "SOC-REMU-MOY-HOR-F", "SOC-REMU-MOY-HOR-H",
                          "SOC-REMU-VAR-MOY-F", "SOC-REMU-VAR-MOY-H"})
        from .sensibles import sensibles_et_derives

        derives = sensibles_et_derives({"SOC-REMU-MOY-AN-F"})
        self.assertIn("SOC-ECART-MOY-AN", derives)  # un écart calculé sur une donnée sensible l'est aussi


class ResumeInstallationTests(TestCase):
    """Le résumé avant installation nomme le niveau conseillé (Entité), et non « le plus bas » (Site)."""

    def test_phrase_du_rattachement(self):
        from django.urls import reverse

        from referentiel.models import Utilisateur

        self.client.force_login(Utilisateur.objects.create_user("adm", "adm@exemple.test", "x", role=Utilisateur.Role.ADMIN))
        kpis = [k["code"] for k in P.fourni(FICHIER).paquet.kpis]
        self.client.post(reverse("parametres:installer_kpi", args=["TRANSPARENCE_REMU"]), {"action": "continuer", "kpi": kpis})
        resume = self.client.get(reverse("parametres:installer_resume", args=["TRANSPARENCE_REMU"]))
        self.assertContains(resume, "les KPI saisis aux niveaux conseillés par le modèle (<b>Entité</b>)", html=False)
        self.assertNotContains(resume, "(le plus bas)")
