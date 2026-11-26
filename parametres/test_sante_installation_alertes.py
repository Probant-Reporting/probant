"""Page Paramètres › Santé, bloc « Alertes par e-mail » (``vues_hebergement.sante_installation``) : réglé par un
gestionnaire des espaces (formulaire, enregistrement, historique ; ici le premier administrateur de l'espace principal),
alerte d'essai pour qui voit le détail de l'installation ; l'administrateur d'un autre espace
voit l'état seul et ses envois sont refusés (403) ; un envoi non valide garde la page et dit pourquoi."""
from django.core import mail
from django.test import Client

from collecte.models import Journal
from espaces import contexte as E
from espaces.aides_tests import creer
from espaces.essais import EspacesTestCase
from espaces.models import ReglageAlertes
from parametres import alertes as AL
from parametres.aides_tests.alertes import DossierAlertes, disque_plein, installation_existante
from parametres.aides_tests.emails import SMTP_REEL, port_ferme, regler
from referentiel.models import Utilisateur

URL = "/administration/parametres/sante/"


def connecter(u, espace="principal"):
    c = Client()
    with E.activer(espace):
        c.force_login(Utilisateur.objects.get(pk=u.pk))
    return c


class PageAlertesTests(DossierAlertes, EspacesTestCase):
    allumer = False

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.admin = creer("admin@exemple.example", "admin", first_name="Alice")
        cls.admin_essai = creer("admin.essai@exemple.example", "admin", "essai")
        installation_existante()  # installation neuve : voir test_installation_neuve_alertes

    def test_eteintes_par_defaut_et_formulaire_pour_qui_voit_le_detail(self):
        rep = connecter(self.admin).get(URL)
        self.assertContains(rep, 'id="alertes"')
        self.assertContains(rep, "Les alertes par e-mail sont éteintes.")
        self.assertContains(rep, 'name="action" value="reglage_alertes"')
        self.assertContains(rep, 'name="action" value="tester_alertes"')
        self.assertContains(rep, "Alice")  # destinataire par défaut nommé

    def test_administrateur_d_un_autre_espace_etat_seul_et_envois_refuses(self):
        c = connecter(self.admin_essai, "essai")
        rep = c.get(f"/espace/essai{URL}")
        self.assertEqual(rep.status_code, 200)
        self.assertContains(rep, "Les alertes par e-mail sont éteintes.")
        self.assertNotContains(rep, 'value="reglage_alertes"')
        self.assertNotContains(rep, "admin@exemple.example")  # ni les destinataires
        for action in ("reglage_alertes", "tester_alertes"):
            rep = c.post(f"/espace/essai{URL}", {"action": action, "actives": "on", "adresses": "x@exemple.example"})
            self.assertEqual(rep.status_code, 403, action)
        self.assertFalse(ReglageAlertes.objects.exists())
        self.assertEqual(mail.outbox, [])

    def test_enregistrer_et_historique(self):
        c = connecter(self.admin)
        rep = c.post(URL, {"action": "reglage_alertes", "actives": "on", "aux_comptes": "on", "adresses": "it@exemple.example"})
        self.assertRedirects(rep, URL + "#alertes", fetch_redirect_response=False)
        r = AL.reglage()
        self.assertEqual((r.actives, r.aux_comptes, r.adresses, r.modifie_par), (True, True, "it@exemple.example", self.admin.pk))
        champs = set(Journal.objects.filter(action="reglage_alertes").values_list("champ", "apres"))
        self.assertEqual(champs, {("actives", "True"), ("adresses", "1")})  # le nombre d'adresses, pas les adresses
        rep = c.get(URL)
        self.assertContains(rep, "Les alertes par e-mail sont allumées.")
        self.assertContains(rep, "Elles partent à 2 destinataires.")
        self.assertEqual(c.get(URL).status_code, 200)

    def test_adresse_non_valide_et_aucun_destinataire(self):
        c = connecter(self.admin)
        rep = c.post(URL, {"action": "reglage_alertes", "actives": "on", "aux_comptes": "on", "adresses": "it@exemple.example\npas-valide"})
        self.assertEqual(rep.status_code, 200)
        self.assertContains(rep, "Ces adresses ne sont pas valides : pas-valide.")
        self.assertContains(rep, 'aria-describedby="erreur-alertes-adresses aide-alertes-adresses"')
        rep = c.post(URL, {"action": "reglage_alertes", "actives": "on", "adresses": ""})
        self.assertContains(rep, "Choisissez au moins un destinataire.")
        self.assertFalse(ReglageAlertes.objects.exists())

    def test_alerte_d_essai(self):
        AL.enregistrer(self.admin, True, False, "it@exemple.example")
        with disque_plein():
            rep = connecter(self.admin).post(URL, {"action": "tester_alertes"}, follow=True)
        self.assertContains(rep, "Alerte d&#x27;essai envoyée à 1 destinataire.")
        self.assertEqual(len(mail.outbox), 1)
        m = mail.outbox[0]
        self.assertIn("alerte d'essai", m.subject)
        self.assertIn("Problèmes du moment", m.body)
        self.assertIn("Espace disque", m.body)
        self.assertIn("Alice", m.body)  # qui l'a envoyée
        self.assertTrue(Journal.objects.filter(action="test_alerte").exists())
        self.assertEqual(AL.etat().problemes, {})  # l'essai ne compte pas comme une alerte envoyée

    def test_alerte_d_essai_serveur_en_panne(self):
        AL.enregistrer(self.admin, True, False, "it@exemple.example")
        regler(hote="127.0.0.1", port=port_ferme(), securite="none", identifiant="", mot_de_passe="")
        with SMTP_REEL, self.assertLogs("reporting.alertes", "WARNING"):
            rep = connecter(self.admin).post(URL, {"action": "tester_alertes"}, follow=True)
        self.assertContains(rep, "a refusé la connexion")
        self.assertTrue(Journal.objects.filter(action="test_alerte_echec").exists())
        rep = connecter(self.admin).get(URL)
        self.assertContains(rep, "a pas pu partir (")
        self.assertContains(rep, "(ConnectionRefusedError)")  # résumé technique pour qui voit le détail

    def test_allumees_sans_serveur_d_envoi(self):
        from django.test import override_settings

        from espaces.models import ServeurEnvoi

        AL.enregistrer(self.admin, True, True, "")
        ServeurEnvoi.objects.all().delete()
        with override_settings(EMAIL_HOST=""):
            rep = connecter(self.admin).get(URL)
            self.assertContains(rep, "aucune alerte ne peut partir")
            rep = connecter(self.admin).post(URL, {"action": "tester_alertes"}, follow=True)
            self.assertContains(rep, "L&#x27;envoi des e-mails n&#x27;est pas réglé.")
        self.assertEqual(mail.outbox, [])
