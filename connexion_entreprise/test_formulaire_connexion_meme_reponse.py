"""Page de connexion, connexion d'entreprise allumée : tout échec par mot de passe reçoit la même réponse (texte, code
de l'erreur, statut), qu'il s'agisse d'un mot de passe juste pour un compte qui doit passer par l'entreprise, d'un mot
de passe faux ou d'un compte inconnu. Avant, un mot de passe juste avait son propre message (« utilisez le compte
d'entreprise ») : la page confirmait que le compte existait et que le mot de passe était bon. La page dit, de façon
générale, que le compte peut se connecter par le bouton du compte d'entreprise. Éteinte : rien ne change."""
import re
import time

from django.test import Client

from espaces.aides_tests import MDP
from parametres.libelles import libelle
from referentiel.models import HistoriqueConnexion

from .aides_tests import BaseEntreprise


def essai(identifiant, mot_de_passe):
    c = Client()
    debut = time.perf_counter()
    r = c.post("/connexion/", {"username": identifiant, "password": mot_de_passe})
    duree = time.perf_counter() - debut
    erreur = re.search(r'id="erreur-connexion"[^>]*>(.*?)</(?:p|div)>', r.content.decode(), re.S)
    codes = [e.code for e in r.context["form"].non_field_errors().as_data()] if r.status_code == 200 else []
    return {"statut": r.status_code, "erreur": erreur.group(1).strip() if erreur else "", "codes": codes,
            "connecte": "_auth_user_id" in c.session}, duree


class MemeReponseTests(BaseEntreprise):
    def test_allumee_tous_les_echecs_identiques(self):
        self.regler()
        juste, d1 = essai(self.contrib.email, MDP)  # mot de passe juste, compte qui passe par l'entreprise
        faux, d2 = essai(self.contrib.email, "faux-mot-de-passe")
        inconnu, d3 = essai("personne@exemple.example", MDP)
        self.assertFalse(juste["connecte"])
        self.assertEqual(juste, faux)
        self.assertEqual(juste, inconnu)
        self.assertEqual(juste["statut"], 200)
        self.assertEqual(juste["codes"], ["invalid_login"])
        self.assertIn(libelle("cadre.connexion.entreprise.incorrect").split(". ")[0], juste["erreur"])
        self.assertLess(max(d1, d2, d3), 10 * min(d1, d2, d3) + 0.5)  # durées comparables (une empreinte chacun)
        # l'historique, lu par l'administrateur et l'auditeur, garde la cause (bon mot de passe refusé)
        motifs = list(HistoriqueConnexion.objects.order_by("pk").values_list("motif", flat=True))
        self.assertEqual(motifs[0], "mot_de_passe")

    def test_eteinte_message_habituel(self):
        faux, _ = essai(self.contrib.email, "faux-mot-de-passe")
        self.assertIn(libelle("cadre.connexion.incorrect").split(".")[0].replace("'", "&#x27;"), faux["erreur"])
        juste, _ = essai(self.contrib.email, MDP)
        self.assertTrue(juste["connecte"])

    def test_secours_entre_toujours(self):
        self.regler()
        r, _ = essai(self.gestionnaire.email, MDP)
        self.assertTrue(r["connecte"])
