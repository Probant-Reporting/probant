"""Panneau de saisie dans un vrai navigateur (Playwright, Chromium) : aucune valeur tapée n'est perdue.

Fermer le panneau (Échap, voile, croix, retour du téléphone) avec une valeur, une case N/A ou un commentaire non
enregistrés pose la question « Enregistrer le brouillon et fermer / Fermer sans enregistrer / Continuer la saisie »,
depuis Saisie, Pour moi et « Tous mes référentiels ». La saisie tapée survit au dépôt d'une preuve et à « Rouvrir la
saisie ». Accessibilité et téléphone (étape 6) : lien d'évitement, titres, pastilles, marges. Ignoré si Playwright
ou Chromium manquent (la recette de l'étape exige qu'il ait tourné).
"""
import datetime
import os
import shutil
import tempfile
from decimal import Decimal


from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.utils import timezone

from parametres.models import TypeReponse
from referentiel.composition import composer
from referentiel.models import KPI, Attribution, Niveau, Organisation, Referentiel, Utilisateur

from . import saisie as S
from .aides_tests.navigateur import _hors_boucle, _lancer_chromium, attentes_longues, surveiller_politique, sync_playwright
from .outils_tests import RetourSerialiseIndependantDeLOrdre, ServeurDeTestUnSeulFil, navigateur_indisponible
from .models import Campagne, Journal, Reponse

PDF = b"%PDF-1.4 test"


class PanneauNavigateurTests(ServeurDeTestUnSeulFil, RetourSerialiseIndependantDeLOrdre, StaticLiveServerTestCase):
    """Deux référentiels (« Reporting » et « Énergie », même année) pour que Pour moi propose « Tous mes
    référentiels » ; trois formats de réponse : nombre, oui / non, liste sans option par défaut."""

    serialized_rollback = True  # réglages fournis par les migrations (niveaux, types), remis avant chaque test

    @classmethod
    def setUpClass(cls):
        if sync_playwright is None:
            navigateur_indisponible("Playwright n'est pas installé.")
        # Playwright (synchrone) garde une boucle asyncio active dans ce fil tant qu'il tourne : il est lancé dans
        # chaque test, après les données, et arrêté avant le nettoyage de la base ; entre-temps, l'ORM passe par
        # _hors_boucle() (voir self.base)
        cls._async = os.environ.get("DJANGO_ALLOW_ASYNC_UNSAFE")
        os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
        cls._media = tempfile.mkdtemp()
        cls._reglage_media = override_settings(MEDIA_ROOT=cls._media)
        cls._reglage_media.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._reglage_media.disable()
        shutil.rmtree(cls._media, ignore_errors=True)
        if cls._async is None:
            os.environ.pop("DJANGO_ALLOW_ASYNC_UNSAFE", None)
        else:
            os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = cls._async

    def setUp(self):
        super().setUp()
        oui_non, _ = TypeReponse.objects.get_or_create(code="OuiNonEssai", defaults={"libelle": "Oui / non", "format": "oui_non"})
        liste, _ = TypeReponse.objects.get_or_create(code="ListeEssai", defaults={"libelle": "Niveau", "format": "liste",
                                                                                   "valeurs": ["Faible", "Fort"]})
        self.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.p = Organisation.objects.create(nom="Pays", niveau_id=Niveau.COUNTRY, parent=self.g)
        self.e1 = Organisation.objects.create(nom="Lille", niveau_id=Niveau.ENTITY, parent=self.p)
        self.e2 = Organisation.objects.create(nom="Lyon", niveau_id=Niveau.ENTITY, parent=self.p)

        def kpi(code, libelle, **autres):
            return KPI.objects.create(code=code, libelle=libelle, type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                                      **{"methode_agregation": "Somme", **autres})
        self.nb = kpi("NB", "Effectif")
        self.oui = kpi("OUI", "Politique formalisée", type_reponse=oui_non, methode_agregation="Décompte")
        self.lst = kpi("LST", "Niveau de risque", type_reponse=liste, methode_agregation="Aucune")
        self.nrj = kpi("NRJ", "Énergie totale")
        rse = Referentiel.objects.create(code="RSE", nom="Reporting", ordre=1, couleur="#1F5FAD")
        nrg = Referentiel.objects.create(code="ENERGIE", nom="Énergie", ordre=2, couleur="#E07A1F")
        composer({"NB": ["Social"], "OUI": ["Social"], "LST": ["Social"]}, rse)
        composer({"NRJ": ["Consommations"]}, nrg)
        fin = timezone.localdate() + datetime.timedelta(days=30)
        self.c = Campagne.objects.create(referentiel=rse, exercice=2026, statut=Campagne.Statut.OUVERTE, date_fin_saisie=fin)
        Campagne.objects.create(referentiel=nrg, exercice=2026, statut=Campagne.Statut.OUVERTE, date_fin_saisie=fin)
        self.contrib = Utilisateur.objects.create(username="contrib", email="contrib@exemple.test")
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN)
        for k in (self.nb, self.oui, self.lst, self.nrj):
            for o in (self.e1, self.e2):
                Attribution.objects.create(kpi=k, organisation=o, utilisateur=self.contrib)
        self._pw = self.navigateur = None

    def tearDown(self):
        if self._pw is not None:
            self.navigateur.close()
            self._pw.stop()
        super().tearDown()

    # -- outils --------------------------------------------------------------------------------------------------
    def page(self, utilisateur=None, largeur=1440):
        """Page connectée (cookie de session posé, sans passer par la page de connexion) ; dialogues notés."""
        with _hors_boucle():
            self.client.force_login(utilisateur or self.contrib)
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
        page.set_default_timeout(15000)  # suite en parallèle : le serveur de test peut être lent
        attentes_longues(page)
        page.dialogues = []
        page.erreurs = []
        page.on("pageerror", lambda e: page.erreurs.append(str(e)))
        # requêtes parties et pas encore terminées (voir attendre_reponse)
        page.en_vol = set()
        page.on("request", lambda r: page.en_vol.add(r))
        page.on("requestfinished", lambda r: page.en_vol.discard(r))
        page.on("requestfailed", lambda r: page.en_vol.discard(r))

        def dialogue(d):
            page.dialogues.append(d.type)
            d.dismiss()  # « Quitter la page ? » : on reste
        page.on("dialog", dialogue)
        return surveiller_politique(self, page)

    def aller(self, page, chemin):
        page.goto(self.live_server_url + chemin)
        page.wait_for_load_state("networkidle")

    def ouvrir(self, page, kpi, org=None):
        org = org or self.e1
        page.locator(f'tr.ligne[data-cle="{kpi.code}|{org.id}"]').first.click()
        page.wait_for_selector("body.panneau-ouvert #panneau-contenu form[data-garde]")
        # le panneau montre bien cette case (et pas encore la précédente, sous la suite parallèle)
        page.wait_for_function("(suffixe) => (document.querySelector('#panneau-contenu form[data-garde]')?.getAttribute('action') || '')"
                               ".split('?')[0].endsWith(suffixe)", arg=f"/{org.id}/")
        page.wait_for_function("document.activeElement && document.getElementById('panneau').contains(document.activeElement)")

    def ouvert(self, page):
        return page.evaluate("document.body.classList.contains('panneau-ouvert')")

    def question(self, page):
        return page.locator("#panneau-contenu [data-question]")

    def question_posee(self, page):
        """Question de fermeture affichée (posée après l'essai d'enregistrement automatique, qui est asynchrone)."""
        page.wait_for_selector("#panneau-contenu [data-question]:not([hidden])")
        self.assertTrue(self.question(page).is_visible())

    def choisir(self, page, nom):
        page.locator("#panneau-contenu [data-question]").get_by_role("button", name=nom).click()

    def attendre_fermeture(self, page):
        page.wait_for_function("!document.body.classList.contains('panneau-ouvert')")
        page.wait_for_function("getComputedStyle(document.getElementById('panneau')).visibility === 'hidden'")

    def ecritures(self):
        with _hors_boucle():
            return Reponse.objects.count(), Journal.objects.count()

    def reponse(self, kpi, org=None):
        """(valeur, texte, commentaire, statut, validée par, nombre de preuves) de la case, lus en base."""
        with _hors_boucle():
            r = S.reponse_de(self.c, kpi, org or self.e1)
            return r and (r.valeur, r.texte, r.commentaire, r.statut, r.valide_par_id, r.preuves.count())

    def attendre_reponse(self, page, kpi, org=None):
        """Réponse de la case, attendue en base (envoi en arrière-plan) jusqu'à 30 s : la suite lancée en parallèle
        ralentit le serveur de test (5 s, puis 10 s, ne suffisaient pas toujours sous charge). Lue seulement quand plus aucune requête de la page
        n'est en cours, et jamais pendant que le serveur traite une requête (self.reponse passe par _hors_boucle, donc
        par outils_tests.hors_requete) : sous SQLite en mémoire, le serveur de test et ce fil partagent la même connexion,
        et une lecture faite pendant l'enregistrement voit la ligne déjà créée mais pas encore remplie (valeur None, « à
        saisir » ; la ligne est créée puis verrouillée, saisie.reponse_verrouillee). Le seul suivi des requêtes de la
        page ne suffit pas : Chromium déclare abandonné (net::ERR_ABORTED) l'envoi « keepalive » parti au déchargement de
        la page, que le serveur reçoit et traite pourtant ensuite. wait_for_load_state("networkidle") ne l'attendait pas
        non plus : cet état de chargement de la page est atteint une fois pour toutes, il ne suit pas les fetch partis ensuite."""
        for _ in range(300):
            r = None if page.en_vol else self.reponse(kpi, org)
            if r:
                return r
            page.wait_for_timeout(100)
        self.assertFalse(page.en_vol, "requête encore en cours après 30 s : " + ", ".join(sorted(q.url for q in page.en_vol)))
        return r

    # -- la question --------------------------------------------------------------------------------------------
    def test_fermer_enregistre_le_brouillon_sur_les_trois_pages(self):
        """Brouillon enregistré automatiquement : valeur, N/A seule ou commentaire seul, puis Échap
        ou voile, aussitôt (avant les deux secondes) : enregistré en brouillon, jamais validé, le panneau se ferme sans
        question et le focus revient à la ligne."""
        page = self.page()
        n = 0
        for chemin in (f"/saisie/?org={self.e1.id}", "/pour-moi/?tous=0", "/pour-moi/?tous=1"):
            self.aller(page, chemin)
            for modification, geste in (("valeur", "Escape"), ("na", "voile"), ("commentaire", "Escape")):
                with self.subTest(page=chemin, modification=modification, geste=geste):
                    n += 1
                    self.ouvrir(page, self.nb)
                    if modification == "valeur":
                        if page.locator("#panneau-contenu [name=non_applicable]").is_checked():  # N/A de la page précédente
                            page.locator("#panneau-contenu .na-interrupteur").click()
                        page.locator("#panneau-contenu #valeur").fill(str(1000 + n))
                    elif modification == "na":
                        page.locator("#panneau-contenu .na-interrupteur").click()
                    else:
                        page.locator("#panneau-contenu #commentaire").fill(f"Source : factures {n}")
                    self.assertEqual(page.locator("#panneau-contenu [data-repere]").inner_text(), "Pas encore enregistré")
                    if geste == "Escape":
                        page.keyboard.press("Escape")
                    else:
                        page.mouse.click(10, 450)  # voile, à gauche du panneau
                    self.attendre_fermeture(page)
                    self.assertFalse(self.question(page).is_visible())
                    self.assertEqual(page.evaluate("document.activeElement.dataset.cle"), f"NB|{self.e1.id}")  # focus rendu à la ligne
                    r = self.reponse(self.nb)
                    self.assertIn(r[3], (Reponse.Statut.BROUILLON, Reponse.Statut.A_SAISIR))  # jamais validé
                    if modification == "commentaire":
                        self.assertEqual(r[2], f"Source : factures {n}")
        self.assertEqual((page.dialogues, page.erreurs), ([], []))

    def test_brouillon_enregistre_apres_deux_secondes_puis_annule(self):
        """Deux secondes sans frappe : brouillon enregistré sans déplacer le focus, repère annoncé « Brouillon enregistré à
        HH:MM », pastille et ligne mises à jour, une ligne de journal par enregistrement ; « Annuler mes modifications »
        remet la case comme à l'ouverture (nouvelle ligne, rien n'est retiré du journal). Nombre illisible et séparateur
        ambigu : rien n'est envoyé, le motif reste affiché."""
        page = self.page()
        self.aller(page, "/pour-moi/?tous=0")
        self.ouvrir(page, self.nb)
        repere = page.locator("#panneau-contenu [data-repere]")
        self.assertEqual((repere.get_attribute("role"), page.get_attribute("#panneau-contenu [data-repere-passager]", "aria-hidden")),
                         ("status", "true"))
        page.locator("#panneau-contenu #valeur").press_sequentially("12")
        self.assertEqual(repere.inner_text(), "Pas encore enregistré")  # affiché seulement (aria-hidden), pas annoncé
        self.assertEqual(page.inner_text("#panneau-contenu [data-repere-annonce]"), "")
        page.wait_for_selector("#panneau-contenu [data-repere-annonce]:has-text('Brouillon enregistré à')")
        self.assertRegex(repere.inner_text(), r"^Brouillon enregistré à \d\d:\d\d$")
        self.assertEqual(self.reponse(self.nb)[0::3], (12, Reponse.Statut.BROUILLON))
        self.assertEqual(page.evaluate("document.activeElement.id"), "valeur")  # le focus n'a pas bougé
        self.assertEqual(page.inner_text("#panneau-contenu .statut-panneau .statut"), "Brouillon")
        self.assertIn("statut-brouillon", page.locator(f'tr.ligne[data-cle="NB|{self.e1.id}"]').inner_html())
        page.locator("#panneau-contenu #valeur").press_sequentially("0")
        page.wait_for_function("() => (document.querySelector('#panneau-contenu #valeur').defaultValue === '120')")
        page.wait_for_load_state("networkidle")
        with _hors_boucle():
            r = S.reponse_de(self.c, self.nb, self.e1)
            lignes = [tuple(format(Decimal(t).normalize(), "f") if t else "" for t in x)
                      for x in Journal.objects.filter(objet="Reponse", objet_id=str(r.pk), champ="valeur").order_by("pk").values_list("avant", "apres")]
        self.assertEqual((r.valeur, lignes), (120, [("", "12"), ("12", "120")]))  # une ligne par pause, jamais réécrite
        # annuler : la case revient « à saisir » ; la valeur remise est une ligne de plus (le journal ne fait que grandir)
        annuler = page.get_by_role("button", name="Annuler mes modifications")
        self.assertTrue(annuler.is_visible())
        annuler.click()
        page.wait_for_selector("#panneau-contenu [data-repere-annonce]:has-text('Modifications annulées')")
        self.assertFalse(annuler.is_visible())
        self.assertEqual(page.evaluate("document.activeElement.id"), "valeur")
        self.assertEqual(page.input_value("#panneau-contenu #valeur"), "")
        with _hors_boucle():
            r = S.reponse_de(self.c, self.nb, self.e1)
            self.assertEqual((r.valeur, r.statut), (None, Reponse.Statut.A_SAISIR))
            self.assertEqual([tuple(format(Decimal(t).normalize(), "f") if t else "" for t in x)
                              for x in Journal.objects.filter(objet="Reponse", objet_id=str(r.pk), champ="valeur").order_by("pk")
                              .values_list("avant", "apres")], [("", "12"), ("12", "120"), ("120", "")])
        # pas un nombre : refusé, motif affiché et annoncé, valeur marquée invalide ; il reste (Error-Stays)
        page.fill("#panneau-contenu #valeur", "abc")
        page.wait_for_selector("#panneau-contenu [data-repere-annonce]:has-text('Non enregistré')")
        self.assertIn("Cette valeur n'est pas un nombre", repere.inner_text())
        self.assertEqual(page.get_attribute("#panneau-contenu #valeur", "aria-invalid"), "true")
        page.wait_for_timeout(2500)
        self.assertIn("Cette valeur n'est pas un nombre", repere.inner_text())
        # séparateur ambigu : rien n'est envoyé, le repère dit comment décider
        page.fill("#panneau-contenu #valeur", "1,234")
        page.wait_for_timeout(2500)
        self.assertIn("« 1,234 » peut se lire de deux façons", repere.inner_text())
        self.assertIsNone(self.reponse(self.nb)[0])
        self.assertEqual(page.locator("#panneau-contenu .question-separateur").count(), 0)  # posée seulement en enregistrant
        page.keyboard.press("Escape")
        self.question_posee(page)
        self.choisir(page, "Fermer sans enregistrer")
        self.attendre_fermeture(page)
        self.assertIsNone(self.reponse(self.nb)[0])
        self.assertEqual((page.dialogues, page.erreurs), ([], []))

    def test_question_valeur_validee(self):
        """Valeur validée modifiée (jamais enregistrée automatiquement) : Échap ou voile pose la question, la saisie gardée ;
        elle retient le focus (Tab), Échap ramène au champ ; « Fermer sans enregistrer » n'écrit rien."""
        with _hors_boucle():
            S.enregistrer(self.contrib, self.c, self.nb, self.e1, "10", False, "")
            S.valider(self.contrib, self.c, self.nb, self.e1)
        avant = self.ecritures()
        page = self.page()
        for chemin in (f"/saisie/?org={self.e1.id}", "/pour-moi/?tous=1"):
            self.aller(page, chemin)
            for modification, geste in (("valeur", "Escape"), ("na", "voile"), ("commentaire", "Escape")):
                with self.subTest(page=chemin, modification=modification, geste=geste):
                    self.ouvrir(page, self.nb)
                    champ = page.locator("#panneau-contenu #valeur")
                    if modification == "valeur":
                        champ.fill("1234")
                    elif modification == "na":
                        page.locator("#panneau-contenu .na-interrupteur").click()
                    else:
                        page.locator("#panneau-contenu #commentaire").fill("Source : factures")
                    # dit, et annoncé (région role=status) : rien ne part tant que la personne n'enregistre pas
                    self.assertEqual(page.locator("#panneau-contenu [data-repere]").inner_text(),
                                     "Pas encore enregistré. Une valeur validée ne change que si vous l'enregistrez.")
                    if modification == "valeur" and chemin.startswith("/saisie/"):
                        page.wait_for_timeout(2500)
                        self.assertEqual(self.ecritures(), avant)
                    if geste == "Escape":
                        page.keyboard.press("Escape")
                    else:
                        page.mouse.click(10, 450)  # voile, à gauche du panneau
                    self.question_posee(page)
                    self.assertTrue(self.ouvert(page))
                    self.assertEqual(page.evaluate("document.activeElement.textContent"), "Enregistrer la modification et fermer")
                    self.assertEqual(self.question(page).get_attribute("role"), "alertdialog")
                    for _ in range(3):
                        page.keyboard.press("Tab")
                    self.assertEqual(page.evaluate("document.activeElement.textContent"), "Enregistrer la modification et fermer")
                    # Échap sur la question : retour à la saisie, au champ, rien de perdu
                    page.keyboard.press("Escape")
                    self.assertFalse(self.question(page).is_visible())
                    self.assertTrue(self.ouvert(page))
                    if modification == "valeur":
                        self.assertEqual(page.evaluate("document.activeElement.id"), "valeur")
                        self.assertEqual(champ.input_value(), "1234")
                    elif modification == "na":
                        self.assertTrue(page.locator("#panneau-contenu [name=non_applicable]").is_checked())
                    else:
                        self.assertEqual(page.locator("#panneau-contenu #commentaire").input_value(), "Source : factures")
                    # la croix repose la question ; « Fermer sans enregistrer » ferme sans rien écrire
                    page.locator("#panneau [data-fermer]").click()
                    self.question_posee(page)
                    self.choisir(page, "Fermer sans enregistrer")
                    self.attendre_fermeture(page)
                    self.assertEqual(page.evaluate("document.activeElement.dataset.cle"), f"NB|{self.e1.id}")  # focus rendu à la ligne
        self.assertEqual(self.ecritures(), avant)
        self.assertEqual((page.dialogues, page.erreurs), ([], []))

    def test_sans_modification_fermeture_immediate(self):
        """Nombre, oui / non et liste sans option par défaut : ouvrir puis fermer sans rien changer ne demande rien."""
        page = self.page()
        self.aller(page, "/pour-moi/?tous=0")
        for kpi in (self.nb, self.oui, self.lst):
            for geste in ("Escape", "voile"):
                with self.subTest(kpi=kpi.code, geste=geste):
                    self.ouvrir(page, kpi)
                    self.assertEqual(page.locator("#panneau-contenu [data-repere]").inner_text(), "")
                    if geste == "Escape":
                        page.keyboard.press("Escape")
                    else:
                        page.mouse.click(10, 450)
                    self.attendre_fermeture(page)
                    self.assertFalse(self.question(page).is_visible())
        # un choix dans la liste, puis « — choisir — » à nouveau : rien n'a changé, pas de question
        self.ouvrir(page, self.lst)
        page.select_option("#panneau-contenu #valeur", "Fort")
        self.assertEqual(page.locator("#panneau-contenu [data-repere]").inner_text(), "Pas encore enregistré")
        page.select_option("#panneau-contenu #valeur", "")
        self.assertEqual(page.locator("#panneau-contenu [data-repere]").inner_text(), "")
        page.keyboard.press("Escape")
        self.attendre_fermeture(page)
        self.assertEqual(page.erreurs, [])

    def test_oui_non_enregistre_puis_pleine_page(self):
        """Oui / non choisi puis Échap : enregistré en brouillon, le panneau se ferme, et l'on change d'organisation sans
        « Quitter la page ? ». En pleine page, Échap ne fait rien (pas de croix) ; quitter la page enregistre ce qui peut
        l'être (envoi qui survit à la page), le navigateur n'avertit que pour le reste (nombre illisible) (E4)."""
        page = self.page()
        self.aller(page, f"/saisie/?org={self.e1.id}")
        self.ouvrir(page, self.oui)
        page.locator("#panneau-contenu .puce-reponse").first.click()  # « Oui »
        page.keyboard.press("Escape")
        self.attendre_fermeture(page)
        self.assertEqual(self.attendre_reponse(page, self.oui)[1:4], ("Oui", "", Reponse.Statut.BROUILLON))
        page.evaluate("u => { location.href = u; }", f"/saisie/?org={self.e2.id}")
        page.wait_for_url(f"**/saisie/?org={self.e2.id}")
        self.assertEqual(page.dialogues, [])
        # pleine page
        avant = self.ecritures()
        self.aller(page, f"/saisie/{self.c.pk}/NB/{self.e1.id}/")
        page.fill("#valeur", "abc")
        page.keyboard.press("Escape")
        self.assertFalse(page.locator(".page-cellule [data-fermer]").is_visible())  # pas de croix en pleine page
        self.assertEqual(page.input_value("#valeur"), "abc")
        self.assertFalse(self.question(page).is_visible())
        page.evaluate("u => { location.href = u; }", "/pour-moi/")
        for _ in range(300):  # « Quitter la page ? » attendu (machine lente), pas un délai fixe
            if page.dialogues:
                break
            page.wait_for_timeout(100)
        self.assertEqual(page.dialogues, ["beforeunload"])
        self.assertIn(f"/saisie/{self.c.pk}/NB/", page.url)  # resté sur la page, valeur gardée
        self.assertEqual(self.ecritures(), avant)
        # un nombre : quitter la page l'enregistre en brouillon, sans avertissement
        page.fill("#valeur", "77")
        page.evaluate("u => { location.href = u; }", "/pour-moi/")
        page.wait_for_url("**/pour-moi/")
        self.assertEqual(page.dialogues, ["beforeunload"])
        self.assertEqual(self.attendre_reponse(page, self.nb)[0::3], (77, Reponse.Statut.BROUILLON))

    def test_enregistrer_le_brouillon_et_fermer(self):
        """Fermer enregistre le brouillon (jamais validé) ; refusé (pas un nombre), la question est posée ; son premier
        choix renvoie la saisie : refusée, le panneau reste ouvert, la saisie et l'erreur affichées, et la question revient
        à la fermeture suivante."""
        page = self.page()
        self.aller(page, "/pour-moi/?tous=1")
        self.ouvrir(page, self.nb)
        page.fill("#panneau-contenu #valeur", "42")
        page.mouse.click(10, 450)
        self.attendre_fermeture(page)
        self.assertEqual(self.reponse(self.nb), (42, "", "", Reponse.Statut.BROUILLON, None, 0))
        self.assertIn("statut-brouillon", page.locator(f'tr.ligne[data-cle="NB|{self.e1.id}"]').inner_html())
        # liste : le choix est enregistré tel quel
        self.ouvrir(page, self.lst)
        page.select_option("#panneau-contenu #valeur", "Faible")
        page.keyboard.press("Escape")
        self.attendre_fermeture(page)
        self.assertEqual(self.reponse(self.lst)[1], "Faible")
        # refus du serveur : rien en base, panneau ouvert, saisie et repère gardés
        avant = self.ecritures()
        self.ouvrir(page, self.nb, self.e2)
        page.fill("#panneau-contenu #valeur", "abc")
        page.keyboard.press("Escape")
        self.question_posee(page)
        self.assertEqual(page.locator("#panneau-contenu [data-repere]").inner_text(),
                         "Non enregistré : Cette valeur n'est pas un nombre. Saisissez un nombre.")
        self.choisir(page, "Enregistrer le brouillon et fermer")
        page.wait_for_selector("#panneau-contenu form[data-non-enregistre]")
        self.assertTrue(self.ouvert(page))
        self.assertIn("Cette valeur n'est pas un nombre. Saisissez un nombre.", page.inner_text("#panneau-contenu"))
        self.assertEqual(page.input_value("#panneau-contenu #valeur"), "abc")
        self.assertEqual(page.locator("#panneau-contenu [data-repere]").inner_text(), "Pas encore enregistré")
        self.assertEqual(page.evaluate("document.activeElement.id"), "valeur")  # le focus n'est pas perdu
        # lecteur d'écran : le champ qui a le focus est marqué invalide et décrit par le motif du refus
        focus = page.evaluate("""() => { const c = document.activeElement, d = c.getAttribute('aria-describedby');
            return [c.getAttribute('aria-invalid'), d && document.getElementById(d)?.textContent || ''] }""")
        self.assertEqual(focus[0], "true")
        self.assertIn("Cette valeur n'est pas un nombre. Saisissez un nombre.", focus[1])
        # à l'écran : bord en rouge d'erreur, étiquette « Non enregistré » (rien n'est en base)
        self.assertEqual(page.evaluate("""() => { const t = document.createElement('span'); t.style.color = 'var(--erreur)';
            document.body.append(t); const c = getComputedStyle(t).color; t.remove();
            return getComputedStyle(document.querySelector('#panneau-contenu .champ-valeur')).borderTopColor === c }"""), True)
        self.assertIn("Non enregistré", page.inner_text("#panneau-contenu .points-attention"))
        page.keyboard.press("Escape")
        self.assertTrue(self.question(page).is_visible())
        self.choisir(page, "Fermer sans enregistrer")
        self.attendre_fermeture(page)
        self.assertEqual(self.ecritures(), avant)
        self.assertEqual(page.erreurs, [])

    def test_separateur_ambigu_demande_confirmation(self):
        """« 1,234 » : avant l'envoi, la question « 1 234 ou 1,234 ? » sous la valeur, le focus
        sur la première lecture ; Échap revient au champ sans rien écrire ; le choix réécrit la saisie puis enregistre."""
        avant = self.ecritures()
        page = self.page()
        self.aller(page, "/pour-moi/?tous=0")
        self.ouvrir(page, self.nb)
        page.fill("#panneau-contenu #valeur", "1,234")
        page.locator("#panneau-contenu button[value=enregistrer]").click()
        q = page.locator("#panneau-contenu .question-separateur")
        q.wait_for()
        self.assertIn("1\u202f234 ou 1,234", q.inner_text())
        self.assertEqual(page.evaluate("document.activeElement.dataset.lecture"), "milliers")
        page.keyboard.press("Escape")
        self.assertEqual(q.count(), 0)
        self.assertTrue(self.ouvert(page))
        self.assertEqual(page.evaluate("document.activeElement.id"), "valeur")
        self.assertEqual(self.ecritures(), avant)
        # « 1 234 » : la saisie devient « 1234 », enregistrée
        page.locator("#panneau-contenu button[value=enregistrer]").click()
        page.locator("#panneau-contenu .question-separateur [data-lecture=milliers]").click()
        self.assertEqual(self.attendre_reponse(page, self.nb)[0], 1234)
        # « 1,234 » lu avec sa décimale : enregistré tel quel (décimale de la langue). « Enregistrer » laisse le panneau
        # ouvert : on le ferme (rien n'est en attente) avant d'ouvrir la case suivante
        # la réponse est en base avant que le panneau ait fini de se redessiner : attendre la fin de l'envoi
        page.wait_for_load_state("networkidle")
        page.wait_for_function("!document.querySelector('#panneau-contenu [aria-busy=\"true\"]')")
        if self.ouvert(page):
            page.keyboard.press("Escape")
            self.attendre_fermeture(page)
        self.ouvrir(page, self.nb, self.e2)
        page.fill("#panneau-contenu #valeur", "1,234")
        page.locator("#panneau-contenu button[value=enregistrer]").click()
        page.locator("#panneau-contenu .question-separateur [data-lecture=decimal]").click()
        self.assertEqual(self.attendre_reponse(page, self.nb, self.e2)[0], Decimal("1.234"))
        self.assertEqual(page.erreurs, [])

    def test_conflit_de_version_entree_ne_remplace_rien(self):
        """Une autre personne enregistre la case pendant la saisie : l'enregistrement est refusé (version) ; la croix pose
        la question, qui le dit, avec le focus sur « Fermer sans enregistrer » : Entrée ferme et garde sa valeur."""
        page = self.page()
        self.aller(page, f"/saisie/?org={self.e1.id}")
        self.ouvrir(page, self.nb)
        with _hors_boucle():
            S.enregistrer(self.admin, self.c, self.nb, self.e1, "1111", False, "")  # l'admin, au même moment
        page.fill("#panneau-contenu #valeur", "2222")
        page.locator("#panneau-contenu button[value=enregistrer]").click()
        page.wait_for_selector("#panneau-contenu form[data-non-enregistre]")
        self.assertIn("vient d'être modifiée", page.inner_text("#panneau-contenu"))
        self.assertEqual(self.reponse(self.nb)[0], 1111)
        page.locator("#panneau [data-fermer]").click()
        self.assertTrue(self.question(page).is_visible())
        self.assertIn("Si vous enregistrez, votre valeur remplace la sienne", self.question(page).inner_text())
        self.assertEqual(self.question(page).locator("button").all_inner_texts(),
                         ["Fermer sans enregistrer", "Remplacer par ma saisie et fermer", "Continuer la saisie"])
        self.assertEqual(page.evaluate("document.activeElement.textContent"), "Fermer sans enregistrer")
        page.keyboard.press("Enter")
        self.attendre_fermeture(page)
        self.assertEqual(self.reponse(self.nb)[0], 1111)  # la valeur de l'autre personne est gardée
        # en connaissance de cause : « Remplacer par ma saisie et fermer » enregistre la sienne (règle de version inchangée)
        self.ouvrir(page, self.nb)
        with _hors_boucle():
            S.enregistrer(self.admin, self.c, self.nb, self.e1, "1112", False, "")
        page.fill("#panneau-contenu #valeur", "2222")
        page.locator("#panneau-contenu button[value=enregistrer]").click()
        page.wait_for_selector("#panneau-contenu form[data-non-enregistre]")
        page.keyboard.press("Escape")
        self.choisir(page, "Remplacer par ma saisie et fermer")
        self.attendre_fermeture(page)
        self.assertEqual(self.reponse(self.nb)[0], 2222)
        self.assertEqual((page.dialogues, page.erreurs), ([], []))

    def test_question_depuis_un_lien_du_panneau(self):
        """Un lien du panneau (alerte, composante) ouvre un autre panneau : la question le dit (« … et ouvrir le lien ») ;
        fermer ensuite revient aux libellés « … et fermer »."""
        page = self.page()
        self.aller(page, "/pour-moi/?tous=1")
        self.ouvrir(page, self.nb)
        page.evaluate("""(href) => { const a = document.createElement('a'); a.href = href; a.dataset.panneau = '';
            a.id = 'lien-essai'; a.textContent = 'Autre case'; document.querySelector('#panneau-contenu h2').after(a); }""",
                      page.evaluate("(c) => document.querySelector(`tr.ligne[data-cle='${c}']`).dataset.url", f"LST|{self.e1.id}"))
        page.fill("#panneau-contenu #valeur", "abc")  # pas un nombre : l'enregistrement automatique est refusé
        page.click("#lien-essai")
        self.question_posee(page)
        noms = self.question(page).locator("button").all_inner_texts()
        self.assertEqual(noms, ["Enregistrer le brouillon et ouvrir le lien", "Ouvrir le lien sans enregistrer", "Continuer la saisie"])
        self.choisir(page, "Ouvrir le lien sans enregistrer")
        page.wait_for_selector("#panneau-contenu select#valeur")
        self.assertEqual(self.ecritures(), (0, 0))
        # le libellé « … et fermer » revient (valeur validée : la question est posée)
        with _hors_boucle():
            S.enregistrer(self.contrib, self.c, self.lst, self.e1, "Faible", False, "")
            S.valider(self.contrib, self.c, self.lst, self.e1)
        self.aller(page, "/pour-moi/?tous=1")
        self.ouvrir(page, self.lst)
        page.select_option("#panneau-contenu #valeur", "Fort")
        page.keyboard.press("Escape")
        self.question_posee(page)
        self.assertEqual(self.question(page).locator("button").first.inner_text(), "Enregistrer la modification et fermer")
        self.choisir(page, "Fermer sans enregistrer")
        self.attendre_fermeture(page)
        self.assertEqual(self.reponse(self.lst)[1], "Faible")
        # un nombre : enregistré, puis le lien s'ouvre, sans question
        self.ouvrir(page, self.nb)
        page.evaluate("""(href) => { const a = document.createElement('a'); a.href = href; a.dataset.panneau = '';
            a.id = 'lien-essai'; a.textContent = 'Autre case'; document.querySelector('#panneau-contenu h2').after(a); }""",
                      page.evaluate("(c) => document.querySelector(`tr.ligne[data-cle='${c}']`).dataset.url", f"OUI|{self.e1.id}"))
        page.fill("#panneau-contenu #valeur", "7")
        page.click("#lien-essai")
        page.wait_for_selector("#panneau-contenu .choix-reponse")
        self.assertFalse(self.question(page).first.is_visible())
        self.assertEqual(self.reponse(self.nb)[0::3], (7, Reponse.Statut.BROUILLON))
        self.assertEqual(page.erreurs, [])

    def test_valeur_validee_modifiee_puis_preuve_puis_enregistrement(self):
        """La valeur tapée survit au dépôt d'une preuve et à « Rouvrir la saisie » (E5) ; l'enregistrement qui suit ne
        bute pas sur la version (la preuve a changé la date de mise à jour)."""
        for k, v in ((self.nb, "10"), (self.lst, "Faible")):
            S.enregistrer(self.contrib, self.c, k, self.e1, v, False, "")
            S.valider(self.contrib, self.c, k, self.e1)
        page = self.page()
        self.aller(page, f"/saisie/?org={self.e1.id}")
        self.ouvrir(page, self.nb)
        self.assertIn("Enregistrer la modification et fermer", self.question(page).inner_text())
        page.fill("#panneau-contenu #valeur", "12")
        page.fill("#panneau-contenu #commentaire", "Recompté")
        page.set_input_files("#panneau-contenu [data-depot]", files=[{"name": "preuve.pdf", "mimeType": "application/pdf", "buffer": PDF}])
        page.locator("#panneau-contenu button[value=preuve]").click()
        page.wait_for_selector("#panneau-contenu .preuve-ligne")
        self.assertEqual(page.input_value("#panneau-contenu #valeur"), "12")
        self.assertEqual(page.input_value("#panneau-contenu #commentaire"), "Recompté")
        self.assertEqual(self.reponse(self.nb)[3:], (Reponse.Statut.BROUILLON, None, 1))  # la preuve a repassé la valeur en brouillon
        # brouillon désormais : la saisie gardée peut s'enregistrer automatiquement ; « Enregistrer » attend cet envoi
        # (sa version) au lieu de buter sur un conflit avec soi-même
        page.locator("#panneau-contenu button[value=enregistrer]").click()
        page.wait_for_selector("#panneau-contenu .encart-succes:has-text('Brouillon enregistré')")  # {% encart "succes" %}
        self.assertNotIn("vient d'être modifiée", page.inner_text("#panneau-contenu"))
        self.assertEqual(self.reponse(self.nb), (12, "", "Recompté", Reponse.Statut.BROUILLON, None, 1))
        self.assertEqual(page.locator("#panneau-contenu [data-repere]").inner_text(), "")
        page.keyboard.press("Escape")
        self.attendre_fermeture(page)
        # « Rouvrir la saisie » d'une valeur validée garde la valeur tapée (E5)
        self.ouvrir(page, self.lst)
        page.select_option("#panneau-contenu #valeur", "Fort")
        page.locator("#panneau-contenu button[value=brouillon]").click()
        page.wait_for_selector("#panneau-contenu .statut-brouillon")
        self.assertEqual(page.input_value("#panneau-contenu #valeur"), "Fort")
        self.assertEqual(self.reponse(self.lst)[1:4], ("Faible", "", Reponse.Statut.BROUILLON))
        # rouverte en brouillon : la saisie gardée s'enregistre en fermant, sans question
        page.keyboard.press("Escape")
        self.attendre_fermeture(page)
        self.assertEqual(self.reponse(self.lst)[1:4], ("Fort", "", Reponse.Statut.BROUILLON))
        self.assertEqual(page.erreurs, [])

    def test_telephone_retour_et_lien_du_panneau(self):
        """390 px : le retour referme le panneau sans quitter la page (question d'abord si besoin) ; après « Régler ce
        KPI », un seul retour ramène à la saisie."""
        page = self.page(largeur=390)
        self.aller(page, "/pour-moi/?tous=0")
        url = page.url
        self.ouvrir(page, self.nb)
        page.go_back()
        self.attendre_fermeture(page)
        self.assertEqual(page.url, url)
        # saisie en cours : le retour pose la question ; « Continuer » puis retour la repose ; « Fermer sans enregistrer »
        self.ouvrir(page, self.nb)
        page.fill("#panneau-contenu #valeur", "9 kg")  # refusée : la question est posée
        page.go_back()
        page.wait_for_selector("#panneau-contenu [data-question]:not([hidden])")
        self.assertTrue(self.ouvert(page))
        self.assertEqual(page.url, url)
        boutons = self.question(page).locator("button")
        self.assertGreaterEqual(min(boutons.nth(i).bounding_box()["height"] for i in range(3)), 44)
        self.choisir(page, "Continuer la saisie")
        self.assertEqual(page.input_value("#panneau-contenu #valeur"), "9 kg")
        page.go_back()
        page.wait_for_selector("#panneau-contenu [data-question]:not([hidden])")
        # second retour pendant la question : elle reste posée, la page n'est pas quittée (sans « Quitter la page ? »,
        # absent de Safari sur iPhone)
        page.go_back()
        page.wait_for_timeout(300)
        self.assertTrue(self.ouvert(page))
        self.assertTrue(self.question(page).is_visible())
        self.assertEqual(page.url, url)
        self.assertEqual(page.input_value("#panneau-contenu #valeur"), "9 kg")
        self.assertEqual(page.dialogues, [])
        self.choisir(page, "Fermer sans enregistrer")
        self.attendre_fermeture(page)
        self.assertEqual(page.url, url)
        self.assertEqual(self.ecritures(), (0, 0))
        # admin : lien ordinaire du panneau, puis un seul retour
        page = self.page(self.admin, largeur=390)
        self.aller(page, "/tableau-de-bord/")
        self.aller(page, f"/saisie/?org={self.e1.id}")
        url = page.url
        self.ouvrir(page, self.nb)
        page.get_by_role("link", name="Régler ce KPI dans le référentiel").click()
        page.wait_for_url("**/referentiel/**")
        page.go_back()
        page.wait_for_url(url)
        page.wait_for_load_state("networkidle")
        self.assertEqual(page.url, url)
        # historique et panneau d'accord : un retour de plus ferme le panneau s'il est resté ouvert, sinon quitte la saisie
        etat = page.evaluate("({ouvert: document.body.classList.contains('panneau-ouvert'), entree: Boolean(history.state && history.state.panneauSaisie)})")
        self.assertEqual(etat["ouvert"], etat["entree"])
        if etat["ouvert"]:  # page reprise du cache de retour, panneau ouvert : le retour suivant le referme
            page.go_back()
            self.attendre_fermeture(page)
        page.go_back()  # puis quitte la saisie : pas d'entrée fantôme laissée par le panneau
        page.wait_for_url("**/tableau-de-bord/")
        self.assertEqual((page.dialogues, page.erreurs), ([], []))

    # -- justifier une alerte dans le panneau (étape 4) ------------------------------------------------------------
    def test_justifier_dans_le_panneau_et_explication_protegee(self):
        """« Justifier » du bandeau ouvre la première ligne en alerte, sur son champ d'explication ; le constat se lit dans
        la liste ; une explication tapée puis Échap pose la question adaptée (« Enregistrer l'explication et fermer /
        Fermer sans l'enregistrer / Continuer ») et l'explication est gardée ; avec une valeur aussi tapée, la question de
        la saisie prévient que l'explication serait perdue ; enregistrée, l'alerte est justifiée et la ligne n'est plus
        « à vérifier »."""
        from .models import Alerte

        for k, v in ((self.nb, "42"), (self.oui, "oui"), (self.lst, "Faible")):  # tout est saisi à Lille (import : sans contrôle)
            Reponse.objects.create(periode=self.c.periode, kpi=k, organisation=self.e1, valeur=Decimal(v) if k is self.nb else None,
                                   texte="" if k is self.nb else v, statut=Reponse.Statut.VALIDE, origine=Reponse.Origine.IMPORT)
        a = Alerte.objects.create(campagne=self.c, kpi=self.nb, organisation=self.e1, controle=Alerte.Controle.HISTORIQUE,
                                  message="42 salariés, contre environ 3 480 salariés d'habitude (médiane des 5 exercices "
                                          "précédents) : 83 fois moins.", valeur="42 salariés", reference="médiane : 3 480 salariés")
        page = self.page()
        self.aller(page, f"/saisie/?org={self.e1.id}")
        ligne = page.locator(f'tr.ligne[data-cle="NB|{self.e1.id}"]')
        self.assertIn("contre environ 3 480 salariés d'habitude", ligne.locator(".constat-ligne").inner_text())
        self.assertIn("À vérifier", ligne.locator(".badge-alerte").inner_text())
        page.locator("#resume [data-justifier]").click()
        page.wait_for_selector("body.panneau-ouvert #panneau-contenu [data-justification]")
        self.assertEqual(page.evaluate("document.activeElement.name"), "justification")
        explication = page.locator(f"#justif-{a.pk}")
        explication.fill("Inventaire refait en mars")
        question = page.locator("#panneau-contenu [data-question-explication]")
        page.keyboard.press("Escape")
        self.assertTrue(question.is_visible())
        self.assertEqual(question.get_attribute("role"), "alertdialog")
        self.assertEqual(question.locator("button").all_inner_texts(),
                         ["Enregistrer l'explication et fermer", "Fermer sans l'enregistrer", "Continuer"])
        self.assertEqual(page.evaluate("document.activeElement.textContent"), "Enregistrer l'explication et fermer")
        page.keyboard.press("Escape")  # retour à l'explication, rien de perdu
        self.assertFalse(question.is_visible())
        self.assertEqual(page.evaluate("document.activeElement.id"), f"justif-{a.pk}")
        self.assertEqual(explication.input_value(), "Inventaire refait en mars")
        # valeur et explication tapées : la question de la saisie dit que l'explication serait perdue
        page.fill("#panneau-contenu #valeur", "43")
        page.locator("#panneau [data-fermer]").click()
        saisie = page.locator("#panneau-contenu [data-question]:not([data-question-explication])")
        self.assertTrue(saisie.is_visible())
        self.assertTrue(saisie.locator("[data-explication-perdue]").is_visible())
        # la phrase est lue avec la question (lecteur d'écran), et seulement quand une explication serait perdue
        self.assertEqual(saisie.get_attribute("aria-describedby"), "question-fermeture-detail question-fermeture-explication")
        self.assertEqual(page.evaluate("document.activeElement.textContent"), "Enregistrer la modification et fermer")
        saisie.get_by_role("button", name="Continuer la saisie").click()
        explication.fill("")  # explication effacée : la question de la saisie ne parle plus d'elle
        page.keyboard.press("Escape")
        self.assertTrue(saisie.is_visible())
        self.assertFalse(saisie.locator("[data-explication-perdue]").is_visible())
        self.assertEqual(saisie.get_attribute("aria-describedby"), "question-fermeture-detail")  # valeur validée : reste dit
        saisie.get_by_role("button", name="Continuer la saisie").click()
        explication.fill("Inventaire refait en mars")
        page.fill("#panneau-contenu #valeur", "42")  # valeur remise : seule l'explication reste à enregistrer
        page.mouse.click(10, 450)  # voile
        self.assertTrue(question.is_visible())
        self.assertEqual(self.ecritures(), (3, 0))
        question.get_by_role("button", name="Enregistrer l'explication et fermer").click()
        self.attendre_fermeture(page)
        with _hors_boucle():
            a.refresh_from_db()
        self.assertEqual((a.statut, a.justification), (Alerte.Statut.JUSTIFIEE, "Inventaire refait en mars"))
        page.wait_for_function(f"!document.querySelector('tr.ligne[data-cle=\"NB|{self.e1.id}\"] .badge-alerte')")
        self.assertEqual(self.reponse(self.nb)[0], 42)  # la saisie n'a pas bougé
        self.assertEqual((page.dialogues, page.erreurs), ([], []))

    def test_justifier_curseur_a_la_fin_de_la_proposition(self):
        """Explication proposée à partir du commentaire de la saisie : « Justifier » met le focus dans le champ avec le
        curseur à la fin, et le texte tapé s'ajoute après la proposition (et non devant)."""
        from .models import Alerte

        for k, v in ((self.nb, "42"), (self.oui, "oui"), (self.lst, "Faible")):
            Reponse.objects.create(periode=self.c.periode, kpi=k, organisation=self.e1, valeur=Decimal(v) if k is self.nb else None,
                                   texte="" if k is self.nb else v, statut=Reponse.Statut.VALIDE, origine=Reponse.Origine.IMPORT,
                                   commentaire="Valeur vérifiée." if k is self.nb else "")
        a = Alerte.objects.create(campagne=self.c, kpi=self.nb, organisation=self.e1, controle=Alerte.Controle.HISTORIQUE,
                                  message="42 salariés, contre environ 3 480 salariés d'habitude (médiane des 5 exercices "
                                          "précédents) : 83 fois moins.", valeur="42 salariés", reference="médiane : 3 480 salariés")
        page = self.page()
        self.aller(page, f"/saisie/?org={self.e1.id}")
        page.locator("#resume [data-justifier]").click()
        page.wait_for_selector("body.panneau-ouvert #panneau-contenu [data-justification]")
        self.assertEqual(page.evaluate("document.activeElement.id"), f"justif-{a.pk}")
        self.assertEqual(page.evaluate("[document.activeElement.selectionStart, document.activeElement.value.length]"), [16, 16])
        page.keyboard.type(" Inventaire refait.")
        self.assertEqual(page.locator(f"#justif-{a.pk}").input_value(), "Valeur vérifiée. Inventaire refait.")
        self.assertEqual(page.erreurs, [])

    def test_justifier_puis_message_avec_le_focus(self):
        """Le bouton « Enregistrer l'explication » enregistre sans quitter la saisie et met le focus sur le message ; vide,
        l'erreur s'affiche sous le champ, qui garde le focus."""
        from .models import Alerte

        a = Alerte.objects.create(campagne=self.c, kpi=self.nb, organisation=self.e1, controle=Alerte.Controle.FORMAT,
                                  message="Valeur négative.", valeur="-5 salariés")
        page = self.page()
        self.aller(page, "/pour-moi/?tous=0")
        self.ouvrir(page, self.nb)
        page.locator("#panneau-contenu #valeur").fill("12")  # valeur tapée : gardée pendant l'explication
        bouton = page.locator("#panneau-contenu [data-justification] button[value=justifier]")
        bouton.click()
        page.wait_for_selector(f"#justif-{a.pk}[aria-invalid=true]")
        self.assertEqual(page.evaluate("document.activeElement.id"), f"justif-{a.pk}")
        self.assertEqual(page.input_value("#panneau-contenu #valeur"), "12")
        page.fill(f"#justif-{a.pk}", "Avoir sur facture")
        page.locator("#panneau-contenu [data-justification] button[value=justifier]").click()
        page.wait_for_selector("#panneau-contenu [data-message-justif]")
        self.assertEqual(page.evaluate("document.activeElement.dataset.messageJustif"), "")
        self.assertIn("Explication enregistrée", page.evaluate("document.activeElement.textContent"))
        self.assertEqual(page.input_value("#panneau-contenu #valeur"), "12")
        with _hors_boucle():
            a.refresh_from_db()
        self.assertEqual(a.statut, Alerte.Statut.JUSTIFIEE)
        page.keyboard.press("Escape")  # la valeur gardée s'enregistre en brouillon en fermant
        self.attendre_fermeture(page)
        self.assertEqual(self.reponse(self.nb)[0::3], (12, Reponse.Statut.BROUILLON))
        self.assertEqual(page.erreurs, [])

    # -- accessibilité et téléphone (étape 6) ---------------------------------------------------------------------
    def test_accessibilite_clavier_titres_annonces_et_telephone(self):
        """Lien « Aller au contenu » en premier, Entrée met le focus sur le contenu ; titres de section dans l'arbre
        d'accessibilité (niveau 2 sur Saisie, 3 sous un référentiel) ; pastilles avec aria-pressed et nombre de lignes
        annoncé au filtrage, jamais après un enregistrement ; marge de 16 px et aucun défilement horizontal à 390 et
        768 px ; libellés Import / Export et Administration visibles à 1 440 px ; zones à toucher de 24 px."""
        page = self.page()
        self.aller(page, f"/saisie/?org={self.e1.id}")
        page.keyboard.press("Tab")
        self.assertEqual(page.evaluate("document.activeElement.textContent"), "Aller au contenu")
        page.keyboard.press("Enter")
        self.assertEqual(page.evaluate("document.activeElement.id"), "contenu")
        # second lien : « Aller aux KPI », puis la première ligne en 2 tabulations (summary, ligne)
        self.aller(page, f"/saisie/?org={self.e1.id}")
        for _ in range(2):
            page.keyboard.press("Tab")
        self.assertEqual(page.evaluate("document.activeElement.textContent"), "Aller aux KPI")
        page.keyboard.press("Enter")
        self.assertEqual(page.evaluate("document.activeElement.id"), "liste")
        for attendu in ("SUMMARY", "TR"):
            page.keyboard.press("Tab")
            self.assertEqual(page.evaluate("document.activeElement.tagName"), attendu)
        self.assertTrue(page.evaluate("document.activeElement.matches('tr.ligne')"))
        self.assertIn('heading "Social" [level=2]', page.locator("#liste").aria_snapshot())
        self.assertEqual(page.input_value("#recherche"), "")
        self.assertEqual(page.locator("#annonce-filtres").text_content(), "")  # rien d'annoncé au chargement
        page.locator("[data-filtre-statut=a_saisir]").click()
        self.assertEqual(page.locator("[data-filtre-statut=a_saisir]").get_attribute("aria-pressed"), "true")
        self.assertEqual(page.locator("[data-filtre-statut='']").get_attribute("aria-pressed"), "false")
        page.wait_for_function("document.getElementById('annonce-filtres').textContent === '3 KPI affichés'")
        # même nombre une seconde fois : la zone est vidée puis réécrite, pour que le lecteur d'écran le relise
        page.evaluate("""() => { window.__annonces = []; new MutationObserver(() => window.__annonces.push(
            document.getElementById('annonce-filtres').textContent)).observe(document.getElementById('annonce-filtres'), {childList: true}); }""")
        page.locator("[data-filtre-statut=a_saisir]").click()
        page.wait_for_function("window.__annonces.length >= 2")
        self.assertEqual(page.evaluate("window.__annonces"), ["", "3 KPI affichés"])
        page.locator("#recherche").fill("zzz")
        page.wait_for_function("document.getElementById('annonce-filtres').textContent.startsWith('Aucun')")
        # enregistrement : le bandeau et la liste sont relus, sans annonce de filtre
        self.aller(page, f"/saisie/?org={self.e1.id}")
        self.ouvrir(page, self.nb)
        page.locator("#panneau-contenu #valeur").fill("12")
        page.locator("#panneau-contenu .actions button[value=enregistrer]").click()
        page.wait_for_selector(f'tr.ligne[data-cle="NB|{self.e1.id}"][data-statut=brouillon]')
        page.wait_for_timeout(800)
        self.assertEqual(page.locator("#annonce-filtres").text_content(), "")
        self.assertEqual(page.locator("[data-filtre-statut='']").get_attribute("aria-pressed"), "true")  # bandeau relu
        # Tous mes référentiels : h3 sous le h2 de chaque référentiel
        self.aller(page, "/pour-moi/?tous=1")
        arbre = page.locator("#liste").aria_snapshot()
        self.assertIn("[level=3]", arbre)
        self.assertNotIn('heading "Social" [level=2]', arbre)
        self.assertEqual(page.erreurs, [])
        # téléphone et tablette : marge de 16 px, aucun défilement horizontal
        for utilisateur in (self.contrib, self.admin):
            for largeur in (390, 768):
                p = self.page(utilisateur, largeur)
                for chemin in ("/saisie/", "/pour-moi/", "/tableau-de-bord/"):
                    with self.subTest(utilisateur=utilisateur.username, largeur=largeur, page=chemin):
                        self.aller(p, chemin)
                        self.assertEqual(p.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth"), 0)
                        self.assertEqual(p.evaluate("getComputedStyle(document.querySelector('main')).paddingLeft"), "16px")
                if largeur == 390 and utilisateur == self.admin:
                    self.aller(p, "/tableau-de-bord/")
                    # une colonne masquée ne garde aucune largeur : chaque tableau reste dans la marge de sa carte
                    debords = p.evaluate("""() => [...document.querySelectorAll('.carte table')].map(t => { const c = t.closest('.carte'),
                        st = getComputedStyle(c); return t.getBoundingClientRect().right - (c.getBoundingClientRect().right
                        - parseFloat(st.borderRightWidth) - parseFloat(st.paddingRight)); })""")
                    self.assertTrue(debords)
                    self.assertLessEqual(max(debords), 0.5)
                    # colonne « Indicateur » de Saisie : case, valeur, statut et SPOC lui laissent 72 px au moins
                    self.aller(p, "/saisie/")
                    indicateur = p.evaluate("""() => [...document.querySelectorAll('#liste table.cellules thead th')]
                        .find(t => /Indicateur/.test(t.textContent)).getBoundingClientRect().width""")
                    self.assertGreaterEqual(indicateur, 72)
                    self.aller(p, "/tableau-de-bord/")
                    # liens des lignes visibles (les lignes repliées de l'arbre n'ont pas de zone à toucher)
                    hauteurs = p.evaluate("[...document.querySelectorAll('td.retrait-arbre a')].filter(a => a.offsetParent).map(a => a.getBoundingClientRect().height)")
                    self.assertTrue(hauteurs)
                    self.assertGreaterEqual(min(hauteurs), 24)
        # grand écran : libellés des onglets à icône visibles
        p = self.page(self.admin, 1440)
        self.aller(p, "/saisie/")
        self.assertEqual(p.evaluate("[...document.querySelectorAll('nav.onglets .libelle-onglet')].map(l => l.offsetWidth > 0)"), [True, True])

    def test_bandeau_avec_un_nom_d_outil_long_et_ecart_sous_la_valeur(self):
        """E15 : avec un nom d'outil de 60 caractères (le plus long accepté), les onglets ne débordent pas (nom coupé par
        « … », puis nom du compte et libellés des onglets à icône retirés au besoin, serrerOnglets) ; avec le nom par
        défaut, les libellés restent visibles jusqu'à 1 600 px. E13 : un écart au-delà du seuil se lit sous la valeur à
        768 px (sa colonne est masquée), pas à 1 440 px (il est dans sa colonne)."""
        from parametres.models import Instance

        for largeur in (1440, 1536, 1600):
            p = self.page(self.admin, largeur)
            for chemin in ("/saisie/", "/administration/"):
                with self.subTest(largeur=largeur, page=chemin, nom="par défaut"):
                    self.aller(p, chemin)
                    self.assertEqual(p.evaluate("(n => n.scrollWidth - n.clientWidth)(document.querySelector('nav.onglets'))"), 0)
                    self.assertEqual(p.evaluate("[...document.querySelectorAll('nav.onglets .libelle-onglet')].map(l => l.offsetWidth > 0)"), [True, True])
        # tablette (801 à 1 024 px) : les onglets qui ne tiennent pas passent sur leur propre rangée, jamais coupés
        for utilisateur in (self.contrib, self.admin):
            for largeur in (820, 900, 1024):
                p = self.page(utilisateur, largeur)
                with self.subTest(utilisateur=utilisateur.username, largeur=largeur, nom="par défaut"):
                    self.aller(p, "/tableau-de-bord/")
                    self.assertEqual(p.evaluate("(n => n.scrollWidth - n.clientWidth)(document.querySelector('nav.onglets'))"), 0)
                    self.assertEqual(p.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth"), 0)
        with _hors_boucle():
            i = Instance.courante()
            i.titre = "Outil de reporting des indicateurs du groupe Essai France"
            i.save()
        for largeur in (820, 900, 1024, 1100, 1340, 1440, 1536, 1600, 1920):
            p = self.page(self.admin, largeur)
            for chemin in ("/saisie/", "/administration/"):
                with self.subTest(largeur=largeur, page=chemin, nom="60 caractères"):
                    self.aller(p, chemin)
                    self.assertEqual(p.evaluate("(n => n.scrollWidth - n.clientWidth)(document.querySelector('nav.onglets'))"), 0)
        # écart sous la valeur : N-1 à 10, 20 cette année, seuil de 20 %
        with _hors_boucle():
            avant = Campagne.objects.create(referentiel=self.c.referentiel, exercice=2025, statut=Campagne.Statut.CLOTUREE)
            Reponse.objects.create(periode=avant.periode, kpi=self.nb, organisation=self.e1, valeur=Decimal(10),
                                   statut=Reponse.Statut.VALIDE, origine=Reponse.Origine.IMPORT)
            Reponse.objects.create(periode=self.c.periode, kpi=self.nb, organisation=self.e1, valeur=Decimal(20),
                                   statut=Reponse.Statut.VALIDE, origine=Reponse.Origine.IMPORT)
            self.c.seuil_ecart = Decimal("0.2")
            self.c.save()
        for largeur, visible in ((768, True), (1440, False)):
            p = self.page(self.contrib, largeur)
            self.aller(p, f"/saisie/?org={self.e1.id}")
            with self.subTest(largeur=largeur):
                ecart = p.locator(f'tr.ligne[data-cle="NB|{self.e1.id}"] .ecart-sous')
                self.assertEqual(ecart.count(), 1)
                self.assertEqual(ecart.evaluate("e => e.offsetParent !== null"), visible)
        self.assertIn("+100,0\u202f%", ecart.text_content())
        self.assertEqual(p.erreurs, [])

    def test_telephone_barre_du_haut_avec_deux_espaces(self):
        """Constat : avec deux espaces, le sélecteur d'espace poussait la barre du haut hors de
        l'écran du téléphone (26 px à 375 px, déconnexion coupée). Elle tient désormais de 320 à 414 px : le nom de
        l'espace se raccourcit (« … »), le bouton garde sa zone à toucher de 44 px."""
        from espaces.models import AccesEspace, Espace

        with _hors_boucle():
            for rang, (code, nom) in enumerate((("principal", "Espace principal"), ("achatstest", "Achats Test"))):
                e = Espace.objects.create(code=code, nom=nom, etat="actif", rang=rang)
                AccesEspace.objects.create(compte_id=self.admin.pk, espace=e, role="admin")
        for largeur in (320, 360, 375, 390, 414):
            p = self.page(self.admin, largeur)
            for chemin in ("/saisie/", "/administration/"):
                with self.subTest(largeur=largeur, page=chemin):
                    self.aller(p, chemin)
                    self.assertEqual(p.locator(".bouton-espace").count(), 1)
                    self.assertEqual(p.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth"), 0)
                    droite = p.evaluate("""() => Math.max(...[...document.querySelectorAll('.compte-haut > *')]
                        .map(e => e.getBoundingClientRect().right))""")
                    self.assertLessEqual(droite, largeur)
                    self.assertGreaterEqual(p.evaluate("document.querySelector('.bouton-espace').getBoundingClientRect().width"), 44)
        self.assertEqual(p.erreurs, [])

    def test_telephone_onglet_actif_visible(self):
        """Constat : sur téléphone, la barre d'onglets défile mais restait au début ; l'onglet de la
        page en cours (Cohérence, Import / Export, Administration, Visualisation) était hors de l'écran. Il est
        maintenant amené dans la partie visible de la barre au chargement."""
        for largeur in (360, 390):
            p = self.page(self.admin, largeur)
            for chemin in ("/saisie/", "/visualisation/", "/coherence/", "/import-export/", "/administration/"):
                with self.subTest(largeur=largeur, page=chemin):
                    self.aller(p, chemin)
                    nav, actif = p.evaluate("""() => { const n = document.querySelector('nav.onglets'), a = n.querySelector('a.actif');
                        const r = e => { const b = e.getBoundingClientRect(); return [b.left, b.right]; };
                        return [r(n), a ? r(a) : null]; }""")
                    self.assertIsNotNone(actif)
                    self.assertGreaterEqual(actif[0], nav[0] - 0.5)
                    self.assertLessEqual(actif[1], nav[1] + 0.5)
        # barre ramenée au début à la main, puis seule la hauteur change (barre d'adresse du téléphone) : rien ne bouge
        p.evaluate("document.querySelector('nav.onglets').scrollLeft = 0")
        p.set_viewport_size({"width": 390, "height": 700})
        p.wait_for_timeout(100)
        self.assertEqual(p.evaluate("document.querySelector('nav.onglets').scrollLeft"), 0)
        self.assertEqual(p.erreurs, [])

    def test_pastille_de_statut_entiere_dans_sa_cellule_en_trois_langues(self):
        """Constat : en espagnol, la pastille « Por capturar » (KPI à saisir) était coupée au bord
        droit de sa cellule sur téléphone et à 768 px, et chevauchait l'avatar voisin. Elle passe maintenant à la ligne
        si le libellé est plus long que la colonne, en français, en anglais et en espagnol."""
        from parametres.models import Langue

        with _hors_boucle():
            Langue.objects.get_or_create(code="es", defaults={"libelle": "Español", "ordre": 3})
            Langue.objects.get_or_create(code="en", defaults={"libelle": "English", "ordre": 2})
        for langue in ("fr", "en", "es"):
            with _hors_boucle():
                Utilisateur.objects.filter(pk=self.contrib.pk).update(langue=langue)
            for largeur in (320, 390, 768):
                p = self.page(self.contrib, largeur)
                self.aller(p, "/saisie/")
                with self.subTest(langue=langue, largeur=largeur):
                    self.assertEqual(p.evaluate("document.documentElement.lang"), langue)
                    debords = p.evaluate("""() => [...document.querySelectorAll('table.cellules td .statut')].filter(s => s.offsetParent)
                        .map(s => { const td = s.closest('td'), r = td.getBoundingClientRect(), b = s.getBoundingClientRect();
                            return [s.textContent.trim(), b.right - (r.right - parseFloat(getComputedStyle(td).paddingRight)), td.scrollWidth - td.clientWidth]; })
                        .filter(([, d, s]) => d > 0.5 || s > 0)""")
                    self.assertEqual(debords, [])
                p.context.close()
        self.assertEqual(p.erreurs, [])

    def test_ecart_mensuel_sous_la_valeur_sur_telephone(self):
        """E13, référentiel mensuel : la comparaison est un mois (« vs septembre 2026 ») ; sur téléphone, l'écart et sa
        comparaison se lisent en entier dans la colonne Valeur (le mois passe à la ligne au lieu d'être coupé)."""
        from .periodes import campagne as campagne_de

        with _hors_boucle():
            mensuel = Referentiel.objects.create(code="MOIS", nom="Électricité", ordre=3, frequence="mois", comparaison="P-1")
            elm = KPI.objects.create(code="ELM", libelle="Électricité consommée", type_saisie_id="Saisi",
                                     granularite_id=Niveau.ENTITY, methode_agregation="Somme")
            composer({"ELM": ["Consommations"]}, mensuel)
            Attribution.objects.create(kpi=elm, organisation=self.e1, utilisateur=self.contrib)
            fin = timezone.localdate() + datetime.timedelta(days=30)
            septembre, _ = campagne_de(mensuel, datetime.date(2026, 9, 1), statut=Campagne.Statut.CLOTUREE, date_fin_saisie=fin)
            octobre, _ = campagne_de(mensuel, datetime.date(2026, 10, 1), statut=Campagne.Statut.OUVERTE, date_fin_saisie=fin,
                                     seuil_ecart=Decimal("0.3"))
            for c, v in ((septembre, 100), (octobre, 10108)):
                Reponse.objects.create(periode=c.periode, kpi=elm, organisation=self.e1, valeur=Decimal(v),
                                       statut=Reponse.Statut.VALIDE, origine=Reponse.Origine.IMPORT)
        for largeur in (360, 390):
            p = self.page(self.contrib, largeur)
            self.aller(p, f"/saisie/?campagne={octobre.pk}&org={self.e1.id}")
            with self.subTest(largeur=largeur):
                ecart = p.locator(f'tr.ligne[data-cle="ELM|{self.e1.id}"] .ecart-sous')
                self.assertTrue(ecart.is_visible())
                self.assertIn("vs septembre 2026", " ".join(ecart.inner_text().split()))
                self.assertIn("+10 008,0 %", " ".join(ecart.inner_text().replace("\u202f", " ").replace("\xa0", " ").split()))
                # chaque morceau visible (écart, « vs septembre 2026 ») reste dans sa cellule : rien n'est coupé
                debord = ecart.evaluate("""e => { const td = e.closest('td').getBoundingClientRect();
                    return Math.max(...[...e.querySelectorAll(':scope > span:not(.visuellement-cache)')].flatMap(s => [...s.getClientRects()])
                        .map(r => r.right - td.right)); }""")
                self.assertLessEqual(debord, 0.5)
                self.assertEqual(p.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth"), 0)
        self.assertEqual(p.erreurs, [])
