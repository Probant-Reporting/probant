"""Fichiers de langue de l'interface (parametres/libelles.py) : mêmes clés et mêmes paramètres dans chaque langue,
repli, pluriel, clés utilisées dans le code toutes présentes."""
import json
import re
from pathlib import Path

from django.conf import settings
from django.template import Context, Template
from django.test import TestCase

from parametres import langues as L
from parametres import libelles as LB
from parametres.models import Instance, Langue
from django.test import SimpleTestCase

BASE = Path(settings.BASE_DIR)
UTILISEES = re.compile(r"""(?:\{%\s*libelle(?:_html)?\s+|\b(?:libelle|lib|t)\(\s*)["']((?:visu|format|cadre|commun|saisie|suivi|admin|"""
                       r"""referentiels|messages)\.[\w.]*\w)["']""")


def parametres(texte):
    textes = texte.values() if isinstance(texte, dict) else [texte]
    return {m for t in textes for m in LB.PARAMETRE.findall(t)}


class FichiersTests(TestCase):
    def test_memes_cles_et_parametres(self):
        """Visualisation : français et anglais complets (les autres zones et l'espagnol : parametres/test_traduction.py)."""
        langues = LB.langues_disponibles()
        self.assertIn("fr", langues)
        self.assertIn("en", langues)
        fr = {k: v for k, v in LB.table("fr").items() if k.startswith(("visu.", "format."))}
        self.assertGreater(len(fr), 100)
        for langue in ("en",):
            autre = {k: v for k, v in LB.table(langue).items() if k.startswith(("visu.", "format."))}
            with self.subTest(langue=langue):
                self.assertEqual(set(autre), set(fr))
                for cle, texte in fr.items():
                    self.assertEqual(parametres(autre[cle]), parametres(texte), cle)
                    self.assertEqual(isinstance(autre[cle], dict), isinstance(texte, dict), cle)
                    if isinstance(texte, dict):
                        self.assertEqual(set(texte), {"one", "other"}, cle)
                        self.assertEqual(set(autre[cle]), {"one", "other"}, cle)

    def test_fichiers_bien_formes(self):
        for p in (BASE / "libelles").glob("*.json"):
            with self.subTest(fichier=p.name):
                d = json.loads(p.read_text(encoding="utf-8"))
                self.assertTrue(all(re.fullmatch(r"[a-z0-9_]+(\.[a-z0-9_]+)+", k) for k in d))
                self.assertTrue(all(isinstance(v, (str, dict)) for v in d.values()))

    def test_cles_utilisees_existent(self):
        fichiers = [p for d in ("collecte", "parametres", "templates", "static/js") for p in (BASE / d).rglob("*")
                    if p.suffix in (".py", ".html", ".js") and "test_" not in p.name and "migrations" not in p.parts]
        trouvees = set()
        for p in fichiers:
            trouvees |= set(UTILISEES.findall(p.read_text(encoding="utf-8")))
        manquantes = sorted(c for c in trouvees if c not in LB.table("fr"))
        self.assertEqual(manquantes, [])


class LibelleTests(TestCase):
    def test_parametres_et_pluriel_francais(self):
        self.assertEqual(LB.libelle("visu.vue.copie_de", "fr", nom="Énergie"), "Copie de Énergie")
        self.assertEqual(LB.libelle("visu.kpi.nb", "fr", n=0), "0 KPI")
        self.assertEqual(LB.libelle("visu.vue.masques", "fr", n=1), "1 visuel de cette vue ne vous concerne pas.")
        self.assertEqual(LB.libelle("visu.vue.masques", "fr", n=0), "0 visuel de cette vue ne vous concerne pas.")
        self.assertEqual(LB.libelle("visu.vue.masques", "fr", n=2), "2 visuels de cette vue ne vous concernent pas.")

    def test_pluriel_anglais(self):
        self.assertEqual(LB.libelle("visu.kpi.nb", "en", n=0), "0 KPIs")
        self.assertEqual(LB.libelle("visu.kpi.nb", "en", n=1), "1 KPI")

    def test_parametre_manquant_garde_tel_quel(self):
        self.assertEqual(LB.libelle("visu.vue.copie_de", "fr"), "Copie de {nom}")

    def test_repli(self):
        """Clé pas encore traduite (langue sans fichier de langue, ici le japonais) : langue par défaut de l'installation, puis français ; clé
        inconnue : la clé."""
        self.assertEqual(LB.libelle("visu.vue.renommer", "ja"), "Renommer")
        Langue.objects.get_or_create(code="en", defaults={"libelle": "English"})
        i = Instance.courante()
        i.langue = "en"
        i.save()
        with L.session():
            self.assertEqual(LB.libelle("visu.vue.renommer", "ja"), "Rename")
            self.assertEqual(LB.libelle("visu.vue.renommer"), "Rename")  # langue courante : défaut de l'installation
            self.assertEqual(LB.libelle("visu.vue.renommer", "fr"), "Renommer")
            self.assertEqual(LB.libelle("visu.vue.renommer", "en-GB"), "Rename")  # variante : langue de base
        self.assertEqual(LB.libelle("visu.cle.inconnue", "fr"), "visu.cle.inconnue")

    def test_libelles_pour_le_javascript(self):
        d = LB.libelles("visu.type.", "en")
        self.assertEqual(d["visu.type.anneau"], "Donut")
        self.assertTrue(all(k.startswith("visu.type.") for k in d))
        self.assertEqual(LB.libelles("visu.", "ja")["visu.type.anneau"], "Anneau")  # repli sur le français

    def test_etiquette_de_gabarit(self):
        t = Template('{% load collecte %}{% libelle "visu.deplace" titre="<b>X</b>" position=2 total=6 %}|{% libelle "visu.kpi.nb" n=3 %}')
        self.assertEqual(t.render(Context()), "Visuel « &lt;b&gt;X&lt;/b&gt; » déplacé en position 2 sur 6.|3 KPI")


class TextesTests(SimpleTestCase):
    def test_plus_d_equipe_responsable_dans_les_phrases(self):
        gardees = {"saisie.fiche.equipe", "suivi.fichier.entete.equipe_responsable", "choix.kpi.equipe_responsable"}
        for p in Path(settings.BASE_DIR, "libelles").glob("*.json"):
            for cle, v in json.loads(p.read_text(encoding="utf-8")).items():
                textes = v.values() if isinstance(v, dict) else [v]
                for t in textes:
                    if cle not in gardees:
                        for mot in ("équipe responsable", "responsible team", "equipo responsable"):
                            self.assertNotIn(mot, t.lower(), f"{p.name} {cle}")

    def test_singulier_pour_un_seul_kpi(self):
        self.assertEqual(LB.libelle("referentiels.installer.resume.ajout", "fr", n=1, existant="GES"),
                         "<b>1 KPI</b> va être ajouté à « GES ». Rien n'est retiré.")
        self.assertIn("vont être ajoutés", LB.libelle("referentiels.installer.resume.ajout", "fr", n=3, existant="GES"))
        self.assertIn("va être installé", LB.libelle("referentiels.installer.resume.installes", "fr", n=1, nom="X", themes="1 thème"))
        self.assertIn("il reste dans le catalogue", LB.libelle("referentiels.vues.kpi_retires", "fr", n=1, referentiel="X"))
        self.assertEqual(LB.libelle("admin.accueil.kpi_actifs", "fr", n=1), "1 KPI actif")
        self.assertEqual(LB.libelle("admin.accueil.kpi_actifs", "en", n=1), "1 active KPI")
        self.assertEqual(LB.libelle("saisie.js.kpi_coches", "fr", n=1), "KPI coché")
