"""Réglages de la Visualisation : vue d'accueil de chaque rôle et nombre de vues personnelles (Paramètres ›
Visualisation), couleurs des graphiques (Paramètres › Identité), journalisés ; migration parametres/0014."""
import json
import re
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from collecte.models import AccueilVisu, Journal, VueVisu
from parametres import couleurs as CO
from parametres.models import Instance
from referentiel.models import Utilisateur

URL = reverse("parametres:visualisation")


class VuesAccueilTests(TestCase):
    def setUp(self):
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN)
        self.contrib = Utilisateur.objects.create(username="contrib", email="contrib@exemple.test")
        self.comite = VueVisu.objects.create(nom="Comité de direction", proprietaire=self.admin, partage=True)
        self.perimetre = VueVisu.objects.create(nom="Mon périmètre", proprietaire=self.admin, partage=True, ordre=1)
        self.perso = VueVisu.objects.create(nom="Vue personnelle de l'admin", proprietaire=self.admin)

    def test_reserve_a_l_admin(self):
        self.client.force_login(self.contrib)
        self.assertEqual(self.client.get(URL).status_code, 403)
        self.assertEqual(self.client.post(URL, {"accueil_admin": self.comite.pk}).status_code, 403)
        self.assertFalse(AccueilVisu.objects.exists())

    def test_page(self):
        self.client.force_login(self.admin)
        rep = self.client.get(URL)
        self.assertContains(rep, "accueil de chaque rôle")
        for texte in ("Administrateurs", "Validateurs", "Contributeurs", "Lecteurs", "Auditeurs", "Comité de direction", "Mon périmètre",
                      'aria-current="page"'):
            self.assertContains(rep, texte)
        self.assertNotContains(rep, "Vue personnelle de l'admin")  # seulement les vues partagées
        self.assertContains(self.client.get(reverse("parametres:identite")), URL)  # onglet des Paramètres

    def test_regler_par_role_et_journal(self):
        self.client.force_login(self.admin)
        rep = self.client.post(URL, {"vues_personnelles_max": 10, "accueil_admin": self.comite.pk, "accueil_lecteur": self.comite.pk,
                                     "accueil_auditeur": self.comite.pk, "accueil_contributeur": self.perimetre.pk,
                                     "accueil_validateur": self.perimetre.pk})
        self.assertRedirects(rep, URL)
        self.assertEqual(dict(AccueilVisu.objects.values_list("role", "vue_id")), {
            "admin": self.comite.pk, "lecteur": self.comite.pk, "auditeur": self.comite.pk,
            "contributeur": self.perimetre.pk, "validateur": self.perimetre.pk})
        self.assertEqual(Journal.objects.filter(action="vue_partagee").count(), 5)
        rep = self.client.post(URL, {"vues_personnelles_max": 10, "accueil_admin": self.comite.pk, "accueil_lecteur": "",
                                     "accueil_auditeur": self.comite.pk, "accueil_contributeur": self.perimetre.pk,
                                     "accueil_validateur": self.perimetre.pk})
        self.assertFalse(AccueilVisu.objects.filter(role="lecteur").exists())
        e = Journal.objects.filter(action="vue_partagee").latest("pk")
        self.assertEqual((e.champ, e.avant, e.apres, e.objet_id), ("vue d'accueil (Lecteurs)", "Comité de direction", "", str(self.comite.pk)))
        self.assertEqual(Journal.objects.filter(action="vue_partagee").count(), 6)  # seuls les changements sont notés

    def test_vue_non_partagee_refusee(self):
        self.client.force_login(self.admin)
        rep = self.client.post(URL, {"vues_personnelles_max": 10, "accueil_admin": self.perso.pk, "accueil_lecteur": self.comite.pk})
        self.assertEqual(rep.status_code, 200)
        self.assertContains(rep, "plus partagée")
        self.assertFalse(AccueilVisu.objects.exists())  # rien d'enregistré


class VuesPersonnellesTests(TestCase):
    """Nombre de vues personnelles par personne : 25 par défaut, réglable ; contrôlé à la création et à la duplication."""

    def setUp(self):
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN)
        self.contrib = Utilisateur.objects.create(username="contrib", email="contrib@exemple.test")
        self.partagee = VueVisu.objects.create(nom="Comité", proprietaire=self.admin, partage=True)

    def post(self, nom, donnees=None, args=()):
        return self.client.post(reverse(f"collecte:{nom}", args=args), json.dumps(donnees or {}), content_type="application/json")

    def test_defaut_et_reglage(self):
        self.assertEqual(Instance.courante().vues_personnelles_max, 10)
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(URL), 'name="vues_personnelles_max"')
        rep = self.client.post(URL, {"vues_personnelles_max": "2"})
        self.assertRedirects(rep, URL)
        self.assertEqual(Instance.courante().vues_personnelles_max, 2)
        e = Journal.objects.get(action="reglage_visualisation")
        self.assertEqual((e.champ, e.avant, e.apres), ("vues_personnelles_max", "10", "2"))
        rep = self.client.post(URL, {"vues_personnelles_max": "0"})
        self.assertEqual(rep.status_code, 200)
        self.assertEqual(Instance.courante().vues_personnelles_max, 2)  # refusé : rien d'enregistré

    def test_creer_et_dupliquer_au_dela(self):
        Instance.objects.filter(pk=Instance.courante().pk).update(vues_personnelles_max=2)
        self.client.force_login(self.contrib)
        for i in range(2):
            self.assertEqual(self.post("visu_vue_creer", {"nom": f"Vue {i}", "visuels": []}).status_code, 201)
        message = "Vous avez atteint le maximum de 2 vues personnelles. Supprimez-en une ou demandez à l'administrateur."
        rep = self.post("visu_vue_creer", {"nom": "Une de trop", "visuels": []})
        self.assertEqual((rep.status_code, rep.json()["erreurs"][0]["message"]), (400, message))
        rep = self.post("visu_vue_dupliquer", {}, [self.partagee.pk])
        self.assertEqual((rep.status_code, rep.json()["erreurs"][0]["message"]), (400, message))
        self.assertEqual(VueVisu.objects.filter(proprietaire=self.contrib).count(), 2)
        self.assertContains(self.client.get(reverse("collecte:visu_vue_nouvelle")), "Vous avez atteint le maximum de 2 vues personnelles")
        # elle garde ses vues, et les modifie
        v = VueVisu.objects.filter(proprietaire=self.contrib).first()
        self.assertEqual(self.post("visu_vue_enregistrer", {"version": v.version, "nom": "Renommée"}, [v.pk]).status_code, 200)
        self.assertEqual(self.post("visu_vue_supprimer", {}, [v.pk]).status_code, 200)
        self.assertEqual(self.post("visu_vue_creer", {"nom": "Remplaçante", "visuels": []}).status_code, 201)

    def test_au_dessus_garde_ses_vues_et_vues_partagees_hors_compte(self):
        for i in range(3):
            VueVisu.objects.create(nom=f"Ancienne {i}", proprietaire=self.contrib)
        Instance.objects.filter(pk=Instance.courante().pk).update(vues_personnelles_max=2)
        self.client.force_login(self.contrib)
        self.assertEqual(len(self.client.get(reverse("collecte:visu")).context["vues"]), 4)  # ses 3 vues et la vue partagée
        self.assertEqual(self.post("visu_vue_creer", {"nom": "X", "visuels": []}).status_code, 400)
        self.client.force_login(self.admin)  # les vues partagées de l'admin ne comptent pas
        for i in range(3):
            VueVisu.objects.create(nom=f"Partagée {i}", proprietaire=self.admin, partage=True)
        self.assertEqual(self.post("visu_vue_creer", {"nom": "Perso admin", "visuels": []}).status_code, 201)
        self.assertEqual(self.post("visu_vue_creer", {"nom": "Partagée", "partage": True, "visuels": []}).status_code, 201)


class CouleursGraphiquesTests(TestCase):
    """Paramètres › Identité › « Couleurs des graphiques » : vide = la palette fournie (rien ne change à l'écran)."""

    def setUp(self):
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN)
        self.url = reverse("parametres:identite")

    def donnees(self, **autres):
        i = Instance.courante()
        d = {"nom": i.nom, "titre": i.titre, "sous_titre": i.sous_titre, "sigle": i.sigle, "contact": i.contact, "palette": i.palette,
             "couleur_principale": i.couleur_principale, "couleur_accent": i.couleur_accent, "couleur_fond": i.couleur_fond,
             "couleur_texte": i.couleur_texte}
        d.update({f"viz_{n}": c for n, c in enumerate(CO.VIZ, start=1)}, viz_autres=CO.VIZ_AUTRES)
        d.update(autres)
        return d

    def test_palette_fournie_identique_a_outil_css(self):
        css = (Path(settings.BASE_DIR) / "static" / "css" / "outil.css").read_text(encoding="utf-8")
        racine = re.search(r":root(?:, \.apparence-claire)? \{[^}]*--viz-1:[^}]*\}", css).group(0)  # le bloc :root des couleurs de données
        valeurs = dict(re.findall(r"--viz-(\w+): (#[0-9a-fA-F]{6})", racine))
        self.assertEqual([valeurs[str(i)].upper() for i in range(1, 9)], CO.VIZ)
        self.assertEqual((valeurs["autres"].upper(), valeurs["pale"].upper()), (CO.VIZ_AUTRES, CO.VIZ_PALE))

    def test_installation_existante_rien_ne_change(self):
        self.client.force_login(self.admin)
        self.assertEqual(Instance.courante().couleurs_graphiques, {})
        page = self.client.get(reverse("collecte:visu")).content.decode()
        self.assertNotIn("--viz-1:", page.split("</style>")[0].split("apparence sombre")[0])  # aucune couleur injectée en clair : celles d'outil.css
        self.assertEqual(self.client.get(reverse("collecte:visu")).context["contexte_visu"]["viz_claires"], [])
        rep = self.client.get(self.url)
        self.assertContains(rep, "Couleurs des graphiques")
        self.assertContains(rep, "Palette fournie, vérifiée pour les daltonismes.")
        self.assertNotContains(rep, 'value="couleurs_graphiques_defaut"')
        self.client.post(self.url, self.donnees())  # enregistrer sans rien changer : toujours la palette fournie
        self.assertEqual(Instance.courante().couleurs_graphiques, {})
        self.assertFalse(Journal.objects.filter(champ="couleurs_graphiques").exists())

    def test_regler_puis_revenir_aux_couleurs_par_defaut(self):
        self.client.force_login(self.admin)
        rep = self.client.post(self.url, self.donnees(viz_1="#112233", viz_4="#ffee00", viz_autres="#777777"))
        self.assertEqual(rep.status_code, 302)
        i = Instance.courante()
        self.assertEqual(i.couleurs_graphiques["series"][:4], ["#112233", "#EB6834", "#1BAF7A", "#FFEE00"])
        self.assertEqual(i.couleurs_graphiques["autres"], "#777777")
        style = self.client.get(reverse("collecte:visu")).content.decode().split("</style>")[0]
        self.assertIn("--viz-1: #112233;", style)
        self.assertIn("--viz-autres: #777777;", style)
        self.assertIn(f"--viz-pale: {CO.pale('#112233')};", style)
        claires = self.client.get(reverse("collecte:visu")).context["contexte_visu"]["viz_claires"]
        # le jaune #FFEE00 choisi est sous 3:1 : ses valeurs seront toujours écrites ; les teintes claires de la palette
        # fournie restées à leur place (séries 3 et 5) gardent leur affichage, comme les couleurs foncées choisies
        self.assertEqual(claires, [3])
        page = self.client.get(self.url)
        self.assertContains(page, "Palette réglée pour votre installation.")
        self.assertContains(page, "trop claire")
        e = Journal.objects.get(action="reglage_identite", champ="couleurs_graphiques")
        self.assertEqual(e.avant, "palette fournie")
        self.assertTrue(e.apres.startswith("#112233, #EB6834"))
        rep = self.client.post(self.url, {"action": "couleurs_graphiques_defaut"})
        self.assertRedirects(rep, self.url + "#couleurs-graphiques")
        self.assertEqual(Instance.courante().couleurs_graphiques, {})
        self.assertEqual(Journal.objects.filter(champ="couleurs_graphiques").latest("pk").apres, "palette fournie")

    def test_couleur_invalide(self):
        self.client.force_login(self.admin)
        rep = self.client.post(self.url, self.donnees(viz_2="bleu", nom="Autre nom"))
        self.assertEqual(rep.status_code, 200)
        self.assertContains(rep, "#RRGGBB")
        self.assertEqual(Instance.courante().couleurs_graphiques, {})
        self.assertNotEqual(Instance.courante().nom, "Autre nom")  # rien d'enregistré

    def test_reglage_abime_vaut_palette_fournie(self):
        for abime in ({"series": ["#000000"]}, {"series": ["x"] * 8, "autres": "#000000"}, ["#000000"], None):
            with self.subTest(reglage=abime):
                self.assertEqual(CO.palette_graphiques(abime), (CO.VIZ, CO.VIZ_AUTRES, False))
                self.assertEqual(CO.css_graphiques(abime), "")


class MigrationParametresTests(TransactionTestCase):
    """Migration parametres/0014 : aller et retour sans perte ; une installation existante garde la palette fournie.
    Sans ``serialized_rollback`` : comme les autres tests de migration qui passent après les tests du navigateur (une
    remise des données après un test en transaction qui a vidé la base échouerait sur les types de contenu)."""

    AVANT = [("parametres", "0013_seuils_de_suivi")]
    APRES = [("parametres", "0014_visualisation")]

    def migrer(self, cible):
        e = MigrationExecutor(connection)
        e.loader.build_graph()
        e.migrate(cible)
        return e.loader.project_state(cible).apps

    def tearDown(self):
        self.migrer(MigrationExecutor(connection).loader.graph.leaf_nodes())
        super().tearDown()

    def test_aller_retour(self):
        anciennes = self.migrer(self.AVANT)
        I = anciennes.get_model("parametres", "Instance")
        I.objects.update_or_create(pk=1, defaults={"nom": "Client", "couleur_principale": "#B5305F", "tolerance_retard": 12})
        avant = I.objects.values("nom", "couleur_principale", "tolerance_retard").get(pk=1)
        nouvelles = self.migrer(self.APRES)
        i = nouvelles.get_model("parametres", "Instance").objects.get(pk=1)
        self.assertEqual((i.couleurs_graphiques, i.vues_personnelles_max), ({}, 25))
        self.assertEqual({k: getattr(i, k) for k in avant}, avant)
        anciennes = self.migrer(self.AVANT)
        self.assertEqual(anciennes.get_model("parametres", "Instance").objects.values("nom", "couleur_principale", "tolerance_retard").get(pk=1), avant)


class BaseAdminFr(TestCase):
    def setUp(self):
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN,
                                                langue="fr")
        self.client.force_login(self.admin)


class VuesPersonnellesPageTests(BaseAdminFr):
    def test_dix_par_defaut_et_texte_court(self):
        self.assertEqual(Instance.courante().vues_personnelles_max, 10)
        rep = self.client.get(reverse("parametres:visualisation"))
        self.assertContains(rep, "10 par défaut. Les vues partagées ne comptent pas.")
        self.assertNotContains(rep, "25 par défaut")

    def test_au_dessus_de_la_limite_personne_ne_perd_de_vue(self):
        """Une personne qui a déjà plus de 10 vues les garde toutes, les ouvre et les modifie ; elle n'en crée plus."""
        import json

        for i in range(12):
            VueVisu.objects.create(nom=f"Vue {i}", proprietaire=self.admin)
        self.assertEqual(len(self.client.get(reverse("collecte:visu")).context["vues"]), 12)
        rep = self.client.post(reverse("collecte:visu_vue_creer"), json.dumps({"nom": "Une de plus", "visuels": []}),
                               content_type="application/json")
        self.assertEqual(rep.status_code, 400)
        self.assertIn("maximum de 10 vues personnelles", rep.json()["erreurs"][0]["message"])
        v = VueVisu.objects.filter(proprietaire=self.admin).first()
        rep = self.client.post(reverse("collecte:visu_vue_enregistrer", args=[v.pk]), json.dumps({"version": v.version, "nom": "Renommée"}),
                               content_type="application/json")
        self.assertEqual(rep.status_code, 200)
        self.assertEqual(VueVisu.objects.filter(proprietaire=self.admin).count(), 12)


class MigrationVuesPersonnellesTests(TransactionTestCase):
    """parametres/0026 : 25 (ancienne valeur par défaut) devient 10 ; une autre valeur est gardée ; retour arrière."""

    AVANT = [("parametres", "0025_na_roles")]
    APRES = [("parametres", "0026_vues_personnelles_10")]

    def migrer(self, cible):
        e = MigrationExecutor(connection)
        e.loader.build_graph()
        e.migrate(cible)
        return e.loader.project_state(cible).apps

    def tearDown(self):
        self.migrer(MigrationExecutor(connection).loader.graph.leaf_nodes())
        super().tearDown()

    def test_aller_retour(self):
        for choisie, attendue, retour in ((25, 10, 25), (40, 40, 40), (3, 3, 3)):
            with self.subTest(valeur=choisie):
                anciennes = self.migrer(self.AVANT)
                I = anciennes.get_model("parametres", "Instance")
                I.objects.update_or_create(pk=1, defaults={"nom": "Client", "vues_personnelles_max": choisie})
                nouvelles = self.migrer(self.APRES)
                i = nouvelles.get_model("parametres", "Instance").objects.get(pk=1)
                self.assertEqual((i.vues_personnelles_max, i.nom), (attendue, "Client"))
                anciennes = self.migrer(self.AVANT)
                self.assertEqual(anciennes.get_model("parametres", "Instance").objects.get(pk=1).vues_personnelles_max, retour)
