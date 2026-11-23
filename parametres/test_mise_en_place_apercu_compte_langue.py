"""Assistant de mise en place, étape 1 (compte) : l'aperçu de la page de connexion montre le nom par défaut de la structure
dans la langue de l'interface.

Défaut corrigé : à l'étape 1, le nom de la structure est encore la valeur enregistrée à la création de l'installation
(« Ma structure », valeur par défaut du modèle, en français) ; il n'est mis dans la langue de la personne qu'à la création
du compte (``localiser_defauts``). L'aperçu affichait donc « Probant · Ma structure » dans une interface anglaise. Rien
n'est écrit avant la création du compte : seul l'affichage suit la langue ; un nom déjà choisi s'affiche tel quel."""
from django.test import TestCase
from django.urls import reverse

from .libelles import libelle
from .models import Instance

LANGUES = ("en", "fr", "es", "de", "it", "nl", "pt")


class ApercuCompteLangueTests(TestCase):
    def page(self, langue):
        self.client.post(reverse("langue"), {"langue": langue})
        return self.client.get(reverse("parametres:mise_en_place"))

    def test_nom_par_defaut_dans_la_langue_de_l_interface(self):
        self.assertEqual(Instance.courante().nom, "Ma structure")  # valeur enregistrée, inchangée par l'affichage
        for langue in LANGUES:
            with self.subTest(langue):
                rep = self.page(langue)
                nom = libelle("referentiels.mep.defaut.nom", langue=langue)
                self.assertContains(rep, f"{Instance.courante().titre} · {nom}")
                if langue != "fr":
                    self.assertNotContains(rep, "Ma structure")
        self.assertEqual(Instance.courante().nom, "Ma structure")

    def test_nom_choisi_affiche_tel_quel(self):
        i = Instance.courante()
        i.nom = "Exemple SA"
        i.save(update_fields=["nom"])
        self.assertContains(self.page("en"), "Exemple SA")
