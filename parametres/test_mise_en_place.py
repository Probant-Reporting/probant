"""Assistant « Mise en place » (phase 7) : base vide configurée de bout en bout jusqu'à une campagne ouverte et une
première saisie, reprise après interruption, « Passer », installations existantes non affectées, lecture de l'arbre."""
import importlib

from django.apps import apps as django_apps
from django.test import TestCase
from django.urls import reverse

from collecte import paquets as P
from collecte.models import Campagne, Reponse
from referentiel.models import KPI, Organisation, Referentiel, Utilisateur

from . import mise_en_place as M
from . import niveaux as N
from .models import Instance, Langue
from collecte.aides_tests.bibliotheque_essai import BibliothequeEssai

MDP = "Essai-mise-en-place-2026"
ADMIN = {"prenom": "Alice", "nom": "Exemple", "email": "admin@exemple.test", "mot_de_passe": MDP, "confirmation": MDP}
ARBRE = "Mon groupe\n  France\n    Alpha France\n      Lyon\n  Espagne\n    Alpha España"


def confirmer_niveaux(client):
    """Étape 4 : « Confirmer ces niveaux » (modèle Groupe › Pays › Entité › Site, celui d'une installation neuve)."""
    client.post(etape(4), {"action": "niveaux", "modele": "groupe-pays-entite-site"})


def etape(n):
    return reverse("parametres:mise_en_place_etape", args=[n])


class Parcours(BibliothequeEssai, TestCase):
    """Une installation vide, configurée par l'assistant."""

    def test_base_vide_de_bout_en_bout(self):
        c = self.client
        # sans compte : toute page mène à l'assistant, à la place de la connexion
        for url in ("/", reverse("login"), reverse("collecte:tableau_de_bord")):
            self.assertRedirects(c.get(url), reverse("parametres:mise_en_place"), target_status_code=200)
        rep = c.get(reverse("parametres:mise_en_place"))
        self.assertContains(rep, "Compte administrateur")
        self.assertNotContains(rep, 'value="passer"')  # pas de « Passer » pour le compte
        self.assertRedirects(c.get(etape(4)), reverse("parametres:mise_en_place"), target_status_code=200)

        # 1. compte administrateur (mots de passe différents : refusé)
        rep = c.post(reverse("parametres:mise_en_place"), {**ADMIN, "confirmation": "autre"})
        self.assertContains(rep, "sont différents")
        self.assertFalse(Utilisateur.objects.exists())
        self.assertRedirects(c.post(reverse("parametres:mise_en_place"), ADMIN), etape(2))
        admin = Utilisateur.objects.get()
        self.assertEqual((admin.email, admin.role, admin.is_superuser), ("admin@exemple.test", Utilisateur.Role.ADMIN, True))
        self.assertEqual(Instance.courante().mise_en_place_etape, 2)

        # 2. structure, avec l'aperçu
        rep = c.get(etape(2))
        self.assertContains(rep, "Ce que voient les contributeurs")
        identite = {"nom": "Exemple SA", "titre": "Reporting durable", "sous_titre": "", "sigle": "EX", "contact": "l'équipe responsable",
                    "palette": "ocean", "couleur_principale": "#1F5FAD", "couleur_accent": "#0F9D9A", "couleur_fond": "#F2F4F7",
                    "couleur_texte": "#1E2A38", "langue": "fr"}
        self.assertRedirects(c.post(etape(2), identite), etape(3))
        self.assertEqual(Instance.courante().nom, "Exemple SA")

        # 3. langues : ajouter l'espagnol puis continuer
        self.assertRedirects(c.post(etape(3), {"action": "ajouter", "code": "es", "libelle": "Español"}), etape(3))
        self.assertTrue(Langue.objects.filter(code="es").exists())
        defaut = {"defaut": "fr", **{f"libelle__{l.code}": l.libelle for l in Langue.objects.all()},
                  **{f"active__{l.code}": "on" for l in Langue.objects.all()}}
        self.assertRedirects(c.post(etape(3), defaut), etape(4))

        # 4. organisation : niveaux (modèle), aperçu de l'arbre, puis création
        self.assertRedirects(c.post(etape(4), {"action": "niveaux", "modele": "groupe-pays-entite-site"}), etape(4))
        self.assertEqual([n.code for n in N.tous()], ["Group", "Country", "Entity", "Site"])
        rep = c.post(etape(4), {"action": "apercu", "arbre": ARBRE})
        self.assertContains(rep, "Alpha España")
        self.assertFalse(Organisation.objects.exists())  # aperçu seulement
        self.assertRedirects(c.post(etape(4), {"action": "suivant", "arbre": ARBRE}), etape(5))
        lyon = Organisation.objects.get(nom="Lyon")
        self.assertEqual((lyon.niveau_id, lyon.parent.nom, lyon.parent.parent.nom), ("Site", "Alpha France", "France"))
        self.assertEqual(Organisation.objects.count(), 6)

        # 5. référentiels : installer un socle de la bibliothèque (écrans de la phase 6), régler sa fréquence
        rep = c.get(etape(5))
        self.assertContains(rep, "Installer depuis la bibliothèque")
        url_kpi = reverse("parametres:installer_kpi", args=["SOCLE_SOCIAL"])
        self.assertContains(rep, url_kpi + "?depuis=mise_en_place")
        rep = c.get(url_kpi + "?depuis=mise_en_place")
        self.assertNotContains(rep, "Niveaux de saisie")
        codes = [k["code"] for k in P.fourni("socle_social.json").paquet.kpis]
        rep = c.post(url_kpi, {"action": "continuer", "kpi": codes})
        rep = c.get(rep["Location"])
        self.assertNotContains(rep, "Niveaux de saisie")
        self.assertContains(rep, "au niveau <b>Site</b>", html=False)
        rep = c.post(reverse("parametres:installer_resume", args=["SOCLE_SOCIAL"]), {"action": "installer", "nom": "Social (modèle)",
                                                                                     "frequence": "annee"})
        self.assertRedirects(rep, etape(5), fetch_redirect_response=False)  # retour à l'assistant, avec un message
        self.assertContains(c.get(etape(5)), "installé : 23 KPI")
        ref = Referentiel.objects.get(code="SOCLE_SOCIAL")
        post = {f"frequence__{r.code}": r.frequence for r in Referentiel.objects.all()}
        post.update({f"mois_debut__{r.code}": r.mois_debut for r in Referentiel.objects.all()})
        post["frequence__SOCLE_SOCIAL"] = "annee"
        self.assertRedirects(c.post(etape(5), post), etape(6))

        # 6. fiche indicateur : jeu par défaut gardé
        self.assertContains(c.get(etape(6)), "Catégories de description")
        self.assertRedirects(c.post(etape(6), {"action": "passer"}), etape(7))

        # 7. équipe : une contributrice ; le message d'accès est proposé
        rep = c.post(etape(7), {"action": "creer", "first_name_0": "Bea", "last_name_0": "Essai", "email_0": "bea@exemple.test",
                                "role_0": "contributeur"})
        self.assertContains(rep, "Message à envoyer à Bea")
        self.assertTrue(Utilisateur.objects.filter(email="bea@exemple.test", role=Utilisateur.Role.CONTRIBUTEUR).exists())
        self.assertRedirects(c.post(etape(7), {"action": "suivant"}), etape(8))

        # 8. première campagne : la période en cours est proposée ; ouverte tout de suite
        rep = c.get(etape(8))
        self.assertContains(rep, "Ouvrir la saisie maintenant")
        form = rep.context["form"]
        self.assertTrue(form.initial.get("exercice"))
        rep = c.post(etape(8), {"action": "suivant", "referentiel": ref.pk, "exercice": form.initial["exercice"], "rang": 1,
                                "date_ouverture": form.initial["date_ouverture"].isoformat(),
                                "date_fin_saisie": form.initial["date_fin_saisie"].isoformat(), "seuil_pct": "20",
                                "seuil_historique": "", "ouvrir": "on"})
        self.assertRedirects(rep, reverse("collecte:tableau_de_bord"))
        campagne = Campagne.objects.get(referentiel=ref)
        self.assertEqual(campagne.statut, Campagne.Statut.OUVERTE)
        i = Instance.courante()
        self.assertTrue(i.mise_en_place_terminee)
        self.assertNotContains(c.get(reverse("collecte:tableau_de_bord")), "Reprendre la mise en place")
        self.assertEqual(c.get("/").status_code, 302)  # accueil normal, plus l'assistant
        self.assertNotIn("mise-en-place", c.get("/")["Location"])

        # première saisie
        kpi = KPI.objects.get(code="SOC-EFFECTIF")
        self.assertEqual(kpi.granularite_id, "Site")  # modèle sans niveau : KPI saisi au niveau le plus bas de l'arbre
        org = Organisation.objects.get(nom="Lyon")
        rep = c.post(reverse("collecte:cellule", args=[campagne.pk, kpi.code, org.pk]), {"action": "enregistrer", "valeur": "120"})
        self.assertLess(rep.status_code, 400)
        r = Reponse.objects.get(periode=campagne.periode, kpi=kpi, organisation=org)
        self.assertEqual(r.valeur, 120)

        # terminée : l'assistant reste consultable, chaque étape modifiable
        # terminée : l'assistant ne sert plus, tout se règle dans Administration
        self.assertRedirects(c.get(reverse("parametres:mise_en_place")), reverse("collecte:admin_accueil"))
        self.assertRedirects(c.get(reverse("parametres:mise_en_place_etape", args=[3])), reverse("collecte:admin_accueil"))
        self.assertNotContains(c.get(reverse("parametres:identite")), "lien-mise-en-place")


class Reprise(TestCase):
    def setUp(self):
        self.client.post(reverse("parametres:mise_en_place"), ADMIN)

    def test_reprise_apres_interruption(self):
        c = self.client
        c.post(etape(2), {"action": "passer"})
        c.post(etape(3), {"action": "passer"})
        self.assertEqual(Instance.courante().mise_en_place_etape, 4)
        c.logout()
        self.assertEqual(c.get("/").status_code, 302)
        self.assertIn(reverse("login"), c.get("/")["Location"])  # un compte existe : la connexion habituelle
        self.assertTrue(c.login(username=ADMIN["email"], password=MDP))
        self.assertRedirects(c.get("/"), reverse("parametres:mise_en_place"), fetch_redirect_response=False)
        self.assertRedirects(c.get(reverse("parametres:mise_en_place")), etape(4))
        # ailleurs : un bandeau propose de reprendre
        rep = c.get(reverse("collecte:admin_accueil"))
        self.assertContains(rep, "Reprendre la mise en place")
        self.assertContains(rep, "étape 4 sur 8")

    def test_passer_garde_les_valeurs(self):
        c = self.client
        avant = Instance.courante()
        niveaux = [n.code for n in N.tous()]
        for n in range(2, 8):
            if n == 4:  # étape 4 : niveaux confirmés d'abord 
                self.assertRedirects(c.post(etape(4), {"action": "passer"}), etape(4))
                confirmer_niveaux(c)
            self.assertRedirects(c.post(etape(n), {"action": "passer"}), etape(n + 1))
        i = Instance.courante()
        self.assertEqual((i.nom, i.couleur_principale, i.langue), (avant.nom, avant.couleur_principale, avant.langue))
        self.assertEqual([n.code for n in N.tous()], niveaux)
        self.assertFalse(Organisation.objects.exists())
        self.assertEqual(Utilisateur.objects.count(), 1)
        self.assertFalse(i.mise_en_place_terminee)
        self.assertRedirects(c.post(etape(8), {"action": "passer"}), reverse("collecte:tableau_de_bord"))
        self.assertTrue(Instance.courante().mise_en_place_terminee)
        self.assertFalse(Campagne.objects.exists())

    def test_etape_suivante_exige_une_valeur(self):
        confirmer_niveaux(self.client)
        rep = self.client.post(etape(4), {"action": "suivant", "arbre": ""}, follow=True)
        self.assertContains(rep, "au moins une organisation")
        self.assertEqual(Instance.courante().mise_en_place_etape, 4)

    def test_reserve_a_l_administrateur(self):
        u = Utilisateur.objects.create_user("contrib", email="c@exemple.test", password=MDP, role=Utilisateur.Role.CONTRIBUTEUR)
        self.client.force_login(u)
        self.assertEqual(self.client.get(etape(2)).status_code, 403)
        self.assertNotEqual(self.client.get("/").get("Location", ""), reverse("parametres:mise_en_place"))


class InstallationsExistantes(TestCase):
    def test_comptes_existants_rien_ne_change(self):
        u = Utilisateur.objects.create_user("admin", email="a@exemple.test", password=MDP, role=Utilisateur.Role.ADMIN)
        self.assertNotIn("mise-en-place", self.client.get("/").get("Location", ""))
        self.client.force_login(u)
        self.assertNotIn("mise-en-place", self.client.get("/").get("Location", ""))
        self.assertNotContains(self.client.get(reverse("collecte:admin_accueil")), "Reprendre la mise en place")

    def test_migration_marque_terminee(self):
        migration = importlib.import_module("parametres.migrations.0007_mise_en_place")
        Instance.objects.all().delete()
        migration.marquer_existantes(django_apps, None)
        self.assertFalse(Instance.objects.exists())  # base vide : l'assistant s'affichera
        Utilisateur.objects.create_user("admin", email="a@exemple.test", password=MDP)
        migration.marquer_existantes(django_apps, None)
        self.assertTrue(Instance.objects.get(pk=1).mise_en_place_terminee)

    def test_demos_marquees_terminees(self):
        from collecte.aides_tests import jeu_trois_niveaux as J
        from collecte.management.commands import _exemplia

        self.assertTrue(_exemplia.IDENTITE["mise_en_place_terminee"])
        self.assertTrue(J.IDENTITE["mise_en_place_terminee"])


class LectureArbre(TestCase):
    def setUp(self):
        self.niveaux = N.tous()  # Groupe › Pays › Entité › Site par défaut

    def lire(self, texte):
        return M.lire_arbre(texte, self.niveaux)

    def test_decalage(self):
        noeuds, erreurs = self.lire("G\n\tFrance\n\t\tA\n\t\t\tLyon\n\tItalie")
        self.assertEqual(erreurs, [])
        self.assertEqual([(x.nom, x.niveau.code, x.parent) for x in noeuds],
                         [("G", "Group", ""), ("France", "Country", "G"), ("A", "Entity", "France"), ("Lyon", "Site", "A"),
                          ("Italie", "Country", "G")])

    def test_puces_chemin_et_niveau_force(self):
        noeuds, erreurs = self.lire("- G\n  - France\nG > Italie > B\nG > Siège [Site]")
        self.assertEqual(erreurs, [])
        self.assertEqual({x.nom: (x.niveau.code, x.parent) for x in noeuds},
                         {"G": ("Group", ""), "France": ("Country", "G"), "Italie": ("Country", "G"), "B": ("Entity", "Italie"),
                          "Siège": ("Site", "G")})

    def test_collage_excel(self):
        noeuds, erreurs = self.lire("Groupe\tPays\tEntité\tSite\nG\tFrance\tA\tLyon\n\t\t\tParis\n\tItalie\tB\t")
        self.assertEqual(erreurs, [])
        self.assertEqual([(x.nom, x.parent) for x in noeuds],
                         [("G", ""), ("France", "G"), ("A", "France"), ("Lyon", "A"), ("Paris", "A"), ("Italie", "G"), ("B", "Italie")])

    def test_erreurs(self):
        _, erreurs = self.lire("  France")
        self.assertEqual(len(erreurs), 0)  # premier décalage = sommet
        _, erreurs = self.lire("France [Pays]")
        self.assertIn("rattaché", erreurs[0])
        _, erreurs = self.lire("G\n  A [Inconnu]")
        self.assertIn("inconnu", erreurs[0])
        _, erreurs = self.lire("G\n  France\n    A\n      Lyon\n        Trop bas")
        self.assertIn("trop bas", erreurs[0])
        _, erreurs = self.lire("G\n  France\n  Italie\n    France")
        self.assertIn("deux fois", erreurs[0])
