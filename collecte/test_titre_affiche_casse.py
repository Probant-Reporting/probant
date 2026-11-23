"""Titre d'une campagne en milieu de phrase (``Campagne.titre_affiche``, et ``titre`` qui le reprend) : la casse vient du
libellé de chaque langue, jamais d'un passage en minuscules (« Berichtsjahr 2026 » en allemand, nom commun avec majuscule ;
un mois anglais garde sa majuscule)."""
import datetime

from django.urls import reverse

from parametres import langues as L
from parametres.libelles import libelle
from referentiel.models import Frequence

from . import periodes as P
from .aides_tests.echanges import Base
from .models import Campagne

LANGUES = ("en", "fr", "es", "de", "it", "nl", "pt")


class TitreAfficheCasseTests(Base):
    def test_annuel_dans_chaque_langue(self):
        for lg in LANGUES:
            with self.subTest(langue=lg), L.activer(lg):
                c = Campagne.objects.get(pk=self.c.pk)
                attendu = libelle("messages.campagne.exercice_titre", lg, annee=c.periode)
                self.assertEqual(c.titre_affiche, attendu)
                self.assertEqual(c.titre, attendu)
        with L.activer("de"):
            self.assertEqual(Campagne.objects.get(pk=self.c.pk).titre_affiche, "Berichtsjahr 2026")
        with L.activer("fr"):
            self.assertEqual(Campagne.objects.get(pk=self.c.pk).titre_affiche, "exercice 2026")

    def test_mois_garde_sa_casse(self):
        mars = P.obtenir(Frequence.MOIS, datetime.date(2026, 3, 1))
        for lg, attendu in (("en", "March 2026"), ("fr", "mars 2026")):
            with self.subTest(langue=lg), L.activer(lg):
                c = Campagne(referentiel=self.c.referentiel, periode=mars, exercice=2026)
                self.assertEqual(c.titre_affiche, attendu)

    def test_titre_de_page_en_allemand(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("langue"), {"langue": "de"})
        t = self.client.get(reverse("collecte:tableau_de_bord") + f"?campagne={self.c.pk}").content.decode()
        self.assertIn("Berichtsjahr 2026", t)
        self.assertNotIn("berichtsjahr 2026", t)
