"""Chaque outil du serveur MCP, appelé par chaque rôle, autorise exactement ce que la page correspondante autorise (même
refus, même motif), sur une case du périmètre, une case hors périmètre, un KPI calculé et une campagne clôturée ;
lecteur et auditeur n'écrivent jamais rien (docs/mcp.md, règle absolue : les mêmes fonctions que les pages)."""
from decimal import Decimal

from django.db import transaction
from django.test import Client
from django.urls import reverse

from collecte import saisie as S
from collecte.models import Alerte, Reponse

from . import outils as O
from .aides_tests import MODERNE, BaseMCP

ROLES = ("admin", "validateur", "contributeur", "autre", "lecteur", "auditeur")


class Annulee:
    """Bloc dont toutes les écritures sont annulées à la sortie (pour essayer la page puis l'outil sur le même état)."""

    def __enter__(self):
        self.atomic = transaction.atomic()
        self.atomic.__enter__()

    def __exit__(self, *exc):
        transaction.set_rollback(True)
        return self.atomic.__exit__(*exc)


class OutilsCommePagesTests(BaseMCP):
    def page(self, role):
        c = Client()
        c.force_login(self.comptes[role])
        return c

    def cases(self):
        return {"perimetre": self.case(), "autre_org": self.case(org=self.e2), "calcule": self.case(kpi=self.calc),
                "cloturee": self.case(campagne=self.c0), "pays": self.case(org=self.p)}

    def url_cellule(self, a):
        return reverse("collecte:cellule", args=[a["campaign_id"], a["kpi_code"], a["organisation_id"]])

    def refus_mcp(self, resultat):
        import json

        return bool(resultat["isError"]) and json.loads(resultat["content"][0]["text"])["error"]["type"] == "permission_denied"

    def test_catalogue_complet(self):
        self.assertEqual(sorted(O.PAR_NOM), sorted([
            "list_campaigns", "list_organisations", "list_kpis", "get_completion", "list_values", "get_value",
            "get_cell_history", "list_evidence", "list_alerts", "save_value", "mark_not_applicable", "validate_value",
            "justify_alert", "send_reminder"]))
        for o in O.OUTILS:  # aucun outil d'administration ; chaque page nommée existe dans « collecte »
            reverse("collecte:" + o.page, args=[1, "x", 1] if o.page == "cellule" else [1] if o.page == "alerte" else None)

    def test_lecture_par_role_comme_les_pages(self):
        tdb = reverse("collecte:tableau_de_bord") + f"?campagne={self.c.pk}"
        pages = {"list_campaigns": reverse("collecte:choix_reponse"), "list_organisations": tdb, "list_kpis": tdb, "get_completion": tdb,
                 "list_values": reverse("collecte:saisie") + f"?campagne={self.c.pk}",
                 "list_alerts": reverse("collecte:coherence") + f"?campagne={self.c.pk}"}
        for role in ROLES:
            client = self.page(role)
            for nom, url in pages.items():
                with self.subTest(role=role, outil=nom):
                    statut = client.get(url).status_code
                    self.assertIn(statut, (200, 403))
                    _, res, _ = self.outil(role, nom, {} if nom == "list_campaigns" else {"campaign_id": self.c.pk}, MODERNE)
                    self.assertEqual(self.refus_mcp(res), statut == 403, res)
            for cle, a in self.cases().items():
                statut = client.get(self.url_cellule(a)).status_code
                self.assertIn(statut, (200, 403))
                for nom in ("get_value", "get_cell_history", "list_evidence"):
                    with self.subTest(role=role, outil=nom, case=cle):
                        _, res, d = self.outil(role, nom, a)
                        self.assertEqual(self.refus_mcp(res), statut == 403, res)
                        if statut == 403:  # un motif, jamais une réponse vide
                            self.assertTrue(d["error"]["message"])

    def test_motif_du_refus_identique_a_droits(self):
        a = self.case(org=self.e2)
        _, res, d = self.outil("contributeur", "get_value", a)
        self.assertTrue(res["isError"])
        self.assertEqual(d["error"]["message"], S.droits(self.contrib, self.c, self.eff, self.e2).motif)
        _, res, d = self.outil("lecteur", "get_value", self.case())
        # motif d'un outil, pas d'une page (B9) : réglage « un lecteur peut lire par un assistant » éteint
        self.assertEqual(d["error"]["message"], "Dans cet espace, un lecteur ne peut pas lire les valeurs par un assistant. "
                                                "Demandez à votre administrateur.")

    def essai_page_ecriture(self, role, a, action, valeur="777", na=False):
        """(statut HTTP, réponse après) d'un envoi du panneau de saisie, annulé ensuite."""
        r = Reponse.objects.filter(periode__campagnes__pk=a["campaign_id"], kpi_id=a["kpi_code"], organisation_id=a["organisation_id"]).first()
        with Annulee():
            rep = self.page(role).post(self.url_cellule(a), {"action": action, "valeur": valeur, "commentaire": "Raison",
                                                             "non_applicable": "on" if na else "", "version": S.version(r)})
            apres = self.etat(r)
        return rep.status_code, apres != self.etat(r)

    def etat(self, r):
        return Reponse.objects.filter(pk=r.pk).values_list("valeur", "non_applicable", "statut").first() if r else None

    def test_ecriture_par_role_comme_le_panneau(self):
        for role in ROLES:
            for cle, a in self.cases().items():
                r = Reponse.objects.filter(periode__campagnes__pk=a["campaign_id"], kpi_id=a["kpi_code"], organisation_id=a["organisation_id"]).first()
                version, avant = S.version(r), self.etat(r)
                with self.subTest(role=role, case=cle, outil="save_value"):
                    statut, page_ok = self.essai_page_ecriture(role, a, "enregistrer")
                    with Annulee():
                        _, res, d = self.outil(role, "save_value", {**a, "value": "777", "comment": "Raison", "version": version})
                        mcp_ok = not res["isError"] and self.etat(r) != avant
                    self.assertEqual(mcp_ok, page_ok, (statut, d))
                    if not page_ok and not self.comptes[role].lecture_seule and statut == 403:
                        self.assertEqual(d["error"]["type"], "permission_denied")
                with self.subTest(role=role, case=cle, outil="mark_not_applicable"):
                    statut, page_ok = self.essai_page_ecriture(role, a, "enregistrer", "", na=True)
                    with Annulee():
                        _, res, d = self.outil(role, "mark_not_applicable", {**a, "comment": "Raison", "version": version})
                        mcp_ok = not res["isError"] and self.etat(r) != avant
                    self.assertEqual(mcp_ok, page_ok, (statut, d))
                with self.subTest(role=role, case=cle, outil="validate_value"):
                    valeur = S.valeur_pour_saisie(r, self.eff) if r else ""
                    statut, page_ok = self.essai_page_ecriture(role, a, "valider", valeur)
                    with Annulee():
                        _, res, d = self.outil(role, "validate_value", a)
                        mcp_ok = not res["isError"] and self.etat(r) != avant
                    self.assertEqual(mcp_ok, page_ok, (statut, d))

    def test_campagne_cloturee_ecriture_refusee_avec_le_motif_de_la_page(self):
        a = self.case(campagne=self.c0)
        r = S.reponse_de(self.c0, self.eff, self.e1)
        for role in ("admin", "contributeur"):
            _, res, d = self.outil(role, "save_value", {**a, "value": "5", "version": S.version(r)})
            self.assertTrue(res["isError"])
            self.assertEqual(d["error"], {"type": "permission_denied", "message": self.c0.motif_lecture_seule})
        r.refresh_from_db()
        self.assertEqual(r.valeur, Decimal(100))

    def test_lecteur_et_auditeur_n_ecrivent_jamais(self):
        alerte = Alerte.objects.create(campagne=self.c, kpi=self.eff, organisation=self.e1, controle=Alerte.Controle.ECART_N1,
                                       message="écart")
        avant = list(Reponse.objects.values_list("pk", "valeur", "statut", "non_applicable", "commentaire"))
        for role in ("lecteur", "auditeur"):
            outils = {t["name"] for t in self.requete(self.jetons[role], "tools/list").json()["result"]["tools"]}
            self.assertFalse(outils & {o.nom for o in O.OUTILS if o.ecriture}, role)
            for nom, args in (("save_value", {**self.case(), "value": "1", "version": ""}),
                              ("mark_not_applicable", {**self.case(), "comment": "x", "version": ""}),
                              ("validate_value", self.case()), ("justify_alert", {"alert_id": alerte.pk, "text": "x"}),
                              ("send_reminder", {"send": True, "person_ids": [self.contrib.pk]})):
                _, res, d = self.outil(role, nom, args)
                self.assertEqual(d["error"]["type"], "permission_denied", (role, nom))
        self.assertEqual(list(Reponse.objects.values_list("pk", "valeur", "statut", "non_applicable", "commentaire")), avant)
        alerte.refresh_from_db()
        self.assertEqual(alerte.statut, Alerte.Statut.OUVERTE)

    def test_justifier_une_alerte_comme_sa_fiche(self):
        alerte = Alerte.objects.create(campagne=self.c, kpi=self.eff, organisation=self.e1, controle=Alerte.Controle.ECART_N1,
                                       message="écart")
        url = reverse("collecte:alerte", args=[alerte.pk])
        for role in ROLES:
            with self.subTest(role=role):
                with Annulee():
                    statut = self.page(role).post(url, {"action": "justifier", "texte": "Embauches"}).status_code
                    page_ok = Alerte.objects.get(pk=alerte.pk).statut == Alerte.Statut.JUSTIFIEE
                with Annulee():
                    _, res, d = self.outil(role, "justify_alert", {"alert_id": alerte.pk, "text": "Embauches"})
                    mcp_ok = not res["isError"] and Alerte.objects.get(pk=alerte.pk).statut == Alerte.Statut.JUSTIFIEE
                self.assertEqual(mcp_ok, page_ok, (role, statut, d))

    def test_relances_comme_la_page(self):
        for role in ROLES:
            with self.subTest(role=role):
                statut = self.page(role).get(reverse("collecte:relances")).status_code
                outils = {t["name"] for t in self.requete(self.jetons[role], "tools/list").json()["result"]["tools"]}
                _, res, d = self.outil(role, "send_reminder", {})
                self.assertEqual("send_reminder" in outils, statut == 200)
                self.assertEqual(self.refus_mcp(res), statut == 403, d)

    def test_relance_sans_serveur_d_envoi_refusee_comme_la_page(self):
        _, res, d = self.outil("admin", "send_reminder", {"send": True, "person_ids": [self.contrib.pk]})
        self.assertEqual(d["error"]["type"], "invalid")
        self.assertIn("e-mail", d["error"]["message"].lower())

    def test_par_personne_comme_le_tableau_de_bord(self):
        for role, refuse in (("contributeur", True), ("validateur", False), ("lecteur", False), ("admin", False)):
            _, res, _ = self.outil(role, "get_completion", {"campaign_id": self.c.pk, "group_by": "person"})
            self.assertEqual(bool(res["isError"]), refuse, role)

    def test_meme_contenu_que_la_saisie(self):
        _, res, d = self.outil("contributeur", "list_values", {"campaign_id": self.c.pk})
        lignes = S.lignes(self.contrib, self.c)
        self.assertEqual(sorted((v["kpi"]["code"], v["organisation"]["id"]) for v in d["values"]),
                         sorted((l.kpi.code, l.organisation.id) for l in lignes))
        v = next(v for v in d["values"] if v["kpi"]["code"] == "TX")
        self.assertEqual((v["value"], v["status"]), ("35", "brouillon"))  # pourcentage comme il se saisit (0 à 100)

    def test_taux_de_remplissage_comme_le_tableau_de_bord(self):
        from referentiel.plans import Plan

        for role in ("admin", "contributeur", "lecteur"):
            u = self.comptes[role]
            tdb = S.tableau_de_bord(S.lignes(u, self.c, plan=Plan(self.c.referentiel)), Plan(self.c.referentiel))
            _, _, d = self.outil(role, "get_completion", {"campaign_id": self.c.pk})
            self.assertEqual((d["total"]["expected"], d["total"]["validated"], d["total"]["rate"]),
                             (tdb["total"].total, tdb["total"].valide, tdb["total"].taux), role)
