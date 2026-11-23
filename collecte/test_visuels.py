"""Moteur des visuels de la Visualisation v2 (collecte/visuels/) : formes par défaut, compatibilités, validées et
brouillons, N et N-1, taux de remplissage, périmètre, nombre de requêtes, définitions invalides."""
import json
from decimal import Decimal

from django.db import connection
from django.test.utils import CaptureQueriesContext

from referentiel.models import KPI, Attribution, Niveau, Organisation, Utilisateur

from . import saisie as S
from . import visuels as VS
from .models import Reponse
from .aides_tests.visuels import AvecKpis, vue

D = Decimal


class FormesTests(AvecKpis):
    def test_forme_par_defaut_selon_le_format(self):
        d = self.donnees(self.admin, {"type": "auto", "kpis": ["EFF"]}, {"type": "auto", "kpis": ["OUI"]},
                         {"type": "auto", "kpis": ["EFF", "EFF2"]}, {"type": "auto", "kpis": ["EFF", "TX"]},
                         {"type": "auto", "kpis": ["GRP"]}, {"type": "auto", "source": "filtre_theme"}, {"type": "auto"},
                         parametres={"org": str(self.p.id), "periode": str(self.c.periode.pk)})
        types = [d["visuels"][f"v{i}"]["type"] for i in range(1, 8)]
        self.assertEqual(types, ["chiffre", "anneau", "courbe", "tableau", "chiffre", "tableau", "remplissage"])
        self.assertEqual([d["visuels"][f"v{i}"]["largeur"] for i in (1, 2, 3, 4)], [3, 4, 6, 12])
        self.assertEqual(d["visuels"]["v1"]["definition"]["type"], "chiffre")  # définition résolue renvoyée

    def test_oui_non_sans_organisation_dessous(self):
        d = self.donnees(self.admin, {"type": "auto", "kpis": ["OUI"]}, parametres={"org": str(self.e1.id)})
        self.assertEqual(d["visuels"]["v1"]["type"], "chiffre")  # rien en dessous : la réponse elle-même
        self.assertEqual(d["visuels"]["v1"]["chiffre"]["lignes"][0]["texte"], "Oui")

    def test_compatibilites(self):
        d = self.donnees(self.admin, {"type": "anneau", "kpis": ["TX"]}, {"type": "organisations", "kpis": ["GRP"]},
                         {"type": "barres", "kpis": ["OUI"]}, {"type": "anneau", "kpis": ["DBL"]},
                         {"type": "courbe", "kpis": ["EFF", "TX"]})
        v = d["visuels"]
        self.assertEqual((v["v1"]["etat"], v["v1"]["message"]), ("incompatible", "Un pourcentage ne s'additionne pas."))
        self.assertEqual(v["v2"]["message"], "Ce KPI se saisit au niveau Groupe. Il n'y a rien à comparer en dessous.")
        self.assertIn("barres empilées", v["v3"]["message"])
        self.assertEqual(v["v4"]["etat"], "ok")  # calculé additionnable
        self.assertEqual(v["v5"]["message"], "Les KPI n'ont pas la même unité.")
        self.assertIs(v["v1"]["compatibles"]["chiffre"], True)
        self.assertIn("organisations", v["v4"]["suggestions"])
        self.assertNotIn("anneau", v["v1"]["suggestions"])

    def test_les_neuf_formes_et_leur_tableau(self):
        S.valider(self.contrib, self.c, self.eff, self.e1)
        S.valider(self.admin, self.c, self.eff, self.e2)
        d = self.donnees(self.admin, *[{"type": t, "kpis": ["EFF"]} for t in VS.TYPES if t != "remplissage"],
                         {"type": "remplissage"}, parametres={"org": str(self.p.id), "periode": str(self.c.periode.pk)})
        for p in d["visuels"].values():
            with self.subTest(forme=p["type"]):
                self.assertEqual(p["etat"], "ok", p["message"])
                self.assertTrue(p["tableau"]["entetes"])
                self.assertTrue(p["resume"].startswith(VS.lib(f"visu.type.{p['type']}")))
                json.dumps(p)  # tout se sérialise
        orgs = d["visuels"]["v7"]
        self.assertEqual([c["libelle"] for c in orgs["categories"]], ["E1", "E2"])
        self.assertEqual(orgs["series"][0]["valeurs"], [110.0, 40.0])
        self.assertEqual(orgs["series"][0]["textes"], ["110 ETP", "40 ETP"])
        self.assertEqual(orgs["series"][1]["role"], "repere")
        self.assertEqual(orgs["series"][1]["textes"], ["100 ETP", "30 ETP"])
        self.assertEqual(orgs["tableau"]["lignes"][0]["cellules"][3]["t"], "▲ +10,0\u202f%")
        anneau = d["visuels"]["v5"]
        self.assertEqual(anneau["total"], "150 ETP")
        self.assertEqual(anneau["series"][0]["textes"], ["110 ETP · 73,3\u202f%", "40 ETP · 26,7\u202f%"])
        chiffre = d["visuels"]["v1"]["chiffre"]["lignes"][0]
        self.assertEqual((chiffre["texte"], chiffre["comparaison"]["texte"], chiffre["ecart"]["texte"]), ("150 ETP", "130 ETP", "▲ +15,4\u202f%"))
        empile = d["visuels"]["v3"]
        self.assertEqual(empile["totaux"][-1], "150 ETP")  # total du moteur, pas une somme du navigateur

    def test_kpi_sans_aucune_valeur_un_message_pas_des_axes_vides(self):
        KPI.objects.create(code="VIDE", libelle="Jamais saisi", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                           methode_agregation="Somme", unite=self.eff.unite)
        formes = ["barres", "barres_empilees", "courbe", "anneau", "organisations", "comparaison_n1"]
        d = self.donnees(self.admin, *[{"type": t, "kpis": ["VIDE"]} for t in formes], {"type": "chiffre", "kpis": ["VIDE"]},
                         {"type": "organisations", "kpis": ["EFF"]}, parametres={"org": str(self.p.id)})
        for i, forme in enumerate(formes, start=1):
            with self.subTest(forme=forme):
                p = d["visuels"][f"v{i}"]
                if forme in ("courbe", "comparaison_n1"):  # une seule période ici : déjà dit autrement
                    self.assertEqual(p["etat"], "incompatible")
                else:
                    self.assertEqual((p["etat"], p["message"]), ("vide", "Rien à montrer pour ces filtres."))
        self.assertEqual(d["visuels"]["v7"]["etat"], "ok")  # le chiffre clé dit « – » lui-même
        self.assertEqual(d["visuels"]["v8"]["etat"], "ok")  # un KPI qui a des valeurs reste dessiné
        self.assertFalse(VS.sans_rien_a_dessiner([{"valeurs": [None], "etats": ["attente"]}]))  # en attente : dessiné
        self.assertFalse(VS.sans_rien_a_dessiner([]))

    def test_oui_non_decompte(self):
        d = self.donnees(self.admin, {"type": "anneau", "kpis": ["OUI"]}, {"type": "barres_empilees", "kpis": ["OUI"]},
                         {"type": "organisations", "kpis": ["OUI"]}, parametres={"org": str(self.p.id)})
        a = d["visuels"]["v1"]
        self.assertEqual([c["libelle"] for c in a["categories"]], ["Oui", "Non"])
        self.assertEqual(a["series"][0]["valeurs"], [1.0, 1.0])
        self.assertEqual(a["total"], "2 organisations")
        e = d["visuels"]["v2"]
        self.assertEqual([s["libelle"] for s in e["series"]], ["Oui", "Non"])
        o = d["visuels"]["v3"]
        self.assertTrue(o["liste"])
        self.assertEqual(o["series"][0]["textes"], ["Oui", "Non"])


class ValeursTests(AvecKpis):
    def test_validees_seulement_puis_brouillons(self):
        params = {"org": str(self.p.id), "periode": str(self.c.periode.pk)}
        d = self.donnees(self.admin, {"type": "organisations", "kpis": ["EFF"]}, {"type": "chiffre", "kpis": ["EFF"]}, parametres=params)
        o = d["visuels"]["v1"]
        self.assertEqual(o["series"][0]["etats"], ["attente", "attente"])
        self.assertEqual(o["series"][0]["valeurs"], [None, None])  # pas de barre
        self.assertEqual(o["series"][0]["textes"], ["en attente de validation"] * 2)
        self.assertEqual(d["etat"]["nb_attente"], 3)  # E1, E2 et le total du pays
        self.assertIn("3 valeurs en attente de validation pour 2026", d["etat"]["phrase"])
        d = self.donnees(self.admin, {"type": "organisations", "kpis": ["EFF"]}, parametres={**params, "brouillons": "1"})
        o = d["visuels"]["v1"]
        self.assertEqual(o["series"][0]["etats"], ["provisoire", "provisoire"])
        self.assertEqual(o["series"][0]["valeurs"], [110.0, 40.0])
        self.assertIn("(provisoire)", o["tableau"]["lignes"][0]["cellules"][1]["t"])
        self.assertEqual(d["etat"]["nb_provisoires"], 2)
        self.assertEqual(d["filtres"]["valeurs"], "brouillons")

    def test_n_et_n1(self):
        d = self.donnees(self.admin, {"type": "comparaison_n1", "kpis": ["EFF"]}, {"type": "comparaison_n1", "kpis": ["EFF", "TX"]},
                         parametres={"org": str(self.p.id), "periode": str(self.c.periode.pk), "brouillons": "1"})
        a = d["visuels"]["v1"]
        self.assertEqual((a["mode"], [s["cle"] for s in a["series"]]), ("valeurs", ["n", "cmp"]))
        self.assertEqual(a["series"][1]["valeurs"], [100.0, 30.0])
        b = d["visuels"]["v2"]
        self.assertEqual(b["mode"], "ecart")  # unités différentes : l'écart en %
        self.assertEqual(b["series"][0]["textes"][0], "▲ +15,4\u202f%")
        d = self.donnees(self.admin, {"type": "comparaison_n1", "kpis": ["EFF"]},
                         parametres={"org": str(self.p.id), "periode": str(self.c0.periode.pk)})
        self.assertEqual(d["visuels"]["v1"]["message"], "Aucune période de comparaison.")

    def test_periode_precedente_et_filtres_du_visuel(self):
        d = self.donnees(self.admin, {"type": "chiffre", "kpis": ["EFF"], "filtres": {"periode": self.c.periode.pk, "valeurs": "brouillons"}},
                         {"type": "chiffre", "kpis": ["EFF"]}, parametres={"org": str(self.p.id), "cmp": "p1"})
        v1, v2 = d["visuels"]["v1"], d["visuels"]["v2"]
        self.assertEqual(v1["chiffre"]["lignes"][0]["texte"], "150 ETP")
        self.assertIn("Filtres propres : 2026 · Brouillons compris", v1["sous_titre"])
        self.assertEqual(v2["chiffre"]["lignes"][0]["texte"], "130 ETP")  # 2025, période de la vue

    def test_filtre_enregistre_inapplicable(self):
        d = self.donnees(self.admin, {"type": "chiffre", "kpis": ["EFF"]}, filtres={"org": 999999, "periode": 999999})
        self.assertEqual(d["filtres"]["org"]["nom"], "Groupe")
        self.assertEqual(d["filtres"]["periode"]["libelle"], "2025")
        self.assertEqual(len(d["avertissements"]), 2)


class RemplissageTests(AvecKpis):
    def test_identique_au_tableau_de_bord(self):
        tdb = S.tableau_de_bord(S.lignes(self.admin, self.c))
        d = self.donnees(self.admin, {"type": "remplissage", "options": {"remplissage_par": "total"}},
                         {"type": "remplissage"}, parametres={"periode": str(self.c.periode.pk)})
        t = d["visuels"]["v1"]
        self.assertEqual([s["valeurs"][0] for s in t["series"]], [tdb["total"].valide, tdb["total"].brouillon, tdb["total"].a_saisir])
        self.assertEqual(t["taux_total"], f"{VS.nombre(D(str(tdb['total'].taux)), 1)}\u202f%")
        par_org = dict(tdb["par_org"])
        o = d["visuels"]["v2"]
        self.assertEqual([c["libelle"] for c in o["categories"]], ["Groupe", "Pays"])
        self.assertEqual(o["series"][0]["valeurs"][0], par_org[self.g].valide)
        self.assertEqual(o["categories"][0]["cases"], par_org[self.g].total)


class PerimetreTests(AvecKpis):
    def _json(self, u, **params):
        d = self.donnees(u, {"type": "organisations", "kpis": ["EFF"]}, {"type": "anneau", "kpis": ["EFF"]},
                         {"type": "chiffre", "kpis": ["EFF"]}, {"type": "tableau", "source": "filtre_theme"},
                         {"type": "barres", "kpis": ["EFF"], "axe": "organisations"}, {"type": "remplissage"},
                         parametres={"brouillons": "1", "periode": str(self.c.periode.pk), **params})
        return d, json.dumps(d, ensure_ascii=False)

    def test_contributeur(self):
        d, texte = self._json(self.contrib)
        self.assertNotIn("E2", texte)
        self.assertNotIn(f'"org": {self.e2.id}', texte)
        self.assertNotIn('"Pays"', texte)
        # aucun total hors de ses cases ; « 150 » seul pouvait être le morceau d'un identifiant (1508)
        self.assertNotRegex(texte, r"(?<![\d.])150(\.0)?(?![\d.])")
        self.assertEqual(d["filtres"]["org"]["nom"], "E1")
        self.assertEqual(d["visuels"]["v3"]["chiffre"]["lignes"][0]["texte"], "110 ETP")

    def test_contributeur_kpi_hors_perimetre_masque(self):
        d = self.donnees(self.contrib, {"type": "chiffre", "kpis": ["EFF"]}, {"type": "auto", "source": "filtre_theme"})
        self.assertIn("v1", d["visuels"])
        propre = [{"id": "x1", "type": "chiffre", "kpis": ["OUI"], "largeur": 3, "hauteur": "m"}]  # vue partagée par l'admin
        d = VS.donnees(self.contrib, {}, propre)
        self.assertEqual(d["visuels"], {})
        self.assertEqual(d["etat"]["masques"], 1)
        self.assertEqual(d["etat"]["phrase_masques"], "1 visuel de cette vue ne vous concerne pas.")

    def test_validateur(self):
        val = Utilisateur.objects.create(username="val", email="val@exemple.test", role=Utilisateur.Role.VALIDATEUR)
        Attribution.objects.create(kpi=self.eff, organisation=self.e2, utilisateur=val, role=Attribution.Role.VALIDATEUR)
        d, texte = self._json(val)
        self.assertNotIn('"E1"', texte)
        # la valeur de E1 (110 ETP) n'apparaît nulle part ; « 110 » seul pouvait être le morceau d'un identifiant (1110)
        self.assertNotIn("110 ETP", texte)
        self.assertNotRegex(texte, r"(?<![\d.])110(\.0)?(?![\d.])")
        self.assertEqual(d["filtres"]["org"]["nom"], "E2")

    def test_lecteur_limite(self):
        lecteur = Utilisateur.objects.create(username="lec", email="lec@exemple.test", role=Utilisateur.Role.LECTEUR)
        autre = Organisation.objects.create(nom="Autre pays", niveau_id=Niveau.COUNTRY, parent=self.g)
        Organisation.objects.create(nom="Filiale secrète", niveau_id=Niveau.ENTITY, parent=autre)
        lecteur.perimetre_lecture.set([self.p])
        d, texte = self._json(lecteur)
        for nom in ("Groupe", "Autre pays", "Filiale secrète"):
            self.assertNotIn(nom, texte)
        self.assertNotIn(f'"org": {self.g.id},', texte)
        self.assertEqual(d["filtres"]["org"]["nom"], "Pays")
        d, texte = self._json(lecteur, org=str(self.g.id))  # adresse forgée : ignorée
        self.assertEqual(d["filtres"]["org"]["nom"], "Pays")
        self.assertNotIn("Groupe", texte)

    def test_plusieurs_sommets(self):
        lecteur = Utilisateur.objects.create(username="lec2", email="lec2@exemple.test", role=Utilisateur.Role.LECTEUR)
        lecteur.perimetre_lecture.set([self.e1, self.e2])
        d = self.donnees(lecteur, {"type": "chiffre", "kpis": ["EFF"]}, parametres={"brouillons": "1", "periode": str(self.c.periode.pk)})
        self.assertTrue(d["filtres"]["org"]["tout"])
        lignes = d["visuels"]["v1"]["chiffre"]["lignes"]
        self.assertEqual([(l["org"], l["texte"]) for l in lignes], [("E1", "110 ETP"), ("E2", "40 ETP")])  # aucun total
        # « 150 ETP » et non « 150 » seul : sous PostgreSQL, un numéro d'organisation (1505…) contient ces chiffres
        self.assertNotIn("150 ETP", json.dumps(d))
        self.assertNotIn('"v": 150', json.dumps(d))


class RequetesTests(AvecKpis):
    def test_meme_plafond_pour_1_et_12_visuels(self):
        formes = [{"type": "chiffre", "kpis": ["EFF"]}, {"type": "barres", "kpis": ["EFF"]}, {"type": "organisations", "kpis": ["EFF"]},
                  {"type": "anneau", "kpis": ["EFF"]}, {"type": "courbe", "kpis": ["EFF", "EFF2"]},
                  {"type": "comparaison_n1", "kpis": ["EFF"]}]
        un = vue(formes[0])
        douze = vue(*(formes * 2))
        propre1, _ = VS.valider_vue({"nom": "a", "visuels": un}, self.admin)
        propre12, _ = VS.valider_vue({"nom": "a", "visuels": douze}, self.admin)
        params = {"org": str(self.p.id)}
        VS.donnees(self.admin, {}, propre12["visuels"], params)  # caches de l'installation (niveaux, instance)
        with CaptureQueriesContext(connection) as q1:
            VS.donnees(self.admin, {}, propre1["visuels"], params)
        with CaptureQueriesContext(connection) as q12:
            d = VS.donnees(self.admin, {}, propre12["visuels"], params)
        self.assertEqual(len(d["visuels"]), 12)
        self.assertLessEqual(len(q12), len(q1) + 2, [q["sql"][:120] for q in q12.captured_queries])
        self.assertLess(len(q12), 60)


class ValidationTests(AvecKpis):
    def test_definitions_invalides(self):
        cas = [
            ({"nom": "", "visuels": []}, "La vue n'a pas de nom. Saisissez un nom pour la retrouver."),
            ({"nom": "x", "visuels": [{"id": "A B", "type": "chiffre"}]}, "l'identifiant n'est pas valide"),
            ({"nom": "x", "visuels": [{"id": "a", "type": "chiffre"}, {"id": "a", "type": "chiffre"}]}, "en double"),
            ({"nom": "x", "visuels": [{"type": "jauge"}]}, "forme inconnue « jauge »"),
            ({"nom": "x", "visuels": [{"type": "chiffre", "kpis": ["INCONNU"]}]}, "« INCONNU » n'est pas un KPI que vous pouvez voir"),
            ({"nom": "x", "visuels": [{"type": "chiffre", "options": {"repere": "oui"}}]}, "le réglage « repere » n'est pas valide"),
            ({"nom": "x", "visuels": [{"type": "chiffre", "options": {"script": 1}}]}, "le réglage « script » n'est pas valide"),
            ({"nom": "x", "visuels": [{"type": "barres", "kpis": ["EFF"] * 1 + [f"K{i}" for i in range(9)]}]}, "8 KPI au plus"),
            ({"nom": "x", "visuels": [{"type": "chiffre"}] * 41}, "Une vue contient 40 visuels au plus."),
            ({"nom": "x", "visuels": [{"type": "tableau", "source": "liste:abc"}]}, "la liste ou le thème n'existe plus"),
            ({"nom": "x", "filtres": {"org": "<script>"}, "visuels": []}, "Le filtre « org » n'est pas valide"),
            ({"nom": "x", "visuels": [{"type": "chiffre", "filtres": {"nb_periodes": 99}}]}, "le réglage « nb_periodes » n'est pas valide"),
        ]
        for donnees, attendu in cas:
            with self.subTest(attendu=attendu):
                _, erreurs = VS.valider_vue(donnees, self.admin)
                self.assertTrue(any(attendu in e["message"] for e in erreurs), erreurs)

    def test_quarante_visuels_au_plus(self):
        propre, erreurs = VS.valider_vue({"nom": "x", "visuels": [{"type": "chiffre"}] * 40}, self.admin)
        self.assertEqual((erreurs, len(propre["visuels"])), ([], 40))
        self.assertEqual(len({v["id"] for v in propre["visuels"]}), 40)  # identifiants uniques
        # vue convertie d'un ancien tableau de 45 tuiles : elle reste modifiable, sans gagner de visuel
        _, erreurs = VS.valider_vue({"nom": "x", "visuels": [{"type": "chiffre"}] * 45}, self.admin, plafond=45)
        self.assertEqual(erreurs, [])
        _, erreurs = VS.valider_vue({"nom": "x", "visuels": [{"type": "chiffre"}] * 46}, self.admin, plafond=45)
        self.assertEqual(erreurs[0]["message"], "Cette vue a 45 visuels, plus que les 40 permis. Vous pouvez en "
                                                "retirer, mais pas en ajouter.")

    def test_kpi_hors_perimetre_refuse_au_contributeur(self):
        _, erreurs = VS.valider_vue({"nom": "x", "visuels": [{"type": "chiffre", "kpis": ["OUI"]}]}, self.contrib)
        self.assertEqual(erreurs[0]["message"], "Visuel 1 : « OUI » n'est pas un KPI que vous pouvez voir.")
        _, erreurs = VS.valider_vue({"nom": "x", "visuels": [{"type": "chiffre", "kpis": ["OUI"]}]}, self.contrib, anciens={"OUI"})
        self.assertEqual(erreurs, [])  # déjà dans la vue enregistrée : gardé

    def test_propre_et_identifiants(self):
        propre, erreurs = VS.valider_vue({"nom": " Ma vue ", "visuels": [{"type": "chiffre", "kpis": ["EFF"], "largeur": 5, "x": 1}]}, self.admin)
        self.assertEqual(erreurs, [])
        v = propre["visuels"][0]
        self.assertRegex(v["id"], VS.ID_VISUEL)
        self.assertEqual((propre["nom"], v["largeur"], v["hauteur"]), ("Ma vue", 3, "m"))
        self.assertNotIn("x", v)

    def test_taille_et_json(self):
        self.assertIsNotNone(VS.lire_json(b"{" * (VS.TAILLE_MAX + 1))[1])
        self.assertEqual(VS.lire_json(b"pas du json")[1], "La définition de la vue est illisible.")
        self.assertEqual(VS.lire_json(b'{"nom": "x"}'), ({"nom": "x"}, None))

    def test_visuel_en_erreur_n_empeche_pas_les_autres(self):
        from unittest import mock

        with mock.patch.dict(VS.CONSTRUCTEURS, {"courbe": mock.Mock(side_effect=ZeroDivisionError)}), self.assertLogs("reporting.visualisation"):
            d = self.donnees(self.admin, {"type": "courbe", "kpis": ["EFF"]}, {"type": "chiffre", "kpis": ["EFF"]},
                             parametres={"periode": str(self.c.periode.pk)})
        self.assertEqual(d["visuels"]["v1"]["etat"], "erreur")
        self.assertEqual(d["visuels"]["v1"]["message"], "Ce visuel n'a pas pu être calculé.")
        self.assertEqual(d["visuels"]["v2"]["etat"], "ok")

    def test_kpi_disparu_et_forme_inconnue(self):
        d = VS.donnees(self.admin, {}, [{"id": "a", "type": "chiffre", "kpis": ["SUPPRIME"]},
                                        {"id": "b", "type": "indisponible", "origine": {"brut": {"type": "jauge"}}},
                                        {"id": "c", "type": "tableau", "source": "theme:99999", "kpis": []}])
        self.assertEqual(d["visuels"]["a"]["message"], "Ce KPI n'est plus disponible (supprimé, désactivé ou hors de votre périmètre).")
        self.assertEqual(d["visuels"]["b"]["etat"], "indisponible")
        self.assertEqual(d["visuels"]["c"]["message"], "La liste ou le thème n'existe plus.")


class ArrondiTests(AvecKpis):
    def test_arrondi_comme_excel(self):
        """La moitié vers le haut, en valeur absolue (pas « au pair ») ; jamais « -0 »."""
        self.assertEqual(VS.nombre(D("2.5"), 0), "3")
        self.assertEqual(VS.nombre(2.5, 0), "3")
        self.assertEqual(VS.nombre(D("3.5"), 0), "4")
        self.assertEqual(VS.nombre(D("-2.5"), 0), "-3")
        self.assertEqual(VS.nombre(D("0.125"), 2), "0,13")
        self.assertEqual(VS.nombre(1.005, 2), "1,01")  # décimal, pas la valeur binaire 1,00499…
        self.assertEqual(VS.nombre(D("-0.001"), 2), "0,00")
        self.assertEqual(VS.nombre(D("-0.04"), 1), "0,0")
        self.assertEqual(VS.nombre(D("1234567.895"), 2), "1\u202f234\u202f567,90")
        self.assertEqual(VS.nombre_excel(2.5, 0), 3.0)
        self.assertEqual(VS.nombre_excel(-0.001, 2), 0.0)
        self.assertEqual(VS.nombre_excel(110, 0), 110)

    def test_valeurs_et_parts_affichees(self):
        self.eff.decimales = 1
        self.eff.save()
        Reponse.objects.filter(kpi=self.eff, organisation=self.e2, periode=self.c0.periode).update(valeur=D("30.25"))
        from . import calcul as C

        C.recalculer(self.c0)
        d = self.donnees(self.admin, {"type": "organisations", "kpis": ["EFF"]}, parametres={"org": str(self.p.id), "cmp": "aucune"})
        self.assertEqual(d["visuels"]["v1"]["series"][0]["textes"], ["100,0 ETP", "30,3 ETP"])  # 30,25 → 30,3


class AnglaisTests(AvecKpis):
    def test_textes_et_nombres_en_anglais(self):
        from parametres import langues as L

        self.eff.decimales = 1
        self.eff.save()
        with L.session(), L.activer("en"):
            d = self.donnees(self.admin, {"type": "organisations", "kpis": ["EFF"]},
                             parametres={"org": str(self.p.id), "periode": str(self.c.periode.pk), "brouillons": "1"})
        v = d["visuels"]["v1"]
        self.assertEqual(v["series"][0]["textes"][0], "110.0 ETP")
        self.assertTrue(v["resume"].startswith("Organisation comparison"))
        self.assertTrue(d["etat"]["phrase"].startswith("Drafts included"))
