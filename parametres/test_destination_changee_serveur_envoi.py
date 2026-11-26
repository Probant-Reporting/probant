"""Serveur d'envoi des e-mails (Paramètres › Hébergement) : le mot de passe enregistré ne part jamais vers une autre
destination que celle pour laquelle il a été saisi. Un autre serveur (sans la casse ni les espaces autour), un autre
port, un passage de la sécurité vers « Aucune » ou un autre identifiant, sans mot de passe saisi dans le même envoi :
le mot de passe est effacé, l'écran demande de le saisir de nouveau, l'historique note « mot de passe effacé (serveur
changé) » sans rien de secret. Avec un mot de passe saisi : il est enregistré. Même destination : rien ne change
(« champ vide = garder »)."""
from collecte.models import Journal
from espaces.aides_tests import creer
from espaces.essais import EspacesTestCase
from espaces.models import ServeurEnvoi
from parametres import envoi_emails as EE
from parametres.aides_tests.emails import EXPEDITEUR, HOTE, IDENTIFIANT, MDP, SANS_ENV, regler
from parametres.libelles import libelle
from parametres.test_detail_installation_permis import connecter

URL = "/administration/parametres/hebergement/"
MEME = {"action": "reglage_emails", "hote": HOTE, "port": "587", "securite": "starttls", "identifiant": IDENTIFIANT,
        "mot_de_passe": "", "expediteur": EXPEDITEUR}


@SANS_ENV
class DestinationChangeeTests(EspacesTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.gestionnaire = creer("gestion@exemple.example", "admin")

    def setUp(self):
        super().setUp()
        regler()  # HOTE:587, STARTTLS, IDENTIFIANT, avec le mot de passe MDP
        self.chiffre = ServeurEnvoi.objects.get().mot_de_passe_chiffre
        self.c = connecter(self.gestionnaire)

    def efface(self):
        return Journal.objects.filter(action="reglage_emails", champ="mot_de_passe", apres=EE.EFFACE_SERVEUR_CHANGE)

    def test_destination_changee_efface_le_mot_de_passe(self):
        cas = {"hote": {"hote": "smtp.autre.example"}, "port": {"port": "2525"},
               "securite_aucune": {"securite": "none", "port": "25"}, "identifiant": {"identifiant": "autre@outil.example"}}
        for nom, changement in cas.items():
            with self.subTest(nom):
                regler()
                Journal.objects.all().delete()
                rep = self.c.post(URL, {**MEME, **changement}, follow=True)
                s = ServeurEnvoi.objects.get()
                self.assertEqual((s.mot_de_passe_chiffre, s.mot_de_passe_le), ("", None))
                self.assertFalse(EE.reglage().mot_de_passe)
                self.assertContains(rep, libelle("admin.hebergement.smtp.mdp_efface_serveur").split(":")[0])
                self.assertContains(rep, "encart-avertissement")
                self.assertEqual(self.efface().count(), 1)
                textes = " ".join(f"{j.champ} {j.avant} {j.apres}" for j in Journal.objects.all())
                self.assertNotIn(MDP, textes)
                self.assertNotIn(self.chiffre, textes)

    def test_aucune_sans_question_quand_le_mot_de_passe_part(self):
        """Passer à « Aucune » sur un autre relais : le mot de passe enregistré ne partira pas (il est effacé), la case
        « envoyer en clair » n'est pas demandée."""
        rep = self.c.post(URL, {**MEME, "hote": "relais.interne.example", "port": "25", "securite": "none"})
        self.assertEqual(rep.status_code, 302)
        self.assertEqual((EE.reglage().securite, EE.reglage().mot_de_passe), ("none", False))

    def test_avec_un_mot_de_passe_saisi_il_est_enregistre(self):
        rep = self.c.post(URL, {**MEME, "hote": "smtp.autre.example", "mot_de_passe": "Nouveau-mdp-9"}, follow=True)
        self.assertContains(rep, "Réglages des e-mails enregistrés (smtp.autre.example)")
        self.assertEqual(EE.CH.dechiffrer(ServeurEnvoi.objects.get().mot_de_passe_chiffre, EE.CH.MOT_DE_PASSE_SMTP), "Nouveau-mdp-9")
        self.assertFalse(self.efface().exists())

    def test_meme_destination_garde_le_mot_de_passe(self):
        """Casse et espaces du nom du serveur, STARTTLS ↔ SSL, autre expéditeur : même destination."""
        for changement in ({"hote": f"  {HOTE.upper()} "}, {"securite": "ssl"}, {"expediteur": "autre@outil.example"}, {}):
            with self.subTest(changement):
                rep = self.c.post(URL, {**MEME, **changement}, follow=True)
                self.assertEqual(ServeurEnvoi.objects.get().mot_de_passe_chiffre, self.chiffre)
                self.assertNotContains(rep, libelle("admin.hebergement.smtp.mdp_efface_serveur").split(":")[0])
        self.assertFalse(self.efface().exists())

    def test_decide_sous_verrou_dans_enregistrer(self):
        """La règle vit dans ``envoi_emails.enregistrer`` (relu sous verrou), pas seulement dans l'écran."""
        changements = EE.enregistrer(None, "smtp.autre.example", 587, "starttls", IDENTIFIANT, EXPEDITEUR, "")
        self.assertIn(("mot_de_passe", "", EE.EFFACE_SERVEUR_CHANGE), changements)
        self.assertEqual(ServeurEnvoi.objects.get().mot_de_passe_chiffre, "")
        # rien à effacer : aucune ligne de plus
        changements = EE.enregistrer(None, "smtp.troisieme.example", 587, "starttls", IDENTIFIANT, EXPEDITEUR, "")
        self.assertNotIn(("mot_de_passe", "", EE.EFFACE_SERVEUR_CHANGE), changements)
