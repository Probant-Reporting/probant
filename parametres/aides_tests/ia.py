"""Aides des tests de la prise IA : dossier des clés propre à chaque test, fournisseur factice remis à zéro, prise
allumée en une ligne. Aucun test n'appelle le réseau (settings.IA_RESEAU_INTERDIT)."""
import shutil
import tempfile
from pathlib import Path

from django.test import override_settings

from parametres import ia as IA
from parametres.ia_fournisseurs import FournisseurFactice
from parametres.models import Instance

CLE = "sk-test-0123456789abcdefghijklmnopqrstuvwxyz"


class AvecIA:
    """À mêler à une classe de test (avant la base). ``self.factice`` : état du fournisseur factice (requêtes reçues,
    réponse ou erreur imposée)."""

    def setUp(self):
        super().setUp()
        self._cles = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self._cles, True)
        reglage = override_settings(IA_CLES_DIR=self._cles / "ai-keys", IA_PRISE_PERMISE=True, IA_FOURNISSEUR_FACTICE=True)
        reglage.enable()
        self.addCleanup(reglage.disable)
        FournisseurFactice.remettre()
        self.factice = FournisseurFactice.etat

    def allumer(self, cle=True, **champs):
        """Prise allumée avec le fournisseur factice, les trois usages allumés sauf ``champs`` contraires."""
        i = Instance.courante()
        reglages = {"ia_active": True, "ia_fournisseur": "factice", "ia_modele": "factice-1", "ia_expliquer_alertes": True,
                    "ia_reprise": True, "ia_traductions": True, **champs}
        for c, v in reglages.items():
            setattr(i, c, v)
        i.save()
        if cle:
            IA.enregistrer_cle(CLE)
        return i
