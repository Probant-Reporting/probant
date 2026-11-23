"""Aide à la saisie des organisations (assistant, étape 4) : le nom d'un niveau vient des données (« Site », « Filiale »…) :
il est écrit tel quel entre guillemets, jamais fondu dans la phrase (article, genre, majuscule d'une langue)."""
from django.test import SimpleTestCase

from .libelles import libelle

LANGUES = ("en", "fr", "es", "de", "it", "nl", "pt")


class SaisieRapideSansNomFonduTests(SimpleTestCase):
    def test_le_nom_du_niveau_n_entre_pas_dans_la_grammaire_de_la_phrase(self):
        for langue in LANGUES:
            gabarit = libelle("referentiels.mep.organisation.saisie_rapide", langue=langue, niveau="@@", niveau_minuscule="##",
                              niveaux="::")
            self.assertNotIn("##", gabarit, langue)
            for morceau in gabarit.split("@@")[:-1]:
                self.assertTrue(morceau.rstrip().endswith(("[", "[ ")), (langue, morceau[-30:]))

    def test_dates_attendues_dans_les_messages_de_fichier(self):
        for langue in LANGUES:
            texte = libelle("admin.config.erreur.date", langue=langue, valeur="x")
            self.assertIn("-mm-", texte.lower(), langue)  # le format ISO, aussi accepté, est dit
