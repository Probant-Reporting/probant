"""Bouton « Essayer la destination » et confirmation de la clé SFTP (page Copie externe), contre de faux serveurs locaux :

- essai réussi : fichier témoin déposé, relu, supprimé (rien ne reste) ; suppression refusée avec « 0 copie gardée » :
  avertissement, pas un échec ; échec : cause en clair, jamais le message du service ;
- au plus ``ESSAIS_MAX`` essais par ``ESSAIS_FENETRE`` pour toute l'installation ;
- SFTP : la clé inconnue est montrée (empreinte SHA-256) sans rien envoyer ; une empreinte qui n'est pas celle de la clé
  gardée, ou une proposition de plus d'une heure, ne s'épingle pas ; confirmée, l'essai passe ; clé changée ensuite :
  refus, alerte, nouvelle clé montrée à côté de l'ancienne ;
- retirer la destination : plus de copie, alerte résolue, rien supprimé à distance."""
import datetime
import html
import logging

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from espaces.models import DestinationCopie, EtatCopie, ProblemeSignale
from parametres import copie_externe as CE
from parametres.aides_tests.copie import DossiersTemporaires, regler_s3, regler_sftp
from parametres.aides_tests.faux_s3 import FauxS3
from parametres.aides_tests.faux_sftp import FauxSFTP
from parametres.copie_sftp import empreinte
from referentiel.models import Utilisateur

logging.getLogger("paramiko").setLevel(logging.CRITICAL)
URL = reverse("parametres:copie_externe")


def texte(rep):
    return html.unescape(rep.content.decode())


class EssaiS3Tests(DossiersTemporaires, TestCase):
    databases = {"default", "commun"}

    def setUp(self):
        self.dossiers()
        self.admin = Utilisateur.objects.create(username="adm", email="adm@exemple.test", role=Utilisateur.Role.ADMIN)
        self.client.force_login(self.admin)
        self.faux = FauxS3()
        self.addCleanup(self.faux.fermer)

    def test_essai_reussi_rien_ne_reste(self):
        regler_s3(self.faux)
        rep = self.client.post(URL, {"action": "essayer"})
        self.assertEqual(rep.status_code, 200)
        self.assertIn("La destination fonctionne.", texte(rep))
        self.assertEqual(self.faux.objets, {})
        methodes = [r[0] for r in self.faux.requetes]
        self.assertEqual(methodes, ["PUT", "HEAD", "GET", "DELETE"])
        self.assertTrue(self.faux.requetes[0][1].startswith("/sauvegardes/pre/"))

    def test_suppression_refusee_avertissement_ou_echec(self):
        regler_s3(self.faux)
        self.faux.refus = {"DELETE"}
        rep = self.client.post(URL, {"action": "essayer"})
        self.assertIn("L'outil ne peut pas supprimer de fichier à la destination.", texte(rep))
        self.assertIn("La destination fonctionne.", texte(rep))
        regler_s3(self.faux, conserver=3)  # rotation demandée : il faut pouvoir supprimer
        rep = self.client.post(URL, {"action": "essayer"})
        self.assertIn("Le compte ne peut pas supprimer de fichier à la destination.", texte(rep))
        self.assertNotIn("La destination fonctionne.", texte(rep))

    def test_echec_en_clair_sans_le_message_du_service(self):
        regler_s3(self.faux, secret="mauvais-secret")
        rep = self.client.post(URL, {"action": "essayer"})
        self.assertIn("La destination a refusé l'identifiant ou le secret.", texte(rep))
        self.assertIn("HTTP 403 SignatureDoesNotMatch", texte(rep))
        self.assertNotIn("message-interne-du-service", texte(rep))

    def test_essais_limites(self):
        regler_s3(self.faux)
        for _ in range(CE.ESSAIS_MAX):
            self.client.post(URL, {"action": "essayer"})
        n = len(self.faux.requetes)
        rep = self.client.post(URL, {"action": "essayer"}, follow=True)
        self.assertIn("Réessayez dans 15 minutes.", texte(rep))
        self.assertEqual(len(self.faux.requetes), n)
        anciens = [(timezone.now() - CE.ESSAIS_FENETRE - datetime.timedelta(minutes=1)).isoformat()] * CE.ESSAIS_MAX
        EtatCopie.objects.filter(pk=1).update(essais=anciens)
        self.assertContains(self.client.post(URL, {"action": "essayer"}), "La destination fonctionne.")

    def test_retirer(self):
        regler_s3(self.faux)
        ProblemeSignale.objects.create(cle=CE.CLE_ALERTE, titre="t", constat="c")
        self.client.post(URL, {"action": "retirer"})
        self.assertFalse(CE.reglage().configure)
        self.assertFalse(ProblemeSignale.objects.filter(cle=CE.CLE_ALERTE).exists())
        self.assertEqual([r for r in self.faux.requetes if r[0] == "DELETE"], [])


class EssaiSFTPTests(DossiersTemporaires, TestCase):
    databases = {"default", "commun"}

    def setUp(self):
        self.dossiers()
        self.admin = Utilisateur.objects.create(username="adm", email="adm@exemple.test", role=Utilisateur.Role.ADMIN)
        self.client.force_login(self.admin)
        racine = self.tmp / "serveur"
        racine.mkdir()
        self.faux = FauxSFTP(racine)
        self.addCleanup(self.faux.fermer)
        self.racine = racine

    def test_confirmer_la_cle_puis_cle_changee(self):
        regler_sftp(self.faux, epingler=False)
        rep = self.client.post(URL, {"action": "essayer"})
        vue = empreinte(self.faux.cle_publique)
        self.assertIn(vue, texte(rep))
        self.assertIn("Le serveur a présenté sa clé.", texte(rep))
        self.assertEqual(self.faux.authentifications, [])
        self.assertEqual(DestinationCopie.objects.get().cle_proposee, self.faux.cle_publique)
        # une autre empreinte que celle de la clé gardée : rien n'est épinglé
        self.client.post(URL, {"action": "confirmer_cle", "empreinte": "SHA256:" + "A" * 43})
        self.assertEqual(DestinationCopie.objects.get().cle_serveur, "")
        # proposition trop ancienne : refusée
        DestinationCopie.objects.filter(pk=1).update(cle_proposee_le=timezone.now() - datetime.timedelta(hours=2))
        rep = self.client.post(URL, {"action": "confirmer_cle", "empreinte": vue}, follow=True)
        self.assertIn("La clé n'a pas été confirmée", texte(rep))
        self.assertEqual(DestinationCopie.objects.get().cle_serveur, "")
        DestinationCopie.objects.filter(pk=1).update(cle_proposee_le=timezone.now())
        rep = self.client.post(URL, {"action": "confirmer_cle", "empreinte": vue}, follow=True)
        self.assertIn(f"Clé confirmée ({vue})", texte(rep))
        d = DestinationCopie.objects.get()
        self.assertEqual((d.cle_serveur, d.cle_proposee, d.cle_serveur_par), (self.faux.cle_publique, "", self.admin.pk))
        rep = self.client.post(URL, {"action": "essayer"})
        self.assertIn("La destination fonctionne.", texte(rep))
        self.assertEqual(self.faux.authentifications, [("password", "copie")])
        # le serveur change de clé : refus avant l'authentification, alerte, les deux empreintes à l'écran
        autre = FauxSFTP(self.racine)
        self.addCleanup(autre.fermer)
        DestinationCopie.objects.filter(pk=1).update(port=autre.port)
        rep = self.client.post(URL, {"action": "essayer"})
        self.assertIn("Le serveur SFTP a présenté une clé qui n'est pas la clé confirmée", texte(rep))
        self.assertIn(empreinte(autre.cle_publique), texte(rep))
        self.assertIn(vue, texte(rep))
        self.assertIn("Remplacer la clé confirmée", texte(rep))
        self.assertEqual(autre.authentifications, [])
        self.assertTrue(ProblemeSignale.objects.filter(cle=CE.CLE_ALERTE, quoi="admin.copie.cause.empreinte").exists())

    def test_autre_serveur_oublie_la_cle(self):
        regler_sftp(self.faux)
        changements = CE.enregistrer(None, "sftp", {"hote": "autre.exemple.lan", "port": self.faux.port, "identifiant": "copie",
                                                    "chemin": "/sauvegardes", "conserver": 0})
        self.assertIn(("cle_serveur", "", "oubliée (autre serveur)"), changements)
        self.assertEqual(DestinationCopie.objects.get().cle_serveur, "")
