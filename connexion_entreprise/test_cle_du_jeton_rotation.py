"""Clés du fournisseur (JWKS) : gardées en mémoire, relues quand une clé inconnue arrive (rotation chez le fournisseur),
au plus une fois par minute ; découverte gardée 10 minutes. Aucun appel au fournisseur sans geste d'une personne."""
from unittest import mock

from django.test import Client

from . import oidc
from .aides_tests import BaseEntreprise


def lectures_cles(faux):
    return sum(1 for m, p in faux.appels if m == "GET" and p.endswith("/jwks"))


class RotationTests(BaseEntreprise):
    def setUp(self):
        super().setUp()
        self.regler()

    def test_rotation_suivie(self):
        c, _ = self.parcours()
        self.assertTrue(self.connecte(c))
        self.assertEqual(lectures_cles(self.faux), 1)
        c, _ = self.parcours()  # clés gardées : pas de nouvelle lecture
        self.assertEqual(lectures_cles(self.faux), 1)
        self.faux.tourner()  # le fournisseur signe avec une clé nouvelle
        c, _ = self.parcours()
        self.assertTrue(self.connecte(c))
        self.assertEqual(lectures_cles(self.faux), 2)

    def test_cle_inconnue_relue_une_fois_par_minute_au_plus(self):
        self.parcours()
        self.faux.mode = "cle_inconnue"
        with self.assertLogs("connexion_entreprise", "WARNING"):
            self.parcours()
            self.parcours()
            self.parcours()
        self.assertEqual(lectures_cles(self.faux), 2)  # une relecture pour trois jetons à clé inconnue
        with mock.patch.object(oidc.time, "monotonic", return_value=oidc.time.monotonic() + oidc.RELECTURE_CLES + 1):
            with self.assertLogs("connexion_entreprise", "WARNING"):
                self.parcours()
        self.assertEqual(lectures_cles(self.faux), 3)  # une minute après : une relecture de plus

    def test_aucun_appel_sans_geste(self):
        """Page de connexion, pages de l'outil, réglage lu : aucun appel au fournisseur ; seulement le bouton."""
        Client().get("/connexion/")
        c = Client()
        c.force_login(self.contrib)
        c.get("/mon-compte/")
        self.assertEqual(self.faux.appels, [])
        self.aller()
        self.assertEqual([p.split("?")[0].rsplit("/", 1)[-1] for _, p in self.faux.appels], ["openid-configuration"])
