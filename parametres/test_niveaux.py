"""Niveaux de l'arbre réglables : structures à 2, 3 et 5 niveaux, rattachement souple, page Paramètres › Niveaux,
classeur de configuration (onglet Niveaux), exports à colonnes de hiérarchie dynamiques."""
import io
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from openpyxl import load_workbook

from collecte import configuration as C
from collecte import exports as E
from collecte import imports as I
from collecte import saisie as S
from collecte.calcul import Calculateur, recalculer
from collecte.models import Campagne, Journal, RegleCoherence, Reponse
from referentiel.models import KPI, Attribution, Organisation, Utilisateur

from . import couleurs as CO
from . import niveaux as N
from .models import NiveauHierarchique
from collecte.outils_tests import xlsx
from collecte.outils_tests import html_de

D = Decimal
FETCH = {"HTTP_X_REQUESTED_WITH": "fetch"}


def structure(*noms):
    """Remplace les 4 niveaux d'installation par ceux donnés (du sommet vers le bas) ; codes = noms sans accent."""
    NiveauHierarchique.objects.all().delete()
    niveaux = []
    for rang, nom in enumerate(noms, start=1):
        n = NiveauHierarchique(code=N.nouveau_code(nom), rang=rang, nom=nom, nom_pluriel=nom + "s",
                               couleur=CO.COULEURS_NIVEAUX[rang - 1])
        n.deriver_couleurs()
        n.save()
        niveaux.append(n.code)
    return niveaux


class Base(TestCase):
    def org(self, nom, niveau, parent=None, actif=True):
        o = Organisation(nom=nom, niveau_id=niveau, parent=parent, actif=actif)
        o.full_clean()  # le rattachement est vérifié comme dans l'outil
        o.save()
        return o

    def kpi(self, i, niveau, t="Saisi", f="", agg="Somme"):
        return KPI.objects.create(code=i, libelle=i, type_saisie_id=t, formule=f, granularite_id=niveau, methode_agregation=agg)

    def saisir(self, kpi, org, v):
        Reponse.objects.create(periode=self.c.periode, kpi_id=kpi, organisation=org, valeur=D(v), origine=Reponse.Origine.SAISIE,
                               statut=Reponse.Statut.VALIDE)

    def setUp(self):
        self.c = Campagne.objects.create(exercice=2026, statut=Campagne.Statut.OUVERTE)
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN)


class DeuxNiveauxTests(Base):
    """Entreprise › Établissement : la plus petite structure utile."""

    def setUp(self):
        super().setUp()
        self.haut, self.bas = structure("Entreprise", "Établissement")
        self.e = self.org("Entreprise", self.haut)
        self.a, self.b = self.org("Atelier A", self.bas, self.e), self.org("Atelier B", self.bas, self.e)
        self.kpi("ELEC", self.bas)

    def test_agregation_et_pages(self):
        self.saisir("ELEC", self.a, 10)
        self.saisir("ELEC", self.b, 5)
        recalculer(self.c)
        self.assertEqual(Reponse.objects.get(kpi_id="ELEC", organisation=self.e).valeur, D(15))
        self.client.force_login(self.admin)
        for nom in ("admin_organisations", "admin_attributions", "saisie", "tableau_de_bord", "referentiel"):
            rep = self.client.get(reverse(f"collecte:{nom}"))
            self.assertEqual(rep.status_code, 200, nom)
        rep = self.client.get(reverse("collecte:admin_attributions"))
        self.assertEqual([o["code"] for o in rep.context["onglets"]], [self.haut, self.bas])
        self.assertEqual(rep.context["niveau"], self.bas)  # le seul niveau qui a des cases à attribuer
        rep = self.client.get(reverse("collecte:admin_organisations"))
        self.assertContains(rep, "Établissements → Entreprises")
        self.assertContains(rep, "Sans les Établissements")
        self.assertContains(rep, f".niveau-{self.bas}{{")  # couleurs du niveau générées dans la page

    def test_export_une_colonne_par_niveau(self):
        self.saisir("ELEC", self.a, 10)
        p = E.Parametres(exercices=["2026"], contenus=["valide"])
        self.assertEqual(p.niveaux, [self.haut, self.bas])
        cols = [c for c, _, _ in E.colonnes_base(p)]
        self.assertEqual(cols[cols.index("niveau") + 1:cols.index("valeur")], [f"niv:{self.haut}", f"niv:{self.bas}"])
        wb = load_workbook(io.BytesIO(E.exporter(self.admin, p).content))
        tete = [c.value for c in wb["Valeurs"][1]]
        ligne = [c.value for c in wb["Valeurs"][2]]
        self.assertEqual((ligne[tete.index("Entreprise")], ligne[tete.index("Établissement")]), ("Entreprise", "Atelier A"))


class TroisNiveauxTests(Base):
    """Holding › Filiale › Site, avec un site rattaché directement à la holding (rattachement souple)."""

    def setUp(self):
        super().setUp()
        self.H, self.F, self.S = structure("Holding", "Filiale", "Site")
        self.h = self.org("Holding", self.H)
        self.f = self.org("Filiale", self.F, self.h)
        self.s1 = self.org("Usine", self.S, self.f)
        self.siege = self.org("Siège", self.S, self.h)  # sous la holding, sans filiale

    def test_agregation_depuis_les_enfants_directs(self):
        self.kpi("ELEC", self.S)
        self.kpi("EFF", self.F)
        self.kpi("FE", self.H, "FE", agg="Aucune")
        self.kpi("GES", self.S, "Calculé", "[ELEC] * [FE]")
        self.saisir("ELEC", self.s1, 100)
        self.saisir("ELEC", self.siege, 20)
        self.saisir("EFF", self.f, 7)
        self.saisir("FE", self.h, "0.5")
        calc = Calculateur(self.c)
        self.assertEqual(calc.valeur("ELEC", self.h.id), D(120))  # filiale (100) + siège (20)
        self.assertEqual(calc.valeur("EFF", self.h.id), D(7))  # le siège est sous la granularité : ignoré
        self.assertEqual(calc.valeur("GES", self.siege.id), D(10))  # facteur hérité de la holding
        self.assertEqual(calc.valeur("GES", self.h.id), D(60))
        recalculer(self.c)
        r = Reponse.objects.get(kpi_id="ELEC", organisation=self.h)
        self.assertEqual((r.valeur, r.origine), (D(120), Reponse.Origine.AGREGATION))

    def test_profondeur_et_cellules(self):
        arbre = S.arbre_organisations()
        self.assertEqual([arbre[o.id].prof for o in (self.h, self.f, self.s1, self.siege)], [0, 1, 2, 1])
        self.kpi("ELEC", self.S)
        self.assertEqual({o.nom for k, o in S.cellules(self.admin)}, {"Usine", "Siège"})

    def test_fiche_organisation_propose_tous_les_niveaux_superieurs(self):
        self.client.force_login(self.admin)
        html = self.client.get(reverse("collecte:admin_organisation_nouvelle") + f"?parent={self.h.id}", **FETCH).json()["html"]
        self.assertRegex(html, rf'value="{self.F}"[^>]* checked')  # sous la holding : le niveau juste en dessous
        self.assertIn('data-dessus="Filiale ou Holding"', html)
        res = self.client.post(reverse("collecte:admin_organisation_nouvelle"), {
            "nom": "Entrepôt", "niveau": self.S, "parent": self.h.id, "rang": 0, "actif": "on", "action": "enregistrer"}, **FETCH).json()
        self.assertTrue(res["ok"], res["html"])
        res = self.client.post(reverse("collecte:admin_organisation_nouvelle"), {
            "nom": "Filiale bis", "niveau": self.F, "parent": self.s1.id, "rang": 0, "actif": "on", "action": "enregistrer"}, **FETCH).json()
        self.assertFalse(res["ok"])
        self.assertIn("niveau supérieur", res["html"])


class CinqNiveauxTests(Base):
    """Monde › Zone › Pays › Entité › Site : une chaîne d'agrégation profonde."""

    def setUp(self):
        super().setUp()
        self.codes = structure("Monde", "Zone", "Pays", "Entité", "Site")
        parent = None
        self.orgs = []
        for code, nom in zip(self.codes, ["Monde", "Europe", "France", "Filiale FR", "Lyon"]):
            parent = self.org(nom, code, parent)
            self.orgs.append(parent)
        self.lille = self.org("Lille", self.codes[4], self.orgs[3])
        self.kpi("ELEC", self.codes[4])
        self.kpi("EFF", self.codes[3])
        self.kpi("PART", self.codes[4], "Calculé", "[ELEC] / 10", agg="Formule")

    def test_agregation_sur_quatre_niveaux(self):
        self.saisir("ELEC", self.orgs[4], 30)
        self.saisir("ELEC", self.lille, 10)
        recalculer(self.c)
        valeurs = dict(Reponse.objects.filter(kpi_id="ELEC").values_list("organisation__nom", "valeur"))
        self.assertEqual([valeurs[n] for n in ("Filiale FR", "France", "Europe", "Monde")], [D(40)] * 4)
        self.assertEqual(Calculateur(self.c).valeur("PART", self.orgs[0].id), D(4))  # formule refaite au sommet

    def test_import_de_valeurs(self):
        f = xlsx({"Saisie": [["ID KPI", "Organisation", "Exercice", "Valeur"], ["ELEC", "Lyon", 2026, 12],
                             ["ELEC", "Europe", 2026, 99], ["EFF", "Lyon", 2026, 3], ["EFF", "Filiale FR", 2026, 50]]})
        a = I.analyser(self.admin, f)
        self.assertEqual([(l.action, l.motif) for l in sorted(a.lignes, key=lambda l: l.numero)], [
            ("creer", ""), ("ignore", "Total agrégé : l'outil le calcule à ce niveau."),
            ("rejet", "Ce KPI se saisit au niveau Entité, pas Site."), ("creer", "")])

    def test_exports_et_classeur_de_configuration(self):
        self.saisir("ELEC", self.orgs[4], 30)
        p = E.Parametres(exercices=["2026"], contenus=["valide"])
        wb = load_workbook(io.BytesIO(E.exporter(self.admin, p).content))
        tete = [c.value for c in wb["Organisations"][1]]
        self.assertEqual(tete, ["Code organisation", "Organisation", "Niveau", "Rattachée à", "Code du rattachement", "Monde", "Zone",
                                "Pays", "Entité", "Site", "Active"])
        wb = C.classeur()
        self.assertEqual([[c.value for c in r] for r in wb["Niveaux"].iter_rows(min_row=2, max_col=3)],
                         [[c, i, n] for i, (c, n) in enumerate(zip(self.codes, ["Monde", "Zone", "Pays", "Entité", "Site"]), 1)])
        flux = io.BytesIO()
        wb.save(flux)
        a = C.analyser(SimpleUploadedFile("config.xlsx", flux.getvalue()))
        self.assertFalse(a.erreur)
        self.assertEqual({c.action for cs in a.onglets.values() for c in cs}, {"inchange"})
        self.assertEqual(len(a.onglets["KPI"]), 3)


class PageNiveauxTests(Base):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)
        self.url = reverse("parametres:niveaux")
        g = self.org("Groupe", "Group")
        self.e = self.org("Entité", "Entity", g)
        self.org("Site", "Site", self.e)

    def post(self, **donnees):
        return self.client.post(self.url, donnees, follow=True)

    def chaine(self):
        return [n.nom for n in N.tous()]

    def test_reserve_a_l_admin(self):
        contrib = Utilisateur.objects.create(username="c", email="c@exemple.test")
        self.client.force_login(contrib)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_page_et_apercu(self):
        rep = self.client.get(self.url)
        self.assertContains(rep, "Aperçu de l'arbre")
        self.assertContains(rep, 'data-etiquette="Site"')
        self.assertEqual([(n.code, n.utilise) for n in rep.context["niveaux"]],
                         [("Group", True), ("Country", False), ("Entity", True), ("Site", True)])

    def test_ajouter_renommer_recolorer(self):
        self.post(action="ajouter", nom="Business unit", nom_pluriel="Business units", couleur="#e0a526", position="Country")
        self.assertEqual(self.chaine(), ["Groupe", "Pays", "Business unit", "Entité", "Site"])
        bu = NiveauHierarchique.objects.get(nom="Business unit")
        self.assertEqual((bu.code, bu.couleur), ("BusinessUnit", "#E0A526"))
        self.assertGreaterEqual(CO.contraste(bu.couleur_texte, bu.couleur_fond), CO.SEUIL_AA)
        donnees = {f"{c}_{n.code}": v for n in N.tous() for c, v in (("nom", n.nom), ("pluriel", n.nom_pluriel), ("couleur", n.couleur))}
        donnees.update(nom_Entity="Filiale", pluriel_Entity="Filiales", couleur_Entity="#123456")
        self.post(action="enregistrer", **donnees)
        e = NiveauHierarchique.objects.get(code="Entity")
        self.assertEqual((e.nom, e.couleur), ("Filiale", "#123456"))
        self.assertTrue(Journal.objects.filter(action="reglage_niveaux", objet_id="Entity", champ="nom", apres="Filiale").exists())
        donnees.update(nom_Site="Filiale")  # deux niveaux du même nom : refusé
        rep = self.post(action="enregistrer", **donnees)
        self.assertContains(rep, "Deux niveaux s&#x27;appellent")
        self.assertEqual(NiveauHierarchique.objects.get(code="Site").nom, "Site")

    def test_huit_niveaux_au_plus(self):
        for i in range(4):
            self.post(action="ajouter", nom=f"N{i}", couleur="#112233", position="Site")
        self.assertEqual(NiveauHierarchique.objects.count(), 8)
        rep = self.post(action="ajouter", nom="Trop", couleur="#112233")
        self.assertContains(rep, "8 niveaux au plus")

    def test_reordonner_si_l_arbre_le_permet(self):
        rep = self.post(monter="Site")  # des sites sont rattachés à une entité : refusé
        self.assertContains(rep, "au-dessus de son rattachement")
        self.assertEqual(self.chaine(), ["Groupe", "Pays", "Entité", "Site"])
        self.post(descendre="Country")  # Pays est vide : il passe sous Entité
        self.assertEqual(self.chaine(), ["Groupe", "Entité", "Pays", "Site"])
        self.post(monter="Group")  # déjà en haut : rien ne change
        self.assertEqual(self.chaine(), ["Groupe", "Entité", "Pays", "Site"])

    def test_supprimer_un_niveau_vide_seulement(self):
        rep = self.post(supprimer="Entity")
        self.assertContains(rep, "Vous ne pouvez supprimer qu")
        self.post(supprimer="Country")
        self.assertEqual(self.chaine(), ["Groupe", "Entité", "Site"])
        self.assertEqual([n.rang for n in N.tous()], [1, 2, 3])


class ConfigurationNiveauxTests(Base):
    """Une installation neuve importe sa structure : niveaux, puis organisations rattachées à ces niveaux."""

    def test_installation_neuve(self):
        f = xlsx({
            "Niveaux": [["Code", "Rang", "Nom", "Nom au pluriel", "Couleur"], ["Holding", 1, "Holding", "", "#1D3F6E"],
                        ["Filiale", 2, "Filiale", "Filiales", ""], ["Site", 3, "Site", "Sites", "#0F9D9A"]],
            "Organisations": [["Nom", "Niveau", "Rattachée à"], ["Essai", "Holding", ""], ["Essai France", "Filiales", "Essai"],
                              ["Lyon", "Site", "Essai France"], ["Siège", "Site", "Essai"], ["Perdue", "Filiale", "Lyon"]],
        })
        a = C.analyser(f)
        self.assertEqual({(c.cle, c.action) for c in a.onglets["Niveaux"]}, {
            ("Holding", "creer"), ("Filiale", "creer"), ("Site", "modifier"), ("Group", "supprimer"), ("Country", "supprimer"),
            ("Entity", "supprimer")})
        orgs = {c.cle: c for c in a.onglets["Organisations"]}
        self.assertEqual([orgs[n].action for n in ("Essai", "Essai France", "Lyon", "Siège")], ["creer"] * 4)
        self.assertIn("niveau supérieur", orgs["Perdue"].motif)
        f.seek(0)
        C.appliquer(self.admin, f, "config.xlsx")  # une ligne refusée : rien n'est enregistré (tout ou rien)
        self.assertEqual([n.code for n in N.tous()], ["Group", "Country", "Entity", "Site"])
        self.assertFalse(Organisation.objects.filter(nom="Essai").exists())
        f = xlsx({
            "Niveaux": [["Code", "Rang", "Nom", "Nom au pluriel", "Couleur"], ["Holding", 1, "Holding", "", "#1D3F6E"],
                        ["Filiale", 2, "Filiale", "Filiales", ""], ["Site", 3, "Site", "Sites", "#0F9D9A"]],
            "Organisations": [["Nom", "Niveau", "Rattachée à"], ["Essai", "Holding", ""], ["Essai France", "Filiales", "Essai"],
                              ["Lyon", "Site", "Essai France"], ["Siège", "Site", "Essai"]],
        })
        C.appliquer(self.admin, f, "config.xlsx")
        self.assertEqual([(n.code, n.rang, n.nom_pluriel) for n in N.tous()],
                         [("Holding", 1, "Holding"), ("Filiale", 2, "Filiales"), ("Site", 3, "Sites")])
        self.assertEqual(Organisation.objects.get(nom="Siège").parent.nom, "Essai")

    def test_l_ordre_des_niveaux_utilises_ne_change_pas_par_import(self):
        g = self.org("Groupe", "Group")
        self.org("Site", "Site", g)
        f = xlsx({"Niveaux": [["Code", "Rang", "Nom"], ["Site", 1, "Site"], ["Group", 2, "Groupe"]]})
        a = C.analyser(f)
        self.assertTrue(all(c.action == "rejet" for c in a.onglets["Niveaux"]))
        self.assertEqual([n.code for n in N.tous()], ["Group", "Country", "Entity", "Site"])


class CouleursNiveauxTests(TestCase):
    def test_couleurs_derivees_lisibles(self):
        for c in CO.COULEURS_NIVEAUX + ["#FFE14D", "#9FD3FF", "#111111"]:
            fond, texte, pale = CO.couleurs_niveau(c)
            self.assertGreaterEqual(CO.contraste(texte, fond), CO.SEUIL_AA, c)

    def test_code_tire_du_nom(self):
        self.assertEqual(N.nouveau_code("Business unit"), "BusinessUnit")
        self.assertEqual(N.nouveau_code("Entité"), "Entite")
        self.assertEqual(N.nouveau_code("Site"), "Site2")  # « Site » existe déjà
        self.assertEqual(N.nouveau_code("2e niveau"), "N2eNiveau")

    def test_regle_et_attribution_suivent_le_niveau(self):
        structure("A", "B")
        a = Organisation.objects.create(nom="a", niveau_id="A")
        b = Organisation.objects.create(nom="b", niveau_id="B", parent=a)
        k = KPI.objects.create(code="K", type_saisie_id="Saisi", granularite_id="B")
        u = Utilisateur.objects.create(username="u", email="u@exemple.test")
        Attribution(kpi=k, organisation=b, utilisateur=u).full_clean()
        with self.assertRaisesMessage(Exception, "Ce KPI se saisit au niveau B"):
            Attribution(kpi=k, organisation=a, utilisateur=u).full_clean()
        RegleCoherence.objects.create(nom="r", gauche="[K]", droite="1", niveau_id="B")
        self.assertEqual(N.utilises(), {"A", "B"})


class JeuTroisNiveauxTests(TestCase):
    def test_chargement(self):
        from io import StringIO

        from django.core.management import call_command

        from collecte.aides_tests import jeu_trois_niveaux as J

        J.charger()
        self.assertEqual([n.nom for n in N.tous()], ["Holding", "Filiale", "Site"])
        self.assertEqual(Organisation.objects.get(nom="Siège Essai").parent.nom, "Essai Holding")
        c = Campagne.objects.get(exercice=2025, referentiel_id="REPORTING")
        r = {o: v for o, v in Reponse.objects.filter(periode=c.periode, kpi_id="ENR-01").values_list("organisation__nom", "valeur")}
        self.assertEqual(r["Essai Holding"], r["Essai France"] + r["Essai Deutschland"] + r["Essai Iberia"] + r["Siège Essai"])
        with self.assertRaisesMessage(Exception, "one installation = one client"):
            call_command("charger_demo", "--language", "fr", stdout=StringIO())  # démo Exemplia sur une base de l'ancienne seconde démo : refusé sans --reset


class JournalNiveauxTests(Base):
    def test_journal_ecrit_les_noms_de_niveau(self):
        from collecte import reglages as R

        kpi = KPI.objects.create(code="K", libelle="K", type_saisie_id="Saisi", granularite_id="Entity")
        donnees = {c: getattr(kpi, "granularite_id" if c == "granularite" else c) for c in R.CHAMPS_FICHE}
        donnees = {c: v for c, v in donnees.items() if v is not False and v is not None}
        donnees["granularite"] = "Site"
        form = R.KPIForm(donnees, instance=kpi)
        self.assertTrue(form.is_valid(), form.errors)
        R.enregistrer_kpi(self.admin, form)
        j = Journal.objects.get(action="reglage_kpi", champ="granularite")
        self.assertEqual((j.avant, j.apres), ("Entité", "Site"))


class BaseAdminConnecte(TestCase):
    def setUp(self):
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN)
        self.client.force_login(self.admin)


class NiveauxPageTests(BaseAdminConnecte):
    def page(self):
        return html_de(self.client, reverse("parametres:niveaux"))

    def test_plus_de_paragraphe_ni_de_phrase_sous_le_bouton(self):
        html = self.page()
        self.assertNotIn("Chaque organisation appartient à un niveau", html)
        self.assertNotIn("fonce automatiquement", html)

    def test_lignes_en_arbre_sous_des_titres_de_colonnes(self):
        html = self.page()
        self.assertIn('class="tete-niveaux" aria-hidden="true"', html)
        for rang, code in enumerate(("Group", "Country", "Entity", "Site")):
            self.assertIn(f'<li class="ligne-niveau" data-code="{code}" style="--prof:{rang}">', html)
        self.assertEqual(html.count('class="arbre-niveau"'), 4)

    def test_code_du_niveau_affiche_une_seule_fois_nulle_part_en_texte(self):
        html = self.page()
        self.assertNotIn("code-niveau", html)
        self.assertNotIn(">Country<", html)  # le code n'est plus répété sous le nom (« Pays »)
        self.assertIn('name="nom_Country"', html)  # il reste la clé des champs

    def test_lien_organisations_pres_du_titre_et_regle_dans_l_aide(self):
        html = self.page()
        tete = html.split('class="tete-apercu-arbre"')[1].split("</div>")[0]
        self.assertIn(reverse("collecte:admin_organisations"), tete)
        aide = html.split('<details class="aide-repliable aide-suppression">')[1].split("</details>")[0]
        self.assertIn("Vous ne pouvez monter un niveau", aide)
        apres_arbre = html.split('class="apercu-arbre"')[1]
        self.assertNotIn("Vous ne pouvez monter un niveau", apres_arbre)
