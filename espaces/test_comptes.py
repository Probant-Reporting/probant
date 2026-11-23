"""Comptes communs : numéro unique, rattachement par e-mail, propagation, connexion, page « pas d'accès », et la règle
contre l'élévation de droits entre espaces (l'administrateur d'un espace ne prend pas la main sur le compte d'une
personne qui sert aussi dans un espace où il n'est pas administrateur)."""
from django.core.exceptions import PermissionDenied
from django.test import Client

from referentiel.models import Utilisateur

from . import contexte as E
from .essais import EspacesTestCase
from .models import AccesEspace, Compte
from .aides_tests import MDP, creer


class Base(EspacesTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # premier administrateur de l'espace principal : gestionnaire des espaces (un contributeur ne le devient jamais)
        cls.premier = creer("premier@exemple.example", "admin")
        cls.rse = creer("admin.rse@exemple.example", "admin")  # administrateur de l'espace principal
        cls.copie_rse = creer("Admin.RSE@exemple.example", "contributeur", "essai")  # … et contributeur de « essai »
        cls.achats = creer("admin.achats@exemple.example", "admin", "essai")  # administrateur de « essai » seulement
        cls.acheteur = creer("acheteur@exemple.example", "contributeur", "essai")  # « essai » seulement


class NumerosTests(Base):
    def test_numero_unique_et_rattachement_sans_majuscules(self):
        self.assertEqual(self.copie_rse.pk, self.rse.pk)
        self.assertTrue(self.copie_rse._espaces_rattache)
        self.assertEqual(self.copie_rse.email, "admin.rse@exemple.example")  # champs communs repris du registre
        self.assertTrue(Compte.objects.get(pk=self.premier.pk).gestionnaire)
        self.assertFalse(Compte.objects.get(pk=self.rse.pk).gestionnaire)
        numeros = {self.premier.pk, self.rse.pk, self.achats.pk, self.acheteur.pk}
        self.assertEqual(len(numeros), 4)
        self.assertEqual(set(Compte.objects.values_list("pk", flat=True)), numeros)
        with E.activer("essai"):
            self.assertFalse(Utilisateur.objects.filter(pk=self.premier.pk).exists())

    def test_propagation_des_champs_communs_seulement(self):
        u = Utilisateur.objects.get(pk=self.rse.pk)
        u.first_name, u.equipe = "Adèle", "Direction"
        u.save()
        copie = Utilisateur.objects.using("espace_essai").get(pk=self.rse.pk)
        self.assertEqual(copie.first_name, "Adèle")
        self.assertEqual(copie.equipe, "")  # propre à l'espace
        self.assertEqual(copie.role, "contributeur")
        self.assertEqual(Compte.objects.get(pk=self.rse.pk).first_name, "Adèle")

    def test_mot_de_passe_propage(self):
        u = Utilisateur.objects.get(pk=self.rse.pk)
        u.set_password("Nouveau-mot-2026")
        u.save()
        self.assertTrue(Utilisateur.objects.using("espace_essai").get(pk=self.rse.pk).check_password("Nouveau-mot-2026"))

    def test_index_des_acces(self):
        self.assertEqual(set(AccesEspace.objects.filter(compte_id=self.rse.pk).values_list("espace__code", "role")),
                         {("principal", "admin"), ("essai", "contributeur")})
        with E.activer("essai"):
            u = Utilisateur.objects.get(pk=self.rse.pk)
            u.is_active = False
            u.save(update_fields=["is_active"])
        self.assertFalse(AccesEspace.objects.get(compte_id=self.rse.pk, espace__code="essai").actif)

    def test_suppression_du_dernier_acces(self):
        with E.activer("essai"):
            Utilisateur.objects.get(pk=self.rse.pk).delete()
        self.assertTrue(Compte.objects.filter(pk=self.rse.pk).exists())
        self.assertFalse(AccesEspace.objects.filter(compte_id=self.rse.pk, espace__code="essai").exists())
        with E.activer("essai"):
            Utilisateur.objects.get(pk=self.acheteur.pk).delete()
        self.assertFalse(Compte.objects.filter(pk=self.acheteur.pk).exists())

    def test_email_deja_pris_au_registre(self):
        from django.db import IntegrityError

        with E.activer("essai"):
            u = Utilisateur.objects.get(pk=self.acheteur.pk)
            u.email = "PREMIER@exemple.example"
            with self.assertRaises(IntegrityError):
                u.save()
        self.assertEqual(Compte.objects.get(pk=self.acheteur.pk).email, "acheteur@exemple.example")


class ConnexionTests(Base):
    def connecter(self, prefixe, email):
        c = Client()
        r = c.post(f"{prefixe}/connexion/", {"username": email, "password": MDP})
        return c, r

    def test_connexion_dans_l_espace_demande(self):
        c, r = self.connecter("/espace/essai", "admin.rse@exemple.example")
        self.assertRedirects(r, "/espace/essai/", fetch_redirect_response=False)
        self.assertEqual(c.get("/espace/essai/mon-compte/").status_code, 200)
        self.assertEqual(c.get("/mon-compte/").status_code, 200)  # session commune : connecté une seule fois
        self.assertEqual(Compte.objects.get(pk=self.rse.pk).dernier_espace, "essai")

    def test_langue_choisie_suit_la_personne_d_un_espace_a_l_autre(self):
        """La langue de l'interface (barre du haut) est un choix de la personne : elle vaut dans tous ses espaces."""
        c, _ = self.connecter("", "admin.rse@exemple.example")
        c.post("/langue/", {"langue": "en", "suivant": "/"})
        self.assertContains(c.get("/espace/essai/mon-compte/"), '<html lang="en"')
        c.post("/espace/essai/langue/", {"langue": "es", "suivant": "/espace/essai/"})
        self.assertContains(c.get("/mon-compte/"), '<html lang="es"')
        self.assertContains(c.get("/espace/essai/mon-compte/"), '<html lang="es"')

    def test_langue_du_compte_reprise_dans_les_autres_espaces(self):
        """Langue choisie lors d'une session précédente (gardée dans le compte, pas dans la session) : reprise à la
        connexion dans tous les espaces, page « pas d'accès » comprise ; un choix fait dans un espace est recopié
        dans les copies du compte des autres espaces."""
        Utilisateur.objects.filter(pk=self.rse.pk).update(langue="en")
        c, _ = self.connecter("", "admin.rse@exemple.example")
        self.assertContains(c.get("/mon-compte/"), '<html lang="en"')
        self.assertContains(c.get("/espace/essai/mon-compte/"), '<html lang="en"')
        c.post("/espace/essai/langue/", {"langue": "es", "suivant": "/espace/essai/"})
        self.assertEqual(Utilisateur.objects.get(pk=self.rse.pk).langue, "es")  # copie de l'espace principal
        Utilisateur.objects.filter(pk=self.premier.pk).update(langue="es")
        c, _ = self.connecter("", "premier@exemple.example")
        self.assertContains(c.get("/espace/essai/"), '<html lang="es"', status_code=403)

    def test_page_pas_d_acces_dans_la_langue_choisie(self):
        c = Client()
        c.force_login(Utilisateur.objects.get(pk=self.premier.pk))
        c.post("/langue/", {"langue": "en", "suivant": "/"})
        r = c.get("/espace/essai/")
        self.assertContains(r, "You do not have access to the space “Achats”", status_code=403)
        r = c.get("/espace/essai/mon-compte/", headers={"X-Requested-With": "fetch"})
        self.assertEqual(r.json()["erreur"], "You do not have access to the space “Achats”")

    def test_arrivee_dans_l_espace_accessible(self):
        c, r = self.connecter("", "acheteur@exemple.example")
        self.assertRedirects(r, "/espace/essai/", fetch_redirect_response=False)
        r = c.get("/espace/essai/mon-compte/")
        self.assertContains(r, "vous voici dans l&#x27;espace « Achats »")

    def test_mauvais_mot_de_passe(self):
        r = Client().post("/connexion/", {"username": "acheteur@exemple.example", "password": "faux-mot-de-passe"})
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("_auth_user_id", r.client.session)

    def test_page_pas_d_acces(self):
        c = Client()
        c.force_login(Utilisateur.objects.get(pk=self.premier.pk))
        r = c.get("/espace/essai/")
        self.assertContains(r, "Vous n'avez pas accès à l'espace « Achats »", status_code=403)
        r = c.get("/espace/essai/mon-compte/", headers={"X-Requested-With": "fetch"})
        self.assertEqual(r.status_code, 403)
        self.assertFalse(r.json()["ok"])
        self.assertEqual(c.get("/mon-compte/").status_code, 200)

    def test_pas_d_acces_liste_mes_espaces(self):
        c = Client()
        with E.activer("essai"):
            c.force_login(Utilisateur.objects.get(pk=self.acheteur.pk))
        r = c.get("/")
        self.assertContains(r, 'href="/espace/essai/"', status_code=403)

    def test_identifiant_qui_ressemble_a_l_email_d_un_autre(self):
        """Un compte du registre dont l'identifiant est l'e-mail d'une autre personne (base restaurée) ne prend jamais
        sa place : l'e-mail est cherché d'abord."""
        from django.contrib.auth.hashers import make_password

        Compte.objects.create(pk=900, username="ADMIN.RSE@exemple.example", email="intrus@exemple.example",
                              password=make_password("Intrus-2026-xyz"))
        c, r = self.connecter("", "admin.rse@exemple.example")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(c.get("/mon-compte/").wsgi_request.user.pk, self.rse.pk)
        r = Client().post("/connexion/", {"username": "admin.rse@exemple.example", "password": "Intrus-2026-xyz"})
        self.assertEqual(r.status_code, 200)  # refusé : ce n'est pas le mot de passe de cette personne

    def test_copie_desactivee_dans_un_espace(self):
        with E.activer("essai"):
            Utilisateur.objects.filter(pk=self.rse.pk).update(is_active=False)
        c = Client()
        c.force_login(Utilisateur.objects.get(pk=self.rse.pk))
        self.assertEqual(c.get("/espace/essai/").status_code, 403)
        self.assertEqual(c.get("/mon-compte/").status_code, 200)

    def test_emails_differents_refuses(self):
        c = Client()
        c.force_login(Utilisateur.objects.get(pk=self.rse.pk))
        with E.activer("essai"):
            Utilisateur.objects.filter(pk=self.rse.pk).update(email="quelquun@exemple.example")
        with self.assertLogs("referentiel.connexion", "ERROR"):
            r = c.get("/espace/essai/mon-compte/")
        self.assertNotEqual(r.status_code, 200)

    def test_compte_inactif_au_registre(self):
        Compte.objects.filter(pk=self.rse.pk).update(actif=False)
        _, r = self.connecter("", "admin.rse@exemple.example")
        self.assertEqual(r.status_code, 200)  # formulaire réaffiché, message neutre
        self.assertNotIn("_auth_user_id", r.client.session)


class ElevationTests(Base):
    """Point de sécurité n° 1 : l'administrateur de « essai » ne peut ni réinitialiser le mot de passe ni changer
    l'e-mail de l'administrateur de l'espace principal."""

    def client_achats(self):
        c = Client()
        with E.activer("essai"):
            c.force_login(Utilisateur.objects.get(pk=self.achats.pk))
        return c

    def test_reinitialisation_refusee_par_l_ecran(self):
        c = self.client_achats()
        avant = Compte.objects.get(pk=self.rse.pk).password
        r = c.get(f"/espace/essai/administration/comptes/{self.rse.pk}/")
        self.assertContains(r, "Ce compte sert aussi dans")
        self.assertNotContains(r, 'value="reinitialiser"')
        r = c.post(f"/espace/essai/administration/comptes/{self.rse.pk}/", {"action": "reinitialiser"})
        self.assertEqual(Compte.objects.get(pk=self.rse.pk).password, avant)
        self.assertFalse(Compte.objects.get(pk=self.rse.pk).doit_changer_mdp)

    def test_email_force_par_un_post(self):
        c = self.client_achats()
        c.post(f"/espace/essai/administration/comptes/{self.rse.pk}/", {
            "action": "enregistrer", "first_name": "Pirate", "last_name": "X", "email": "pirate@exemple.example",
            "role": "contributeur", "is_active": "on", "equipe": ""})
        self.assertEqual(Compte.objects.get(pk=self.rse.pk).email, "admin.rse@exemple.example")
        self.assertEqual(Utilisateur.objects.get(pk=self.rse.pk).email, "admin.rse@exemple.example")
        self.assertNotEqual(Compte.objects.get(pk=self.rse.pk).first_name, "Pirate")

    def test_refus_a_l_enregistrement_quel_que_soit_le_chemin(self):
        with E.activer("essai"), E.acteur(self.achats.pk):
            u = Utilisateur.objects.get(pk=self.rse.pk)
            u.set_password("Pris-en-main-2026")
            with self.assertRaises(PermissionDenied):
                u.save()
            u = Utilisateur.objects.get(pk=self.rse.pk)
            u.doit_changer_mdp = True
            with self.assertRaises(PermissionDenied):
                u.save(update_fields=["doit_changer_mdp"])
        self.assertTrue(Utilisateur.objects.get(pk=self.rse.pk).check_password(MDP))

    def test_compte_de_son_seul_espace(self):
        c = self.client_achats()
        r = c.post(f"/espace/essai/administration/comptes/{self.acheteur.pk}/", {"action": "reinitialiser"})
        self.assertContains(r, "Mot de passe provisoire")
        self.assertTrue(Compte.objects.get(pk=self.acheteur.pk).doit_changer_mdp)

    def test_la_personne_elle_meme_et_le_gestionnaire(self):
        with E.activer("essai"), E.acteur(self.rse.pk):
            u = Utilisateur.objects.get(pk=self.rse.pk)
            u.first_name = "Moi"
            u.save()
        with E.activer("essai"), E.acteur(self.premier.pk):
            u = Utilisateur.objects.get(pk=self.rse.pk)
            u.first_name = "Gestion"
            u.save()
        self.assertEqual(Utilisateur.objects.get(pk=self.rse.pk).first_name, "Gestion")

    def test_administrateur_de_tous_ses_espaces(self):
        with E.activer("essai"):  # l'administrateur de « essai » devient aussi administrateur de l'espace principal
            pass
        u = creer("admin.achats@exemple.example", "admin", "principal")
        self.assertEqual(u.pk, self.achats.pk)
        with E.activer("essai"), E.acteur(self.achats.pk):
            u = Utilisateur.objects.get(pk=self.rse.pk)
            u.first_name = "Permis"
            u.save()
        self.assertEqual(Compte.objects.get(pk=self.rse.pk).first_name, "Permis")

    def test_copie_desactivee_compte_aussi(self):
        """L'administrateur de l'espace principal, désactivé (congé) : l'administrateur de « essai » ne choisit pas son
        mot de passe (il entrerait avec ses droits à la réactivation)."""
        Utilisateur.objects.filter(pk=self.rse.pk).update(is_active=False)
        avant = Compte.objects.get(pk=self.rse.pk).password
        c = self.client_achats()
        r = c.get(f"/espace/essai/administration/comptes/{self.rse.pk}/")
        self.assertNotContains(r, 'value="reinitialiser"')
        c.post(f"/espace/essai/administration/comptes/{self.rse.pk}/", {"action": "reinitialiser"})
        self.assertEqual(Compte.objects.get(pk=self.rse.pk).password, avant)

    def test_espace_archive_ou_indisponible_compte_aussi(self):
        """Administratrice de « essai » archivé (ou indisponible), contributrice de l'espace principal : l'administrateur de
        l'espace principal, simple contributeur dans « essai », ne prend pas la main sur son compte."""
        import tempfile

        from django.test import override_settings

        from . import comptes as EC
        from .models import Espace

        cible = creer("cible@exemple.example", "admin", "essai")
        creer("cible@exemple.example", "contributeur", "principal")
        Espace.objects.filter(code="essai").update(etat="archive")
        with E.acteur(self.rse.pk):
            self.assertFalse(EC.peut_modifier_identite(cible.pk))
        c = Client()
        c.force_login(Utilisateur.objects.get(pk=self.rse.pk))
        avant = Compte.objects.get(pk=cible.pk).password
        c.post(f"/administration/comptes/{cible.pk}/", {"action": "reinitialiser"})
        self.assertEqual(Compte.objects.get(pk=cible.pk).password, avant)
        self.assertIn("Achats", EC.partage_ailleurs(cible.pk, "default"))
        Espace.objects.filter(code="essai").update(etat="actif")
        with tempfile.TemporaryDirectory() as d, override_settings(ESPACES_DOSSIER=d):
            E.marquer_indisponible("essai", "essai")
            with E.acteur(self.rse.pk):
                self.assertFalse(EC.peut_modifier_identite(cible.pk))
            with E.acteur(self.achats.pk):  # administrateur de « essai », mais pas de l'espace principal
                self.assertFalse(EC.peut_modifier_identite(cible.pk))
        self.assertTrue(EC.peut_modifier_identite(cible.pk, self.premier.pk))  # gestionnaire

    def test_compte_d_un_gestionnaire_protege(self):
        """L'administrateur du seul espace où un gestionnaire a une copie ne change pas son mot de
        passe (il prendrait son compte, puis toute l'installation)."""
        from . import comptes as EC

        cible = creer("gestion@exemple.example", "contributeur", "principal")
        with E.acteur(self.rse.pk):
            self.assertTrue(EC.peut_modifier_identite(cible.pk))
        Compte.objects.filter(pk=cible.pk).update(gestionnaire=True)
        with E.acteur(self.rse.pk):
            self.assertFalse(EC.peut_modifier_identite(cible.pk))
        c = Client()
        c.force_login(Utilisateur.objects.get(pk=self.rse.pk))
        avant = Compte.objects.get(pk=cible.pk).password
        c.post(f"/administration/comptes/{cible.pk}/", {"action": "reinitialiser"})
        self.assertEqual(Compte.objects.get(pk=cible.pk).password, avant)
        self.assertTrue(EC.peut_modifier_identite(cible.pk, cible.pk))  # la personne elle-même
        self.assertTrue(EC.peut_modifier_identite(cible.pk, self.premier.pk))  # un autre gestionnaire

    def test_compte_garde_avec_une_copie_dans_un_espace_archive(self):
        from .models import Espace

        Espace.objects.filter(code="essai").update(etat="archive")
        Utilisateur.objects.get(pk=self.rse.pk).delete()  # dernière copie ouverte : celle d'« essai » reste
        self.assertTrue(Compte.objects.filter(pk=self.rse.pk).exists())
        with E.activer("principal"):  # recréé avec le même e-mail : même personne, même numéro
            u = creer("admin.rse@exemple.example", "admin")
        self.assertEqual(u.pk, self.rse.pk)

    def test_anonyme(self):
        with E.acteur(E.ANONYME), self.assertRaises(PermissionDenied):
            u = Utilisateur.objects.get(pk=self.rse.pk)
            u.first_name = "Anonyme"
            u.save()

    def test_rattachement_depuis_l_ecran_sans_mot_de_passe(self):
        c = Client()
        c.force_login(Utilisateur.objects.get(pk=self.rse.pk))
        r = c.post("/administration/comptes/nouveau/", {
            "action": "enregistrer", "first_name": "Autre", "last_name": "Nom", "email": "ACHETEUR@exemple.example",
            "role": "contributeur", "is_active": "on", "equipe": "", "mot_de_passe": ""}, headers={"X-Requested-With": "fetch"})
        self.assertIn("Cette personne a déjà un compte", r.json()["html"])
        self.assertNotIn("Mot de passe provisoire :", r.json()["html"])
        u = Utilisateur.objects.get(email="acheteur@exemple.example")
        self.assertEqual(u.pk, self.acheteur.pk)
        self.assertTrue(u.check_password(MDP))
        self.assertFalse(u.doit_changer_mdp)


class MiseEnPlaceTests(Base):
    def test_espace_neuf_sans_etape_1_pour_un_visiteur(self):
        r = Client().get("/espace/essai/mise-en-place/")
        self.assertNotEqual(r.status_code, 200)
        r = Client().get("/espace/essai/")
        self.assertIn("/connexion/", r.headers.get("Location", ""))
