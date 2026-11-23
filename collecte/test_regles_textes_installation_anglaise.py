"""Textes des règles des modèles de la bibliothèque dans une installation en anglais (réunion des corrections des modèles et
des corrections de l'outil) : le paquet porte le nom et l'explication d'une règle en français et, dans ``traductions``,
en anglais (``socles.paquet``), l'installation enregistre le texte de sa langue de référence, et la liste des règles
et le détail d'une alerte les affichent dans la langue de la personne qui lit, pour une règle d'un ESRS comme pour une règle
de la norme VS.

Défauts corrigés : l'anglais écrit dans ``traductions`` par la relecture des modèles n'était lu par rien (une installation
en anglais enregistrait le nom français), et les corrections de l'outil lisaient la table anglaise des règles de ``documentation.py``, retirée par la relecture des modèles : la liste des règles
tombait en erreur dès qu'un modèle était installé."""
from django.urls import reverse

from parametres import langues as L
from parametres.models import Instance
from referentiel.models import KPI

from . import paquets as P
from .aides_tests.paquets import vider
from .aides_tests.saisie import Base
from .models import Alerte, RegleCoherence

VS = ("Effectif féminin ≤ effectif total", "Female headcount ≤ total headcount",
      "L'effectif féminin ne peut pas dépasser l'effectif total.", "The female headcount cannot exceed the total headcount.")
ESRS = ("Contrats permanents et temporaires ≤ effectif total", "Permanent and temporary employees ≤ total headcount")


def installer(*fichiers):
    for f in fichiers:
        a = P.analyser(P.fourni(f).paquet, source=f, fourni=True)
        assert a.erreur == "", a.erreur
        P.appliquer(None, a)


def explication_esrs(langue):
    regle = next(r for r in P.fourni("esrs_s1.json").paquet.regles if r["nom"] == ESRS[0])
    return regle["description"] if langue == "fr" else regle["traductions"][langue]["description"]


class InstallationReferenceFrancaiseLueEnAnglaisTests(Base):
    """Installation de référence française (la règle est enregistrée en français), lue par une personne en anglais."""

    @classmethod
    def setUpTestData(cls):
        vider()
        installer("vs_base.json", "esrs_s1.json")

    def setUp(self):
        super().setUp()
        self.admin.langue = "en"  # contenus et interface en anglais pour cette personne
        self.admin.save()
        self.client.force_login(self.admin)

    def test_regles_enregistrees_dans_la_langue_de_reference(self):
        noms = set(RegleCoherence.objects.values_list("nom", flat=True))
        self.assertIn(VS[0], noms)
        self.assertIn(ESRS[0], noms)
        self.assertEqual(RegleCoherence.objects.get(nom=VS[0]).description, VS[2])

    def test_liste_des_regles_en_anglais(self):
        page = self.client.get(reverse("collecte:regles"), HTTP_ACCEPT_LANGUAGE="en")
        self.assertEqual(page.status_code, 200)
        html = page.content.decode()
        for anglais, francais in ((VS[1], VS[0]), (ESRS[1], ESRS[0])):
            self.assertIn(anglais, html)
            self.assertNotIn(francais, html)

    def test_alerte_d_une_regle_esrs_et_de_la_vs_en_anglais(self):
        for nom_fr, nom_en, description_en in ((VS[0], VS[1], VS[3]), (ESRS[0], ESRS[1], explication_esrs("en"))):
            with self.subTest(nom_en):
                regle = RegleCoherence.objects.get(nom=nom_fr)
                kpi = KPI.objects.get(code="SOC-EFFECTIF")
                a = Alerte.objects.create(campagne=self.c, kpi=kpi, organisation=self.e1, controle=Alerte.Controle.REGLE,
                                          regle=regle, message=nom_fr, empreinte=f"{regle.pk}|1",
                                          textes={"message": {"cle": "saisie.coherence.msg.regle_non_respectee",
                                                              "v": {"regle": nom_fr}}})
                html = self.client.get(reverse("collecte:alerte", args=[a.pk])).content.decode()
                self.assertIn(nom_en, html)
                self.assertIn(description_en, html)
                self.assertNotIn(nom_fr, html)


class InstallationReferenceAnglaiseTests(Base):
    """Installation de référence anglaise : la règle est enregistrée en anglais et se lit en français pour une personne en
    français."""

    @classmethod
    def setUpTestData(cls):
        i = Instance.courante()
        i.langue_reference, i.langue = "en", "en"
        i.save()
        vider()
        installer("vs_base.json", "esrs_s1.json")

    def test_nom_et_explication_enregistres_en_anglais(self):
        noms = set(RegleCoherence.objects.values_list("nom", flat=True))
        self.assertIn(VS[1], noms)
        self.assertIn(ESRS[1], noms)
        self.assertNotIn(VS[0], noms)
        self.assertEqual(RegleCoherence.objects.get(nom=VS[1]).description, VS[3])
        self.assertEqual(RegleCoherence.objects.get(nom=ESRS[1]).description, explication_esrs("en"))
        # une seule règle par condition : la VS et l'ESRS S1 portent le même contrôle des effectifs
        self.assertEqual(RegleCoherence.objects.filter(gauche="[SOC-EFF-FEMMES]", droite="[SOC-EFFECTIF]").count(), 1)

    def test_lu_en_francais(self):
        with L.activer("fr"):
            self.assertEqual(RegleCoherence.objects.get(nom=ESRS[1]).nom_affiche, ESRS[0])
            self.assertEqual(RegleCoherence.objects.get(nom=VS[1]).description_affichee, VS[2])
