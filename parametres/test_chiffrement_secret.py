"""Chiffrement du mot de passe du serveur d'envoi avec le secret de l'installation (``chiffrement.py``) : relu à
l'identique, jamais en clair, deux chiffrements différents, et illisible (jamais un texte faux) avec un autre secret, une
valeur modifiée ou abîmée ; un secret de ``SECRET_KEY_FALLBACKS`` relit encore."""
from django.test import SimpleTestCase, override_settings

from parametres import chiffrement as CH

U = CH.MOT_DE_PASSE_SMTP


class ChiffrementTests(SimpleTestCase):
    def test_relu_a_l_identique_et_jamais_en_clair(self):
        for texte in ("Mdp-1", "é€ 漢字 avec espaces ", "x" * 512, ""):
            with self.subTest(texte=texte):
                v = CH.chiffrer(texte, U)
                self.assertTrue(v.startswith("v1$"))
                self.assertNotIn(texte or "\x00", v)
                self.assertEqual(CH.dechiffrer(v, U), texte)
        self.assertNotEqual(CH.chiffrer("meme", U), CH.chiffrer("meme", U))  # nonce aléatoire

    def test_autre_secret_illisible(self):
        v = CH.chiffrer("Mdp-SMTP", U)
        with override_settings(SECRET_KEY="un-tout-autre-secret-de-l-installation-0123456789"):
            with self.assertRaises(CH.Illisible):
                CH.dechiffrer(v, U)

    def test_ancien_secret_garde_dans_les_cles_de_repli(self):
        ancien = "ancien-secret-de-l-installation-0123456789-abcdef"
        v = CH.chiffrer("Mdp-SMTP", U, secret=ancien)
        with self.assertRaises(CH.Illisible):
            CH.dechiffrer(v, U)
        with override_settings(SECRET_KEY_FALLBACKS=[ancien]):
            self.assertEqual(CH.dechiffrer(v, U), "Mdp-SMTP")

    def test_valeur_modifiee_ou_abimee_illisible(self):
        import base64

        v = CH.chiffrer("Mdp-SMTP", U)
        brut = bytearray(base64.urlsafe_b64decode(v[3:]))
        brut[17] ^= 1  # un bit du texte chiffré
        abimees = ["v1$" + base64.urlsafe_b64encode(bytes(brut)).decode(), "v2" + v[2:], v[:-4], "", "v1$", "v1$!!!", "sans-dollar",
                   None, "v1$" + base64.urlsafe_b64encode(b"court").decode()]
        for a in abimees:
            with self.subTest(valeur=a), self.assertRaises(CH.Illisible):
                CH.dechiffrer(a, U)
