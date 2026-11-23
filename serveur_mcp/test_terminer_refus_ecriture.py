"""Écritures refusées d'un assistant (``journal.terminer``) : assez de trace pour repérer l'essai d'un jeton volé, sans
refaire exploser le volume du journal. Dans la ligne du jour de la personne (« appels_mcp ») : les écritures refusées à
part et les numéros des jetons utilisés ; et une ligne par personne, par jour et par outil d'écriture refusé
(« refus_mcp »), mise à jour sur place : nombre de refus, jetons, heure et motif du dernier refus, ses arguments."""
import datetime
import re

from django.test import Client
from django.urls import reverse

from collecte.models import Journal

from . import jetons as JT
from .aides_tests import BaseMCP


class RefusEcritureTests(BaseMCP):
    def jour(self, u):
        return Journal.objects.get(action="appels_mcp", utilisateur=u)

    def refuser(self, jeton="contributeur", valeur="5"):
        # campagne clôturée : écriture refusée
        res = self.outil(jeton, "save_value", {**self.case(campagne=self.c0), "value": valeur, "version": ""})[1]
        self.assertTrue(res["isError"])

    def test_ligne_du_jour_jetons_et_ecritures_refusees(self):
        second, j2 = JT.creer(self.contrib, "Second", 7)
        j1 = JT.authentifier(self.jetons["contributeur"])[1]
        self.outil("contributeur", "list_campaigns")
        self.refuser()
        self.refuser(second)
        self.outil("contributeur", "get_value", self.case(org=self.e2))  # lecture refusée : hors périmètre
        texte = self.jour(self.contrib).apres
        m = re.fullmatch(r"lectures : 1 ; refus : 3 ; dernier appel : \d\d:\d\d ; écritures refusées : 2 ; jetons : (.+)", texte)
        self.assertIsNotNone(m, texte)
        self.assertEqual(m.group(1), f"{j1.pk}, {j2.pk}")

    def test_une_ligne_par_personne_jour_et_outil_d_ecriture_refuse(self):
        avant = Journal.objects.count()
        for n in range(25):
            self.refuser(valeur=str(n))
        self.refuser("admin")
        lignes = Journal.objects.filter(action="refus_mcp", utilisateur=self.contrib)
        self.assertEqual(lignes.count(), 1)
        ligne = lignes.get()
        j1 = JT.authentifier(self.jetons["contributeur"])[1]
        self.assertEqual(ligne.champ, "save_value")
        self.assertRegex(ligne.apres, rf"^refus : 25 ; jetons : {j1.pk} ; dernier refus : \d\d:\d\d : .+")
        self.assertIn('"value": "24"', ligne.avant)  # arguments du dernier refus
        # personne et jour : contrib (ligne du jour + refus_mcp), admin (ligne du jour + refus_mcp)
        self.assertEqual(Journal.objects.count() - avant, 4)
        # le lendemain : une nouvelle ligne
        Journal.objects.filter(pk=ligne.pk).update(date=ligne.date - datetime.timedelta(days=1))
        self.refuser()
        self.assertEqual(Journal.objects.filter(action="refus_mcp", utilisateur=self.contrib).count(), 2)

    def test_lecture_refusee_sans_ligne_de_refus_d_ecriture(self):
        self.outil("contributeur", "get_value", self.case(org=self.e2))
        self.assertFalse(Journal.objects.filter(action="refus_mcp").exists())

    def test_historique_famille_mcp_et_traduction(self):
        self.refuser()
        c = Client()
        c.force_login(self.admin)
        page = c.get(reverse("collecte:admin_journal") + "?famille=mcp").content.decode()
        self.assertIn("écritures refusées : 1", page)
        self.assertIn("refus : 1 ; jetons : ", page)
        self.admin.langue = "en"
        self.admin.save(update_fields=["langue"])
        page = c.get(reverse("collecte:admin_journal") + "?famille=mcp").content.decode()
        self.assertIn("refused writes: 1; tokens no.: ", page)
        self.assertIn("refused: 1; tokens no.: ", page)
