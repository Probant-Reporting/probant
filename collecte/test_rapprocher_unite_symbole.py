"""Rapprochement des unités à l'import d'un fichier référentiel, à l'installation d'un modèle de la bibliothèque et dans le
classeur de configuration (``parametres.rapprochement_unites.rapprocher_unite``) : symbole exact (NFKC, sans
espaces), code, traduction exacte ; jamais une forme sans symboles (« €/h » n'est pas « h ») ; un écart de casse seul est
rapproché avec un avertissement, sauf quand la casse peut changer le sens (« MW » n'est pas « mW »). Données inventées."""
import uuid

from django.test import SimpleTestCase, TestCase

from collecte import configuration as CF
from collecte import paquets as P
from collecte.outils_tests import xlsx
from parametres.models import NiveauHierarchique, TypeReponse, TypeSaisie, Unite
from parametres.rapprochement_unites import rapprocher_unite
from referentiel.models import KPI, Niveau
from .aides_tests.bibliotheque_essai import BibliothequeEssai


def u(code, symbole, libelle="", **trad):
    return Unite(code=code, symbole=symbole, libelle=libelle, traductions={lg: {"symbole": s} for lg, s in trad.items()})


class RegleTests(SimpleTestCase):
    def setUp(self):
        self.unites = [u("h", "h", "heure"), u("M€", "M€", "million d'euros"), u("k€", "k€"), u("mW", "mW", "milliwatt"),
                       u("kWh", "kWh", "kilowattheure"), u("m³", "m³"), u("sal", "salariés", en="employees")]

    def trouve(self, *textes, **kw):
        r = rapprocher_unite(textes, self.unites, **kw)
        return r.unite.code if r.unite else None

    def test_jamais_une_forme_sans_symboles(self):
        for t in ("€/h", "m", "M", "k", "MW", "h.", "k-€"):
            self.assertIsNone(self.trouve(t), t)

    def test_symbole_exact_code_et_traductions(self):
        self.assertEqual(self.trouve("m3"), "m³")  # NFKC
        self.assertEqual(self.trouve("k €"), "k€")  # espaces retirés
        self.assertEqual(self.trouve("employees"), "sal")  # traduction du symbole
        self.assertEqual(self.trouve("kilowattheure"), "kWh")  # libellé exact
        self.assertEqual(self.trouve("sal"), "sal")  # code

    def test_casse_seule(self):
        r = rapprocher_unite(["kwh"], self.unites)
        self.assertEqual((r.unite.code, r.casse, r.texte), ("kWh", "kWh", "kwh"))  # même première lettre : rapproché, à dire
        r = rapprocher_unite(["MW"], self.unites)
        self.assertEqual((r.unite, r.ecartee), (None, "mW"))  # m / M : la casse change le sens, unité créée à part
        self.assertIsNone(rapprocher_unite(["kwh"], self.unites, casse=False).unite)

    def test_code_du_paquet_prefere_s_il_a_le_meme_symbole(self):
        unites = [u("kWh", "kWh"), u("kWh2", "kWh")]
        self.assertEqual(rapprocher_unite(["kWh"], unites, code="kWh2").unite.code, "kWh2")
        self.assertEqual(rapprocher_unite(["MWh"], [u("kWh", "kWh")], code="kWh").unite, None)


class PaquetTests(BibliothequeEssai, TestCase):
    def test_modele_vs_base_euro_par_heure(self):
        self.assertTrue(Unite.objects.filter(symbole="h").exists())  # unité de départ de toute installation
        a = P.analyser(P.fourni("vs_base.json").paquet, fourni=True)
        r = next(x for x in a.reglages if x.genre == "unite" and x.code == "€/h")
        self.assertEqual(r.action, "cree")
        P.appliquer(None, a)
        for code in ("SOC-REMU-H-HOMMES", "SOC-REMU-H-FEMMES"):
            self.assertEqual(KPI.objects.get(pk=code).unite.symbole, "€/h")

    def _paquet(self, unite, kpi_unite=None):
        p = P.fourni("socle_energie.json").paquet
        p.unites.append(unite)
        p.kpis[0]["unite"] = kpi_unite or unite["code"]
        p.referentiel["identifiant"], p.referentiel["code"] = str(uuid.uuid4()), "RESSAI"
        return P.analyser(p)

    def test_metre_et_megawatt_crees(self):
        Unite.objects.create(code="mW", symbole="mW", libelle="milliwatt", ordre=99)
        a = self._paquet({"code": "m", "symbole": {"fr": "m", "en": "m"}, "libelle": {"fr": "mètre"}, "decimales": 1})
        self.assertEqual([(x.action, x.libelle_local) for x in a.reglages if x.code == "m"], [("cree", "m")])
        a = self._paquet({"code": "MW", "symbole": {"fr": "MW", "en": "MW"}, "libelle": {"fr": "mégawatt"}, "decimales": 1})
        self.assertEqual([(x.action, x.libelle_local) for x in a.reglages if x.code == "MW"], [("cree", "MW")])
        self.assertTrue(any("mW" in t and "MW" in t for t in a.avertissements), a.avertissements)

    def test_casse_sans_risque_reprise_avec_avertissement(self):
        a = self._paquet({"code": "kwh", "symbole": {"fr": "kwh", "en": "kwh"}, "libelle": {"fr": "kilowattheure"}})
        self.assertEqual([(x.action, x.code_local) for x in a.reglages if x.code == "kwh"], [("repris", "kWh")])
        self.assertTrue(any("kwh" in t and "kWh" in t for t in a.avertissements), a.avertissements)

    def test_unite_citee_seulement_dans_l_onglet_kpi(self):
        p = P.fourni("socle_energie.json").paquet
        p.kpis[0]["unite"] = "€/h"
        p.referentiel["identifiant"], p.referentiel["code"] = str(uuid.uuid4()), "RESSAI"
        a = P.analyser(p)
        self.assertEqual([(x.action, x.libelle_local) for x in a.reglages if x.code == "€/h"], [("cree", "€/h")])


class ClasseurTests(TestCase):
    def setUp(self):
        Unite.objects.get_or_create(code="mW", defaults=dict(symbole="mW", libelle="milliwatt", ordre=99))

    def test_cellules(self):
        cles = CF._cles_objets({x.code: x for x in Unite.objects.all()})
        for t in ("m", "M", "k", "MW", "€/h"):
            with self.assertRaises(ValueError, msg=t):
                CF.depuis_cellule(t, "unite", cles)
        self.assertEqual(CF.depuis_cellule("m3", "unite", cles), "m³")
        self.assertEqual(CF.depuis_cellule("kwh", "unite", cles), "kWh")

    def test_onglet_kpi_cree_l_unite_voulue(self):
        saisie = TypeSaisie.objects.filter(comportement=TypeSaisie.Comportement.SAISIE).first()
        nombre = TypeReponse.objects.filter(format=TypeReponse.Format.NOMBRE).first()
        site = NiveauHierarchique.objects.get(code=Niveau.SITE)
        entetes = ["ID KPI", "Nom (FR)", "Type de saisie", "Type de réponse", "Unité", "Granularité"]
        lignes = [entetes] + [[f"K-{i}", f"Essai {i}", saisie.libelle, nombre.libelle, t, site.nom]
                              for i, t in enumerate(("m", "MW", "kwh", "€/h"))]
        a = CF.analyser(xlsx({"KPI": lignes}))
        kpis = {ch.cle: ch for ch in a.onglets["KPI"]}
        self.assertEqual({c: (ch.action, ch.objet.unite_id) for c, ch in kpis.items()},
                         {"K-0": ("creer", "m"), "K-1": ("creer", "MW"), "K-2": ("creer", "kWh"), "K-3": ("creer", "€/h")})
        self.assertEqual(sorted(ch.cle for ch in a.onglets["Unités"]), ["MW", "m", "€/h"])
        self.assertIn("kWh", kpis["K-2"].avertissement)
