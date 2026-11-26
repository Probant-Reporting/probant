"""Règles des gestionnaires des espaces, version 1.1.1 (``comptes.simuler`` / ``comptes.appliquer``), porte par
porte :

1. seul un administrateur actif de l'espace principal peut être nommé (fiche d'un compte et page Espaces) ;
2. jamais d'installation sans gestionnaire capable d'agir : désactiver, rétrograder, supprimer ou bloquer le dernier,
   ou archiver l'espace de sa seule copie active, est refusé avec un message, par toutes les portes ;
3. un gestionnaire qui n'est plus administrateur actif de l'espace principal perd le rôle (ligne d'historique), annoncé
   et confirmé dans la fiche avant l'enregistrement ; un gestionnaire d'avant la règle le garde tant qu'on ne touche
   ni à sa copie de l'espace principal ni à sa connexion."""
from django.test import Client

from collecte.models import Journal
from parametres import libelles as LB
from parametres.libelles import libelle
from referentiel.models import Utilisateur

from . import comptes as EC
from . import contexte as E
from .aides_tests import creer
from .essais import EspacesTestCase
from .models import Compte, Espace
from .test_changer_gestionnaire_fiche_compte import LANGUES, copie, fiche, gestionnaire, lignes

ESPACES = "/administration/espaces/"
CLES = ("espaces.erreur.dernier_gestionnaire", "espaces.erreur.archive_dernier_gestionnaire",
        "espaces.erreur.pas_admin_principal", "admin.compte.gestionnaire.perte_confirmer_requis",
        "admin.compte.gestionnaire.perte_case", "admin.compte.gestionnaire.perte_aide",
        "admin.compte.gestionnaire.perte_faite", "admin.compte.gestionnaire.ancien",
        "admin.compte.gestionnaire.pas_eligible")


def texte(rep):
    """Texte lisible d'une réponse (page, ou panneau en JSON) : balises retirées (l'encart met sa première phrase en
    gras), entités décodées, espaces réduits."""
    import html
    import json
    import re

    contenu = rep.content.decode()
    if rep.get("Content-Type", "").startswith("application/json"):
        contenu = json.loads(contenu).get("html", "")
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", contenu)))


class Base(EspacesTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.g1 = creer("g1@exemple.example", "admin", last_name="Un")  # premier administrateur : gestionnaire
        cls.admin = creer("admin@exemple.example", "admin", last_name="Admin")
        cls.validateur = creer("valid@exemple.example", "validateur")
        cls.contrib = creer("contrib@exemple.example", "contributeur")
        cls.lecteur = creer("lecteur@exemple.example", "lecteur")
        cls.auditeur = creer("auditeur@exemple.example", "auditeur")
        cls.inactif = creer("inactif@exemple.example", "admin", is_active=False)
        cls.admin_essai = creer("admin.essai@exemple.example", "admin", "essai")

    def connecter(self, u, espace="principal"):
        c = Client()
        c.force_login(copie(u, espace))
        return c

    def deuxieme(self):
        """Un second gestionnaire (administrateur actif de l'espace principal), nommé par g1."""
        self.assertTrue(EC.changer_gestionnaire(copie(self.g1), self.admin.pk, True)[0])
        Journal.objects.all().delete()

    def corps(self, u, **changes):
        x = copie(u)
        return {"action": "enregistrer", "first_name": x.first_name, "last_name": x.last_name or "Nom", "email": x.email,
                "role": "admin" if x.est_admin else x.role, "is_active": "on", **changes}

    def enregistrer(self, client, u, espace="", fetch=True, **changes):
        corps = self.corps(u, **changes)
        if corps.get("is_active") is None:
            corps.pop("is_active")
        entetes = {"HTTP_X_REQUESTED_WITH": "fetch"} if fetch else {}
        return client.post(fiche(u, espace), corps, **entetes)


class Regle1NommerTests(Base):
    def test_seul_un_administrateur_actif_de_l_espace_principal(self):
        c = self.connecter(self.g1)
        for u in (self.validateur, self.contrib, self.lecteur, self.auditeur, self.inactif):
            rep = c.post(fiche(u), {"action": "gestionnaire", "valeur": "1"}, HTTP_X_REQUESTED_WITH="fetch")
            self.assertIn(libelle("espaces.erreur.pas_admin_principal", nom=Compte.objects.get(pk=u.pk)), texte(rep))
            self.assertFalse(gestionnaire(u), u.email)
        self.assertEqual(lignes(), [])
        self.assertEqual(c.post(fiche(self.admin), {"action": "gestionnaire", "valeur": "1"}).status_code, 302)
        self.assertTrue(gestionnaire(self.admin))

    def test_page_espaces_meme_regle_et_bouton_cache(self):
        c = self.connecter(self.g1)
        rep = c.post(ESPACES, {"action": "gestionnaire", "compte": self.contrib.pk, "valeur": "1"}, follow=True)
        self.assertIn(libelle("espaces.erreur.pas_admin_principal", nom=Compte.objects.get(pk=self.contrib.pk)),
                      [str(m) for m in rep.context["messages"]])
        self.assertFalse(gestionnaire(self.contrib))
        html = c.get(ESPACES).content.decode()
        self.assertIn(libelle("espaces.personnes.nommer", nom=self.admin.email), html)
        self.assertNotIn(libelle("espaces.personnes.nommer", nom=self.contrib.email), html)
        self.assertNotIn(libelle("espaces.personnes.nommer", nom=self.admin_essai.email), html)

    def test_administrateur_d_un_espace_secondaire_seulement(self):
        """Même définition que ``doit_devenir_gestionnaire`` : l'administrateur d'un autre espace (contributeur ou
        absent de l'espace principal) ne prend pas la main sur toute l'installation."""
        self.assertFalse(EC.changer_gestionnaire(copie(self.g1), self.admin_essai.pk, True)[0])
        self.assertFalse(gestionnaire(self.admin_essai))
        creer("g1@exemple.example", "admin", "essai")
        r = self.connecter(self.g1, "essai").get("/espace/essai" + fiche(self.admin_essai))
        self.assertIn(libelle("admin.compte.gestionnaire.pas_eligible"), texte(r))
        self.assertNotContains(r, 'value="gestionnaire"')


class Regle2DernierTests(Base):
    """g1 est le seul gestionnaire capable d'agir ; l'administrateur ``admin`` essaie de le retirer par chaque porte."""

    def refus(self):
        return libelle("espaces.erreur.dernier_gestionnaire", nom=Compte.objects.get(pk=self.g1.pk))

    def resteg1(self):
        g = copie(self.g1)
        self.assertTrue(g.is_active and g.est_admin and gestionnaire(self.g1) and Compte.objects.get(pk=self.g1.pk).actif)

    def test_fiche_desactiver_retrograder_lecture_seule(self):
        c = self.connecter(self.admin)
        for changes in ({"is_active": None}, {"role": "contributeur"}, {"role": "validateur"}, {"role": "lecteur"},
                        {"role": "auditeur"}):
            rep = self.enregistrer(c, self.g1, **changes)
            self.assertIn(self.refus(), texte(rep), str(changes))
            self.resteg1()
        self.assertEqual(lignes(), [])

    def test_fiche_supprimer(self):
        c = self.connecter(self.admin)
        rep = c.post(fiche(self.g1), {"action": "supprimer"}, HTTP_X_REQUESTED_WITH="fetch")
        self.assertIn(self.refus(), texte(rep))
        self.assertTrue(Utilisateur.objects.filter(pk=self.g1.pk).exists())
        self.assertFalse(Journal.objects.filter(action="suppression_compte").exists())

    def test_remplacer_une_personne_et_desactiver(self):
        c = self.connecter(self.admin)
        rep = c.post("/administration/attributions/remplacer/", {"de": self.g1.pk, "par": self.contrib.pk, "desactiver": "on"},
                     HTTP_X_REQUESTED_WITH="fetch")
        self.assertIn(self.refus(), texte(rep))
        self.resteg1()
        self.assertFalse(Journal.objects.filter(action="remplacement_personne").exists())  # tout ou rien

    def test_toute_copie_enregistree(self):
        """Toute autre porte qui enregistre la copie (commande, code) : refus par le signal."""
        g = copie(self.g1)
        g.is_active = False
        with self.assertRaises(EC.DernierGestionnaire):
            g.save(update_fields=["is_active"])
        self.resteg1()

    def test_bloquer_et_archiver(self):
        """Page Espaces : bloquer la connexion (registre commun) ou archiver l'espace de la seule copie active du
        dernier gestionnaire capable d'agir. Par la page, celui qui agit est un gestionnaire capable d'agir qui ne
        peut se bloquer : la règle se vérifie sur la fonction, et l'archivage sur un gestionnaire d'avant la règle
        dont la seule copie active est dans « essai »."""
        with self.assertRaises(EC.DernierGestionnaire):
            EC.appliquer(self.g1.pk, compte_actif=False, ecrire=lambda: Compte.objects.filter(pk=self.g1.pk).update(actif=False))
        self.resteg1()
        ancien = creer("ancien@exemple.example", "contributeur", "essai")
        Compte.objects.filter(pk=ancien.pk).update(gestionnaire=True)
        Compte.objects.filter(pk=self.g1.pk).update(gestionnaire=False)
        with self.assertRaises(EC.DernierGestionnaire) as x:
            EC.appliquer(None, archive="essai", ecrire=lambda: Espace.objects.filter(code="essai").update(etat="archive"))
        self.assertEqual(x.exception.message, libelle("espaces.erreur.archive_dernier_gestionnaire"))
        self.assertEqual(Espace.objects.get(code="essai").etat, "actif")
        Compte.objects.filter(pk=self.g1.pk).update(gestionnaire=True)
        c = self.connecter(self.g1)
        c.post(ESPACES, {"code": "essai", "action": "archiver"})
        self.assertEqual(Espace.objects.get(code="essai").etat, "archive")  # un autre gestionnaire reste

    def test_page_espaces_bloquer_refuse_par_la_page(self):
        """Gestionnaire d'avant la règle, seul capable d'agir, qui agit depuis « essai » sur g1 bloqué d'avance : la page
        refuse de bloquer le dernier (message), rien n'est écrit."""
        ancien = creer("ancien@exemple.example", "admin", "essai")
        Compte.objects.filter(pk=ancien.pk).update(gestionnaire=True)
        Compte.objects.filter(pk=self.g1.pk).update(gestionnaire=False)
        c = self.connecter(ancien, "essai")
        # l'ancien ne peut se bloquer lui-même (règle « soi-même »), et il est le dernier : la fonction le protège aussi
        self.assertEqual(EC.simuler(ancien.pk, compte_actif=False)[0],
                         libelle("espaces.erreur.dernier_gestionnaire", nom=Compte.objects.get(pk=ancien.pk)))
        rep = c.post("/espace/essai" + ESPACES, {"action": "bloquer", "compte": ancien.pk, "valeur": "1"}, follow=True)
        self.assertTrue(Compte.objects.get(pk=ancien.pk).actif)
        self.assertTrue(rep.context["messages"])

    def test_commande_de_l_it_permise_avec_un_avertissement(self):
        """Ligne de commande (IT, secours) : retirer le dernier gestionnaire reste permis ; la commande le dit."""
        from io import StringIO

        from django.core.management import call_command

        sortie = StringIO()
        call_command("espaces", "--remove-manager", self.g1.email, stdout=sortie)
        self.assertFalse(gestionnaire(self.g1))
        self.assertIn("Warning: no space manager can act now", sortie.getvalue())
        call_command("espaces", "--manager", self.g1.email, stdout=StringIO())
        self.assertTrue(gestionnaire(self.g1))

    def test_creation_de_comptes_sans_effet(self):
        """« Plusieurs comptes » et la fiche d'un nouveau compte ne font que créer : aucun gestionnaire n'est retiré."""
        c = self.connecter(self.admin)
        rep = c.post("/administration/comptes/plusieurs/", {
            "first_name_0": "Nina", "last_name_0": "Neuve", "email_0": "nina@exemple.example", "role_0": "lecteur"})
        self.assertIn(rep.status_code, (200, 302))
        self.resteg1()


class Regle3PerteTests(Base):
    def test_fiche_annonce_puis_retire_avec_historique(self):
        self.deuxieme()
        c = self.connecter(self.g1)
        rep = self.enregistrer(c, self.admin, role="contributeur")
        self.assertIn(libelle("admin.compte.gestionnaire.perte_confirmer_requis", nom=copie(self.admin)), texte(rep))
        self.assertIn("confirmer_gestionnaire", rep.content.decode())
        self.assertTrue(gestionnaire(self.admin))
        self.assertEqual(copie(self.admin).role, "admin")
        rep = self.enregistrer(c, self.admin, role="contributeur", confirmer_gestionnaire="on")
        self.assertIn(libelle("admin.compte.gestionnaire.perte_faite", nom=copie(self.admin)), texte(rep))
        self.assertFalse(gestionnaire(self.admin))
        self.assertEqual(copie(self.admin).role, "contributeur")
        self.assertEqual(lignes(), [(self.g1.pk, "Utilisateur", str(self.admin.pk), "True", "False")])

    def test_fiche_desactivation_confirmee(self):
        self.deuxieme()
        c = self.connecter(self.g1)
        self.enregistrer(c, self.admin, is_active=None)
        self.assertTrue(gestionnaire(self.admin) and copie(self.admin).is_active)
        self.enregistrer(c, self.admin, is_active=None, confirmer_gestionnaire="on")
        self.assertFalse(gestionnaire(self.admin) or copie(self.admin).is_active)

    def test_copie_d_un_autre_espace_sans_effet(self):
        self.deuxieme()
        creer("admin@exemple.example", "admin", "essai")
        u = copie(self.admin, "essai")
        with E.activer("essai"):
            u.role, u.is_superuser = "contributeur", False
            u.save()
        self.assertTrue(gestionnaire(self.admin))

    def test_remplacer_une_personne_et_bloquer(self):
        self.deuxieme()
        c = self.connecter(self.g1)
        c.post("/administration/attributions/remplacer/", {"de": self.admin.pk, "par": self.contrib.pk, "desactiver": "on"})
        self.assertFalse(gestionnaire(self.admin))
        self.assertEqual(len(lignes()), 1)
        EC.changer_gestionnaire(copie(self.g1), self.admin.pk, True)  # refusé : désactivé
        self.assertFalse(gestionnaire(self.admin))
        autre = creer("autre@exemple.example", "admin")
        Compte.objects.filter(pk=autre.pk).update(gestionnaire=True)
        c.post(ESPACES, {"action": "bloquer", "compte": autre.pk, "valeur": "1"})
        self.assertFalse(Compte.objects.get(pk=autre.pk).actif)
        self.assertFalse(gestionnaire(autre))

    def test_gestionnaire_d_avant_la_regle(self):
        """Gestionnaire contributeur d'avant la règle : il garde le rôle, la fiche le dit ; un changement sans rapport
        (équipe) ne change rien ; un changement de rôle le lui retire, après confirmation."""
        # nom complet d'abord : l'identité d'un gestionnaire n'est modifiable que par un gestionnaire (champs grisés)
        Utilisateur.objects.filter(pk=self.contrib.pk).update(last_name="Contrib")
        Compte.objects.filter(pk=self.contrib.pk).update(gestionnaire=True, last_name="Contrib")
        c = self.connecter(self.admin)
        r = c.get(fiche(self.contrib))
        self.assertIn(libelle("admin.compte.gestionnaire.ancien", nom=copie(self.contrib)), texte(r))
        self.assertIn(libelle("espaces.personnes.gestionnaire"), texte(r))
        rep = self.enregistrer(c, self.contrib, fetch=False, equipe="Achats")
        self.assertEqual(rep.status_code, 302, rep.context and rep.context.get("form") and rep.context["form"].errors.as_text())
        self.assertTrue(gestionnaire(self.contrib))
        self.enregistrer(c, self.contrib, role="validateur")
        self.assertTrue(gestionnaire(self.contrib))
        self.enregistrer(c, self.contrib, role="validateur", confirmer_gestionnaire="on")
        self.assertFalse(gestionnaire(self.contrib))


class TextesTests(Base):
    def test_textes_dans_les_sept_langues(self):
        for langue in LANGUES:
            for cle in CLES:
                self.assertTrue(LB.table(langue).get(cle), f"{cle} ({langue})")
