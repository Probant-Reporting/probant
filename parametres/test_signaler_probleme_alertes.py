"""Problème signalé par une autre partie de l'outil (``alertes.signaler`` / ``alertes.resoudre``, pour la mise à jour
automatique ou la copie externe des sauvegardes) : montré sur la page Santé, envoyé comme les autres constats, dans la
langue de chaque destinataire, « résolu » quand il est retiré ; le détail pour l'IT reste sur la page."""
from django.core import mail
from django.test import Client

from espaces import contexte as E
from espaces.aides_tests import creer
from espaces.essais import EspacesTestCase
from parametres import alertes as AL
from parametres.aides_tests.alertes import DossierAlertes, passer
from referentiel.models import Utilisateur

URL = "/administration/parametres/sante/"


class SignalerTests(DossierAlertes, EspacesTestCase):
    adresses = "it@exemple.example"

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.admin = creer("admin@exemple.example", "admin", langue="en")
        cls.admin_essai = creer("admin.essai@exemple.example", "admin", "essai")

    def signaler(self, **k):
        # textes : des clés de libellé existantes, comme le ferait un lot suivant avec les siennes
        AL.signaler("copie_externe", "admin.sante.sauvegarde.titre", "admin.sante.sauvegarde.echec",
                    "admin.sante.sauvegarde.echec_quoi", {"quand": "25/11/2026"}, detail="/chemin/secret/copie", **k)

    def test_page_et_e_mail_puis_resolu(self):
        self.signaler()
        c = Client()
        c.force_login(Utilisateur.objects.get(pk=self.admin.pk))
        rep = c.get(URL)
        ligne = next(x for x in rep.context["lignes"] if x["cle"] == "signal-copie_externe")
        self.assertEqual((ligne["etat"], ligne["detail"]), ("panne", "/chemin/secret/copie"))
        self.assertContains(rep, "The last automatic backup failed (25/11/2026).")  # dans la langue de la personne
        r = passer()
        self.assertEqual(r["nouveaux"], ["signal-copie_externe"])
        self.assertIn("failed (25/11/2026)", next(m for m in mail.outbox if m.to == ["admin@exemple.example"]).body)
        it = next(m for m in mail.outbox if m.to == ["it@exemple.example"]).body
        self.assertIn("La dernière sauvegarde automatique a échoué (25/11/2026).", it)
        self.assertNotIn("/chemin/secret/copie", it)  # détail pour l'IT : page seulement
        AL.resoudre("copie_externe")
        mail.outbox = []
        passer(16)
        self.assertEqual(passer(32)["resolus"], ["signal-copie_externe"])
        self.assertIn("Dernière sauvegarde", next(m for m in mail.outbox if m.to == ["it@exemple.example"]).body)

    def test_probleme_d_un_espace(self):
        self.signaler(espace="essai")
        c = Client()
        with E.activer("essai"):
            c.force_login(Utilisateur.objects.get(pk=self.admin_essai.pk))
        rep = c.get(f"/espace/essai{URL}")
        ligne = next(x for x in rep.context["lignes"] if x["cle"] == "signal-copie_externe")
        self.assertEqual(ligne["detail"], "")  # administrateur d'un autre espace : pas de détail pour l'IT
        self.assertEqual(passer()["nouveaux"], ["essai:signal-copie_externe"])
        self.assertIn("Espace : Achats", next(m for m in mail.outbox if m.to == ["it@exemple.example"]).body)

    def test_un_espace_ne_voit_pas_le_probleme_d_un_autre(self):
        self.signaler(espace="principal")
        c = Client()
        with E.activer("essai"):
            c.force_login(Utilisateur.objects.get(pk=self.admin_essai.pk))
        rep = c.get(f"/espace/essai{URL}")
        self.assertNotIn("signal-copie_externe", [x["cle"] for x in rep.context["lignes"]])

    def test_mise_a_jour_sans_doublon_et_etat_controle(self):
        self.signaler()
        self.signaler()
        from espaces.models import ProblemeSignale

        self.assertEqual(ProblemeSignale.objects.count(), 1)
        with self.assertRaises(ValueError):
            AL.signaler("x", "a", "b", etat="bon")
        AL.resoudre("inconnu")  # sans effet
