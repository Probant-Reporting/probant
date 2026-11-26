"""Secrets de la copie externe (clé secrète S3, mot de passe ou clé privée SFTP) : même règle que le mot de passe du serveur
d'e-mails. Jamais réaffichés ni renvoyés au navigateur, jamais en clair en base, jamais dans l'historique, le journal du
serveur, les rapports d'erreur, le fichier de configuration exporté ni l'archive d'un espace (ni même chiffrés) ; l'archive
du registre commun ne les garde que chiffrés. Champ vide : le secret est gardé ; « Effacer » : geste explicite. Secret
changé ou registre venu d'un autre serveur : « à saisir de nouveau », aucune erreur 500 ; restauré avec le registre."""
import json
import logging
import zipfile

from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from collecte.models import Journal
from espaces.models import DestinationCopie
from parametres import copie_externe as CE
from parametres import sauvegardes as SV
from parametres.aides_tests.copie import MDP_SFTP, SECRET_S3, DossiersTemporaires
from parametres.aides_tests.faux_sftp import cle_client_texte
from referentiel.models import Utilisateur

URL = reverse("parametres:copie_externe")
S3 = {"action": "enregistrer", "genre": "s3", "adresse": "https://stockage.exemple.test", "region": "fr-par",
      "compartiment": "sauvegardes", "chemin": "", "style": "auto", "identifiant": "IDENTIFIANT-CLE-ACCES", "secret": SECRET_S3,
      "conserver": "0"}
SFTP = {"action": "enregistrer", "genre": "sftp", "hote": "nas.exemple.lan", "port": "22", "identifiant": "copie",
        "secret": MDP_SFTP, "cle_privee": "", "chemin": "/backups", "conserver": "3"}
AUTRE_SECRET = override_settings(SECRET_KEY="secret-d-un-autre-serveur-0123456789-abcdefghijkl")


def morceaux(secret, n=10):
    return {secret[i:i + n] for i in range(len(secret) - n + 1)}


class JamaisRenvoyeTests(TestCase):
    databases = {"default", "commun"}

    def setUp(self):
        self.admin = Utilisateur.objects.create(username="adm", email="adm@exemple.test", role=Utilisateur.Role.ADMIN)
        self.client.force_login(self.admin)

    def test_page_historique_journal_et_base(self):
        texte_cle, _ = cle_client_texte()
        with self.assertLogs(level="DEBUG") as journaux:
            self.assertEqual(self.client.post(URL, S3).status_code, 302)
            page_s3 = self.client.get(URL).content.decode()
            self.assertEqual(self.client.post(URL, {**SFTP, "secret": "", "cle_privee": texte_cle}).status_code, 302)
            page_sftp = self.client.get(URL).content.decode()
            logging.getLogger("reporting.copie").debug("fin")
        corps = texte_cle.split("\n")[1]  # une ligne du corps de la clé
        for page in (page_s3, page_sftp):
            for m in morceaux(SECRET_S3) | morceaux(corps):
                self.assertNotIn(m, page)
            self.assertRegex(page, r'<input type="password" name="secret"(?![^>]*value=)[^>]*>')
        self.assertIn("Une clé privée est enregistrée depuis le", page_sftp)
        tout = "\n".join(journaux.output)
        self.assertNotIn(SECRET_S3, tout)
        self.assertNotIn(corps, tout)
        textes = " ".join(f"{j.champ} {j.avant} {j.apres}" for j in Journal.objects.all())
        for secret in (SECRET_S3, corps, "IDENTIFIANT-CLE-ACCES"):
            self.assertNotIn(secret, textes)
        self.assertIn("enregistré", textes)
        d = DestinationCopie.objects.get()
        valeurs = repr([getattr(d, f.attname) for f in d._meta.concrete_fields])
        self.assertNotIn(SECRET_S3, valeurs)
        self.assertNotIn(corps, valeurs)

    def test_cache_des_rapports_d_erreur(self):
        from django.views.debug import SafeExceptionReporterFilter

        requete = self.client.post(URL, S3).wsgi_request
        self.assertEqual(getattr(requete, "sensitive_post_parameters", None), ("secret", "cle_privee"))
        filtre = SafeExceptionReporterFilter()
        self.assertEqual(filtre.get_post_parameters(requete)["secret"], filtre.cleansed_substitute)

    def test_champ_vide_garde_et_effacer_est_explicite(self):
        self.client.post(URL, S3)
        chiffre = DestinationCopie.objects.get().secret_chiffre
        # même destination : le préfixe n'en change pas (une autre destination redemande le secret :
        # test_destination_changee_copie_externe)
        rep = self.client.post(URL, {**S3, "secret": "", "chemin": "pre"})
        self.assertEqual(rep.status_code, 302)
        d = DestinationCopie.objects.get()
        self.assertEqual((d.secret_chiffre, d.chemin), (chiffre, "pre"))
        self.client.post(URL, {"action": "effacer_secrets"})
        self.assertEqual(DestinationCopie.objects.get().secret_chiffre, "")
        self.assertEqual(CE.reglage().manques, ("secret",))
        rep = self.client.post(URL, {**S3, "secret": ""})  # plus de secret : le champ redevient obligatoire
        self.assertEqual(rep.status_code, 200)
        self.assertContains(rep, "Saisissez la clé secrète.")

    def test_autre_genre_oublie_le_secret(self):
        self.client.post(URL, S3)
        self.client.post(URL, SFTP)
        d = DestinationCopie.objects.get()
        self.assertEqual(d.genre, "sftp")
        self.assertEqual(CE.CH.dechiffrer(d.secret_chiffre, CE.CH.SECRET_COPIE), MDP_SFTP)
        self.assertEqual(d.cle_privee_chiffree, "")

    def test_ni_dans_le_fichier_de_configuration_exporte(self):
        import io

        from collecte import configuration as C

        self.client.post(URL, S3)
        for rep in (C.exporter(), C.exporter(format="csv"), C.exporter(vierge=True)):
            contenu = b"".join(rep.streaming_content) if getattr(rep, "streaming", False) else rep.content
            if contenu[:2] == b"PK":
                with zipfile.ZipFile(io.BytesIO(contenu)) as z:
                    contenu = b"".join(z.read(n) for n in z.namelist())
            for secret in (SECRET_S3, "stockage.exemple.test", "IDENTIFIANT-CLE-ACCES"):
                self.assertNotIn(secret.encode(), contenu)

    def test_secret_change_a_saisir_de_nouveau_sans_erreur(self):
        self.client.post(URL, S3)
        with AUTRE_SECRET:
            self.client.force_login(self.admin)
            r = CE.reglage()
            self.assertEqual((r.secret, r.secret_illisible, r.complet), (True, True, False))
            page = self.client.get(URL)
            self.assertEqual(page.status_code, 200)
            self.assertContains(page, "Le secret enregistré ne peut plus être lu")
            self.assertEqual(self.client.get(reverse("parametres:hebergement")).status_code, 200)
            self.assertEqual(self.client.get(reverse("parametres:sante_installation")).status_code, 200)
            self.client.post(URL, {**S3, "secret": "Nouveau-secret-S3"})
            self.assertTrue(CE.reglage().complet)


class DemarrageTests(TestCase):
    databases = {"default", "commun"}

    def test_demarrage_le_dit_a_l_it_sans_le_secret(self):
        from parametres.management.commands.demarrage import Command

        self.assertEqual(Command._copie(), "")  # sans destination : aucune ligne nouvelle
        CE.enregistrer(None, "s3", {"adresse": "https://stockage.exemple.test", "region": "", "compartiment": "sauvegardes",
                                    "style": "auto", "identifiant": "IDENTIFIANT-CLE-ACCES", "chemin": "", "conserver": 0},
                       secret=SECRET_S3)
        ligne = Command._copie()
        self.assertEqual(ligne, "S3 sauvegardes at https://stockage.exemple.test (set in the tool, Settings > Hosting)")
        with AUTRE_SECRET:
            self.assertIn("enter it again", Command._copie())
        self.assertNotIn(SECRET_S3, ligne)


class ArchivesTests(DossiersTemporaires, TestCase):
    databases = {"default", "commun"}

    def setUp(self):
        self.dossiers()
        Utilisateur.objects.create(username="adm", email="adm@exemple.test", role=Utilisateur.Role.ADMIN)
        CE.enregistrer(None, "s3", {"adresse": "https://stockage.exemple.test", "region": "", "compartiment": "sauvegardes",
                                    "style": "auto", "identifiant": "IDENTIFIANT-CLE-ACCES", "chemin": "", "conserver": 0},
                       secret=SECRET_S3)
        self.chiffre = DestinationCopie.objects.get().secret_chiffre

    def test_archive_d_un_espace_sans_la_destination(self):
        a = SV.creer("essai", format_base="json")
        with zipfile.ZipFile(a.chemin) as z:
            contenu = b"".join(z.read(n) for n in z.namelist())
        for secret in (SECRET_S3, self.chiffre, "stockage.exemple.test", "IDENTIFIANT-CLE-ACCES", "destinationcopie", "etatcopie"):
            self.assertNotIn(secret.encode(), contenu)

    def test_archive_du_registre_seulement_chiffre_sans_l_etat(self):
        chemin = SV.creer_registre("essai")
        with zipfile.ZipFile(chemin) as z:
            lignes = json.loads(z.read("registry.json"))
        d = [o for o in lignes if o["model"] == "espaces.destinationcopie"]
        self.assertEqual(len(d), 1)
        self.assertEqual(d[0]["fields"]["secret_chiffre"], self.chiffre)
        self.assertNotIn(SECRET_S3, json.dumps(lignes))
        self.assertFalse([o for o in lignes if o["model"] == "espaces.etatcopie"])


class RestaurationRegistreTests(DossiersTemporaires, TransactionTestCase):
    databases = {"default", "commun"}

    def test_restaurer_le_registre_remet_la_destination(self):
        self.dossiers()
        Utilisateur.objects.create(username="adm", email="adm@exemple.test", role=Utilisateur.Role.ADMIN)
        CE.enregistrer(None, "sftp", {"hote": "nas.exemple.lan", "port": 22, "identifiant": "copie", "chemin": "/backups",
                                      "conserver": 2}, secret=MDP_SFTP)
        DestinationCopie.objects.filter(pk=1).update(cle_serveur="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl")
        chemin = SV.creer_registre("essai")
        CE.retirer(None)
        self.assertFalse(CE.reglage().configure)
        SV.restaurer_registre(chemin)
        d = DestinationCopie.objects.get()
        self.assertEqual((d.genre, d.hote, d.conserver), ("sftp", "nas.exemple.lan", 2))
        self.assertTrue(d.cle_serveur.startswith("ssh-ed25519 "))
        self.assertEqual(CE.CH.dechiffrer(d.secret_chiffre, CE.CH.SECRET_COPIE), MDP_SFTP)  # même secret de l'installation : relu
        with AUTRE_SECRET:  # registre restauré sur un autre serveur : à saisir de nouveau
            self.assertEqual(CE.reglage().manques, ("secret_illisible",))
