"""Historique des connexions : ce qui est noté (réussie, échec, bloquée), où (base de l'espace), ce qui ne
l'est jamais (mot de passe, identifiant inconnu tapé, compte d'un autre espace), qui le voit (administrateur de l'espace,
la personne dans Mon compte), combien de temps (réglage de Hébergement, ménage de la nuit), page de confidentialité."""
import datetime

from django.core.cache import caches
from django.test import Client
from django.utils import timezone

from collecte import controle_donnees as CD
from collecte.models import Journal
from espaces import contexte as E
from espaces.aides_tests import MDP, creer
from espaces.essais import EspacesTestCase
from parametres.models import Instance

from . import connexion as CX
from . import historique_connexions as HC
from .models import HistoriqueConnexion, Utilisateur

PIEGE = "<script>alert(1)</script>Mon-Mot-De-Passe-2026"  # mot de passe tapé dans le champ de l'identifiant
URL_ADMIN = "/administration/comptes/connexions/"


def se_connecter(identifiant, mdp=MDP, espace="principal"):
    page = "/connexion/" if espace == "principal" else f"/espace/{espace}/connexion/"
    c = Client()
    return c, c.post(page, {"username": identifiant, "password": mdp})


def lignes(espace="principal"):
    with E.activer(espace):
        return list(HistoriqueConnexion.objects.order_by("pk").values_list("utilisateur_id", "resultat", "empreinte"))


def tous_les_champs(espace="principal"):
    with E.activer(espace):
        return " ".join(map(str, HistoriqueConnexion.objects.values_list("utilisateur_id", "resultat", "empreinte", "date")))


class Base(EspacesTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.admin = creer("admin@exemple.example", "admin")
        cls.contrib = creer("contrib@exemple.example")
        cls.lecteur = creer("lecteur@exemple.example", "lecteur")
        cls.auditeur = creer("auditeur@exemple.example", "auditeur")
        cls.validateur = creer("validateur@exemple.example", "validateur")
        cls.achats = creer("achats@exemple.example", "contributeur", "essai")  # « essai » seulement

    def setUp(self):
        super().setUp()
        caches["connexion"].clear()

    def client_de(self, u, espace="principal"):
        c = Client()
        with E.activer(espace):
            c.force_login(Utilisateur.objects.get(pk=u.pk))
        return c


class NoterTests(Base):
    def test_reussite_et_echec_d_un_compte(self):
        _, rep = se_connecter("contrib@exemple.example")
        self.assertEqual(rep.status_code, 302)
        se_connecter("CONTRIB@exemple.example", "mauvais")
        self.assertEqual(lignes(), [(self.contrib.pk, "reussie", ""),
                                    (self.contrib.pk, "echec", HC.empreinte("contrib@exemple.example"))])

    def test_identifiant_inconnu_jamais_garde_tel_quel(self):
        se_connecter(PIEGE, "x")
        self.assertEqual(lignes(), [(None, "echec", HC.empreinte(PIEGE))])
        self.assertNotIn("script", tous_les_champs())
        self.assertNotIn("Mot-De-Passe", tous_les_champs())
        rep = self.client_de(self.admin).get(URL_ADMIN)
        self.assertContains(rep, HC.empreinte(PIEGE))
        self.assertNotContains(rep, "Mot-De-Passe")
        self.assertNotContains(rep, "<script>alert")

    def test_mot_de_passe_jamais_garde(self):
        se_connecter("contrib@exemple.example", "Secret-tape-2026")
        self.assertNotIn("Secret", tous_les_champs())

    def test_bloquee_par_la_limite_d_essais(self):
        for _ in range(CX.ESSAIS_MAX):
            se_connecter("contrib@exemple.example", "mauvais")
        _, rep = se_connecter("contrib@exemple.example")  # bon mot de passe, mais trop d'essais
        self.assertEqual(rep.status_code, 200)
        resultats = [r for _, r, _ in lignes()]
        self.assertEqual(resultats, ["echec"] * CX.ESSAIS_MAX + ["bloquee"])
        self.assertEqual(lignes()[-1][0], self.contrib.pk)

    def test_compte_d_un_autre_espace_seulement_par_son_empreinte(self):
        """L'administrateur de l'espace principal n'apprend pas qu'un compte d'« essai » existe."""
        se_connecter("achats@exemple.example", "mauvais")
        self.assertEqual(lignes(), [(None, "echec", HC.empreinte("achats@exemple.example"))])

    def test_connexion_dans_l_espace_ou_la_personne_a_acces(self):
        """Bon mot de passe sur la page de l'espace principal, sans accès ici : réussite notée dans « essai », aucun échec
        ici."""
        _, rep = se_connecter("achats@exemple.example")
        self.assertEqual(rep.status_code, 302)
        self.assertEqual(lignes(), [])
        self.assertEqual(lignes("essai"), [(self.achats.pk, "reussie", "")])

    def test_session_ouverte_par_le_code_non_notee(self):
        self.client_de(self.contrib)
        self.assertEqual(lignes(), [])

    def test_mode_expert_bloque(self):
        for _ in range(CX.ESSAIS_MAX):
            Client().post("/admin/login/", {"username": "admin@exemple.example", "password": "mauvais"})
        Client().post("/admin/login/", {"username": "admin@exemple.example", "password": MDP})
        self.assertEqual([r for _, r, _ in lignes()][-1], "bloquee")


class PageAdministrateurTests(Base):
    def test_droits_par_role(self):
        for u in (self.contrib, self.lecteur, self.auditeur, self.validateur):
            c = self.client_de(u)
            self.assertEqual(c.get(URL_ADMIN).status_code, 403, u.role)
            self.assertEqual(c.post(URL_ADMIN).status_code, 403, u.role)
        self.assertEqual(Client().get(URL_ADMIN).status_code, 302)
        self.assertEqual(self.client_de(self.admin).get(URL_ADMIN).status_code, 200)

    def test_vide(self):
        rep = self.client_de(self.admin).get(URL_ADMIN)
        self.assertContains(rep, "page-vide")
        self.assertNotContains(rep, "recherche-connexions")

    def test_filtres_et_espace(self):
        se_connecter("contrib@exemple.example")
        se_connecter("lecteur@exemple.example", "mauvais")
        se_connecter(PIEGE, "x")
        se_connecter("achats@exemple.example", MDP, "essai")  # dans « essai » : pas sur la page de l'espace principal
        c = self.client_de(self.admin)
        rep = c.get(URL_ADMIN)
        self.assertEqual(len(rep.context["lignes"]), 3)
        self.assertNotContains(rep, "achats@exemple.example")
        self.assertContains(rep, 'class="carte-table table-connexions"')
        rep = c.get(URL_ADMIN, {"resultat": "echec"})
        self.assertEqual({x.resultat for x in rep.context["lignes"]}, {"echec"})
        self.assertEqual(len(rep.context["lignes"]), 2)
        rep = c.get(URL_ADMIN, {"q": "lecteur"})
        self.assertEqual([x.utilisateur_id for x in rep.context["lignes"]], [self.lecteur.pk])
        rep = c.get(URL_ADMIN, {"q": PIEGE})  # l'identifiant tapé retrouve sa ligne par son empreinte
        self.assertEqual([x.empreinte for x in rep.context["lignes"]], [HC.empreinte(PIEGE)])
        HistoriqueConnexion.objects.filter(utilisateur_id=self.contrib.pk).update(date=timezone.now() - datetime.timedelta(days=3))
        rep = c.get(URL_ADMIN, {"periode": "1"})
        self.assertNotIn(self.contrib.pk, [x.utilisateur_id for x in rep.context["lignes"]])
        self.assertEqual(c.get(URL_ADMIN, {"periode": "999"}).context["periode"], "")  # valeur inconnue : ignorée
        with E.activer("essai"):
            rep = self.client_de(self.achats, "essai").get(f"/espace/essai{URL_ADMIN}")
        self.assertEqual(rep.status_code, 403)  # contributeur d'« essai »

    def test_lien_depuis_comptes(self):
        self.assertContains(self.client_de(self.admin).get("/administration/comptes/"), URL_ADMIN)


class MonCompteTests(Base):
    def test_mes_connexions_seulement(self):
        se_connecter("contrib@exemple.example", "mauvais")
        se_connecter("contrib@exemple.example")
        se_connecter("lecteur@exemple.example")
        rep = self.client_de(self.contrib).get("/mon-compte/")
        self.assertEqual([x.resultat for x in rep.context["connexions"]], ["reussie", "echec"])
        rep = self.client_de(self.auditeur).get("/mon-compte/")
        self.assertEqual(rep.context["connexions"], [])
        self.assertContains(rep, 'id="mes-connexions"')


class ConservationTests(Base):
    def test_duree_reglee_ecran_et_menage_de_la_nuit(self):
        se_connecter("contrib@exemple.example")
        se_connecter("lecteur@exemple.example")
        HistoriqueConnexion.objects.filter(utilisateur_id=self.contrib.pk).update(date=timezone.now() - datetime.timedelta(days=200))
        rep = self.client_de(self.admin).get(URL_ADMIN)
        self.assertEqual([x.utilisateur_id for x in rep.context["lignes"]], [self.lecteur.pk])  # 180 jours par défaut
        CD.menage_nocturne([E.PRINCIPAL])
        self.assertEqual([u for u, _, _ in lignes()], [self.lecteur.pk])

    def test_reglage_dans_hebergement(self):
        c = self.client_de(self.admin)
        rep = c.post("/administration/parametres/hebergement/", {"action": "reglage_connexions", "connexions_jours": "30"})
        self.assertEqual(rep.status_code, 302)
        self.assertEqual(Instance.courante().connexions_jours, 30)
        self.assertTrue(Journal.objects.filter(action="reglage_connexions", avant="180", apres="30").exists())
        for valeur in ("0", "731", "abc"):
            rep = c.post("/administration/parametres/hebergement/", {"action": "reglage_connexions", "connexions_jours": valeur})
            self.assertEqual(rep.status_code, 200, valeur)
        self.assertEqual(Instance.courante().connexions_jours, 30)
        rep = self.client_de(self.lecteur).post("/administration/parametres/hebergement/",
                                                {"action": "reglage_connexions", "connexions_jours": "5"})
        self.assertEqual(rep.status_code, 403)
        self.assertEqual(Instance.courante().connexions_jours, 30)

    def test_page_de_confidentialite(self):
        rep = Client().get("/confidentialite/")
        self.assertEqual(rep.status_code, 200)
        self.assertTrue(any(cle == "historique_connexions" for cle, *_ in rep.context["lignes"]))
