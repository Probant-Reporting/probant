"""« Récemment supprimés » de Mon compte dans un vrai navigateur (Playwright, Chromium) : « Restaurer » remet l'export à
sa place, la page reste sur la section avec le message « Restauré », la ligne disparaît ; sur téléphone, le bouton
passe sous le texte, en pleine largeur, sans défilement horizontal. Ignoré si Playwright ou Chromium manquent."""
import os


from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.cache import cache, caches

from referentiel.models import Utilisateur

from .models import ReglageExport, VueVisu
from .outils_tests import RetourSerialiseIndependantDeLOrdre, ServeurDeTestUnSeulFil, navigateur_indisponible
from .aides_tests.navigateur import _hors_boucle, _lancer_chromium, attentes_longues, surveiller_politique, sync_playwright


class SupprimesNavigateurTests(ServeurDeTestUnSeulFil, RetourSerialiseIndependantDeLOrdre, StaticLiveServerTestCase):
    serialized_rollback = True

    @classmethod
    def setUpClass(cls):
        if sync_playwright is None:
            navigateur_indisponible("Playwright n'est pas installé.")
        cls._async = os.environ.get("DJANGO_ALLOW_ASYNC_UNSAFE")
        os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        if cls._async is None:
            os.environ.pop("DJANGO_ALLOW_ASYNC_UNSAFE", None)
        else:
            os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = cls._async

    def tearDown(self):
        if self._pw is not None:
            self.navigateur.close()
            self._pw.stop()
        super().tearDown()

    def page(self, utilisateur, largeur=1440):
        with _hors_boucle():
            self.client.force_login(utilisateur)
        if self._pw is None:
            self._pw = sync_playwright().start()
            try:
                self.navigateur = _lancer_chromium(self._pw)
            except Exception as e:  # noqa: BLE001 - navigateur absent : test ignoré
                self._pw.stop()
                self._pw = None
                navigateur_indisponible(f"Chromium indisponible : {e}")
        ctx = self.navigateur.new_context(viewport={"width": largeur, "height": 900})
        ctx.add_cookies([{"name": settings.SESSION_COOKIE_NAME, "value": self.client.cookies[settings.SESSION_COOKIE_NAME].value,
                          "url": self.live_server_url}])
        page = ctx.new_page()
        page.set_default_timeout(15000)
        attentes_longues(page)
        page.erreurs = []
        page.on("pageerror", lambda e: page.erreurs.append(str(e)))
        return surveiller_politique(self, page)

    def setUp(self):
        cache.clear()
        caches["connexion"].clear()  # compteur des essais de connexion (cache dédié)
        self.contrib = Utilisateur.objects.create(username="contrib", email="contrib@exemple.test", first_name="Camille")
        self.export = ReglageExport.objects.create(nom="Énergie mensuelle", proprietaire=self.contrib, parametres={})
        self.export.supprimer(self.contrib)
        self._pw = self.navigateur = None

    def test_restaurer_depuis_mon_compte(self):
        page = self.page(self.contrib)
        page.goto(self.live_server_url + "/mon-compte/")
        section = page.locator("#recemment-supprimes")
        self.assertIn("Énergie mensuelle", section.inner_text())
        bouton = section.get_by_role("button", name="Restaurer « Énergie mensuelle »")
        bouton.focus()
        page.keyboard.press("Enter")  # au clavier
        page.wait_for_url("**/mon-compte/#recemment-supprimes")
        self.assertIn("Restauré : « Énergie mensuelle »", page.locator("body").inner_text())
        self.assertNotIn("Énergie mensuelle", section.inner_text())
        self.assertIn("Rien de supprimé récemment", section.inner_text())
        self.assertTrue(ReglageExport.objects.filter(pk=self.export.pk, proprietaire=self.contrib).exists())
        self.assertEqual(page.erreurs, [])

    def test_telephone_bouton_pleine_largeur(self):
        VueVisu.objects.create(nom="Une vue au nom assez long pour passer sur deux lignes au moins", proprietaire=self.contrib).supprimer(self.contrib)
        page = self.page(self.contrib, largeur=390)
        page.goto(self.live_server_url + "/mon-compte/")
        bouton = page.locator("#recemment-supprimes .liste-supprimes button").first
        boite, ligne = bouton.bounding_box(), page.locator("#recemment-supprimes .supprime").first.bounding_box()
        self.assertGreaterEqual(boite["height"], 44)
        self.assertGreater(boite["width"], ligne["width"] - 2)  # pleine largeur de la ligne
        self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), 390)
