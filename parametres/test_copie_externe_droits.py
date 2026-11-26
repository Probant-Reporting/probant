"""Qui règle la copie externe (Paramètres › Hébergement › Copie externe) : un réglage de l'INSTALLATION, au registre
commun, modifiable seulement par un gestionnaire des espaces (``espaces.comptes.est_gestionnaire`` ; ici le premier
administrateur de l'espace principal, devenu gestionnaire ; un administrateur de l'espace principal qui ne l'est pas :
``test_est_gestionnaire_reglages_installation``). L'administrateur d'un autre espace voit l'état, sans le serveur ni le
compartiment, et chacun de ses envois est refusé ; lecteur, auditeur, contributeur et validateur : refusés partout,
rien n'est écrit. La table n'existe qu'au registre commun."""
from django.db import connections

from espaces.aides_tests import creer
from espaces.essais import EspacesTestCase
from espaces.models import Compte, DestinationCopie
from parametres.aides_tests.copie import SANS_PROXY
from parametres.test_detail_installation_permis import connecter

URL = "/administration/parametres/hebergement/copie-externe/"
S3 = {"action": "enregistrer", "genre": "s3", "adresse": "https://stockage.exemple.test", "region": "", "compartiment": "sauvegardes",
      "chemin": "probant", "style": "auto", "identifiant": "CLE-ACCES", "secret": "Secret-balayage-9", "conserver": "0"}
ACTIONS = ("enregistrer", "effacer_secrets", "retirer", "essayer", "confirmer_cle")


@SANS_PROXY
class DroitsTests(EspacesTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.admin = creer("admin@exemple.example", "admin")
        cls.admin_essai = creer("admin.essai@exemple.example", "admin", "essai")
        cls.autres = {r: creer(f"{r}@exemple.example", r) for r in ("lecteur", "auditeur", "contributeur", "validateur")}

    def test_gestionnaire_de_l_espace_principal_regle(self):
        c = connecter(self.admin)
        page = c.get(URL + "?type=s3").content.decode()
        self.assertIn('name="adresse"', page)
        self.assertIn('autocomplete="new-password"', page)
        rep = c.post(URL, S3)
        self.assertEqual(rep.status_code, 302)
        d = DestinationCopie.objects.get()
        self.assertEqual((d.genre, d.adresse, d.compartiment, d.chemin), ("s3", "https://stockage.exemple.test", "sauvegardes", "probant"))
        self.assertTrue(d.secret_chiffre.startswith("v1$"))

    def test_administrateur_d_un_autre_espace_lecture_seule(self):
        connecter(self.admin).post(URL, S3)
        c = connecter(self.admin_essai, "essai")
        page = c.get(f"/espace/essai{URL}")
        self.assertEqual(page.status_code, 200)
        texte = page.content.decode()
        self.assertNotIn('name="adresse"', texte)
        self.assertNotIn("stockage.exemple.test", texte)  # détail de l'installation : ni le serveur ni le compartiment
        self.assertIn("Seul un gestionnaire des espaces peut la modifier", texte)
        avant = list(DestinationCopie.objects.values())
        for action in ACTIONS:
            self.assertEqual(c.post(f"/espace/essai{URL}", {**S3, "action": action}).status_code, 403, action)
        self.assertEqual(list(DestinationCopie.objects.values()), avant)

    def test_gestionnaire_des_espaces_depuis_un_autre_espace(self):
        Compte.objects.filter(pk=self.admin_essai.pk).update(gestionnaire=True)
        c = connecter(self.admin_essai, "essai")
        self.assertIn('name="adresse"', c.get(f"/espace/essai{URL}?type=s3").content.decode())
        self.assertEqual(c.post(f"/espace/essai{URL}", S3).status_code, 302)
        self.assertEqual(DestinationCopie.objects.get().genre, "s3")

    def test_lecture_seule_et_autres_roles_refuses(self):
        for role, u in self.autres.items():
            c = connecter(u)
            self.assertEqual(c.get(URL).status_code, 403, role)
            for action in ACTIONS:
                self.assertEqual(c.post(URL, {**S3, "action": action}).status_code, 403, f"{role} {action}")
        self.assertFalse(DestinationCopie.objects.exists())

    def test_rien_dans_les_bases_des_espaces(self):
        tables = {alias: connections[alias].introspection.table_names() for alias in ("default", "commun", "espace_essai")}
        for table in ("espaces_destinationcopie", "espaces_etatcopie"):
            self.assertIn(table, tables["commun"])
            self.assertNotIn(table, tables["default"])
            self.assertNotIn(table, tables["espace_essai"])
