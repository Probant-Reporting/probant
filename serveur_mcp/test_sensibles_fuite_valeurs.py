"""Réglage « KPI sensibles donnés aux assistants » éteint : aucune valeur d'un KPI sensible
ne sort par aucun des 14 outils, même citée par un texte que l'outil compose sur une AUTRE case (constats 3 et 4) : motif d'une règle bloquante (get_value « blocks_validation », refus de validate_value), alerte, détail,
historique ; ni un KPI calculé dont une source, de proche en proche, est sensible ([X], [X@N-1], formule d'une formule).

Base : valeurs sensibles reconnaissables (nombres uniques), chaque outil appelé sur chaque case non sensible, par
l'administrateur ; aucun de ces nombres dans aucune réponse.

Données inventées uniquement."""
import json
import re

from collecte import calcul as C
from collecte import saisie as S
from collecte.models import RegleCoherence, Reponse
from referentiel.models import KPI, ElementReferentiel, Niveau

from . import outils as O
from .aides_tests import MODERNE, BaseMCP
from .models import ReglageMCP

SECRETS = ("271828", "161803", "57721", "329549")  # SEC : E1 2026, E1 2025, E2 2026, total du pays 2026
CACHES = ("SEC", "RAT", "CPY", "PRV", "DEUX")  # le KPI sensible et les KPI calculés qui en dérivent


def sans_separateurs(texte):
    return re.sub(r"[\s  .,'’]", "", texte)


class FuiteValeursSensiblesTests(BaseMCP):
    def setUp(self):
        super().setUp()
        ref = self.c.referentiel
        self.sec = KPI.objects.create(code="SEC", libelle="Salaire du dirigeant", type_saisie_id="Saisi",
                                      granularite_id=Niveau.ENTITY, methode_agregation="Somme",
                                      confidentialite=KPI.Confidentialite.CONFIDENTIEL)
        formules = {"RAT": "[EFF] / [SEC]", "CPY": "[SEC] * 1", "PRV": "[SEC@N-1] + 0", "DEUX": "[CPY] + [EFF]"}
        for code, f in formules.items():
            KPI.objects.create(code=code, libelle=f"Calcul {code}", type_saisie_id="Calculé", formule=f,
                               granularite_id=Niveau.ENTITY, methode_agregation="Somme")
        for i, code in enumerate(("SEC",) + tuple(formules), start=10):
            ElementReferentiel.objects.update_or_create(referentiel=ref, kpi_id=code, defaults={"ordre": i})
        Reponse.objects.create(periode=self.c0.periode, kpi=self.sec, organisation=self.e1, valeur=161803, statut="valide",
                               origine="import")
        S.enregistrer(self.admin, self.c, self.sec, self.e1, "271828", False, "")
        S.enregistrer(self.admin, self.c, self.sec, self.e2, "57721", False, "")
        # règle bloquante sur un KPI non sensible qui cite le KPI sensible : EFF (110) ≥ SEC (271 828) n'est pas respectée
        RegleCoherence.objects.create(nom="Effectif et salaire", gauche="[EFF]", operateur=">=", droite="[SEC]",
                                      niveau_id=Niveau.ENTITY, bloquante=True, description="Voir la paie.")
        C.recalculer(self.c)
        ReglageMCP.objects.filter(pk=1).update(kpi_sensibles=False, lecteur_lit=True)

    def verifier(self, nom, args, role="admin"):
        _, res, d = self.outil(role, nom, args, MODERNE)
        texte = res["content"][0]["text"]
        plat = sans_separateurs(texte)
        for s in SECRETS:
            self.assertNotIn(s, plat, (nom, args, texte[:600]))
        for code in CACHES:
            self.assertNotIn(f'"{code}"', texte, (nom, args, texte[:600]))
        return res, d

    def cases(self):
        orgs = (self.g, self.p, self.e1, self.e2)
        return [{"campaign_id": c.pk, "kpi_code": k, "organisation_id": o.pk}
                for c in (self.c, self.c0) for k in ("EFF", "TX", "DBL") for o in orgs]

    def test_aucun_nombre_sensible_dans_aucune_reponse(self):
        lectures = [("list_campaigns", {})]
        for c in (self.c, self.c0):
            lectures += [("list_organisations", {"campaign_id": c.pk}), ("list_kpis", {"campaign_id": c.pk}),
                         ("list_alerts", {"campaign_id": c.pk, "status": "all"}), ("send_reminder", {"campaign_id": c.pk})]
            lectures += [("get_completion", {"campaign_id": c.pk, "group_by": g}) for g in ("organisation", "theme", "person")]
            lectures += [("list_values", {"campaign_id": c.pk, "organisation_id": o.pk, "include_calculated": True})
                         for o in (self.g, self.p, self.e1, self.e2)]
            lectures += [("list_values", {"campaign_id": c.pk})]
        for case in self.cases():
            lectures += [("get_value", case), ("get_cell_history", case), ("list_evidence", case)]
        for nom, args in lectures:
            with self.subTest(outil=nom, args=args):
                self.verifier(nom, args)
        # écritures sur les cases non sensibles : refus et réponses sans le nombre sensible
        res, d = self.verifier("validate_value", self.case())  # EFF de E1 : bloquée par la règle
        self.assertTrue(res["isError"])
        self.assertIn("sensible", json.dumps(d, ensure_ascii=False).lower())
        _, _, v = self.outil("admin", "get_value", self.case(), MODERNE)
        self.assertTrue(v["blocks_validation"])  # la validation reste bloquée, avec un motif générique
        self.verifier("save_value", {**self.case(), "value": "120", "version": v["version"]})
        _, _, v = self.outil("admin", "get_value", self.case(), MODERNE)
        self.verifier("mark_not_applicable", {**self.case(), "comment": "Essai", "version": v["version"]})
        for a in self.outil("admin", "list_alerts", {"campaign_id": self.c.pk, "status": "all"}, MODERNE)[2]["alerts"]:
            self.verifier("justify_alert", {"alert_id": a["id"], "text": "Explication"})

    def test_kpi_calcule_depuis_un_kpi_sensible_cache(self):
        self.assertEqual(set(CACHES) - self.ctx_sensibles(), set())
        for code in ("RAT", "CPY", "PRV", "DEUX"):
            _, res, d = self.outil("admin", "get_value", self.case(kpi=KPI.objects.get(pk=code)), MODERNE)
            self.assertEqual(d["error"]["type"], "permission_denied", code)
        _, _, d = self.outil("admin", "list_kpis", {"campaign_id": self.c.pk}, MODERNE)
        self.assertEqual({k["code"] for k in d["kpis"]} & set(CACHES), set())
        self.assertNotIn("DBL", self.ctx_sensibles())  # calculé depuis un KPI non sensible : donné
        _, res, d = self.outil("admin", "get_value", self.case(kpi=self.calc), MODERNE)
        self.assertFalse(res["isError"], d)

    def ctx_sensibles(self):
        return set(O.Contexte(self.admin, None, ReglageMCP.courant()).sensibles())

    def test_reglage_allume_rien_ne_change(self):
        ReglageMCP.objects.filter(pk=1).update(kpi_sensibles=True)
        self.assertEqual(self.ctx_sensibles(), set())
        _, _, v = self.outil("admin", "get_value", self.case(), MODERNE)
        self.assertIn("271", " ".join(v["blocks_validation"]))  # mêmes droits que les pages : le motif complet
