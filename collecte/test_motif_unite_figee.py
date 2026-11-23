"""Unité d'un KPI figée par ses valeurs (règle du projet, « N3 ») : comme le format, l'unité d'un KPI qui a
des réponses saisies ou importées (validées ou en brouillon, dans toute période) ne change plus. Sinon, 1 234 m³ de 2025
se lisent 1 234 L à côté de 2026, dans l'écran, les exports et la comparaison N-1.

Mêmes contrôles à toutes les portes : fiche KPI, fichier du référentiel (format historique), classeur de configuration,
fichier référentiel et mise à jour d'un modèle de la bibliothèque (paquet : la ligne est rejetée, le KPI reste tel quel).
Page Unités et formats, onglet « Unités » du classeur : le symbole d'une unité dont un KPI a des valeurs ne change plus,
sauf une correction d'écriture (« m3 » → « m³ ») ; ses décimales par défaut restent réglables (elles ne changent pas le
sens des valeurs : chaque KPI garde les siennes)."""
import io
import tempfile
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from parametres.models import Unite
from referentiel.models import KPI

from . import reglages as R
from .aides_tests.arbre_france import Arbre
from .models import Reponse

D = Decimal


def donnees_fiche(k, **changes):
    """Fiche KPI telle que la page l'envoie, avec ``changes``."""
    form = R.KPIForm(instance=k)
    donnees = {n: form[n].value() for n in form.fields if form[n].value() not in (None, False, "")}
    donnees.update(version=R.version_kpi(k), **changes)
    return donnees


class UniteFigeeTests(Arbre):
    """EAU (m³) a une valeur importée et validée dans l'exercice 2025 clôturé ; NEUF (m³) n'a aucune valeur."""

    def setUp(self):
        super().setUp()
        self.m3, self.litre = Unite.objects.get(code="m³"), Unite.objects.get(code="L")  # unités fournies
        self.eau = self.kpi("EAU", unite=self.m3, type_reponse_id="Numérique")
        self.neuf = self.kpi("NEUF", unite=self.m3, type_reponse_id="Numérique")
        self.saisir("EAU", self.e1, 1234, camp=self.c0)

    def test_motif(self):
        motif = R.motif_unite_figee("EAU", self.m3, self.litre)
        self.assertTrue(motif.startswith("Ce KPI a déjà 1 valeur en « m³ » : son unité ne peut donc plus changer."), motif)
        self.assertIn("créez un nouveau KPI", motif)
        self.assertEqual(R.motif_unite_figee("EAU", self.m3, self.m3), "")
        self.assertEqual(R.motif_unite_figee("NEUF", self.m3, self.litre), "")  # aucune valeur : libre
        self.assertTrue(R.motif_unite_figee("EAU", self.m3, None))  # retirer l'unité : refusé aussi
        self.kpi("SANS", type_reponse_id="Numérique")
        self.saisir("SANS", self.e1, 3)
        self.assertTrue(R.motif_unite_figee("SANS", None, self.litre).startswith("Ce KPI a déjà 1 valeur, sans unité :"))

    def test_brouillon_et_valeurs_calculees(self):
        """Un brouillon saisi compte ; une valeur calculée, un agrégat, un N/A ne comptent pas (ils n'ont pas de sens
        propre dans l'unité, comme pour le format)."""
        Reponse.objects.create(periode=self.c.periode, kpi=self.neuf, organisation=self.e2, valeur=D(5),
                               origine=Reponse.Origine.SAISIE, statut=Reponse.Statut.BROUILLON)
        self.assertTrue(R.motif_unite_figee("NEUF", self.m3, self.litre))
        autre = self.kpi("AUTRE", unite=self.m3, type_reponse_id="Numérique")
        Reponse.objects.create(periode=self.c.periode, kpi=autre, organisation=self.fr, valeur=D(5), origine=Reponse.Origine.AGREGATION)
        self.saisir("AUTRE", self.e1, na=True)
        self.assertEqual(R.motif_unite_figee("AUTRE", self.m3, self.litre), "")

    def test_fiche_kpi(self):
        form = R.KPIForm(donnees_fiche(self.eau, unite=self.litre.pk, confirmer="on"), instance=self.eau)
        self.assertFalse(form.is_valid())
        self.assertIn("son unité ne peut donc plus changer", " ".join(form.errors["unite"]))
        self.assertEqual(KPI.objects.get(pk="EAU").unite_id, "m³")
        form = R.KPIForm(donnees_fiche(self.neuf, unite=self.litre.pk), instance=self.neuf)
        self.assertTrue(form.is_valid(), form.errors)
        form = R.KPIForm(donnees_fiche(self.eau, decimales=3), instance=self.eau)  # le reste de la fiche reste réglable
        self.assertTrue(form.is_valid(), form.errors)

    def test_fiche_kpi_par_la_page(self):
        self.client.force_login(self.admin)
        url = reverse("collecte:referentiel_kpi", args=["EAU"])
        rep = self.client.post(url, donnees_fiche(self.eau, unite=self.litre.pk, confirmer="on"), HTTP_X_REQUESTED_WITH="fetch")
        self.assertFalse(rep.json().get("ok"))
        self.assertIn("son unité ne peut donc plus changer", rep.json().get("html", ""))
        self.assertEqual(KPI.objects.get(pk="EAU").unite_id, "m³")

    def test_fichier_du_referentiel_historique(self):
        from openpyxl import load_workbook

        from referentiel.echange import exporter_kpi, importer_kpi

        with tempfile.TemporaryDirectory() as d:
            chemin = f"{d}/referentiel.xlsx"
            exporter_kpi(chemin)
            wb = load_workbook(chemin)
            ws = wb["KPI"]
            tete = [c.value for c in ws[1]]
            for r in range(2, ws.max_row + 1):
                if ws.cell(r, 1).value in ("EAU", "NEUF"):
                    ws.cell(r, tete.index("unite") + 1, "L")
            wb.save(chemin)
            r = importer_kpi(chemin)
        self.assertEqual([(i, m.split(" :")[0]) for _, i, m in r.erreurs], [("EAU", "Ce KPI a déjà 1 valeur en « m³ »")])
        self.assertEqual(KPI.objects.get(pk="EAU").unite_id, "m³")  # tout ou rien

    def test_classeur_de_configuration(self):
        from openpyxl import load_workbook

        from . import configuration as C

        wb = load_workbook(io.BytesIO(C.exporter().content))
        ws = wb["KPI"]
        tete = [c.value for c in ws[1]]
        for r in range(2, ws.max_row + 1):
            if ws.cell(r, 1).value in ("EAU", "NEUF"):
                ws.cell(r, tete.index("Unité") + 1, "L")
        flux = io.BytesIO()
        wb.save(flux)
        a = C.analyser(SimpleUploadedFile("conf.xlsx", flux.getvalue()))
        lignes = {c.cle: c for c in a.onglets["KPI"]}
        self.assertEqual((lignes["EAU"].action, lignes["NEUF"].action), ("rejet", "modifier"))
        self.assertTrue(lignes["EAU"].motif.startswith("Ce KPI a déjà 1 valeur en « m³ »"), lignes["EAU"].motif)
        C.appliquer(self.admin, SimpleUploadedFile("conf.xlsx", flux.getvalue()))  # tout ou rien : rien
        self.assertEqual([KPI.objects.get(pk=c).unite_id for c in ("EAU", "NEUF")], ["m³", "m³"])

    def test_classeur_onglet_unites(self):
        from openpyxl import load_workbook

        from . import configuration as C

        wb = load_workbook(io.BytesIO(C.exporter().content))
        ws = wb["Unités"]
        tete = [c.value for c in ws[1]]
        for r in range(2, ws.max_row + 1):
            if ws.cell(r, 1).value == "m³":
                ws.cell(r, next(i for i, t in enumerate(tete) if str(t).startswith("Symbole")) + 1, "L")
        flux = io.BytesIO()
        wb.save(flux)
        a = C.analyser(SimpleUploadedFile("conf.xlsx", flux.getvalue()))
        ligne = next(c for c in a.onglets["Unités"] if c.cle == "m³")
        self.assertEqual(ligne.action, "rejet")
        self.assertIn("1 KPI qui utilise cette unité a déjà des valeurs", ligne.motif)
        for r in range(2, ws.max_row + 1):
            if ws.cell(r, 1).value == "m³":
                ws.cell(r, next(i for i, t in enumerate(tete) if str(t).startswith("Symbole")) + 1, "m3")  # correction d'écriture : acceptée
        flux = io.BytesIO()
        wb.save(flux)
        a = C.analyser(SimpleUploadedFile("conf.xlsx", flux.getvalue()))
        self.assertEqual(next(c for c in a.onglets["Unités"] if c.cle == "m³").action, "modifier")


class SymboleUniteTests(Arbre):
    """Page Unités et formats : le symbole d'une unité utilisée par un KPI qui a des valeurs."""

    URL = "/parametres/referentiel/"

    def setUp(self):
        super().setUp()
        self.m3 = Unite.objects.create(code="mcube", symbole="m3", libelle="mètre cube", ordre=1, decimales=2)
        self.kpi("EAU", unite=self.m3, type_reponse_id="Numérique")
        self.saisir("EAU", self.e1, 1234, camp=self.c0)
        self.client.force_login(self.admin)

    def envoyer(self, symbole, decimales="2"):
        return self.client.post(reverse("parametres:referentiel") + "?section=unites", {
            "action": "enregistrer", "nb": "1", "code__0": "mcube", "symbole__0": symbole, "libelle__0": "mètre cube",
            "famille__0": "", "decimales__0": decimales})

    def test_equivalences(self):
        for a, b in (("m3", "m³"), ("t CO2e", "tCO₂e"), ("m²", "m2")):
            self.assertTrue(R.symboles_equivalents(a, b), (a, b))
        for a, b in (("m³", "L"), ("mW", "MW"), ("kWh", "MWh"), ("m3", "m")):
            self.assertFalse(R.symboles_equivalents(a, b), (a, b))

    def test_changement_de_sens_refuse(self):
        rep = self.envoyer("L")
        self.assertEqual(rep.status_code, 200)
        self.assertContains(rep, "1 KPI qui utilise cette unité a déjà des valeurs")
        self.assertEqual(Unite.objects.get(pk="mcube").symbole, "m3")

    def test_correction_d_ecriture_et_decimales_acceptees(self):
        rep = self.envoyer("m³", decimales="3")
        self.assertEqual(rep.status_code, 302)
        u = Unite.objects.get(pk="mcube")
        self.assertEqual((u.symbole, u.decimales), ("m³", 3))

    def test_unite_sans_valeurs_libre(self):
        Reponse.objects.all().delete()
        self.assertEqual(self.envoyer("L").status_code, 302)
        self.assertEqual(Unite.objects.get(pk="mcube").symbole, "L")


class PaquetUniteTests(TestCase):
    """Fichier référentiel, nouvelle version d'un modèle de la bibliothèque : A (kWh) a une valeur ; la nouvelle version passe A en
    kgCO2e et change la formule de C. L'aperçu le dit ; A reste tel quel (ligne rejetée), le reste s'applique."""

    def setUp(self):
        from .aides_tests.paquets import Base

        Base.setUpTestData.__func__(type(self))
        self.r1, self.admin = type(self).r1, type(self).admin

    def test_unite_changee_par_la_nouvelle_version(self):
        from referentiel.models import Organisation

        from . import paquets as P
        from .aides_tests.paquets import fichier, kp
        from .models import Campagne

        from referentiel.models import Niveau

        org = Organisation.objects.create(nom="Site 1", niveau_id=Niveau.SITE)
        c = Campagne.objects.create(exercice=2024, statut=Campagne.Statut.CLOTUREE)
        Reponse.objects.create(periode=c.periode, kpi_id="A", organisation=org, valeur=D(10), origine=Reponse.Origine.SAISIE,
                               statut=Reponse.Statut.VALIDE)
        p = P.extraire(self.r1)
        kp(p, "A").update(unite="kgCO2e")
        kp(p, "C").update(formule="[A] * 3")
        a = P.analyser(P.lire(fichier(p)), {"kpi:A": "mettre_a_jour", "kpi:C": "mettre_a_jour"})
        lignes = {l.code: l for l in a.kpis}
        self.assertEqual(lignes["A"].statut, "rejet")
        self.assertEqual(lignes["A"].motif, "L'unité passerait de « kWh » à « kgCO2e » : ce KPI a déjà 1 valeur. "
                                            "Le KPI reste tel quel.")
        self.assertEqual(lignes["C"].statut, "modifie")
        P.appliquer(self.admin, a)
        self.assertEqual(KPI.objects.get(pk="A").unite_id, "kWh")
        self.assertEqual(KPI.objects.get(pk="C").formule, "[A] * 3")
