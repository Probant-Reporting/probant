"""Aides des tests du serveur MCP : base (organisations, KPI, campagne ouverte et campagne clôturée, cinq rôles et un
validateur), assistants permis, jetons, appel JSON-RPC sur le point d'entrée."""
import json
import logging

from django.test import Client
from django.urls import reverse

from collecte.aides_tests.lecture_seule import Base as BaseLectureSeule
from referentiel.models import Attribution, Utilisateur

from . import jetons as JT
from .models import ReglageMCP

MODERNE = "2026-07-28"


class BaseMCP(BaseLectureSeule):
    """Assistants permis (lecture et écriture), un jeton par personne ; ``self.c`` ouverte, ``self.c0`` clôturée."""

    ecriture = True

    def setUp(self):
        super().setUp()
        journal = logging.getLogger("serveur_mcp")  # refus de jeton notés au journal du serveur : pas dans la sortie des tests
        niveau = journal.level
        journal.setLevel(logging.ERROR)
        self.addCleanup(journal.setLevel, niveau)
        self.validateur = Utilisateur.objects.create(username="val", email="val@exemple.test", role=Utilisateur.Role.VALIDATEUR)
        Attribution.objects.create(kpi=self.eff, organisation=self.p, utilisateur=self.validateur, role=Attribution.Role.VALIDATEUR)
        ReglageMCP.objects.update_or_create(pk=1, defaults={"actif": True, "ecriture": self.ecriture, "appels_minute": 600})
        self.comptes = {"admin": self.admin, "validateur": self.validateur, "contributeur": self.contrib, "autre": self.autre,
                        "lecteur": self.lecteur, "auditeur": self.auditeur}
        self.jetons = {role: JT.creer(u, f"Essai {role}", 30)[0] for role, u in self.comptes.items()}
        self.mcp = Client()  # sans session : seul le jeton compte
        self.url_mcp = reverse("serveur_mcp:point")

    def requete(self, jeton, methode, params=None, rid=1, version=None, entetes=None, corps=None):
        """POST JSON-RPC ; ``version`` : 2026-07-28 (enveloppe et en-têtes) ou une version à poignée de main (en-tête seul)."""
        params = dict(params or {})
        h = {"HTTP_AUTHORIZATION": f"Bearer {jeton}"} if jeton else {}
        if version == MODERNE:
            params["_meta"] = {"io.modelcontextprotocol/protocolVersion": MODERNE, "io.modelcontextprotocol/clientCapabilities": {}}
            h.update(HTTP_MCP_PROTOCOL_VERSION=MODERNE, HTTP_MCP_METHOD=methode)
            if methode == "tools/call":
                h["HTTP_MCP_NAME"] = params.get("name", "")
        elif version:
            h["HTTP_MCP_PROTOCOL_VERSION"] = version
        h.update(entetes or {})
        if corps is None:
            corps = json.dumps({"jsonrpc": "2.0", "id": rid, "method": methode, "params": params})
        return self.mcp.post(self.url_mcp, corps, content_type="application/json", **h)

    def outil(self, role_ou_jeton, nom, arguments=None, version=None):
        """(réponse HTTP, résultat de l'outil, données) d'un appel d'outil."""
        jeton = self.jetons.get(role_ou_jeton, role_ou_jeton)
        rep = self.requete(jeton, "tools/call", {"name": nom, "arguments": arguments or {}}, version=version)
        corps = rep.json()
        resultat = corps.get("result")
        donnees = json.loads(resultat["content"][0]["text"]) if resultat else None
        return rep, resultat, donnees

    def case(self, campagne=None, kpi=None, org=None):
        return {"campaign_id": (campagne or self.c).pk, "kpi_code": (kpi or self.eff).pk, "organisation_id": (org or self.e1).pk}
