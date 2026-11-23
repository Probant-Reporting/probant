"""Visualisation v2 : points d'accès JSON des vues (créer, enregistrer, conflit, dupliquer, supprimer, partager, ordre,
vue par défaut, vue d'accueil), droits par rôle, CSRF, limites, Excel égal au JSON ; un lecteur ou un auditeur
n'écrit aucune valeur, aucune ligne de journal ni aucune alerte."""
import io

from django.test import Client
from django.urls import reverse
from openpyxl import load_workbook


from . import lecture_seule as LS
from . import vues_visu as VV
from .models import AccueilVisu, Journal, PreferenceVisu, VueVisu
from .aides_tests.vues import Base

VISUELS = [{"id": "a1", "type": "organisations", "kpis": ["EFF"]}, {"id": "a2", "type": "chiffre", "kpis": ["EFF"]}]


class VuesTests(Base):
    def test_creer_enregistrer_conflit(self):
        self.client.force_login(self.contrib)
        rep = self.post("visu_vue_creer", {"nom": "Ma vue", "partage": True, "visuels": VISUELS})
        self.assertEqual(rep.status_code, 201, rep.content)
        v = VueVisu.objects.get(pk=rep.json()["vue"]["id"])
        self.assertEqual((v.proprietaire, v.partage, v.version), (self.contrib, False, 1))  # seul l'admin partage
        rep = self.post("visu_vue_enregistrer", {"version": 1, "nom": "Renommée"}, [v.pk])
        self.assertEqual(rep.status_code, 200)
        v.refresh_from_db()
        self.assertEqual((v.nom, v.version, len(v.visuels)), ("Renommée", 2, 2))  # enregistrement partiel
        rep = self.post("visu_vue_enregistrer", {"version": 1, "visuels": []}, [v.pk])
        self.assertEqual(rep.status_code, 409)
        self.assertIn("modifiée entre-temps", rep.json()["erreurs"][0]["message"])
        rep = self.post("visu_vue_enregistrer", {"version": 2, "visuels": [{"type": "chiffre", "kpis": ["OUI"]}]}, [v.pk])
        self.assertEqual(rep.status_code, 400)  # KPI hors de son périmètre
        self.assertEqual(rep.json()["erreurs"][0]["message"], "Visuel 1 : « OUI » n'est pas un KPI que vous pouvez voir.")
        self.assertEqual(Journal.objects.filter(action="vue_partagee").count(), 0)  # vue personnelle : pas de journal

    def test_vue_convertie_de_plus_de_40_visuels_reste_modifiable(self):
        """Un ancien tableau de 45 tuiles converti sans perte : ses visuels se modifient encore, sans en ajouter."""
        tuiles = [{"id": f"t9-{i}", "type": "chiffre", "kpis": ["EFF"], "largeur": 3, "hauteur": "m"} for i in range(1, 46)]
        v = VueVisu.objects.create(nom="Ancien tableau", proprietaire=self.admin, visuels=tuiles, ancien_tableau=9)
        self.client.force_login(self.admin)
        modifies = [{**x, "titre": f"Chiffre {i}"} for i, x in enumerate(tuiles)]
        rep = self.post("visu_vue_enregistrer", {"version": 1, "visuels": modifies}, [v.pk])
        self.assertEqual(rep.status_code, 200, rep.content)
        rep = self.post("visu_vue_enregistrer", {"version": 2, "visuels": modifies + [{"type": "chiffre", "kpis": ["EFF"]}]}, [v.pk])
        self.assertEqual(rep.status_code, 400)
        self.assertIn("a 45 visuels, plus que les 40 permis", rep.json()["erreurs"][0]["message"])
        self.assertEqual(self.post("visu_vue_enregistrer", {"version": 2, "visuels": modifies[:44]}, [v.pk]).status_code, 200)
        v.refresh_from_db()
        self.assertEqual((len(v.visuels), v.visuels[0]["titre"]), (44, "Chiffre 0"))
        page = self.client.get(reverse("collecte:visu_vue", args=[v.pk]))
        self.assertEqual(page.context["contexte_visu"]["limites"]["visuels"], 44)

    def test_vue_partagee_reservee_a_l_admin(self):
        for u in (self.contrib, self.lecteur, self.auditeur):
            with self.subTest(role=u.role):
                self.client.force_login(u)
                self.assertEqual(self.post("visu_vue_enregistrer", {"version": 1, "nom": "X"}, [self.partagee.pk]).status_code, 403)
                self.assertEqual(self.post("visu_vue_supprimer", {}, [self.partagee.pk]).status_code, 403)
                self.assertEqual(self.post("visu_vue_partage", {"partage": False}, [self.partagee.pk]).status_code, 403)
                self.assertEqual(self.post("visu_vue_preferee", {"accueil": True}, [self.partagee.pk]).status_code, 403)
                self.assertEqual(self.post("visu_vue_preferee", {"accueil": ["contributeur"]}, [self.partagee.pk]).status_code, 403)
                self.assertEqual(self.client.get(reverse("collecte:visu_vue_donnees", args=[self.partagee.pk])).status_code, 200)
        self.partagee.refresh_from_db()
        self.assertEqual((self.partagee.nom, self.partagee.partage), ("Comité", True))
        self.assertFalse(AccueilVisu.objects.exists())

    def test_admin_partage_journal_accueil(self):
        self.client.force_login(self.admin)
        rep = self.post("visu_vue_creer", {"nom": "Énergie", "visuels": VISUELS})
        v = VueVisu.objects.get(pk=rep.json()["vue"]["id"])
        self.assertEqual(self.post("visu_vue_preferee", {"accueil": True}, [v.pk]).status_code, 403)  # pas encore partagée
        self.assertEqual(self.post("visu_vue_partage", {"partage": True}, [v.pk]).status_code, 200)
        v.refresh_from_db()
        self.assertTrue(v.partage)
        self.assertEqual(self.post("visu_vue_preferee", {"accueil": True}, [v.pk]).status_code, 200)  # tous les rôles
        self.assertEqual(AccueilVisu.roles_de(v), AccueilVisu.ROLES)
        rep = self.post("visu_vue_preferee", {"accueil": ["contributeur", "validateur"]}, [self.partagee.pk])
        self.assertEqual(rep.json()["message"], "« Comité » est la vue d'accueil de : Validateurs, Contributeurs.")
        self.assertEqual(rep.json()["vue"]["accueil"], ["validateur", "contributeur"])
        accueils = dict(AccueilVisu.objects.values_list("role", "vue_id"))  # une seule vue d'accueil par rôle
        self.assertEqual(accueils, {"admin": v.pk, "validateur": self.partagee.pk, "contributeur": self.partagee.pk,
                                    "lecteur": v.pk, "auditeur": v.pk})
        self.assertEqual(self.post("visu_vue_preferee", {"accueil": ["inconnu"]}, [v.pk]).status_code, 400)
        rep = self.post("visu_vue_preferee", {"accueil": []}, [self.partagee.pk])
        self.assertEqual(rep.json()["message"], "« Comité » n'est la vue d'accueil d'aucun rôle.")
        self.assertEqual(self.post("visu_vue_enregistrer", {"version": v.version, "nom": "Énergie et climat"}, [v.pk]).status_code, 200)
        self.assertEqual(self.post("visu_vue_partage", {"partage": False}, [v.pk]).status_code, 200)  # plus partagée :
        self.assertFalse(AccueilVisu.objects.exists())  # plus la vue d'accueil de personne
        self.assertEqual(self.post("visu_vue_supprimer", {}, [v.pk]).status_code, 200)
        champs = list(Journal.objects.filter(action="vue_partagee").values_list("champ", flat=True))
        self.assertEqual(champs.count("vue d'accueil (Lecteurs)"), 2)  # pour « Énergie », puis retirée en ne la partageant plus
        self.assertEqual(champs.count("vue d'accueil (Contributeurs)"), 3)  # Énergie, puis Comité, puis plus aucune
        self.assertEqual(sorted(set(champs) - {f"vue d'accueil ({VV.nom_role(r)})" for r in AccueilVisu.ROLES}), ["modification", "partage"])
        entree = Journal.objects.filter(action="vue_partagee", champ="vue d'accueil (Contributeurs)").order_by("date", "pk")[1]
        self.assertEqual((entree.avant, entree.apres, entree.objet_id), ("Énergie", "Comité", str(self.partagee.pk)))
        self.assertTrue(all(e.objet == "VueVisu" for e in Journal.objects.filter(action="vue_partagee")))
        self.client.force_login(self.lecteur)
        self.assertContains(self.client.get(reverse("collecte:admin_journal")), "", status_code=403)

    def test_dupliquer_ordre_defaut(self):
        self.client.force_login(self.lecteur)
        rep = self.post("visu_vue_dupliquer", {}, [self.partagee.pk])
        self.assertEqual(rep.status_code, 201)
        copie = VueVisu.objects.get(pk=rep.json()["vue"]["id"])
        self.assertEqual((copie.nom, copie.proprietaire, copie.partage, copie.visuels), ("Copie de Comité", self.lecteur, False, VISUELS))
        self.assertIn("?modifier=1", rep.json()["url"])
        perso_admin = VueVisu.objects.create(nom="Perso admin", proprietaire=self.admin)
        rep = self.post("visu_vues_ordre", {"ordre": [copie.pk, perso_admin.pk, self.partagee.pk], "partagees": True})
        self.assertEqual(rep.json()["ordre"], [copie.pk, self.partagee.pk])  # la vue d'autrui est ignorée
        self.assertEqual(self.post("visu_vue_preferee", {"defaut": True}, [copie.pk]).status_code, 200)
        pref = PreferenceVisu.objects.get(utilisateur=self.lecteur)
        self.assertEqual((pref.vue_defaut, pref.ordre), (copie, [copie.pk, self.partagee.pk]))
        self.assertEqual(self.client.get(reverse("collecte:visu_vue_donnees", args=[perso_admin.pk])).status_code, 404)
        self.assertEqual(self.post("visu_vue_supprimer", {}, [copie.pk]).status_code, 200)  # sa vue à lui
        # dans la corbeille : elle ne s'ouvre plus par défaut ; la préférence reste, « Annuler » la rend telle quelle
        from .vues_visualisation import vue_ouverte

        self.assertNotEqual(vue_ouverte(self.lecteur), copie)
        pref.refresh_from_db()
        self.assertEqual(pref.vue_defaut_id, copie.pk)

    def test_lecteur_et_auditeur_n_ecrivent_rien(self):
        for u in (self.lecteur, self.auditeur):
            with self.subTest(role=u.role):
                avant = self.compter()
                self.client.force_login(u)
                rep = self.post("visu_vue_creer", {"nom": "Perso", "partage": True, "accueil": True, "visuels": VISUELS})
                self.assertEqual(rep.status_code, 201)
                v = VueVisu.objects.get(pk=rep.json()["vue"]["id"])
                self.assertEqual((v.partage, AccueilVisu.objects.filter(vue=v).exists()), (False, False))
                self.assertEqual(self.post("visu_vue_partage", {"partage": True}, [v.pk]).status_code, 403)
                self.assertEqual(self.post("visu_donnees", {"visuels": VISUELS}).status_code, 200)
                self.assertEqual(self.post("visu_excel", {"visuels": VISUELS}).status_code, 200)
                self.assertEqual(self.post("visu_vue_enregistrer", {"version": 1, "nom": "Perso 2"}, [v.pk]).status_code, 200)
                self.assertEqual(self.compter(), avant)

    def test_csrf_et_limites(self):
        c = Client(enforce_csrf_checks=True)
        c.force_login(self.contrib)
        self.assertEqual(self.post("visu_vue_creer", {"nom": "X", "visuels": []}, client=c).status_code, 403)
        self.client.force_login(self.contrib)
        rep = self.client.post(reverse("collecte:visu_vue_creer"), b"{" + b" " * (201 * 1024) + b"}", content_type="application/json")
        self.assertEqual(rep.status_code, 413)
        rep = self.client.post(reverse("collecte:visu_vue_creer"), b"pas du json", content_type="application/json")
        self.assertEqual(rep.status_code, 400)
        rep = self.post("visu_vue_creer", {"nom": "X", "visuels": [{"type": "chiffre"}] * 41})
        self.assertEqual(rep.status_code, 400)
        self.assertEqual(rep.json()["erreurs"][0]["message"], "Une vue contient 40 visuels au plus.")
        self.assertEqual(self.post("visu_vue_creer", {"nom": "X", "visuels": [{"type": "chiffre"}] * 40}).status_code, 201)
        self.assertEqual(self.client.get(reverse("collecte:visu_vue_creer")).status_code, 405)


class DonneesTests(Base):
    def test_donnees_d_une_vue_et_filtres_dans_l_adresse(self):
        self.client.force_login(self.admin)
        rep = self.client.get(reverse("collecte:visu_vue_donnees", args=[self.partagee.pk]),
                              {"org": self.p.pk, "periode": self.c.periode.pk, "brouillons": "1"})
        d = rep.json()
        self.assertEqual(d["ordre"], ["a1", "a2"])
        self.assertEqual(d["visuels"]["a1"]["series"][0]["textes"], ["110 ETP", "40 ETP"])
        self.assertTrue(d["filtres"]["differents"])
        # la page envoie toujours l'organisation affichée : celle que la vue montre déjà n'est ni un changement, ni fixée
        # dans les filtres à enregistrer (la vue continue de suivre le périmètre de chacun)
        url = reverse("collecte:visu_vue_donnees", args=[self.partagee.pk])
        f = self.client.get(url, {"org": self.g.pk, "periode": "auto", "cmp": "n1", "ref": "je_reponds_a", "brouillons": "0"}).json()["filtres"]
        self.assertEqual((f["differents"], f["brut"]["org"], f["org"]["id"]), (False, None, self.g.pk))
        f = self.client.get(url, {"org": self.g.pk, "brouillons": "1"}).json()["filtres"]
        self.assertEqual((f["differents"], f["brut"]["org"], f["brut"]["valeurs"]), (True, None, "brouillons"))
        f = self.client.get(url, {"org": self.p.pk, "brouillons": "0"}).json()["filtres"]  # une autre organisation : fixée
        self.assertEqual((f["differents"], f["brut"]["org"]), (True, self.p.pk))

    def test_definition_non_enregistree(self):
        self.client.force_login(self.contrib)
        rep = self.post("visu_donnees", {"visuels": [{"id": "x", "type": "auto", "kpis": ["EFF"]}], "parametres": {"brouillons": "1"}})
        d = rep.json()
        self.assertEqual(d["visuels"]["x"]["type"], "chiffre")
        self.assertEqual(d["visuels"]["x"]["definition"]["type"], "chiffre")
        rep = self.post("visu_donnees", {"visuels": [{"id": "x", "type": "chiffre", "kpis": ["OUI"]}]})
        self.assertEqual(rep.status_code, 400)

    def test_catalogue(self):
        self.client.force_login(self.contrib)
        d = self.client.get(reverse("collecte:visu_catalogue")).json()
        self.assertEqual({k["code"] for k in d["kpis"]}, {"EFF", "TX"})  # ses KPI
        self.assertEqual(d["autres"][0]["type"], "remplissage")
        self.client.force_login(self.admin)
        codes = {k["code"] for k in self.client.get(reverse("collecte:visu_catalogue")).json()["kpis"]}
        self.assertTrue({"EFF", "TX", "DBL", "OUI", "GRP"} <= codes)


class ExcelTests(Base):
    def test_excel_egal_au_json(self):
        self.client.force_login(self.admin)
        params = {"org": self.p.pk, "periode": self.c.periode.pk, "brouillons": "1"}
        d = self.client.get(reverse("collecte:visu_vue_donnees", args=[self.partagee.pk]), params).json()
        rep = self.client.get(reverse("collecte:visu_vue_excel", args=[self.partagee.pk]), {**params, "visuel": "a1"})
        self.assertEqual(rep.status_code, 200)
        self.assertIn("Visualisation_Comite_", rep["Content-Disposition"])
        wb = load_workbook(io.BytesIO(rep.content))
        self.assertEqual(wb.sheetnames, ["À lire", "Données"])
        lignes = list(wb["Données"].iter_rows(values_only=True))
        self.assertEqual(lignes[0], ("Organisation", "2026", "2025", "Écart", "État"))
        self.assertEqual(lignes[1][:3], ("E1", 110, 100))
        self.assertEqual(lignes[1][4], "provisoire")
        self.assertEqual([l[1] for l in lignes[1:]], d["visuels"]["a1"]["series"][0]["valeurs"])
        a_lire = " ".join(str(c) for r in wb["À lire"].iter_rows(values_only=True) for c in r if c)
        for texte in ("Comité", "Données de votre périmètre", "Brouillons compris", "Période : 2026"):
            self.assertIn(texte, a_lire)
        rep = self.client.get(reverse("collecte:visu_vue_excel", args=[self.partagee.pk]), params)  # toute la vue
        wb = load_workbook(io.BytesIO(rep.content))
        self.assertEqual(len(wb.sheetnames), 3)
        self.assertEqual(self.client.get(reverse("collecte:visu_vue_excel", args=[self.partagee.pk]), {"visuel": "zz"}).status_code, 404)

    def test_pourcentage_de_0_a_100(self):
        self.client.force_login(self.admin)
        rep = self.post("visu_excel", {"nom": "Taux", "visuels": [{"id": "t", "type": "tableau", "kpis": ["TX"]}],
                                       "parametres": {"org": str(self.e1.pk), "periode": str(self.c.periode.pk), "brouillons": "1"}})
        lignes = list(load_workbook(io.BytesIO(rep.content))["Données"].iter_rows(values_only=True))
        self.assertEqual(lignes[1][1], 35)


class LectureSeuleNomsTests(Base):
    def test_ensembles_du_middleware(self):
        nouveaux = {"visu_vue", "visu_vue_nouvelle", "visu_catalogue", "visu_vue_donnees", "visu_donnees", "visu_vue_creer",
                    "visu_vue_enregistrer", "visu_vue_dupliquer", "visu_vue_supprimer", "visu_vue_partage", "visu_vues_ordre",
                    "visu_vue_preferee", "visu_vue_excel", "visu_excel"}
        self.assertTrue(nouveaux <= LS.PAGES_LECTEUR)
        self.assertNotIn("visu_vue_partage", LS.ECRITURES_PERMISES)
        self.assertTrue({"visu_donnees", "visu_excel", "visu_vue_creer", "visu_vue_enregistrer", "visu_vue_dupliquer",
                         "visu_vue_supprimer", "visu_vues_ordre", "visu_vue_preferee"} <= LS.ECRITURES_PERMISES)
        self.client.force_login(self.lecteur)
        rep = self.post("visu_vue_partage", {"partage": True}, [self.partagee.pk])
        self.assertEqual(rep.status_code, 403)  # refusé par le middleware, avant la vue


class PageTests(Base):
    def test_page_d_une_vue(self):
        self.client.force_login(self.lecteur)
        rep = self.client.get(reverse("collecte:visu_vue", args=[self.partagee.pk]), {"org": self.p.pk, "periode": self.c.periode.pk, "brouillons": "1"})
        self.assertEqual(rep.status_code, 200)
        self.assertContains(rep, 'id="visu-contexte"')
        self.assertContains(rep, 'id="visu-donnees"')
        self.assertContains(rep, "<noscript>")
        self.assertContains(rep, "110 ETP (provisoire)")  # tableau de données sans script
        self.assertContains(rep, "vendor/echarts-6.1.0/echarts.min.js")
        self.assertContains(rep, 'aria-current="page"')
        self.assertContains(rep, 'name="brouillons"')
        self.assertNotContains(rep, "{#")  # aucun commentaire de gabarit affiché tel quel
        perso = VueVisu.objects.create(nom="Perso admin", proprietaire=self.admin)
        self.assertEqual(self.client.get(reverse("collecte:visu_vue", args=[perso.pk])).status_code, 404)
        # en modification : la barre du haut (Annuler, Enregistrer la vue, raccourci Ctrl + S) est dans la page
        self.client.force_login(self.admin)
        rep = self.client.get(reverse("collecte:visu_vue", args=[self.partagee.pk]), {"modifier": "1"})
        self.assertContains(rep, "data-barre-haut")
        self.assertContains(rep, 'aria-keyshortcuts="Control+S Meta+S"', count=2)
        self.assertNotContains(rep, "{#")
        self.assertNotContains(rep, "{%")

    def test_vue_de_depart_et_lien_d_essai(self):
        self.client.force_login(self.contrib)
        rep = self.client.get(reverse("collecte:visu"))
        self.assertContains(rep, reverse("collecte:visu_vue", args=[self.partagee.pk]))  # « Essayer la nouvelle Visualisation »
        rep = self.client.get(reverse("collecte:visu_vue_nouvelle") + "?depart=1")
        self.assertEqual(rep.status_code, 200)
        self.assertContains(rep, "Vue de départ")
        self.assertContains(rep, "Enregistrer comme vue")
