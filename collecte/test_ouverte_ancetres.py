"""Une organisation ne peut pas être ouverte avant son parent (constat 1) : une date d'ouverture
posée sur une organisation qui a des enfants vaut aussi pour eux (``calcul.ouverte``, seule fonction qui porte la règle).
Avant : l'entité n'avait plus de case avant sa date, mais ses sites restaient ouverts, à saisir, et leurs valeurs ne
comptaient plus dans aucun total. La fiche, le collage et l'import du classeur de configuration le disent.

Données inventées uniquement."""
import datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from referentiel.composition import composer
from referentiel.models import KPI, Niveau, Organisation, Referentiel, Utilisateur

from . import calcul as C
from . import periodes as P
from . import saisie as S
from .administration import OrganisationForm
from .models import Campagne, Reponse

D = Decimal


class Arbre(TestCase):
    """Groupe > E1 (sites L1, L2), E2 (site M1) ; KPI saisi au site, sommé."""

    def setUp(self):
        self.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.e1 = Organisation.objects.create(nom="E1", niveau_id=Niveau.ENTITY, parent=self.g)
        self.e2 = Organisation.objects.create(nom="E2", niveau_id=Niveau.ENTITY, parent=self.g)
        self.l1 = Organisation.objects.create(nom="L1", niveau_id=Niveau.SITE, parent=self.e1)
        self.l2 = Organisation.objects.create(nom="L2", niveau_id=Niveau.SITE, parent=self.e1)
        self.m1 = Organisation.objects.create(nom="M1", niveau_id=Niveau.SITE, parent=self.e2)
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN)
        KPI.objects.create(code="EAU", libelle="Eau", type_saisie_id="Saisi", granularite_id=Niveau.SITE,
                           methode_agregation="Somme")
        self.ref = Referentiel.objects.create(code="RAP", nom="Rapport", ordre=1)
        composer({"EAU": ["Environnement"]}, self.ref)
        fin = timezone.localdate() + datetime.timedelta(days=30)
        self.c25 = P.campagne(self.ref, datetime.date(2025, 1, 1), statut=Campagne.Statut.OUVERTE, date_fin_saisie=fin)[0]
        for org, v in ((self.l1, 10), (self.l2, 20), (self.m1, 5)):
            Reponse.objects.create(periode=self.c25.periode, kpi_id="EAU", organisation=org, valeur=D(v),
                                   statut=Reponse.Statut.VALIDE, origine=Reponse.Origine.SAISIE)

    def total(self, org):
        r = Reponse.objects.filter(periode=self.c25.periode, kpi_id="EAU", organisation=org).first()
        return None if r is None else (r.valeur, r.statut)


class OuverteAncetresTests(Arbre):
    def test_sans_date_rien_ne_change(self):
        orgs = {o.id: o for o in Organisation.objects.all()}
        for o in orgs.values():
            self.assertTrue(C.ouverte(o, self.c25.periode, orgs))
            self.assertTrue(C.ouverte(o, self.c25.periode))

    def test_un_site_n_est_pas_ouvert_avant_son_entite(self):
        Organisation.objects.filter(pk=self.e1.pk).update(date_ouverture=datetime.date(2026, 1, 1))
        orgs = {o.id: o for o in Organisation.objects.all()}
        p = self.c25.periode
        self.assertFalse(C.ouverte(orgs[self.l1.id], p, orgs))
        self.assertFalse(C.ouverte(Organisation.objects.get(pk=self.l1.pk), p))  # sans l'arbre : lu par le parent
        self.assertTrue(C.ouverte(orgs[self.m1.id], p, orgs))
        self.assertTrue(C.ouverte(orgs[self.l1.id], P.annuelle(2026), orgs))

    def test_une_desactivation_du_parent_ne_se_propage_pas(self):
        # seule la date d'ouverture d'un ancêtre se propage (sans date, rien ne change, même pour un parent fermé)
        Organisation.objects.filter(pk=self.e1.pk).update(actif=False)
        orgs = {o.id: o for o in Organisation.objects.all()}
        self.assertTrue(C.ouverte(orgs[self.l1.id], self.c25.periode, orgs))

    def test_calcul_et_cases_a_saisir_coincident(self):
        Organisation.objects.filter(pk=self.e1.pk).update(date_ouverture=datetime.date(2026, 1, 1))
        C.recalculer(self.c25)
        self.assertEqual(self.total(self.g), (D(5), Reponse.Statut.CALCULE))  # E1 et ses sites ne comptent pas en 2025
        orgs = {o.id for k, o in S.cellules(self.admin, campagne=self.c25)}
        self.assertEqual(orgs, {self.m1.id})  # rien à saisir pour L1, L2 en 2025


class FicheAncetresTests(Arbre):
    def donnees(self, **champs):
        d = {"nom": self.e1.nom, "code": self.e1.code, "niveau": Niveau.ENTITY, "parent": self.g.pk, "rang": 0,
             "actif": "on"}
        d.update(champs)
        return d

    def test_la_fiche_compte_les_valeurs_des_organisations_en_dessous(self):
        f = OrganisationForm(self.donnees(date_ouverture="2026-01-01"), instance=self.e1)
        self.assertFalse(f.is_valid())
        self.assertEqual(f.valeurs_avant_ouverture, 2)  # L1 et L2, l'entité elle-même n'en a pas
        self.assertIn("2025", str(f.errors["date_ouverture"]))
        self.assertTrue(OrganisationForm(self.donnees(date_ouverture="2026-01-01", confirmer_ouverture="on"),
                                         instance=self.e1).is_valid())

    def test_deplacee_sous_un_parent_ouvert_plus_tard(self):
        Organisation.objects.filter(pk=self.e2.pk).update(date_ouverture=datetime.date(2026, 1, 1))
        d = {"nom": self.l1.nom, "code": self.l1.code, "niveau": Niveau.SITE, "parent": self.e2.pk, "rang": 0, "actif": "on"}
        f = OrganisationForm(d, instance=self.l1)
        self.assertFalse(f.is_valid())
        self.assertEqual(f.valeurs_avant_ouverture, 1)


class ImportEtCollageAncetresTests(Arbre):
    def test_l_apercu_de_l_import_de_configuration_avertit(self):
        from collecte.outils_tests import xlsx

        from . import configuration as CF

        lignes = [["Nom", "Niveau", "Rattachée à", "Ouverte depuis"], ["E1", "Entité", "Groupe", "01/01/2026"]]
        ch = CF.analyser(xlsx({"Organisations": lignes})).onglets["Organisations"][0]
        self.assertEqual(ch.action, "modifier")  # pas de refus : l'administrateur relit l'aperçu
        self.assertIn("2", ch.avertissement)  # L1 et L2
        self.assertIn("2025", ch.avertissement)
        lignes[1][3] = "01/01/2025"  # 2025 compte encore : rien à dire
        self.assertEqual(CF.analyser(xlsx({"Organisations": lignes})).onglets["Organisations"][0].avertissement, "")

    def test_le_collage_dit_la_date_qui_vaut_pour_les_organisations_en_dessous(self):
        from parametres import niveaux as N
        from parametres.mise_en_place import lire_arbre

        Organisation.objects.filter(pk=self.e1.pk).update(date_ouverture=datetime.date(2026, 3, 1))
        niveaux = list(N.tous())
        nom = {n.code: n.nom for n in niveaux}
        e, s = nom[Niveau.ENTITY], nom[Niveau.SITE]
        noeuds, erreurs = lire_arbre(f"Groupe\n  E1 [{e}]\n    L9 [{s}]\n  E7 [{e}, 2027-01-01]\n    L8 [{s}, 2025-01-01]\n"
                                     f"    L7 [{s}]", niveaux)
        self.assertEqual(erreurs, [])
        par_nom = {x.nom: x for x in noeuds}
        self.assertEqual(par_nom["L9"].ouverture_parent, (datetime.date(2026, 3, 1), "E1"))  # E1 existante
        self.assertEqual(par_nom["L8"].ouverture_parent, (datetime.date(2027, 1, 1), "E7"))  # E7 collée
        self.assertEqual(par_nom["L7"].ouverture_parent, (datetime.date(2027, 1, 1), "E7"))
        self.assertIsNone(par_nom["E7"].ouverture_parent)
