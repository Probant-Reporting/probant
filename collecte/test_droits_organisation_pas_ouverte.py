"""Valeur pour une organisation qui n'est pas ouverte pendant la période (date d'ouverture, la sienne ou celle d'un
ancêtre, après la période) : refusée partout (constat 6 ; règle du projet :
« refuser et proposer de modifier la date d'ouverture »). Écran (adresse directe), import (motif dans l'aperçu, qui nomme
l'organisation et sa date), serveur MCP (même fonction ``saisie.enregistrer``). Un administrateur reçoit un lien vers la
fiche de l'organisation qui porte la date ; les autres rôles, l'indication de s'adresser à un administrateur.

Données inventées uniquement."""
import datetime

from django.core.exceptions import PermissionDenied
from django.urls import reverse

from referentiel.models import Organisation

from . import imports as I
from . import saisie as S
from .aides_tests.echanges import Base
from .models import Campagne, Reponse
from .outils_tests import xlsx

ENTETES = ["ID KPI", "Organisation", "Exercice", "Valeur", "Commentaire"]


class OrganisationPasOuverteTests(Base):
    def setUp(self):
        super().setUp()
        # le pays (parent de E1 et E2) n'ouvre qu'en 2027 : ni E1 ni E2 ne sont ouvertes en 2026
        Organisation.objects.filter(pk=self.p.pk).update(date_ouverture=datetime.date(2027, 1, 1))
        self.c = Campagne.objects.get(pk=self.c.pk)  # objet relu (l'arbre est lu une fois par objet campagne)

    def test_ecran_administrateur_refus_et_lien_vers_la_fiche(self):
        d = S.droits(self.admin, self.c, self.eff, self.e2)
        self.assertTrue(d.voir)
        self.assertFalse(d.modifier)
        self.assertIn("01/01/2027", d.motif)
        self.assertIn("Pays", d.motif)
        self.assertEqual(d.lien, reverse("collecte:admin_organisation", args=[self.p.pk]))
        with self.assertRaises(PermissionDenied):
            S.enregistrer(self.admin, self.c, self.eff, self.e2, "41", False, "")
        self.assertEqual(Reponse.objects.get(periode=self.c.periode, kpi=self.eff, organisation=self.e2).valeur, 40)
        self.client.force_login(self.admin)
        page = self.client.get(reverse("collecte:cellule", args=[self.c.pk, "EFF", self.e2.pk])).content.decode()
        self.assertIn(reverse("collecte:admin_organisation", args=[self.p.pk]), page)

    def test_contributeur_s_adresse_a_un_administrateur(self):
        d = S.droits(self.contrib, self.c, self.eff, self.e1)
        self.assertFalse(d.modifier)
        self.assertIn("administra", d.motif)
        self.assertEqual(d.lien, "")

    def test_import_ligne_refusee_avec_le_motif(self):
        a = I.analyser(self.admin, xlsx([ENTETES, ["EFF", "E2", 2026, 41, ""]]), campagne_defaut=self.c.pk)
        l = a.lignes[0]
        self.assertNotIn(l.action, ("creer", "modifier"))
        self.assertIn("Pays", l.motif)
        self.assertIn("01/01/2027", l.motif)

    def test_sans_date_rien_ne_change(self):
        Organisation.objects.filter(pk=self.p.pk).update(date_ouverture=None)
        self.c = Campagne.objects.get(pk=self.c.pk)
        self.assertTrue(S.droits(self.admin, self.c, self.eff, self.e2).modifier)

