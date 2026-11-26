"""Chaque texte chiffré est lié à son usage (``chiffrement.chiffrer(texte, usage)``) : le nom de l'usage entre dans le
sceau et dans la dérivation du flux. Un secret recopié d'un champ à un autre (par exemple la clé secrète S3 de la copie
externe mise à la place du mot de passe du serveur d'e-mails, par quelqu'un qui écrit dans la base) ne se déchiffre
pas : l'outil dit « illisible » au lieu de l'envoyer à un autre serveur."""
from django.test import SimpleTestCase, TestCase

from espaces.models import DestinationCopie, ServeurEnvoi
from parametres import chiffrement as CH
from parametres import envoi_emails as EE
from parametres.aides_tests.emails import SANS_ENV, regler


class UsageTests(SimpleTestCase):
    def test_lu_seulement_pour_son_usage(self):
        for usage in CH.USAGES:
            v = CH.chiffrer("Secret-9", usage)
            self.assertEqual(CH.dechiffrer(v, usage), "Secret-9")
            for autre in CH.USAGES - {usage}:
                with self.subTest(usage=usage, autre=autre), self.assertRaises(CH.Illisible):
                    CH.dechiffrer(v, autre)

    def test_usage_inconnu_refuse(self):
        with self.assertRaises(ValueError):
            CH.chiffrer("x", "usage-inconnu")
        with self.assertRaises(ValueError):
            CH.dechiffrer(CH.chiffrer("x", CH.MOT_DE_PASSE_SMTP), "usage-inconnu")


@SANS_ENV
class RecopieTests(TestCase):
    databases = {"default", "commun"}

    def test_secret_de_la_copie_recopie_dans_le_serveur_d_e_mails(self):
        regler()
        DestinationCopie.objects.create(pk=1, genre="s3", secret_chiffre=CH.chiffrer("Cle-S3-secrete", CH.SECRET_COPIE))
        ServeurEnvoi.objects.filter(pk=1).update(mot_de_passe_chiffre=DestinationCopie.objects.get().secret_chiffre)
        self.assertTrue(EE.reglage().mot_de_passe_illisible)
        with self.assertRaises(EE.MotDePasseIllisible):
            EE.connexion_envoi()
