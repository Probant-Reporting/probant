"""Commande ``auto_update`` lue par la tâche de la machine (``auto-update.sh``) et par ``install.sh`` : outil occupé
(restauration, sauvegarde, gros import ou export en cours), empreinte des migrations de chaque base, choix d'une
installation neuve. Elle ne fait que lire l'état, ou écrire le choix."""
import io
import shutil
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.db import connections
from django.test import override_settings

from collecte.models import TacheExport, TacheImport
from espaces import contexte as E
from espaces.aides_tests import creer
from espaces.essais import EspacesTestCase
from parametres import mise_a_jour_auto as MA
from parametres import sauvegardes as SV


def lancer(*options):
    sortie = io.StringIO()
    try:
        call_command("auto_update", *options, stdout=sortie)
        code = 0
    except SystemExit as e:
        code = e.code
    return code, sortie.getvalue().strip()


class CommandeTests(EspacesTestCase):
    def setUp(self):
        super().setUp()
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        r = override_settings(DOSSIER_DONNEES=self.tmp, SAUVEGARDES_DIR=self.tmp / "backups")
        r.enable()
        self.addCleanup(r.disable)

    def test_occupe(self):
        self.assertEqual(lancer("--busy"), (0, "idle"))
        d = E.dossier_sauvegardes("essai")
        d.mkdir(parents=True)
        (d / SV.EN_COURS).write_text('{"archive": "x.zip"}')
        self.assertEqual(lancer("--busy"), (3, "busy_restore"))
        (d / SV.EN_COURS).unlink()
        (d / ".backup-20990101-020000.zip.partiel").write_bytes(b"")
        self.assertEqual(lancer("--busy"), (3, "busy_backup"))
        (d / ".backup-20990101-020000.zip.partiel").unlink()
        u = creer("admin@exemple.example", "admin", "essai")
        with E.activer("essai"):
            t = TacheImport.objects.create(utilisateur_id=u.pk, nom_fichier="gros.xlsx", chemin="x", statut="en_cours")
        self.assertEqual(lancer("--busy"), (3, "busy_import"))
        with E.activer("essai"):
            TacheImport.objects.filter(pk=t.pk).update(statut="terminee")
            TacheExport.objects.create(utilisateur_id=u.pk, statut="attente")
        self.assertEqual(lancer("--busy"), (3, "busy_export"))

    def test_empreintes(self):
        code, texte = lancer("--fingerprint")
        self.assertEqual(code, 0)
        lignes = texte.splitlines()
        self.assertEqual([x.split()[0:-1] for x in lignes], [["registry"], ["space", "principal"], ["space", "essai"]])
        for x in lignes:
            self.assertRegex(x.split()[-1], r"^[0-9a-f]{64}$")
        avant = dict(x.rsplit(" ", 1) for x in lignes)
        # une migration de plus dans l'espace « essai » (comme l'aurait appliquée une version plus récente)
        alias = E.declarer("essai")
        with E.toutes_les_bases(), connections[alias].cursor() as c:
            c.execute("INSERT INTO django_migrations (app, name, applied) VALUES ('parametres', '9999_plus_recente', CURRENT_TIMESTAMP)")
        apres = dict(x.rsplit(" ", 1) for x in lancer("--fingerprint")[1].splitlines())
        self.assertEqual({k for k in avant if avant[k] != apres[k]}, {"space essai"})

    def test_choix_d_une_installation_neuve(self):
        self.assertEqual(lancer("--set-choice", "automatic", "--if-unset")[0], 0)
        self.assertEqual(MA.lire_choix(), {"mode": "automatic", "delai": 3, "ecrit": True})
        MA.ecrire_choix("off", 0)
        code, texte = lancer("--set-choice", "automatic", "--if-unset")
        self.assertIn("unchanged", texte)
        self.assertEqual(MA.lire_choix()["mode"], "off", "le choix d'un administrateur n'est jamais remplacé")

    def test_registre_seulement_ses_propres_applications(self):
        """Django note chaque migration de chaque application dans chaque base, même sans table (le routeur la refuse) :
        une migration d'un espace laisse donc une ligne au registre commun, sans rien changer à sa structure. L'empreinte
        du registre ne compte que les applications qui y ont leurs tables (sinon une migration d'espace ferait croire à un
        registre changé, et le retour arrière s'arrêterait)."""
        from espaces.routeur import APPLICATIONS_COMMUNES, MODELES_COMMUNS

        def registre():
            return dict(x.rsplit(" ", 1) for x in lancer("--fingerprint")[1].splitlines())["registry"]

        self.assertEqual(set(MA.REGISTRE), APPLICATIONS_COMMUNES | {m.split(".")[0] for m in MODELES_COMMUNS})
        avant = registre()
        for app, change in (("parametres", False), ("espaces", True)):
            with E.toutes_les_bases(), connections["commun"].cursor() as c:
                c.execute(f"INSERT INTO django_migrations (app, name, applied) VALUES ('{app}', '9999_plus_recente', CURRENT_TIMESTAMP)")
            self.assertEqual(registre() != avant, change, app)
