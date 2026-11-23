"""Aide dans l'outil (collecte/aide.py) : accès, langue, section, lien de la barre du haut, images, et contrôle des guides
eux-mêmes (images citées présentes, ancres identiques en anglais et en français, libellés en gras qui existent dans
``libelles/`` de leur langue, aucun mot interdit, aucune image orpheline)."""
import glob
import json
import re
import unittest
from pathlib import Path
from unittest import mock

from django.test import TestCase
from django.urls import reverse

from parametres.aides_tests import interdits as INTERDITS
from referentiel.models import Utilisateur

from . import aide as AI

RACINE = Path(__file__).resolve().parent.parent
ROLES = {"admin": "administrator", "validateur": "validator", "contributeur": "contributor", "lecteur": "reader",
         "auditeur": "auditor"}
PAGES_PRINCIPALES = ("collecte:tableau_de_bord", "collecte:visu", "collecte:mon_compte", "collecte:confidentialite")


def guides():
    """[(guide, langue, chemin, texte)] de tous les guides."""
    sortie = []
    for g in AI.GUIDES:
        for langue in AI.LANGUES_GUIDES:
            chemin = AI.chemin_guide(g, langue)
            sortie.append((g, langue, chemin, chemin.read_text(encoding="utf-8")))
    return sortie


class AideAccesTests(TestCase):
    def setUp(self):
        self.u = {r: Utilisateur.objects.create(username=r, email=f"{r}@exemple.test", role=r) for r in ROLES}

    def connecter(self, role, langue=None):
        self.client.force_login(self.u[role])
        if langue:
            self.client.post(reverse("langue"), {"langue": langue})

    def test_sans_connexion_renvoie_a_la_connexion(self):
        for url in (reverse("collecte:aide"), reverse("collecte:aide_guide", args=["reader"]),
                    reverse("collecte:aide_image", args=["en", "dashboard.png"])):
            r = self.client.get(url)
            self.assertEqual(r.status_code, 302, url)
            self.assertIn("/connexion/", r["Location"])

    def test_chaque_role_ouvre_le_guide_de_son_role(self):
        for role, guide in ROLES.items():
            self.connecter(role, "en")
            r = self.client.get(reverse("collecte:aide"))
            self.assertEqual(r.status_code, 200, role)
            titre = AI.lire(guide, "en")[0]
            self.assertContains(r, f"<h1>{titre}</h1>", html=True)

    def test_chaque_langue_a_son_guide_et_pas_de_note(self):
        titres = {"fr": "Guide du contributeur", "es": "Guía del colaborador", "de": "Anleitung für Mitwirkende",
                  "it": "Guida del collaboratore", "nl": "Handleiding voor bijdragers", "pt": "Guia do colaborador",
                  "en": "Contributor guide"}
        for langue, titre in titres.items():
            self.connecter("contributeur", langue)
            r = self.client.get(reverse("collecte:aide"))
            self.assertContains(r, titre, msg_prefix=langue)
            self.assertContains(r, f'class="guide-corps" lang="{langue}"')
            self.assertNotContains(r, 'class="aide-champ"', msg_prefix=langue)  # la note ne sert qu'à une langue sans guide

    def test_langue_sans_guide_recoit_le_guide_anglais_avec_une_note(self):
        self.connecter("contributeur", "de")
        with mock.patch.object(AI, "LANGUES_GUIDES", ("en", "fr")):
            r = self.client.get(reverse("collecte:aide"))
        self.assertContains(r, "Contributor guide")
        self.assertContains(r, "Die Anleitungen sind in Ihrer Sprache noch nicht verfügbar.")
        self.assertContains(r, 'class="guide-corps" lang="en"')

    def test_lecteur_et_auditeur_lisent_tous_les_guides(self):
        for role in ("lecteur", "auditeur"):
            self.connecter(role, "en")
            for g in AI.GUIDES:
                self.assertEqual(self.client.get(reverse("collecte:aide_guide", args=[g])).status_code, 200, (role, g))
            self.assertEqual(self.client.post(reverse("collecte:aide")).status_code, 403)  # aucune écriture

    def test_guide_inconnu_et_images_piegees(self):
        self.connecter("admin")
        self.assertEqual(self.client.get(reverse("collecte:aide_guide", args=["inconnu"])).status_code, 404)
        for langue, nom in (("xx", "dashboard.png"), ("en", "..%2Fx.png"), ("en", "Dashboard.png"), ("en", "absent.png"),
                            ("en", "dashboard.jpg")):
            r = self.client.get(f"/aide/images/{langue}/{nom}")
            self.assertEqual(r.status_code, 404, (langue, nom))

    def test_image_servie_aux_personnes_connectees(self):
        self.connecter("lecteur")
        r = self.client.get(reverse("collecte:aide_image", args=["en", "dashboard.png"]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "image/png")
        self.assertTrue(b"".join(r.streaming_content).startswith(b"\x89PNG"))

    def test_page_du_guide_a_ses_ancres_images_et_pas_de_html_injecte(self):
        self.connecter("admin", "en")
        r = self.client.get(reverse("collecte:aide"))
        self.assertContains(r, '<h2 id="campaign">')
        self.assertContains(r, 'href="#campaign"')
        self.assertContains(r, "/aide/images/en/admin-campaigns.png")
        self.assertNotContains(r, "French version")  # la phrase qui renvoie à l'autre langue est retirée
        corps = AI._rendre("## T {#t}\n\n<script>alert(1)</script> **x**\n\n![a](https://exemple.test/x.png)\n", "en")[1]
        self.assertNotIn("<script>", corps)
        self.assertNotIn("<img", corps)  # seule une image de docs/screenshots/ est chargée

    def test_lien_d_aide_sur_les_pages_et_bonne_section(self):
        attendu = {"admin": ("collecte:admin_campagnes", "campaign"), "validateur": ("collecte:relances", "reminders"),
                   "contributeur": ("collecte:coherence", "check"), "lecteur": ("collecte:tableau_de_bord", "dashboard"),
                   "auditeur": ("collecte:historique", "history")}
        for role, (nom, section) in attendu.items():
            self.connecter(role, "en")
            r = self.client.get(reverse(nom))
            self.assertEqual(r.status_code, 200, (role, nom))
            self.assertContains(r, f'class="aide-haut" href="{reverse("collecte:aide")}#{section}"', msg_prefix=role)
            self.assertContains(r, 'aria-label="Help"')
            for page in PAGES_PRINCIPALES:
                self.assertContains(self.client.get(reverse(page)), 'class="aide-haut"', msg_prefix=f"{role} {page}")

    def test_pas_de_lien_d_aide_sans_connexion(self):
        self.assertNotContains(self.client.get(reverse("login")), "aide-haut")

    def test_toute_section_declaree_existe_dans_chaque_guide(self):
        for table in [SEC for SEC in AI.SECTIONS.values()] + [p[1] for p in AI.PREFIXES]:
            for guide, ancre in table.items():
                for langue in AI.LANGUES_GUIDES:
                    self.assertIn(ancre, AI.ancres(guide, langue), (guide, langue, ancre))


class GuidesContenuTests(TestCase):
    def test_images_citees_presentes_et_aucune_orpheline(self):
        citees = set()
        for g, langue, chemin, texte in guides():
            for alt, src in re.findall(r"!\[([^\]]*)\]\(([^)]+)\)", texte):
                m = re.fullmatch(r"(?:\.\./)+screenshots/(en|fr|es|de|it|nl|pt)/([a-z0-9_-]+\.png)", src)
                self.assertTrue(m, (chemin.name, src))
                self.assertEqual(m.group(1), langue, (chemin.name, src))  # le guide français cite les captures françaises
                self.assertTrue((RACINE / "docs" / "screenshots" / m.group(1) / m.group(2)).is_file(), (chemin.name, src))
                self.assertTrue(alt.strip(), (chemin.name, src))
                citees.add((m.group(1), m.group(2)))
        for chemin in (RACINE / "docs").glob("**/installation.md"):
            for src in re.findall(r"!\[[^\]]*\]\(([^)]+\.png)\)", chemin.read_text(encoding="utf-8")):
                m = re.search(r"screenshots/(en|fr)/([a-z0-9_-]+\.png)$", src)
                self.assertTrue(m, (chemin, src))
                self.assertTrue((RACINE / "docs" / "screenshots" / m.group(1) / m.group(2)).is_file(), (chemin, src))
                citees.add((m.group(1), m.group(2)))
        presentes = {(p.parent.name, p.name) for p in (RACINE / "docs" / "screenshots").glob("*/*.png")}
        self.assertEqual(presentes - citees, set(), "images que personne ne cite")
        self.assertFalse(list((RACINE / "docs" / "screenshots").glob("*.png")), "image hors des dossiers de langue")

    def test_poids_et_nombre_des_images(self):
        for langue in AI.LANGUES_GUIDES:
            fichiers = list((RACINE / "docs" / "screenshots" / langue).glob("*.png"))
            self.assertLessEqual(len(fichiers), 35, langue)
            for f in fichiers:
                self.assertLessEqual(f.stat().st_size, 300 * 1024, f.name)

    def test_memes_ancres_et_memes_images_dans_les_sept_langues(self):
        for g in AI.GUIDES:
            reference = [a for a, _ in AI.lire(g, "en")[2]]
            images_en = re.findall(r"screenshots/en/([a-z0-9_-]+\.png)", AI.chemin_guide(g, "en").read_text(encoding="utf-8"))
            for langue in AI.LANGUES_GUIDES:
                self.assertEqual([a for a, _ in AI.lire(g, langue)[2]], reference, (g, langue))
                texte = AI.chemin_guide(g, langue).read_text(encoding="utf-8")
                self.assertEqual(re.findall(r"screenshots/[a-z]{2}/([a-z0-9_-]+\.png)", texte), images_en, (g, langue))

    def test_meme_structure_que_le_guide_anglais(self):
        """Garde-fou contre le retard d'une traduction : par section (même ancre), le guide d'une langue a autant de
        paragraphes, d'éléments de liste et d'images que le guide anglais. Une section ajoutée ou un point ajouté
        en anglais seulement fait échouer le test, avec le guide et la section à rattraper."""
        def structure(texte):
            sections = {}
            for bloc in re.split(r"(?m)^(?=## )", texte)[1:]:
                m = re.match(r"## .*\{#([a-z0-9-]+)\}", bloc)
                lignes = [ln for ln in bloc.split("\n")[1:] if ln.strip()]
                items = sum(1 for ln in lignes if re.match(r"\s*(\d+\.|-)\s", ln))
                images = sum(1 for ln in lignes if ln.startswith("!["))
                paragraphes = 0
                precedent_liste = False
                for ln in bloc.split("\n")[1:]:
                    if not ln.strip():
                        continue
                    est_item = bool(re.match(r"\s*(\d+\.|-)\s", ln)) or ln.startswith("![")
                    if not est_item and not ln.startswith("   ") and not ln.startswith("\t"):
                        paragraphes += 1
                    elif not est_item and ln.startswith("   ") and not precedent_liste:
                        paragraphes += 1
                    precedent_liste = est_item or (precedent_liste and ln.startswith("   "))
                sections[m.group(1)] = (paragraphes, items, images)
            return sections

        ecarts = []
        for g in AI.GUIDES:
            ref = structure(AI.chemin_guide(g, "en").read_text(encoding="utf-8"))
            for langue in AI.LANGUES_GUIDES:
                if langue == "en":
                    continue
                autre = structure(AI.chemin_guide(g, langue).read_text(encoding="utf-8"))
                for ancre, (p, i, im) in ref.items():
                    q = autre.get(ancre)
                    if q != (p, i, im):
                        ecarts.append(f"{AI.chemin_guide(g, langue).relative_to(RACINE)} section {{#{ancre}}} : "
                                      f"{q} (paragraphes, éléments de liste, images) au lieu de {(p, i, im)} en anglais")
        self.assertEqual(ecarts, [], "Guides en retard sur l'anglais : à rattraper section par section\n" + "\n".join(ecarts))

    def test_ancres_uniques(self):
        for g, langue, chemin, texte in guides():
            ids = re.findall(r"\{#([a-z0-9-]+)\}", texte)
            self.assertEqual(len(ids), len(set(ids)), chemin.name)

    def test_libelles_en_gras_existent_dans_la_langue_du_guide(self):
        """Chaque libellé en gras d'un guide (chemin « A › B » coupé en morceaux) est un texte de ``libelles/`` de sa langue,
        ou le contenu d'un gras d'un texte (« <strong>Choose a file</strong> or drag it here »)."""
        for langue in AI.LANGUES_GUIDES:
            valeurs = set()
            for f in glob.glob(str(RACINE / "libelles" / f"*.{langue}.json")):
                for v in json.load(open(f, encoding="utf-8")).values():
                    textes = [v] if isinstance(v, str) else [t for t in v.values() if isinstance(t, str)] if isinstance(v, dict) else []
                    for t in textes:
                        valeurs.add(t.strip())
                        valeurs.update(re.findall(r"<strong>(.*?)</strong>", t))
                        valeurs.add(re.sub(r"<[^>]+>", "", t).strip())
            inconnus = []
            for g, lg, chemin, texte in guides():
                if lg != langue:
                    continue
                for gras in re.findall(r"\*\*([^*]+)\*\*", texte):
                    for morceau in (m.strip() for m in gras.split("›")):
                        if morceau not in valeurs:
                            inconnus.append((chemin.name, morceau))
            self.assertEqual(inconnus, [], langue)

    def test_pas_de_mot_interdit(self):
        for g, langue, chemin, texte in guides():
            self.assertNotRegex(texte, r"\bRSE\b", chemin.name)

    @unittest.skipUnless(INTERDITS.present(), INTERDITS.SAUTE)
    def test_aucun_nom_interdit(self):
        """Aucun mot ni couleur interdits (liste hors du dépôt : ``parametres/aides_tests/interdits.py``)."""
        for g, langue, chemin, texte in guides():
            self.assertEqual(INTERDITS.nombre_trouves(texte), 0, f"{langue}/{chemin.name}")
