"""Apparence sombre : gamme tirée des couleurs du client, contrastes vérifiés comme en clair, CSS injecté
(système en sombre ou choix « Sombre »), choix de l'appareil dans Mon compte (cookie, rien dans la base), pages
d'erreur autonomes, contrôles de la page Identité."""
import re
import unittest
from pathlib import Path

from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from collecte.models import Journal
from parametres import couleurs as CO
from parametres.models import Instance
from referentiel.models import Utilisateur
from decimal import Decimal

from collecte import imports as I
from collecte.aides_tests.aller_retour import Base as BaseEchanges, fichier
from parametres.aides_tests import interdits as INTERDITS

# palettes d'essai en plus des palettes fournies : couleur principale très claire, très foncée, vive
AUTRES = {
    "jaune": ("#FFD400", "#222222", "#FFFFFF", "#111111"),
    "marine": ("#14213D", "#FCA311", "#F5F5F5", "#000000"),
    "rose": ("#E5005B", "#3C3C3B", "#F5F5F5", "#1D1D1B"),
    "cyan": ("#00E5FF", "#FF00AA", "#FAFAFA", "#0A0A0A"),
}


def gammes():
    for code, p in CO.PALETTES.items():
        yield code, CO.gamme(p["principale"], p["accent"], p["fond"], p["texte"], code)
    for code, c in AUTRES.items():
        yield code, CO.gamme(*c)


class GammeSombreTests(TestCase):
    def test_contrastes_de_chaque_palette(self):
        """Mêmes contrôles qu'en clair (page Identité), et chaque couleur de texte sur tous les fonds où elle apparaît."""
        for code, g in gammes():
            s = CO.gamme_sombre(g)
            with self.subTest(palette=code):
                self.assertTrue(all(c["ok"] for c in CO.controles(s)), CO.controles(s))
                self.assertLess(CO.luminance(s["fond"]), .02)  # vraiment sombre
                fonds = [s[k] for k in ("fond", "surface", "entete-table", "neutre", "surface-vive")]
                pales = [s[k] for k in ("vert-pale", "jaune-pale", "orange-pale", "bleu3")]
                for texte in ("texte", "texte-doux", "principale-texte"):
                    for f in fonds + pales:
                        self.assertGreaterEqual(CO.contraste(s[texte], f), 4.5, (texte, f))
                for etat, pale in (("vert", "vert-pale"), ("jaune", "jaune-pale"), ("orange", "orange-pale"), ("bleu", "bleu3")):
                    self.assertGreaterEqual(CO.contraste(s[f"{etat}-texte"], s[pale]), 4.5, etat)
                for trait in ("principale-bord", "contour", "erreur", "orange"):
                    self.assertGreaterEqual(CO.contraste(s[trait], s["surface"]), 3, trait)
                self.assertGreaterEqual(CO.contraste(s["sur-principale"], s["principale"]), 4.5)
                self.assertGreaterEqual(CO.contraste(s["sur-erreur"], s["erreur"]), 4.5)
                self.assertGreaterEqual(CO.contraste(s["erreur-texte"], s["erreur-teinte"]), 4.5)
                self.assertGreaterEqual(CO.contraste(s["sur-bandeau-actif"], s["bandeau-actif"]), 4.5)
                self.assertGreaterEqual(CO.contraste(s["accent-texte"], s["accent-teinte"]), 4.5)
                self.assertEqual(set(s), set(CO.VARIABLES) | set(CO.FIXES))  # toute la gamme, rien de plus

    def test_gamme_fixee_d_une_palette_enregistree(self):
        """Une gamme fixée à l'identique (charte d'une marque) a aussi sa gamme sombre, tirée de ses couleurs."""
        g = CO.gamme("#B5305F", "#5A2D82", "#F6F6F6", "#2B2B2B")
        fixe = {k: g[k] for k in CO.VARIABLES if k in g}
        s = CO.gamme_sombre(CO.gamme("#B5305F", "#5A2D82", "#F6F6F6", "#2B2B2B", gamme_fixe=fixe))
        self.assertTrue(all(c["ok"] for c in CO.controles(s)))

    def test_couleurs_des_graphiques(self):
        """Chaque série (fournie ou réglée par l'admin) à 3:1 au moins sur les cartes sombres."""
        s = CO.gamme_sombre(CO.gamme("#1F5FAD", "#0F9D9A", "#F2F4F7", "#1E2A38"))
        for reglage in ({}, {"series": ["#000080", "#101010", "#2A78D6", "#EB6834", "#1BAF7A", "#EDA100", "#E87BA4", "#008300"],
                             "autres": "#333333"}):
            css = CO.css_graphiques_sombre(reglage, s["surface"])
            couleurs = dict(re.findall(r"--viz-(\d|autres): (#[0-9A-F]{6})", css))
            self.assertEqual(len(couleurs), 9)
            for c in couleurs.values():
                self.assertGreaterEqual(CO.contraste(c, s["surface"]), 3, c)

    def test_niveaux_types_referentiels(self):
        surface = CO.gamme_sombre(CO.gamme("#1F5FAD", "#0F9D9A", "#F2F4F7", "#1E2A38"))["surface"]
        for c in CO.COULEURS_NIVEAUX + ["#FFEC32", "#000000", "#FFFFFF", "", "rouge"]:  # les deux dernières : abîmées
            etiquette, texte, _, trait = CO.couleurs_niveau_sombre(c, surface)
            self.assertGreaterEqual(CO.contraste(texte, etiquette), 4.5, c)
            self.assertGreaterEqual(CO.contraste(trait, surface), 3, c)

    def test_bloc_sombre(self):
        """Deux fois : système en sombre (sauf choix « Clair ») et choix « Sombre » ; écran seulement (impression claire)."""
        css = CO.bloc_sombre("--fond: #000000; ", [(".niveau-X", "color:#FFFFFF")])
        self.assertIn("@media screen and (prefers-color-scheme: dark){:root:not([data-apparence=clair]){color-scheme: dark; --fond: #000000; }", css)
        self.assertIn(":where(:root:not([data-apparence=clair])) .niveau-X{color:#FFFFFF}", css)
        self.assertIn("@media screen{:root[data-apparence=sombre]{color-scheme: dark;", css)
        self.assertIn(":where(:root[data-apparence=sombre]) .niveau-X{color:#FFFFFF}", css)
        self.assertNotIn('"', css)  # rien que le gabarit échapperait

    def test_pages_d_erreur_autonomes(self):
        """Les pages 400 à 503 (sans base) reprennent la palette par défaut, en clair et en sombre."""
        p = CO.PALETTES[CO.PALETTE_PAR_DEFAUT]
        g = CO.gamme(p["principale"], p["accent"], p["fond"], p["texte"], CO.PALETTE_PAR_DEFAUT)
        style = (Path(settings.BASE_DIR) / "templates" / "_style_erreur.html").read_text(encoding="utf-8")
        clair, sombre = re.findall(r":root \{ (?:color-scheme: light dark; )?(--fond:[^}]*)\}", style)
        for bloc, gam in ((clair, g), (sombre, CO.gamme_sombre(g))):
            valeurs = dict(re.findall(r"--([a-z-]+): (#[0-9A-F]{6})", bloc))
            self.assertEqual(valeurs, {k: gam[k] for k in valeurs})
            self.assertEqual(len(valeurs), 6)
        for code in ("400", "403", "403_csrf", "404", "500", "503_stockage"):
            page = (Path(settings.BASE_DIR) / "templates" / f"{code}.html").read_text(encoding="utf-8")
            self.assertIn('{% include "_style_erreur.html" %}', page)
            self.assertNotRegex(page, r"#[0-9A-Fa-f]{6}")


class ApparencePagesTests(TestCase):
    def setUp(self):
        self.lecteur = Utilisateur.objects.create(username="lecteur", email="l@exemple.test", role=Utilisateur.Role.LECTEUR)
        self.admin = Utilisateur.objects.create(username="admin", email="a@exemple.test", role=Utilisateur.Role.ADMIN)

    def test_css_injecte_et_systeme_par_defaut(self):
        self.client.force_login(self.lecteur)
        html = self.client.get(reverse("collecte:mon_compte")).content.decode()
        self.assertIn('<meta name="color-scheme" content="light dark">', html)
        self.assertNotIn("data-apparence=", html.split("<head>")[0])
        self.assertIn(":root, .apparence-claire {", html)
        s = CO.gamme_sombre(Instance.courante().gamme())
        self.assertIn(f"{CO.AUTO}{{color-scheme: dark; --principale-vive: {s['principale-vive']};", html)
        self.assertIn(f"{CO.FORCE}{{color-scheme: dark;", html)
        self.assertIn(f":where({CO.AUTO}) .niveau-", html)  # étiquettes des niveaux recalculées
        self.assertIn('aria-pressed="true">Automatique</button>', html)

    def test_choix_de_l_appareil_sans_rien_ecrire(self):
        """Mon compte › Apparence : un cookie, aussi pour un lecteur (lecture seule : rien dans la base, rien au journal)."""
        self.client.force_login(self.lecteur)
        url = reverse("collecte:mon_compte")
        journal = Journal.objects.count()
        rep = self.client.post(url, {"action": "apparence", "apparence": "sombre"})
        self.assertRedirects(rep, url + "#apparence")  # revient sur le bloc Apparence 
        self.assertEqual(rep.cookies[CO.COOKIE_APPARENCE].value, "sombre")
        self.assertTrue(rep.cookies[CO.COOKIE_APPARENCE]["httponly"])
        html = self.client.get(url).content.decode()
        self.assertIn('<html lang="fr" data-apparence="sombre">', html)
        self.assertIn('<meta name="color-scheme" content="dark">', html)
        self.assertIn('aria-pressed="true">Sombre</button>', html)
        self.client.post(url, {"action": "apparence", "apparence": "clair"})
        self.assertIn('data-apparence="clair"', self.client.get(url).content.decode())
        rep = self.client.post(url, {"action": "apparence", "apparence": "systeme"})
        self.assertEqual(rep.cookies[CO.COOKIE_APPARENCE].value, "")  # cookie effacé
        self.assertNotIn("data-apparence=", self.client.get(url).content.decode().split("<head>")[0])
        # appliquée par la page (_app/12_communs.js) : 204, cookie posé, pas de message pour la page suivante
        rep = self.client.post(url, {"action": "apparence", "apparence": "sombre"}, HTTP_X_REQUESTED_WITH="fetch")
        self.assertEqual(rep.status_code, 204)
        self.assertEqual(rep.cookies[CO.COOKIE_APPARENCE].value, "sombre")
        self.assertEqual(self.client.get(url).content.decode().count("Apparence enregistrée."), 1)  # la phrase cachée de la page seulement
        self.client.post(url, {"action": "apparence", "apparence": "<b>"})  # valeur inconnue : ignorée
        self.client.cookies[CO.COOKIE_APPARENCE] = "rouge"  # cookie abîmé : le système
        self.assertNotIn("data-apparence=", self.client.get(url).content.decode().split("<head>")[0])
        self.assertEqual(Journal.objects.count(), journal)
        self.lecteur.refresh_from_db()

    def test_page_de_connexion_suit_le_choix(self):
        self.client.cookies[CO.COOKIE_APPARENCE] = "sombre"
        self.assertIn('data-apparence="sombre"', self.client.get(reverse("login")).content.decode())

    def test_identite_controles_sombres(self):
        self.client.force_login(self.admin)
        html = self.client.get(reverse("parametres:identite")).content.decode()
        self.assertIn("data-controles-sombres", html)
        self.assertIn("data-apercu-sombre", html)
        self.assertIn("Lisibilité des couleurs, apparence sombre", html)
        self.assertEqual(html.count('<li class="ok">'), 2 * len(CO.CONTROLES))
        d = self.client.get(reverse("parametres:apercu"), {"principale": "#FFD400", "accent": "#222222", "fond": "#FFFFFF",
                                                            "texte": "#111111"}).json()
        self.assertTrue(d["ok"])
        self.assertEqual(len(d["controles_sombres"]), len(CO.CONTROLES))
        self.assertIn("--surface-vive:", d["css_sombre"])


class DemosEtCouleursTests(TestCase):
    def test_identite_des_demos_sans_rse(self):
        from collecte.aides_tests import jeu_trois_niveaux as J
        from collecte.management.commands import _exemplia

        for identite in (_exemplia.IDENTITE, J.IDENTITE):
            self.assertEqual(identite["titre"], "Probant")
            self.assertNotIn("RSE", " ".join(str(v) for v in identite.values()))
        self.assertEqual([r[0] for r in J.REFERENTIELS], ["REPORTING", "ENERGIE"])

    def test_couleurs_des_types_d_une_installation_neuve(self):
        """Base neuve (migrations) : ni le jaune du brouillon ni le vert du validé."""
        from parametres.models import TypeSaisie

        couleurs = {t.code: (t.couleur, t.couleur_fond) for t in TypeSaisie.objects.all()}
        for c, fond in couleurs.values():
            self.assertNotIn(fond.upper(), {"#FFF5C2", "#D7F3E6"})
            self.assertNotIn(c.upper(), {"#E6B800", "#0EC97E"})
        self.assertEqual(couleurs["Saisi"][0], "#5A6B85")

    def test_couleurs_reglees_d_une_demo_existante_remises_a_neuf(self):
        from parametres import referentiel as PR
        from parametres.models import TypeSaisie

        TypeSaisie.objects.filter(code="Saisi").update(couleur="#E6B800", couleur_fond="#FFF5C2")
        PR.couleurs_types_par_defaut()
        self.assertEqual(TypeSaisie.objects.get(code="Saisi").couleur_fond, "#E8ECF2")


D = Decimal


class InstallationNeuveNeutreTests(BaseEchanges):
    """P9 : une installation neuve ne reçoit ni les couleurs d'une charte retirée ni un vocabulaire propre à une
    installation (garde-fou). Les couleurs interdites ne sont pas écrites ici : ``parametres/aides_tests/interdits.py``."""

    def test_bulles_et_niveaux_lisibles(self):
        from parametres import couleurs as CO
        from parametres.couleurs import BLANC

        from collecte.templatetags import collecte as T

        for c in T.PALETTE:  # initiales blanches lisibles
            self.assertGreaterEqual(CO.contraste(c, BLANC), 4.5)

    @unittest.skipUnless(INTERDITS.present(), INTERDITS.SAUTE)
    def test_bulles_niveaux_et_palettes_sans_couleur_interdite(self):
        from parametres import couleurs as CO
        from parametres import niveaux as N
        from parametres.couleurs import BLANC, lisible

        from collecte.templatetags import collecte as T

        _, interdites = INTERDITS.interdits()
        fournies = {c.upper() for p in CO.PALETTES.values() for c in (p["principale"], p["accent"], p["fond"], p["texte"])}
        niveaux = {c.upper() for n in N.PAR_DEFAUT for c in n[4:]}
        self.assertEqual(len({lisible(c, [BLANC]).upper() for c in interdites} & {c.upper() for c in T.PALETTE}), 0)
        for nom, couleurs in (("niveaux ajoutés", {c.upper() for c in CO.COULEURS_NIVEAUX}), ("niveaux de départ", niveaux),
                              ("palettes fournies", fournies)):
            self.assertEqual(len(interdites & couleurs), 0, nom)

    def test_fichier_a_remplir_vierge(self):
        import io

        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(I.modele_vierge(self.admin, self.c).content))
        textes = " ".join(str(v) for ws in wb.worksheets for r in ws.iter_rows(values_only=True) for v in r if v)
        self.assertNotRegex(textes, r"\bRSE\b")  # aucun texte de l'interface ne parle de RSE
        a = I.analyser(self.admin, fichier([["ID", "Organisation", "Exercice", "Valeur"], ["EFF", "E1", 2026, 111]]))
        self.assertEqual(a.lignes[0].valeur, D(111))  # l'ancien en-tête générique reste lu
