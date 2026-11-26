"""Qui règle le serveur d'envoi des e-mails (Paramètres › Hébergement) : un réglage de l'INSTALLATION, gardé au registre
commun, modifiable seulement par un gestionnaire des espaces (``espaces.comptes.est_gestionnaire`` ; ici le premier
administrateur de l'espace principal, devenu gestionnaire ; un administrateur de l'espace principal qui ne l'est pas :
``test_est_gestionnaire_reglages_installation``) ; l'administrateur d'un autre espace le voit en lecture seule (sans
l'identifiant) et son envoi est refusé ; lecteur, auditeur, contributeur et validateur n'écrivent rien. Une valeur pour
tous les espaces : réglée dans un espace, elle sert aux relances et au test de chaque espace."""
from django.core import mail
from collecte.models import Journal
from espaces import contexte as E
from espaces.aides_tests import creer
from espaces.essais import EspacesTestCase
from espaces.models import Compte, ServeurEnvoi
from parametres import envoi_emails as EE
from parametres.aides_tests.emails import EXPEDITEUR, HOTE, IDENTIFIANT, MDP, SANS_ENV, SMTP_REEL, regler
from parametres.test_detail_installation_permis import connecter

URL = "/administration/parametres/hebergement/"
FORMULAIRE = {"action": "reglage_emails", "hote": "smtp.nouveau.example", "port": "465", "securite": "ssl",
              "identifiant": "nouveau@nouveau.example", "mot_de_passe": "Nouveau-mdp-9", "expediteur": "envoi@nouveau.example"}


@SANS_ENV
class DroitsTests(EspacesTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.admin = creer("admin@exemple.example", "admin")
        cls.admin_essai = creer("admin.essai@exemple.example", "admin", "essai")
        cls.autres = {r: creer(f"{r}@exemple.example", r) for r in ("lecteur", "auditeur", "contributeur", "validateur")}

    def etat(self):
        s = ServeurEnvoi.objects.filter(pk=1).first()
        return None if s is None else (s.hote, s.port, s.securite, s.identifiant, s.mot_de_passe_chiffre, s.expediteur)

    def test_gestionnaire_de_l_espace_principal_regle(self):
        c = connecter(self.admin)
        page = c.get(URL).content.decode()
        self.assertIn('name="hote"', page)
        self.assertIn('autocomplete="new-password"', page)
        rep = c.post(URL, FORMULAIRE, follow=True)
        self.assertContains(rep, "Réglages des e-mails enregistrés (smtp.nouveau.example)")
        r = EE.reglage()
        self.assertEqual((r.source, r.hote, r.port, r.securite, r.identifiant, r.expediteur),
                         (EE.OUTIL, "smtp.nouveau.example", 465, "ssl", "nouveau@nouveau.example", "envoi@nouveau.example"))
        self.assertEqual(ServeurEnvoi.objects.get().modifie_par, self.admin.pk)
        champs = set(Journal.objects.filter(action="reglage_emails").values_list("champ", flat=True))
        self.assertEqual(champs, {"hote", "port", "securite", "identifiant", "expediteur", "mot_de_passe"})

    def test_administrateur_d_un_autre_espace_lecture_seule(self):
        regler()
        avant = self.etat()
        c = connecter(self.admin_essai, "essai")
        page = c.get(f"/espace/essai{URL}").content.decode()
        self.assertNotIn('name="hote"', page)
        self.assertIn(f"{HOTE}:587 (STARTTLS)", page)  # le serveur reste dit
        self.assertIn("Réglé dans l'outil par un gestionnaire des espaces", page)
        self.assertNotIn(IDENTIFIANT, page)  # détail de l'installation
        for action in ("reglage_emails", "effacer_mdp_emails"):
            rep = c.post(f"/espace/essai{URL}", {**FORMULAIRE, "action": action})
            self.assertEqual(rep.status_code, 403, action)
        self.assertEqual(self.etat(), avant)

    def test_gestionnaire_des_espaces_regle_depuis_un_autre_espace(self):
        Compte.objects.filter(pk=self.admin_essai.pk).update(gestionnaire=True)
        c = connecter(self.admin_essai, "essai")
        rep = c.post(f"/espace/essai{URL}", FORMULAIRE)
        self.assertEqual(rep.status_code, 302)
        with E.activer("essai"):
            self.assertTrue(Journal.objects.filter(action="reglage_emails").exists())  # historique de l'espace où l'on était
        self.assertFalse(Journal.objects.filter(action="reglage_emails").exists())
        self.assertEqual(EE.reglage().hote, "smtp.nouveau.example")  # lu depuis l'espace principal : même valeur

    def test_roles_sans_droit_n_ecrivent_rien(self):
        regler()
        avant = self.etat()
        for role, u in self.autres.items():
            c = connecter(u)
            for action in ("reglage_emails", "effacer_mdp_emails", "tester_email"):
                rep = c.post(URL, {**FORMULAIRE, "action": action, "destinataire": "x@exemple.test"})
                self.assertEqual(rep.status_code, 403, f"{role} {action}")
        self.assertEqual(self.etat(), avant)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(ServeurEnvoi.objects.get().essais, [])

    def test_une_valeur_pour_tous_les_espaces(self):
        regler()
        with E.activer("essai"):
            self.assertEqual((EE.reglage().source, EE.reglage().hote), (EE.OUTIL, HOTE))
            self.assertEqual(EE.connexion_envoi()[1], EXPEDITEUR)
        # test d'envoi depuis l'autre espace : réglages de l'installation
        c = connecter(self.admin_essai, "essai")
        rep = c.post(f"/espace/essai{URL}", {"action": "tester_email", "destinataire": "it@exemple.test"}, follow=True)
        self.assertContains(rep, "E-mail de test envoyé à it@exemple.test")
        self.assertEqual(mail.outbox[0].from_email, EXPEDITEUR)

    def test_rien_dans_les_bases_des_espaces(self):
        """La table n'existe qu'au registre commun (migration espaces 0002) ; aucune base d'espace ne la reçoit."""
        from django.db import connections

        tables = {alias: connections[alias].introspection.table_names() for alias in ("default", "commun", "espace_essai")}
        self.assertIn("espaces_serveurenvoi", tables["commun"])
        self.assertNotIn("espaces_serveurenvoi", tables["default"])
        self.assertNotIn("espaces_serveurenvoi", tables["espace_essai"])


@SANS_ENV
class MotDePasseDansLeFormulaireTests(EspacesTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.admin = creer("admin@exemple.example", "admin")

    @staticmethod
    def mot_de_passe_utilise():
        with SMTP_REEL:  # connexion SMTP préparée (pas ouverte) : le mot de passe qu'elle enverrait
            return EE.connexion_envoi()[0].password

    def test_champ_vide_garde_le_mot_de_passe_et_un_geste_l_efface(self):
        c = connecter(self.admin)
        regler()
        chiffre = ServeurEnvoi.objects.get().mot_de_passe_chiffre
        # même destination (un autre serveur efface le mot de passe : test_destination_changee_serveur_envoi)
        c.post(URL, {**FORMULAIRE, "hote": HOTE, "port": "587", "securite": "starttls", "identifiant": IDENTIFIANT,
                     "mot_de_passe": ""})
        s = ServeurEnvoi.objects.get()
        self.assertEqual((s.expediteur, s.mot_de_passe_chiffre), ("envoi@nouveau.example", chiffre))
        self.assertEqual(self.mot_de_passe_utilise(), MDP)
        page = c.get(URL).content.decode()
        self.assertIn("Un mot de passe est enregistré depuis le", page)
        self.assertIn('value="effacer_mdp_emails"', page)
        rep = c.post(URL, {"action": "effacer_mdp_emails"}, follow=True)
        self.assertContains(rep, "Le mot de passe du serveur d&#x27;e-mails est effacé.")
        self.assertEqual(ServeurEnvoi.objects.get().mot_de_passe_chiffre, "")
        self.assertEqual(self.mot_de_passe_utilise(), "")
        self.assertTrue(Journal.objects.filter(action="reglage_emails", champ="mot_de_passe", apres="mot de passe effacé").exists())

    def test_saisies_refusees(self):
        c = connecter(self.admin)
        cas = {"hote": ("smtp://smtp.example.com", "sans « smtp:// »"), "port": ("0", "entre 1 et 65535"),
               "expediteur": ("", "Saisissez l&#x27;adresse d&#x27;expédition"),
               "mot_de_passe": ("ligne\r\nRCPT TO:<x@y>", "Retirez les retours à la ligne")}
        for champ, (valeur, message) in cas.items():
            with self.subTest(champ=champ):
                rep = c.post(URL, {**FORMULAIRE, champ: valeur})
                self.assertEqual(rep.status_code, 200)
                self.assertContains(rep, message)
                self.assertContains(rep, f'id="erreur-smtp-{champ}"')
                self.assertNotContains(rep, "RCPT TO")  # le mot de passe refusé n'est pas réaffiché
                self.assertIsNone(EE.ligne())  # rien n'est enregistré
        rep = c.post(URL, {**FORMULAIRE, "hote": "smtp.example.com:587"})
        self.assertContains(rep, "sans le port")


@SANS_ENV
class SanteTests(EspacesTestCase):
    """Paramètres › Santé : la ligne « E-mails » suit les réglages en vigueur ; d'où ils viennent est un détail de
    l'installation (gestionnaire des espaces, administrateur de l'espace principal)."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.admin = creer("admin@exemple.example", "admin")
        cls.admin_essai = creer("admin.essai@exemple.example", "admin", "essai")

    def ligne(self, client, prefixe=""):
        rep = client.get(f"{prefixe}/administration/parametres/sante/")
        return next(x for x in rep.context["lignes"] if x["cle"] == "email")

    def test_reglage_de_l_outil(self):
        self.assertEqual(self.ligne(connecter(self.admin))["etat"], "regarder")  # rien de réglé
        regler()
        ligne = self.ligne(connecter(self.admin))
        self.assertEqual((ligne["etat"], ligne["detail"]), ("bon", f"réglé dans l'outil, Paramètres › Hébergement ({HOTE}:587)"))
        ligne = self.ligne(connecter(self.admin_essai, "essai"), "/espace/essai")
        self.assertEqual((ligne["etat"], ligne["detail"]), ("bon", ""))
