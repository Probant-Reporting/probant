"""Paramètres › Identité : couleurs dérivées, contrastes, page d'administration, logo, journal, exports."""
import io
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from openpyxl import load_workbook

from collecte.models import Journal
from referentiel.models import Utilisateur

from . import couleurs as CO
from .models import Instance
from collecte.outils_tests import html_de

MEDIA = tempfile.mkdtemp()
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


class CouleursTests(TestCase):
    def test_palettes_fournies_neutres(self):
        """Les palettes fournies sont celles de l'outil, et elles seules (aucune palette propre à une installation)."""
        self.assertEqual(set(CO.PALETTES), {"ocean", "indigo", "foret", "ardoise", "terracotta", "prune", "graphite"})

    def test_palette_retiree_devient_palette_propre_a_l_installation(self):
        """Palette qui n'est plus fournie : la migration 0009 la convertit en palette enregistrée de l'installation, avec
        ses quatre couleurs ; l'apparence ne change pas (gamme dérivée de ces couleurs, comme avant). Une palette fournie,
        « perso » ou déjà enregistrée ne bouge pas."""
        import importlib

        from django.apps import apps as django_apps

        from .models import PaletteEnregistree

        migration = importlib.import_module("parametres.migrations.0009_palettes_enregistrees")
        couleurs = {"couleur_principale": "#B5305F", "couleur_accent": "#6E56CF", "couleur_fond": "#F7F5F4",
                    "couleur_texte": "#2B2A30"}
        Instance.objects.update_or_create(pk=1, defaults={"palette": "ancienne", **couleurs})
        avant = Instance.courante().gamme()
        migration.convertir_palette_retiree(django_apps, None)
        i = Instance.courante()
        p = PaletteEnregistree.objects.get(nom="Palette d'origine")
        self.assertEqual((i.palette, p.gamme), (p.code, {}))
        self.assertEqual((p.principale, p.accent, p.fond, p.texte), tuple(couleurs.values()))
        self.assertEqual(i.gamme(), avant)
        for code in ("ocean", "perso", p.code):
            Instance.objects.filter(pk=1).update(palette=code)
            migration.convertir_palette_retiree(django_apps, None)
            self.assertEqual(Instance.courante().palette, code)
        self.assertEqual(PaletteEnregistree.objects.count(), 1)

    def test_toutes_les_palettes_sont_lisibles(self):
        for code, p in CO.PALETTES.items():
            g = CO.gamme(p["principale"], p["accent"], p["fond"], p["texte"], code)
            self.assertEqual(set(g), set(CO.VARIABLES) | set(CO.FIXES))  # marque, puis couleurs communes (états, ombres)
            self.assertTrue(all(c["ok"] for c in CO.controles(g)), code)

    def test_contraste_et_melange(self):
        self.assertAlmostEqual(CO.contraste("#FFFFFF", "#000000"), 21)
        self.assertEqual(CO.melange("#FF0000", "#FFFFFF", .5), "#FF8080")
        perso = CO.gamme("#9FD3FF", "#0F9D9A", "#F2F4F7", "#1E2A38", "perso")  # trop clair : l'outil s'adapte et le dit
        self.assertTrue(all(c["ok"] for c in CO.controles(perso)))
        self.assertEqual(len(CO.adaptations(perso)), 2)
        pale = CO.gamme("#1F5FAD", "#0F9D9A", "#F2F4F7", "#9AA3AD", "perso")  # texte trop clair : signalé
        self.assertFalse(all(c["ok"] for c in CO.controles(pale)))

    def test_couleurs_derivees_lisibles(self):
        """Bords des champs à 3:1, texte des boutons et du bandeau à 4,5:1, bandeau clair si le blanc ne passe pas."""
        for p in [*CO.PALETTES.values(), {"principale": "#9FD3FF", "accent": "#0F9D9A", "fond": "#F2F4F7", "texte": "#1E2A38"}]:
            g = CO.gamme(p["principale"], p["accent"], p["fond"], p["texte"], "perso")
            self.assertGreaterEqual(min(CO.contraste(g["contour"], f) for f in (g["fond"], g["surface"])), 3)
            self.assertGreaterEqual(CO.contraste(g["sur-principale"], g["principale"]), 4.5)
            self.assertGreaterEqual(CO.contraste(g["sur-bandeau"], g["bandeau"]), 4.5)
            self.assertGreaterEqual(CO.contraste(g["sur-bandeau-actif"], g["bandeau-actif"]), 4.5)
            self.assertGreaterEqual(CO.contraste(g["principale-texte"], g["fond"]), 4.5)
        clair = CO.gamme("#9FD3FF", "#0F9D9A", "#F2F4F7", "#1E2A38", "perso")
        self.assertEqual((clair["bandeau"], clair["bandeau-filet"]), (clair["surface"], "#9FD3FF"))
        self.assertEqual(CO.gamme("#1F5FAD", "#0F9D9A", "#F2F4F7", "#1E2A38", "ocean")["bandeau"], "#1F5FAD")


@override_settings(MEDIA_ROOT=MEDIA)
class IdentiteTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN)
        self.contrib = Utilisateur.objects.create(username="contrib", email="contrib@exemple.test")

    def donnees(self, **autres):
        return {"nom": "Essai", "titre": "Reporting ESG", "sous_titre": "", "sigle": "ESG", "contact": "l'équipe ESG",
                "langue": "fr", "palette": "foret", "couleur_principale": "#1d6b4f", "couleur_accent": "#D9822B",
                "couleur_fond": "#F5F7F4", "couleur_texte": "#1A221E", **autres}

    def test_installation_neuve_generique(self):
        i = Instance.courante()
        self.assertEqual((i.nom, i.palette), ("Ma structure", CO.PALETTE_PAR_DEFAUT))
        rep = self.client.get(reverse("login"))
        self.assertContains(rep, f"--principale: {CO.PALETTES[CO.PALETTE_PAR_DEFAUT]['principale']};")
        self.assertContains(rep, "Probant")
        self.assertNotRegex(rep.content.decode(), r"\bRSE\b")  # identité neutre : aucun texte ne parle de RSE

    def test_page_identite_reservee_a_l_admin_et_journalisee(self):
        url = reverse("parametres:identite")
        self.client.force_login(self.contrib)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(url), "Palettes proposées")
        rep = self.client.post(url, self.donnees())
        self.assertEqual(rep.status_code, 302)
        i = Instance.courante()
        self.assertEqual((i.nom, i.couleur_principale, i.palette), ("Essai", "#1D6B4F", "foret"))
        self.assertTrue(Journal.objects.filter(action="reglage_identite", champ="couleur_principale", apres="#1D6B4F").exists())
        page = self.client.get(reverse("collecte:saisie"))
        self.assertContains(page, "--principale: #1D6B4F;")
        self.assertContains(page, "<b>Reporting ESG</b>")
        rep = self.client.post(url, self.donnees(couleur_principale="rouge"))
        self.assertContains(rep, "#RRGGBB")
        self.client.post(url, self.donnees(couleur_principale="#123456"))
        self.assertEqual(Instance.courante().palette, "perso")  # couleurs modifiées : palette personnalisée

    def test_apercu(self):
        self.client.force_login(self.admin)
        d = self.client.get(reverse("parametres:apercu"), {"principale": "#1F5FAD", "accent": "#0F9D9A", "fond": "#F2F4F7",
                                                           "texte": "#1E2A38"}).json()
        self.assertTrue(d["ok"])
        self.assertIn("--principale: #1F5FAD;", d["css"])
        self.assertEqual(len(d["controles"]), len(CO.CONTROLES))
        self.assertFalse(self.client.get(reverse("parametres:apercu"), {"principale": "x"}).json()["ok"])

    def test_logo(self):
        self.client.force_login(self.admin)
        url = reverse("parametres:identite")
        rep = self.client.post(url, self.donnees(logo=SimpleUploadedFile("logo.svg", b"<svg onload='x'/>")))
        self.assertContains(rep, "PNG, JPG ou WebP")
        rep = self.client.post(url, self.donnees(logo=SimpleUploadedFile("faux.png", b"pas une image")))
        self.assertContains(rep, "pas une image valide")
        self.client.post(url, self.donnees(logo=SimpleUploadedFile("logo.png", PNG)))
        self.assertTrue(Instance.courante().logo)
        self.client.logout()
        rep = self.client.get(reverse("parametres:logo"))  # visible sans connexion (page de connexion)
        self.assertEqual((rep.status_code, rep["Content-Type"]), (200, "image/png"))
        self.assertContains(self.client.get(reverse("login")), "logo-connexion")
        # fichier du logo disparu (base restaurée sans ses fichiers) : pastille du sigle, pas d'image cassée ni d'erreur
        i = Instance.courante()
        i.logo.storage.delete(i.logo.name)
        self.assertEqual(self.client.get(reverse("parametres:logo")).status_code, 404)
        self.assertNotContains(self.client.get(reverse("login")), "logo-connexion")
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("collecte:accueil"), follow=True), '<span class="logo">')
        self.client.post(url, self.donnees(logo=SimpleUploadedFile("logo.png", PNG)))
        self.client.post(url, self.donnees(supprimer_logo="on"))
        self.assertFalse(Instance.courante().logo)
        self.assertEqual(self.client.get(reverse("parametres:logo")).status_code, 404)

    def test_les_exports_excel_suivent_l_identite(self):
        Instance.objects.update_or_create(pk=1, defaults={"palette": "foret", "couleur_principale": "#1D6B4F",
                                                          "couleur_accent": "#C28A1E", "couleur_fond": "#F3F4EF",
                                                          "couleur_texte": "#23291F"})
        from collecte import configuration as C

        wb = load_workbook(io.BytesIO(C.exporter().content))
        self.assertEqual(wb["À lire"]["A1"].font.color.rgb[-6:], "1D6B4F")  # titre aux couleurs de l'identité


class PalettesEnregistreesTests(TestCase):
    def setUp(self):
        self.admin = Utilisateur.objects.create_user("admin", email="a@exemple.test", password="x", role=Utilisateur.Role.ADMIN)
        self.client.force_login(self.admin)
        self.donnees = {"nom": "Essai", "titre": "Reporting", "sous_titre": "", "sigle": "AC", "contact": "l'équipe",
                        "langue": "fr", "palette": "perso", "couleur_principale": "#123456", "couleur_accent": "#0F9D9A",
                        "couleur_fond": "#F2F4F7", "couleur_texte": "#1E2A38"}

    def test_enregistrer_choisir_supprimer(self):
        from .models import PaletteEnregistree

        url = reverse("parametres:identite")
        rep = self.client.post(url, {**self.donnees, "action": "enregistrer_palette", "nom_palette": ""})
        self.assertContains(rep, "Saisissez un nom pour enregistrer la palette")
        self.client.post(url, {**self.donnees, "action": "enregistrer_palette", "nom_palette": "Charte 2026"})
        p = PaletteEnregistree.objects.get()
        self.assertEqual((p.nom, p.principale, Instance.courante().palette), ("Charte 2026", "#123456", p.code))
        rep = self.client.get(url)
        self.assertContains(rep, "Charte 2026")
        self.assertContains(rep, f'value="{p.code}" checked')
        # reprendre la palette après un autre choix : reconnue comme telle
        self.client.post(url, {**self.donnees, "palette": "ocean", "couleur_principale": "#1F5FAD"})
        self.client.post(url, {**self.donnees, "palette": p.code})
        self.assertEqual(Instance.courante().palette, p.code)
        self.client.post(url, {"action": f"supprimer_palette:{p.code}"})
        self.assertFalse(PaletteEnregistree.objects.exists())
        self.assertEqual((Instance.courante().palette, Instance.courante().couleur_principale), ("perso", "#123456"))



class SeuilsTests(TestCase):
    """Paramètres › Seuils de suivi : valeurs d'avant par défaut, enregistrement en fraction, effet sur les retards."""

    def setUp(self):
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN)
        self.client.force_login(self.admin)

    def test_valeurs_par_defaut_identiques_a_avant(self):
        from decimal import Decimal

        i = Instance.courante()
        self.assertEqual((i.tolerance_retard, i.historique_annees, i.historique_minimum, i.tolerance_fe, i.tolerance_detail),
                         (10, 5, 3, Decimal("0.01"), Decimal("0.005")))

    def test_reglage_en_pourcentage_journalise(self):
        from decimal import Decimal

        url = reverse("parametres:seuils")
        rep = self.client.get(url)
        self.assertContains(rep, "Seuils de suivi")
        self.assertContains(rep, 'value="0,5"')
        donnees = {"tolerance_retard": "15", "historique_annees": "4", "historique_minimum": "2",
                   "tolerance_fe_pct": "2", "tolerance_detail_pct": "1,0"}
        self.assertEqual(self.client.post(url, donnees).status_code, 302)
        i = Instance.courante()
        self.assertEqual((i.tolerance_retard, i.historique_annees, i.historique_minimum, i.tolerance_fe, i.tolerance_detail),
                         (15, 4, 2, Decimal("0.02"), Decimal("0.01")))
        self.assertTrue(Journal.objects.filter(action="reglage_seuils", champ="tolerance_retard").exists())
        rep = self.client.post(url, {**donnees, "historique_minimum": "6"})
        self.assertContains(rep, "Les valeurs passées nécessaires ne peuvent pas dépasser")
        rep = self.client.post(url, {**donnees, "tolerance_retard": "80"})
        self.assertEqual(rep.status_code, 200)
        self.assertEqual(Instance.courante().tolerance_retard, 15)

    def test_reserve_a_l_admin(self):
        contrib = Utilisateur.objects.create(username="c", email="c@exemple.test")
        self.client.force_login(contrib)
        self.assertEqual(self.client.get(reverse("parametres:seuils")).status_code, 403)


class VersionFeuilleTests(TestCase):
    """L'adresse de la feuille de style change avec son contenu : le navigateur recharge les nouveaux styles après une mise à
    jour, sans vider son cache (sinon les pages s'affichent avec l'ancienne feuille)."""

    def test_empreinte_du_fichier_dans_l_adresse(self):
        import os
        from unittest import mock

        from django.conf import settings

        from . import contexte

        v = contexte.version_css()
        self.assertRegex(v, rf"^{settings.VERSION}-[0-9a-f]{{10}}$")
        chemin = os.path.join(tempfile.mkdtemp(), "outil.css")
        with open(chemin, "w") as f:
            f.write("a { color: red; }")
        with mock.patch("django.contrib.staticfiles.finders.find", return_value=chemin):
            v1 = contexte.version_css()
            with open(chemin, "w") as f:
                f.write("a { color: blue; }")
            os.utime(chemin, (1, 1))
            self.assertNotEqual(contexte.version_css(), v1)
        shutil.rmtree(os.path.dirname(chemin))


class BaseAdminConnecte(TestCase):
    def setUp(self):
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN)
        self.client.force_login(self.admin)


class IdentitePageTests(BaseAdminConnecte):
    def page(self):
        return html_de(self.client, reverse("parametres:identite"))

    def test_sans_colonne_laterale_ni_phrases_d_aide(self):
        html = self.page()
        self.assertIn('class="page-identite sans-cote"', html)
        self.assertNotIn("colonne-apercu", html)
        for phrase in ("onglet du navigateur", "(facultatif)", "Affiché sur la page de connexion"):
            self.assertNotIn(phrase, html)

    def test_simulateur_dans_le_bloc_structure(self):
        i = Instance.courante()
        i.titre, i.sous_titre, i.contact = "Mon reporting", "Groupe Test", "aide@exemple.test"
        i.save()
        html = self.page()
        simu = html.split('class="simulateur-identite"')[1].split("</section>")[0]
        self.assertIn("<b data-titre-apercu>Mon reporting</b>", simu)
        self.assertIn("<span data-sous-titre-apercu>Groupe Test</span>", simu)
        self.assertIn("<b data-contact-apercu>aide@exemple.test</b>", simu)
        self.assertIn("data-apercu ", simu)  # suit les couleurs choisies, comme l'aperçu clair

    def test_palettes_et_apercus_dans_le_meme_bloc(self):
        html = self.page()
        bloc = html.split('class="palettes"')[1].split("</section>")[0]
        for attendu in ("data-apercu ", "data-apercu-sombre", "Apparence claire", "Apparence sombre", 'id="id_couleur_principale"',
                        "data-controles", "data-alerte-contraste"):
            self.assertIn(attendu, bloc)

    def test_lisibilite_dans_un_volet_avec_bilan(self):
        html = self.page()
        volet = html.split('<details class="lisibilite"')[1]
        self.assertTrue(volet.startswith(">"))  # replié quand tout est lisible
        n = len(CO.CONTROLES)
        self.assertIn(f'data-bilan="clair">Clair <b><span data-bilan-ok>{n}</span>/{n}</b>', volet)
        self.assertIn(f'data-bilan="sombre">Sombre <b><span data-bilan-ok>{n}</span>/{n}</b>', volet)
        self.assertIn("data-controles-sombres", volet)

    def test_palette_illisible_signalee_et_volet_ouvert(self):
        i = Instance.courante()
        i.palette, i.couleur_texte = "perso", "#DDDDDD"  # texte presque invisible sur le fond
        i.save()
        html = self.page()
        self.assertIn('<details class="lisibilite" open>', html)
        self.assertIn('class="bilan-contraste ko" data-bilan="clair"', html)
        self.assertIn('<p class="encart encart-avertissement" data-alerte-contraste >', html)
        self.assertIn('<li class="ko">', html)

    def test_apercu_en_direct_inchange(self):
        d = self.client.get(reverse("parametres:apercu"), {"principale": "#1D6B4F", "accent": "#D9822B", "fond": "#F5F7F4",
                                                          "texte": "#DDDDDD", "palette": "perso"}).json()
        self.assertTrue(d["ok"])
        self.assertFalse(all(c["ok"] for c in d["controles"]))
        self.assertEqual(len(d["controles_sombres"]), len(CO.CONTROLES))

    def test_markdown_dans_la_zone_de_texte(self):
        html = self.page()
        zone = html.split('<textarea name="texte_confidentialite"')[1].split(">")[0]
        self.assertIn('placeholder="Markdown accepté : **gras**, *italique*, listes, liens."', zone)
        self.assertIn('aria-describedby="aide-texte-confidentialite"', zone)
        self.assertIn('<span class="visually-hidden" id="aide-texte-confidentialite">Markdown accepté', html)
        self.assertNotIn("Le Markdown est accepté", html)

    def test_couleurs_des_graphiques_texte_court(self):
        html = self.page()
        self.assertIn("Les séries prennent ces couleurs, dans cet ordre.", html)
        self.assertNotIn("ses teintes claires ont aussi des motifs", html)

    def test_enregistrement_garde_le_texte_de_l_entreprise(self):
        i = Instance.courante()
        donnees = {c: getattr(i, c) for c in ("nom", "titre", "sous_titre", "sigle", "contact", "palette", "couleur_principale",
                                              "couleur_accent", "couleur_fond", "couleur_texte")}
        donnees.update(titre="Autre nom", texte_confidentialite="**Responsable** : la direction.")
        rep = self.client.post(reverse("parametres:identite"), donnees)
        self.assertEqual(rep.status_code, 302)
        i.refresh_from_db()
        self.assertEqual((i.titre, i.texte_confidentialite), ("Autre nom", "**Responsable** : la direction."))


class BaseAdminFr(TestCase):
    def setUp(self):
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN,
                                                langue="fr")
        self.client.force_login(self.admin)


class SeuilsPageTests(BaseAdminFr):
    def test_un_sous_titre_par_controle(self):
        html = html_de(self.client, reverse("parametres:seuils"))
        for titre in ("Valeur hors historique", "Paramètre hérité modifié", "Total différent du détail"):
            self.assertIn(f">{titre}</h3>", html)
        self.assertEqual(html.count('class="groupe-seuil"'), 3)
        self.assertIn("Écart toléré (points)", html)
        self.assertIn("Exemple : à la moitié de la saisie, le rythme attendu est de 50 %.", html)
        for champ in ("tolerance_retard", "historique_annees", "historique_minimum", "tolerance_fe_pct", "tolerance_detail_pct"):
            self.assertIn(f'name="{champ}"', html)  # aucun réglage retiré
