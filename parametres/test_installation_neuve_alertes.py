"""Alertes par e-mail allumées d'office sur une installation neuve (``alertes.installation_neuve``, ``alertes.reglage``),
inchangées (éteintes) sur une installation existante qui se met à jour ; un administrateur qui les éteint les garde
éteintes ; la page Santé dit l'état et pourquoi. Aussi : un problème nouveau part tout de suite, même quand un autre est
déjà en cours (sans attendre le rappel du jour)."""
import datetime

from django.core import mail
from django.db import connections
from django.db.migrations.recorder import MigrationRecorder
from django.test import Client

from espaces import contexte as E
from espaces.aides_tests import creer
from espaces.essais import EspacesTestCase
from espaces.models import Compte, EtatAlertes, ReglageAlertes
from parametres import alertes as AL
from parametres.aides_tests.alertes import DossierAlertes, disque_plein, installation_existante, passer
from referentiel.models import Utilisateur

URL = "/administration/parametres/sante/"


def page(u, espace="principal"):
    c = Client()
    with E.activer(espace):
        c.force_login(Utilisateur.objects.get(pk=u.pk))
    return c.get(URL if espace == "principal" else f"/espace/{espace}{URL}")


class InstallationNeuveTests(DossierAlertes, EspacesTestCase):
    """Base de test = installation neuve : migrations appliquées, puis comptes créés ; aucun réglage enregistré."""

    allumer = False

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.admin = creer("admin@exemple.example", "admin", first_name="Alice")
        cls.admin_essai = creer("admin.essai@exemple.example", "admin", "essai")

    def test_allumees_d_office_et_premier_probleme_envoye(self):
        self.assertFalse(ReglageAlertes.objects.exists())
        self.assertTrue(AL.installation_neuve())
        r = AL.reglage()
        self.assertTrue((r.actives, r.par_defaut) == (True, True))
        with disque_plein():
            self.assertEqual(passer()["nouveaux"], ["disque.panne"])
        self.assertEqual([m.to for m in mail.outbox], [["admin@exemple.example"]])  # comptes permis par défaut
        self.assertFalse(ReglageAlertes.objects.exists())  # rien n'est écrit pour décider

    def test_installation_existante_eteintes_tant_que_personne_ne_les_allume(self):
        installation_existante()
        self.assertFalse(AL.installation_neuve())
        self.assertFalse(AL.reglage().actives)
        with disque_plein():
            self.assertEqual(passer()["raison"], "off")
        self.assertEqual(mail.outbox, [])

    def test_comptes_d_avant_la_mise_a_jour_installation_existante(self):
        """Registre créé par cette version (mise à jour depuis une version sans espaces) : les comptes repris de la base
        principale gardent leur date de création, d'avant la migration des alertes."""
        appliquee = MigrationRecorder(connections["commun"]).migration_qs.get(app="espaces", name="0003_alertes_sante").applied
        Compte.objects.filter(pk=self.admin.pk).update(date_joined=appliquee - datetime.timedelta(days=400))
        self.assertFalse(AL.installation_neuve())
        self.assertFalse(AL.reglage().actives)

    def test_migration_des_alertes_absente_eteintes(self):
        MigrationRecorder(connections["commun"]).migration_qs.filter(app="espaces", name="0003_alertes_sante").delete()
        self.assertFalse(AL.installation_neuve())
        self.assertFalse(AL.reglage().actives)

    def test_eteintes_par_un_administrateur_restent_eteintes(self):
        AL.enregistrer(self.admin, False, True, "")
        self.assertTrue(AL.installation_neuve())
        r = AL.reglage()
        self.assertEqual((r.actives, r.par_defaut), (False, False))
        with disque_plein():
            self.assertEqual(passer()["raison"], "off")
            self.assertEqual(passer(60 * 24 * 3)["raison"], "off")
        self.assertEqual(mail.outbox, [])

    def test_premier_enregistrement_sans_changement_ne_refait_pas_partir_les_problemes(self):
        with disque_plein():
            passer()
            mail.outbox = []
            self.assertEqual(AL.enregistrer(self.admin, True, True, ""), [])  # rien ne change : alertes déjà allumées
            self.assertTrue(ReglageAlertes.objects.get().actives)
            self.assertEqual(passer(16)["toujours"], ["disque.panne"])
        self.assertEqual(mail.outbox, [])
        self.assertIn("disque.panne", EtatAlertes.objects.get().problemes)

    def test_la_page_dit_l_etat_et_pourquoi(self):
        rep = page(self.admin)
        self.assertContains(rep, "Les alertes par e-mail sont allumées.")
        self.assertContains(rep, "parce que cette installation est neuve. Éteignez-les ci-dessous")
        self.assertContains(rep, 'name="actives" id="id_actives" checked')
        rep = page(self.admin_essai, "essai")  # état seul : sans renvoi au formulaire qu'il ne voit pas
        self.assertContains(rep, "parce que cette installation est neuve.")
        self.assertNotContains(rep, "Éteignez-les ci-dessous")

    def test_la_page_dit_qui_les_a_eteintes(self):
        c = Client()
        c.force_login(Utilisateur.objects.get(pk=self.admin.pk))
        c.post(URL, {"action": "reglage_alertes", "aux_comptes": "on", "adresses": ""})
        rep = c.get(URL)
        self.assertContains(rep, "Les alertes par e-mail sont éteintes.")
        self.assertContains(rep, "Dernière modification par Alice")
        self.assertNotContains(rep, "installation est neuve")

    def test_la_page_d_une_installation_existante_dit_pourquoi_elles_sont_eteintes(self):
        installation_existante()
        rep = page(self.admin)
        self.assertContains(rep, "Les alertes par e-mail sont éteintes.")
        self.assertContains(rep, "Elles restent éteintes parce que cette installation existait avant les alertes par e-mail.")
        self.assertNotContains(rep, 'id="id_actives" checked')


class NouveauProblemeTests(DossierAlertes, EspacesTestCase):
    adresses = "it@exemple.example"

    def test_un_probleme_nouveau_part_tout_de_suite_pendant_qu_un_autre_dure(self):
        from unittest import mock

        from parametres import sauvegardes as SV
        from parametres.aides_tests.alertes import T0

        with disque_plein():
            passer()
            mail.outbox = []
            SV.noter_echec_auto(OSError("disque"))
            etat = {"active": True, "derniere": None, "prochaine": T0, "en_retard": False}
            with mock.patch.object(SV, "etat_automatique", return_value=etat):
                r = passer(60)  # une heure après : bien avant le rappel du jour
        self.assertEqual((r["nouveaux"], r["toujours"]), (["principal:sauvegarde.echec"], ["disque.panne"]))
        boite = [m for m in mail.outbox if "it@exemple.example" in m.to]
        self.assertEqual(len(boite), 1)
        self.assertIn("nouveau problème", boite[0].subject)
        self.assertIn("Dernière sauvegarde", boite[0].body)
        self.assertIn("Espace disque", boite[0].body)  # le problème en cours est rappelé dans le même e-mail
