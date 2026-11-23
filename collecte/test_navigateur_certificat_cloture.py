"""Certificat de clôture dans un vrai navigateur (1 440 et 390 px) : ouverture depuis la fiche de la campagne, contenu, média
« print » (sans menus, en-tête et pied de page, tableaux entiers, A4 et Letter), aucune écriture, sans erreur de script ni
violation de la politique des contenus, sans défilement horizontal, cibles d'au moins 24 px, axe-core (si AXE_JS). Les
captures et les PDF sont écrits dans le dossier de la variable DOSSIER_CAPTURES quand elle existe."""
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from referentiel.models import KPI, Utilisateur

from .aides_tests.navigateur import AXE, NavigateurBase, _hors_boucle
from .models import Alerte, Campagne, Journal, Preuve, Reponse
from .test_navigateur_aide import REGLES_AXE
from .test_navigateur_cibles_tactiles import MESURE


class CertificatNavigateurTests(NavigateurBase):
    def setUp(self):
        super().setUp()
        with _hors_boucle():
            for u in (self.admin, self.lecteur):
                u.langue = "en"
                u.save()
            self.auditeur = Utilisateur.objects.create(username="auditeur", email="auditeur@exemple.test",
                                                       role=Utilisateur.Role.AUDITEUR, langue="en")
            self.campagne = self.campagnes[-1]  # 2025, clôturée
            Alerte.objects.create(campagne=self.campagne, kpi=self.eff, organisation=self.e1, controle=Alerte.Controle.ECART_N1,
                                  message="Écart avec N-1", statut=Alerte.Statut.OUVERTE)

    def _dossier(self):
        dossier = os.environ.get("DOSSIER_CAPTURES")
        if dossier:
            Path(dossier).mkdir(parents=True, exist_ok=True)
        return dossier

    def _capture(self, page, nom, **options):
        dossier = self._dossier()
        if dossier:
            page.wait_for_timeout(300)
            page.screenshot(path=str(Path(dossier) / nom), **options)

    def compteurs(self):
        with _hors_boucle():
            return {m.__name__: m.objects.count() for m in (Reponse, Journal, Alerte, Preuve, Campagne, Utilisateur, KPI)}

    def test_depuis_la_fiche_de_la_campagne_cloturee(self):
        page = self.page(self.admin)
        self.aller(page, f"/administration/campagnes/{self.campagne.pk}/")
        lien = page.locator("a:has-text('Closing certificate')")
        self.assertEqual(lien.count(), 1)
        lien.click()
        page.wait_for_load_state("networkidle")
        self.assertIn("/certificat-de-cloture/", page.url)
        self.assertEqual(page.locator("h1").inner_text(), "Closing certificate")
        corps = page.locator(".certificat").inner_text()
        for attendu in ("Scope", "Completion", "Values", "Consistency alerts", "Fingerprint of the figures", "Écart avec N-1"):
            self.assertIn(attendu, corps)
        self.assertRegex(page.locator(".certificat-condense").inner_text().replace("\n", "").replace(" ", ""), r"^[0-9a-f]{64}$")
        self.assertEqual(page.erreurs, [])

    def test_aucune_ecriture_et_empreinte_stable(self):
        page = self.page(self.admin)
        avant = self.compteurs()
        self.aller(page, f"/certificat-de-cloture/{self.campagne.pk}/")
        e1 = page.locator(".certificat-condense").inner_text()
        self.aller(page, f"/certificat-de-cloture/{self.campagne.pk}/")
        self.assertEqual(page.locator(".certificat-condense").inner_text(), e1)
        self.assertEqual(self.compteurs(), avant)

    def test_ordinateur_et_telephone(self):
        for largeur in (1440, 390):
            page = self.page(self.admin, largeur=largeur, tactile=largeur < 500)
            self.aller(page, f"/certificat-de-cloture/{self.campagne.pk}/")
            self.assertFalse(page.evaluate("document.documentElement.scrollWidth > window.innerWidth"), largeur)
            self.assertEqual(page.evaluate(MESURE), [], largeur)  # cibles d'au moins 24 px
            self.assertEqual(page.locator("button[data-imprimer]").count(), 1)
            self._capture(page, f"certificat-ecran-{largeur}.png", full_page=True)
            self.assertEqual(page.erreurs, [])

    def test_le_bouton_imprimer_ouvre_l_impression(self):
        page = self.page(self.admin)
        self.aller(page, f"/certificat-de-cloture/{self.campagne.pk}/")
        page.evaluate("() => { window.__imprime = 0; window.print = () => { window.__imprime += 1; }; }")
        page.locator("button[data-imprimer]").click()
        self.assertEqual(page.evaluate("window.__imprime"), 1)

    def test_media_print(self):
        page = self.page(self.admin)
        self.aller(page, f"/certificat-de-cloture/{self.campagne.pk}/")
        page.emulate_media(media="print")
        visible = "(s) => [...document.querySelectorAll(s)].some(e => getComputedStyle(e).display !== 'none' && e.getBoundingClientRect().width > 0)"
        for cache in ("header.haut", "nav.onglets", ".pied-version", ".barre-certificat", "button[data-imprimer]"):
            self.assertFalse(page.evaluate(visible, cache), cache)
        for montre in (".certificat", ".certificat-tete", ".certificat-page-entete", ".certificat-page-pied"):
            self.assertTrue(page.evaluate(visible, montre), montre)
        # en-tête et pied dans le flux de la page (groupes de tableau répétés sur chaque feuille), jamais « fixed » :
        # un bloc fixe qui sort de la zone de page se retrouve sur la feuille voisine
        self.assertEqual(page.evaluate("getComputedStyle(document.querySelector('.certificat-page-entete')).display"), "table-header-group")
        self.assertEqual(page.evaluate("getComputedStyle(document.querySelector('.certificat-page-pied')).display"), "table-footer-group")
        self.assertEqual(page.evaluate("[...document.querySelectorAll('.certificat *')].filter(e => getComputedStyle(e).position === 'fixed').length"), 0)
        self.assertEqual(page.evaluate("[...document.querySelectorAll('.certificat-table')].every(t => getComputedStyle(t).breakInside === 'avoid')"), True)
        # un titre de section n'est jamais séparé de son tableau : une section ne se coupe pas (sauf celle de la liste des alertes)
        self.assertEqual(page.evaluate("""[...document.querySelectorAll('.certificat section')].filter(s => !s.querySelector('h3'))
            .map(s => getComputedStyle(s).breakInside).filter(v => v !== 'avoid')"""), [])
        self.assertEqual(page.evaluate("getComputedStyle(document.body).backgroundColor"), "rgb(255, 255, 255)")
        # noir sur blanc quelle que soit l'apparence de l'écran
        self.assertEqual(page.evaluate("getComputedStyle(document.querySelector('.certificat h2')).color"), "rgb(0, 0, 0)")
        self._capture(page, "certificat-impression.png", full_page=True)

    def test_pdf_a4_et_letter_avec_en_tete_et_pied_sur_chaque_page(self):
        page = self.page(self.admin)
        self.aller(page, f"/certificat-de-cloture/{self.campagne.pk}/")
        dossier = self._dossier()
        for papier in ("A4", "Letter"):
            octets = page.pdf(format=papier, print_background=True, prefer_css_page_size=False)
            self.assertTrue(octets.startswith(b"%PDF"))
            pages = len(re.findall(rb"/Type\s*/Page[^s]", octets))
            self.assertGreaterEqual(pages, 1, papier)
            # une page de plus que le contenu ne doit pas apparaître pour une campagne aussi courte
            self.assertLessEqual(pages, 3, papier)
            if dossier:
                (Path(dossier) / f"certificat-{papier.lower()}.pdf").write_bytes(octets)

    def test_pdf_chaque_feuille_commence_par_l_en_tete_et_finit_par_le_pied(self):
        """Le PDF produit par Chromium (A4 et Letter) : sur chaque feuille la première ligne est l'en-tête, la dernière le pied,
        et le pied n'est jamais au milieu du texte (il s'imprimait avant sur la première ligne d'un tableau)."""
        if not shutil.which("pdftotext"):
            self.skipTest("pdftotext absent")
        page = self.page(self.admin)
        self.aller(page, f"/certificat-de-cloture/{self.campagne.pk}/")
        entete = page.locator(".certificat-page-entete span").first.inner_text().strip()
        pied = page.locator(".certificat-page-pied span").first.inner_text().strip()
        version = page.locator(".certificat-page-pied span").last.inner_text().strip()
        for papier in ("A4", "Letter"):
            octets = page.pdf(format=papier, print_background=True)
            with tempfile.TemporaryDirectory() as dossier:
                fichier = Path(dossier) / "c.pdf"
                fichier.write_bytes(octets)
                texte = subprocess.run(["pdftotext", "-layout", str(fichier), "-"], capture_output=True, text=True, check=True).stdout
            feuilles = [f for f in texte.split("\f") if f.strip()]
            self.assertGreaterEqual(len(feuilles), 2, papier)
            for n, feuille in enumerate(feuilles, 1):
                lignes = [ligne for ligne in feuille.splitlines() if ligne.strip()]
                self.assertIn(entete, lignes[0], f"{papier} feuille {n} : en-tête")
                self.assertIn(pied, lignes[-1], f"{papier} feuille {n} : pied")
                self.assertEqual(sum(pied in ligne and version in ligne for ligne in lignes), 1, f"{papier} feuille {n} : pied répété ou coupé")

    def test_l_auditeur_ouvre_le_certificat_depuis_son_historique(self):
        page = self.page(self.auditeur)
        self.aller(page, "/historique/")
        lien = page.locator(".liens-certificats a").first
        self.assertEqual(page.locator(".liens-certificats a").count(), 3)  # 2023, 2024, 2025
        lien.click()
        page.wait_for_load_state("networkidle")
        self.assertIn("/certificat-de-cloture/", page.url)
        self.assertEqual(page.locator("h1").inner_text(), "Closing certificate")
        self.assertEqual(page.erreurs, [])

    def test_le_lecteur_n_y_accede_pas(self):
        page = self.page(self.lecteur)
        reponse = page.goto(self.live_server_url + f"/certificat-de-cloture/{self.campagne.pk}/")
        self.assertEqual(reponse.status, 403)

    def test_accessibilite(self):
        if not AXE or not os.path.exists(AXE):
            self.skipTest("axe-core absent (variable AXE_JS)")
        with open(AXE, encoding="utf-8") as f:
            axe = f.read()
        for largeur in (1440, 390):
            page = self.page(self.admin, largeur=largeur, tactile=largeur < 500)
            self.aller(page, f"/certificat-de-cloture/{self.campagne.pk}/")
            page.add_script_tag(content=axe)
            self.assertEqual(page.evaluate(REGLES_AXE), [], largeur)
            page.emulate_media(media="print")
            self.assertEqual(page.evaluate(REGLES_AXE), [], f"print {largeur}")


class CertificatPartielNavigateurTests(CertificatNavigateurTests):
    """Auditeur limité à Lille : certificat partiel, mention visible à l'écran, dans l'en-tête imprimé de chaque feuille du
    PDF A4, sans le nom d'une organisation hors périmètre ; axe-core à l'écran et à l'impression."""

    def setUp(self):
        super().setUp()
        with _hors_boucle():
            self.limite = Utilisateur.objects.create(username="audit-lille", email="audit-lille@exemple.test",
                                                     role=Utilisateur.Role.AUDITEUR, langue="en")
            self.limite.perimetre_lecture.add(self.e1)
        self.url = f"/certificat-de-cloture/{self.campagne.pk}/"

    def test_mention_a_l_ecran_et_au_telephone(self):
        for largeur in (1440, 390):
            page = self.page(self.limite, largeur=largeur, tactile=largeur < 500)
            self.aller(page, self.url)
            mention = page.locator("[data-partiel] .certificat-partiel-titre")
            self.assertTrue(mention.is_visible(), largeur)
            self.assertRegex(mention.inner_text(), r"^Partial certificate: 1 of \d+ organisations$")
            corps = page.locator(".certificat").inner_text()
            self.assertIn("It covers Lille", corps)
            for cache in ("Lyon", "Groupe"):
                self.assertNotIn(cache, page.content(), largeur)
            self.assertFalse(page.evaluate("document.documentElement.scrollWidth > window.innerWidth"), largeur)
            self.assertEqual(page.evaluate(MESURE), [], largeur)
            self._capture(page, f"certificat-partiel-{largeur}.png", full_page=True)
            self.assertEqual(page.erreurs, [])

    def test_mention_dans_l_en_tete_imprime_de_chaque_feuille(self):
        page = self.page(self.limite)
        self.aller(page, self.url)
        page.emulate_media(media="print")
        self.assertTrue(page.locator("[data-partiel-entete]").is_visible())
        mention = page.locator("[data-partiel-entete]").inner_text().strip()
        self._capture(page, "certificat-partiel-impression.png", full_page=True)
        octets = page.pdf(format="A4", print_background=True)
        dossier = self._dossier()
        if dossier:
            (Path(dossier) / "certificat-partiel-a4.pdf").write_bytes(octets)
        if not shutil.which("pdftotext"):
            self.skipTest("pdftotext absent")
        with tempfile.TemporaryDirectory() as d:
            fichier = Path(d) / "c.pdf"
            fichier.write_bytes(octets)
            texte = subprocess.run(["pdftotext", "-layout", str(fichier), "-"], capture_output=True, text=True, check=True).stdout
        feuilles = [f for f in texte.split("\f") if f.strip()]
        self.assertGreaterEqual(len(feuilles), 1)
        for n, feuille in enumerate(feuilles, 1):
            lignes = [ligne.strip() for ligne in feuille.splitlines() if ligne.strip()]
            self.assertIn(mention, lignes[:3], f"feuille {n}")
        self.assertNotIn("Lyon", texte)

    def test_l_auditeur_ouvre_le_certificat_depuis_son_historique(self):
        page = self.page(self.limite)
        self.aller(page, "/historique/")
        self.assertEqual(page.locator(".liens-certificats a").count(), 3)
        page.locator(".liens-certificats a").first.click()
        page.wait_for_load_state("networkidle")
        self.assertEqual(page.locator("[data-partiel]").count(), 1)
        self.assertEqual(page.erreurs, [])

    def test_accessibilite(self):
        if not AXE or not os.path.exists(AXE):
            self.skipTest("axe-core absent (variable AXE_JS)")
        with open(AXE, encoding="utf-8") as f:
            axe = f.read()
        for largeur in (1440, 390):
            page = self.page(self.limite, largeur=largeur, tactile=largeur < 500)
            self.aller(page, self.url)
            page.add_script_tag(content=axe)
            self.assertEqual(page.evaluate(REGLES_AXE), [], largeur)
            page.emulate_media(media="print")
            self.assertEqual(page.evaluate(REGLES_AXE), [], f"print {largeur}")

    # les autres essais de la classe parente portent sur l'administrateur : pas répétés ici
    test_depuis_la_fiche_de_la_campagne_cloturee = None
    test_aucune_ecriture_et_empreinte_stable = None
    test_ordinateur_et_telephone = None
    test_le_bouton_imprimer_ouvre_l_impression = None
    test_media_print = None
    test_pdf_a4_et_letter_avec_en_tete_et_pied_sur_chaque_page = None
    test_pdf_chaque_feuille_commence_par_l_en_tete_et_finit_par_le_pied = None
    test_le_lecteur_n_y_accede_pas = None
