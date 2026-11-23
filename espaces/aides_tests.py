"""Aides des tests des espaces : compte d'essai, alias de base retiré, dossier temporaire d'un espace créé."""
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.db import connections
from django.test import override_settings

from referentiel.models import Utilisateur

from . import contexte as E



def oublier_alias(alias):
    """Tests : retire un alias déclaré à la volée (base fermée)."""
    if alias in connections.settings:
        connections[alias].close()
        connections.settings = {k: v for k, v in connections.settings.items() if k != alias}
        settings.DATABASES = {k: v for k, v in settings.DATABASES.items() if k != alias}
        try:
            delattr(connections._connections, alias)
        except AttributeError:
            pass


MDP = "Essai-espaces-2026"


def creer(email, role="contributeur", espace="principal", **kw):
    with E.activer(espace):
        u = Utilisateur(username=email.lower(), email=email, role=role, first_name=kw.pop("first_name", "Prénom"), **kw)
        if role == "admin":
            u.is_superuser = u.is_staff = True
        u.set_password(MDP)
        u.save()
        return u


class DossierTemporaire:
    """Espace « achats » créé pendant le test, dans un dossier temporaire (ou un schéma PostgreSQL), retiré à la fin."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        reglages = override_settings(ESPACES_DOSSIER=self.tmp / "spaces-data", MEDIA_ROOT=self.tmp / "media")
        reglages.enable()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.addCleanup(reglages.disable)
        super().setUp()
        self.addCleanup(self.nettoyer)
        # base créée pendant le test (comme par l'outil) : permise, hors des transactions du test
        self.enterContext(mock.patch.object(type(self), "databases", frozenset(self.databases) | {"espace_achats"}))

    def nettoyer(self):
        alias = "espace_achats"
        if alias in connections.settings:
            c = connections[alias]
            if c.vendor == "postgresql":
                with E.toutes_les_bases(), c.cursor() as cur:
                    cur.execute("DROP SCHEMA IF EXISTS espace_achats CASCADE")
            oublier_alias(alias)
