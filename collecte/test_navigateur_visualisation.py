"""Visualisation dans un vrai navigateur (Playwright, Chromium). Ignoré si Playwright ou Chromium manquent.

Bibliothèques servies par l'outil (hors ligne) ; vues en lecture (filtres, descente, données, clavier, infobulles,
exports, téléphone, nom piégé, axe-core) et en modification (clavier, glisser, flèches, formes, enregistrement,
question en quittant, conflit, droits).
"""
import os
from decimal import Decimal



from referentiel.models import KPI, Niveau

from .models import Reponse
from .aides_tests.navigateur import _hors_boucle
from .aides_tests.navigateur import ATTENTE_LONGUE, AXE, NavigateurBase

D = Decimal


class HorsLigneTests(NavigateurBase):
    def test_bibliotheques_servies_par_l_outil(self):
        """Toute requête vers un autre site est coupée : ECharts et SortableJS se chargent depuis /static/."""
        page = self.page()
        externes = []

        def filtrer(route):
            if route.request.url.startswith(self.live_server_url):
                route.continue_()
            else:
                externes.append(route.request.url)
                route.abort()
        page.route("**/*", filtrer)
        self.aller(page, "/visualisation/")
        for chemin in ("vendor/echarts-6.1.0/echarts.min.js", "vendor/echarts-6.1.0/langFR.js",
                       "vendor/sortablejs-1.15.7/Sortable.min.js"):
            page.add_script_tag(url=f"{self.live_server_url}/static/{chemin}")
        self.assertEqual(page.evaluate("echarts.version"), "6.1.0")
        self.assertEqual(page.evaluate("Sortable.version"), "1.15.7")
        sources = page.evaluate("performance.getEntriesByType('resource').map(r => r.name).filter(n => /echarts|Sortable/.test(n))")
        self.assertTrue(sources)
        self.assertTrue(all(s.startswith(f"{self.live_server_url}/static/vendor/") for s in sources), sources)
        self.assertEqual(externes, [])
        self.assertEqual(page.erreurs, [])


class PageVueTests(NavigateurBase):
    """Visualisation v2 en lecture : une vue partagée de quatre visuels."""

    def setUp(self):
        super().setUp()
        from .models import VueVisu

        self.vue = VueVisu.objects.create(nom="Comité", partage=True, proprietaire=self.admin, visuels=[
            {"id": "a", "type": "chiffre", "kpis": ["EFF"], "largeur": 3, "hauteur": "m"},
            {"id": "b", "type": "organisations", "kpis": ["EFF"], "largeur": 6, "hauteur": "m"},
            {"id": "c", "type": "courbe", "kpis": ["EFF"], "largeur": 6, "hauteur": "m"},
            {"id": "d", "type": "tableau", "kpis": ["EFF"], "largeur": 12, "hauteur": "m"},
        ])
        self.url = f"/visualisation/vues/{self.vue.pk}/"

    def ouvrir(self, page, chemin=None):
        self.aller(page, chemin or self.url)
        page.wait_for_function("document.querySelectorAll('.graphique canvas').length >= 1")

    def test_lecture_filtres_descente_donnees(self):
        page = self.page(self.lecteur)
        self.ouvrir(page)
        self.assertEqual(page.locator(".onglet-vue[aria-current=page]").inner_text().strip()[:6], "Comité")
        self.assertIn("170 ETP", page.locator(".forme-chiffre .valeur-chiffre").inner_text())  # 2025 : 120 + 50
        # voir les données (tableau équivalent, bouton à état)
        bouton = page.locator(".forme-organisations .lien-donnees")
        bouton.click()
        self.assertEqual(bouton.get_attribute("aria-expanded"), "true")
        self.assertIn("170 ETP", page.locator(".forme-organisations .table-donnees-visu").inner_text())
        # flèches sur le graphique : la zone d'annonce lit le texte du serveur ; Entrée descend dans l'arbre
        g = page.locator(".forme-organisations .graphique")
        g.focus()
        page.keyboard.press("ArrowRight")
        page.wait_for_function("document.getElementById('annonce-visu').textContent.includes('Pays')")
        self.assertIn("170 ETP", page.evaluate("document.getElementById('annonce-visu').textContent"))
        page.keyboard.press("Enter")
        page.wait_for_function("location.search.includes('org=')")
        page.wait_for_selector(".chemin-org a")
        self.assertIn("Lille", page.evaluate("JSON.stringify(window.visualisation.donnees().visuels.b.categories)"))
        page.locator(".chemin-org a").first.click()  # remonter
        page.wait_for_function("!document.querySelector('.chemin-org')")
        # changer la période : l'adresse garde le filtre (lien partageable)
        page.select_option("#f-periode", str(self.campagnes[1].periode_id))
        page.wait_for_function("location.search.includes('periode=')")
        page.wait_for_function("document.querySelector('.forme-chiffre .valeur-chiffre').textContent.includes('155 ETP')")
        page.go_back()
        page.wait_for_function("document.querySelector('.forme-chiffre .valeur-chiffre').textContent.includes('170 ETP')")
        self.assertEqual(page.erreurs, [])

    def test_repere_n1_ne_coupe_pas_la_valeur(self):
        """Comparaison des organisations : un repère N-1 plus loin que la barre ne coupe plus le premier chiffre de la valeur,
        écrite après la barre et après le repère."""
        with _hors_boucle():  # Lille 2024 : 200 ; le Pays passe de 245 en 2024 à 170 en 2025
            Reponse.objects.filter(periode=self.campagnes[1].periode, organisation=self.e1).update(valeur=D(200))
        page = self.page(self.lecteur)
        self.ouvrir(page)
        page.wait_for_function("window.visualisation.graphiques.b")
        series = page.evaluate("""window.visualisation.graphiques.b.getOption().series.map(s => ({type: s.type,
            etiquette: !!(s.label && s.label.show), valeurs: s.data.map(d => (d && typeof d === 'object') ? d.value : d)}))""")
        self.assertEqual([(s["type"], s["etiquette"]) for s in series], [("bar", False), ("scatter", False), ("scatter", True)])
        self.assertEqual((series[0]["valeurs"], series[1]["valeurs"], series[2]["valeurs"]), ([170], [245], [245]))
        # le texte écrit reste la valeur de la période (170 ETP), placé après le repère de 2024 (245)
        texte = page.evaluate("window.visualisation.graphiques.b.getOption().series[2].data[0].texte")
        self.assertEqual(texte, "170 ETP")
        self.assertEqual(page.erreurs, [])

    def test_infobulle_au_survol(self):
        """Infobulle d'ECharts : la valeur d'abord (texte du serveur), le libellé ensuite."""
        page = self.page()
        self.ouvrir(page)
        g = page.locator(".forme-courbe .graphique")
        g.scroll_into_view_if_needed()
        boite = g.bounding_box()
        page.mouse.move(boite["x"] + boite["width"] - 40, boite["y"] + boite["height"] / 2)
        bulle = page.locator(".ligne-bulle b").first
        bulle.wait_for()
        self.assertEqual(bulle.inner_text(), "170 ETP")
        self.assertEqual(page.locator(".cat-bulle").first.inner_text(), "2025")

    def test_exports_png_et_excel(self):
        page = self.page()
        self.ouvrir(page)
        carte = page.locator(".forme-organisations")
        carte.locator("summary").click()
        with page.expect_download() as d:
            carte.locator('[data-action="png"]').click()
        png = d.value
        self.assertRegex(png.suggested_filename, r"^Visualisation_Comite_Effectif_\d{4}-\d{2}-\d{2}\.png$")
        with open(png.path(), "rb") as f:
            self.assertEqual(f.read(8), b"\x89PNG\r\n\x1a\n")
        page.locator(".forme-chiffre summary").click()
        with page.expect_download() as d:
            page.locator('.forme-chiffre [data-action="png"]').click()
        self.assertTrue(d.value.suggested_filename.endswith(".png"))
        carte.locator("summary").click()
        with page.expect_download() as d:
            carte.locator('[data-action="excel"]').click()
        self.assertTrue(d.value.suggested_filename.endswith(".xlsx"))
        self.assertEqual(page.erreurs, [])

    def test_telephone_390_sans_defilement(self):
        page = self.page(self.lecteur, largeur=390)
        self.aller(page, self.url)
        self.assertFalse(page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth"))
        self.assertTrue(page.locator(".choix-vue-tel summary").is_visible())
        self.assertFalse(page.locator(".onglets-vues").is_visible())
        page.locator("[data-ouvrir-filtres]").click()
        self.assertTrue(page.locator("#filtres-vue").is_visible())
        page.keyboard.press("Escape")
        self.assertFalse(page.locator("#filtres-vue").is_visible())
        self.assertEqual(page.evaluate("document.activeElement.hasAttribute('data-ouvrir-filtres')"), True)
        self.assertEqual(page.erreurs, [])

    def test_nom_piege_echappe(self):
        with _hors_boucle():
            self.eff.libelle = "<img src=x onerror=alert(1)>"
            self.eff.save()
        page = self.page()
        dialogues = []
        page.on("dialog", lambda d: (dialogues.append(d.message), d.dismiss()))
        self.ouvrir(page)
        self.assertIn("<img src=x onerror=alert(1)>", page.locator(".forme-chiffre .titre-visuel").inner_text())
        page.locator(".forme-organisations .graphique").hover(position={"x": 200, "y": 60})
        page.wait_for_timeout(300)
        self.assertEqual(dialogues, [])
        self.assertEqual(page.locator("img[src=x]").count(), 0)

    def test_noms_des_cartes_uniques(self):
        """Constat (axe-core, landmark-unique) : deux visuels d'un même KPI portaient le même nom de
        repère (le titre seul). Le nom d'une carte est maintenant son titre et son sous-titre ; deux cartes identiques
        (visuel dupliqué) sont numérotées « (2) »."""
        from .models import VueVisu

        with _hors_boucle():
            vue = VueVisu.objects.create(nom="Doublons", partage=True, proprietaire=self.admin, visuels=[
                {"id": "x", "type": "chiffre", "kpis": ["EFF"], "largeur": 3, "hauteur": "m"},
                {"id": "y", "type": "organisations", "kpis": ["EFF"], "largeur": 6, "hauteur": "m"},
                {"id": "z", "type": "chiffre", "kpis": ["EFF"], "largeur": 3, "hauteur": "m"},
            ])
        page = self.page(self.lecteur)
        self.ouvrir(page, f"/visualisation/vues/{vue.pk}/")
        noms = page.evaluate("""() => [...document.querySelectorAll('section[data-visuel]')].map(n => n.getAttribute('aria-label')
            || n.getAttribute('aria-labelledby').split(' ').map(i => document.getElementById(i).textContent.trim()).filter(Boolean).join(' '))""")
        self.assertEqual(len(noms), 3)
        self.assertEqual(len(set(noms)), 3, noms)
        self.assertTrue(noms[2].endswith("(2)"), noms)
        self.assertEqual(page.erreurs, [])

    def test_accessibilite_axe(self):
        if not AXE or not os.path.exists(AXE):
            self.skipTest("axe-core absent (variable AXE_JS)")
        with open(AXE, encoding="utf-8") as f:
            axe = f.read()
        for largeur, modifier in ((1440, False), (390, False), (1440, True), (390, True)):
            page = self.page(self.admin if modifier else self.lecteur, largeur=largeur)
            self.ouvrir(page, self.url + ("?modifier=1" if modifier else ""))
            if modifier:  # réglages du premier visuel ouverts
                page.wait_for_selector("[data-ref-kpi] option", state="attached")
                page.locator("[data-visuel] .selection-visuel").first.click()
                page.wait_for_selector("[data-form-reglages]:not([hidden])")
            page.add_script_tag(content=axe)
            graves = page.evaluate("""async () => { const r = await axe.run(document, {runOnly: {type: 'tag', values:
                ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa']}});
                return r.violations.filter(v => ['serious', 'critical'].includes(v.impact)).map(v => v.id + ' ' + v.nodes.map(n => n.target).join(','))}""")
            self.assertEqual(graves, [], (largeur, modifier))


class EditionTests(NavigateurBase):
    """Visualisation v2 en modification : ajouter au clavier, glisser à la souris, déplacer aux flèches, changer de forme,
    enregistrer puis recharger, question en quittant, conflit, vue partagée non modifiable par un lecteur."""

    def setUp(self):
        super().setUp()
        from referentiel.composition import composer

        self.eff2 = KPI.objects.create(code="EFF2", libelle="Intérimaires", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                                       methode_agregation="Somme", unite=self.eff.unite, decimales=0)
        composer({"EFF": ["Social"], "EFF2": ["Social"]})

    def editer(self, page, chemin):
        self.aller(page, chemin)
        page.wait_for_selector("[data-panneau-kpi] .kpi-liste", state="attached")
        page.locator(".groupe-theme summary").first.click()

    def montrer_filtre(self, page, cle, libelle):
        """Filtre optionnel caché tant qu'il garde sa valeur de départ (revue des filtres, DESIGN.md « Filters ») : on
        l'ouvre comme une personne, par « Ajouter un filtre » puis son nom ; il s'affiche et reçoit le focus."""
        bloc = page.locator(f'[data-filtre-optionnel="{cle}"]')
        self.assertTrue(bloc.is_hidden())
        page.locator("[data-ajouter-filtre] summary").click()
        page.locator("[data-ajouter-filtre]").get_by_role("button", name=libelle, exact=True).click()
        bloc.wait_for(state="visible")
        page.wait_for_function("(cle) => document.activeElement?.closest('[data-filtre-optionnel]')?.dataset.filtreOptionnel === cle", arg=cle)

    def vue(self, nom="Perso", **autres):
        from .models import VueVisu

        with _hors_boucle():
            return VueVisu.objects.create(nom=nom, proprietaire=self.admin, **autres)

    def test_ajouter_au_clavier_changer_de_forme_enregistrer(self):
        from .models import VueVisu

        page = self.page()
        self.editer(page, "/visualisation/vues/nouvelle/")
        bouton = page.get_by_role("button", name="Ajouter « Effectif » à la vue")
        bouton.focus()
        page.keyboard.press("Enter")
        carte = page.locator("[data-visuel]").first
        carte.locator(".valeur-chiffre").wait_for(timeout=ATTENTE_LONGUE)  # forme choisie par le serveur : chiffre clé
        self.assertIn("Visuel « Effectif » ajouté", page.locator("#toast").inner_text())
        carte.focus()
        page.keyboard.press("Enter")  # sélection : les réglages s'ouvrent et reçoivent le focus
        page.wait_for_function("document.activeElement && document.activeElement.id === 'titre-reglages'")
        self.assertTrue(page.locator("[data-form-reglages]").is_visible())
        anneau = page.locator('input[name="type"][value="anneau"]')
        self.assertFalse(anneau.is_disabled())
        page.locator('.choix-forme[data-forme="courbe"]').click()
        page.wait_for_selector('[data-visuel].forme-courbe .graphique canvas')
        page.keyboard.press("Escape")
        page.fill("[data-nom-vue]", "Ma vue au clavier")
        page.locator("[data-barre-haut] [data-enregistrer-vue]").click()
        page.wait_for_url("**/visualisation/vues/*/")
        with _hors_boucle():
            v = VueVisu.objects.get(nom="Ma vue au clavier")
        self.assertEqual((v.proprietaire_id, [x["type"] for x in v.visuels], v.visuels[0]["kpis"]), (self.admin.id, ["courbe"], ["EFF"]))
        page.reload()
        page.wait_for_selector(".forme-courbe .graphique canvas")
        self.assertEqual(page.erreurs, [])

    def test_glisser_a_la_souris_et_deplacer_aux_fleches(self):
        v = self.vue(visuels=[{"id": "a", "type": "chiffre", "kpis": ["EFF"], "largeur": 3, "hauteur": "m"}])
        page = self.page()
        self.editer(page, f"/visualisation/vues/{v.pk}/?modifier=1")
        page.locator('.kpi-liste[data-code="EFF2"]').drag_to(page.locator("[data-grille]"), target_position={"x": 600, "y": 40})
        page.wait_for_function("document.querySelectorAll('[data-grille] > [data-visuel]').length === 2")
        page.wait_for_function("[...document.querySelectorAll('[data-visuel] .titre-visuel')].some(h => h.textContent.includes('Intérimaires'))")
        rang = page.evaluate("[...document.querySelectorAll('[data-grille] > [data-visuel]')].findIndex(x => x.dataset.id === 'a') + 1")
        poignee = page.locator('[data-visuel][data-id="a"] .poignee-visuel')
        self.assertIn(f"position {rang} sur 2", poignee.get_attribute("aria-label"))
        poignee.focus()
        page.keyboard.press("End")
        page.wait_for_function("document.querySelector('[data-grille] > [data-visuel]:last-child').dataset.id === 'a'")
        if rang == 2:
            page.keyboard.press("ArrowLeft")
            page.wait_for_function("document.querySelector('[data-grille] > [data-visuel]').dataset.id === 'a'")
            self.assertIn("déplacé en position 1 sur 2", page.locator("#toast").inner_text())
        else:
            self.assertIn("déplacé en position 2 sur 2", page.locator("#toast").inner_text())
        self.assertEqual(page.evaluate("document.activeElement.closest('[data-visuel]').dataset.id"), "a")
        page.keyboard.press("Home")
        page.wait_for_function("document.querySelector('[data-grille] > [data-visuel]').dataset.id === 'a'")
        # question de l'outil en quittant par un lien : la modification n'est pas enregistrée (plus celle du navigateur)
        dialogues = []
        page.on("dialog", lambda d: (dialogues.append(d.type), d.dismiss()))
        question = page.locator('[data-fenetre="quitter"]')
        page.locator(".barre-vues .nouvelle-vue").click()
        question.wait_for()
        self.assertEqual(page.evaluate("document.activeElement.dataset.quitter"), "continuer")
        page.keyboard.press("Escape")  # Échap : on continue la modification
        question.wait_for(state="hidden")
        self.assertIn("modifier=1", page.url)
        page.locator(".barre-vues .nouvelle-vue").click()
        question.get_by_role("button", name="Quitter sans enregistrer").click()
        page.wait_for_url("**/visualisation/vues/nouvelle/")
        self.assertEqual(dialogues, [])
        self.assertEqual(page.erreurs, [])

    def test_enregistrer_et_quitter(self):
        """« Enregistrer et quitter » : refusé (conflit), on reste en modification avec l'erreur à l'écran ; enregistré,
        le lien est suivi."""
        v = self.vue(visuels=[{"id": "a", "type": "chiffre", "kpis": ["EFF"], "largeur": 3, "hauteur": "m"}])
        page = self.page()
        self.editer(page, f"/visualisation/vues/{v.pk}/?modifier=1")
        page.fill("[data-nom-vue]", "Perso renommée")
        question = page.locator('[data-fenetre="quitter"]')
        with _hors_boucle():
            version = type(v).objects.get(pk=v.pk).version
            type(v).objects.filter(pk=v.pk).update(version=version + 5)  # modifiée ailleurs entre-temps
        page.locator(".barre-vues .nouvelle-vue").click()
        question.get_by_role("button", name="Enregistrer et quitter").click()
        page.wait_for_function("!document.getElementById('erreur-persistante').hidden")
        self.assertIn("modifiée entre-temps", page.locator("#erreur-persistante").inner_text())
        self.assertTrue(question.is_hidden())
        self.assertIn("modifier=1", page.url)
        with _hors_boucle():
            type(v).objects.filter(pk=v.pk).update(version=version)
        page.locator(".barre-vues .nouvelle-vue").click()
        question.get_by_role("button", name="Enregistrer et quitter").click()
        page.wait_for_url("**/visualisation/vues/nouvelle/")
        with _hors_boucle():
            self.assertEqual(type(v).objects.get(pk=v.pk).nom, "Perso renommée")
        self.assertEqual(page.erreurs, [])

    def test_conflit_et_ajout_a_un_visuel(self):
        v = self.vue(visuels=[{"id": "a", "type": "chiffre", "kpis": ["EFF"], "largeur": 3, "hauteur": "m"}])
        page = self.page()
        self.editer(page, f"/visualisation/vues/{v.pk}/?modifier=1")
        page.locator('[data-visuel][data-id="a"] .selection-visuel').click()
        page.get_by_role("button", name="Ajouter « Intérimaires » au visuel « Effectif »").click()
        page.wait_for_selector('[data-visuel][data-id="a"].forme-courbe, [data-visuel][data-id="a"].forme-barres')  # même unité : une série de plus
        with _hors_boucle():
            type(v).objects.filter(pk=v.pk).update(version=5)  # modifiée ailleurs entre-temps
        page.locator("[data-barre-haut] [data-enregistrer-vue]").click()
        page.wait_for_function("document.getElementById('toast').textContent.includes('modifiée entre-temps')")
        self.assertIn("modifier=1", page.url)  # les changements restent dans la page

    def test_barre_du_haut_et_ctrl_s(self):
        """En modification, « Abandonner les modifications » et « Enregistrer la vue » restent visibles en haut, à deux
        tabulations de « Modifier la vue » ; Ctrl + S enregistre la vue en modification, et rien en lecture."""
        from .models import VueVisu

        v = self.vue(visuels=[{"id": f"v{i}", "type": "chiffre", "kpis": ["EFF"], "largeur": 3, "hauteur": "m"} for i in range(16)])
        page = self.page()
        self.aller(page, f"/visualisation/vues/{v.pk}/")
        page.wait_for_selector(".forme-chiffre .valeur-chiffre")
        self.assertFalse(page.locator("[data-barre-haut]").is_visible())
        page.keyboard.press("Control+s")  # en lecture : la vue n'est pas enregistrée
        page.wait_for_timeout(300)
        with _hors_boucle():
            self.assertEqual(VueVisu.objects.get(pk=v.pk).version, v.version)
        page.locator("[data-modifier-vue]").focus()
        page.keyboard.press("Enter")
        barre = page.locator("[data-barre-haut]")
        barre.wait_for()
        page.wait_for_function("document.activeElement && document.activeElement.hasAttribute('data-barre-haut')")
        page.wait_for_function("document.getElementById('annonce-visu').textContent.includes('Ctrl + S')")
        self.assertIn("Enregistrer la vue", page.evaluate("document.getElementById('annonce-visu').textContent"))
        bouton = barre.locator("[data-enregistrer-vue]")
        self.assertEqual(bouton.get_attribute("aria-keyshortcuts"), "Control+S Meta+S")
        self.assertEqual(page.locator("#aide-raccourci-visu").inner_text(), "Raccourci : Ctrl + S")
        page.keyboard.press("Tab")
        page.keyboard.press("Tab")
        self.assertEqual(page.evaluate("document.activeElement.textContent.trim()"), "Enregistrer la vue")
        # toujours visible : collée en haut de l'écran, même en bas de la page
        page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
        page.wait_for_timeout(200)
        self.assertGreater(page.evaluate("window.scrollY"), 300)
        boite = bouton.bounding_box()
        self.assertTrue(0 <= boite["y"] <= 60, boite)
        # Ctrl + S depuis le nom de la vue : la vue est enregistrée
        page.fill("[data-nom-vue]", "Renommée au clavier")
        page.keyboard.press("Control+s")
        page.wait_for_url(f"**/visualisation/vues/{v.pk}/")
        with _hors_boucle():
            self.assertEqual(VueVisu.objects.get(pk=v.pk).nom, "Renommée au clavier")
        self.assertEqual(page.erreurs, [])

    def test_telephone_barre_du_haut_et_vue_vide(self):
        """Téléphone (375 px, tactile) : la barre du haut garde ses deux boutons sans déborder ; la vue vide ne dit pas
        « Glissez » (on ajoute par boutons)."""
        page = self.page(largeur=375, hauteur=740, tactile=True)
        self.aller(page, "/visualisation/vues/nouvelle/")
        barre = page.locator("[data-barre-haut]")
        barre.wait_for()
        self.assertIn("touchez « Ajouter des KPI »", page.locator(".vue-vide").inner_text())
        self.assertNotIn("Glissez", page.locator(".vue-vide").inner_text())
        self.assertFalse(page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth"))
        for b in (barre.locator("[data-annuler-vue]"), barre.locator("[data-enregistrer-vue]")):
            self.assertTrue(b.is_visible())
            self.assertGreaterEqual(b.bounding_box()["height"], 44)
        self.assertFalse(page.locator("#aide-raccourci-visu").is_visible())  # pas de clavier : pas de raccourci écrit
        self.assertEqual(page.erreurs, [])

    def test_enregistrer_les_filtres_dans_la_vue(self):
        """Filtres changés en lecture : « Enregistrer les filtres » (la personne peut modifier la vue) ; les
        visuels ne changent pas. En modification : « Garder les filtres », dans le brouillon."""
        from .models import VueVisu

        v = self.vue(visuels=[{"id": "a", "type": "chiffre", "kpis": ["EFF"], "largeur": 3, "hauteur": "m"}])
        page = self.page()
        self.aller(page, f"/visualisation/vues/{v.pk}/")
        page.wait_for_selector(".forme-chiffre .valeur-chiffre")
        bouton = page.locator("[data-enregistrer-filtres]")
        self.assertFalse(bouton.is_visible())
        self.montrer_filtre(page, "brouillons", "Valeurs")
        self.assertFalse(bouton.is_visible())  # filtre seulement affiché : rien n'a changé
        page.select_option("#f-valeurs", "1")  # brouillons compris
        bouton.wait_for(state="visible")
        self.assertFalse(page.locator("[data-garder-filtres]").is_visible())
        bouton.click()
        page.wait_for_url(f"**/visualisation/vues/{v.pk}/")
        page.wait_for_function("document.getElementById('toast').textContent.includes('Filtres enregistrés dans la vue « Perso »')")
        with _hors_boucle():
            w = VueVisu.objects.get(pk=v.pk)
        self.assertEqual((w.filtres.get("valeurs"), w.visuels, w.version), ("brouillons", v.visuels, v.version + 1))
        self.assertFalse(bouton.is_visible())  # les filtres de la page sont ceux de la vue
        # en modification : changer un filtre propose de le garder dans le brouillon (pas d'enregistrement direct)
        page.locator("[data-modifier-vue]").click()
        page.locator("[data-barre-haut]").wait_for()
        page.select_option("#f-valeurs", "0")
        garder = page.locator("[data-garder-filtres]")
        garder.wait_for(state="visible")
        self.assertFalse(bouton.is_visible())
        garder.click()
        page.wait_for_function("document.getElementById('toast').textContent.includes('Filtres gardés')")
        page.locator("[data-barre-haut] [data-enregistrer-vue]").click()
        page.wait_for_url(f"**/visualisation/vues/{v.pk}/")
        with _hors_boucle():
            self.assertEqual(VueVisu.objects.get(pk=v.pk).filtres.get("valeurs"), "validees")
        self.assertEqual(page.erreurs, [])

    def test_lecteur_vue_partagee_non_modifiable(self):
        v = self.vue(nom="Partagée", partage=True, visuels=[{"id": "a", "type": "chiffre", "kpis": ["EFF"], "largeur": 3, "hauteur": "m"}])
        page = self.page(self.lecteur)
        self.aller(page, f"/visualisation/vues/{v.pk}/?modifier=1")
        page.wait_for_selector(".forme-chiffre .valeur-chiffre")
        self.assertEqual(page.locator("[data-modifier-vue]").count(), 0)
        self.assertFalse(page.locator("[data-panneau-kpi]").is_visible())
        self.assertTrue(page.get_by_role("button", name="Dupliquer pour modifier").first.is_visible())
        self.montrer_filtre(page, "brouillons", "Valeurs")
        page.select_option("#f-valeurs", "1")  # filtres changés : rien à enregistrer pour un lecteur
        page.wait_for_selector("[data-retablir]:not([hidden])")
        self.assertEqual(page.locator("[data-enregistrer-filtres], [data-garder-filtres]").count(), 0)
