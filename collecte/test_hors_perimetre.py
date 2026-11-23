"""Visualisation : rien de hors du périmètre de la personne ne part vers le navigateur (HTML de la page, JSON de la vue
et des données, Excel, phrases d'accessibilité), pour un contributeur, un validateur et un lecteur limité ; « Dupliquer »
ne copie que ce qu'elle voit ; à l'enregistrement d'une de ses vues, ce qu'elle n'a pas reçu est gardé tel quel."""
import io
import json
import re
from decimal import Decimal

from django.urls import reverse
from openpyxl import load_workbook

from referentiel.models import KPI, Attribution, Niveau, Theme, Utilisateur

from . import visuels as VS
from .models import Reponse, VueVisu
from .aides_tests.vues import Base

D = Decimal
SECRET, NOM_SECRET = "ZZSECRET", "Émissions confidentielles"


def visuel(id_, forme, kpis=(), **autres):
    return {"id": id_, "type": forme, "titre": "", "kpis": list(kpis), "source": "", "axe": "", "series": "", "largeur": 6,
            "hauteur": "m", "filtres": {}, "options": {}, **autres}


def json_script(html, nom):
    m = re.search(rf'<script id="{nom}" type="application/json">(.*?)</script>', html, re.S)
    return json.loads(m.group(1))


def organisations_citees(x, sortie=None):
    """Identifiants d'organisation cités dans un JSON : clés « org » et « org_id », listes « ids », chemins."""
    sortie = set() if sortie is None else sortie
    if isinstance(x, dict):
        for k, v in x.items():
            if k in ("org", "org_id") and isinstance(v, int) and not isinstance(v, bool):
                sortie.add(v)
            elif k == "ids" and isinstance(v, list):
                sortie |= {i for i in v if isinstance(i, int)}
            elif k == "chemin" and isinstance(v, list):
                sortie |= {c["id"] for c in v if isinstance(c, dict)}
            organisations_citees(v, sortie)
    elif isinstance(x, list):
        for v in x:
            organisations_citees(v, sortie)
    return sortie


class HorsPerimetreBase(Base):
    def setUp(self):
        super().setUp()
        from referentiel.composition import composer

        for o, nom in ((self.g, "Holding Alpha"), (self.p, "Pays Bravo"), (self.e1, "Entité Charlie"), (self.e2, "Entité Delta")):
            o.nom = nom
            o.save()
        self.secret = KPI.objects.create(code=SECRET, libelle=NOM_SECRET, type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                                         methode_agregation="Somme", unite=self.eff.unite, decimales=0)
        Reponse.objects.create(periode=self.c0.periode, kpi=self.secret, organisation=self.e2, valeur=D(7), statut="valide", origine="import")
        ref = composer({SECRET: ["Thème réservé"], "EFF": ["Social"], "TX": ["Social"]})
        self.theme = Theme.objects.get(referentiel=ref, nom="Thème réservé")
        self.validateur = Utilisateur.objects.create(username="val", email="val@exemple.test", role=Utilisateur.Role.VALIDATEUR)
        Attribution.objects.create(kpi=self.eff, organisation=self.e2, utilisateur=self.validateur, role=Attribution.Role.VALIDATEUR)
        self.lecteur.perimetre_lecture.set([self.e1])  # lecteur limité à une entité
        self.choisies = {"mode": "choisies", "ids": [self.e1.id, self.e2.id, self.g.id]}
        self.vue = VueVisu.objects.create(nom="Comité", proprietaire=self.admin, partage=True, filtres={"org": self.g.id}, visuels=[
            visuel("a", "chiffre", ["EFF"], largeur=3),
            visuel("b", "chiffre", [SECRET]),
            visuel("c", "barres", ["EFF", SECRET], axe="organisations", filtres={"org": self.e2.id, "orgs_comparees": self.choisies}),
            visuel("d", "tableau", source=f"theme:{self.theme.pk}", largeur=12),
            visuel("e", "indisponible", [SECRET], origine={"tableau": 3, "tuile": 1, "type": "jauge", "brut": {"type": "jauge", "kpi": SECRET}}),
        ])
        self.hors = {  # ce que chacun ne doit jamais recevoir : textes, identifiants d'organisation
            "contributeur": ([SECRET, NOM_SECRET, "Holding Alpha", "Pays Bravo", "Entité Delta"], {self.g.id, self.p.id, self.e2.id}),
            "validateur": (["Holding Alpha", "Pays Bravo", "Entité Charlie"], {self.g.id, self.p.id, self.e1.id}),
            "lecteur": (["Holding Alpha", "Pays Bravo", "Entité Delta"], {self.g.id, self.p.id, self.e2.id}),
        }
        self.comptes = {"contributeur": self.contrib, "validateur": self.validateur, "lecteur": self.lecteur}

    def verifier(self, role, textes):
        """Aucun texte ni identifiant hors du périmètre de ``role`` dans ``textes`` (chaînes JSON ou HTML)."""
        mots, ids = self.hors[role]
        for t in textes:
            for mot in mots:
                self.assertNotIn(mot, t, (role, mot))
            try:
                donnees = json.loads(t)
            except ValueError:
                continue
            self.assertEqual(organisations_citees(donnees) & ids, set(), role)


class PageEtJsonTests(HorsPerimetreBase):
    def test_page_et_json_de_la_vue(self):
        for role, u in self.comptes.items():
            with self.subTest(role=role):
                self.client.force_login(u)
                url = reverse("collecte:visu_vue", args=[self.vue.pk])
                html = self.client.get(url, {"brouillons": "1"}).content.decode()
                contexte, donnees = json_script(html, "visu-contexte"), json_script(html, "visu-donnees")
                rep = self.client.get(reverse("collecte:visu_vue_donnees", args=[self.vue.pk]), {"brouillons": "1"})
                self.verifier(role, [html, json.dumps(contexte, ensure_ascii=False), json.dumps(donnees, ensure_ascii=False),
                                     rep.content.decode()])
                self.assertNotIn("origine", json.dumps(contexte["vue"]["visuels"]))  # jamais l'origine d'un tableau converti
                self.assertNotIn("org", contexte["vue"]["filtres"])

    def test_contributeur_visuels_retires_et_nettoyes(self):
        self.client.force_login(self.contrib)
        html = self.client.get(reverse("collecte:visu_vue", args=[self.vue.pk])).content.decode()
        contexte, donnees = json_script(html, "visu-contexte"), json_script(html, "visu-donnees")
        vue = contexte["vue"]
        self.assertEqual([v["id"] for v in vue["visuels"]], ["a", "c"])  # b, d, e : entièrement hors de son périmètre
        self.assertEqual(vue["masques"], 3)
        self.assertEqual(donnees["ordre"], ["a", "c"])
        self.assertEqual(donnees["etat"]["phrase_masques"], "3 visuels de cette vue ne vous concernent pas.")
        c = vue["visuels"][1]
        self.assertEqual(c["kpis"], ["EFF"])
        self.assertEqual(c["filtres"], {"orgs_comparees": {"mode": "choisies", "ids": [self.e1.id]}})
        self.assertEqual(donnees["visuels"]["c"]["avertissements"], ["1 élément hors de votre périmètre est ignoré."])
        self.assertEqual(len(vue["garde"]), 3 + 1 + 1 + 2 + 1)  # 3 visuels, 1 KPI, 1 organisation fixée, 2 choisies, filtre de la vue
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]{16}", x) for x in vue["garde"]))
        self.assertEqual(contexte["limites"]["visuels"], VS.MAX_VISUELS - 3)

    def test_admin_voit_tout_sauf_l_origine(self):
        self.client.force_login(self.admin)
        html = self.client.get(reverse("collecte:visu_vue", args=[self.vue.pk])).content.decode()
        vue = json_script(html, "visu-contexte")["vue"]
        self.assertEqual([v["id"] for v in vue["visuels"]], ["a", "b", "c", "d", "e"])
        self.assertEqual((vue["masques"], vue["garde"], vue["filtres"]), (0, [], {"org": self.g.id}))
        self.assertEqual(vue["visuels"][2]["kpis"], ["EFF", SECRET])
        self.assertNotIn("origine", vue["visuels"][4])

    def test_excel(self):
        self.client.force_login(self.contrib)
        rep = self.client.get(reverse("collecte:visu_vue_excel", args=[self.vue.pk]), {"brouillons": "1"})
        wb = load_workbook(io.BytesIO(rep.content))
        texte = " ".join(str(c) for ws in wb for r in ws.iter_rows(values_only=True) for c in r if c is not None)
        self.verifier("contributeur", [texte])
        self.assertEqual(len(wb.sheetnames), 3)  # « À lire » et ses deux visuels
        for masque in ("b", "d", "e"):
            self.assertEqual(self.client.get(reverse("collecte:visu_vue_excel", args=[self.vue.pk]), {"visuel": masque}).status_code, 404)
        self.assertEqual(self.client.get(reverse("collecte:visu_vue_excel", args=[self.vue.pk]), {"visuel": "c"}).status_code, 200)

    def test_reponses_des_envois_sans_definition(self):
        self.client.force_login(self.contrib)
        rep = self.post("visu_vue_creer", {"nom": "Perso", "visuels": [visuel("x", "chiffre", ["EFF"])]})
        self.assertNotIn("visuels", rep.json()["vue"])
        v = VueVisu.objects.get(pk=rep.json()["vue"]["id"])
        for nom, corps in (("visu_vue_enregistrer", {"version": 1, "nom": "Perso 2"}), ("visu_vue_preferee", {"defaut": True})):
            rep = self.post(nom, corps, [v.pk])
            self.assertEqual(rep.status_code, 200)
            self.assertNotIn("visuels", rep.json()["vue"])


class DupliquerTests(HorsPerimetreBase):
    def test_copie_de_ce_que_la_personne_voit(self):
        self.client.force_login(self.contrib)
        rep = self.post("visu_vue_dupliquer", {}, [self.vue.pk])
        self.assertEqual(rep.status_code, 201)
        self.assertEqual(rep.json()["message"], "Copie créée : « Copie de Comité ». 3 visuels hors de votre périmètre n'ont pas été copiés.")
        copie = VueVisu.objects.get(pk=rep.json()["vue"]["id"])
        self.assertEqual([v["id"] for v in copie.visuels], ["a", "c"])
        self.assertEqual(copie.visuels[1]["kpis"], ["EFF"])
        self.assertEqual(copie.visuels[1]["filtres"], {"orgs_comparees": {"mode": "choisies", "ids": [self.e1.id]}})
        self.assertEqual(copie.filtres, {})
        self.assertNotIn(SECRET, json.dumps(copie.visuels))

    def test_admin_copie_tout(self):
        self.client.force_login(self.admin)
        rep = self.post("visu_vue_dupliquer", {}, [self.vue.pk])
        self.assertEqual(rep.json()["message"], "Copie créée : « Copie de Comité ».")
        copie = VueVisu.objects.get(pk=rep.json()["vue"]["id"])
        self.assertEqual(len(copie.visuels), 5)
        self.assertNotIn("origine", copie.visuels[4])  # une copie n'est pas un tableau converti


class EnregistrerSansPerteTests(HorsPerimetreBase):
    """Une vue personnelle du contributeur, dont une partie est sortie de son périmètre (attribution retirée)."""

    def setUp(self):
        super().setUp()
        self.origine = {"tableau": 8, "tuile": 3, "type": "evolution"}
        self.perso = VueVisu.objects.create(nom="Mes chiffres", proprietaire=self.contrib, filtres={"org": self.e2.id}, visuels=[
            visuel("a", "chiffre", ["EFF"]),
            visuel("h1", "chiffre", [SECRET]),
            visuel("c", "barres", ["EFF", SECRET], axe="organisations", origine=self.origine,
                   filtres={"org": self.e2.id, "orgs_comparees": self.choisies}),
            visuel("h2", "indisponible", [SECRET]),
        ])
        self.avant = json.loads(json.dumps(self.perso.visuels))
        self.client.force_login(self.contrib)

    def page(self):
        html = self.client.get(reverse("collecte:visu_vue", args=[self.perso.pk]) + "?modifier=1").content.decode()
        return json_script(html, "visu-contexte")["vue"]

    def enregistrer(self, vue, visuels, **autres):
        corps = {"version": vue["version"], "nom": vue["nom"], "filtres": vue["filtres"], "visuels": visuels, **autres}
        rep = self.post("visu_vue_enregistrer", corps, [self.perso.pk])
        self.assertEqual(rep.status_code, 200, rep.content)
        self.perso.refresh_from_db()
        return self.perso.visuels

    def test_ce_qui_n_a_pas_ete_recu_est_garde(self):
        vue = self.page()
        self.assertEqual([v["id"] for v in vue["visuels"]], ["a", "c"])
        a, c = vue["visuels"]
        c = {**c, "titre": "Effectifs par entité"}
        nouveau = visuel("n1", "chiffre", ["TX"])
        apres = self.enregistrer(vue, [c, a, nouveau], garde=vue["garde"])
        self.assertEqual([v["id"] for v in apres], ["c", "h1", "a", "h2", "n1"])  # les visuels gardés à leur place
        self.assertEqual(apres[1], self.avant[1])
        self.assertEqual(apres[3], self.avant[3])
        self.assertEqual(apres[0]["titre"], "Effectifs par entité")
        self.assertEqual(apres[0]["kpis"], ["EFF", SECRET])
        self.assertEqual(apres[0]["filtres"], {"org": self.e2.id, "orgs_comparees": {"mode": "choisies", "ids": [self.e1.id, self.e2.id, self.g.id]}})
        self.assertEqual(apres[0]["origine"], self.origine)
        self.assertEqual(self.perso.filtres, {"org": self.e2.id})

    def test_sans_empreintes_le_perimetre_d_aujourd_hui(self):
        vue = self.page()
        apres = self.enregistrer(vue, vue["visuels"])
        self.assertEqual(apres, self.avant)

    def test_perimetre_change_pendant_la_modification(self):
        """Les empreintes de la page font foi : ce qu'elle n'a pas reçu est gardé, même devenu visible entre-temps."""
        vue = self.page()
        Attribution.objects.create(kpi=self.secret, organisation=self.e1, utilisateur=self.contrib)
        apres = self.enregistrer(vue, vue["visuels"], garde=vue["garde"])
        self.assertEqual(apres, self.avant)

    def test_la_page_ne_dicte_ni_l_origine_ni_un_identifiant_cache(self):
        vue = self.page()
        a, c = vue["visuels"]
        pirate = visuel("h1", "chiffre", ["EFF"], origine={"brut": "inventé"})
        apres = self.enregistrer(vue, [a, {**c, "origine": {"tableau": 99}}, pirate], garde=vue["garde"])
        self.assertEqual(sum(1 for v in apres if v["id"] == "h1"), 1)
        self.assertIn(self.avant[1], apres)  # le visuel caché reste intact
        self.assertEqual(len({v["id"] for v in apres}), len(apres))
        self.assertEqual(next(v for v in apres if v["id"] == "c")["origine"], self.origine)
        self.assertTrue(all(v.get("origine") != {"brut": "inventé"} for v in apres))

    def test_supprimer_un_visuel_visible(self):
        vue = self.page()
        apres = self.enregistrer(vue, [vue["visuels"][0]], garde=vue["garde"])
        self.assertEqual([v["id"] for v in apres], ["a", "h1", "h2"])

    def test_plafond_avec_les_visuels_gardes(self):
        vue = self.page()
        self.assertEqual(vue["masques"], 2)
        trop = [visuel(f"x{i}", "chiffre", ["EFF"]) for i in range(VS.MAX_VISUELS - 1)]
        rep = self.post("visu_vue_enregistrer", {"version": vue["version"], "visuels": trop, "garde": vue["garde"]}, [self.perso.pk])
        self.assertEqual(rep.status_code, 400)
        self.assertEqual(rep.json()["erreurs"][0]["message"], "Une vue contient 40 visuels au plus.")
        assez = trop[:VS.MAX_VISUELS - 2]
        rep = self.post("visu_vue_enregistrer", {"version": vue["version"], "visuels": assez, "garde": vue["garde"]}, [self.perso.pk])
        self.assertEqual(rep.status_code, 200)
        self.perso.refresh_from_db()
        self.assertEqual(len(self.perso.visuels), VS.MAX_VISUELS)
