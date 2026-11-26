"""Cas d'attaque et refus de la connexion d'entreprise, contre le faux fournisseur : chaque cas laisse la personne non
connectée, écrit une ligne « echec » (méthode « entreprise », motif) dans l'historique, et renvoie à la page de
connexion avec un message simple. Un compte inconnu, désactivé, bloqué ou en double reçoit le même message : la page ne
dit pas si l'adresse existe."""
from django.test import Client

from espaces.models import Compte
from parametres.libelles import libelle
from referentiel.models import HistoriqueConnexion, Utilisateur

from .aides_tests import RETOUR, BaseEntreprise
from .models import LienEntreprise

MESSAGE_COMPTE = "cadre.connexion.entreprise.refus.compte"


def messages_de(client):
    """Messages montrés par la page de connexion (rendus dans sa carte)."""
    return [str(m) for m in client.get("/connexion/").context["messages"]]


class AttaquesTests(BaseEntreprise):
    def setUp(self):
        super().setUp()
        self.regler()

    def refuse(self, motif, message="cadre.connexion.entreprise.refus.technique", c=None, r=None, lien=False):
        if r is None and motif == "fournisseur":  # cause technique : écrite au journal du serveur (avertissement)
            with self.assertLogs("connexion_entreprise", "WARNING"):
                c, r = self.parcours()
        elif r is None:
            c, r = self.parcours()
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r["Location"], "/connexion/")
        self.assertIsNone(self.connecte(c))
        self.assertEqual(messages_de(c), [libelle(message)])
        h = HistoriqueConnexion.objects.order_by("-pk").first()
        self.assertEqual((h.resultat, h.methode, h.motif), ("echec", "entreprise", motif))
        self.assertEqual(LienEntreprise.objects.exists(), lien)
        return h

    # ------------------------------------------------------------ state, nonce, jeton
    def test_state_rejoue(self):
        c, r = self.aller()
        import urllib.parse

        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(r["Location"]).query))
        params = {"code": self.faux.emettre_code(q), "state": q["state"]}
        premiere = c.get(RETOUR, params)
        self.assertEqual(int(self.connecte(c)), self.contrib.pk)
        c.post("/deconnexion/")
        self.assertEqual(premiere.status_code, 302)
        # même retour rejoué (même navigateur, puis un autre) : refusé, personne n'est connecté
        params["code"] = self.faux.emettre_code(q)
        self.refuse("expiree", "cadre.connexion.entreprise.refus.expiree", c, c.get(RETOUR, params), lien=True)
        autre = Client()
        self.refuse("expiree", "cadre.connexion.entreprise.refus.expiree", autre, autre.get(RETOUR, params), lien=True)

    def test_state_ne_sert_qu_une_fois_meme_session(self):
        """Premier retour refusé (code faux chez le fournisseur) : le même ``state`` rejoué dans la même session avec un
        bon code est refusé, la personne n'est pas connectée."""
        import urllib.parse

        c, r = self.aller()
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(r["Location"]).query))
        with self.assertLogs("connexion_entreprise", "WARNING"):
            self.refuse("fournisseur", c=c, r=c.get(RETOUR, {"code": "code-faux", "state": q["state"]}))
        self.refuse("expiree", "cadre.connexion.entreprise.refus.expiree", c,
                    c.get(RETOUR, {"code": self.faux.emettre_code(q), "state": q["state"]}))

    def test_state_inconnu_ou_absent(self):
        c, _ = self.aller()
        self.refuse("expiree", "cadre.connexion.entreprise.refus.expiree", c, c.get(RETOUR, {"code": "x", "state": "faux"}))
        self.refuse("expiree", "cadre.connexion.entreprise.refus.expiree", c, c.get(RETOUR, {"code": "x"}))

    def test_nonce_faux(self):
        self.faux.mode = "nonce_faux"
        self.refuse("fournisseur")

    def test_aud_faux(self):
        self.faux.mode = "aud_faux"
        self.refuse("fournisseur")

    def test_iss_faux(self):
        self.faux.mode = "iss_faux"
        self.refuse("fournisseur")

    def test_jeton_expire(self):
        self.faux.mode = "expire"
        self.refuse("fournisseur")

    def test_jeton_emis_dans_le_futur(self):
        self.faux.mode = "futur"
        self.refuse("fournisseur")

    def test_cle_inconnue(self):
        self.faux.mode = "cle_inconnue"
        self.refuse("fournisseur")

    def test_signature_fausse(self):
        self.faux.mode = "signature_fausse"
        self.refuse("fournisseur")

    def test_alg_none(self):
        self.faux.mode = "alg_none"
        self.faux.decouverte = {"id_token_signing_alg_values_supported": ["RS256", "none"]}
        with self.assertLogs("connexion_entreprise", "WARNING") as j:
            c, r = self.parcours()
        self.refuse("fournisseur", c=c, r=r)
        self.assertIn("algorithme_refuse", j.output[-1])  # refusé par la liste des algorithmes, avant toute clé

    def test_hs256_avec_le_secret_du_client(self):
        """Confusion d'algorithme : un jeton signé HS256 avec le secret du client (ou la clé publique) est refusé, même
        si le fournisseur annonçait HS256."""
        self.faux.decouverte = {"id_token_signing_alg_values_supported": ["RS256", "HS256"]}
        self.faux.mode = "hs256"
        with self.assertLogs("connexion_entreprise", "WARNING") as j:
            c, r = self.parcours()
        self.refuse("fournisseur", c=c, r=r)
        self.assertIn("algorithme_refuse", j.output[-1])

    def test_sans_jeton_d_identite(self):
        self.faux.mode = "sans_jeton"
        self.refuse("fournisseur")

    def test_destinataires_multiples_sans_azp(self):
        self.faux.claims = {"aud": ["probant-essai", "autre-client"]}
        self.refuse("fournisseur")

    def test_azp_autre_client(self):
        self.faux.claims = {"azp": "autre-client"}
        self.refuse("fournisseur")

    def test_refus_chez_le_fournisseur(self):
        self.faux.mode = "refus"
        self.refuse("annulee", "cadre.connexion.entreprise.refus.annulee")

    def test_fournisseur_injoignable(self):
        self.regler(emetteur="http://127.0.0.1:9/realms/essai")  # port fermé
        with self.assertLogs("connexion_entreprise", "WARNING"):
            c, r = self.aller()
        self.refuse("fournisseur", c=c, r=r)

    def test_reglage_change_pendant_la_connexion(self):
        c, r = self.aller()
        import urllib.parse

        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(r["Location"]).query))
        self.regler(client_id="autre-client")
        self.refuse("expiree", "cadre.connexion.entreprise.refus.expiree", c,
                    c.get(RETOUR, {"code": self.faux.emettre_code(q), "state": q["state"]}))

    # ------------------------------------------------------------ adresse e-mail
    def test_email_non_verifie(self):
        self.faux.claims = {"email_verified": False}
        h = self.refuse("adresse", "cadre.connexion.entreprise.refus.adresse")
        self.assertIsNone(h.utilisateur_id)

    def test_email_verified_absent_refuse_par_defaut(self):
        self.faux.claims = {"email_verified": None}
        self.refuse("adresse", "cadre.connexion.entreprise.refus.adresse")

    def test_email_verified_absent_accepte_si_regle(self):
        self.regler(email_non_declare=True)
        self.faux.claims = {"email_verified": None}
        c, _ = self.parcours()
        self.assertEqual(int(self.connecte(c)), self.contrib.pk)

    def test_email_verified_faux_jamais_accepte(self):
        self.regler(email_non_declare=True)
        self.faux.claims = {"email_verified": "false"}
        self.refuse("adresse", "cadre.connexion.entreprise.refus.adresse")

    def test_sans_email(self):
        self.faux.claims = {"email": None}
        self.refuse("adresse", "cadre.connexion.entreprise.refus.adresse")

    # ------------------------------------------------------------ compte : même message, sans dire s'il existe
    def test_compte_inconnu(self):
        self.faux.claims = {"email": "personne@exemple.example"}
        h = self.refuse("compte", MESSAGE_COMPTE)
        self.assertIsNone(h.utilisateur_id)
        self.assertFalse(Compte.objects.filter(email__iexact="personne@exemple.example").exists())  # rien n'est créé

    def test_compte_bloque_dans_tous_les_espaces(self):
        Compte.objects.filter(pk=self.contrib.pk).update(actif=False)
        h = self.refuse("compte", MESSAGE_COMPTE)
        self.assertEqual(h.utilisateur_id, self.contrib.pk)

    def test_compte_desactive_dans_l_espace(self):
        Utilisateur.objects.filter(pk=self.contrib.pk).update(is_active=False)
        self.refuse("compte", MESSAGE_COMPTE)

    def test_deux_comptes_de_meme_adresse(self):
        Compte.objects.create(pk=9999, username="contrib-bis", email="CONTRIB@exemple.example", password="!")
        self.refuse("compte", MESSAGE_COMPTE)

    def test_autre_sub_pour_le_meme_compte(self):
        """L'adresse a été donnée à une autre personne chez le fournisseur : son « sub » n'est pas celui du lien."""
        c, _ = self.parcours()
        c.post("/deconnexion/")
        self.faux.claims = {"sub": "autre-personne"}
        c, r = self.parcours()
        self.assertIsNone(self.connecte(c))
        h = HistoriqueConnexion.objects.order_by("-pk").first()
        self.assertEqual((h.resultat, h.motif), ("echec", "lien"))
        self.assertEqual(messages_de(c), [libelle(MESSAGE_COMPTE)])
        self.assertEqual(LienEntreprise.objects.get().sujet, "sujet-001")

    def test_meme_sub_pour_un_autre_compte(self):
        self.parcours()
        self.faux.claims = {"email": "admin2@exemple.example"}  # même « sub », autre adresse
        c, r = self.parcours()
        self.assertIsNone(self.connecte(c))
        self.assertEqual(HistoriqueConnexion.objects.order_by("-pk").first().motif, "lien")

    # ------------------------------------------------------------ limite des refus
    def test_trop_de_refus_depuis_une_adresse(self):
        """Refus obtenus sans compte chez le fournisseur (ici : retour « access_denied » forgé) : comptés pour l'adresse,
        qui est bloquée au-delà de ``REFUS_MAX``. Les refus après une authentification réussie (compte inconnu…) ne
        comptent que pour la personne : ``test_retour_refus_limites``."""
        from . import flux

        self.faux.mode = "refus"
        for _ in range(flux.REFUS_MAX):
            self.parcours()
        self.faux.mode = ""
        appels = len(self.faux.appels)
        c, r = self.aller()
        self.assertEqual(r["Location"], "/connexion/")
        self.assertEqual(messages_de(c), [libelle("cadre.connexion.entreprise.refus.trop")])
        self.assertEqual(len(self.faux.appels), appels)  # aucun appel au fournisseur
