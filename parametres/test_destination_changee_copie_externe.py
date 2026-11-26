"""Copie externe (Paramètres › Hébergement › Copie externe) : les secrets enregistrés (clé secrète S3, mot de passe ou clé
privée SFTP) ne partent jamais vers une autre destination que celle pour laquelle ils ont été saisis. Une autre
destination du même genre (S3 : adresse, région, compartiment, clé d'accès ; SFTP : hôte, port, compte) sans nouveau
secret : l'écran refuse l'envoi et demande le secret (rien n'est enregistré, l'ancienne destination reste entière) ;
``copie_externe.enregistrer`` (relu sous verrou) efface les secrets si un tel envoi lui parvient quand même. Avec un
nouveau secret : enregistré. Même destination (casse, préfixe, style, copies gardées) : rien ne change. Hôte ou port
SFTP changé : la clé du serveur épinglée est oubliée (déjà le cas avant ce lot)."""
from django.test import TestCase
from django.urls import reverse

from collecte.models import Journal
from espaces.models import DestinationCopie
from parametres import copie_externe as CE
from parametres.aides_tests.copie import MDP_SFTP, SECRET_S3
from parametres.aides_tests.faux_sftp import cle_client_texte
from parametres.libelles import libelle
from referentiel.models import Utilisateur

URL = reverse("parametres:copie_externe")
S3 = {"action": "enregistrer", "genre": "s3", "adresse": "https://stockage.exemple.test", "region": "fr-par",
      "compartiment": "sauvegardes", "chemin": "", "style": "auto", "identifiant": "IDENTIFIANT-CLE-ACCES", "secret": "",
      "conserver": "0"}
SFTP = {"action": "enregistrer", "genre": "sftp", "hote": "nas.exemple.lan", "port": "22", "identifiant": "copie",
        "secret": "", "cle_privee": "", "chemin": "/backups", "conserver": "3"}
CLE = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl"


def valeurs(formulaire):
    return {c: (int(formulaire[c]) if c in ("port", "conserver") else formulaire[c]) for c in CE.CHAMPS[formulaire["genre"]]}


class DestinationChangeeTests(TestCase):
    databases = {"default", "commun"}

    def setUp(self):
        self.admin = Utilisateur.objects.create(username="adm", email="adm@exemple.test", role=Utilisateur.Role.ADMIN)
        self.client.force_login(self.admin)

    def regler_s3(self):
        CE.enregistrer(None, "s3", valeurs(S3), secret=SECRET_S3)
        return DestinationCopie.objects.get().secret_chiffre

    def regler_sftp(self, cle_privee=""):
        CE.enregistrer(None, "sftp", valeurs(SFTP), secret="" if cle_privee else MDP_SFTP, cle_privee=cle_privee)
        DestinationCopie.objects.filter(pk=1).update(cle_serveur=CLE)
        d = DestinationCopie.objects.get()
        return d.secret_chiffre, d.cle_privee_chiffree

    def test_s3_autre_destination_sans_secret_refusee(self):
        for champ, valeur in (("adresse", "https://autre-stockage.exemple.test"), ("region", "nl-ams"),
                              ("compartiment", "autres-sauvegardes"), ("identifiant", "AUTRE-CLE-ACCES")):
            with self.subTest(champ):
                chiffre = self.regler_s3()
                rep = self.client.post(URL, {**S3, champ: valeur})
                self.assertEqual(rep.status_code, 200)
                self.assertContains(rep, libelle("admin.copie.erreur.secret_s3_destination").split(":")[0])
                d = DestinationCopie.objects.get()
                self.assertEqual((getattr(d, champ) != valeur, d.secret_chiffre), (True, chiffre))  # rien d'enregistré
                rep = self.client.post(URL, {**S3, champ: valeur, "secret": "Nouvelle-cle-S3"})  # saisi de nouveau
                self.assertEqual(rep.status_code, 302)
                d = DestinationCopie.objects.get()
                self.assertEqual(getattr(d, champ), valeur)
                self.assertEqual(CE.CH.dechiffrer(d.secret_chiffre, CE.CH.SECRET_COPIE), "Nouvelle-cle-S3")
                CE.retirer(None)

    def test_sftp_autre_serveur_sans_secret_refuse(self):
        for champ, valeur in (("hote", "autre-nas.exemple.lan"), ("port", "2222"), ("identifiant", "autre-compte")):
            with self.subTest(champ):
                avant = self.regler_sftp()
                rep = self.client.post(URL, {**SFTP, champ: valeur})
                self.assertEqual(rep.status_code, 200)
                self.assertContains(rep, libelle("admin.copie.erreur.secret_sftp_destination").split(":")[0])
                d = DestinationCopie.objects.get()
                self.assertEqual((d.secret_chiffre, d.cle_privee_chiffree), avant)
                self.assertEqual(d.cle_serveur, CLE)
                CE.retirer(None)

    def test_meme_destination_garde_les_secrets(self):
        chiffre = self.regler_s3()
        for changement in ({"adresse": "HTTPS://Stockage.Exemple.Test/"}, {"region": " FR-PAR "}, {"chemin": "pre"},
                           {"style": "path"}, {"conserver": "4"}):
            with self.subTest(changement):
                self.assertEqual(self.client.post(URL, {**S3, **changement}).status_code, 302)
                self.assertEqual(DestinationCopie.objects.get().secret_chiffre, chiffre)
        CE.retirer(None)
        avant = self.regler_sftp()
        for changement in ({"hote": "NAS.exemple.lan"}, {"chemin": "/autres"}, {"conserver": "5"}):
            with self.subTest(changement):
                self.assertEqual(self.client.post(URL, {**SFTP, **changement}).status_code, 302)
                d = DestinationCopie.objects.get()
                self.assertEqual((d.secret_chiffre, d.cle_privee_chiffree), avant)
        self.assertFalse(Journal.objects.filter(apres=CE.EFFACES_DESTINATION_CHANGEE).exists())

    def test_enregistrer_efface_sous_verrou(self):
        """Envoi qui passerait l'écran (deux onglets, appel direct) : ``enregistrer`` efface les secrets, oublie la clé
        épinglée, et l'historique le dit sans rien de secret."""
        texte_cle, _ = cle_client_texte()
        self.regler_sftp(cle_privee=texte_cle + "\n")
        changements = CE.enregistrer(None, "sftp", {**valeurs(SFTP), "hote": "autre-nas.exemple.lan"})
        self.assertIn(("secret", "", CE.EFFACES_DESTINATION_CHANGEE), changements)
        self.assertIn(("cle_serveur", "", "oubliée (autre serveur)"), changements)
        d = DestinationCopie.objects.get()
        self.assertEqual((d.secret_chiffre, d.cle_privee_chiffree, d.secret_le, d.cle_serveur), ("", "", None, ""))
        self.assertIn("secret", CE.reglage().manques)
        CE.retirer(None)
        self.regler_s3()
        changements = CE.enregistrer(None, "s3", {**valeurs(S3), "compartiment": "autres"})
        self.assertIn(("secret", "", CE.EFFACES_DESTINATION_CHANGEE), changements)
        self.assertEqual(DestinationCopie.objects.get().secret_chiffre, "")
        for c in changements:
            self.assertNotIn(SECRET_S3, " ".join(map(str, c)))
