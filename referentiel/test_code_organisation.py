"""Code d'organisation stable (migrations 0012 et 0013) : rempli sans perte pour les organisations existantes, unique,
gardé quand on renomme, réglable par l'admin."""
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from referentiel.models import Niveau, Organisation, Utilisateur, code_libre, normaliser_code
import io

from django.core.files.uploadedfile import SimpleUploadedFile

from collecte import imports as I
from collecte.aides_tests.echanges import Base, classeur


class MigrationCodeTests(TransactionTestCase):
    avant = [("referentiel", "0011_retrait_code_dans_referentiel")]
    apres = [("referentiel", "0013_organisation_code_unique")]

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_codes_remplis_et_uniques(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.avant)
        apps = executor.loader.project_state(self.avant).apps
        O = apps.get_model("referentiel", "Organisation")
        c6 = dict(couleur="#000000", couleur_fond="#FFFFFF", couleur_texte="#000000")
        apps.get_model("parametres", "NiveauHierarchique").objects.get_or_create(
            code=Niveau.GROUP, defaults=dict(rang=1, nom="Groupe", nom_pluriel="Groupes", couleur_pale="#FFFFFF", **c6))
        O.objects.all().delete()
        for nom in ("FR LOG", "Fr-Log", "Été (Groupe)", "***"):
            O.objects.create(nom=nom, niveau_id=Niveau.GROUP, nom_court="x", actif=nom != "***")
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(self.apres)
        O = executor.loader.project_state(self.apres).apps.get_model("referentiel", "Organisation")
        self.assertEqual(dict(O.objects.values_list("nom", "code")),
                         {"FR LOG": "FR-LOG", "Fr-Log": "FR-LOG-2", "Été (Groupe)": "ETE-GROUPE", "***": "ORG"})
        self.assertEqual(O.objects.filter(actif=True, nom_court="x").count(), 3)  # le reste est inchangé


class CodeOrganisationTests(TestCase):
    def test_tire_du_nom_puis_garde(self):
        g = Organisation.objects.create(nom="Holding Été", niveau_id=Niveau.GROUP)
        self.assertEqual(g.code, "HOLDING-ETE")
        g.nom = "Holding 2027"
        g.save()
        self.assertEqual(Organisation.objects.get(pk=g.pk).code, "HOLDING-ETE")
        self.assertEqual(code_libre("holding été", {"HOLDING-ETE"}), "HOLDING-ETE-2")
        self.assertEqual(normaliser_code(" fr log/2 "), "FR-LOG-2")

    def test_reglable_par_l_admin(self):
        g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        autre = Organisation.objects.create(nom="Autre", niveau_id=Niveau.GROUP)
        admin = Utilisateur.objects.create(username="admin", email="a@exemple.test", role=Utilisateur.Role.ADMIN)
        self.client.force_login(admin)
        url = reverse("collecte:admin_organisation", args=[g.pk])
        donnees = {"nom": "Groupe", "niveau": Niveau.GROUP, "rang": 0, "actif": "on"}
        self.client.post(url, {**donnees, "code": "grp 1"})
        self.assertEqual(Organisation.objects.get(pk=g.pk).code, "GRP-1")
        rep = self.client.post(url, {**donnees, "code": autre.code})
        self.assertContains(rep, "déjà pris")
        self.assertEqual(Organisation.objects.get(pk=g.pk).code, "GRP-1")


class CodeOrganisationFichierTests(Base):
    def test_fichier_a_remplir_reconnu_par_le_code_meme_si_le_nom_change(self):
        wb = classeur(I.modele(self.contrib, self.c, I.lignes_modele(self.contrib, self.c)))
        ws = wb["Saisie"]
        n = next(r for r in range(1, 15) if ws.cell(r, 2).value == "ID KPI")
        tete = [c.value for c in ws[n]]
        col = tete.index("Code organisation") + 1
        ligne = next(r for r in range(n + 1, ws.max_row + 1) if ws.cell(r, 2).value == "EFF")
        self.assertEqual(ws.cell(ligne, col).value, self.e1.code)
        self.assertTrue(ws.cell(ligne, col).protection.locked)  # clé grise
        ws.cell(ligne, tete.index("Valeur") + 1).value = 130
        flux = io.BytesIO()
        wb.save(flux)
        self.e1.nom = "Entité renommée"  # le nom change entre le téléchargement et le dépôt
        self.e1.save()
        a = I.analyser(self.contrib, SimpleUploadedFile("rempli.xlsx", flux.getvalue()))
        eff = next(l for l in a.lignes if l.kpi_id == "EFF")
        self.assertEqual((eff.org, eff.action), (self.e1, "modifier"))
