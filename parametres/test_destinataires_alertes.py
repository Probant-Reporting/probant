"""Destinataires des alertes par e-mail (``alertes.destinataires``) : par défaut les personnes qui voient le détail de
l'installation (même règle que ``detail_installation_permis`` : administrateurs actifs de l'espace principal,
gestionnaires des espaces), plus les adresses saisies ; jamais un administrateur d'un autre espace, un contributeur, un
compte désactivé. Chaque compte reçoit l'e-mail dans sa langue ; une adresse saisie, dans celle de l'installation."""
from django.core import mail

from espaces.aides_tests import creer
from espaces.essais import EspacesTestCase
from espaces.models import Compte
from parametres import alertes as AL
from parametres.aides_tests.alertes import DossierAlertes, disque_plein, passer
from referentiel.models import Utilisateur

from . import sante_installation as SI


class DestinatairesTests(DossierAlertes, EspacesTestCase):
    adresses = "IT@exemple.example\nautre@exemple.example"

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.admin = creer("admin@exemple.example", "admin")
        cls.admin_en = creer("admin.en@exemple.example", "admin", langue="en")
        cls.contrib = creer("contrib@exemple.example")
        cls.admin_essai = creer("admin.essai@exemple.example", "admin", "essai")  # administrateur de « essai » seulement
        cls.gestionnaire = creer("gestion@exemple.example", "contributeur", "essai")
        Compte.objects.filter(pk=cls.gestionnaire.pk).update(gestionnaire=True)
        cls.inactif = creer("ancien@exemple.example", "admin")
        Utilisateur.objects.filter(pk=cls.inactif.pk).update(is_active=False)

    def adresses_(self):
        return [a for a, _ in AL.destinataires()]

    def test_meme_regle_que_le_detail_de_l_installation(self):
        from espaces import contexte as E

        attendus = set()
        for u in (self.admin, self.admin_en, self.contrib, self.admin_essai, self.gestionnaire, self.inactif):
            for code in ("principal", "essai"):
                with E.activer(code):
                    copie = Utilisateur.objects.filter(pk=u.pk).first()
                    if copie is not None and SI.detail_installation_permis(copie):
                        attendus.add(u.email)
        self.assertEqual({a for a, _, _ in AL.comptes_permis()}, attendus)
        self.assertEqual(attendus, {"admin@exemple.example", "admin.en@exemple.example", "gestion@exemple.example"})

    def test_comptes_puis_adresses_saisies_sans_doublon(self):
        AL.enregistrer(None, True, True, "it@exemple.example\nADMIN@exemple.example\nautre@exemple.example")
        self.assertEqual(self.adresses_(), ["admin.en@exemple.example", "admin@exemple.example", "gestion@exemple.example",
                                            "it@exemple.example", "autre@exemple.example"])

    def test_sans_les_comptes(self):
        AL.enregistrer(None, True, False, "it@exemple.example")
        self.assertEqual(self.adresses_(), ["it@exemple.example"])

    def test_compte_desactive_au_registre(self):
        Compte.objects.filter(pk=self.admin.pk).update(actif=False)
        self.assertNotIn("admin@exemple.example", self.adresses_())

    def test_chacun_dans_sa_langue(self):
        with disque_plein():
            passer()
        sujets = {m.to[0]: m.subject for m in mail.outbox}
        self.assertIn("new problem", sujets["admin.en@exemple.example"])
        self.assertIn("nouveau problème", sujets["admin@exemple.example"])
        self.assertIn("nouveau problème", sujets["IT@exemple.example"])  # langue de l'installation
        self.assertEqual(len(mail.outbox), 5)
        self.assertTrue(all(len(m.to) == 1 and not m.cc and not m.bcc for m in mail.outbox))  # personne ne voit les autres

    def test_lire_adresses(self):
        self.assertEqual(AL.lire_adresses("a@x.example, b@x.example;\n a@X.example \n pas-une-adresse"),
                         (["a@x.example", "b@x.example"], ["pas-une-adresse"]))
