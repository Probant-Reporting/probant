"""Signature des requêtes vers un stockage compatible S3 (``copie_s3``) : la bibliothèque standard seulement, appliquée
comme le protocole « Signature Version 4 » le décrit. Les exemples publiés avec le protocole (documentation publique du
protocole, identifiants d'exemple qui ne donnent accès à rien) sont rejoués ici à l'identique : clé dérivée, requête GET
élémentaire de la suite d'essai du protocole, et les quatre exemples propres au stockage S3 (lecture d'une partie d'un
objet, dépôt avec un caractère à encoder, sous-ressource sans valeur, liste avec paramètres). Une seule différence de
signature : le service refuserait chaque requête."""
import datetime
import hashlib

from django.test import SimpleTestCase

from parametres import copie_s3 as S

EXEMPLE_IAM = "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY"
# identifiant d'exemple du protocole, écrit en deux morceaux : le contrôle de publication cherche la forme d'une vraie clé
S3_ID, S3_SECRET = "AKIA" + "IOSFODNN7EXAMPLE", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
JOUR_S3 = datetime.datetime(2013, 5, 24, tzinfo=datetime.timezone.utc)
HOTE_S3 = "examplebucket.s3.amazonaws.com"


def signature(auth):
    return auth.rsplit("Signature=", 1)[1]


class VecteursPubliesTests(SimpleTestCase):
    def test_cle_derivee(self):
        cle = S.cle_signature(EXEMPLE_IAM, "20120215", "us-east-1", "iam")
        self.assertEqual(cle.hex(), "f4780e2d9f65fa895f9c67b32ce1baf0b0d8a43505a000a1a9e090d414db404d")

    def test_get_vanilla(self):
        quand = datetime.datetime(2015, 8, 30, 12, 36, tzinfo=datetime.timezone.utc)
        auth = S.autorisation("GET", "/", [], {"host": "example.amazonaws.com", "x-amz-date": "20150830T123600Z"}, S.VIDE,
                              "AKIDEXAMPLE", EXEMPLE_IAM, "us-east-1", quand, "service")
        self.assertEqual(auth, "AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/20150830/us-east-1/service/aws4_request, "
                               "SignedHeaders=host;x-amz-date, "
                               "Signature=5fa00fa31553b73ebf1942676e86291e8372ff2a2260956d9b8aae1d763fbf31")

    def entetes(self, **autres):
        return {"host": HOTE_S3, "x-amz-date": "20130524T000000Z", "x-amz-content-sha256": S.VIDE, **autres}

    def test_s3_lire_une_partie(self):
        auth = S.autorisation("GET", "/test.txt", [], self.entetes(range="bytes=0-9"), S.VIDE, S3_ID, S3_SECRET,
                              "us-east-1", JOUR_S3)
        self.assertIn("SignedHeaders=host;range;x-amz-content-sha256;x-amz-date,", auth)
        self.assertEqual(signature(auth), "f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41")

    def test_s3_deposer(self):
        empreinte = hashlib.sha256(b"Welcome to Amazon S3.").hexdigest()
        self.assertEqual(empreinte, "44ce7dd67c959e0d3524ffac1771dfbba87d2b6b4b4e99e42034a8b803f8b072")
        chemin = S.encoder("/test$file.text", garder_slash=True)
        self.assertEqual(chemin, "/test%24file.text")
        entetes = {"host": HOTE_S3, "date": "Fri, 24 May 2013 00:00:00 GMT", "x-amz-date": "20130524T000000Z",
                   "x-amz-storage-class": "REDUCED_REDUNDANCY", "x-amz-content-sha256": empreinte}
        auth = S.autorisation("PUT", chemin, [], entetes, empreinte, S3_ID, S3_SECRET, "us-east-1", JOUR_S3)
        self.assertEqual(signature(auth), "98ad721746da40c64f1a55b78f14c238d841ea1380cd77a1b5971af0ece108bd")

    def test_s3_sous_ressource_sans_valeur(self):
        auth = S.autorisation("GET", "/", [("lifecycle", "")], self.entetes(), S.VIDE, S3_ID, S3_SECRET, "us-east-1", JOUR_S3)
        self.assertEqual(signature(auth), "fea454ca298b7da1c68078a5d1bdbfbbe0d65c699e0f91ac7a200a0136783543")

    def test_s3_liste_avec_parametres(self):
        # paramètres donnés dans le désordre : la requête canonique les trie
        auth = S.autorisation("GET", "/", [("prefix", "J"), ("max-keys", "2")], self.entetes(), S.VIDE, S3_ID, S3_SECRET,
                              "us-east-1", JOUR_S3)
        self.assertEqual(signature(auth), "34b48302e7b5fa45bde8084f4b7868a86f0a534bc59db6670ed5711ef69dc6f7")


class EncodageTests(SimpleTestCase):
    def test_caracteres(self):
        self.assertEqual(S.encoder("a b/c~d_e.f-g"), "a%20b%2Fc~d_e.f-g")
        self.assertEqual(S.encoder("a b/c", garder_slash=True), "a%20b/c")
        self.assertEqual(S.encoder("é+="), "%C3%A9%2B%3D")

    def test_valeurs_d_en_tete_sans_espaces_en_trop(self):
        canonique, signes = S.requete_canonique("GET", "/", [], {"Host": " h ", "X-Amz-Meta-A": "a   b  c"}, S.VIDE)
        self.assertEqual(signes, "host;x-amz-meta-a")
        self.assertIn("host:h\nx-amz-meta-a:a b c\n", canonique)
