"""Alertes par e-mail de la santé de l'installation (``alertes.passage``) : un e-mail à l'apparition, un rappel au plus
par jour, un e-mail « résolu », un seul e-mail pour tout ce qui change dans un passage ; rien quand c'est éteint, ni sans
serveur d'envoi, ni pour une installation existante (aucune ligne de réglage) ; serveur d'envoi en panne : rien ne
plante, l'échec est journalisé, l'état n'avance pas et le passage suivant réessaie."""
import datetime
from unittest import mock

from django.core import mail
from django.test import override_settings

from espaces.aides_tests import creer
from espaces.essais import EspacesTestCase
from espaces.models import EtatAlertes, ReglageAlertes
from parametres import alertes as AL
from parametres import envoi_emails as EE
from parametres.aides_tests.alertes import SECRET, T0, DossierAlertes, disque_plein, installation_existante, passer
from parametres.aides_tests.emails import SMTP_REEL, port_ferme, regler


class PassageTests(DossierAlertes, EspacesTestCase):
    adresses = "it@exemple.example"

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.admin = creer("admin@exemple.example", "admin")  # administrateur de l'espace principal : destinataire

    def test_rien_sans_probleme(self):
        r = passer()
        self.assertTrue(r["fait"])
        self.assertEqual((r["nouveaux"], mail.outbox), ([], []))

    def test_apparition_un_e_mail_par_destinataire(self):
        with disque_plein():
            r = passer()
        self.assertEqual(r["nouveaux"], ["disque.panne"])
        self.assertEqual(sorted(m.to[0] for m in mail.outbox), ["admin@exemple.example", "it@exemple.example"])
        m = self.boite("it@exemple.example")[0]
        self.assertIn("nouveau problème", m.subject)
        self.assertIn("Probant", m.subject)  # nom de l'installation
        self.assertIn("Espace disque (En panne)", m.body)
        self.assertIn("Que faire :", m.body)  # mêmes textes que la page Santé
        self.assertIn("https://outil.example/administration/parametres/sante/", m.body)
        self.assertNotIn(str(SECRET), m.body)  # jamais un chemin du disque (détail pour l'IT de la page)
        self.assertNotIsInstance(m, mail.EmailMultiAlternatives)  # texte brut, comme les relances

    def test_pas_de_second_e_mail_tant_que_rien_ne_change(self):
        with disque_plein():
            passer()
            mail.outbox = []
            for minutes in (16, 32, 60, 600, 1400):
                self.assertEqual(passer(minutes)["toujours"], ["disque.panne"])
        self.assertEqual(mail.outbox, [])

    def test_rappel_au_plus_une_fois_par_jour(self):
        with disque_plein():
            passer()
            mail.outbox = []
            passer(24 * 60 + 1)
            self.assertEqual(len(self.boite("it@exemple.example")), 1)
            self.assertIn("toujours en cours", self.boite("it@exemple.example")[0].subject)
            mail.outbox = []
            passer(24 * 60 + 20)
            passer(47 * 60)
            self.assertEqual(mail.outbox, [])
            passer(48 * 60 + 2)
            self.assertEqual(len(self.boite("it@exemple.example")), 1)

    def test_resolu_apres_deux_passages_sans_le_probleme(self):
        with disque_plein():
            passer()
        mail.outbox = []
        self.assertEqual(passer(16)["resolus"], [])  # absent une fois : peut-être passager, rien n'est dit
        self.assertEqual(mail.outbox, [])
        self.assertEqual(passer(32)["resolus"], ["disque"])
        m = self.boite("it@exemple.example")[0]
        self.assertIn("résolu", m.subject)
        self.assertIn("Espace disque", m.body)
        mail.outbox = []
        passer(48)
        self.assertEqual(mail.outbox, [])  # plus rien à dire
        self.assertEqual(EtatAlertes.objects.get().problemes, {})

    def test_probleme_passager_jamais_dit_resolu(self):
        with disque_plein():
            passer()
        passer(16)  # absent une fois
        mail.outbox = []
        with disque_plein():
            r = passer(32)  # revenu : ni nouveau ni résolu
        self.assertEqual((r["nouveaux"], r["toujours"], r["resolus"], mail.outbox), ([], ["disque.panne"], [], []))

    def test_plusieurs_problemes_du_meme_passage_un_seul_e_mail(self):
        from parametres import sauvegardes as SV

        SV.noter_echec_auto(OSError("disque"))
        with disque_plein(), mock.patch.object(SV, "etat_automatique",
                                               return_value={"active": True, "derniere": None, "prochaine": T0, "en_retard": False}):
            r = passer()
        self.assertEqual(r["nouveaux"], ["disque.panne", "principal:sauvegarde.echec"])
        boite = self.boite("it@exemple.example")
        self.assertEqual(len(boite), 1)
        self.assertIn("2 nouveaux problèmes", boite[0].subject)
        self.assertIn("Espace disque", boite[0].body)
        self.assertIn("Dernière sauvegarde", boite[0].body)

    def test_un_cas_qui_en_remplace_un_autre_sur_la_meme_ligne(self):
        """Disque à regarder puis en panne : le nouveau cas part tout de suite, l'ancien n'est pas « résolu »."""
        from django.conf import settings

        bas = 5 * settings.ALERTE_DISQUE_MO * 1024 * 1024
        with mock.patch("parametres.vues_hebergement.espace_disque", return_value=(bas, SECRET)):
            self.assertEqual(passer()["nouveaux"], ["disque.bas"])
        mail.outbox = []
        with disque_plein():
            r = passer(16)
        self.assertEqual((r["nouveaux"], r["resolus"]), (["disque.panne"], []))
        self.assertEqual(len(self.boite("it@exemple.example")), 1)
        self.assertNotIn("Résolus", self.boite("it@exemple.example")[0].body)

    def test_un_passage_au_plus_toutes_les_15_minutes(self):
        with disque_plein():
            self.assertTrue(passer()["fait"])
            self.assertEqual(passer(5)["raison"], "busy")
            self.assertEqual(passer(14)["raison"], "busy")
            self.assertTrue(passer(15)["fait"])

    def test_eteintes_rien_n_est_envoye(self):
        AL.enregistrer(None, False, True, "it@exemple.example")
        with disque_plein():
            self.assertEqual(passer()["raison"], "off")
        self.assertEqual(mail.outbox, [])
        self.assertIsNone(EtatAlertes.objects.filter(pk=1).values_list("passage_le", flat=True).first())

    def test_rallumees_les_problemes_en_cours_repartent(self):
        with disque_plein():
            passer()
            AL.enregistrer(None, False, True, "it@exemple.example")
            AL.enregistrer(None, True, True, "it@exemple.example")
            mail.outbox = []
            self.assertEqual(passer(16)["nouveaux"], ["disque.panne"])
        self.assertEqual(len(self.boite("it@exemple.example")), 1)

    @override_settings(EMAIL_HOST="")
    def test_sans_serveur_d_envoi_rien_n_est_envoye(self):
        from espaces.models import ServeurEnvoi

        ServeurEnvoi.objects.all().delete()
        self.assertFalse(EE.envoi_actif())
        with disque_plein():
            self.assertEqual(passer()["raison"], "no_smtp")
        self.assertEqual(mail.outbox, [])

    def test_serveur_d_envoi_en_panne_rien_ne_plante_et_le_passage_suivant_reessaie(self):
        regler(hote="127.0.0.1", port=port_ferme(), securite="none", identifiant="", mot_de_passe="")
        with SMTP_REEL, disque_plein(), self.assertLogs("reporting.alertes", "WARNING") as journal:
            r = passer()
        self.assertEqual((r["envoyes"], r["erreur"]), (0, "refusee"))
        self.assertTrue(any("ConnectionRefusedError" in ligne for ligne in journal.output))
        e = EtatAlertes.objects.get()
        self.assertEqual((e.problemes, e.envoye_le, e.echec, e.echec_resume), ({}, None, "refusee", "ConnectionRefusedError"))
        # la page Santé le dit, et le constat reste visible
        regler()  # serveur revenu
        with disque_plein():
            r = passer(16)
        self.assertEqual((r["nouveaux"], r["envoyes"]), (["disque.panne"], 2))
        self.assertEqual(len(self.boite("it@exemple.example")), 1)

    def test_un_destinataire_refuse_n_empeche_pas_les_autres(self):

        envoyer = mail.EmailMessage.send

        def envoi(message, *a, **k):
            if message.to == ["it@exemple.example"]:
                import smtplib

                raise smtplib.SMTPRecipientsRefused({"it@exemple.example": (550, b"non")})
            return envoyer(message, *a, **k)

        with disque_plein(), mock.patch.object(mail.EmailMessage, "send", envoi), self.assertLogs("reporting.alertes", "WARNING"):
            r = passer()
        self.assertEqual(r["envoyes"], 1)
        self.assertEqual(list(EtatAlertes.objects.get().problemes), ["disque.panne"])  # parti : pas renvoyé à chaque passage

    def test_passage_planifie_n_arrete_jamais_la_boucle(self):
        with mock.patch.object(AL, "_premier", 0.0), mock.patch.object(AL, "passage", side_effect=RuntimeError("panne")), \
                self.assertLogs("reporting.alertes", "ERROR"):
            self.assertIsNone(AL.passage_planifie())

    def test_passage_planifie_attend_le_demarrage_des_autres_taches(self):
        with mock.patch.object(AL, "_premier", None), mock.patch.object(AL, "passage") as p:
            AL.passage_planifie()
        p.assert_not_called()


class InstallationExistanteTests(DossierAlertes, EspacesTestCase):
    """Mise à jour d'une installation existante : aucune ligne de réglage, alertes éteintes, aucun e-mail nouveau même
    avec un serveur d'envoi réglé et un problème en cours."""

    allumer = False

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        creer("admin@exemple.example", "admin")
        installation_existante()  # la base de test est sinon une installation neuve (alertes allumées d'office)

    def test_aucun_e_mail_sans_geste_de_l_administrateur(self):
        self.assertFalse(ReglageAlertes.objects.exists())
        self.assertTrue(EE.envoi_actif())
        self.assertFalse(AL.reglage().actives)
        with disque_plein():
            self.assertEqual(passer()["raison"], "off")
            self.assertEqual(passer(60 * 24 * 3)["raison"], "off")
        self.assertEqual(mail.outbox, [])

    def test_migration_additive_sans_ligne(self):
        from django.db import connections
        from django.db.migrations.recorder import MigrationRecorder

        noms = set(MigrationRecorder(connections["commun"]).applied_migrations())
        self.assertIn(("espaces", "0003_alertes_sante"), noms)
        self.assertFalse(EtatAlertes.objects.exists())
        tables = {"espaces_reglagealertes", "espaces_etatalertes", "espaces_problemesignale"}
        self.assertLessEqual(tables, set(connections["commun"].introspection.table_names()))
        for alias in ("default", "espace_essai"):  # jamais dans la base d'un espace (une restauration n'y touche pas)
            self.assertFalse(tables & set(connections[alias].introspection.table_names()), alias)


class PlusieursEspacesTests(DossierAlertes, EspacesTestCase):
    """Un problème d'un espace secondaire nomme l'espace ; un problème de toute l'installation n'est dit qu'une fois."""

    adresses = "it@exemple.example"

    def test_probleme_d_un_espace_nomme_l_espace(self):
        from espaces import contexte as E
        from parametres import sauvegardes as SV

        with E.activer("essai"):
            SV.noter_echec_auto(OSError("x"))
        etat = {"active": True, "derniere": None, "prochaine": T0, "en_retard": False}
        with disque_plein(), mock.patch.object(SV, "etat_automatique", return_value=etat):
            r = passer()
        self.assertEqual(r["nouveaux"], ["disque.panne", "essai:sauvegarde.echec"])  # disque : une seule fois
        corps = self.boite("it@exemple.example")[0].body
        self.assertEqual(corps.count("Espace disque"), 1)
        self.assertIn("Espace : Achats", corps)  # nom de l'espace « essai »

    def test_espace_injoignable_dit_comme_la_ligne_base_de_donnees(self):
        from parametres import sante_installation as SI

        vrai = SI.constats

        def constats(permis, https=None, codes=None):
            if codes == ["essai"]:
                raise RuntimeError("base injoignable")
            return vrai(permis, https, codes)

        with mock.patch.object(SI, "constats", side_effect=constats), self.assertLogs("reporting.alertes", "ERROR"):
            r = passer()
        self.assertEqual(r["nouveaux"], ["essai:base.panne"])
        self.assertIn("La base de données ne répond pas", self.boite("it@exemple.example")[0].body)


class EtatHorsDesEspacesTests(DossierAlertes, EspacesTestCase):
    adresses = "it@exemple.example"

    def test_etat_au_registre_commun_jamais_dans_l_archive_d_un_espace(self):
        from parametres import sauvegardes as SV

        modeles = {m._meta.label_lower for m in SV.modeles_sauvegardes()}
        self.assertFalse({"espaces.etatalertes", "espaces.reglagealertes", "espaces.problemesignale"} & modeles)
        self.assertIn("espaces.reglagealertes", SV.MODELES_REGISTRE)  # le réglage suit le registre (restore --shared)
        self.assertNotIn("espaces.etatalertes", SV.MODELES_REGISTRE)
        self.assertEqual(EtatAlertes.objects.db, "commun")

    def test_horloge_remise_en_arriere(self):
        with disque_plein():
            passer(60 * 5)
            self.assertTrue(passer()["fait"])  # passage noté 5 h « dans le futur » : repris
        self.assertEqual(EtatAlertes.objects.get().passage_le, T0)

    def test_rappel_apres_24_heures_exactes(self):
        with disque_plein():
            passer()
            mail.outbox = []
            passer(24 * 60 - 1)
            self.assertEqual(mail.outbox, [])
            passer(24 * 60 + 15)
        self.assertTrue(mail.outbox)
        self.assertEqual(EtatAlertes.objects.get().envoye_le, T0 + datetime.timedelta(minutes=24 * 60 + 15))
