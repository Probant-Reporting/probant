"""Aides des tests des échanges : base (organisations, alias, KPI, comptes), lecture d'un classeur, ligne d'en-têtes."""
import datetime
import io
import shutil
import tempfile
from decimal import Decimal

from django.test import TestCase, override_settings
from django.utils import timezone
from openpyxl import load_workbook

from collecte import saisie as S
from collecte.models import Campagne, Reponse
from parametres.referentiel import unite_depuis_symbole as U
from referentiel.models import Attribution, KPI, Niveau, OrgAlias, Organisation, Utilisateur


D = Decimal


def classeur(reponse):
    return load_workbook(io.BytesIO(reponse.content))


def entete(ws, titre, colonne=1):
    """Ligne d'en-têtes d'un onglet à bandeau (titre, mode d'emploi, légende au-dessus)."""
    return next(r for r in range(1, 20) if ws.cell(r, colonne).value == titre)


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
        OrgAlias.objects.create(organisation=self.e1, source="Fichier historique", libelle="Entité numéro 1")
        self.c0 = Campagne.objects.create(exercice=2025, statut=Campagne.Statut.CLOTUREE)
        self.c = Campagne.objects.create(exercice=2026, statut=Campagne.Statut.OUVERTE,
                                         date_fin_saisie=timezone.localdate() + datetime.timedelta(days=30))
        self.eff = KPI.objects.create(code="EFF", libelle="Effectif", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                                      methode_agregation="Somme", unite=U("ETP"), decimales=0)
        self.taux = KPI.objects.create(code="TX", libelle="Taux", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                                       type_reponse_id="Pourcentage", unite=U("%"))
        self.calc = KPI.objects.create(code="DBL", libelle="Double", type_saisie_id="Calculé", formule="[EFF] * 2",
                                       granularite_id=Niveau.ENTITY, methode_agregation="Somme")
        self.contrib = Utilisateur.objects.create(username="contrib", email="contrib@exemple.test", first_name="Camille")
        self.autre = Utilisateur.objects.create(username="autre", email="autre@exemple.test")
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN)
        for k in (self.eff, self.taux):
            Attribution.objects.create(kpi=k, organisation=self.e1, utilisateur=self.contrib)
        Reponse.objects.create(periode=self.c0.periode, kpi=self.eff, organisation=self.e1, valeur=D(100), statut="valide", origine="import")
        S.enregistrer(self.contrib, self.c, self.eff, self.e1, "110", False, "Embauches")
        S.enregistrer(self.admin, self.c, self.eff, self.e2, "40", False, "")
        S.enregistrer(self.contrib, self.c, self.taux, self.e1, "35", False, "")
