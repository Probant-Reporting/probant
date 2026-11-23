"""Aides des tests de la saisie : base (organisations, KPI, comptes, campagne) et petit fichier de preuve."""
import datetime
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone

from collecte import saisie as S
from collecte.models import Campagne
from parametres.referentiel import unite_depuis_symbole as U
from referentiel.models import Attribution, KPI, Niveau, Organisation, Utilisateur


PDF = b"%PDF-1.4 test"


def fichier(nom="preuve.pdf", contenu=PDF, type_="application/pdf"):
    return SimpleUploadedFile(nom, contenu, content_type=type_)


class Base(TestCase):
    @classmethod
    def setUpClass(cls):
        # un dossier de fichiers par classe : en parallèle, une classe qui finit ne vide pas celui d'une autre
        cls._media = tempfile.mkdtemp()
        cls._reglage_media = override_settings(MEDIA_ROOT=cls._media)
        cls._reglage_media.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._reglage_media.disable()
        shutil.rmtree(cls._media, ignore_errors=True)

    def setUp(self):
        self.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.p = Organisation.objects.create(nom="Pays", niveau_id=Niveau.COUNTRY, parent=self.g)
        self.e1 = Organisation.objects.create(nom="E1", niveau_id=Niveau.ENTITY, parent=self.p)
        self.e2 = Organisation.objects.create(nom="E2", niveau_id=Niveau.ENTITY, parent=self.p)
        self.c0 = Campagne.objects.create(exercice=2025, statut=Campagne.Statut.CLOTUREE)
        self.c = Campagne.objects.create(exercice=2026, statut=Campagne.Statut.OUVERTE,
                                         date_fin_saisie=timezone.localdate() + datetime.timedelta(days=30))
        self.eff = KPI.objects.create(code="EFF", libelle="Effectif", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                                      methode_agregation="Somme", unite=U("ETP"))
        self.taux = KPI.objects.create(code="TX", libelle="Taux", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                                       type_reponse_id="Pourcentage", unite=U("%"))
        self.calc = KPI.objects.create(code="DBL", libelle="Double", type_saisie_id="Calculé", formule="[EFF] * 2",
                                       granularite_id=Niveau.ENTITY, methode_agregation="Somme")
        self.contrib = Utilisateur.objects.create(username="contrib", email="contrib@exemple.test")
        self.autre = Utilisateur.objects.create(username="autre", email="autre@exemple.test")
        self.valid = Utilisateur.objects.create(username="valid", email="valid@exemple.test", role=Utilisateur.Role.VALIDATEUR)
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN)
        for k in (self.eff, self.taux):
            Attribution.objects.create(kpi=k, organisation=self.e1, utilisateur=self.contrib)
        Attribution.objects.create(kpi=self.eff, organisation=self.p, utilisateur=self.valid, role=Attribution.Role.VALIDATEUR)

    def enregistrer(self, v, kpi=None, user=None, na=False, com="", org=None):
        return S.enregistrer(user or self.contrib, self.c, kpi or self.eff, org or self.e1, v, na, com)
