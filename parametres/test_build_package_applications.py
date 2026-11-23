"""Version tout-en-un (``portable/build_package.py``) : le paquet contient toutes les applications de l'outil.

Constaté en construisant le paquet : l'application des assistants (``serveur_mcp``), ajoutée à ``INSTALLED_APPS`` après
la liste ``APP``, n'était pas copiée ; le Python du paquet s'arrêtait au premier ``manage.py migrate``
(« No module named 'serveur_mcp' ») et l'étape d'essai du workflow aurait échoué. Une entrée de ``APP`` absente du dépôt
est ignorée sans message par ``extraire_app`` : une faute de frappe y retirerait un dossier du paquet."""
import importlib.util
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

RACINE = Path(settings.BASE_DIR)


def module():
    spec = importlib.util.spec_from_file_location("build_package_applications", RACINE / "portable" / "build_package.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class ApplicationsDuPaquetTests(SimpleTestCase):
    def test_chaque_application_installee_est_dans_le_paquet(self):
        app = set(module().APP)
        locales = [a.split(".")[0] for a in settings.INSTALLED_APPS if not a.startswith("django.")]
        self.assertTrue(locales)
        manquantes = [a for a in locales if a not in app]
        self.assertEqual(manquantes, [], "applications absentes de APP dans portable/build_package.py")

    def test_modules_du_reglage_dans_le_paquet(self):
        app = set(module().APP)
        for reglage in (settings.ROOT_URLCONF, settings.WSGI_APPLICATION):
            self.assertIn(reglage.split(".")[0], app, reglage)

    def test_chaque_entree_de_app_existe(self):
        absentes = [c for c in module().APP if not (RACINE / c).exists()]
        self.assertEqual(absentes, [], "entrées de APP absentes du dépôt (ignorées sans message à la construction)")
