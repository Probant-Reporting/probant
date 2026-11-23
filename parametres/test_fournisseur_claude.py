"""Fournisseur Claude de la prise IA : requête construite (en-têtes, corps), lecture de la réponse, erreurs en clair,
repli sans l'en-tête bêta ; et aucun réseau pendant les tests. Aucun appel réel : ``_ouvrir`` est remplacé."""
import io
import json
import socket
import urllib.error
from unittest import mock

from django.test import SimpleTestCase

from parametres import ia_fournisseurs as F

SCHEMA = {"type": "object", "properties": {"explanation": {"type": "string"}}, "required": ["explanation"],
          "additionalProperties": False}


def requete(modele="claude-fable-5-2"):
    return F.Requete(cle="sk-ant-secret-0123456789abcdef", modele=modele, systeme="Consignes", donnees="<data>\n{}\n</data>",
                     schema=SCHEMA, max_jetons=2000, effort="medium", delai=30, usage="expliquer_alerte")


class Reponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def succes(texte='{"explanation": "Une explication."}', arret="end_turn", modele="claude-fable-5-2"):
    corps = {"model": modele, "stop_reason": arret, "usage": {"input_tokens": 12, "output_tokens": 34},
             "content": [{"type": "thinking", "thinking": ""}, {"type": "text", "text": texte}]}
    return Reponse(json.dumps(corps).encode())


def erreur_http(code, message="x"):
    return urllib.error.HTTPError(F.FournisseurClaude.url, code, "erreur", {"request-id": "req_1"},
                                  io.BytesIO(json.dumps({"type": "error", "error": {"message": message}}).encode()))


class SansBruit(SimpleTestCase):
    def setUp(self):
        super().setUp()
        F.journal.disabled = True  # avertissements attendus : pas dans la sortie des tests
        self.addCleanup(setattr, F.journal, "disabled", False)


class RequeteTests(SansBruit):
    def test_en_tetes_et_corps(self):
        envoyees = []

        def ouvrir(req, delai):
            envoyees.append((req, delai))
            return succes()
        with mock.patch.object(F, "_ouvrir", ouvrir):
            rep = F.FournisseurClaude().demander(requete())
        req, delai = envoyees[0]
        self.assertEqual((req.full_url, req.get_method(), delai), ("https://api.anthropic.com/v1/messages", "POST", 30))
        entetes = {k.lower(): v for k, v in req.header_items()}
        self.assertEqual(entetes["x-api-key"], "sk-ant-secret-0123456789abcdef")
        self.assertEqual(entetes["anthropic-version"], "2026-10-21")
        self.assertEqual(entetes["anthropic-beta"], "server-side-fallback-2026-07-01")
        corps = json.loads(req.data)
        self.assertEqual(corps["model"], "claude-fable-5-2")
        self.assertEqual(corps["system"], "Consignes")
        self.assertEqual(corps["messages"], [{"role": "user", "content": "<data>\n{}\n</data>"}])
        self.assertEqual(corps["output_config"], {"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}})
        self.assertEqual(corps["fallbacks"], "default")
        for interdit in ("temperature", "top_p", "top_k", "thinking"):  # refusés par la version 2026-10-21 / inutiles
            self.assertNotIn(interdit, corps)
        self.assertEqual((rep.donnees, rep.jetons_entree, rep.jetons_sortie), ({"explanation": "Une explication."}, 12, 34))

    def test_haiku_sans_repli_cote_serveur(self):
        envoyees = []
        with mock.patch.object(F, "_ouvrir", lambda req, delai: envoyees.append(req) or succes()):
            F.FournisseurClaude().demander(requete("claude-haiku-5-5"))
        self.assertNotIn("fallbacks", json.loads(envoyees[0].data))
        self.assertNotIn("anthropic-beta", {k.lower() for k, _ in envoyees[0].header_items()})

    def test_compte_sans_beta_une_seule_nouvelle_tentative_sans_lui(self):
        envoyees = []

        def ouvrir(req, delai):
            envoyees.append(req)
            if len(envoyees) == 1:
                raise erreur_http(400, "Unexpected value(s) `server-side-fallback-2026-07-01` for the `anthropic-beta` header.")
            return succes()
        with mock.patch.object(F, "_ouvrir", ouvrir):
            F.FournisseurClaude().demander(requete())
        self.assertEqual(len(envoyees), 2)
        self.assertNotIn("fallbacks", json.loads(envoyees[1].data))

    def test_modeles_proposes_le_plus_capable_par_defaut(self):
        self.assertEqual(F.FournisseurClaude.modele_par_defaut, "claude-fable-5-2")
        self.assertEqual([m for m, _, _ in F.FournisseurClaude.modeles],
                         ["claude-fable-5-2", "claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"])


class ErreursTests(SansBruit):
    def code(self, exc=None, reponse=None):
        def ouvrir(req, delai):
            if exc is not None:
                raise exc
            return reponse
        with mock.patch.object(F, "_ouvrir", ouvrir), self.assertRaises(F.ErreurIA) as e:
            F.FournisseurClaude().demander(requete())
        return e.exception.code

    def test_codes_http_en_clair(self):
        for statut, attendu in ((401, "cle_refusee"), (403, "cle_refusee"), (402, "credit"), (404, "modele"), (413, "trop_long"),
                                (429, "quota"), (500, "surcharge"), (529, "surcharge"), (422, "requete")):
            with self.subTest(statut=statut):
                self.assertEqual(self.code(erreur_http(statut)), attendu)
        self.assertEqual(self.code(erreur_http(400, "Your credit balance is too low")), "credit")

    def test_reseau_et_delai(self):
        self.assertEqual(self.code(urllib.error.URLError(ConnectionRefusedError())), "reseau")
        self.assertEqual(self.code(urllib.error.URLError(socket.timeout())), "delai")
        self.assertEqual(self.code(TimeoutError()), "delai")

    def test_refus_reponse_coupee_ou_illisible(self):
        self.assertEqual(self.code(reponse=succes(arret="refusal")), "refus")
        self.assertEqual(self.code(reponse=succes(arret="max_tokens")), "trop_long")
        self.assertEqual(self.code(reponse=succes(texte="pas du JSON")), "reponse_invalide")
        self.assertEqual(self.code(reponse=succes(texte="[1, 2]")), "reponse_invalide")
        self.assertEqual(self.code(reponse=Reponse(b"<html>")), "reponse_invalide")

    def test_le_journal_du_serveur_ne_contient_ni_cle_ni_contenu(self):
        F.journal.disabled = False
        with self.assertLogs("reporting.ia", "WARNING") as journal:
            self.code(erreur_http(401, "invalid x-api-key"))
        texte = "\n".join(journal.output)
        self.assertNotIn("sk-ant-secret", texte)
        self.assertNotIn("Consignes", texte)
        self.assertIn("status=401", texte)


class SansReseauTests(SimpleTestCase):
    def test_aucune_connexion_pendant_les_tests(self):
        with self.assertRaisesMessage(RuntimeError, "forbidden while the tests run"):
            F._ouvrir(None, 1)
        with mock.patch("urllib.request.urlopen") as ouvrir, self.assertRaises(RuntimeError):
            F.FournisseurClaude().demander(requete())
        ouvrir.assert_not_called()

    def test_fournisseur_factice_seulement_si_permis(self):
        with self.settings(IA_FOURNISSEUR_FACTICE=False):
            self.assertEqual(list(F.disponibles()), ["claude"])
        with self.settings(IA_FOURNISSEUR_FACTICE=True):
            self.assertEqual(list(F.disponibles()), ["claude", "factice"])
