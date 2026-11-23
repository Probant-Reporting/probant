"""Jetons personnels et accès au serveur MCP : un jeton montré une fois et gardé haché ; refusé tout de suite pour un compte
désactivé (dans l'espace ou au registre), un jeton expiré ou révoqué, un mot de passe provisoire, des assistants éteints ;
écritures éteintes ; limite de débit ; Mon compte et Paramètres › Assistants ; jetons jamais sauvegardés."""
import datetime

from django.test import Client
from django.urls import reverse
from django.utils import timezone

from collecte.models import Journal
from espaces.models import Compte
from parametres import sauvegardes as SV

from . import jetons as JT
from .aides_tests import BaseMCP
from .models import AppelMCP, JetonMCP, ReglageMCP


class JetonsTests(BaseMCP):
    def liste(self, role_ou_jeton):
        return self.requete(self.jetons.get(role_ou_jeton, role_ou_jeton), "tools/list")

    def assertRefuse(self, rep):
        self.assertEqual(rep.status_code, 401)
        self.assertIn("Bearer", rep["WWW-Authenticate"])
        self.assertEqual(rep.json()["error"]["data"]["reason"], "invalid_token")

    def test_jeton_haché_jamais_en_clair(self):
        clair = self.jetons["contributeur"]
        j = JetonMCP.objects.get(utilisateur=self.contrib)
        self.assertTrue(clair.startswith("prb_") and len(clair) > 40)
        self.assertEqual(j.empreinte, JT.empreinte(clair))
        self.assertNotIn(clair, str(list(JetonMCP.objects.values())))
        self.assertNotIn(clair, str(list(Journal.objects.values())))
        self.assertEqual(self.liste("contributeur").status_code, 200)

    def test_sans_jeton_ou_jeton_inconnu(self):
        for jeton in ("", "prb_inconnu", "autre-chose", "prb_" + "x" * 300):
            self.assertRefuse(self.requete(jeton, "tools/list"))
        self.assertRefuse(self.requete(None, "tools/list", entetes={"HTTP_AUTHORIZATION": f"Basic {self.jetons['admin']}"}))

    def test_compte_desactive_dans_l_espace_ou_au_registre(self):
        self.assertEqual(self.liste("contributeur").status_code, 200)
        self.contrib.is_active = False
        self.contrib.save()
        self.assertRefuse(self.liste("contributeur"))
        self.contrib.is_active = True
        self.contrib.save()
        Compte.objects.filter(pk=self.contrib.pk).update(actif=False)
        self.assertRefuse(self.liste("contributeur"))

    def test_compte_supprime(self):
        self.autre.delete()
        self.assertRefuse(self.liste(self.jetons["autre"]))

    def test_mot_de_passe_provisoire(self):
        self.contrib.doit_changer_mdp = True
        self.contrib.save()
        self.assertRefuse(self.liste("contributeur"))

    def test_jeton_expire_puis_revoque(self):
        j = JetonMCP.objects.get(utilisateur=self.admin)
        JetonMCP.objects.filter(pk=j.pk).update(expire_le=timezone.now() - datetime.timedelta(seconds=1))
        self.assertRefuse(self.liste("admin"))
        JetonMCP.objects.filter(pk=j.pk).update(expire_le=timezone.now() + datetime.timedelta(days=1))
        self.assertEqual(self.liste("admin").status_code, 200)
        JT.revoquer(self.admin, j.pk)
        self.assertRefuse(self.liste("admin"))

    def test_droits_relus_a_chaque_requete(self):
        _, res, _ = self.outil("contributeur", "get_value", self.case())
        self.assertFalse(res["isError"])
        self.contrib.role = "lecteur"
        self.contrib.save()
        outils = {t["name"] for t in self.liste("contributeur").json()["result"]["tools"]}
        self.assertNotIn("save_value", outils)
        self.assertNotIn("list_values", outils)

    def test_assistants_eteints(self):
        ReglageMCP.objects.filter(pk=1).update(actif=False)
        rep = self.liste("admin")
        self.assertEqual(rep.status_code, 403)
        self.assertEqual(rep.json()["error"]["data"]["reason"], "mcp_disabled")
        with self.assertRaises(Exception):
            JT.creer(self.admin, "Nouveau", 30)

    def test_ecritures_eteintes(self):
        ReglageMCP.objects.filter(pk=1).update(ecriture=False)
        outils = {t["name"] for t in self.liste("admin").json()["result"]["tools"]}
        self.assertNotIn("save_value", outils)
        self.assertIn("get_value", outils)
        _, res, d = self.outil("admin", "save_value", {**self.case(), "value": "1", "version": ""})
        self.assertEqual(d["error"]["type"], "permission_denied")
        self.assertIn("lire", d["error"]["message"])

    def test_limite_de_debit(self):
        ReglageMCP.objects.filter(pk=1).update(appels_minute=2)
        for _ in range(2):
            self.assertEqual(self.outil("contributeur", "list_campaigns")[0].status_code, 200)
        rep = self.requete(self.jetons["contributeur"], "tools/call", {"name": "list_campaigns"})
        self.assertEqual(rep.status_code, 429)
        self.assertGreaterEqual(int(rep["Retry-After"]), 1)
        self.assertEqual(rep.json()["error"]["data"]["reason"], "rate_limited")
        self.assertEqual(self.outil("admin", "list_campaigns")[0].status_code, 200)  # par personne
        AppelMCP.objects.update(date=timezone.now() - datetime.timedelta(seconds=61))
        self.assertEqual(self.outil("contributeur", "list_campaigns")[0].status_code, 200)

    def test_limite_par_personne_tous_jetons_ensemble(self):
        ReglageMCP.objects.filter(pk=1).update(appels_minute=1)
        second, _ = JT.creer(self.contrib, "Second", 7)
        self.assertEqual(self.outil("contributeur", "list_campaigns")[0].status_code, 200)
        self.assertEqual(self.requete(second, "tools/call", {"name": "list_campaigns"}).status_code, 429)

    def test_creation_bornee(self):
        for nom, jours in (("", 30), ("x" * 81, 30), ("Ok", 31), ("Ok", "abc"), ("Ok", 365)):
            with self.assertRaises(Exception):
                JT.creer(self.lecteur, nom, jours)
        for i in range(JT.JETONS_MAX - 1):
            JT.creer(self.lecteur, f"J{i}", 7)
        with self.assertRaises(Exception):
            JT.creer(self.lecteur, "Onzième", 7)
        self.assertEqual(JT.actifs(self.lecteur).count(), JT.JETONS_MAX)

    def test_durees_proposees(self):
        r = ReglageMCP.courant()
        for maxi, attendu in ((90, [7, 30, 90]), (60, [7, 30, 60]), (365, [7, 30, 90, 365]), (5, [5])):
            r.duree_max_jours = maxi
            self.assertEqual(JT.durees_proposees(r), attendu)
            self.assertIn(JT.duree_par_defaut(attendu), attendu)

    def test_jamais_dans_une_sauvegarde(self):
        modeles = {m._meta.label_lower for m in SV.modeles_sauvegardes()}
        self.assertNotIn("serveur_mcp.jetonmcp", modeles)
        self.assertIn("serveur_mcp.reglagemcp", modeles)
        self.assertIn("serveur_mcp.journalmcp", modeles)


class MonCompteEtReglagesTests(BaseMCP):
    def test_creer_et_revoquer_dans_mon_compte_tous_les_roles(self):
        for u in (self.lecteur, self.auditeur, self.contrib):
            c = Client()
            c.force_login(u)
            rep = c.post(reverse("collecte:mon_compte"), {"action": "jeton_creer", "nom": "Mon assistant", "jours": "7"}, follow=True)
            self.assertEqual(rep.status_code, 200)  # après la redirection (test_action_jeton_rechargement.py)
            j = JetonMCP.objects.filter(utilisateur=u, nom="Mon assistant").get()
            page = rep.content.decode()
            clair = page.split('id="jeton-nouveau" class="code-copie">')[1].split("<")[0]
            self.assertEqual(JT.empreinte(clair), j.empreinte)  # montré une fois, dans la page qui suit la création
            self.assertIn("claude mcp add --transport http probant", page)
            self.assertNotIn(clair, c.get(reverse("collecte:mon_compte")).content.decode())  # jamais remontré
            c.post(reverse("collecte:mon_compte"), {"action": "jeton_revoquer", "jeton": j.pk})
            j.refresh_from_db()
            self.assertIsNotNone(j.revoque_le)
        self.assertTrue(Journal.objects.filter(action="jeton_mcp", champ="mcp_jeton_cree").exists())
        self.assertTrue(Journal.objects.filter(action="jeton_mcp", champ="mcp_jeton_revoque").exists())

    def test_pas_de_jeton_avec_un_mot_de_passe_provisoire(self):
        self.contrib.doit_changer_mdp = True
        self.contrib.save()
        c = Client()
        c.force_login(self.contrib)
        c.post(reverse("collecte:mon_compte"), {"action": "jeton_creer", "nom": "Provisoire", "jours": "7"})
        self.assertFalse(JetonMCP.objects.filter(nom="Provisoire").exists())

    def test_on_ne_revoque_pas_le_jeton_d_un_autre(self):
        j = JetonMCP.objects.get(utilisateur=self.admin)
        c = Client()
        c.force_login(self.contrib)
        c.post(reverse("collecte:mon_compte"), {"action": "jeton_revoquer", "jeton": j.pk})
        j.refresh_from_db()
        self.assertIsNone(j.revoque_le)

    def test_mon_compte_sans_assistants(self):
        ReglageMCP.objects.filter(pk=1).update(actif=False)
        c = Client()
        c.force_login(self.contrib)
        page = c.get(reverse("collecte:mon_compte")).content.decode()
        self.assertIn("n'a pas permis les assistants", page)
        self.assertNotIn('name="action" value="jeton_creer"', page)
        rep = c.post(reverse("collecte:mon_compte"), {"action": "jeton_creer", "nom": "x", "jours": "7"})
        self.assertIn("n'a pas permis les assistants", rep.content.decode())
        self.assertFalse(JetonMCP.objects.filter(nom="x").exists())

    def test_reglages_reserves_a_l_administrateur_et_journalises(self):
        url = reverse("serveur_mcp:reglages")
        for u in (self.contrib, self.validateur, self.lecteur, self.auditeur):
            c = Client()
            c.force_login(u)
            self.assertEqual(c.get(url).status_code, 403)
            self.assertEqual(c.post(url, {"actif": "on", "appels_minute": 5, "duree_max_jours": 5}).status_code, 403)
        c = Client()
        c.force_login(self.admin)
        self.assertEqual(c.get(url).status_code, 200)
        rep = c.post(url, {"appels_minute": 30, "duree_max_jours": 10, "kpi_sensibles": "on"})  # case cochée par défaut
        self.assertEqual(rep.status_code, 302)
        r = ReglageMCP.courant()
        self.assertEqual((r.actif, r.ecriture, r.appels_minute, r.duree_max_jours), (False, False, 30, 10))
        self.assertEqual(set(Journal.objects.filter(action="reglage_mcp").values_list("champ", flat=True)),
                         {"mcp_actif", "mcp_ecriture", "mcp_appels_minute", "mcp_duree_max_jours"})
        rep = c.post(url, {"actif": "on", "appels_minute": 0, "duree_max_jours": 400})
        self.assertEqual(rep.status_code, 200)  # hors bornes : refusé, rien d'enregistré
        self.assertFalse(ReglageMCP.courant().actif)

    def test_l_administrateur_revoque_un_jeton_de_l_espace(self):
        j = JetonMCP.objects.get(utilisateur=self.contrib)
        c = Client()
        c.force_login(self.admin)
        page = c.get(reverse("serveur_mcp:reglages")).content.decode()
        self.assertIn(j.debut, page)
        self.assertNotIn(self.jetons["contributeur"], page)
        c.post(reverse("serveur_mcp:reglages"), {"action": "revoquer", "jeton": j.pk})
        j.refresh_from_db()
        self.assertEqual(j.revoque_par, self.admin)
        self.assertEqual(self.requete(self.jetons["contributeur"], "tools/list").status_code, 401)

    def test_eteint_par_defaut(self):
        ReglageMCP.objects.all().delete()
        self.assertFalse(ReglageMCP.courant().actif)
        self.assertFalse(ReglageMCP.courant().ecriture)
