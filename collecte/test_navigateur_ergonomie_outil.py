"""Navigateur (Chromium) : ergonomie de l'outil, un test par défaut relevé au contrôle visuel (DESIGN.md « Menus »,
« Touch targets », « Buttons », « Inputs / Fields »). Rien de métier : focus, largeurs, hauteurs, alignements, styles."""
from referentiel.models import Utilisateur

from .aides_tests.navigateur import NavigateurBase
from .models import Campagne


class MenusFocusTests(NavigateurBase):
    """Échap ferme un menu déroulant et rend le focus au bouton qui l'a ouvert (et non à <body>)."""

    def _ouvrir_puis_echap(self, page, chemin, resume):
        self.aller(page, chemin)
        bouton = page.locator(resume).first
        bouton.focus()
        page.keyboard.press("Enter")
        self.assertTrue(page.evaluate("(s) => document.querySelector(s).closest('details').open", resume))
        page.keyboard.press("Escape")
        self.assertFalse(page.evaluate("(s) => document.querySelector(s).closest('details').open", resume))
        return page.evaluate("""(s) => { const a = document.activeElement; return a === document.querySelector(s); }""", resume)

    def test_menu_affichage_de_la_saisie(self):
        page = self.page()
        self.assertTrue(self._ouvrir_puis_echap(page, "/saisie/", "details.menu-affichage > summary"))

    def test_menu_de_langue(self):
        page = self.page()
        self.assertTrue(self._ouvrir_puis_echap(page, "/saisie/", "details.menu-langue > summary"))

    def test_menu_ouvert_puis_focus_dans_la_liste(self):
        """Le focus est déjà dans la liste du menu (flèche bas) : Échap le ramène au bouton."""
        page = self.page()
        self.aller(page, "/saisie/")
        page.locator("details.menu-langue > summary").focus()
        page.keyboard.press("Enter")
        page.keyboard.press("ArrowDown")
        self.assertTrue(page.evaluate("document.activeElement.closest('.menu-liste') !== null"))
        page.keyboard.press("Escape")
        self.assertTrue(page.evaluate("document.activeElement === document.querySelector('details.menu-langue > summary')"))

    def test_menus_import_et_coherence(self):
        page = self.page()
        for chemin in ("/import-export/", "/coherence/", "/visualisation/", "/administration/parametres/langues/"):
            self.aller(page, chemin)
            for i in range(page.locator("details.menu-deroulant > summary").count()):
                resume = page.locator("details.menu-deroulant > summary").nth(i)
                if not resume.is_visible():
                    continue
                resume.focus()
                page.keyboard.press("Enter")
                if not page.evaluate("document.activeElement.closest('details').open"):
                    continue
                page.keyboard.press("Escape")
                self.assertTrue(page.evaluate("(n) => document.activeElement === document.querySelectorAll('details.menu-deroulant > summary')[n]", i),
                                f"{chemin} menu {i} : le focus n'est pas revenu au bouton")


class MonCompteFocusTests(NavigateurBase):
    def test_la_page_s_ouvre_en_haut_sans_focus_sur_le_mot_de_passe(self):
        page = self.page()
        self.aller(page, "/mon-compte/")
        self.assertEqual(page.evaluate("document.activeElement.name || document.activeElement.tagName"), "BODY")
        self.assertEqual(page.evaluate("window.scrollY"), 0)

    def test_focus_sur_le_mot_de_passe_apres_une_erreur(self):
        page = self.page()
        self.aller(page, "/mon-compte/")
        champ = page.locator("input[name=old_password]")
        champ.fill("mauvais-mot-de-passe-x")
        page.fill("input[name=new_password1]", "Un-nouveau-mot-de-passe-9271")
        page.fill("input[name=new_password2]", "Un-nouveau-mot-de-passe-9271")
        with page.expect_navigation():
            page.locator("form:has(input[name=old_password]) button[type=submit]").first.click()
        page.wait_for_load_state("networkidle")
        self.assertEqual(page.evaluate("document.activeElement.name"), "old_password")


class CampagnesTelephoneTests(NavigateurBase):
    def test_campagnes_sans_defilement_horizontal_de_360_a_390_px(self):
        c = Campagne.objects.first()
        r = c.referentiel
        r.nom = "Norme volontaire de durabilité, module de base pour les petites et moyennes entreprises"
        r.save()
        for largeur in (360, 375, 390):
            page = self.page(largeur=largeur, hauteur=800, tactile=True)
            self.aller(page, "/administration/campagnes/")
            self.assertGreater(page.locator("section.groupe-campagnes").count(), 0)
            self.assertEqual(page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth"), 0,
                             f"défilement horizontal à {largeur} px")
            self.assertEqual(page.evaluate("""() => [...document.querySelectorAll('.tete-groupe-campagnes h2, .tete-groupe-campagnes h2 *')]
                .filter(e => e.getBoundingClientRect().right > innerWidth + 0.5).length"""), 0)


class ColonnesDeChiffresTests(NavigateurBase):
    def test_colonnes_de_chiffres_alignees_a_droite_en_chiffres_tabulaires(self):
        page = self.page()
        for chemin in ("/saisie/", "/tableau-de-bord/", "/tableau-de-bord/relances/", "/administration/campagnes/"):
            self.aller(page, chemin)
            faux = page.evaluate("""() => [...document.querySelectorAll('td.nombre, th.nombre')].filter(e => {
                const s = getComputedStyle(e); return e.getBoundingClientRect().width > 0 && !e.classList.contains('texte') &&
                  (s.textAlign !== 'right' || !s.fontVariantNumeric.includes('tabular-nums')); }).map(e => e.className)""")
            self.assertEqual(faux, [], chemin)


def _contenu_referentiel(test):
    """Deux KPI dans un thème du référentiel des campagnes : de quoi monter et descendre une ligne."""
    from referentiel.models import KPI, ElementReferentiel, Theme

    ref = Campagne.objects.first().referentiel
    theme = Theme.objects.create(referentiel=ref, code="T1", nom="Thème un", ordre=1)
    deuxieme = KPI.objects.create(code="EFF2", libelle="Effectif bis", type_saisie_id="Saisi", granularite_id=test.eff.granularite_id,
                                  methode_agregation="Somme", unite=test.eff.unite, decimales=0)
    ElementReferentiel.objects.create(referentiel=ref, kpi=test.eff, theme=theme, ordre=1)
    ElementReferentiel.objects.create(referentiel=ref, kpi=deuxieme, theme=theme, ordre=2)
    return ref


class DeplacerUnKpiAuClavierTests(NavigateurBase):
    def test_alt_fleche_propose_d_annuler_et_l_annulation_remet_l_ordre(self):
        ref = _contenu_referentiel(self)
        page = self.page(largeur=1440, hauteur=900)
        self.aller(page, f"/administration/referentiels/{ref.code}/")
        ordre = "() => [...document.querySelectorAll('tr[data-element]')].map(t => t.dataset.element)"
        avant = page.evaluate(ordre)
        self.assertEqual(avant, ["EFF", "EFF2"])
        self.assertTrue(page.locator(".astuce-clavier").is_visible())  # le raccourci est écrit à l'écran
        page.locator("tr[data-element=EFF]").focus()
        page.keyboard.press("Alt+ArrowDown")
        page.wait_for_selector("button.lien-annulation")
        self.assertEqual(page.evaluate(ordre), ["EFF2", "EFF"])
        self.assertIn("Effectif", page.locator("#annulation").inner_text())
        page.locator("button.lien-annulation").click()
        page.wait_for_function("() => [...document.querySelectorAll('tr[data-element]')].map(t => t.dataset.element)[0] === 'EFF'")
        self.assertEqual(page.evaluate(ordre), avant)


class DefautsVisuelsTests(NavigateurBase):
    def test_champs_et_boutons_a_une_hauteur_par_taille(self):
        page = self.page()
        mesure = """() => [...document.querySelectorAll('input:not([type=hidden]):not([type=checkbox]):not([type=radio]):not([type=file]):not([type=color]):not([type=search]), select')]
            .filter(e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 && !e.closest('[hidden], .menu-liste, .compact, table'); })
            .map(e => Math.round(e.getBoundingClientRect().height * 10) / 10)"""
        for chemin in ("/administration/parametres/hebergement/", "/administration/comptes/nouveau/", "/mon-compte/", "/administration/parametres/langues/",
                       "/administration/parametres/"):
            self.aller(page, chemin)
            hauteurs = set(page.evaluate(mesure))
            self.assertTrue(hauteurs, chemin)
            self.assertEqual(hauteurs, {40.0}, chemin)

    def test_champ_heure_comme_les_autres_champs(self):
        page = self.page()
        self.aller(page, "/administration/parametres/hebergement/")
        mesure = "e => { const s = getComputedStyle(e); return [e.getBoundingClientRect().height, s.fontSize, s.borderRadius]; }"
        self.assertEqual(page.locator("input[type=time]").first.evaluate(mesure), page.locator("input[type=number]").first.evaluate(mesure))

    def test_pas_de_bouton_principal_dans_la_carte_d_une_langue(self):
        page = self.page()
        self.aller(page, "/administration/parametres/langues/")
        self.assertGreater(page.locator("article.carte-langue .actions-langue a.bouton").count(), 0)
        self.assertEqual(page.locator("article.carte-langue a.bouton:not(.secondaire)").count(), 0)
        hauteurs = page.evaluate("[...document.querySelectorAll('article.carte-langue .actions-langue a.bouton, article.carte-langue .actions-langue summary')].map(e => Math.round(e.getBoundingClientRect().height))")
        self.assertLessEqual(max(hauteurs) - min(hauteurs), 2, hauteurs)

    def test_case_nombre_entier_des_unites_a_une_zone_de_24_px(self):
        page = self.page()
        self.aller(page, "/administration/parametres/referentiel/?section=unites")
        self.assertGreater(page.locator("input[data-entier]").count(), 0)
        petites = page.evaluate("""() => [...document.querySelectorAll('input[data-entier]')].filter(i => i.getBoundingClientRect().width > 0).map(i => {
            const l = i.closest('label'); const r = (l || i).getBoundingClientRect(); return [Math.round(r.width), Math.round(r.height)]; }).filter(d => d[0] < 24 || d[1] < 24)""")
        self.assertEqual(petites, [])

    def test_cibles_citees_au_controle_d_au_moins_24_px(self):
        from .test_navigateur_cibles_tactiles import MESURE

        ref = _contenu_referentiel(self)
        chemins = ["/administration/parametres/referentiel/?section=unites", f"/administration/referentiels/{ref.code}/", "/referentiel/kpi/EFF/",
                   "/coherence/regles/nouvelle/", "/visualisation/", "/introuvable-xyz/", "/mon-compte/"]
        motifs = ("button[button].lien", "a.place-ranger", "button[button].retirer-jeton", "button[button].retirer-filtre", "button[button].icone",
                  'a. "Revenir')
        for largeur in (1440, 390):
            page = self.page(largeur=largeur, hauteur=900, tactile=largeur < 500)
            for chemin in chemins:
                page.goto(self.live_server_url + chemin)
                page.wait_for_load_state("networkidle")
                fautives = [p for p in page.evaluate(MESURE) if any(p.startswith(m) for m in motifs)]
                self.assertEqual(fautives, [], f"{chemin} à {largeur} px")

    def test_page_d_erreur_sans_capitales_espacees_et_lien_de_24_px(self):
        page = self.page()
        reponse = page.goto(self.live_server_url + "/introuvable-xyz/")
        self.assertEqual(reponse.status, 404)
        style = page.locator(".code-erreur").evaluate("e => [getComputedStyle(e).textTransform, getComputedStyle(e).letterSpacing]")
        self.assertEqual(style, ["none", "normal"])
        self.assertGreaterEqual(page.locator("main a").first.bounding_box()["height"], 24)

    def test_un_seul_h1_sur_langues_et_espaces(self):
        page = self.page()
        for chemin in ("/administration/parametres/langues/", "/administration/espaces/"):
            reponse = page.goto(self.live_server_url + chemin)
            if reponse.status != 200:
                continue
            self.assertEqual(page.locator("h1").count(), 1, chemin)

    def test_organisations_controle_segmente_et_boutons_de_meme_hauteur(self):
        page = self.page()
        self.aller(page, "/administration/organisations/")
        hauteurs = page.evaluate("""() => [document.querySelector('.segments'), ...document.querySelectorAll('.barre-filtres .filtres-droite > a.bouton, .barre-filtres .filtres-droite > button')]
            .filter(e => e && e.getBoundingClientRect().height > 0).map(e => Math.round(e.getBoundingClientRect().height))""")
        self.assertGreaterEqual(len(hauteurs), 2)
        self.assertEqual(set(hauteurs), {40}, hauteurs)

    def test_selecteur_de_campagne_identique_pour_contributeur_et_administrateur(self):
        from referentiel.models import Attribution

        contrib = Utilisateur.objects.create(username="contrib", email="contrib@exemple.test")
        Attribution.objects.create(kpi=self.eff, organisation=self.e1, utilisateur=contrib)
        mesures = []
        for qui in (self.admin, contrib):
            page = self.page(qui)
            self.aller(page, "/saisie/")
            mesures.append(page.evaluate("""() => { const e = document.querySelector('.haut .ref-choix'); const r = e.getBoundingClientRect();
                return [r.width <= 2 && r.height <= 2, Math.round(document.querySelector('.haut .bouton-choix-reponse').getBoundingClientRect().width)]; }"""))
        self.assertEqual(mesures[0], mesures[1])
        self.assertTrue(mesures[0][0])

    def test_choix_reponse_ouvert_directement_montre_la_page(self):
        page = self.page()
        self.aller(page, "/je-reponds-a/")
        boite = page.locator(".page-choix-reponse").bounding_box()
        self.assertGreater(boite["height"], 100)
        self.assertLess(boite["y"] + boite["height"], 900)

    def test_bouton_principal_enfonce_plus_sombre_que_le_repos(self):
        page = self.page()
        self.aller(page, "/administration/comptes/nouveau/")
        bouton = page.locator("form[data-ajax] button[type=submit]").first
        luminance = """e => { const t = getComputedStyle(e).backgroundColor; const c = t.match(/[\\d.]+/g).map(Number); const k = t.startsWith('color(') ? 255 : 1;
            return (0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]) * k; }"""
        repos = bouton.evaluate(luminance)
        boite = bouton.bounding_box()
        page.mouse.move(boite["x"] + boite["width"] / 2, boite["y"] + boite["height"] / 2)
        page.mouse.down()
        enfonce = bouton.evaluate(luminance)
        page.mouse.up()
        self.assertLess(enfonce, repos)

    def test_champ_obligatoire_vide_sans_bulle_du_navigateur(self):
        page = self.page()
        self.aller(page, "/administration/comptes/nouveau/")
        self.assertIsNotNone(page.locator("form[data-ajax]").first.get_attribute("novalidate"))
        page.locator("form[data-ajax] button[type=submit]").first.click()
        page.wait_for_selector(".errorlist")
        self.assertGreaterEqual(page.locator(".errorlist").count(), 1)

    def test_confirmation_de_la_cloture_en_style_danger(self):
        c = Campagne.objects.get(exercice=2026)
        page = self.page()
        self.aller(page, f"/administration/campagnes/{c.pk}/")
        bouton = page.locator("button[value=cloturer]").first
        self.assertIn("danger", bouton.get_attribute("class"))
        bouton.click()
        self.assertIn("danger", page.locator("#confirmation [data-confirmer-ok]").get_attribute("class"))
        page.locator("#confirmation [data-annuler]").click()

    def test_panneau_de_saisie_a_360_px_valider_visible_et_ordre_de_tab(self):
        page = self.page(largeur=360, hauteur=640, tactile=True)
        self.aller(page, "/saisie/")
        page.locator("tr.ligne").first.click()
        page.wait_for_selector("body.panneau-ouvert")
        page.wait_for_timeout(500)
        bas = page.locator("#panneau button[value=valider]").first.bounding_box()
        self.assertLessEqual(bas["y"] + bas["height"], 640 + 1)
        ordre = page.evaluate("[...document.querySelectorAll('#panneau .actions button')].map(b => b.value)")
        self.assertEqual(ordre[:2], ["enregistrer", "valider"])
        enregistrer = page.locator("#panneau .actions button[value=enregistrer]").first.bounding_box()
        self.assertLessEqual(enregistrer["y"], bas["y"] + 1)  # l'ordre à l'écran est celui du code


class UnSeulMessageDeLectureSeuleTests(NavigateurBase):
    def test_auditeur_sur_la_saisie_un_seul_message(self):
        auditeur = Utilisateur.objects.create(username="audit", email="audit@exemple.test", role=Utilisateur.Role.AUDITEUR)
        page = self.page(auditeur)
        self.aller(page, "/saisie/")
        messages = page.evaluate("""() => ({fermee: !!document.querySelector('#resume .saisie-fermee'), encart: !!document.querySelector('#resume ~ .encart-info, .encart-info.mt-12')})""")
        self.assertFalse(messages["fermee"] and messages["encart"], messages)
        self.assertTrue(messages["fermee"] or messages["encart"], messages)
