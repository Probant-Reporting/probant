"""Gestionnaire des espaces vu et donné depuis Administration › Comptes (liste et fiche d'un compte), avec la même règle
que la page Espaces › Personnes et accès : une seule écriture (``comptes.changer_gestionnaire``).

- Nommer ou retirer : seulement un gestionnaire des espaces actif ; tout autre rôle (administrateur non gestionnaire, de
  l'espace principal ou d'un autre espace, validateur, contributeur, lecteur, auditeur) : refusé, GET comme POST direct.
- Garde-fous : on ne se retire pas le rôle à soi-même (il reste donc toujours un gestionnaire actif : celui qui agit) ;
  l'acteur est relu sous verrou au registre commun (un gestionnaire retiré entre-temps ne peut plus agir).
- Une ligne d'historique (« reglage_compte », champ « gestionnaire ») dans l'espace où l'on agit, depuis les deux pages.
- Liste des comptes : étiquette « Gestionnaire des espaces », visible de tout administrateur, trouvée par la recherche.
- Qui peut être nommé, perte du rôle, dernier gestionnaire : ``test_dernier_gestionnaire_portes.py``."""
from unittest import mock

from django.core.exceptions import PermissionDenied
from django.test import Client

from collecte.models import Journal
from parametres import libelles as LB
from parametres.libelles import libelle
from referentiel.models import Utilisateur

from . import comptes as EC
from . import contexte as E
from .aides_tests import creer
from .essais import EspacesTestCase
from .models import Compte

LISTE = "/administration/comptes/"
LANGUES = ("en", "fr", "es", "de", "it", "nl", "pt")
CLES = ("admin.compte.gestionnaire.titre", "admin.compte.gestionnaire.est", "admin.compte.gestionnaire.n_est_pas",
        "admin.compte.gestionnaire.admin", "admin.compte.gestionnaire.gestionnaire",
        "admin.compte.gestionnaire.restauration", "admin.compte.gestionnaire.nommer",
        "admin.compte.gestionnaire.nommer_confirmer", "admin.compte.gestionnaire.retirer",
        "admin.compte.gestionnaire.reserve", "admin.compte.gestionnaire.vous", "admin.journal.champ.gestionnaire")


def fiche(u, espace=""):
    return f"{'/espace/' + espace if espace else ''}/administration/comptes/{u.pk}/"


def gestionnaire(u):
    return Compte.objects.get(pk=u.pk).gestionnaire


def copie(u, espace="principal"):
    with E.activer(espace):
        return Utilisateur.objects.get(pk=u.pk)


def lignes(espace="principal"):
    with E.activer(espace):
        return list(Journal.objects.filter(action="reglage_compte", champ="gestionnaire")
                    .values_list("utilisateur_id", "objet", "objet_id", "avant", "apres"))


class Base(EspacesTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.gestion = creer("gestion@exemple.example", "admin", last_name="Gestion")  # premier administrateur : gestionnaire
        cls.admin = creer("admin@exemple.example", "admin", last_name="Admin")
        cls.validateur = creer("valid@exemple.example", "validateur")
        cls.contrib = creer("contrib@exemple.example", "contributeur")
        cls.lecteur = creer("lecteur@exemple.example", "lecteur")
        cls.auditeur = creer("auditeur@exemple.example", "auditeur")
        cls.admin_essai = creer("admin.essai@exemple.example", "admin", "essai")
        creer("gestion@exemple.example", "contributeur", "essai")  # copie du gestionnaire dans « essai »

    def connecter(self, u, espace="principal"):
        c = Client()
        c.force_login(copie(u, espace))
        return c

    def poster(self, client, cible, valeur, espace="", **kw):
        return client.post(fiche(cible, espace), {"action": "gestionnaire", "valeur": valeur}, **kw)


class DroitsTests(Base):
    def test_reglage_de_depart(self):
        self.assertTrue(gestionnaire(self.gestion))
        self.assertFalse(gestionnaire(self.admin))

    def test_gestionnaire_nomme_puis_retire_avec_historique(self):
        c = self.connecter(self.gestion)
        r = c.get(fiche(self.admin))
        self.assertContains(r, 'name="action" value="gestionnaire"')
        self.assertContains(r, libelle("admin.compte.gestionnaire.nommer"))
        rep = self.poster(c, self.admin, "1")
        self.assertEqual(rep.status_code, 302)
        self.assertTrue(gestionnaire(self.admin))
        self.assertContains(c.get(fiche(self.admin)), libelle("admin.compte.gestionnaire.retirer"))
        self.poster(c, self.admin, "0")
        self.assertFalse(gestionnaire(self.admin))
        self.assertEqual(lignes(), [(self.gestion.pk, "Utilisateur", str(self.admin.pk), "True", "False"),
                                    (self.gestion.pk, "Utilisateur", str(self.admin.pk), "False", "True")])
        # page Historique : champ et compte lisibles
        from collecte.administration import libeller_journal

        entrees = list(Journal.objects.filter(champ="gestionnaire"))
        libeller_journal(entrees)
        self.assertEqual({(e.libelle_champ, e.libelle_objet) for e in entrees},
                         {(libelle("admin.journal.champ.gestionnaire"), str(copie(self.admin)))})

    def test_reponse_du_panneau_apres_nomination(self):
        """Fiche ouverte en panneau (envoi par script) : le panneau revient avec le message, pas une redirection."""
        c = self.connecter(self.gestion)
        rep = self.poster(c, self.admin, "1", HTTP_X_REQUESTED_WITH="fetch")
        self.assertEqual(rep.status_code, 200)
        self.assertContains(rep, libelle("espaces.personnes.nomme", nom=Compte.objects.get(pk=self.admin.pk)))

    def test_administrateur_non_gestionnaire_voit_sans_pouvoir_agir(self):
        c = self.connecter(self.admin)
        r = c.get(fiche(self.gestion))
        self.assertContains(r, libelle("admin.compte.gestionnaire.est", nom=copie(self.gestion)))
        self.assertContains(r, libelle("admin.compte.gestionnaire.gestionnaire"))
        self.assertContains(r, libelle("admin.compte.gestionnaire.reserve"))
        self.assertNotContains(r, 'value="gestionnaire"')
        for cible, valeur in ((self.gestion, "0"), (self.admin, "1"), (self.contrib, "1")):
            self.assertEqual(self.poster(c, cible, valeur).status_code, 403)
        self.assertTrue(gestionnaire(self.gestion))
        self.assertFalse(gestionnaire(self.admin) or gestionnaire(self.contrib))
        self.assertEqual(lignes(), [])

    def test_administrateur_d_un_autre_espace_refuse(self):
        c = self.connecter(self.admin_essai, "essai")
        r = c.get(fiche(self.gestion, "essai"))
        self.assertContains(r, libelle("admin.compte.gestionnaire.est", nom=copie(self.gestion, "essai")))
        self.assertNotContains(r, 'value="gestionnaire"')
        self.assertEqual(self.poster(c, self.gestion, "0", "essai").status_code, 403)
        self.assertEqual(self.poster(c, self.admin_essai, "1", "essai").status_code, 403)
        self.assertTrue(gestionnaire(self.gestion))
        self.assertFalse(gestionnaire(self.admin_essai))
        # compte sans copie dans cet espace : fiche introuvable (comme avant)
        self.assertEqual(c.get(fiche(self.admin, "essai")).status_code, 404)

    def test_autres_roles_refuses(self):
        for u in (self.validateur, self.contrib, self.lecteur, self.auditeur):
            c = self.connecter(u)
            self.assertEqual(c.get(fiche(self.admin)).status_code, 403, u.role)
            self.assertEqual(c.get(LISTE).status_code, 403, u.role)
            self.assertEqual(self.poster(c, self.admin, "1").status_code, 403, u.role)
            self.assertEqual(self.poster(c, self.gestion, "0").status_code, 403, u.role)
        self.assertTrue(gestionnaire(self.gestion))
        self.assertFalse(gestionnaire(self.admin))
        self.assertEqual(lignes(), [])

    def test_gestionnaire_qui_agit_depuis_un_autre_espace(self):
        """Le rôle vaut pour toute l'installation : un gestionnaire administrateur d'un autre espace y agit aussi ; la
        ligne d'historique va dans l'espace où il agit."""
        Compte.objects.filter(pk=self.admin_essai.pk).update(gestionnaire=True)
        c = self.connecter(self.admin_essai, "essai")
        self.assertContains(c.get(fiche(self.gestion, "essai")), libelle("admin.compte.gestionnaire.retirer"))
        self.assertEqual(self.poster(c, self.gestion, "0", "essai").status_code, 302)
        self.assertFalse(gestionnaire(self.gestion))
        self.assertEqual(lignes("essai"), [(self.admin_essai.pk, "Utilisateur", str(self.gestion.pk), "True", "False")])
        self.assertEqual(lignes(), [])


class GardeFousTests(Base):
    def test_pas_soi_meme(self):
        """Le seul gestionnaire ne se retire pas son rôle : jamais d'installation sans gestionnaire actif."""
        c = self.connecter(self.gestion)
        r = c.get(fiche(self.gestion))
        self.assertContains(r, libelle("admin.compte.gestionnaire.vous"))
        self.assertNotContains(r, 'value="gestionnaire"')
        rep = self.poster(c, self.gestion, "0", HTTP_X_REQUESTED_WITH="fetch")
        self.assertContains(rep, libelle("espaces.erreur.soi_meme"))
        self.assertTrue(gestionnaire(self.gestion))
        self.assertEqual(lignes(), [])

    def test_acteur_relu_sous_verrou(self):
        """Deux gestionnaires qui se retirent l'un l'autre au même instant : le second, déjà retiré quand il écrit,
        est refusé (relu au registre dans la transaction, pas d'après la page ouverte)."""
        Compte.objects.filter(pk=self.admin.pk).update(gestionnaire=True)
        gestion, admin = copie(self.gestion), copie(self.admin)
        self.assertEqual(EC.changer_gestionnaire(gestion, admin.pk, False)[0], True)
        with mock.patch.object(EC, "est_gestionnaire", return_value=True):  # la page a été ouverte avant le retrait
            with self.assertRaises(PermissionDenied):
                EC.changer_gestionnaire(admin, gestion.pk, False)
        self.assertTrue(gestionnaire(self.gestion))
        self.assertFalse(gestionnaire(self.admin))

    def test_compte_introuvable_et_numero_illisible(self):
        gestion = copie(self.gestion)
        self.assertEqual(EC.changer_gestionnaire(gestion, 999999, True), (False, libelle("espaces.erreur.compte_introuvable")))
        c = self.connecter(self.gestion)
        rep = c.post("/administration/espaces/", {"action": "gestionnaire", "compte": "x²", "valeur": "1"})
        self.assertEqual(rep.status_code, 302)  # avant : erreur 500 (numéro non numérique)

    def test_deja_dans_cet_etat_sans_ligne(self):
        gestion = copie(self.gestion)
        self.assertEqual(EC.changer_gestionnaire(gestion, self.admin.pk, False)[0], True)
        self.assertEqual(lignes(), [])

    # personne nommée (administrateur actif de l'espace principal), perte du rôle et dernier gestionnaire :
    # espaces/test_dernier_gestionnaire_portes.py


class PageEspacesTests(Base):
    def test_meme_fonction_et_meme_ligne(self):
        c = self.connecter(self.gestion)
        with mock.patch.object(EC, "changer_gestionnaire", wraps=EC.changer_gestionnaire) as espion:
            c.post("/administration/espaces/", {"action": "gestionnaire", "compte": self.admin.pk, "valeur": "1"})
            self.poster(c, self.admin, "0")
        self.assertEqual(espion.call_count, 2)
        self.assertEqual(lignes(), [(self.gestion.pk, "Utilisateur", str(self.admin.pk), "True", "False"),
                                    (self.gestion.pk, "Utilisateur", str(self.admin.pk), "False", "True")])


class ListeTests(Base):
    def test_etiquette_dans_la_liste(self):
        etiquette = libelle("espaces.personnes.gestionnaire")
        for u in (self.gestion, self.admin):  # tout administrateur qui voit la page
            html = self.connecter(u).get(LISTE).content.decode()
            ligne = html[html.index(f'data-url="{fiche(self.gestion)}"'):]
            ligne = ligne[:ligne.index("</tr>")]
            self.assertIn(etiquette, ligne)
            self.assertIn(etiquette.lower(), ligne[ligne.index("data-texte"):].split('"')[1])  # trouvée par la recherche
            autre = html[html.index(f'data-url="{fiche(self.admin)}"'):]
            self.assertNotIn(etiquette, autre[:autre.index("</tr>")])
        self.assertEqual(html.count(f'class="badge-partage gestionnaire-espaces">{etiquette}'), 1)

    def test_etiquette_dans_la_liste_d_un_autre_espace(self):
        html = self.connecter(self.admin_essai, "essai").get("/espace/essai" + LISTE).content.decode()
        self.assertEqual(html.count(libelle("espaces.personnes.gestionnaire")), 1)


class TextesTests(Base):
    def test_textes_dans_les_sept_langues(self):
        for langue in LANGUES:
            for cle in CLES:
                self.assertTrue(LB.table(langue).get(cle), f"{cle} ({langue})")  # dans la langue même, sans repli
