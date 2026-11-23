"""Historique : le motif d'une écriture refusée d'un assistant (ligne « refus_mcp ») est enregistré par son code, puis
recomposé dans la langue de la personne qui lit (avant : le texte dans la langue de la personne refusée, resté en
allemand pour un lecteur en français). L'outil s'affiche tel qu'il s'appelle (« save_value », pas « Save_value »)."""
from django.test import Client
from django.urls import reverse

from collecte.models import Journal
from parametres.libelles import libelle

from .aides_tests import BaseMCP


class MotifCodeTests(BaseMCP):
    def page(self, langue):
        self.admin.langue = langue
        self.admin.save(update_fields=["langue"])
        c = Client()
        c.force_login(self.admin)
        return c.get(reverse("collecte:admin_journal") + "?famille=mcp").content.decode()

    def test_motif_d_une_personne_en_allemand_lu_en_francais_et_en_anglais(self):
        self.contrib.langue = "de"
        self.contrib.save(update_fields=["langue"])
        # campagne clôturée : écriture refusée, motif rédigé en allemand pour la personne refusée
        _, res, d = self.outil("contributeur", "save_value", {**self.case(campagne=self.c0), "value": "5", "version": ""})
        cle = "messages.campagne.lecture_seule.cloturee"
        self.assertEqual(d["error"]["message"], libelle(cle, "de"))
        ligne = Journal.objects.get(action="refus_mcp", utilisateur=self.contrib)
        self.assertNotIn(libelle(cle, "de"), ligne.apres)  # un code, pas le texte allemand
        francais = self.page("fr")
        self.assertNotIn(libelle(cle, "de"), francais)
        self.assertIn(libelle(cle, "fr").replace("'", "&#x27;"), francais)
        self.assertIn(libelle(cle, "en").replace("'", "&#x27;"), self.page("en"))

    def test_ancienne_ligne_en_texte_reste_lisible(self):
        Journal.objects.create(utilisateur=self.contrib, action="refus_mcp", objet="Utilisateur", objet_id=str(self.contrib.pk),
                               champ="save_value", apres="refus : 1 ; jetons : 3 ; dernier refus : 10:00 : Kampagne geschlossen")
        self.assertIn("Kampagne geschlossen", self.page("fr"))

    def test_outil_affiche_sans_majuscule(self):
        self.outil("contributeur", "save_value", {**self.case(campagne=self.c0), "value": "5", "version": ""})
        page = self.page("fr")
        self.assertNotIn("Save_value", page)
        self.assertIn("save_value", page)
