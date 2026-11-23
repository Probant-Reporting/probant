"""Deux réglages de Paramètres › Assistants, outil par outil (les 14) et rôle par
rôle : « un lecteur peut lire par un assistant » (défaut : non) et « les KPI sensibles sont donnés aux assistants »
(défaut : oui). Chaque changement est écrit au journal."""

from django.test import Client
from django.urls import reverse

from collecte.models import Alerte, Journal, Reponse
from referentiel.models import KPI

from . import outils as O
from .aides_tests import MODERNE, BaseMCP
from .models import ReglageMCP

ROLES = ("admin", "validateur", "contributeur", "autre", "lecteur", "auditeur")
LECTURE_VALEURS = ("list_values", "get_value", "get_cell_history", "list_evidence", "list_alerts")
SENSIBLE = "KPI sensible : non disponible par un assistant."


class ReglageLecteurTests(BaseMCP):
    def regler(self, **champs):
        ReglageMCP.objects.filter(pk=1).update(**champs)

    def args(self, nom):
        if nom in ("get_value", "get_cell_history", "list_evidence"):
            return self.case()
        return {} if nom == "list_campaigns" else {"campaign_id": self.c.pk}

    def outils_listes(self, role):
        return {t["name"] for t in self.requete(self.jetons[role], "tools/list").json()["result"]["tools"]}

    def test_par_defaut_le_lecteur_ne_lit_pas_les_valeurs_et_le_motif_parle_d_un_outil(self):
        self.assertFalse(ReglageMCP.courant().lecteur_lit)
        self.assertFalse(self.outils_listes("lecteur") & set(LECTURE_VALEURS))
        for nom in LECTURE_VALEURS:
            with self.subTest(outil=nom):
                _, res, d = self.outil("lecteur", nom, self.args(nom))
                self.assertTrue(res["isError"])
                self.assertEqual(d["error"]["type"], "permission_denied")
                self.assertNotIn("page", d["error"]["message"])  # B9 : un motif d'outil, pas « cette page »
                self.assertIn("lecteur", d["error"]["message"])

    def test_reglage_allume_le_lecteur_lit_dans_son_perimetre_jamais_d_ecriture(self):
        Reponse.objects.filter(periode=self.c.periode, kpi=self.eff, organisation=self.e1).update(valeur=12, statut="valide")
        self.lecteur.perimetre_lecture.set([self.e1])  # périmètre de consultation : E1 seulement
        self.regler(lecteur_lit=True)
        self.assertTrue(set(LECTURE_VALEURS) <= self.outils_listes("lecteur"))
        self.assertFalse(self.outils_listes("lecteur") & {o.nom for o in O.OUTILS if o.ecriture})
        _, res, d = self.outil("lecteur", "list_values", {"campaign_id": self.c.pk}, MODERNE)
        self.assertFalse(res["isError"], d)
        self.assertEqual({v["organisation"]["id"] for v in d["values"]}, {self.e1.pk})
        _, res, d = self.outil("lecteur", "get_value", self.case())
        self.assertFalse(res["isError"], d)
        self.assertEqual(d["value"], "12")
        _, res, d = self.outil("lecteur", "get_value", self.case(org=self.e2))  # hors de son périmètre : refusé
        self.assertTrue(res["isError"])
        for nom in ("get_cell_history", "list_evidence", "list_alerts"):
            with self.subTest(outil=nom):
                _, res, d = self.outil("lecteur", nom, self.args(nom))
                self.assertFalse(res["isError"], d)
        for nom, args in (("save_value", {**self.case(), "value": "1", "version": ""}), ("validate_value", self.case())):
            _, res, d = self.outil("lecteur", nom, args)
            self.assertEqual(d["error"]["type"], "permission_denied")
        self.assertEqual(Reponse.objects.get(periode=self.c.periode, organisation=self.e1, kpi=self.eff).valeur, 12)

    def test_le_reglage_ne_change_rien_aux_autres_roles(self):
        avant = {r: self.outils_listes(r) for r in ROLES}
        self.regler(lecteur_lit=True)
        for r in ROLES:
            if r != "lecteur":
                self.assertEqual(self.outils_listes(r), avant[r], r)


class ReglageSensiblesTests(BaseMCP):
    def setUp(self):
        super().setUp()
        KPI.objects.filter(pk=self.eff.pk).update(confidentialite=KPI.Confidentialite.CONFIDENTIEL)
        Reponse.objects.filter(periode=self.c.periode, kpi=self.eff, organisation=self.e1).update(
            valeur=12, commentaire="Commentaire secret", statut="brouillon")
        self.rep = Reponse.objects.get(periode=self.c.periode, kpi=self.eff, organisation=self.e1)
        self.alerte = Alerte.objects.create(campagne=self.c, kpi=self.eff, organisation=self.e1,
                                            controle=Alerte.Controle.ECART_N1, message="écart")
        ReglageMCP.objects.filter(pk=1).update(kpi_sensibles=False, lecteur_lit=True)

    def appels(self):
        """Les 14 outils, avec des arguments qui visent le KPI sensible quand l'outil en prend un."""
        c, case = self.c.pk, self.case()
        return {
            "list_campaigns": {}, "list_organisations": {"campaign_id": c}, "list_kpis": {"campaign_id": c, "search": "EFF"},
            "get_completion": {"campaign_id": c}, "list_values": {"campaign_id": c, "organisation_id": self.e1.pk},
            "get_value": case, "get_cell_history": case, "list_evidence": case,
            "list_alerts": {"campaign_id": c, "status": "all"},
            "save_value": {**case, "value": "13", "version": ""}, "mark_not_applicable": {**case, "comment": "x", "version": ""},
            "validate_value": case, "justify_alert": {"alert_id": self.alerte.pk, "text": "Embauches"},
            "send_reminder": {"campaign_id": c},
        }

    def test_aucun_outil_ne_renvoie_le_kpi_sensible_pour_aucun_role(self):
        self.assertEqual(sorted(self.appels()), sorted(O.PAR_NOM))
        for role in ROLES:
            for nom, args in self.appels().items():
                with self.subTest(role=role, outil=nom):
                    _, res, d = self.outil(role, nom, args, MODERNE)
                    texte = res["content"][0]["text"]
                    self.assertNotIn('"EFF"', texte)  # ni la valeur, ni le commentaire, ni une alerte, ni le code
                    self.assertNotIn("Commentaire secret", texte)
                    if nom in ("get_value", "get_cell_history", "list_evidence", "save_value", "mark_not_applicable",
                               "validate_value", "justify_alert") and not O.refus(self.comptes[role], O.PAR_NOM[nom],
                                                                                    ReglageMCP.courant()):
                        if nom == "justify_alert" and role in ("autre",):
                            continue  # alerte hors de son périmètre : refus de la fiche d'abord
                        self.assertEqual(d["error"]["message"], SENSIBLE, (role, nom, d))
        self.rep.refresh_from_db()
        self.assertEqual((self.rep.valeur, self.rep.statut), (12, "brouillon"))
        self.alerte.refresh_from_db()
        self.assertEqual(self.alerte.justification, "")  # jamais justifiée par un outil

    def test_filtre_par_code_du_kpi_sensible_refuse_clairement(self):
        for nom in ("list_values", "list_alerts"):
            _, res, d = self.outil("admin", nom, {"campaign_id": self.c.pk, "kpi_code": "EFF"})
            self.assertEqual(d["error"]["message"], SENSIBLE, nom)

    def test_les_autres_kpi_restent_donnes(self):
        _, res, d = self.outil("admin", "list_kpis", {"campaign_id": self.c.pk})
        self.assertIn("TX", {k["code"] for k in d["kpis"]})
        _, res, d = self.outil("admin", "get_value", self.case(kpi=self.taux))
        self.assertFalse(res["isError"], d)

    def test_par_defaut_memes_droits_que_les_pages(self):
        ReglageMCP.objects.filter(pk=1).update(kpi_sensibles=True)
        _, res, d = self.outil("admin", "get_value", self.case())
        self.assertFalse(res["isError"], d)
        self.assertEqual(d["value"], "12")
        _, res, d = self.outil("admin", "list_alerts", {"campaign_id": self.c.pk, "status": "all"})
        self.assertIn(self.alerte.pk, [a["id"] for a in d["alerts"]])


class PageReglagesTests(BaseMCP):
    def test_les_deux_reglages_sont_sur_la_page_et_au_journal(self):
        client = Client()
        client.force_login(self.admin)
        url = reverse("serveur_mcp:reglages")
        page = client.get(url).content.decode()
        self.assertIn('name="lecteur_lit"', page)
        self.assertIn('name="kpi_sensibles"', page)
        r = ReglageMCP.courant()
        rep = client.post(url, {"actif": "on", "ecriture": "on", "lecteur_lit": "on", "appels_minute": r.appels_minute,
                                "duree_max_jours": r.duree_max_jours})
        self.assertEqual(rep.status_code, 302)
        r.refresh_from_db()
        self.assertTrue(r.lecteur_lit)
        self.assertFalse(r.kpi_sensibles)
        champs = set(Journal.objects.filter(action="reglage_mcp").values_list("champ", flat=True))
        self.assertEqual(champs, {"mcp_lecteur_lit", "mcp_kpi_sensibles"})
        journal = client.get(reverse("collecte:historique") + "?vue=admin&famille=acces_mcp").content.decode()
        self.assertIn("Lecteur qui lit par un assistant", journal)
