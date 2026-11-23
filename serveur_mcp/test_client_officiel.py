"""Essai de bout en bout : le client du paquet officiel ``mcp`` (requirements-dev.txt) contre un vrai serveur de test, en
2026-07-28 (``server/discover``, mode « auto ») et en 2025-11-25 (``initialize``, mode « legacy ») : liste des outils,
lecture, saisie, refus d'une campagne clôturée, jeton refusé. Sauté si le paquet n'est pas installé."""
import asyncio
import datetime
import json
import unittest
from decimal import Decimal

from django.test import LiveServerTestCase
from django.urls import reverse
from django.utils import timezone

from collecte.models import Campagne, Journal, Reponse
from collecte.outils_tests import RetourSerialiseIndependantDeLOrdre, ServeurDeTestUnSeulFil
from referentiel.models import KPI, Attribution, ElementReferentiel, Niveau, Organisation, Utilisateur

from . import jetons as JT
from .models import ReglageMCP

try:
    import httpx2
    from mcp import Client
    from mcp.client.streamable_http import streamable_http_client
except ImportError:  # pragma: no cover - poste sans le paquet de développement
    Client = None


class ClientOfficielTests(ServeurDeTestUnSeulFil, RetourSerialiseIndependantDeLOrdre, LiveServerTestCase):
    serialized_rollback = True

    @classmethod
    def setUpClass(cls):
        if Client is None:
            raise unittest.SkipTest("Le paquet « mcp » n'est pas installé (requirements-dev.txt).")
        super().setUpClass()

    def setUp(self):
        super().setUp()
        g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.site = Organisation.objects.create(nom="Lille", niveau_id=Niveau.ENTITY, parent=g)
        self.kpi = KPI.objects.create(code="EFF", libelle="Effectif", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                                      methode_agregation="Somme", decimales=0)
        self.close = Campagne.objects.create(exercice=2025, statut=Campagne.Statut.CLOTUREE)
        ElementReferentiel.objects.create(referentiel=self.close.referentiel, kpi=self.kpi)
        self.c = Campagne.objects.create(exercice=2026, statut=Campagne.Statut.OUVERTE,
                                         date_fin_saisie=timezone.localdate() + datetime.timedelta(days=30))
        Reponse.objects.create(periode=self.close.periode, kpi=self.kpi, organisation=self.site, valeur=Decimal(100), statut="valide")
        self.u = Utilisateur.objects.create(username="camille", email="camille@exemple.test", first_name="Camille")
        Attribution.objects.create(kpi=self.kpi, organisation=self.site, utilisateur=self.u)
        ReglageMCP.objects.update_or_create(pk=1, defaults={"actif": True, "ecriture": True})
        self.jeton, _ = JT.creer(self.u, "Essai", 7)
        self.url = self.live_server_url + reverse("serveur_mcp:point")

    def client_mcp(self, jeton, mode):
        http = httpx2.AsyncClient(headers={"Authorization": f"Bearer {jeton}"}, timeout=30, trust_env=False)
        return Client(streamable_http_client(self.url, http_client=http), mode=mode)

    async def parcours(self, mode):
        async with self.client_mcp(self.jeton, mode) as c:
            noms = {t.name for t in (await c.list_tools()).tools}
            camp = json.loads((await c.call_tool("list_campaigns", {})).content[0].text)["campaigns"]
            case = {"campaign_id": self.c.pk, "kpi_code": "EFF", "organisation_id": self.site.pk}
            vide = json.loads((await c.call_tool("get_value", case)).content[0].text)
            ecrit = await c.call_tool("save_value", {**case, "value": "120", "comment": "Embauches", "version": vide["version"]})
            refus = await c.call_tool("save_value", {"campaign_id": self.close.pk, "kpi_code": "EFF", "organisation_id": self.site.pk,
                                                     "value": "5", "version": ""})
            return noms, camp, vide, ecrit, refus

    def test_moderne_puis_poignee_de_main(self):
        for mode in ("auto", "legacy"):
            with self.subTest(mode=mode):
                Reponse.objects.filter(periode=self.c.periode).delete()
                noms, camp, vide, ecrit, refus = asyncio.run(self.parcours(mode))
                self.assertIn("save_value", noms)
                self.assertNotIn("send_reminder", noms)  # contributeur : pas de relances
                self.assertEqual({x["id"] for x in camp}, {self.c.pk, self.close.pk})
                self.assertEqual(vide["status"], "a_saisir")
                self.assertFalse(ecrit.is_error, ecrit.content[0].text)
                self.assertTrue(refus.is_error)
                self.assertIn("lôturée", refus.content[0].text)
                r = Reponse.objects.get(periode=self.c.periode, kpi=self.kpi, organisation=self.site)
                self.assertEqual((r.valeur, r.statut, r.saisi_par_id), (Decimal(120), "brouillon", self.u.pk))
        self.assertEqual(Reponse.objects.get(periode=self.close.periode, organisation=self.site).valeur, Decimal(100))
        # par client : 2 lectures, 1 écriture réussie (une ligne « appel_mcp »), 1 écriture refusée ; lectures et refus
        # comptés dans la ligne du jour (« appels_mcp »)
        self.assertEqual(list(Journal.objects.filter(action="appel_mcp", utilisateur=self.u).values_list("champ", flat=True)),
                         ["save_value", "save_value"])
        jour = Journal.objects.get(action="appels_mcp", utilisateur=self.u)
        self.assertTrue(jour.apres.startswith("lectures : 4 ; refus : 2 ; "), jour.apres)

    def test_jeton_refuse(self):
        from . import vues

        vues._refus.clear()  # avertissement au plus une fois par minute et par espace (test_noter_refus_frequence.py)

        async def essai():
            async with self.client_mcp("prb_pas_un_jeton", "auto") as c:
                await c.list_tools()

        with self.assertRaises(BaseException), self.assertLogs("serveur_mcp", "WARNING"):
            asyncio.run(essai())
