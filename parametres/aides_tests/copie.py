"""Aides des tests de la copie externe des sauvegardes (``parametres/copie_externe.py``) : dossiers des données
temporaires, archives au nom reconnu, destinations réglées comme par la page (registre commun)."""
import os
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.test import override_settings

from parametres import copie_externe as CE

SECRET_S3 = "Cle-secrete-S3-tres-secrete-5d1e"  # jamais dans une page, le journal, l'historique, une archive d'espace
MDP_SFTP = "Mdp-SFTP-tres-secret-42"
SANS_PROXY = mock.patch.dict(os.environ, {k: "" for k in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy",
                                                           "ALL_PROXY", "all_proxy")})


class DossiersTemporaires:
    """Mélange pour un ``TestCase`` : dossier des données, des fichiers et des sauvegardes à lui."""

    def dossiers(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        reglages = override_settings(DOSSIER_DONNEES=self.tmp, MEDIA_ROOT=self.tmp / "files", SAUVEGARDES_DIR=self.tmp / "backups",
                                     ESPACES_DOSSIER=self.tmp / "spaces-data", COPIE_EXTERNE_LOCAL=True)
        reglages.enable()
        self.addCleanup(reglages.disable)
        SANS_PROXY.start()
        self.addCleanup(SANS_PROXY.stop)
        return self.tmp / "backups"


def archive(sauvegardes, rel, taille=2000, contenu=None):
    """Fichier au nom d'une archive (``backup-…zip``, ``spaces/<code>/backup-…zip``, ``shared/registry-…zip``)."""
    p = Path(sauvegardes) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(contenu if contenu is not None else os.urandom(taille))
    return p


def regler_s3(faux, par=None, chemin="pre", conserver=0, secret=None):
    from parametres.aides_tests.faux_s3 import ID, SECRET

    return CE.enregistrer(par, "s3", {"adresse": faux.adresse, "region": "", "compartiment": faux.compartiment, "style": "path",
                                      "identifiant": ID, "chemin": chemin, "conserver": conserver}, secret=secret or SECRET)


def regler_sftp(faux, par=None, epingler=True, chemin="/sauvegardes", conserver=0):
    from espaces.models import DestinationCopie

    CE.enregistrer(par, "sftp", {"hote": "127.0.0.1", "port": faux.port, "identifiant": faux.identifiant, "chemin": chemin,
                                 "conserver": conserver}, secret=faux.mot_de_passe)
    if epingler:
        DestinationCopie.objects.filter(pk=1).update(cle_serveur=faux.cle_publique)


def identifiant_installation():
    from espaces import comptes as EC

    i = EC.installation()
    return i.identifiant if i else "installation"
