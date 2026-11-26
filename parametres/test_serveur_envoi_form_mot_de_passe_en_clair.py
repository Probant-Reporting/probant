"""Serveur d'e-mails réglé avec la sécurité « Aucune » ET un mot de passe : le mot de passe partirait en clair sur le
réseau (smtplib s'authentifie sans chiffrement). L'écran demande une confirmation explicite (case « envoyer le mot de
passe sans chiffrement ») ; sans elle, rien n'est enregistré et le champ Sécurité dit pourquoi. Un relais interne sans
mot de passe (cas normal de « Aucune ») s'enregistre sans rien demander."""
from espaces.aides_tests import creer
from espaces.essais import EspacesTestCase
from espaces.models import ServeurEnvoi
from parametres import envoi_emails as EE
from parametres.aides_tests.emails import SANS_ENV, regler
from parametres.libelles import libelle
from parametres.test_detail_installation_permis import connecter

URL = "/administration/parametres/hebergement/"
BASE = {"action": "reglage_emails", "hote": "relais.interne.example", "port": "25", "securite": "none", "identifiant": "",
        "mot_de_passe": "", "expediteur": "envoi@interne.example"}


@SANS_ENV
class MotDePasseEnClairTests(EspacesTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.gestionnaire = creer("gestion@exemple.example", "admin")

    def test_relais_sans_mot_de_passe_sans_question(self):
        rep = connecter(self.gestionnaire).post(URL, BASE)
        self.assertEqual(rep.status_code, 302)
        self.assertEqual((EE.reglage().securite, EE.reglage().mot_de_passe), ("none", False))

    def test_mot_de_passe_saisi_refuse_sans_confirmation(self):
        c = connecter(self.gestionnaire)
        rep = c.post(URL, {**BASE, "identifiant": "compte", "mot_de_passe": "Secret-en-clair-1"})
        self.assertEqual(rep.status_code, 200)
        self.assertIsNone(EE.ligne())
        self.assertContains(rep, 'id="erreur-smtp-securite"')
        self.assertContains(rep, libelle("admin.hebergement.smtp.erreur.en_clair").split(".")[0])
        self.assertContains(rep, 'name="en_clair"')
        rep = c.post(URL, {**BASE, "identifiant": "compte", "mot_de_passe": "Secret-en-clair-1", "en_clair": "on"})
        self.assertEqual(rep.status_code, 302)
        self.assertEqual((EE.reglage().securite, EE.reglage().mot_de_passe), ("none", True))

    def test_mot_de_passe_deja_enregistre_compte_aussi(self):
        # « Aucune » déjà en vigueur avec un mot de passe, même destination : il est gardé et partirait en clair. (Passer à
        # « Aucune » depuis STARTTLS ou SSL efface le mot de passe : test_destination_changee_serveur_envoi.)
        regler(hote=BASE["hote"], port=25, securite="none", identifiant="")
        rep = connecter(self.gestionnaire).post(URL, {**BASE, "expediteur": "autre@interne.example"})
        self.assertEqual(rep.status_code, 200)
        s = ServeurEnvoi.objects.get()
        self.assertNotEqual(s.expediteur, "autre@interne.example")  # rien n'est enregistré
        self.assertTrue(s.mot_de_passe_chiffre)

    def test_securite_chiffree_sans_question(self):
        rep = connecter(self.gestionnaire).post(URL, {**BASE, "securite": "starttls", "port": "587", "mot_de_passe": "x-1"})
        self.assertEqual(rep.status_code, 302)
