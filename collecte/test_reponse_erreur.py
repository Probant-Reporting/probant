"""Un seul format d'erreur pour les réponses JSON (architecture) : ``{"ok": false, "erreur": m, "message": m}``
(``reponse_erreur``), lu par ``motifErreur`` (``d.erreur || d.message``) et par les écrans qui lisent ``message``."""
import ast
import json
from pathlib import Path

from django.test import SimpleTestCase
from django.urls import reverse

from parametres.libelles import libelle

from .reponses_script import reponse_erreur
from .aides_tests.saisie import Base

RACINE = Path(__file__).resolve().parent.parent
FETCH = {"HTTP_X_REQUESTED_WITH": "fetch"}


class FormatTests(SimpleTestCase):
    def test_les_deux_cles_et_le_statut(self):
        r = reponse_erreur("Refusé : « motif »", status=409, conflit=True)
        self.assertEqual(r.status_code, 409)
        self.assertEqual(json.loads(r.content), {"ok": False, "erreur": "Refusé : « motif »", "message": "Refusé : « motif »",
                                                  "conflit": True})
        self.assertIn("« motif »".encode(), r.content)  # écrit tel quel (ensure_ascii désactivé)
        self.assertEqual(reponse_erreur("x").status_code, 400)

    def test_aucune_reponse_json_d_erreur_ecrite_a_la_main(self):
        """Hors de ``reponse_erreur``, aucun ``JsonResponse({...})`` ne porte la clé « erreur » ni « ok »: False (sauf la
        question « confirmer » de l'éditeur de référentiel : rien n'est refusé, la page demande une confirmation)."""
        from parametres.aides_tests.structure import fichiers_python

        trouves = []
        for p in fichiers_python():
            for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
                if not (isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", "")) == "JsonResponse"
                        and n.args and isinstance(n.args[0], ast.Dict)):
                    continue
                cles = {k.value: v for k, v in zip(n.args[0].keys, n.args[0].values) if isinstance(k, ast.Constant)}
                faux = isinstance(cles.get("ok"), ast.Constant) and cles["ok"].value is False
                if ("erreur" in cles or faux) and "confirmer" not in cles and p.relative_to(RACINE).as_posix() != "espaces/requetes.py":
                    trouves.append(f"{p.relative_to(RACINE)}:{n.lineno}")
        self.assertEqual(trouves, [], "utiliser reponse_erreur")


class ReponsesReellesTests(Base):
    def verifier(self, r, statut, message=None):
        self.assertEqual(r.status_code, statut)
        d = r.json()
        self.assertIs(d["ok"], False)
        self.assertTrue(d["erreur"])
        self.assertEqual(d["erreur"], d["message"])
        if message is not None:
            self.assertEqual(d["erreur"], message)
        return d

    def test_refus_403_envoye_au_script(self):
        self.client.force_login(self.contrib)
        r = self.client.post(reverse("collecte:attribuer"), "{}", content_type="application/json", **FETCH)
        self.verifier(r, 403, libelle("saisie.erreur.reserve_admin"))

    def test_session_expiree_401(self):
        r = self.client.post(reverse("collecte:attribuer"), "{}", content_type="application/json", **FETCH)
        self.assertTrue(self.verifier(r, 401, libelle("messages.reponses.session_expiree"))["session_expiree"])

    def test_attribution_corps_invalide_400(self):
        self.client.force_login(self.admin)
        r = self.client.post(reverse("collecte:attribuer"), "[]", content_type="application/json", **FETCH)
        self.verifier(r, 400, libelle("saisie.erreur.action_inconnue"))

    def test_liste_de_kpi_sans_nom_400(self):
        self.client.force_login(self.admin)
        r = self.client.post(reverse("collecte:echanges_listes"), {"nom": "", "kpis": ["EFF"]}, **FETCH)
        self.verifier(r, 400, libelle("suivi.echanges.msg.liste_nom_requis"))

    def test_visualisation_garde_la_liste_par_visuel(self):
        self.client.force_login(self.admin)
        r = self.client.post(reverse("collecte:visu_vue_creer"), "[]", content_type="application/json", **FETCH)
        d = self.verifier(r, 400)
        self.assertEqual(d["erreurs"][0]["message"], d["erreur"])
