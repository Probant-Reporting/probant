"""``restore --shared`` (``sauvegardes.restaurer_registre``) vide tout le registre commun avant de recharger l'archive :
ce qui n'est pas dans l'archive est remis à zéro. Voulu pour la connexion d'entreprise (réglage et liens jamais dans
l'archive, docs/single_sign_on.md), et pour le serveur d'e-mails, le réglage des alertes et la destination de la copie
externe quand l'archive vient d'une version qui ne les sauvegardait pas. Le message de fin de la commande dit ce qui a
été remis à zéro et doit être réglé de nouveau.

Et la connexion d'entreprise éteinte n'enferme personne dehors : les mots de passe de l'archive reviennent, et chacun
peut de nouveau se connecter avec le mot de passe de l'outil (gestionnaire ou non)."""
import io
import json
import shutil
import tempfile
import zipfile
from pathlib import Path

from django.core.management import call_command
from django.test import Client, TransactionTestCase, override_settings

from connexion_entreprise import regles
from connexion_entreprise.models import LienEntreprise, ReglageEntreprise
from connexion_entreprise.secret import chiffrer
from espaces.models import Compte, ServeurEnvoi
from parametres import sauvegardes as SV
from parametres.aides_tests.emails import SANS_ENV, regler
from referentiel.models import Utilisateur

MDP = "Mot-de-passe-de-l-outil-2026"


def sans_modeles(chemin, modeles):
    """Copie de l'archive sans les lignes de ``modeles`` (archive d'une version qui ne les sauvegardait pas)."""
    with zipfile.ZipFile(chemin) as z:
        d = json.loads(z.read(SV.DESCRIPTIF))
        objets = [o for o in json.loads(z.read("registry.json")) if o["model"] not in modeles]
    sortie = chemin.with_name(chemin.name.replace(".zip", "-ancienne.zip"))
    d.pop("migrations", None)
    with zipfile.ZipFile(sortie, "w") as z:
        z.writestr("registry.json", json.dumps(objets))
        z.writestr(SV.DESCRIPTIF, json.dumps(d))
    return sortie


@SANS_ENV
class RegistreRemisAZeroTests(TransactionTestCase):
    databases = {"default", "commun"}

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        reglages = override_settings(DOSSIER_DONNEES=self.tmp, MEDIA_ROOT=self.tmp / "files", SAUVEGARDES_DIR=self.tmp / "backups",
                                     ESPACES_DOSSIER=self.tmp / "spaces-data")
        reglages.enable()
        self.addCleanup(reglages.disable)
        self.gestion = Utilisateur(username="gestion@exemple.example", email="gestion@exemple.example", role="admin")
        self.gestion.set_password(MDP)
        self.gestion.save()
        self.contrib = Utilisateur(username="contrib@exemple.example", email="contrib@exemple.example", role="contributeur")
        self.contrib.set_password(MDP)
        self.contrib.save()
        Compte.objects.filter(pk=self.gestion.pk).update(gestionnaire=True)
        regler()  # serveur d'e-mails réglé dans l'outil

    def allumer_connexion_entreprise(self):
        ReglageEntreprise.objects.update_or_create(pk=1, defaults={
            "actif": True, "emetteur": "https://login.exemple.example", "client_id": "probant",
            "secret_chiffre": chiffrer("secret-du-client"), "mot_de_passe_pour_tous": False})
        LienEntreprise.objects.create(compte_id=self.contrib.pk, emetteur="https://login.exemple.example", sujet="s-1",
                                      derniere_le="2026-11-01T00:00:00Z")

    def restaurer(self, chemin):
        sortie = io.StringIO()
        call_command("restore", "--shared", str(chemin), "--yes", stdout=sortie)
        return sortie.getvalue()

    def test_connexion_d_entreprise_remise_a_zero_dite(self):
        archive = SV.creer_registre("essai")
        self.allumer_connexion_entreprise()
        sortie = self.restaurer(archive)
        self.assertFalse(ReglageEntreprise.objects.exists())
        self.assertFalse(LienEntreprise.objects.exists())
        self.assertIn("Reset by the restore", sortie)
        self.assertIn("company sign-in is off", sortie)
        self.assertIn("1 link(s)", sortie)
        self.assertNotIn("email server", sortie)  # dans l'archive : remis tel quel, rien à dire

    def test_personne_n_est_enferme_dehors(self):
        archive = SV.creer_registre("essai")
        self.allumer_connexion_entreprise()
        with override_settings(CONNEXION_ENTREPRISE_PERMISE=True):
            self.restaurer(archive)
            self.assertFalse(regles.active())
            for u in (self.contrib, self.gestion):
                self.assertTrue(regles.mot_de_passe_permis(u.pk))
                c = Client()
                r = c.post("/connexion/", {"username": u.username, "password": MDP})
                self.assertEqual(r.status_code, 302, u.username)
                self.assertEqual(int(c.session["_auth_user_id"]), u.pk)

    def test_archive_d_une_version_d_avant(self):
        archive = sans_modeles(SV.creer_registre("essai"),
                               {"espaces.serveurenvoi", "espaces.reglagealertes", "espaces.destinationcopie"})
        sortie = self.restaurer(archive)
        self.assertFalse(ServeurEnvoi.objects.exists())
        self.assertIn("email server", sortie)
        self.assertNotIn("company sign-in", sortie)  # rien n'était réglé

    def test_rien_a_dire(self):
        sortie = self.restaurer(SV.creer_registre("essai"))
        self.assertNotIn("Reset by the restore", sortie)
        self.assertIn("Everyone signs in again", sortie)
