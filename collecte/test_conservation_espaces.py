"""Conservation des preuves : chaque espace a sa durée, sa liste et ses fichiers ; une suppression dans un espace ne touche
jamais l'autre (collecte/conservation.py)."""
import shutil
import tempfile
from decimal import Decimal
from pathlib import Path

from django.core.files.base import ContentFile
from django.test import override_settings

from collecte import conservation as CV
from collecte.aides_tests.espaces import jeu
from collecte.models import Campagne, Journal, Preuve, Reponse
from espaces import contexte as E
from espaces.aides_tests import creer
from espaces.essais import EspacesTestCase
from parametres.models import Instance
from referentiel.models import KPI, Utilisateur


class ConservationEspacesTests(EspacesTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.admin = creer("admin@exemple.example", "admin")
        creer("admin@exemple.example", "admin", "essai")
        cls.org, cls.c, cls.r = jeu("essai", "Usine Achats", "KPI-ACH")

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        reglages = override_settings(MEDIA_ROOT=self.tmp / "files", ESPACES_DOSSIER=self.tmp / "espaces-donnees")
        reglages.enable()
        self.addCleanup(reglages.disable)
        with E.activer("essai"):
            KPI.objects.filter(code="KPI-ACH").update(confidentialite=KPI.Confidentialite.CONFIDENTIEL)
            ancienne = Campagne.objects.create(exercice=2024, statut=Campagne.Statut.CLOTUREE)
            reponse = Reponse.objects.create(periode=ancienne.periode, kpi_id="KPI-ACH", organisation=self.org, valeur=Decimal(7),
                                             statut=Reponse.Statut.VALIDE)
            self.preuve = Preuve.objects.create(reponse=reponse, fichier=ContentFile(b"%PDF-1.4 achats", name="contrat.pdf"))
            i = Instance.courante()
            i.preuves_sensibles_mois = 1
            i.save()
        self.chemin = self.tmp / "espaces-donnees" / "essai" / "files" / self.preuve.fichier.name
        self.client.force_login(Utilisateur.objects.get(pk=self.admin.pk))

    def test_duree_et_liste_propres_a_chaque_espace(self):
        with E.activer("essai"):
            self.assertEqual([l["preuve"].pk for l in CV.a_supprimer()], [self.preuve.pk])
        self.assertIsNone(CV.mois_reglage())  # espace principal : pas de durée réglée
        self.assertEqual(CV.a_supprimer(), [])

    def test_suppression_dans_l_espace_detruit_son_fichier_et_son_journal(self):
        self.assertTrue(self.chemin.is_file())
        with self.captureOnCommitCallbacks(using="espace_essai", execute=True):
            rep = self.client.post("/espace/essai/administration/preuves/", {"preuves": [self.preuve.pk]})
        self.assertEqual(rep.status_code, 302)
        self.assertFalse(self.chemin.exists())
        with E.activer("essai"):
            self.assertFalse(Preuve.objects.filter(pk=self.preuve.pk).exists())
            self.assertEqual(Journal.objects.filter(action="purge_preuve").count(), 1)
        self.assertFalse(Journal.objects.filter(action="purge_preuve").exists())  # rien dans le journal de l'espace principal

    def test_la_page_d_un_espace_ne_montre_pas_les_preuves_de_l_autre(self):
        self.assertContains(self.client.get("/espace/essai/administration/preuves/"), "contrat.pdf</a>")
        self.assertNotContains(self.client.get("/administration/preuves/"), "contrat.pdf")
