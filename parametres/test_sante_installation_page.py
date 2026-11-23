"""Page « Santé de l'installation » (Administration › Paramètres › Santé) : une ligne par point avec un état
« Bon », « À regarder » ou « En panne » et quoi faire ; mesures de /sante/ (une seule écriture) ; détail pour l'IT
(noms des espaces, chemins du disque) réservé au gestionnaire des espaces et à l'espace principal."""
from pathlib import Path
from unittest import mock

from django.test import Client, TestCase, override_settings
from django.urls import reverse

from espaces import contexte as E
from espaces.aides_tests import MDP, creer
from espaces.essais import EspacesTestCase
from espaces.models import Compte
from referentiel.models import Utilisateur

from . import sante_installation as SI
from . import vues_hebergement as VH

URL = "/administration/parametres/sante/"
SECRET = Path("/chemin/secret/des/donnees")


def connecter(u, espace="principal"):
    c = Client()
    with E.activer(espace):
        c.force_login(Utilisateur.objects.get(pk=u.pk))
    return c


def etat_de(rep, cle):
    """État (bon, regarder, panne) d'une ligne de la page."""
    return next(x["etat"] for x in rep.context["lignes"] if x["cle"] == cle)


class PageTests(EspacesTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.admin = creer("admin@exemple.example", "admin")  # gestionnaire des espaces
        cls.contrib = creer("contrib@exemple.example")
        cls.admin_essai = creer("admin.essai@exemple.example", "admin", "essai")  # administrateur de « essai » seulement

    def test_lignes_et_etats(self):
        rep = connecter(self.admin).get(URL)
        self.assertEqual(rep.status_code, 200)
        cles = [x["cle"] for x in rep.context["lignes"]]
        self.assertEqual(cles, ["version", "base", "fichiers", "sauvegarde", "disque", "email", "taches", "migrations", "https"])
        self.assertEqual(etat_de(rep, "base"), SI.BON)
        self.assertEqual(etat_de(rep, "migrations"), SI.BON)
        self.assertEqual(etat_de(rep, "sauvegarde"), SI.A_REGARDER)  # aucune sauvegarde dans les tests
        self.assertEqual(etat_de(rep, "https"), SI.A_REGARDER)  # le client de test n'est pas en HTTPS
        self.assertContains(rep, 'class="etiquette e-vert"')
        self.assertContains(rep, "aria-current=\"page\"")  # onglet Santé des Paramètres

    def test_page_dans_la_langue_de_la_personne(self):
        """La page se termine par « /sante/ » comme la supervision, qui n'a pas de langue : elle doit pourtant suivre la
        langue de la personne (elle s'affichait dans la langue de l'installation)."""
        self.admin.langue = "en"
        self.admin.save()
        rep = connecter(self.admin).get(URL)
        self.assertContains(rep, "Installation health")
        self.assertNotContains(rep, "Santé de l'installation")

    def test_reservee_a_l_administrateur(self):
        self.assertEqual(connecter(self.contrib).get(URL).status_code, 403)
        self.assertEqual(Client().get(URL).status_code, 302)

    @override_settings(HTTPS=True)
    def test_https_bon(self):
        rep = connecter(self.admin).get(URL, secure=True)
        self.assertEqual(etat_de(rep, "https"), SI.BON)

    def test_disque_presque_plein_detail_pour_l_it(self):
        with mock.patch.object(VH, "espace_disque", return_value=(10 * 1024 * 1024, SECRET)):
            rep = connecter(self.admin).get(URL)
            self.assertEqual(etat_de(rep, "disque"), SI.PANNE)
            self.assertContains(rep, str(SECRET))  # espace principal : détail pour l'IT
            self.assertEqual(SI.bilan(rep.context["lignes"])[0], SI.PANNE)
            rep = connecter(self.admin_essai, "essai").get(f"/espace/essai{URL}")
            self.assertEqual(rep.status_code, 200)
            self.assertEqual(etat_de(rep, "disque"), SI.PANNE)  # l'état, sans le chemin du disque
            self.assertNotContains(rep, str(SECRET))

    def test_autre_espace_injoignable_sans_son_nom(self):
        """L'administrateur d'un espace secondaire n'apprend pas le nom ni l'état détaillé des autres espaces."""
        def bases(seulement=None):
            return ("unreachable (space confidentiel)", "ok", ["principal", "essai"])

        with mock.patch.object(VH, "_sante_bases", side_effect=bases):
            rep = connecter(self.admin).get(URL)
            self.assertEqual(etat_de(rep, "base"), SI.PANNE)
            self.assertContains(rep, "confidentiel")
            rep = connecter(self.admin_essai, "essai").get(f"/espace/essai{URL}")
            self.assertEqual(etat_de(rep, "base"), SI.PANNE)
            self.assertNotContains(rep, "confidentiel")

    def test_gestionnaire_voit_le_detail_depuis_un_espace_secondaire(self):
        Compte.objects.filter(pk=self.admin_essai.pk).update(gestionnaire=True)
        with mock.patch.object(VH, "espace_disque", return_value=(10 * 1024 * 1024, SECRET)):
            rep = connecter(self.admin_essai, "essai").get(f"/espace/essai{URL}")
        self.assertContains(rep, str(SECRET))

    def test_seul_l_espace_courant_est_mesure_pour_l_espace_secondaire(self):
        vu = {}
        origine = VH.mesurer_sante

        def espion(codes=None):
            vu["codes"] = codes
            return origine(codes)

        with mock.patch.object(VH, "mesurer_sante", side_effect=espion):
            connecter(self.admin_essai, "essai").get(f"/espace/essai{URL}")
        self.assertEqual(vu["codes"], ["essai"])

    def test_migrations_en_attente(self):
        with mock.patch("collecte.mise_a_jour.base_a_jour", return_value=False):
            rep = connecter(self.admin).get(URL)
        self.assertEqual(etat_de(rep, "migrations"), SI.PANNE)

    @override_settings(EMAIL_HOST="smtp.exemple.test")
    def test_dernier_email_en_echec(self):
        from collecte.models import Relance

        Relance.objects.create(destinataire=Utilisateur.objects.get(pk=self.contrib.pk), statut=Relance.Statut.ECHEC)
        rep = connecter(self.admin).get(URL)
        self.assertEqual(etat_de(rep, "email"), SI.A_REGARDER)

    def test_supervision_inchangee(self):
        """/sante/ répond comme avant : sans connexion depuis une autre machine, l'état seul ; détail pour l'administrateur."""
        rep = Client(REMOTE_ADDR="203.0.113.5").get("/sante/")
        self.assertEqual(set(rep.json()), {"etat"})
        rep = connecter(self.admin).get("/sante/")
        self.assertTrue({"version", "base", "stockage", "derniere_sauvegarde", "controle_donnees", "background_imports",
                         "background_exports"} <= set(rep.json()))


class LienHebergementTests(TestCase):
    def test_lien_depuis_hebergement(self):
        admin = Utilisateur.objects.create_user("a", "a@exemple.test", MDP, role="admin", is_superuser=True, is_staff=True)
        self.client.force_login(admin)
        self.assertContains(self.client.get(reverse("parametres:hebergement")), reverse("parametres:sante_installation"))
