"""Archive du registre commun faite AVANT les migrations d'une mise à jour (``demarrage`` : « before-update ») : une
table que la mise à jour va créer (ici celle de la copie externe, ``espaces/0004``) n'existe pas encore. L'archive se fait
quand même, sans cette table (avant : « no such table », et le démarrage de la mise à jour s'arrêtait ; constaté par la
répétition de la mise à jour sur la démo construite avec la version d'avant)."""
import json
import shutil
import tempfile
import zipfile
from pathlib import Path

from django.db import connections
from django.test import TransactionTestCase, override_settings

from espaces import contexte as ESP
from espaces.models import DestinationCopie
from parametres import sauvegardes as SV


class AvantMigrationTests(TransactionTestCase):
    databases = {"default", "commun"}

    def test_table_pas_encore_creee(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        reglages = override_settings(SAUVEGARDES_DIR=tmp / "backups")
        reglages.enable()
        self.addCleanup(reglages.disable)
        c = connections[ESP.COMMUN]
        with c.schema_editor() as e:
            e.delete_model(DestinationCopie)

        def recreer():
            with c.schema_editor() as e:
                e.create_model(DestinationCopie)
        self.addCleanup(recreer)
        chemin = SV.creer_registre("before-update")
        with zipfile.ZipFile(chemin) as z:
            modeles = {o["model"] for o in json.loads(z.read("registry.json"))}
        self.assertNotIn("espaces.destinationcopie", modeles)
