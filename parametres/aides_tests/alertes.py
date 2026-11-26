"""Aides des tests des alertes par e-mail (``parametres/alertes.py``) : dossier des données à part (signes de vie des
tâches, sauvegardes), serveur d'envoi réglé dans l'outil, alertes allumées, disque presque plein simulé, passages à
heure choisie."""
import datetime
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.core import mail
from django.test import override_settings
from django.utils import timezone

from parametres import alertes as AL
from parametres import vues_hebergement as VH
from parametres.aides_tests.emails import regler

SECRET = Path("/chemin/secret/du/disque")
T0 = timezone.now().replace(microsecond=0)


def installation_existante(jours=30):
    """Le registre d'une installation existante qui vient de se mettre à jour : sa ligne d'installation date d'avant
    la migration des alertes (``alertes.installation_neuve`` faux). Sans cela, la base de test est une installation
    neuve (migrations, puis comptes créés par le test)."""
    from django.db import connections
    from django.db.migrations.recorder import MigrationRecorder

    from espaces.models import Installation

    appliquee = (MigrationRecorder(connections["commun"]).migration_qs.filter(app="espaces", name="0003_alertes_sante")
                 .values_list("applied", flat=True).get())
    i = Installation.objects.first() or Installation.objects.create(identifiant="0" * 32)
    Installation.objects.filter(pk=i.pk).update(creee_le=appliquee - datetime.timedelta(days=jours))


def disque_plein():
    """Disque presque plein (ligne « Espace disque » en panne, toute l'installation)."""
    return mock.patch.object(VH, "espace_disque", return_value=(1024, SECRET))


def passer(minutes=0):
    """Un passage des alertes ``minutes`` après T0 (au-delà de l'intervalle d'un passage au suivant)."""
    return AL.passage(T0 + datetime.timedelta(minutes=minutes))


class DossierAlertes:
    """Mixin : dossier des données temporaire, serveur d'envoi réglé, alertes allumées (comptes permis + ``adresses``)."""

    adresses = ""
    allumer = True

    def setUp(self):
        super().setUp()
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        reglages = override_settings(DOSSIER_DONNEES=self.tmp, MEDIA_ROOT=self.tmp / "files", SAUVEGARDES_DIR=self.tmp / "backups",
                                     ESPACES_DOSSIER=self.tmp / "spaces-data", EMAIL_HOST="", EMAIL_HOST_USER="",
                                     EMAIL_HOST_PASSWORD="", URL_PUBLIQUE="https://outil.example")
        reglages.enable()
        self.addCleanup(reglages.disable)
        (self.tmp / "spaces-data" / "essai").mkdir(parents=True)  # dossier de l'espace « essai » (fichiers modifiables)
        regler()
        if self.allumer:
            AL.enregistrer(None, True, True, self.adresses)
        mail.outbox = []

    def boite(self, adresse=None):
        return [m for m in mail.outbox if adresse is None or adresse in m.to]
