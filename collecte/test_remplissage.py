"""Filet de tests du taux de remplissage (Reste, Compteur, tableau de bord, progression) : figent le comportement actuel.

Taux = réponses validées (N/A validé compris) ÷ cases attendues ; une case calculée, saisie au-dessus de la granularité
ou couverte par une valeur saisie au-dessus n'est pas attendue ; arrondi à une décimale ; 0 quand rien n'est attendu."""
from decimal import Decimal

from referentiel.models import KPI, Niveau

from . import saisie as S
from .models import Reponse
from .aides_tests.echanges import Base
import datetime

from django.urls import reverse
from django.utils import timezone

from .aides_tests.arbre_france import Arbre
from .models import Campagne
from referentiel.models import Attribution, Utilisateur

D = Decimal


class CompteurEtResteTests(Base):
    def test_compteur_pourcentages_arrondis(self):
        c = S.Compteur()
        self.assertEqual((c.taux, c.pct_brouillon, c.pct(0)), (0, 0, 0))  # rien d'attendu : 0, pas d'erreur
        c = S.Compteur(total=3, valide=1, brouillon=2)
        self.assertEqual((c.taux, c.pct_brouillon), (33.3, 66.7))
        self.assertEqual(S.Compteur(total=8, valide=1).taux, 12.5)
        self.assertEqual(S.Compteur(total=6, valide=1).taux, 16.7)

    def test_reste_somme_et_organisation_suivante(self):
        a = S.Reste(total=3, valide=1, alertes=0)
        b = S.Reste(total=2, valide=2, alertes=1)
        self.assertEqual((a.valeurs, a.fini, a.taux, a.a_montrer), (2, False, 33.3, True))
        self.assertEqual((b.valeurs, b.fini, b.taux), (0, False, 100.0))  # une alerte reste à traiter
        self.assertTrue(S.Reste(total=2, valide=2).fini)
        self.assertEqual((S.Reste().taux, S.Reste().a_montrer, S.Reste().fini), (0, False, True))
        tout = S.Reste(par_org={self.e1: a, self.e2: b})._cumuler()
        self.assertEqual((tout.total, tout.valide, tout.alertes), (5, 3, 1))
        self.assertEqual((tout.nb_orgs, tout.nb_orgs_valeurs, tout.nb_orgs_alertes), (2, 1, 1))
        self.assertEqual(tout.suivante(), self.e1)  # des valeurs d'abord
        self.assertEqual(tout.suivante(sauf=self.e1), self.e2)  # sinon des alertes
        self.assertIsNone(S.Reste(par_org={self.e1: S.Reste(total=1, valide=1)}).suivante())
        ailleurs = tout.ailleurs(self.e1)
        self.assertEqual((ailleurs.total, ailleurs.valide, ailleurs.alertes), (2, 2, 1))
        self.assertEqual(tout.ici(self.p).total, 0)
        somme = sum([S.Reste(1, 0, 0, {self.e1: S.Reste(1, 0)}), S.Reste(2, 1, 0, {self.e1: S.Reste(2, 1)})])
        self.assertEqual((somme.total, somme.valide, somme.par_org[self.e1].total), (3, 1, 3))

    def test_reste_hors_selecteur_jamais_propose(self):
        r = S.Reste(par_org={self.e1: S.Reste(alertes=2, hors_selecteur=True)})._cumuler()
        self.assertEqual(r.alertes, 2)
        self.assertIsNone(r.suivante())


class TauxDeRemplissageTests(Base):
    """Cases attendues pour l'admin : EFF et TX pour E1 et E2 (DBL est calculé)."""

    def tdb(self, utilisateur=None, **kw):
        return S.tableau_de_bord(S.lignes(utilisateur or self.admin, self.c, **kw))

    def test_depart_aucune_validee(self):
        ls = S.lignes(self.admin, self.c)
        self.assertEqual(sorted((l.kpi.code, l.organisation.nom) for l in ls),
                         [("EFF", "E1"), ("EFF", "E2"), ("TX", "E1"), ("TX", "E2")])
        self.assertEqual(S.progression(ls), (0, 4))
        t = self.tdb()["total"]
        self.assertEqual((t.total, t.valide, t.brouillon, t.a_saisir, t.na, t.taux), (4, 0, 3, 1, 0, 0))

    def test_na_valide_compte_comme_une_reponse(self):
        S.enregistrer(self.admin, self.c, self.taux, self.e2, "", True, "Pas de salariés")
        S.valider(self.admin, self.c, self.taux, self.e2)
        S.valider(self.contrib, self.c, self.eff, self.e1)
        d = self.tdb()
        t = d["total"]
        self.assertEqual((t.valide, t.na, t.brouillon, t.a_saisir, t.taux), (2, 1, 2, 0, 50.0))
        par_org = {o.nom: c for o, c in d["par_org"]}
        self.assertEqual((par_org["E1"].taux, par_org["E2"].taux, par_org["Pays"].taux, par_org["Groupe"].total), (50.0, 50.0, 50.0, 4))
        self.assertEqual({o.nom: c.total for o, c in d["par_org_propre"].items()}, {"E1": 2, "E2": 2})
        self.assertEqual(S.progression(S.lignes(self.admin, self.c)), (2, 4))

    def test_na_en_brouillon_ne_compte_pas(self):
        S.enregistrer(self.admin, self.c, self.taux, self.e2, "", True, "")
        t = self.tdb()["total"]
        self.assertEqual((t.valide, t.na, t.brouillon, t.taux), (0, 1, 4, 0))

    def test_par_spoc_sans_spoc_en_tete(self):
        d = self.tdb()
        self.assertEqual([(u, c.total) for u, c in d["par_spoc"]], [(None, 2), (self.contrib, 2)])

    def test_contributeur_ne_compte_que_ses_cases(self):
        S.valider(self.contrib, self.c, self.eff, self.e1)
        t = self.tdb(self.contrib)["total"]
        self.assertEqual((t.total, t.valide, t.taux), (2, 1, 50.0))

    def test_cases_calculees_jamais_attendues(self):
        ls = S.lignes(self.admin, self.c, org=self.p, calculees=True)
        self.assertEqual(sorted((l.kpi.code, l.calculee, l.attendue) for l in ls), [("DBL", True, False), ("EFF", True, False)])
        self.assertEqual(S.tableau_de_bord(ls)["total"].total, 0)
        self.assertEqual(S.progression(ls), (0, 0))

    def test_saisie_au_dessus_couvre_les_cases_du_dessous(self):
        self.eff.saisie_au_dessus = True
        self.eff.save()
        ls = S.lignes(self.admin, self.c, org=self.p)
        dessus = [l for l in ls if l.kpi.code == "EFF"]
        self.assertEqual([(l.au_dessus, l.attendue, l.saisie_ici) for l in dessus], [(True, False, False)])  # facultative
        S.enregistrer(self.admin, self.c, self.eff, self.p, "500", False, "Estimation pays")
        ls = S.lignes(self.admin, self.c)
        couvertes = {l.organisation.nom: l.couverte for l in ls if l.kpi.code == "EFF"}
        self.assertEqual(couvertes, {"E1": self.p, "E2": self.p})
        self.assertEqual(S.progression(ls), (0, 2))  # seules les cases TX restent attendues
        self.assertTrue(next(l for l in S.lignes(self.admin, self.c, org=self.p) if l.kpi.code == "EFF").saisie_ici)
        sel = {o.nom: (t, v) for o, t, v, _ in S.organisations_visibles(self.admin, self.c)}
        self.assertEqual(sel["E1"], (1, 0))

    def test_kpi_inactif_ou_organisation_inactive_hors_du_taux(self):
        self.e2.actif = False
        self.e2.save()
        self.assertEqual(self.tdb()["total"].total, 2)
        KPI.objects.filter(code="TX").update(actif=False)
        self.assertEqual(self.tdb()["total"].total, 1)

    def test_selecteur_des_organisations(self):
        S.valider(self.contrib, self.c, self.eff, self.e1)
        sel = [(o.nom, t, v, a) for o, t, v, a in S.organisations_visibles(self.admin, self.c)]
        self.assertEqual(sel, [("Groupe", 0, 0, 0), ("Pays", 0, 0, 0), ("E1", 2, 1, 0), ("E2", 2, 0, 0)])
        r = S.reste_par_org(S.organisations_visibles(self.admin, self.c))
        self.assertEqual((r.total, r.valide, r.valeurs, r.taux), (4, 1, 3, 25.0))
        self.assertEqual([(o.nom, t, v) for o, t, v, _ in S.organisations_visibles(self.contrib, self.c)], [("E1", 2, 1)])

    def test_validee_puis_modifiee_repasse_en_brouillon(self):
        S.valider(self.contrib, self.c, self.eff, self.e1)
        self.assertEqual(self.tdb()["total"].valide, 1)
        S.enregistrer(self.contrib, self.c, self.eff, self.e1, "111", False, "Embauches")
        r = Reponse.objects.get(periode=self.c.periode, kpi=self.eff, organisation=self.e1)
        self.assertEqual((r.statut, r.valide_par, r.date_validation), (Reponse.Statut.BROUILLON, None, None))
        self.assertEqual(self.tdb()["total"].valide, 0)
        S.enregistrer(self.contrib, self.c, self.eff, self.e1, "", False, "")  # case vidée : à saisir
        self.assertEqual(Reponse.objects.get(pk=r.pk).statut, Reponse.Statut.A_SAISIR)

    def test_meme_valeur_reenregistree_garde_la_validation(self):
        S.valider(self.contrib, self.c, self.eff, self.e1)
        S.enregistrer(self.contrib, self.c, self.eff, self.e1, "110,0", False, "Embauches")
        self.assertEqual(Reponse.objects.get(periode=self.c.periode, kpi=self.eff, organisation=self.e1).statut, Reponse.Statut.VALIDE)


class ValidationEtEcartTests(Base):
    def test_validation_refusee_sans_valeur_et_na_sans_commentaire(self):
        with self.assertRaisesMessage(Exception, "Saisissez une valeur ou cochez N/A."):
            S.valider(self.admin, self.c, self.taux, self.e2)
        S.enregistrer(self.admin, self.c, self.taux, self.e2, "", True, "")
        with self.assertRaisesMessage(Exception, "Si vous cochez N/A, saisissez un commentaire."):
            S.valider(self.admin, self.c, self.taux, self.e2)

    def test_seuil_d_ecart_avec_n1_exige_un_commentaire(self):
        self.c.seuil_ecart = D("0.2")
        self.c.save()
        S.enregistrer(self.admin, self.c, self.eff, self.e1, "130", False, "")  # +30 % sur 100 (N-1)
        with self.assertRaisesMessage(Exception, "dépasse 20 %"):
            S.valider(self.admin, self.c, self.eff, self.e1)
        S.enregistrer(self.admin, self.c, self.eff, self.e1, "120", False, "")  # +20 % : au seuil, accepté
        S.valider(self.admin, self.c, self.eff, self.e1)
        ligne = next(l for l in S.lignes(self.admin, self.c) if (l.kpi.code, l.organisation) == ("EFF", self.e1))
        self.assertEqual((ligne.n1.valeur, ligne.ecart), (D(100), D("0.2")))
        self.assertIsNone(next(l for l in S.lignes(self.admin, self.c) if (l.kpi.code, l.organisation) == ("EFF", self.e2)).ecart)

    def test_ecart_ignore_quand_n1_est_na(self):
        Reponse.objects.filter(periode=self.c0.periode, kpi=self.eff, organisation=self.e1).update(non_applicable=True, valeur=None)
        self.c.seuil_ecart = D("0.01")
        self.c.save()
        S.valider(self.contrib, self.c, self.eff, self.e1)  # pas d'écart calculable : validation possible
        ligne = next(l for l in S.lignes(self.admin, self.c) if (l.kpi.code, l.organisation) == ("EFF", self.e1))
        self.assertIsNone(ligne.ecart)

    def test_pas_de_seuil_pour_oui_non(self):
        from parametres.models import TypeReponse

        on = TypeReponse.objects.create(code="OuiNon", libelle="Oui / non", format="oui_non")
        pol = KPI.objects.create(code="POL", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY, type_reponse=on, methode_agregation="Décompte")
        self.c.seuil_ecart = D("0.01")
        self.c.save()
        S.enregistrer(self.admin, self.c, pol, self.e1, "oui", False, "")
        self.assertEqual(S.valider(self.admin, self.c, pol, self.e1).statut, Reponse.Statut.VALIDE)
        r = Reponse.objects.get(periode=self.c.periode, kpi=pol, organisation=self.p)
        self.assertEqual((r.texte, r.valeur), ("", None))  # E2 sans réponse : décompte incomplet
        self.assertEqual(r.statut, Reponse.Statut.INCOMPLET)


# ---------------------------------------------------------------- 2. KPI facultatifs : comptés nulle part (CALC-13)
class FacultatifsTests(Arbre):
    """Le constat : A, B, C obligatoires, OPT facultatif ; E1 et E2 ont tout validé sauf OPT. Avant : taux en tête 75 %,
    carte « Campagnes en cours » 100 %, relance proposée pour OPT seul, retard compté avec OPT."""

    def setUp(self):
        super().setUp()
        from referentiel.composition import composer
        from referentiel.models import ElementReferentiel, Referentiel

        self.ref = Referentiel.objects.get(pk=self.c.referentiel_id)
        for code in ("A", "B", "C", "OPT"):
            self.kpi(code)
        composer({code: ["Thème"] for code in ("A", "B", "C", "OPT")}, self.ref)
        ElementReferentiel.objects.filter(referentiel=self.ref, kpi_id="OPT").update(obligatoire=False)
        self.contrib = Utilisateur.objects.create(username="contrib", email="contrib@exemple.test", first_name="Camille")
        self.valid = Utilisateur.objects.create(username="valid", email="valid@exemple.test", role=Utilisateur.Role.VALIDATEUR)
        for org in (self.e1, self.e2):
            for code in ("A", "B", "C", "OPT"):
                Attribution.objects.create(kpi_id=code, organisation=org, utilisateur=self.contrib)
                if code != "OPT":
                    Reponse.objects.create(periode=self.c.periode, kpi_id=code, organisation=org, valeur=D(1),
                                           statut=Reponse.Statut.VALIDE, origine=Reponse.Origine.SAISIE, saisi_par=self.contrib)
        Attribution.objects.create(kpi_id="A", organisation=self.fr, utilisateur=self.valid, role=Attribution.Role.VALIDATEUR)
        self.c.date_ouverture = timezone.localdate() - datetime.timedelta(days=30)
        self.c.save()

    def test_tableau_de_bord(self):
        self.client.force_login(self.admin)
        rep = self.client.get(reverse("collecte:tableau_de_bord") + f"?campagne={self.c.pk}")
        total = rep.context["total"]
        self.assertEqual((total.valide, total.total, total.taux), (6, 6, 100.0))  # avant : 75 %
        self.assertEqual({c.pk: (n.valide, n.total) for c, n in rep.context["avancement"]}, {self.c.pk: (6, 6)})
        self.assertEqual((rep.context["facultatifs"].valide, rep.context["facultatifs"].total), (0, 2))
        self.assertContains(rep, "KPI facultatifs saisis : 0 / 2")
        self.assertEqual(rep.context["retards"], set())  # avant : E1 et E2 en retard à cause de OPT
        self.assertIsNone(rep.context["sans_spoc"])  # « À relancer » n'est plus sur le tableau de bord

    def test_relances_et_ce_qui_reste(self):
        from . import relances as RL

        self.assertEqual(RL.a_faire([self.c]), [])  # e-mails compris : personne n'est relancé pour OPT seul
        self.assertEqual(RL.restes_sans_spoc([self.c]), 0)
        Reponse.objects.filter(kpi_id="A", organisation=self.e2).update(statut=Reponse.Statut.BROUILLON)
        af = RL.a_faire([self.c])
        self.assertEqual([(x.personne, [l.kpi.code for l in x.lignes]) for x in af], [(self.contrib, ["A"])])
        self.assertNotIn("OPT", RL.liste_texte(af[0]))

    def test_pour_moi_saisie_et_je_reponds_a(self):
        self.client.force_login(self.contrib)
        rep = self.client.get(reverse("collecte:pour_moi") + f"?campagne={self.c.pk}")
        self.assertEqual(rep.context["etat"].valeurs, 0)
        self.assertEqual(rep.context["bandeau"]["code"], "fini")
        html = rep.content.decode()
        self.assertIn('<span class="facultatif">facultatif', html)  # la case reste visible et saisissable
        self.assertEqual(html.count('data-statut="a_saisir" data-attendue="0"'), 2)  # hors de la chaîne « Valider et suivant »
        rep = self.client.get(reverse("collecte:choix_reponse"))
        reste = rep.context["blocs"][0]["en_cours"][0][1]
        self.assertEqual((reste.total, reste.valide), (6, 6))
        self.client.force_login(self.admin)
        orgs = {o.nom: (t, v) for o, t, v, _ in S.organisations_visibles(self.admin, self.c)}
        self.assertEqual((orgs["E1"], orgs["E2"]), ((3, 3), (3, 3)))
        S.enregistrer(self.contrib, self.c, KPI.objects.get(code="OPT"), self.e1, "5", False, "")  # saisissable
        S.valider(self.contrib, self.c, KPI.objects.get(code="OPT"), self.e1)
        rep = self.client.get(reverse("collecte:tableau_de_bord") + f"?campagne={self.c.pk}")
        self.assertEqual((rep.context["facultatifs"].valide, rep.context["total"].total), (1, 6))

    def test_exports_et_fichier_a_remplir(self):
        from . import exports as E
        from . import imports as I

        p = E.Parametres.depuis(E.PRESETS["manquantes"][2])
        self.assertEqual([(l.kpi.code, l.org.nom) for l in E.collecter(self.admin, p)], [])  # avant : OPT × 2
        p = E.Parametres.depuis(E.PRESETS["revue"][2])
        lignes = E.collecter(self.admin, p)
        self.assertNotIn("OPT", {l.kpi.code for l in lignes})
        self.assertEqual({o.nom: c for o, c in E._avancement(lignes).items()}, {"E1": [3, 3, 0], "E2": [3, 3, 0]})
        self.assertEqual(I.lignes_modele(self.contrib, self.c, seulement_a_faire=True), [])
        tout = I.lignes_modele(self.contrib, self.c)
        self.assertEqual(sorted(l.kpi.code for l in tout if l.facultatif), ["OPT", "OPT"])
        import io

        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(I.modele(self.contrib, self.c, tout).content))
        formules = [c.value for ws in wb.worksheets for r in ws.iter_rows() for c in r if isinstance(c.value, str) and "Facultatif" in c.value]
        self.assertEqual(len(formules), 2)

    def test_obligatoire_dans_un_autre_referentiel_de_la_periode(self):
        from referentiel.composition import composer
        from referentiel.models import Referentiel

        from . import relances as RL

        autre = Referentiel.objects.create(code="AUTRE", nom="Autre", ordre=5)
        composer({"OPT": ["Thème"]}, autre)  # obligatoire ici
        c2 = Campagne.objects.create(referentiel=autre, periode=self.c.periode, exercice=2026, statut=Campagne.Statut.OUVERTE,
                                     date_fin_saisie=self.c.date_fin_saisie)
        af = RL.a_faire([self.c, c2])
        self.assertEqual([(c.referentiel_id, sorted(l.kpi.code for l in ls)) for c, ls in af[0].campagnes], [("AUTRE", ["OPT", "OPT"])])
        self.client.force_login(self.admin)
        rep = self.client.get(reverse("collecte:tableau_de_bord") + f"?campagne={c2.pk}")
        self.assertEqual(rep.context["total"].total, 2)
        from . import exports as E

        p = E.Parametres.depuis(E.PRESETS["manquantes"][2])
        self.assertEqual(sorted((l.kpi.code, l.org.nom) for l in E.collecter(self.admin, p)), [("OPT", "E1"), ("OPT", "E2")])
