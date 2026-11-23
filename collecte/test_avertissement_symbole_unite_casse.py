"""Symbole d'une unité utilisée : un changement qui ne touche que la casse est accepté (règle du projet,
P5 : « kwh » → « kWh »), mais demande une confirmation quand la casse peut changer le sens (règle à confirmer) :

- la première lettre passe de m à M, k à K, g à G, p à P ou t à T (ou l'inverse) : un préfixe ou un symbole métrique
  (milli / méga, kilo / kelvin, gramme / giga, pico / péta, tonne / téra) ;
- le nouveau symbole est, à la casse près, celui d'une AUTRE unité de l'installation, ou d'une unité du catalogue écrite
  autrement (« ML » quand le catalogue a « mL » et « ML »).

Un autre changement de sens (« m³ » → « L ») reste refusé. Portes : page Unités et formats (case à cocher puis
« Enregistrer » de nouveau), onglet « Unités » du classeur de configuration (avertissement sur la ligne de l'aperçu, que
l'administrateur relit avant « Importer », comme pour une date d'ouverture). Le fichier référentiel ne change jamais le
symbole d'une unité existante (il la reprend ou en crée une) : rien à contrôler."""
import io

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from collecte.models import Journal
from parametres.models import Unite

from . import reglages as R
from .aides_tests.arbre_france import Arbre
from .models import Reponse


class Base(Arbre):
    def setUp(self):
        super().setUp()
        self.u = Unite.objects.create(code="u-test", symbole="kvarh", libelle="kilovar-heure", ordre=1, decimales=0)
        self.kpi("ELEC", unite=self.u, type_reponse_id="Numérique")
        self.saisir("ELEC", self.e1, 1234, camp=self.c0)

    def symbole(self, s):
        self.u.symbole = s
        self.u.save()


class RegleCasseTests(Base):
    def avert(self, avant, apres, traductions=None):
        return R.avertissement_symbole_unite("u-test", (avant, traductions or {}), (apres, traductions or {}))

    def motif(self, avant, apres):
        return R.motif_symbole_unite("u-test", (avant, {}), (apres, {}))

    def test_casse_seule(self):
        for a, b in (("kwh", "kWh"), ("mw", "MW"), ("t co2e", "tCO₂e"), ("m3", "M³")):
            self.assertTrue(R.casse_seule(a, b), (a, b))
        for a, b in (("m3", "m³"), ("kWh", "kWh"), ("m³", "L"), ("kWh", "MWh")):
            self.assertFalse(R.casse_seule(a, b), (a, b))

    def test_casse_acceptee_sans_avertissement(self):
        for avant, apres in (("kvarh", "kVArh"), ("hl", "hL"), ("kvarh", "kVARH")):
            with self.subTest(avant=avant, apres=apres):
                self.symbole(avant)
                self.assertEqual(self.motif(avant, apres), "")
                self.assertEqual(self.avert(avant, apres), "")

    def test_prefixe_metrique_a_confirmer(self):
        for avant, apres in (("mw", "MW"), ("MW", "mW"), ("mg", "Mg"), ("m", "M"), ("kwh", "KWH"), ("gj", "GJ"),
                             ("pj", "PJ"), ("tco2e", "TCO2E")):
            with self.subTest(avant=avant, apres=apres):
                self.symbole(avant)
                self.assertEqual(self.motif(avant, apres), "")  # pas refusé
                self.assertIn(f"« {apres} »", self.avert(avant, apres))

    def test_autre_unite_a_confirmer(self):
        Unite.objects.create(code="u-autre", symbole="Nm3", libelle="normo mètre cube", ordre=2)
        self.symbole("nm3")
        self.assertIn("« Nm3 »", self.avert("nm3", "NM3"))  # « NM3 » : à la casse près, l'unité « Nm3 »
        self.assertIn("« Nm3 »", self.avert("nm3", "Nm3"))  # le symbole même d'une autre unité
        self.symbole("ml")
        self.assertIn("« mL »", self.avert("ml", "ML"))  # catalogue : « mL » (millilitre) et « ML » (mégalitre)
        if not Unite.objects.filter(symbole="kWh").exists():
            Unite.objects.create(code="u-kwh", symbole="kWh", libelle="kilowattheure", ordre=3)
        self.symbole("kwh")
        self.assertIn("« kWh »", self.avert("kwh", "kWh"))  # deux unités au même symbole : à confirmer

    def test_traduction_du_symbole(self):
        self.assertNotEqual(R.avertissement_symbole_unite("u-test", ("kvarh", {"en": {"symbole": "mw"}}),
                                                          ("kvarh", {"en": {"symbole": "MW"}})), "")
        self.assertEqual(R.motif_symbole_unite("u-test", ("kvarh", {"en": {"symbole": "mw"}}),
                                               ("kvarh", {"en": {"symbole": "MW"}})), "")

    def test_sans_valeurs_rien_a_confirmer(self):
        Reponse.objects.all().delete()
        self.assertEqual(self.avert("mw", "MW"), "")

    def test_changement_de_sens_toujours_refuse(self):
        self.assertNotEqual(self.motif("kvarh", "MWh"), "")
        self.assertNotEqual(self.motif("kvarh", "L"), "")


class PageUnitesCasseTests(Base):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)

    def envoyer(self, symbole, **plus):
        return self.client.post(reverse("parametres:referentiel") + "?section=unites", {
            "action": "enregistrer", "nb": "1", "code__0": "u-test", "symbole__0": symbole, "libelle__0": "kilovar-heure",
            "famille__0": "", "decimales__0": "0", **plus})

    def test_correction_de_casse_acceptee(self):
        self.assertEqual(self.envoyer("kVArh").status_code, 302)
        self.assertEqual(Unite.objects.get(pk="u-test").symbole, "kVArh")
        self.assertTrue(Journal.objects.filter(action="reglage_referentiel", champ="symbole", avant="kvarh", apres="kVArh").exists())

    def test_prefixe_demande_une_confirmation(self):
        self.symbole("mw")
        rep = self.envoyer("MW")
        self.assertEqual(rep.status_code, 200)
        page = rep.content.decode()
        self.assertIn('name="confirmer_casse"', page)
        self.assertIn('value="MW"', page)  # la saisie est gardée
        self.assertEqual(Unite.objects.get(pk="u-test").symbole, "mw")
        self.assertEqual(self.envoyer("MW", confirmer_casse="1").status_code, 302)
        self.assertEqual(Unite.objects.get(pk="u-test").symbole, "MW")

    def test_changement_de_sens_refuse_meme_confirme(self):
        rep = self.envoyer("MWh", confirmer_casse="1")
        self.assertEqual(rep.status_code, 200)
        self.assertEqual(Unite.objects.get(pk="u-test").symbole, "kvarh")


class ClasseurUnitesCasseTests(Base):
    def classeur(self, symbole):
        from openpyxl import load_workbook

        from . import configuration as C

        wb = load_workbook(io.BytesIO(C.exporter().content))
        ws = wb["Unités"]
        tete = [c.value for c in ws[1]]
        col = next(i for i, t in enumerate(tete) if str(t).startswith("Symbole")) + 1
        for r in range(2, ws.max_row + 1):
            if ws.cell(r, 1).value == "u-test":
                ws.cell(r, col, symbole)
        flux = io.BytesIO()
        wb.save(flux)
        return flux.getvalue()

    def ligne(self, symbole):
        from . import configuration as C

        a = C.analyser(SimpleUploadedFile("conf.xlsx", self.classeur(symbole)))
        return next(c for c in a.onglets["Unités"] if c.cle == "u-test")

    def test_casse_acceptee_sans_avertissement(self):
        ligne = self.ligne("kVArh")
        self.assertEqual((ligne.action, ligne.avertissement), ("modifier", ""))

    def test_prefixe_avertissement_dans_l_apercu(self):
        from . import configuration as C

        self.symbole("mw")
        ligne = self.ligne("MW")
        self.assertEqual(ligne.action, "modifier")
        self.assertIn("« MW »", ligne.avertissement)
        C.appliquer(self.admin, SimpleUploadedFile("conf.xlsx", self.classeur("MW")))
        self.assertEqual(Unite.objects.get(pk="u-test").symbole, "MW")

    def test_changement_de_sens_rejete(self):
        self.assertEqual(self.ligne("MWh").action, "rejet")
