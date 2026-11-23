"""Deux petits trous de l'.

- ``calcul.Decompte.lire`` : un décompte enregistré « Oui : 3 · Non : 2 » se relit tel quel ; une réponse seule, sans
  « : n » (case d'une organisation : « Oui »), compte pour une.
- ``imports.appliquer`` d'un fichier refusé (colonnes introuvables) : rien n'est écrit et le nombre d'écritures rendu
  est 0."""
from django.test import SimpleTestCase

from . import imports as I
from .calcul import Decompte
from .models import Reponse
from .aides_tests.echanges import Base
from .outils_tests import xlsx


class DecompteLireTests(SimpleTestCase):
    def test_reponse_seule_compte_pour_une(self):
        self.assertEqual(Decompte.lire("Oui"), {"Oui": 1})
        self.assertEqual(Decompte.lire("Oui : 3 · Non : 2"), {"Oui": 3, "Non": 2})
        self.assertEqual(Decompte.lire("Oui : 2 · Non"), {"Oui": 2, "Non": 1})
        self.assertEqual(Decompte.lire(""), {})


class AppliquerRefuseTests(Base):
    def test_fichier_refuse_aucune_ecriture(self):
        avant = Reponse.objects.count()
        a, n, avertissements = I.appliquer(self.admin, xlsx([["Nom", "Montant"], ["Lyon", 3]]), campagne_defaut=self.c.pk)
        self.assertTrue(a.erreur)
        self.assertEqual((n, avertissements), (0, []))
        self.assertEqual(Reponse.objects.count(), avant)
