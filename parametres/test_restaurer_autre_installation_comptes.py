"""Restauration d'une sauvegarde d'une autre installation (``restaurer(..., autre_installation=True)``, décision du
26/11/2026) : ce que deviennent les comptes, et ce qu'une archive forgée ne peut pas faire.

Avant : la réconciliation du registre rapprochait les comptes par leur NUMÉRO ; les numéros d'une autre installation
n'ont rien à voir avec ceux d'ici. La personne qui avait créé le compte de l'installation vide (n° 1) prenait la place du
n° 1 de la sauvegarde, qui était désactivé ; son propre compte de la sauvegarde (autre numéro, même e-mail) l'était aussi :
plus personne n'entrait. Après : les comptes de cet espace seulement quittent le registre, ceux de la sauvegarde y entrent
sans mot de passe, la personne qui restaure garde son mot de passe et redevient administratrice active."""
import io
import json
import shutil
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.sessions.models import Session
from django.test import Client, TransactionTestCase, override_settings
from django.utils import timezone

from collecte.models import Journal
from espaces import contexte as E
from espaces.aides_tests import MDP, creer
from espaces.models import AccesEspace, Compte, Espace
from referentiel.models import Utilisateur

from . import sauvegardes as SV
from .aides_tests.autre_installation import ORIGINE, archive_d_ailleurs, compte
from .aides_tests.hebergement import DossiersTemporaires

SQLITE = settings.DATABASES["default"]["ENGINE"].endswith("sqlite3")
PIRATE = "Pirate-connu-2026"


class Base(DossiersTemporaires, TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.ext = Path(tempfile.mkdtemp())  # fichiers « téléchargés » hors du dossier des sauvegardes
        self.addCleanup(shutil.rmtree, self.ext, True)
        Espace.objects.get_or_create(code="principal", defaults={"nom": "Principal", "etat": "actif"})
        self.inst = creer("inst@exemple.test", "admin")  # compte créé à l'étape 1 : gestionnaire des espaces
        self.assertTrue(Compte.objects.get(pk=self.inst.pk).gestionnaire)
        self.p = self.inst.pk

    def ailleurs(self, comptes, **options):
        return archive_d_ailleurs(self.ext / f"autre-{len(list(self.ext.iterdir()))}.zip", comptes, **options)

    def restaurer(self, chemin, qui=None):
        qui = qui or self.inst
        return SV.restaurer(chemin, par="essai", origine="outil", autre_installation=True,
                            restaurateur={"pk": qui.pk, "email": qui.email})

    def connecte(self, email, mot_de_passe=MDP):
        return authenticate(None, username=email, password=mot_de_passe)


class ComptesApresRestaurationTests(Base):
    def test_restaurateur_dans_la_sauvegarde_sous_un_autre_numero_et_sans_le_role(self):
        a = self.ailleurs([compte(self.p, "alice@exemple.test", "admin"), compte(self.p + 1, "bob@exemple.test"),
                           compte(self.p + 2, "inst@exemple.test", "lecteur")])
        d = self.restaurer(a)
        self.assertEqual(d["restaurateur"], "remis_admin")
        u = self.connecte("inst@exemple.test")
        self.assertIsNotNone(u)  # jamais de verrouillage dehors : son mot de passe, son compte
        self.assertEqual((u.pk, u.role, u.is_active, u.is_superuser), (self.p + 2, "admin", True, True))
        self.assertTrue(Compte.objects.get(pk=self.p + 2).gestionnaire)
        self.assertEqual(set(Compte.objects.values_list("pk", "email")),
                         {(self.p, "alice@exemple.test"), (self.p + 1, "bob@exemple.test"),
                          (self.p + 2, "inst@exemple.test")})
        for email in ("alice@exemple.test", "bob@exemple.test"):  # les autres : sans mot de passe
            self.assertEqual(Compte.objects.get(email=email).password, SV.MOT_DE_PASSE_RETIRE)
            self.assertFalse(Compte.objects.get(email=email).gestionnaire)
        self.assertEqual(d["comptes_sans_mot_de_passe"], 2)
        j = Journal.objects.get(action="reglage_compte", objet_id=str(self.p + 2))
        self.assertEqual(j.champ, "rôle")
        self.assertIn("Lecteur", j.avant)
        self.assertIn("administrateur", j.apres)

    def test_restaurateur_absent_numero_pris_par_une_autre_personne(self):
        a = self.ailleurs([compte(self.p, "alice@exemple.test", "admin"), compte(self.p + 1, "bob@exemple.test")])
        d = self.restaurer(a)
        self.assertEqual(d["restaurateur"], "ajoute")
        u = self.connecte("inst@exemple.test")
        self.assertIsNotNone(u)
        self.assertNotIn(u.pk, (self.p, self.p + 1))  # numéro libre : jamais celui d'alice
        self.assertTrue(u.est_admin and u.is_active)
        self.assertTrue(Compte.objects.get(pk=u.pk).gestionnaire)
        self.assertEqual(Utilisateur.objects.get(pk=self.p).email, "alice@exemple.test")
        self.assertTrue(Journal.objects.filter(action="creation_compte", objet_id=str(u.pk)).exists())

    def test_restaurateur_absent_numero_libre(self):
        d = self.restaurer(self.ailleurs([compte(self.p + 5, "alice@exemple.test", "admin")]))
        self.assertEqual(d["restaurateur"], "ajoute")
        self.assertEqual(self.connecte("inst@exemple.test").pk, self.p)

    def test_restaurateur_deja_administrateur(self):
        d = self.restaurer(self.ailleurs([compte(self.p + 3, "INST@exemple.test", "admin")]))
        self.assertEqual(d["restaurateur"], "admin")
        self.assertEqual(self.connecte("inst@exemple.test").pk, self.p + 3)

    def test_restaurateur_desactive_dans_la_sauvegarde(self):
        d = self.restaurer(self.ailleurs([compte(self.p + 3, "inst@exemple.test", "admin", actif=False)]))
        self.assertEqual(d["restaurateur"], "remis_admin")
        self.assertTrue(self.connecte("inst@exemple.test").is_active)

    def test_historique_note_l_autre_installation(self):
        self.restaurer(self.ailleurs([compte(self.p + 1, "alice@exemple.test", "admin")]))
        h = SV.historique_restaurations()[0]
        self.assertTrue(h["autre_installation"])
        self.assertEqual(h["installation"], ORIGINE)
        self.assertEqual(h["origine"], "outil")


class ArchiveForgeeTests(Base):
    def assert_aucune_empreinte_lue(self):
        self.assertIsNone(self.connecte("alice@exemple.test", PIRATE))
        self.assertEqual(Compte.objects.get(email="alice@exemple.test").password, SV.MOT_DE_PASSE_RETIRE)
        self.assertEqual(set(Utilisateur.objects.exclude(email="inst@exemple.test").values_list("password", flat=True)),
                         {SV.MOT_DE_PASSE_RETIRE})

    def test_empreinte_connue_ecrite_dans_l_archive_json(self):
        self.restaurer(self.ailleurs([compte(self.p + 1, "alice@exemple.test", "admin", mot_de_passe=PIRATE)]))
        self.assert_aucune_empreinte_lue()

    @unittest.skipUnless(SQLITE, "copie SQLite : base SQLite seulement")
    def test_empreinte_connue_ecrite_dans_l_archive_sqlite(self):
        self.restaurer(self.ailleurs([compte(self.p + 1, "alice@exemple.test", "admin", mot_de_passe=PIRATE)],
                                     format_base="sqlite"))
        self.assert_aucune_empreinte_lue()

    def test_jeton_d_assistant_de_l_archive_jamais_valable(self):
        from serveur_mcp.models import JetonMCP

        jeton = {"model": "serveur_mcp.jetonmcp", "pk": 77, "fields": {
            "utilisateur": ["alice@exemple.test"], "nom": "forgé", "empreinte": "a" * 64, "debut": "pbt_forge",
            "cree_le": timezone.now().isoformat(), "expire_le": (timezone.now() + timedelta(days=30)).isoformat(),
            "revoque_le": None, "revoque_par": None, "derniere_utilisation": None, "mdp_empreinte": ""}}
        avant = list(Compte.objects.values_list("pk", "email"))
        with self.assertRaises(SV.ErreurSauvegarde) as e:  # modèle hors de la liste fermée d'une sauvegarde
            self.restaurer(self.ailleurs([compte(self.p + 1, "alice@exemple.test", "admin")], objets_en_plus=[jeton]))
        self.assertIn("serveur_mcp.jetonmcp", str(e.exception))
        self.assertFalse(JetonMCP.objects.exists())
        self.assertEqual(list(Compte.objects.values_list("pk", "email")), avant)

    def test_l_archive_ne_donne_ni_le_role_de_gestionnaire_ni_un_compte_du_registre(self):
        """Une archive d'un espace qui contient des lignes du registre commun (compte gestionnaire, accès) : elles ne
        vont jamais au registre ; les comptes de la sauvegarde n'y entrent jamais gestionnaires."""
        faux = [{"model": "espaces.compte", "pk": 4242, "fields": {
                    "username": "pirate@exemple.test", "email": "pirate@exemple.test", "password": "x", "first_name": "",
                    "last_name": "", "doit_changer_mdp": False, "actif": True, "gestionnaire": True, "last_login": None,
                    "date_joined": timezone.now().isoformat(), "dernier_espace": ""}}]
        with self.assertRaises(SV.ErreurSauvegarde) as e:  # refusée en entier, avant tout changement
            self.restaurer(self.ailleurs([compte(self.p + 1, "alice@exemple.test", "admin")], objets_en_plus=faux))
        self.assertIn("espaces.compte", str(e.exception))
        self.assertEqual(set(Compte.objects.values_list("email", flat=True)), {"inst@exemple.test"})
        self.assertEqual(list(Compte.objects.filter(gestionnaire=True).values_list("email", flat=True)),
                         ["inst@exemple.test"])

    def test_session_et_compte_d_entreprise_d_un_numero_repris(self):
        """Un compte de cet espace seulement quitte le registre ; son numéro est repris par une autre personne de la
        sauvegarde : ni sa session ni son lien avec un compte d'entreprise n'ouvrent le compte de cette personne."""
        from connexion_entreprise.models import LienEntreprise

        ancien = creer("ancien@exemple.test", "admin")
        c = Client()
        c.force_login(ancien)
        LienEntreprise.objects.create(compte_id=ancien.pk, emetteur="https://idp.exemple.test", sujet="sub-ancien",
                                      derniere_le=timezone.now())
        LienEntreprise.objects.create(compte_id=self.p, emetteur="https://idp.exemple.test", sujet="sub-inst",
                                      derniere_le=timezone.now())
        self.restaurer(self.ailleurs([compte(ancien.pk, "nouvelle@exemple.test", "admin"),
                                      compte(self.p + 9, "inst@exemple.test", "admin")]))
        self.assertFalse(Session.objects.filter(session_key=c.session.session_key).exists())
        self.assertFalse(LienEntreprise.objects.filter(compte_id=ancien.pk).exists())
        # le lien de la personne qui restaure suit son nouveau numéro
        self.assertEqual(LienEntreprise.objects.get(sujet="sub-inst").compte_id, self.p + 9)
        self.assertEqual(Compte.objects.get(pk=ancien.pk).email, "nouvelle@exemple.test")

    def test_reprise_d_une_restauration_interrompue(self):
        """Arrêt brutal après le remplacement de la base (processus interrompu, pas une erreur : pas de retour en arrière) :
        la reprise au démarrage refait les comptes de la même façon."""
        a = self.ailleurs([compte(self.p, "alice@exemple.test", "admin"), compte(self.p + 2, "inst@exemple.test")])
        vrai = SV._echanger_fichiers
        with mock.patch.object(SV, "_echanger_fichiers", side_effect=KeyboardInterrupt("arrêt brutal")):
            with self.assertRaises(KeyboardInterrupt):
                self.restaurer(a)
        self.assertTrue(SV.restauration_en_cours()["autre_installation"])
        with mock.patch.object(SV, "_echanger_fichiers", vrai):
            self.assertEqual(SV.reprendre_restauration(), (a.name, ""))
        u = self.connecte("inst@exemple.test")
        self.assertEqual((u.pk, u.role), (self.p + 2, "admin"))
        self.assertEqual(Compte.objects.get(email="alice@exemple.test").password, SV.MOT_DE_PASSE_RETIRE)


class PlusieursEspacesTests(Base):
    """Comptes gardés : ceux qui ont une copie dans un autre espace (« essai »). La restauration va dans l'espace courant."""

    databases = {"default", "commun", "espace_essai"}

    def setUp(self):
        super().setUp()
        reglage = override_settings(ESPACES_DOSSIER=self.tmp / "spaces-data")
        reglage.enable()
        self.addCleanup(reglage.disable)
        Espace.objects.get_or_create(code="essai", defaults={"nom": "Achats", "etat": "actif", "rang": 1})
        self.k = creer("k@exemple.test", "contributeur", "essai")  # seulement dans « essai »

    def assert_refusee(self, comptes, motif="k@exemple.test"):
        avant = (list(Utilisateur.objects.values_list("pk", "email", "role")), list(Compte.objects.values_list("pk", "email")))
        with self.assertRaises(SV.ErreurSauvegarde) as e:
            self.restaurer(self.ailleurs(comptes))
        self.assertIn("compte dans un autre espace", str(e.exception))  # message des conflits (français par défaut)
        self.assertEqual((list(Utilisateur.objects.values_list("pk", "email", "role")),
                          list(Compte.objects.values_list("pk", "email"))), avant)
        self.assertFalse(SV.historique_restaurations())
        self.assertEqual([a.motif for a in SV.archives()], [])  # refusée avant même la sauvegarde « avant »
        return str(e.exception)

    def test_numero_d_un_compte_d_un_autre_espace_avec_un_autre_e_mail(self):
        texte = self.assert_refusee([compte(self.k.pk, "autre@exemple.test", "admin")])
        self.assertIn("autre@exemple.test", texte)

    def test_e_mail_d_un_compte_d_un_autre_espace_avec_un_autre_numero(self):
        self.assert_refusee([compte(self.k.pk + 50, "k@exemple.test", "admin")])

    def test_identifiant_d_un_compte_d_un_autre_espace(self):
        self.assert_refusee([compte(self.k.pk + 50, "x@exemple.test", "admin", username="k@exemple.test")])

    def test_meme_numero_et_meme_e_mail_droits_dans_cet_espace_seulement(self):
        """Archive forgée qui fait d'une personne d'un autre espace un administrateur : administrateur de CET espace
        seulement, rôle inchangé ailleurs, jamais gestionnaire, mot de passe du registre."""
        self.restaurer(self.ailleurs([compte(self.k.pk, "k@exemple.test", "admin"),
                                      compte(self.k.pk + 50, "alice@exemple.test", "admin")]))
        self.assertEqual(Utilisateur.objects.get(pk=self.k.pk).role, "admin")
        with E.activer("essai"):
            self.assertEqual(Utilisateur.objects.get(pk=self.k.pk).role, "contributeur")
            self.assertEqual(authenticate(None, username="k@exemple.test", password=MDP).pk, self.k.pk)
        self.assertFalse(Compte.objects.get(pk=self.k.pk).gestionnaire)
        self.assertEqual(set(AccesEspace.objects.filter(compte_id=self.k.pk).values_list("espace__code", "role")),
                         {("principal", "admin"), ("essai", "contributeur")})
        alice = Compte.objects.get(email="alice@exemple.test")
        self.assertFalse(alice.gestionnaire)
        self.assertEqual(set(AccesEspace.objects.filter(compte_id=alice.pk).values_list("espace__code", flat=True)),
                         {"principal"})

    def test_restaurateur_qui_a_aussi_une_copie_ailleurs(self):
        creer("inst@exemple.test", "contributeur", "essai")  # même compte, copie dans « essai » : gardé
        d = self.restaurer(self.ailleurs([compte(self.p + 30, "alice@exemple.test", "admin")]))
        self.assertEqual(d["restaurateur"], "ajoute")
        u = self.connecte("inst@exemple.test")
        self.assertEqual((u.pk, u.role), (self.p, "admin"))  # même numéro que sa copie de « essai »
        with E.activer("essai"):
            self.assertEqual(Utilisateur.objects.get(pk=self.p).role, "contributeur")

    def test_restaurateur_garde_dont_le_numero_est_pris_dans_la_sauvegarde(self):
        creer("inst@exemple.test", "contributeur", "essai")
        self.assert_refusee([compte(self.p, "alice@exemple.test", "admin")])

    def test_espace_principal_puis_second_espace_d_une_meme_installation_d_origine(self):
        """Serveur perdu avec deux espaces : l'archive du principal puis celle du second espace, faites par la même
        installation d'origine (numéros cohérents entre elles) : la seconde passe, la personne partagée garde son numéro,
        le compte qui n'était que dans le second espace (k) est remplacé."""
        self.restaurer(self.ailleurs([compte(500, "inst@exemple.test", "admin"), compte(501, "partage@exemple.test", "admin")]))
        inst = self.connecte("inst@exemple.test")
        self.assertEqual(inst.pk, 500)
        with E.activer("essai"):
            second = archive_d_ailleurs(self.ext / "second.zip", [compte(501, "partage@exemple.test", "contributeur"),
                                                                  compte(502, "achats@exemple.test", "admin")])
            d = SV.restaurer(second, par="essai", origine="outil", autre_installation=True,
                             restaurateur={"pk": inst.pk, "email": inst.email})
            self.assertEqual(d["restaurateur"], "ajoute")
            self.assertEqual(Utilisateur.objects.get(pk=500).role, "admin")
            self.assertEqual(Utilisateur.objects.get(pk=501).role, "contributeur")
        self.assertEqual(Utilisateur.objects.get(pk=501).role, "admin")  # principal inchangé
        self.assertEqual(set(Compte.objects.values_list("pk", flat=True)), {500, 501, 502})


class CommandeInchangeeTests(Base):
    def test_la_commande_ne_change_pas(self):
        """La ligne de commande garde ses options et ses contrôles : sans --unsigned, refusée ; avec, restaurée comme avant
        (sans la remise des comptes de l'écran)."""
        from django.core.management import call_command
        from django.core.management.base import CommandError

        a = self.ailleurs([compte(self.p + 1, "alice@exemple.test", "admin")])
        with self.assertRaises(CommandError):
            call_command("restore", str(a), "--yes", stdout=io.StringIO())
        call_command("restore", str(a), "--yes", "--unsigned", "--other-space", stdout=io.StringIO())
        self.assertEqual(json.loads(json.dumps(SV.historique_restaurations()[0], default=str)).get("autre_installation"),
                         None)
