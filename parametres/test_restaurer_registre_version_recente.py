"""``restore --shared`` (``sauvegardes.restaurer_registre``) d'une archive du registre faite par une version PLUS
RÉCENTE de l'outil (archive faite après une mise à jour, puis retour à la version précédente) : refusée proprement,
avec un message clair, avant tout changement (pas d'archive « before-restore », registre intact, sessions gardées).

Deux signes : les migrations du registre notées dans l'archive (archives faites depuis cette version) dont le code ne
connaît pas une, ou un contenu que les modèles du code ne savent pas lire (archives sans liste des migrations)."""
import json
import shutil
import tempfile
import zipfile
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TransactionTestCase, override_settings

from espaces import contexte as ESP
from espaces.models import Compte
from parametres import sauvegardes as SV
from referentiel.models import Utilisateur


def reecrire(chemin, descriptif=None, registre=None):
    """Copie de l'archive ``chemin`` avec un descriptif et un contenu changés (fonction ou None)."""
    with zipfile.ZipFile(chemin) as z:
        d = json.loads(z.read(SV.DESCRIPTIF))
        objets = json.loads(z.read("registry.json"))
    if descriptif:
        descriptif(d)
    if registre:
        registre(objets)
    sortie = chemin.with_name(chemin.name.replace(".zip", "-future.zip"))
    with zipfile.ZipFile(sortie, "w") as z:
        z.writestr("registry.json", json.dumps(objets))
        z.writestr(SV.DESCRIPTIF, json.dumps(d))
    return sortie


class RegistreVersionRecenteTests(TransactionTestCase):
    databases = {"default", "commun"}

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        reglages = override_settings(DOSSIER_DONNEES=self.tmp, MEDIA_ROOT=self.tmp / "files", SAUVEGARDES_DIR=self.tmp / "backups",
                                     ESPACES_DOSSIER=self.tmp / "spaces-data")
        reglages.enable()
        self.addCleanup(reglages.disable)
        Utilisateur.objects.create(username="adm", email="adm@exemple.test", role=Utilisateur.Role.ADMIN)
        self.archive = SV.creer_registre("essai")

    def refusee(self, chemin):
        avant = sorted(p.name for p in SV.archives_registre())
        comptes = sorted(Compte.objects.using(ESP.COMMUN).values_list("username", flat=True))
        with self.assertRaises(SV.ErreurSauvegarde) as cm:
            SV.restaurer_registre(chemin)
        message = str(cm.exception)
        self.assertIn("more recent version", message)
        self.assertIn("Nothing was changed", message)
        self.assertNotIn("Traceback", message)
        self.assertEqual(sorted(p.name for p in SV.archives_registre()), avant, "aucune archive « before-restore »")
        self.assertEqual(sorted(Compte.objects.using(ESP.COMMUN).values_list("username", flat=True)), comptes)
        return message

    def test_descriptif_avec_les_migrations_du_registre(self):
        with zipfile.ZipFile(self.archive) as z:
            d = json.loads(z.read(SV.DESCRIPTIF))
        self.assertIn(["espaces", "0001_initial"], d["migrations"])

    def test_migration_inconnue_refusee(self):
        future = reecrire(self.archive, descriptif=lambda d: (d["migrations"].append(["espaces", "9999_futur"]),
                                                              d.update(version="99.0.0")))
        self.assertIn("99.0.0", self.refusee(future))

    def test_modele_inconnu_refuse_sans_trace(self):
        """Archive sans liste des migrations, avec un modèle que ce code n'a pas : le cas de l'ancienne version devant une
        archive de la nouvelle (``DeserializationError: Invalid model identifier``)."""
        def ajouter(objets):
            objets.append({"model": "espaces.modelefutur", "pk": 1, "fields": {"nom": "x"}})

        self.refusee(reecrire(self.archive, descriptif=lambda d: d.pop("migrations", None), registre=ajouter))

    def test_champ_inconnu_refuse(self):
        def ajouter(objets):
            next(o for o in objets if o["model"] == "espaces.compte")["fields"]["champ_futur"] = 1

        self.refusee(reecrire(self.archive, descriptif=lambda d: d.pop("migrations", None), registre=ajouter))

    def test_commande_message_clair(self):
        future = reecrire(self.archive, descriptif=lambda d: d["migrations"].append(["espaces", "9999_futur"]))
        with self.assertRaises(CommandError) as cm:
            call_command("restore", str(future), "--shared", "--yes")
        self.assertIn("more recent version", str(cm.exception))

    def test_archive_de_cette_version_toujours_restauree(self):
        SV.restaurer_registre(self.archive)
        self.assertTrue(Compte.objects.using(ESP.COMMUN).filter(username="adm").exists())
