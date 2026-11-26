"""La copie externe dans la page Santé, /sante/ et la page Hébergement :

- sans destination : un conseil (état « Bon », aucune alerte), rien de nouveau « à traiter » sur la page Hébergement,
  /sante/ dit « off » : une installation existante ne change pas à la mise à jour ;
- copie réussie : la date de la dernière copie ; échec : une seule ligne (le problème signalé), /sante/ le dit sans
  jamais passer en 503 ; clé SFTP à confirmer, archive en attente depuis plus de 24 heures : « à regarder » ;
- version tout-en-un (sans les bibliothèques) : la fonction n'existe pas, l'écran le dit, aucune ligne, aucun appel."""
import datetime
import json
import os
from unittest import mock

from django.test import TestCase
from django.urls import reverse

from espaces.models import ProblemeSignale
from parametres import copie_externe as CE
from parametres.aides_tests.copie import DossiersTemporaires, archive, regler_s3, regler_sftp
from parametres.aides_tests.faux_s3 import FauxS3
from referentiel.models import Utilisateur


class SanteTests(DossiersTemporaires, TestCase):
    databases = {"default", "commun"}

    def setUp(self):
        self.sauvegardes = self.dossiers()
        self.admin = Utilisateur.objects.create(username="adm", email="adm@exemple.test", role=Utilisateur.Role.ADMIN)
        self.client.force_login(self.admin)
        self.faux = FauxS3()
        self.addCleanup(self.faux.fermer)
        archive(self.sauvegardes, "backup-20261101-023000-auto.zip")

    def ligne(self, cle="copie_externe"):
        lignes = self.client.get(reverse("parametres:sante_installation")).context["lignes"]
        return next((x for x in lignes if x["cle"] == cle), None)

    def sante(self):
        rep = self.client.get(reverse("parametres:sante"))
        return rep.status_code, json.loads(rep.content)

    def test_sans_destination_un_conseil_sans_bruit(self):
        ligne = self.ligne()
        self.assertEqual((ligne["etat"], ligne["alerte"]), ("bon", ""))
        self.assertIn("ne copie pas les sauvegardes hors du serveur", ligne["constat"])
        statut, etat = self.sante()
        self.assertEqual(etat["external_copy"], {"state": "off"})
        page = self.client.get(reverse("parametres:hebergement"))
        self.assertFalse([p for p in page.context["bilan"]["points"] if "copie" in p["texte"].lower()])
        self.assertContains(page, 'id="copie-externe"')
        self.assertContains(page, "Régler une copie hors du serveur")

    def test_reussie_puis_echec_une_seule_ligne_jamais_503(self):
        regler_s3(self.faux)
        CE.passage()
        ligne = self.ligne()
        self.assertEqual(ligne["etat"], "bon")
        self.assertIn("Dernière copie le", ligne["constat"])
        self.assertEqual(self.sante()[1]["external_copy"]["state"], "ok")
        page = self.client.get(reverse("parametres:hebergement"))
        self.assertIn("Sauvegardes copiées hors du serveur le", " ".join(page.context["bilan"]["ok"]))
        archive(self.sauvegardes, "backup-20261102-023000-auto.zip")
        self.faux.refus = {"PUT"}
        with self.assertLogs("reporting.copie", "WARNING"):
            CE.passage()
        self.assertIsNone(self.ligne())  # pas de seconde ligne : celle du problème signalé
        signal = self.ligne("signal-copie_externe")
        self.assertEqual(signal["etat"], "panne")
        self.assertIn("1 archive attend", signal["constat"])
        self.assertIn("Le compte ne peut pas écrire à la destination", signal["quoi"])
        statut, etat = self.sante()
        self.assertEqual(statut, 200)
        self.assertEqual(etat["external_copy"]["state"], "failing")
        self.assertIn("external copy of the backups failing", etat["avertissement"])
        page = self.client.get(reverse("parametres:hebergement"))
        self.assertTrue([p for p in page.context["bilan"]["points"] if p["ancre"] == "copie-externe"])

    def test_cle_a_confirmer_et_retard(self):
        from parametres.aides_tests.faux_sftp import FauxSFTP

        racine = self.tmp / "serveur"
        racine.mkdir()
        sftp = FauxSFTP(racine)
        self.addCleanup(sftp.fermer)
        regler_sftp(sftp, epingler=False)
        ligne = self.ligne()
        self.assertEqual((ligne["etat"], ligne["alerte"]), ("regarder", ""))
        regler_s3(self.faux)
        vieille = archive(self.sauvegardes, "backup-20261001-023000-auto.zip")
        il_y_a_deux_jours = (datetime.datetime.now() - datetime.timedelta(days=2)).timestamp()
        os.utime(vieille, (il_y_a_deux_jours, il_y_a_deux_jours))
        ligne = self.ligne()
        self.assertEqual((ligne["etat"], ligne["alerte"]), ("regarder", "retard"))
        self.assertEqual(self.sante()[1]["external_copy"]["state"], "late")


class VersionToutEnUnTests(DossiersTemporaires, TestCase):
    databases = {"default", "commun"}

    def test_fonction_absente_sans_erreur(self):
        self.dossiers()
        admin = Utilisateur.objects.create(username="adm", email="adm@exemple.test", role=Utilisateur.Role.ADMIN)
        self.client.force_login(admin)
        with mock.patch.object(CE, "disponible", return_value=False):
            page = self.client.get(reverse("parametres:copie_externe"))
            self.assertEqual(page.status_code, 200)
            self.assertContains(page, "La copie externe n&#x27;existe pas dans cette version".replace("&#x27;", "'"))
            self.assertNotContains(page, 'name="action" value="essayer"')
            rep = self.client.post(reverse("parametres:copie_externe"), {"action": "essayer"}, follow=True)
            self.assertContains(rep, "La copie externe n'existe pas dans cette version")
            lignes = self.client.get(reverse("parametres:sante_installation")).context["lignes"]
            self.assertFalse([x for x in lignes if x["cle"] == "copie_externe"])
            self.assertEqual(json.loads(self.client.get(reverse("parametres:sante")).content)["external_copy"],
                             {"state": "unavailable"})
            self.assertEqual(self.client.get(reverse("parametres:hebergement")).status_code, 200)
            self.assertIsNone(CE.passage())
        self.assertFalse(ProblemeSignale.objects.exists())

    def test_bibliotheques_absentes(self):
        import builtins

        vrai_import = builtins.__import__

        def sans_paramiko(nom, *a, **k):
            if nom.split(".")[0] in ("paramiko", "cryptography"):
                raise ImportError(nom)
            return vrai_import(nom, *a, **k)
        with mock.patch("builtins.__import__", side_effect=sans_paramiko):
            self.assertFalse(CE.disponible())
