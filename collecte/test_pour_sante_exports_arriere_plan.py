"""/sante/ signale un gros export bloqué (comme un import bloqué), jamais en 503, avec le même message pour l'IT."""
import datetime
from unittest import mock

from django.urls import reverse
from django.utils import timezone

from . import exports_arriere_plan as EAP
from . import imports_arriere_plan as AP
from .aides_tests.echanges import Base
from .models import TacheExport
from .test_exports_arriere_plan import EXPORT_BASE, seuil

T = TacheExport.Statut


@mock.patch.object(EAP, "BATTEMENT", 0)
@mock.patch.object(AP, "planificateur_actif", lambda: False)
@mock.patch.object(EAP, "demarrer_fil", lambda code: None)
class SanteGrosExportTests(Base):
    def setUp(self):
        super().setUp()
        seuil(1)
        self.client.force_login(self.admin)
        self.client.post(reverse("collecte:echanges_exporter"), {**EXPORT_BASE, "niveaux": ["Group", "Country", "Entity"]})
        self.t = TacheExport.objects.get()

    def sante(self):
        rep = self.client.get("/sante/")
        self.assertEqual(rep.status_code, 200)  # dit, jamais en 503
        return rep.json()

    def test_export_en_attente_puis_bloque(self):
        d = self.sante()
        self.assertEqual((d["background_exports"]["waiting"], d["background_exports"]["running"], d["background_exports"]["stuck"]), (1, 0, 0))
        self.assertNotIn("background export stuck", d.get("avertissement", ""))
        TacheExport.objects.filter(pk=self.t.pk).update(cree_le=timezone.now() - datetime.timedelta(seconds=AP.ATTENTE_MAX + 5))
        d = self.sante()
        self.assertEqual(d["background_exports"]["stuck"], 1)
        self.assertIn("background export stuck", d["avertissement"])
        self.assertIn("run_imports --schedule", d["avertissement"])

    def test_export_en_cours_sans_signe_de_vie(self):
        vieux = timezone.now() - datetime.timedelta(seconds=EAP.PERIME + 5)
        TacheExport.objects.filter(pk=self.t.pk).update(statut=T.EN_COURS, battement=vieux)
        d = self.sante()
        self.assertEqual((d["background_exports"]["running"], d["background_exports"]["stuck"]), (1, 1))
        TacheExport.objects.filter(pk=self.t.pk).update(battement=timezone.now())
        d = self.sante()
        self.assertEqual(d["background_exports"]["stuck"], 0)

    def test_fichier_pret_ou_fini_jamais_signale(self):
        TacheExport.objects.filter(pk=self.t.pk).update(statut=T.PRET, cree_le=timezone.now() - datetime.timedelta(days=3))
        d = self.sante()
        self.assertEqual({k: d["background_exports"][k] for k in ("running", "waiting", "stuck")}, {"running": 0, "waiting": 0, "stuck": 0})

    def test_les_deux_messages_se_cumulent(self):
        from .models import TacheImport

        TacheExport.objects.filter(pk=self.t.pk).update(cree_le=timezone.now() - datetime.timedelta(seconds=AP.ATTENTE_MAX + 5))
        TacheImport.objects.create(utilisateur=self.admin, statut=TacheImport.Statut.ATTENTE, nom_fichier="a.xlsx", chemin="x")
        TacheImport.objects.update(cree_le=timezone.now() - datetime.timedelta(seconds=AP.ATTENTE_MAX + 5))
        d = self.sante()
        self.assertIn("background import stuck", d["avertissement"])
        self.assertIn("background export stuck", d["avertissement"])

    def test_sans_connexion_aucun_detail(self):
        self.client.logout()
        self.assertEqual(self.client.get("/sante/", HTTP_X_FORWARDED_FOR="203.0.113.5").json(), {"etat": "ok"})  # derrière un proxy
