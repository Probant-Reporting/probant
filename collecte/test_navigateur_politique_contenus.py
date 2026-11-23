"""Politique de sécurité des contenus (collecte/politique_contenus.py) dans un vrai navigateur (Playwright, Chromium ;
ignoré s'il manque, obligatoire avec REQUIRE_BROWSER_TESTS=1).

- Balayage : chaque page de l'outil qu'un rôle peut ouvrir (adresses sans paramètre et avec paramètre, remplies avec les
  objets du jeu d'essai), en apparence claire puis sombre, pour les cinq rôles ; la page de connexion et la page 404 sans
  connexion ; le mode expert. Aucune violation de la politique (évènement ``securitypolicyviolation`` et console,
  ``aides_tests.navigateur.surveiller_politique``, qui vaut pour tous les tests du navigateur) ni aucune erreur de script.
- Gestes dont le gestionnaire en attribut a été remplacé par un écouteur : même comportement qu'avant.
- Page reçue à la place d'un fichier et écrite dans le document (``document.write``) : stylée et active.
- Constructeur de formule, glisser-déposer du contenu d'un référentiel, assistant de mise en place, changement de langue."""
import re

from django.test import Client

from parametres import couleurs as CO
from parametres.models import Instance
from referentiel.models import Attribution, Utilisateur

from .aides_tests.navigateur import _hors_boucle
from .aides_tests.navigateur import NavigateurBase
from .models import TableauVisu, VueVisu
from .test_droits_balayage import routes

EXCLUES = {"logout", "langue"}  # déconnexion ; changement de langue (renvoi, pas une page)


class _Jeu(NavigateurBase):
    def setUp(self):
        super().setUp()
        self.validateur = Utilisateur.objects.create(username="val", email="val@exemple.test", role=Utilisateur.Role.VALIDATEUR)
        self.contrib = Utilisateur.objects.create(username="contrib", email="contrib@exemple.test")
        self.auditeur = Utilisateur.objects.create(username="auditeur", email="auditeur@exemple.test", role=Utilisateur.Role.AUDITEUR)
        for o in (self.e1, self.e2):
            Attribution.objects.create(kpi=self.eff, organisation=o, utilisateur=self.contrib)
        Attribution.objects.create(kpi=self.eff, organisation=self.p, utilisateur=self.validateur, role=Attribution.Role.VALIDATEUR)
        self.vue = VueVisu.objects.create(nom="Comité", partage=True, proprietaire=self.admin, visuels=[
            {"id": "a", "type": "chiffre", "kpis": ["EFF"], "largeur": 3, "hauteur": "m"},
            {"id": "b", "type": "organisations", "kpis": ["EFF"], "largeur": 6, "hauteur": "m"}])
        self.tableau = TableauVisu.objects.create(nom="Comité", proprietaire=self.admin, partage=True, tuiles=[{"type": "chiffre", "kpi": "EFF"}])
        from .models import Campagne

        self.ouverte = Campagne.objects.get(exercice=2026)

    def candidats(self):
        """Valeurs essayées pour chaque paramètre d'adresse : la première qui donne une page est gardée."""
        ref = self.ouverte.referentiel
        return {"pk": [self.vue.pk, self.tableau.pk, self.ouverte.pk, ref.pk, self.admin.pk, self.e1.pk],
                "code": ["EFF", ref.code, "fr", "en"], "kpi_id": ["EFF"], "org_id": [self.e1.pk], "user_id": [self.contrib.pk],
                "campagne_id": [self.ouverte.pk], "etape": [2], "guide": ["administrator", "contributor", "reader"],
                "langue": ["en"], "nom": ["x"], "nom_fichier": ["x"], "type_": ["vue"]}

    def pages_ouvertes(self, u):
        """Adresses qui répondent par une page (200, HTML) à ce compte, trouvées sans navigateur."""
        c = Client()
        if u is not None:
            c.force_login(u)
        cand, pages = self.candidats(), []
        for ns, nom, motif in routes():
            if nom in EXCLUES:
                continue
            noms = re.findall(r"<(?:\w+:)?(\w+)>", motif)
            if not noms:
                essais = [{}]
            elif len(noms) == 1:
                essais = [{noms[0]: v} for v in cand.get(noms[0], [])]
            else:  # case de saisie, image d'un guide
                essais = [{"campagne_id": self.ouverte.pk, "kpi_id": "EFF", "org_id": self.e1.pk, "langue": "en", "nom": "x"}]
            for valeurs in essais:
                url = "/" + re.sub(r"<(?:\w+:)?(\w+)>", lambda m: str(valeurs.get(m.group(1), "x")), motif)
                rep = c.get(url)
                if rep.status_code == 200 and rep.get("Content-Type", "").startswith("text/html"):
                    pages.append(url)
                    break
        return sorted(set(pages))

    def ouvrir_en(self, apparence, u):
        page = self.page(u)
        page.emulate_media(color_scheme="dark" if apparence == "sombre" else "light")
        page.context.add_cookies([{"name": CO.COOKIE_APPARENCE, "value": apparence, "url": self.live_server_url}])
        return page


class _Balayage:
    """Balayage d'un rôle (mélangé à ``_Jeu`` par les classes ci-dessous : une classe par rôle, lancées en parallèle)."""

    role = None

    def compte(self):
        return {"admin": self.admin, "validateur": self.validateur, "contributeur": self.contrib, "lecteur": self.lecteur,
                "auditeur": self.auditeur}[self.role]

    def test_toutes_les_pages_dans_les_deux_apparences(self):
        u = self.compte()
        with _hors_boucle():
            pages = self.pages_ouvertes(u)
        self.assertGreater(len(pages), 8, pages)
        for apparence in ("clair", "sombre"):
            page = self.ouvrir_en(apparence, u)
            for url in pages:
                page.goto(self.live_server_url + url, wait_until="networkidle")
                self.assertEqual(page.evaluate("document.documentElement.dataset.apparence || ''"), apparence, url)
                self.assertEqual(page.violations_csp, [], f"{self.role}, {apparence} : {url}")
            self.assertEqual(page.erreurs, [], f"{self.role}, {apparence}")

class BalayageAdministrateurTests(_Balayage, _Jeu):
    role = "admin"


class BalayageValidateurTests(_Balayage, _Jeu):
    role = "validateur"


class BalayageContributeurTests(_Balayage, _Jeu):
    role = "contributeur"


class BalayageLecteurTests(_Balayage, _Jeu):
    role = "lecteur"


class BalayageAuditeurTests(_Balayage, _Jeu):
    role = "auditeur"


class GestesPolitiqueContenusTests(_Jeu):
    def test_connexion_404_et_mode_expert(self):
        page = self.page()
        page.context.clear_cookies()  # sans connexion
        for apparence in ("light", "dark"):
            page.emulate_media(color_scheme=apparence)
            self.aller(page, "/connexion/")
            page.locator("input[name=username]").fill("admin@exemple.test")
            self.aller(page, "/nulle-part/")
            self.assertIn("404", page.title())
        page = self.page()
        with _hors_boucle():
            Utilisateur.objects.filter(pk=self.admin.pk).update(is_staff=True, is_superuser=True)
        self.aller(page, "/admin/")
        self.aller(page, "/admin/referentiel/kpi/")
        self.assertEqual(page.erreurs, [])

    def test_choix_qui_envoient_leur_formulaire(self):
        """« Afficher les calculés » (Saisie, menu Affichage) et « Regrouper par » (Pour moi) : un changement envoie le
        formulaire, comme l'ancien ``onchange="this.form.submit()"``."""
        page = self.page(self.contrib)
        self.aller(page, "/pour-moi/")
        groupe = page.locator("#choix-groupe")
        with page.expect_navigation():
            groupe.select_option("theme")
        self.assertIn("groupe=theme", page.url)
        self.assertEqual(page.locator("#choix-groupe").input_value(), "theme")
        self.assertEqual(page.erreurs, [])

    def test_assistant_langues_et_lien_d_apercu(self):
        with _hors_boucle():
            Instance.objects.filter(pk=Instance.courante().pk).update(mise_en_place_terminee=False, mise_en_place_etape=3)
        page = self.page()
        self.aller(page, "/mise-en-place/3/")
        choix = page.locator("select[data-remplir-libelle]")  # langue proposée : son libellé remplit le champ « Libellé »
        valeur = choix.locator("option").nth(1).get_attribute("value")
        choix.select_option(valeur)
        attendu = choix.locator("option").nth(1).get_attribute("data-libelle")
        self.assertTrue(attendu)
        self.assertEqual(page.locator("input[name=libelle]").input_value(), attendu)
        page.locator("input[data-vider-code]").fill("xx")  # code libre : le choix proposé se vide
        self.assertEqual(choix.input_value(), "")
        page.locator("input[data-vider-code]").fill("")  # champ vidé : le choix n'est pas touché
        choix.select_option(valeur)
        page.locator("input[data-vider-code]").fill("")
        self.assertEqual(choix.input_value(), valeur)
        for etape in range(2, 9):
            self.aller(page, f"/mise-en-place/{etape}/")
        # Identité : le lien de l'aperçu ne mène nulle part (ancien onclick="return false")
        self.aller(page, "/administration/parametres/")
        lien = page.locator("a[data-lien-inerte]").first
        avant = page.url
        lien.click()
        self.assertEqual(page.url, avant)
        self.assertEqual(page.erreurs, [])

    def test_page_recue_a_la_place_d_un_fichier(self):
        """Un téléchargement qui reçoit une page (message, erreur) l'écrit dans le document : la page garde la politique
        de la précédente ; ses styles et scripts portent alors le jeton de celle-ci et s'appliquent."""
        page = self.page(self.contrib)
        self.aller(page, "/pour-moi/")
        page.evaluate("""() => { const a = document.createElement('a'); a.href = '/mon-compte/';
                                a.setAttribute('data-telechargement', ''); a.id = 'essai-telechargement';
                                a.textContent = 'x'; document.body.append(a); }""")
        fond = page.evaluate("getComputedStyle(document.body).backgroundColor")
        page.locator("#essai-telechargement").click()
        page.wait_for_function("() => !!document.getElementById('apparence') && !document.getElementById('essai-telechargement')")
        page.wait_for_load_state("networkidle")
        self.assertEqual(page.evaluate("location.pathname"), "/pour-moi/")  # page écrite sur place
        # couleurs de l'installation (<style> intégré de la page reçue) appliquées, comme avant la page écrite
        self.assertEqual(page.evaluate("getComputedStyle(document.body).backgroundColor"), fond)
        # script de la page reçue actif : le choix de l'apparence s'applique sans recharger
        page.get_by_role("button", name=re.compile("Sombre|Dark")).click()
        page.wait_for_function("() => document.documentElement.getAttribute('data-apparence') === 'sombre'")
        self.assertEqual(page.erreurs, [])

    def test_constructeur_de_formule_et_glisser_deposer(self):
        page = self.page()
        self.aller(page, "/referentiel/kpi/nouveau/")
        page.locator("input[name=type_saisie][value='Calculé']").check()
        recherche = page.locator("[data-si-calcule] [data-recherche-kpi]")
        recherche.fill("EFF")
        suggestion = page.locator("[data-si-calcule] [data-suggestions] li[data-id]").first
        suggestion.wait_for()
        suggestion.click()
        page.locator("[data-si-calcule] [data-jetons] .retirer-jeton").first.wait_for()  # jeton ajouté (icône du script)
        # contenu d'un référentiel : le KPI glissé dans un autre thème y est rangé
        from referentiel.models import ElementReferentiel, Theme

        with _hors_boucle():
            ref = self.ouverte.referentiel
            t1 = Theme.objects.create(referentiel=ref, code="T1", nom="Social")
            t2 = Theme.objects.create(referentiel=ref, code="T2", nom="Environnement")
            ElementReferentiel.objects.update_or_create(referentiel=ref, kpi=self.eff, defaults={"theme": t1, "ordre": 0})
        self.aller(page, f"/administration/referentiels/{ref.code}/")
        page.locator("tr[data-element='EFF']").drag_to(page.locator(f"#contenu-referentiel section[data-zone='{t2.pk}'] .tete-theme"))
        for _ in range(100):
            with _hors_boucle():
                if ElementReferentiel.objects.get(referentiel=ref, kpi=self.eff).theme_id == t2.pk:
                    break
            page.wait_for_timeout(100)
        with _hors_boucle():
            self.assertEqual(ElementReferentiel.objects.get(referentiel=ref, kpi=self.eff).theme_id, t2.pk)
        self.assertEqual(page.erreurs, [])

    def test_langue_menus_et_apparence(self):
        page = self.page()
        self.aller(page, "/mon-compte/")
        page.get_by_role("button", name=re.compile("Sombre|Dark")).click()
        page.wait_for_function("() => document.documentElement.getAttribute('data-apparence') === 'sombre'")
        langue = page.locator("details.menu-langue").first
        langue.locator("summary").click()
        self.assertTrue(langue.evaluate("d => d.open"))
        with page.expect_navigation():
            langue.locator("button[value=en]").click()
        page.wait_for_load_state("networkidle")
        self.assertEqual(page.evaluate("document.documentElement.lang"), "en")
        self.aller(page, "/visualisation/")
        self.aller(page, "/consolidation/")
        self.assertEqual(page.erreurs, [])
