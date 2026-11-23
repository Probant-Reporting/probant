"""Apparence sombre dans un vrai navigateur (Playwright, Chromium) : réglage du système, choix de Mon compte,
impression et images exportées en clair, graphiques redessinés, contrastes (axe-core si AXE_JS)."""
import io
import os

from parametres import couleurs as CO
from parametres.models import Instance

from .aides_tests.navigateur import _hors_boucle
from .aides_tests.navigateur import AXE, NavigateurBase


def rgb(h):
    return "rgb({}, {}, {})".format(*CO.rgb(h))


class ApparenceNavigateurTests(NavigateurBase):
    """Une vue de trois visuels (chiffre clé, organisations, courbe), en sombre."""

    def setUp(self):
        super().setUp()
        from .models import VueVisu

        self.vue = VueVisu.objects.create(nom="Comité", partage=True, proprietaire=self.admin, visuels=[
            {"id": "a", "type": "chiffre", "kpis": ["EFF"], "largeur": 3, "hauteur": "m"},
            {"id": "b", "type": "organisations", "kpis": ["EFF"], "largeur": 6, "hauteur": "m"},
            {"id": "c", "type": "courbe", "kpis": ["EFF"], "largeur": 6, "hauteur": "m"},
        ])
        self.url = f"/visualisation/vues/{self.vue.pk}/"

    def ouvrir(self, page, chemin=None):
        self.aller(page, chemin or self.url)
        page.wait_for_function("document.querySelectorAll('.graphique canvas').length >= 1")

    def page_schema(self, schema, utilisateur=None, largeur=1440, apparence=None):
        page = self.page(utilisateur, largeur=largeur)
        page.emulate_media(color_scheme=schema)
        if apparence:
            page.context.add_cookies([{"name": CO.COOKIE_APPARENCE, "value": apparence, "url": self.live_server_url}])
        return page

    def gammes(self):
        with _hors_boucle():
            g = Instance.courante().gamme()
        return g, CO.gamme_sombre(g)

    def fond(self, page):
        return page.evaluate("getComputedStyle(document.body).backgroundColor")

    def test_systeme_choix_et_impression(self):
        clair, sombre = self.gammes()
        page = self.page_schema("dark", self.lecteur)
        self.ouvrir(page)
        self.assertEqual(self.fond(page), rgb(sombre["fond"]))
        self.assertEqual(page.evaluate("getComputedStyle(document.documentElement).colorScheme"), "dark")
        # la sonde garde les couleurs claires (images exportées, impression)
        self.assertEqual(page.evaluate("getComputedStyle(document.querySelector('.apparence-claire.sonde')).getPropertyValue('--surface').trim()"),
                         clair["surface"])
        page.emulate_media(media="print")
        self.assertEqual(self.fond(page), "rgb(255, 255, 255)")  # l'impression reste claire
        page.emulate_media(media="screen", color_scheme="light")
        self.assertEqual(self.fond(page), rgb(clair["fond"]))  # suit le système pendant la visite
        # choix « Claire » sur un système sombre, « Sombre » sur un système clair
        page = self.page_schema("dark", self.lecteur, apparence="clair")
        self.aller(page, "/mon-compte/")
        self.assertEqual(self.fond(page), rgb(clair["fond"]))
        page = self.page_schema("light", self.lecteur, apparence="sombre")
        self.aller(page, "/mon-compte/")
        self.assertEqual(self.fond(page), rgb(sombre["fond"]))
        self.assertEqual(page.erreurs, [])

    def choisir_apparence(self, page, nom, attribut):
        """Le choix s'applique sans recharger la page (14b49ed) : le script envoie le formulaire (fetch), puis pose
        data-apparence sur <html> et aria-pressed sur le bouton, à la réponse du serveur. On attend cet état précis :
        wait_for_load_state("networkidle") répondait aussitôt (chargement de la page déjà fini), avant la réponse."""
        bouton = page.get_by_role("button", name=nom)
        bouton.click()
        page.wait_for_function("(a) => document.documentElement.getAttribute('data-apparence') === a", arg=attribut)
        self.assertEqual(bouton.get_attribute("aria-pressed"), "true")

    def test_choix_dans_mon_compte(self):
        clair, sombre = self.gammes()
        page = self.page_schema("light", self.lecteur)
        self.aller(page, "/mon-compte/")
        self.choisir_apparence(page, "Sombre", "sombre")
        self.assertEqual(self.fond(page), rgb(sombre["fond"]))
        self.aller(page, "/mon-compte/")  # le choix est enregistré (cookie) : la page suivante le garde
        self.assertEqual(page.evaluate("document.documentElement.getAttribute('data-apparence')"), "sombre")
        self.assertEqual(self.fond(page), rgb(sombre["fond"]))
        self.choisir_apparence(page, "Automatique", None)
        self.assertEqual(self.fond(page), rgb(clair["fond"]))  # système clair
        self.aller(page, "/mon-compte/")
        self.assertIsNone(page.evaluate("document.documentElement.getAttribute('data-apparence')"))
        self.assertEqual(page.erreurs, [])

    def test_graphiques_sombres_image_claire(self):
        """À l'écran, les graphiques prennent les couleurs sombres ; l'image exportée garde le fond clair ; l'impression
        redessine les graphiques en clair, puis les rend."""
        from PIL import Image

        clair, sombre = self.gammes()
        page = self.page_schema("dark")
        self.ouvrir(page)
        theme = "echarts.getInstanceByDom(document.querySelector('.forme-organisations .graphique')).getOption().yAxis[0].axisLabel.color"
        self.assertEqual(page.evaluate(theme), sombre["texte"])
        carte = page.locator(".forme-organisations")
        carte.locator("summary").click()
        with page.expect_download() as d:
            carte.locator('[data-action="png"]').click()
        with open(d.value.path(), "rb") as f:
            image = Image.open(io.BytesIO(f.read())).convert("RGB")
        self.assertEqual(image.getpixel((4, 4)), CO.rgb(clair["surface"]))
        self.assertEqual(page.evaluate(theme), sombre["texte"])  # la page garde ses couleurs
        page.evaluate("window.dispatchEvent(new Event('beforeprint'))")
        self.assertEqual(page.evaluate(theme), clair["texte"])
        page.evaluate("window.dispatchEvent(new Event('afterprint'))")
        self.assertEqual(page.evaluate(theme), sombre["texte"])
        page.emulate_media(color_scheme="light")  # réglage du système changé pendant la visite
        page.wait_for_function(f"{theme} === {clair['texte']!r}")
        self.assertEqual(page.erreurs, [])

    def test_accessibilite_axe_sombre(self):
        if not AXE or not os.path.exists(AXE):
            self.skipTest("axe-core absent (variable AXE_JS)")
        with open(AXE, encoding="utf-8") as f:
            axe = f.read()
        for largeur, chemin in ((1440, self.url), (390, self.url), (1440, "/mon-compte/"), (1440, "/administration/parametres/")):
            page = self.page_schema("dark", self.admin, largeur=largeur)
            self.aller(page, chemin)
            page.add_script_tag(content=axe)
            graves = page.evaluate("""async () => { const r = await axe.run(document, {runOnly: {type: 'tag', values:
                ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']}});
                return r.violations.filter(v => ['serious', 'critical'].includes(v.impact)).map(v => v.id + ' ' + v.nodes.map(n => n.target).join(','))}""")
            self.assertEqual(graves, [], (largeur, chemin))

