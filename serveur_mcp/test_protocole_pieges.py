"""Protocole MCP (HTTP sans état, versions 2026-07-28 et 2025-xx) et entrées piégées : corps illisible, lot JSON-RPC,
identifiants forgés, en-têtes qui contredisent l'enveloppe, version inconnue, Origin d'un autre site, arguments inconnus
ou de mauvais type, textes démesurés, octet NUL, curseur forgé, séparateur ambigu, codes forgés."""
import json

from collecte.models import Reponse

from .aides_tests import MODERNE, BaseMCP


class ProtocoleTests(BaseMCP):
    def test_discover_et_initialize(self):
        rep = self.requete(self.jetons["contributeur"], "server/discover", version=MODERNE)
        r = rep.json()["result"]
        self.assertEqual((rep.status_code, r["supportedVersions"], r["resultType"]), (200, [MODERNE], "complete"))
        self.assertEqual(r["capabilities"], {"tools": {"listChanged": False}})
        self.assertEqual(r["_meta"]["io.modelcontextprotocol/serverInfo"]["name"], "probant")
        self.assertNotIn("Mcp-Session-Id", rep)
        for demandee, obtenue in (("2025-06-18", "2025-06-18"), ("2025-11-25", "2025-11-25"), ("1999-01-01", "2025-11-25")):
            r = self.requete(self.jetons["contributeur"], "initialize", {"protocolVersion": demandee, "capabilities": {},
                                                                         "clientInfo": {"name": "t", "version": "1"}}).json()
            self.assertEqual(r["result"]["protocolVersion"], obtenue)
        self.assertEqual(self.requete(self.jetons["contributeur"], "ping").json()["result"], {})

    def test_resultats_selon_la_version(self):
        moderne = self.requete(self.jetons["contributeur"], "tools/list", version=MODERNE).json()["result"]
        self.assertEqual((moderne["cacheScope"], moderne["ttlMs"], moderne["resultType"]), ("private", 0, "complete"))
        ancienne = self.requete(self.jetons["contributeur"], "tools/list", version="2025-03-26").json()["result"]
        self.assertNotIn("resultType", ancienne)
        _, res, _ = self.outil("contributeur", "list_campaigns", version="2025-06-18")
        self.assertIn("structuredContent", res)
        _, res, _ = self.outil("contributeur", "list_campaigns", version="2025-03-26")
        self.assertNotIn("structuredContent", res)

    def test_get_et_delete_refuses(self):
        self.assertEqual(self.mcp.get(self.url_mcp).status_code, 405)
        self.assertEqual(self.mcp.delete(self.url_mcp).status_code, 405)

    def test_notification_et_reponse_du_client(self):
        j = self.jetons["contributeur"]
        corps = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.assertEqual(self.requete(j, "", corps=corps).status_code, 202)
        self.assertEqual(self.requete(j, "", corps=json.dumps({"jsonrpc": "2.0", "id": 3, "result": {}})).status_code, 202)

    def test_corps_illisibles(self):
        j = self.jetons["contributeur"]
        cas = {"{": -32700, "\xff": -32700, "[]": -32600, json.dumps([{"jsonrpc": "2.0", "id": 1, "method": "ping"}]): -32600,
               json.dumps({"jsonrpc": "1.0", "id": 1, "method": "ping"}): -32600, json.dumps({"jsonrpc": "2.0", "id": 1}): -32600,
               json.dumps({"jsonrpc": "2.0", "id": True, "method": "ping"}): -32600,
               json.dumps({"jsonrpc": "2.0", "id": {"a": 1}, "method": "ping"}): -32600,
               json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping", "params": [1]}): -32602,
               json.dumps({"jsonrpc": "2.0", "id": 1, "method": "resources/list"}): -32601,
               json.dumps({"jsonrpc": "2.0", "id": 1, "method": "x" * 5000}): -32601}
        for corps, code in cas.items():
            with self.subTest(corps=corps[:40]):
                rep = self.requete(j, "", corps=corps)
                self.assertEqual(rep.json()["error"]["code"], code)

    def test_enveloppe_2026_controlee(self):
        j = self.jetons["contributeur"]
        meta = {"io.modelcontextprotocol/protocolVersion": MODERNE, "io.modelcontextprotocol/clientCapabilities": {}}
        cas = [
            ({"_meta": {"io.modelcontextprotocol/protocolVersion": MODERNE}}, {"HTTP_MCP_PROTOCOL_VERSION": MODERNE, "HTTP_MCP_METHOD": "tools/list"}, -32602, 400),
            ({"_meta": meta}, {"HTTP_MCP_METHOD": "tools/list"}, -32020, 400),
            ({"_meta": meta}, {"HTTP_MCP_PROTOCOL_VERSION": MODERNE, "HTTP_MCP_METHOD": "ping"}, -32020, 400),
            ({"_meta": {**meta, "io.modelcontextprotocol/protocolVersion": "2099-01-01"}},
             {"HTTP_MCP_PROTOCOL_VERSION": "2099-01-01", "HTTP_MCP_METHOD": "tools/list"}, -32022, 400),
        ]
        for params, entetes, code, statut in cas:
            with self.subTest(code=code, entetes=entetes):
                corps = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": params})
                rep = self.requete(j, "", corps=corps, entetes=entetes)
                self.assertEqual((rep.status_code, rep.json()["error"]["code"]), (statut, code))
        corps = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"_meta": meta, "name": "list_campaigns"}})
        rep = self.requete(j, "", corps=corps, entetes={"HTTP_MCP_PROTOCOL_VERSION": MODERNE, "HTTP_MCP_METHOD": "tools/call",
                                                        "HTTP_MCP_NAME": "list_values"})
        self.assertEqual(rep.json()["error"]["code"], -32020)
        rep = self.requete(j, "", corps=corps, entetes={"HTTP_MCP_PROTOCOL_VERSION": MODERNE, "HTTP_MCP_METHOD": "tools/call",
                                                        "HTTP_MCP_NAME": "=?base64?bGlzdF9jYW1wYWlnbnM=?="})
        self.assertEqual(rep.status_code, 200)  # nom encodé en base64 : accepté
        rep = self.requete(j, "tools/list", version="1999-01-01")
        self.assertEqual(rep.status_code, 400)

    def test_origine_d_un_autre_site_refusee(self):
        j = self.jetons["contributeur"]
        rep = self.requete(j, "tools/list", entetes={"HTTP_ORIGIN": "https://pirate.example"})
        self.assertEqual(rep.status_code, 403)
        rep = self.requete(j, "tools/list", entetes={"HTTP_ORIGIN": "http://testserver"})
        self.assertEqual(rep.status_code, 200)

    def test_session_du_navigateur_ignoree(self):
        """Une session ouverte (cookie) ne remplace jamais le jeton ; un lecteur connecté n'atteint pas le point d'entrée."""
        self.mcp.force_login(self.admin)
        self.assertEqual(self.requete(None, "tools/list").status_code, 401)
        self.mcp.force_login(self.lecteur)
        self.assertEqual(self.requete(self.jetons["lecteur"], "tools/list").status_code, 403)  # règle des pages


class EntreesPiegeesTests(BaseMCP):
    def erreur_rpc(self, nom, arguments):
        rep = self.requete(self.jetons["admin"], "tools/call", {"name": nom, "arguments": arguments})
        return rep.json().get("error", {}).get("code")

    def test_arguments_refuses_avant_tout_appel(self):
        avant = list(Reponse.objects.values_list("pk", "valeur", "commentaire"))
        c = self.case()
        cas = [
            ("outil_inconnu", {}), ("get_value", {**c, "inconnu": 1}), ("get_value", {**c, "campaign_id": "1"}),
            ("get_value", {**c, "campaign_id": True}), ("get_value", {**c, "campaign_id": -1}), ("get_value", {**c, "campaign_id": 2**40}),
            ("get_value", {**c, "kpi_code": "x" * 31}), ("get_value", {**c, "kpi_code": ["EFF"]}), ("get_value", {"campaign_id": 1}),
            ("save_value", {**c, "value": "x" * 20001, "version": ""}), ("save_value", {**c, "value": {"a": 1}, "version": ""}),
            ("save_value", {**c, "value": "1"}), ("list_values", {"campaign_id": self.c.pk, "status": "pirate"}),
            ("list_values", {"campaign_id": self.c.pk, "limit": 201}), ("list_values", {"campaign_id": self.c.pk, "cursor": "!!"}),
            ("list_values", {"campaign_id": self.c.pk, "cursor": "OTk5OTk5"}),
            ("send_reminder", {"person_ids": [1, "2"]}), ("send_reminder", {"person_ids": list(range(1, 300))}),
        ]
        for nom, args in cas:
            with self.subTest(outil=nom, args=str(args)[:60]):
                self.assertEqual(self.erreur_rpc(nom, args), -32602)
        rep = self.requete(self.jetons["admin"], "tools/call", {"name": "save_value", "arguments": {**c, "value": "1", "version": "",
                                                                                                "comment": "a\x00b"}})
        self.assertEqual(rep.status_code, 400)  # octet NUL : refusé par la garde des requêtes, avant le serveur MCP
        rep = self.requete(self.jetons["admin"], "tools/call", {"name": "get_value", "arguments": "texte"})
        self.assertEqual(rep.json()["error"]["code"], -32602)
        self.assertEqual(list(Reponse.objects.values_list("pk", "valeur", "commentaire")), avant)

    def test_objets_inconnus_ou_forges(self):
        for args in ({**self.case(), "kpi_code": "' OR 1=1 --"}, {**self.case(), "kpi_code": "../EFF"},
                     {**self.case(), "organisation_id": 999999}, {**self.case(), "campaign_id": 999999}):
            _, res, d = self.outil("admin", "get_value", args)
            self.assertEqual(d["error"]["type"], "not_found", args)
        _, res, d = self.outil("admin", "justify_alert", {"alert_id": 424242, "text": "x"})
        self.assertEqual(d["error"]["type"], "not_found")

    def test_valeurs_refusees_par_les_regles_de_la_saisie(self):
        r = Reponse.objects.get(periode=self.c.periode, kpi=self.eff, organisation=self.e1)
        version = r.date_maj.isoformat()
        for valeur in ("1,234", "12.500", "abc", "1e3", "NaN", "9" * 20, "12%"):  # ambigus, illisibles, trop grand, « % » hors pourcentage
            with self.subTest(valeur=valeur):
                _, res, d = self.outil("contributeur", "save_value", {**self.case(), "value": valeur, "version": version})
                self.assertEqual(d["error"]["type"], "invalid")
        _, res, d = self.outil("contributeur", "save_value", {**self.case(), "value": 1e400, "version": version})
        self.assertTrue(res["isError"])
        _, res, d = self.outil("contributeur", "save_value", {**self.case(kpi=self.taux), "value": "150",
                                                              "version": Reponse.objects.get(kpi=self.taux, periode=self.c.periode).date_maj.isoformat()})
        self.assertEqual(d["error"]["type"], "invalid")  # pourcentage hors de 0 à 100
        r.refresh_from_db()
        self.assertEqual(r.valeur, 110)

    def test_nombre_json_et_texte(self):
        r = Reponse.objects.get(periode=self.c.periode, kpi=self.eff, organisation=self.e1)
        _, res, d = self.outil("contributeur", "save_value", {**self.case(), "value": 120, "version": r.date_maj.isoformat()})
        self.assertFalse(res["isError"], d)
        self.assertEqual((d["value"], d["status"], d["comment"]), ("120", "brouillon", {"user_text": "Embauches"}))  # commentaire gardé (texte saisi : enveloppe)

    def test_conflit_de_version(self):
        _, res, d = self.outil("contributeur", "save_value", {**self.case(), "value": "5", "version": "2020-01-01T00:00:00+00:00"})
        self.assertEqual(d["error"]["type"], "invalid")
        self.assertIn("modifiée", d["error"]["message"])

    def test_na_sans_commentaire_refuse(self):
        r = Reponse.objects.get(periode=self.c.periode, kpi=self.eff, organisation=self.e1)
        _, res, d = self.outil("contributeur", "mark_not_applicable", {**self.case(), "comment": "   ", "version": r.date_maj.isoformat()})
        self.assertEqual(d["error"]["type"], "invalid")

    def test_pagination_bornee(self):
        _, _, d = self.outil("admin", "list_values", {"campaign_id": self.c.pk, "limit": 1})
        self.assertEqual(len(d["values"]), 1)
        suite = d["next_cursor"]
        _, _, d2 = self.outil("admin", "list_values", {"campaign_id": self.c.pk, "limit": 1, "cursor": suite})
        self.assertNotEqual(d["values"][0]["organisation"]["id"], d2["values"][0]["organisation"]["id"])

    def test_texte_long_coupe_dans_les_listes_et_entier_dans_get_value(self):
        from parametres.models import TypeReponse
        from referentiel.models import KPI, Attribution, Niveau

        t = TypeReponse.objects.filter(format="texte").first()
        k = KPI.objects.create(code="TXT", libelle="Texte", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY, type_reponse=t)
        from referentiel.models import ElementReferentiel

        ElementReferentiel.objects.create(referentiel=self.c.referentiel, kpi=k)
        Attribution.objects.create(kpi=k, organisation=self.e1, utilisateur=self.contrib)
        long = "Mot " * 1000
        _, res, d = self.outil("contributeur", "save_value", {**self.case(kpi=k), "value": long, "version": ""})
        self.assertFalse(res["isError"], d)
        _, _, d = self.outil("contributeur", "list_values", {"campaign_id": self.c.pk, "kpi_code": "TXT"})
        self.assertTrue(d["values"][0]["truncated"])
        self.assertEqual(len(d["values"][0]["value"]["user_text"]), 1000)
        _, _, d = self.outil("contributeur", "get_value", self.case(kpi=k))
        self.assertEqual(d["value"], {"user_text": long.strip()})

    def test_preuves_sans_contenu(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from collecte import saisie as S

        S.ajouter_preuve(self.contrib, self.c, self.eff, self.e1, SimpleUploadedFile("facture.pdf", b"%PDF-1.4 secret", "application/pdf"))
        rep, res, d = self.outil("auditeur", "list_evidence", self.case())
        self.assertEqual([p["file_name"] for p in d["evidence"]], [{"user_text": "facture.pdf"}])
        self.assertNotIn("secret", rep.content.decode())
