"""Refus d'un outil réservé à certains rôles (``outils.refus``, condition ``visible``) et bornes des entiers
(``outils.lire_arguments``).

- « send_reminder » (comme la page Relances : administrateur ou validateur) : absent de la liste des outils d'un
  contributeur, et refusé à l'appel avec le motif « réservé à certains rôles » (et non celui de la page).
- Un identifiant entier vaut au moins 1 : 1 est accepté, 0 refusé (arguments invalides), le plus grand entier permis
  accepté, au-delà refusé.

Données inventées uniquement."""
from parametres.libelles import libelle

from . import outils as O
from .aides_tests import MODERNE, BaseMCP


class RefusParRoleTests(BaseMCP):
    def test_relance_refusee_au_contributeur_avec_le_motif_du_role(self):
        for role in ("contributeur", "autre"):
            outils = {t["name"] for t in self.requete(self.jetons[role], "tools/list").json()["result"]["tools"]}
            self.assertNotIn("send_reminder", outils, role)
            self.assertIn("get_value", outils, role)
            _, res, d = self.outil(role, "send_reminder", {}, MODERNE)
            self.assertTrue(res["isError"], role)
            self.assertEqual(d["error"], {"type": "permission_denied", "message": libelle("mcp.refus.role")}, role)
        _, res, d = self.outil("validateur", "send_reminder", {}, MODERNE)  # témoin : permis au validateur
        self.assertFalse(res["isError"], d)


class BornesEntiersTests(BaseMCP):
    def appel(self, cid):
        rep = self.requete(self.jetons["admin"], "tools/call", {"name": "list_organisations", "arguments": {"campaign_id": cid}})
        return rep.json()

    def test_minimum_un_et_maximum(self):
        outil = O.PAR_NOM["list_organisations"]
        self.assertEqual(O.lire_arguments(outil, {"campaign_id": 1}), {"campaign_id": 1})  # borne basse permise
        self.assertEqual(O.lire_arguments(outil, {"campaign_id": 2**31 - 1}), {"campaign_id": 2**31 - 1})
        for v in (0, -1, 2**31):
            with self.assertRaises(O.Invalide, msg=v):
                O.lire_arguments(outil, {"campaign_id": v})
        # par le point d'entrée : 1 passe la lecture des arguments (résultat de l'outil, pas d'erreur de paramètres)
        corps = self.appel(1)
        self.assertNotIn("error", corps, corps)
        self.assertIn("result", corps)
        self.assertEqual(self.appel(0)["error"]["code"], -32602)  # paramètres invalides

    def test_minimum_par_defaut_d_un_entier_sans_borne_ecrite(self):
        outil = O.Outil("essai", "Essai", "", {"n": {"type": "integer"}}, lambda ctx, a: a, "saisie")
        self.assertEqual(O.lire_arguments(outil, {"n": 1}), {"n": 1})
        with self.assertRaises(O.Invalide):
            O.lire_arguments(outil, {"n": 0})
