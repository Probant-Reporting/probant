"""Couleurs des fichiers Excel propres au fil (ContextVar) : deux exports simultanés de deux espaces dans le même
processus ne mélangent pas leurs couleurs ; les appelants lisent toujours ``X.MAGENTA``, ``X.NIVEAU_COULEURS``…"""
import contextvars
import threading

from django.test import SimpleTestCase, TestCase

from parametres.models import Instance

from . import fichiers as X


class PaletteParFilTests(SimpleTestCase):
    def test_deux_contextes_ne_se_voient_pas(self):
        vus = {}
        pret = threading.Barrier(2)

        def exporter(nom, couleur):
            X._PALETTE.set({**X.PALETTE_DEFAUT, "MAGENTA": couleur, "NIVEAU_COULEURS": {"G": (couleur, "FFFFFF")}})
            pret.wait()  # les deux fils ont posé leur palette avant de la lire
            vus[nom] = (X.MAGENTA, X.NIVEAU_COULEURS["G"][0], X.palette()["MAGENTA"])

        fils = [threading.Thread(target=exporter, args=a) for a in (("a", "111111"), ("b", "222222"))]
        for f in fils:
            f.start()
        for f in fils:
            f.join()
        self.assertEqual(vus, {"a": ("111111",) * 3, "b": ("222222",) * 3})

    def test_contexte_isole(self):
        def dans_un_autre_contexte():
            X._PALETTE.set({**X.PALETTE_DEFAUT, "VIOLET": "333333"})
            return X.VIOLET
        self.assertEqual(contextvars.copy_context().run(dans_un_autre_contexte), "333333")
        self.assertNotEqual(contextvars.Context().run(lambda: X.VIOLET), "333333")

    def test_nom_inconnu(self):
        with self.assertRaises(AttributeError):
            X.COULEUR_INCONNUE  # noqa: B018


class PaletteInstallationTests(TestCase):
    def test_couleurs_marque_suit_l_identite(self):
        def lire():
            X.couleurs_marque()
            return X.MAGENTA
        attendu = Instance.courante().gamme()["principale"].lstrip("#")
        self.assertEqual(contextvars.Context().run(lire), attendu)
