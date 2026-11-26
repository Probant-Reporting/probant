"""Mot de passe du serveur d'envoi réglé dans l'outil : jamais réaffiché ni renvoyé au navigateur, jamais en clair en base,
jamais dans l'historique, le journal du serveur, les rapports d'erreur, le fichier de configuration exporté ni l'archive
d'un espace (ni même chiffré) ; l'archive du registre commun (IT seulement) ne le garde que chiffré."""
import json
import shutil
import tempfile
import zipfile
from pathlib import Path

from django.test import TestCase, override_settings
from django.urls import reverse

from collecte.models import Journal
from espaces.models import ServeurEnvoi
from parametres import sauvegardes as SV
from parametres.aides_tests.emails import HOTE, IDENTIFIANT, MDP, SANS_ENV, regler
from referentiel.models import Utilisateur

URL = reverse("parametres:hebergement")
FORMULAIRE = {"action": "reglage_emails", "hote": HOTE, "port": "587", "securite": "starttls", "identifiant": IDENTIFIANT,
              "mot_de_passe": MDP, "expediteur": "envoi@outil.example"}


def morceaux(secret, n=10):
    return {secret[i:i + n] for i in range(len(secret) - n + 1)}


@SANS_ENV
class JamaisRenvoyeTests(TestCase):
    def setUp(self):
        self.admin = Utilisateur.objects.create(username="adm", email="adm@exemple.test", role=Utilisateur.Role.ADMIN)
        self.client.force_login(self.admin)

    def test_page_historique_journal_et_base(self):
        with self.assertLogs(level="DEBUG") as journaux:
            rep = self.client.post(URL, FORMULAIRE)
            self.assertEqual(rep.status_code, 302)
            page = self.client.get(URL).content.decode()
            import logging

            logging.getLogger("reporting.emails").debug("fin")  # au moins une ligne capturée
        for m in morceaux(MDP):
            self.assertNotIn(m, page)
        self.assertRegex(page, r'<input type="password" name="mot_de_passe"(?![^>]*value=)[^>]*>')
        self.assertNotIn(MDP, "\n".join(journaux.output))
        textes = " ".join(f"{j.champ} {j.avant} {j.apres}" for j in Journal.objects.all())
        self.assertNotIn(MDP, textes)
        self.assertNotIn(IDENTIFIANT, textes)  # détail de l'installation : seulement « modifié »
        self.assertIn("mot de passe enregistré", textes)
        s = ServeurEnvoi.objects.get()
        self.assertNotIn(MDP, repr([getattr(s, f.attname) for f in s._meta.concrete_fields]))

    def test_cache_des_rapports_d_erreur(self):
        from django.views.debug import SafeExceptionReporterFilter

        requete = self.client.post(URL, FORMULAIRE).wsgi_request
        self.assertEqual(getattr(requete, "sensitive_post_parameters", None), ("mot_de_passe",))
        filtre = SafeExceptionReporterFilter()
        self.assertEqual(filtre.get_post_parameters(requete)["mot_de_passe"], filtre.cleansed_substitute)

    def test_ni_dans_le_fichier_de_configuration_exporte(self):
        from collecte import configuration as C

        regler()
        for rep in (C.exporter(), C.exporter(format="csv"), C.exporter(vierge=True)):
            contenu = b"".join(rep.streaming_content) if getattr(rep, "streaming", False) else rep.content
            if contenu[:2] == b"PK":  # classeur : texte de chaque feuille
                with zipfile.ZipFile(__import__("io").BytesIO(contenu)) as z:
                    contenu = b"".join(z.read(n) for n in z.namelist())
            for secret in (MDP, HOTE, IDENTIFIANT):
                self.assertNotIn(secret.encode(), contenu)


@SANS_ENV
class ArchivesTests(TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        reglages = override_settings(DOSSIER_DONNEES=self.tmp, MEDIA_ROOT=self.tmp / "files", SAUVEGARDES_DIR=self.tmp / "backups",
                                     ESPACES_DOSSIER=self.tmp / "spaces-data")
        reglages.enable()
        self.addCleanup(reglages.disable)
        Utilisateur.objects.create(username="adm", email="adm@exemple.test", role=Utilisateur.Role.ADMIN)
        regler()
        self.chiffre = ServeurEnvoi.objects.get().mot_de_passe_chiffre

    def test_archive_d_un_espace_sans_le_serveur_d_envoi(self):
        a = SV.creer("essai", format_base="json")
        with zipfile.ZipFile(a.chemin) as z:
            contenu = b"".join(z.read(n) for n in z.namelist())
        for secret in (MDP, self.chiffre, HOTE, IDENTIFIANT, "serveurenvoi"):
            self.assertNotIn(secret.encode(), contenu)

    def test_archive_du_registre_seulement_chiffre(self):
        chemin = SV.creer_registre("essai")
        with zipfile.ZipFile(chemin) as z:
            lignes = json.loads(z.read("registry.json"))
        envoi = [o for o in lignes if o["model"] == "espaces.serveurenvoi"]
        self.assertEqual(len(envoi), 1)
        self.assertEqual(envoi[0]["fields"]["mot_de_passe_chiffre"], self.chiffre)
        self.assertNotIn(MDP, json.dumps(lignes))
