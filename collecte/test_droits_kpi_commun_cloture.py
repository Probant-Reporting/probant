"""Droits : un KPI commun à deux référentiels d'une même période ne se modifie plus dans la campagne ouverte quand l'autre
campagne de la période est clôturée. La valeur est unique pour la période : la changer
modifierait une campagne figée. Tous les chemins d'écriture passent par la même règle."""
from decimal import Decimal

from django.core.exceptions import PermissionDenied
from django.urls import reverse

from parametres.libelles import libelle
from referentiel.models import ElementReferentiel, Referentiel

from . import forcage as FO
from . import imports as I
from . import saisie as S
from .aides_tests.arbre_france import csv_
from .aides_tests.saisie import Base
from .models import Campagne, Reponse

D = Decimal


class KpiCommunClotureTests(Base):
    def setUp(self):
        super().setUp()
        # référentiel de la campagne ouverte : EFF et TX ; l'autre référentiel : EFF (commun) et DBL
        for k in (self.eff, self.taux):
            ElementReferentiel.objects.create(referentiel=self.c.referentiel, kpi=k)
        self.autre_ref = Referentiel.objects.create(code="AUTRE", nom="Cadre voisin", ordre=99)  # après : l'import vise d'abord la campagne ouverte
        ElementReferentiel.objects.create(referentiel=self.autre_ref, kpi=self.eff)
        self.voisine = Campagne.objects.create(referentiel=self.autre_ref, periode=self.c.periode,
                                               exercice=self.c.exercice, statut=Campagne.Statut.OUVERTE)
        self.r = S.enregistrer(self.contrib, self.c, self.eff, self.e1, "10", False, "")

    def clore_voisine(self):
        Campagne.objects.filter(pk=self.voisine.pk).update(statut=Campagne.Statut.CLOTUREE)
        self.c = Campagne.objects.get(pk=self.c.pk)  # objets neufs : le périmètre voisin est mis en cache par objet

    def motif(self):
        return libelle("saisie.msg.kpi_commun_cloture", campagne=self.voisine.libelle, referentiel="Cadre voisin")

    def test_voisine_ouverte_rien_ne_change(self):
        self.assertTrue(S.droits(self.contrib, self.c, self.eff, self.e1).modifier)
        self.assertTrue(S.droits(self.admin, self.c, self.eff, self.e1).modifier)

    def test_voisine_cloturee_bloque_la_modification_pour_tous_les_roles(self):
        self.clore_voisine()
        for u in (self.contrib, self.admin):
            d = S.droits(u, self.c, self.eff, self.e1)
            self.assertEqual((d.voir, d.modifier, d.repasser_brouillon, d.motif), (True, False, False, self.motif()), u.username)
        self.assertIn("Cadre voisin", self.motif())

    def test_kpi_propre_a_la_campagne_ouverte_reste_modifiable(self):
        self.clore_voisine()
        self.assertTrue(S.droits(self.contrib, self.c, self.taux, self.e1).modifier)
        S.enregistrer(self.contrib, self.c, self.taux, self.e1, "35", False, "")

    def test_voisine_cloturee_sans_ce_kpi_ne_bloque_pas(self):
        ElementReferentiel.objects.filter(referentiel=self.autre_ref, kpi=self.eff).delete()
        ElementReferentiel.objects.create(referentiel=self.autre_ref, kpi=self.taux)
        self.clore_voisine()
        self.assertTrue(S.droits(self.contrib, self.c, self.eff, self.e1).modifier)

    def test_voisine_cloturee_d_une_autre_periode_ne_bloque_pas(self):
        # l'exercice précédent (campagne clôturée de l'autre période) n'a rien à voir
        self.assertTrue(S.droits(self.contrib, self.c, self.eff, self.e1).modifier)

    def test_chemins_d_ecriture_de_la_saisie_refuses(self):
        self.clore_voisine()
        avant = Reponse.objects.get(pk=self.r.pk)
        appels = {
            "enregistrer": lambda u: S.enregistrer(u, self.c, self.eff, self.e1, "99", False, ""),
            "n/a": lambda u: S.enregistrer(u, self.c, self.eff, self.e1, "", True, "sans objet"),
            "effacer": lambda u: S.enregistrer(u, self.c, self.eff, self.e1, "", False, ""),
            "valider": lambda u: S.valider(u, self.c, self.eff, self.e1),
            "repasser_brouillon": lambda u: S.repasser_brouillon(u, self.c, self.eff, self.e1),
            "remettre_a_saisir": lambda u: S.remettre_a_saisir(u, self.c, self.eff, self.e1),
        }
        for nom, appel in appels.items():
            for u in (self.contrib, self.admin):
                with self.assertRaises(PermissionDenied, msg=f"{nom} / {u.username}") as e:
                    appel(u)
                self.assertEqual(str(e.exception), self.motif())
        apres = Reponse.objects.get(pk=self.r.pk)
        self.assertEqual((apres.valeur, apres.statut, apres.non_applicable), (avant.valeur, avant.statut, avant.non_applicable))

    def test_preuves_refusees(self):
        from .aides_tests.saisie import fichier

        self.clore_voisine()
        with self.assertRaises(PermissionDenied):
            S.ajouter_preuve(self.admin, self.c, self.eff, self.e1, fichier())

    def test_panneau_montre_le_motif_et_refuse_l_envoi(self):
        self.clore_voisine()
        self.client.force_login(self.admin)
        url = reverse("collecte:cellule", args=[self.c.pk, self.eff.pk, self.e1.pk])
        self.assertContains(self.client.get(url), "Cadre voisin")
        self.assertEqual(self.client.post(url, {"action": "enregistrer", "valeur": "77"}).status_code, 403)
        self.assertEqual(Reponse.objects.get(pk=self.r.pk).valeur, D(10))

    def test_import_ligne_rejetee_avec_ce_motif(self):
        self.clore_voisine()
        lignes = [["ID KPI", "Organisation", "Exercice", "Valeur"], ["EFF", "E1", 2026, "55"], ["TX", "E1", 2026, "30"]]
        a = I.analyser(self.admin, csv_(lignes), campagne_defaut=self.c.pk)
        par_kpi = {l.kpi.code: l for l in a.lignes}
        self.assertEqual(par_kpi["EFF"].action, "rejet")
        self.assertEqual(par_kpi["EFF"].motif, self.motif())
        self.assertNotEqual(par_kpi["TX"].action, "rejet")
        a, n, _ = I.appliquer(self.admin, csv_(lignes), campagne_defaut=self.c.pk)
        self.assertEqual(Reponse.objects.get(pk=self.r.pk).valeur, D(10))

    def test_valeur_forcee_refusee(self):
        # KPI calculé commun aux deux référentiels : le forçage écrit dans la période partagée
        ElementReferentiel.objects.create(referentiel=self.c.referentiel, kpi=self.calc)
        ElementReferentiel.objects.create(referentiel=self.autre_ref, kpi=self.calc)
        self.clore_voisine()
        self.assertFalse(FO.peut_demander(self.admin, self.c, self.calc, self.e1))
        with self.assertRaises(PermissionDenied) as e:
            FO.demander(self.admin, self.c, self.calc, self.e1, "5", False, "essai")
        self.assertEqual(str(e.exception), libelle("saisie.msg.kpi_commun_cloture", campagne=self.voisine.libelle,
                                                   referentiel="Cadre voisin"))
        self.assertFalse(Reponse.objects.filter(kpi=self.calc, origine=Reponse.Origine.FORCEE).exists())

    def test_messages_dans_les_trois_langues(self):
        import json
        from pathlib import Path

        racine = Path(__file__).resolve().parent.parent / "libelles"
        for langue in ("en", "fr", "es"):
            textes = json.loads((racine / f"saisie.{langue}.json").read_text(encoding="utf-8"))
            texte = textes["saisie.msg.kpi_commun_cloture"]
            self.assertIn("{campagne}", texte, langue)
            self.assertIn("{referentiel}", texte, langue)
