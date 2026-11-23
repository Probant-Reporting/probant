"""Panneau de saisie ouvert en français, langue passée à l'anglais dans un autre onglet, puis enregistrement du panneau
resté ouvert : « 2,125 » reste 2,125 (``saisie.texte_nombre`` lit le nombre dans la langue où le formulaire a été
affiché ; avant, le serveur lisait 2125 en silence). Enregistrement explicite et enregistrement automatique."""
import unittest
from decimal import Decimal

from . import saisie as S
from .aides_tests.navigateur import _hors_boucle, attentes_longues
from .models import Reponse
from .test_navigateur_saisie import PanneauNavigateurTests


class DeuxOngletsLangueTests(PanneauNavigateurTests):
    def setUp(self):
        super().setUp()
        for org in (self.e1, self.e2):
            S.enregistrer(self.contrib, self.c, self.nb, org, "2.125", False, "")

    def passer_en_anglais(self, page):
        autre = attentes_longues(page.context.new_page())  # autre onglet, même session
        autre.goto(self.live_server_url + "/pour-moi/")
        autre.evaluate("""async () => { const d = new FormData(); d.append('langue', 'en');
            d.append('csrfmiddlewaretoken', document.querySelector('[name=csrfmiddlewaretoken]').value);
            await fetch('/langue/', { method: 'POST', body: d }); }""")
        autre.close()

    def valeur(self, org):
        with _hors_boucle():
            return Reponse.objects.get(kpi=self.nb, organisation=org).valeur, \
                Reponse.objects.get(kpi=self.nb, organisation=org).commentaire

    def test_valeur_relue_dans_la_langue_du_panneau(self):
        page = self.page()
        self.aller(page, f"/saisie/?org={self.e1.id}")
        # enregistrement explicite
        self.ouvrir(page, self.nb)
        self.assertEqual(page.input_value("#panneau-contenu #valeur"), "2,125")
        self.passer_en_anglais(page)
        page.fill("#panneau-contenu #commentaire", "vérifié")
        page.locator("#panneau-contenu button[value=enregistrer]").click()
        for _ in range(100):
            if not page.en_vol and self.valeur(self.e1)[1] == "vérifié":
                break
            page.wait_for_timeout(100)
        self.assertEqual(self.valeur(self.e1), (Decimal("2.125"), "vérifié"))
        # enregistrement automatique (Échap ferme en enregistrant le brouillon), panneau ouvert avant le changement
        self.aller(page, f"/saisie/?org={self.e2.id}")  # page en anglais désormais : on revient au français d'abord
        page.evaluate("""async () => { const d = new FormData(); d.append('langue', 'fr');
            d.append('csrfmiddlewaretoken', document.querySelector('[name=csrfmiddlewaretoken]').value);
            await fetch('/langue/', { method: 'POST', body: d }); }""")
        self.aller(page, f"/saisie/?org={self.e2.id}")
        self.ouvrir(page, self.nb, self.e2)
        self.assertEqual(page.input_value("#panneau-contenu #valeur"), "2,125")
        self.passer_en_anglais(page)
        page.fill("#panneau-contenu #commentaire", "auto")
        page.keyboard.press("Escape")
        self.attendre_fermeture(page)
        for _ in range(100):
            if not page.en_vol and self.valeur(self.e2)[1] == "auto":
                break
            page.wait_for_timeout(100)
        self.assertEqual(self.valeur(self.e2), (Decimal("2.125"), "auto"))
        self.assertEqual(page.erreurs, [])


def load_tests(loader, tests, pattern):
    """Seulement le test de ce fichier (pas ceux de la classe de base, déjà lancés dans test_navigateur_saisie)."""
    return unittest.TestSuite([DeuxOngletsLangueTests("test_valeur_relue_dans_la_langue_du_panneau")])
