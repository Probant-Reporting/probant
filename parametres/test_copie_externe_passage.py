"""Passage de la copie externe (``copie_externe.passage``, lancé à chaque tour du planificateur des sauvegardes) :

- sans destination, rien (ni appel, ni alerte) : une installation existante ne change pas à la mise à jour ;
- toutes les archives partent, celles des espaces ET celle du registre commun, rangées comme dans le dossier des
  sauvegardes sous « <préfixe>/<identifiant de l'installation>/ » ; au tour suivant, seule une archive nouvelle part ;
- échec : alerte (``alertes.signaler``, clé stable), attente croissante avant le nouvel essai ; réussite suivante :
  alerte résolue, rattrapage de tout ce qui attendait ;
- une archive déjà présente à l'identique à la destination n'est pas renvoyée (état perdu, registre restauré) ;
- autre destination : tout repart ; un autre processus en cours : rien ;
- SFTP : clé du serveur pas encore confirmée, aucune connexion ; clé changée, refus avant l'authentification, alerte,
  clé montrée pour confirmation."""
import datetime
import logging

from django.test import TestCase
from django.utils import timezone

from espaces.models import DestinationCopie, EtatCopie, ProblemeSignale
from parametres import copie_externe as CE
from parametres.aides_tests.copie import DossiersTemporaires, archive, identifiant_installation, regler_s3, regler_sftp
from parametres.aides_tests.faux_s3 import FauxS3
from parametres.aides_tests.faux_sftp import FauxSFTP

logging.getLogger("paramiko").setLevel(logging.CRITICAL)
ARCHIVES = ["backup-20261101-023000-auto.zip", "spaces/achats/backup-20261101-023000-auto.zip",
            "shared/registry-20261101-023000-auto.zip"]


class PassageS3Tests(DossiersTemporaires, TestCase):
    databases = {"default", "commun"}

    def setUp(self):
        self.sauvegardes = self.dossiers()
        self.faux = FauxS3()
        self.addCleanup(self.faux.fermer)
        for rel in ARCHIVES:
            archive(self.sauvegardes, rel)
        archive(self.sauvegardes, "notes.txt")  # ni archive ni registre : jamais copié
        self.base = f"pre/{identifiant_installation()}/"

    def test_sans_destination_rien(self):
        self.assertIsNone(CE.passage())
        self.assertEqual(self.faux.requetes, [])
        self.assertFalse(ProblemeSignale.objects.exists())
        self.assertFalse(EtatCopie.objects.exists())

    def test_tout_part_puis_seulement_le_nouveau(self):
        regler_s3(self.faux)
        self.assertEqual(CE.passage(), 3)
        self.assertEqual(sorted(self.faux.objets), sorted(self.base + r for r in ARCHIVES))
        for rel in ARCHIVES:
            self.assertEqual(self.faux.objets[self.base + rel].contenu, (self.sauvegardes / rel).read_bytes())
        e = EtatCopie.objects.get()
        self.assertEqual(set(e.copiees), set(ARCHIVES))
        self.assertIsNotNone(e.reussie_le)
        n = len(self.faux.requetes)
        self.assertIsNone(CE.passage())  # rien n'attend : aucun appel
        self.assertEqual(len(self.faux.requetes), n)
        archive(self.sauvegardes, "spaces/achats/backup-20261102-023000-auto.zip")
        self.assertEqual(CE.passage(), 1)
        self.assertEqual(CE.resume_etat()["etat"], "ok")
        self.assertEqual(CE.resume_etat()["attente"], 0)

    def test_echec_alerte_attente_puis_rattrapage(self):
        regler_s3(self.faux)
        self.faux.refus = {"PUT"}
        self.assertEqual(CE.passage(), 0)
        p = ProblemeSignale.objects.get(cle=CE.CLE_ALERTE)
        self.assertEqual((p.quoi, p.etat, p.params["n"]), ("admin.copie.cause.droits_ecrire", "panne", 3))
        self.assertNotIn("message-interne-du-service", p.detail)
        e = EtatCopie.objects.get()
        self.assertEqual((e.echec, e.echecs_suite), ("droits_ecrire", 1))
        self.assertAlmostEqual((e.prochain_essai - timezone.now()).total_seconds(), 5 * 60, delta=30)
        self.faux.refus = set()
        n = len(self.faux.requetes)
        self.assertIsNone(CE.passage())  # pendant l'attente : rien, aucun appel
        self.assertEqual(len(self.faux.requetes), n)
        self.faux.pannes = 10  # second échec : attente plus longue
        CE.passage(maintenant=e.prochain_essai + datetime.timedelta(seconds=1))
        e.refresh_from_db()
        self.assertEqual((e.echec, e.echecs_suite), ("service", 2))
        self.assertAlmostEqual((e.prochain_essai - timezone.now()).total_seconds(), 15 * 60, delta=30)
        self.assertEqual(CE.resume_etat()["etat"], "echec")
        self.faux.pannes = 0
        self.assertEqual(CE.passage(maintenant=e.prochain_essai + datetime.timedelta(seconds=1)), 3)  # rattrapage
        self.assertFalse(ProblemeSignale.objects.filter(cle=CE.CLE_ALERTE).exists())
        e.refresh_from_db()
        self.assertEqual((e.echec, e.echecs_suite, e.prochain_essai), ("", 0, None))
        self.assertEqual(CE.resume_etat()["etat"], "ok")

    def test_deja_a_l_identique_pas_renvoye(self):
        regler_s3(self.faux)
        CE.passage()
        EtatCopie.objects.all().delete()  # état perdu (registre restauré, par exemple)
        puts = len([r for r in self.faux.requetes if r[0] == "PUT"])
        self.assertEqual(CE.passage(), 0)
        self.assertEqual(len([r for r in self.faux.requetes if r[0] == "PUT"]), puts)
        self.assertEqual(set(EtatCopie.objects.get().copiees), set(ARCHIVES))

    def test_autre_destination_tout_repart(self):
        regler_s3(self.faux)
        CE.passage()
        regler_s3(self.faux, chemin="autre")
        self.assertEqual(CE.passage(), 3)
        self.assertIn(f"autre/{identifiant_installation()}/shared/registry-20261101-023000-auto.zip", self.faux.objets)

    def test_un_seul_passage_a_la_fois(self):
        regler_s3(self.faux)
        EtatCopie.objects.create(pk=1, en_cours_le=timezone.now() - datetime.timedelta(minutes=10))
        self.assertIsNone(CE.passage())
        self.assertEqual(self.faux.requetes, [])
        EtatCopie.objects.filter(pk=1).update(en_cours_le=timezone.now() - CE.BAIL - datetime.timedelta(minutes=1))
        self.assertEqual(CE.passage(), 3)  # processus arrêté en route : la réservation expire

    def test_secret_illisible_alerte_sans_appel(self):
        from django.test import override_settings

        regler_s3(self.faux)
        with override_settings(SECRET_KEY="secret-d-un-autre-serveur-0123456789-abcdefghijkl"):
            self.assertEqual(CE.passage(), 0)
        self.assertEqual(self.faux.requetes, [])
        self.assertEqual(ProblemeSignale.objects.get(cle=CE.CLE_ALERTE).quoi, "admin.copie.cause.secret_illisible")

    def test_archive_supprimee_localement_oubliee(self):
        regler_s3(self.faux)
        CE.passage()
        (self.sauvegardes / ARCHIVES[0]).unlink()  # rotation locale
        archive(self.sauvegardes, "backup-20261102-023000-auto.zip")
        CE.passage()
        self.assertNotIn(ARCHIVES[0], EtatCopie.objects.get().copiees)
        self.assertIn(self.base + ARCHIVES[0], self.faux.objets)  # la copie distante reste (rien à supprimer par défaut)


class PassageSFTPTests(DossiersTemporaires, TestCase):
    databases = {"default", "commun"}

    def setUp(self):
        self.sauvegardes = self.dossiers()
        self.racine = self.tmp / "serveur"
        self.racine.mkdir()
        self.faux = FauxSFTP(self.racine)
        self.addCleanup(self.faux.fermer)
        for rel in ARCHIVES:
            archive(self.sauvegardes, rel)

    def test_cle_pas_confirmee_aucune_connexion(self):
        regler_sftp(self.faux, epingler=False)
        self.assertIsNone(CE.passage())
        self.assertEqual(self.faux.transports, [])
        self.assertEqual(CE.resume_etat()["etat"], "a_confirmer")
        self.assertFalse(ProblemeSignale.objects.exists())

    def test_copie_puis_cle_changee_refus_et_alerte(self):
        regler_sftp(self.faux)
        self.assertEqual(CE.passage(), 3)
        dossier = self.racine / "sauvegardes" / identifiant_installation()
        for rel in ARCHIVES:
            self.assertEqual((dossier / rel).read_bytes(), (self.sauvegardes / rel).read_bytes())
        autre = FauxSFTP(self.racine)  # le serveur « change » : autre clé, même adresse
        self.addCleanup(autre.fermer)
        DestinationCopie.objects.filter(pk=1).update(port=autre.port)
        archive(self.sauvegardes, "backup-20261102-023000-auto.zip")
        self.assertEqual(CE.passage(), 0)
        self.assertEqual(autre.authentifications, [])  # rien envoyé : ni mot de passe ni signature
        p = ProblemeSignale.objects.get(cle=CE.CLE_ALERTE)
        self.assertEqual(p.quoi, "admin.copie.cause.empreinte")
        d = DestinationCopie.objects.get()
        self.assertEqual((d.cle_serveur, d.cle_proposee), (self.faux.cle_publique, autre.cle_publique))
        self.assertFalse((dossier / "backup-20261102-023000-auto.zip").exists())
