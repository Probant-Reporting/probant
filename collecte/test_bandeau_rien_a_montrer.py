"""Bandeau « ce qui reste à faire » (``views._bandeau``) quand il n'y a rien à montrer (aucune case attendue, aucune
alerte) : aucun état, aucune phrase annoncée ; jamais « Tout est fait » sur une liste vide. Témoin : des cases attendues,
toutes validées, donnent bien « fini »."""
from django.test import TestCase

from . import saisie as S
from . import views as V


class BandeauRienAMontrerTests(TestCase):
    def test_rien_a_montrer_aucun_etat(self):
        b = V._bandeau(S.Reste(), S.Compteur())
        self.assertEqual(b["code"], "")
        self.assertNotIn("annonce", b)

    def test_temoin_tout_valide_fini(self):
        b = V._bandeau(S.Reste(total=2, valide=2), S.Compteur(total=2, valide=2))
        self.assertEqual(b["code"], "fini")
        self.assertTrue(b["annonce"])
