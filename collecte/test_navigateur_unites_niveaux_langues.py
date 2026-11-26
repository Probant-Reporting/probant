"""Dans un vrai navigateur (Playwright, Chromium ; ignoré s'il manque) : Paramètres › Niveaux et Unités avec la démo chargée
en espagnol, puis en allemand (langue de référence : le français). Les noms (niveaux, unités, thématiques, symboles du
catalogue, aperçus, pastilles) sont ceux de la langue de l'interface, sans mot français en clair (hors noms propres fictifs
de la démo) ; les champs de saisie gardent la langue de référence et le disent ; en allemand, les noms gardent leur majuscule ;
axe-core sans défaut grave (si AXE_JS) ; la page ne défile pas en largeur sur téléphone (390 px)."""
import os
import re
from io import StringIO

from django.core.management import call_command

from referentiel.models import Utilisateur

from .aides_tests.navigateur import AXE, NavigateurBase, _hors_boucle

UNITES = "/administration/parametres/referentiel/?section=unites"
NIVEAUX = "/administration/parametres/niveaux/"
ORGANISATIONS = "/administration/organisations/"
# mots français des noms d'unités, de niveaux et de thématiques fournis (sensibles à la casse : « Tonne » est aussi allemand)
FRANCAIS_UNITES = re.compile(r"\b(kilowattheure|mégawattheure|tonne|mètre|heure|jours|semaines|mois|années?|salariés|personnes|accidents|"
                             r"fournisseurs|Énergie|Durée|Effectif|Monnaie|Comptages?|Émissions|Intensités|Volume d'eau)\b")
FRANCAIS_NIVEAUX = re.compile(r"\b(Groupe|Pays|Filiale|Entité|Site|Sites)\b")


class _Demo(NavigateurBase):
    """La démo Exemplia dans une langue, sans le jeu d'essai de la base du navigateur."""

    langue = ""

    def setUp(self):
        super(NavigateurBase, self).setUp()
        self._pw = self.navigateur = None
        with _hors_boucle():
            call_command("load_demo", "--language", self.langue, stdout=StringIO())
            self.admin = Utilisateur.objects.get(username="admin")

    def texte(self, page, chemin, ouvrir=True):
        self.aller(page, chemin)
        if ouvrir:
            # seulement les blocs repliables du contenu : le menu de langue de la barre du haut s'ouvre en fenêtre flottante
            # et recouvrirait un onglet des Paramètres (axe : « partially obscured »), ce que personne ne voit sur la page
            page.evaluate("document.querySelectorAll('#contenu details').forEach((d) => { d.open = true; })")
        page.evaluate("document.querySelectorAll('.nom-org').forEach((e) => e.remove())")  # noms propres fictifs de la démo
        return page.inner_text("#contenu")

    def axe(self, page, ou):
        if not (AXE and os.path.exists(AXE)):
            return
        from .test_navigateur_tableaux import REGLES_AXE

        with open(AXE, encoding="utf-8") as f:
            page.add_script_tag(content=f.read())
        self.assertEqual(page.evaluate(REGLES_AXE), [], ou)

    def verifier_commun(self, page):
        unites = self.texte(page, UNITES)
        self.assertEqual(FRANCAIS_UNITES.findall(unites), [], "mot français dans l'écran Unités")
        self.axe(page, "Unités, 1 440 px")
        # les champs de saisie gardent la langue de référence : ce qui est enregistré ne change pas
        self.assertEqual(page.locator('input[name="libelle__0"]').first.input_value(), "kilowattheure")
        niveaux = self.texte(page, NIVEAUX)
        self.assertEqual(FRANCAIS_NIVEAUX.findall(niveaux), [], "mot français dans l'écran Niveaux")
        self.axe(page, "Niveaux, 1 440 px")
        self.assertEqual(page.locator('input[name="nom_Group"]').input_value(), "Groupe")
        # l'aperçu de l'unité, au chargement et après un clic dans une ligne, reste dans la langue de l'interface
        self.aller(page, UNITES)
        self.assertNotIn("kilowattheure", page.inner_text("[data-apercu-unite]"))
        page.evaluate("document.querySelectorAll('#contenu details').forEach((d) => { d.open = true; })")
        page.locator('input[name="libelle__0"]').first.click()
        self.assertNotIn("kilowattheure", page.inner_text("[data-apercu-unite]"))
        return unites, niveaux

    def verifier_telephone(self, page_telephone):
        for chemin in (UNITES, NIVEAUX):
            self.aller(page_telephone, chemin)
            self.assertFalse(page_telephone.evaluate("document.documentElement.scrollWidth > window.innerWidth"), chemin)


class DemoEnEspagnolTests(_Demo):
    langue = "es"

    def test_unites_et_niveaux_en_espagnol(self):
        page = self.page(self.admin)
        unites, niveaux = self.verifier_commun(page)
        for mot in ("Energía", "Duración", "kilovatio hora", "semanas", "meses"):
            self.assertIn(mot, unites)
        for mot in ("Grupo", "País", "Centro", "Idioma de referencia: Français"):
            self.assertIn(mot, niveaux)
        self.assertIn("Español: Grupo · Grupo", niveaux)
        self.verifier_telephone(self.page(self.admin, largeur=390, hauteur=800, tactile=True))


class DemoEnAllemandTests(_Demo):
    langue = "de"

    def test_unites_et_niveaux_en_allemand_avec_majuscules(self):
        page = self.page(self.admin)
        unites, niveaux = self.verifier_commun(page)
        for mot in ("Energie", "Dauer", "Kilowattstunde", "Wochen", "Monate"):
            self.assertIn(mot, unites)
        for mot in ("Konzern", "Land", "Standort", "Tochtergesellschaft", "Referenzsprache: Français"):
            self.assertIn(mot, niveaux)
        self.assertIn("Deutsch: Standort · Standorte", niveaux)
        self.assertIn("Unter „Standort“", niveaux)
        organisations = self.texte(page, ORGANISATIONS, ouvrir=False)
        self.assertRegex(organisations, r"\d+\s+Standorte")  # nom de niveau : majuscule conservée
        self.assertNotIn("standorte", organisations)
        self.verifier_telephone(self.page(self.admin, largeur=390, hauteur=800, tactile=True))
