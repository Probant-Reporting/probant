"""Grille des attributions d'un grand groupe (échelle, P-A4) : au-delà de MAX_COLONNES_ATTRIBUTIONS organisations, la
grille montre un groupe d'organisations à la fois (``groupes_colonnes_attr``, champ « Organisations »).

Preuves : (1) sur des arbres tirés au hasard (graine fixe), les groupes redonnent toutes les colonnes, chacune une fois,
dans l'ordre, sans dépasser la limite, chacun sous son ancre, et l'ancre est la branche la plus haute qui tient ;
(2) sur une base, les pages de tous les groupes mises bout à bout donnent exactement les cases de la grille entière
(« Toutes ») et les mêmes compteurs par niveau ; la grille entière est celle d'avant (même tableau qu'une grille qui
tient sans groupe) ; (3) choix du groupe : adresse, personne, mémoire de session (jamais « Toutes »)."""
import random
import re
from types import SimpleNamespace
from unittest import mock

from django.test import TestCase
from django.urls import reverse

from referentiel.models import KPI, Attribution, Niveau, Organisation, Utilisateur

from . import administration as A

URL = reverse("collecte:admin_attributions")


def arbre_au_hasard(alea, n):
    """Arbre de ``n`` organisations (pk 1..n) ; renvoie (arbre {pk: org}, colonnes en ordre d'arbre)."""
    arbre = {}
    for pk in range(1, n + 1):
        parent = alea.choice([None] + list(arbre)[-12:] + list(arbre)[:3]) if arbre and alea.random() < 0.97 else None
        arbre[pk] = SimpleNamespace(pk=pk, parent_id=parent, nom=f"O{pk}", enfants=[])
        if parent:
            arbre[parent].enfants.append(arbre[pk])
    ordre = []

    def parcourir(o):
        ordre.append(o)
        for e in o.enfants:
            parcourir(e)

    for o in arbre.values():
        if o.parent_id is None:
            parcourir(o)
    feuilles = [o for o in ordre if not o.enfants or alea.random() < 0.1]  # colonnes : surtout des feuilles
    return arbre, feuilles


def ancetres(o, arbre):
    c, p = [], arbre.get(o.parent_id)
    while p is not None:
        c.append(p.pk)
        p = arbre.get(p.parent_id)
    return c


class DecoupageTests(TestCase):
    def test_groupes_au_hasard(self):
        alea = random.Random(20261113)
        for essai in range(300):
            arbre, cols = arbre_au_hasard(alea, alea.randint(1, 400))
            maxi = alea.choice([1, 2, 3, 5, 8, 20, 60])
            groupes = A.groupes_colonnes_attr(cols, arbre, maxi)
            with self.subTest(essai=essai, n=len(cols), maxi=maxi):
                if len(cols) <= maxi:
                    self.assertEqual(groupes, [])
                    continue
                self.assertEqual([o.pk for g in groupes for o in g["orgs"]], [o.pk for o in cols])  # tout, une fois, dans l'ordre
                self.assertEqual(len({g["cle"] for g in groupes}), len(groupes))
                for g in groupes:
                    self.assertTrue(0 < len(g["orgs"]) <= maxi)
                    a = g["ancre"]
                    sous = [o for o in cols if a is None or a.pk in ancetres(o, arbre)]  # colonnes de la branche
                    for o in g["orgs"]:
                        self.assertIn(o, sous)
                    if g["entiere"]:
                        self.assertEqual(g["orgs"], sous)  # la branche entière
                        # la branche au-dessus ne tenait pas : on n'a pas coupé plus fin que nécessaire
                        p = arbre.get(a.parent_id) if a is not None else None
                        dessus = [o for o in cols if p is None or p.pk in ancetres(o, arbre)]
                        self.assertGreater(len(dessus), maxi)
                    else:  # colonnes rattachées directement à une ancre trop grande
                        self.assertGreater(len(sous), maxi)
                        for o in g["orgs"]:
                            self.assertEqual(o.parent_id, a.pk if a is not None else None)


def cases_par_ligne(html):
    """{code du KPI : [HTML des cases de la ligne, dans l'ordre]} et la liste des colonnes (identifiants)."""
    lignes = {}
    for code, corps in re.findall(r'<tr class="ligne" data-texte="([^"]*)".*?>(.*?)</tr>', html, re.S):
        lignes[code] = re.findall(r'<td class="(?:cellule-attr|sans-case).*?</td>', corps, re.S)
    colonnes = re.findall(r'class="choix-colonne" data-org="(\d+)"', html)
    return lignes, colonnes


def grille(html):
    return re.search(r'<table class="grille-attr".*?</table>', html, re.S).group(0)


class PageParGroupeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        alea = random.Random(1113)
        cls.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN)
        cls.personnes = [Utilisateur.objects.create(username=f"c{i}", email=f"c{i}@exemple.test", first_name=f"P{i}")
                         for i in range(6)]
        g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        cls.sites = []
        for p in range(3):
            pays = Organisation.objects.create(nom=f"Pays {p}", niveau_id=Niveau.COUNTRY, parent=g)
            for e in range(alea.randint(1, 3)):
                ent = Organisation.objects.create(nom=f"Entité {p}.{e}", niveau_id=Niveau.ENTITY, parent=pays)
                cls.sites += [Organisation.objects.create(nom=f"Site {p}.{e}.{s}", niveau_id=Niveau.SITE, parent=ent)
                              for s in range(alea.randint(1, 4))]
            # site rattaché directement au pays : il porte lui-même les paramètres hérités du niveau Entité (CALC-09)
            cls.sites.append(Organisation.objects.create(nom=f"Direct {p}", niveau_id=Niveau.SITE, parent=pays))
        kpis = [KPI.objects.create(code=f"S{i}", libelle=f"Site {i}", type_saisie_id="Saisi", granularite_id=Niveau.SITE)
                for i in range(4)]
        kpis += [KPI.objects.create(code="E0", libelle="Entité", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY),
                 KPI.objects.create(code="FE", libelle="Facteur", type_saisie_id="FE", granularite_id=Niveau.ENTITY)]
        for o in Organisation.objects.exclude(niveau_id=Niveau.GROUP):
            for k in kpis:
                for u in alea.sample(cls.personnes, alea.choice([0, 0, 1, 2])):
                    Attribution.objects.create(kpi=k, organisation=o, utilisateur=u)

    def setUp(self):
        self.client.force_login(self.admin)

    def page(self, **params):
        rep = self.client.get(URL, params)
        self.assertEqual(rep.status_code, 200)
        return rep

    def test_groupes_mis_bout_a_bout_egalent_la_grille_entiere(self):
        with mock.patch.object(A, "MAX_COLONNES_ATTRIBUTIONS", 3):
            for niveau in (Niveau.SITE, Niveau.ENTITY):
                with self.subTest(niveau=niveau):
                    tout = self.page(niveau=niveau, groupe=A.TOUTES_COLONNES)
                    groupes = tout.context["groupes_orgs"]
                    self.assertGreater(len(groupes), 1)
                    lignes_tout, colonnes_tout = cases_par_ligne(tout.content.decode())
                    bout_a_bout, colonnes = {code: [] for code in lignes_tout}, []
                    for g in groupes:
                        rep = self.page(niveau=niveau, groupe=g["cle"])
                        self.assertEqual(rep.context["groupe"], g["cle"])
                        self.assertEqual(rep.context["onglets"], tout.context["onglets"])  # compteurs par niveau inchangés
                        lignes, cols = cases_par_ligne(rep.content.decode())
                        self.assertEqual(list(lignes), list(lignes_tout))  # mêmes lignes (KPI), même ordre
                        self.assertLessEqual(len(cols), 3)
                        colonnes += cols
                        for code, cases in lignes.items():
                            bout_a_bout[code] += cases
                    self.assertEqual(colonnes, colonnes_tout)
                    self.assertEqual(bout_a_bout, lignes_tout)
                    self.assertTrue(any("sans-case" in c for cs in lignes_tout.values() for c in cs) or niveau == Niveau.SITE)

    def test_grille_entiere_identique_a_la_grille_sans_groupe(self):
        """« Toutes » d'un niveau découpé = la grille d'avant (la même grille quand elle tient sans groupe)."""
        for niveau in (Niveau.SITE, Niveau.ENTITY):
            sans = self.page(niveau=niveau)
            self.assertEqual(sans.context["groupes_orgs"], [])
            self.assertNotIn('id="filtre-groupe"', sans.content.decode())
            with mock.patch.object(A, "MAX_COLONNES_ATTRIBUTIONS", 3):
                tout = self.page(niveau=niveau, groupe=A.TOUTES_COLONNES)
            self.assertIn('id="filtre-groupe"', tout.content.decode())
            self.assertEqual(grille(tout.content.decode()), grille(sans.content.decode()))

    def test_choix_du_groupe(self):
        with mock.patch.object(A, "MAX_COLONNES_ATTRIBUTIONS", 3):
            premier = self.page(niveau=Niveau.SITE)
            groupes = premier.context["groupes_orgs"]
            self.assertEqual(premier.context["groupe"], groupes[0]["cle"])  # par défaut : les premières colonnes
            html = premier.content.decode()
            self.assertIn(f'data-defaut="{groupes[0]["cle"]}"', html)
            self.assertEqual(html.count("<option value=\"" + A.TOUTES_COLONNES + "\""), 1)
            dernier = groupes[-1]["cle"]
            self.assertEqual(self.page(niveau=Niveau.SITE, groupe=dernier).context["groupe"], dernier)
            self.assertEqual(self.page(niveau=Niveau.SITE).context["groupe"], dernier)  # gardé pour ce niveau
            self.page(niveau=Niveau.SITE, groupe=A.TOUTES_COLONNES)
            self.assertEqual(self.page(niveau=Niveau.SITE).context["groupe"], dernier)  # « Toutes » n'est pas gardé
            self.assertEqual(self.page(niveau=Niveau.SITE, groupe="999-9").context["groupe"], dernier)  # clé inconnue
            # une personne dans l'adresse (après « Remplacer une personne ») : son premier groupe
            u = Utilisateur.objects.create(username="seul", email="seul@exemple.test")
            Attribution.objects.create(kpi_id="S0", organisation=groupes[-2]["orgs"][0], utilisateur=u)
            self.assertEqual(self.page(niveau=Niveau.SITE, personne=u.pk).context["groupe"], groupes[-2]["cle"])

    def test_personne_illisible_dans_l_adresse_ignoree(self):
        """« ² » passe ``isdigit`` mais pas ``int`` ; un nombre trop grand déborde sous SQLite : la page s'affiche quand même
        (relecture de l'échelle)."""
        with mock.patch.object(A, "MAX_COLONNES_ATTRIBUTIONS", 3):
            for personne in ("²", "9" * 25, "abc"):
                with self.subTest(personne=personne):
                    self.page(niveau=Niveau.SITE, personne=personne)

    def test_reserve_a_l_administrateur(self):
        with mock.patch.object(A, "MAX_COLONNES_ATTRIBUTIONS", 3):
            for role in (Utilisateur.Role.VALIDATEUR, Utilisateur.Role.CONTRIBUTEUR, Utilisateur.Role.LECTEUR,
                         Utilisateur.Role.AUDITEUR):
                u = Utilisateur.objects.create(username=f"r-{role}", email=f"{role}@exemple.test", role=role)
                self.client.force_login(u)
                self.assertEqual(self.client.get(URL, {"groupe": A.TOUTES_COLONNES}).status_code, 403, role)
