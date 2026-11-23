"""Fiche d'une organisation : date d'ouverture. Refusée après la date de fermeture ; après
des valeurs déjà saisies, la fiche avertit et n'enregistre qu'avec la case de confirmation cochée.

Données inventées uniquement."""
import datetime
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from referentiel.models import KPI, Niveau, Organisation, Utilisateur

from . import periodes as P
from .administration import OrganisationForm
from .models import Journal, Reponse


class FicheDateOuvertureTests(TestCase):
    def setUp(self):
        self.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.e = Organisation.objects.create(nom="E1", niveau_id=Niveau.ENTITY, parent=self.g)
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN)
        self.admin.set_password("x")
        self.admin.save()

    def donnees(self, **champs):
        d = {"nom": self.e.nom, "code": self.e.code, "niveau": Niveau.ENTITY, "parent": self.g.pk, "rang": 0, "actif": "on"}
        d.update(champs)
        return d

    def test_date_d_ouverture_apres_la_fermeture_refusee(self):
        f = OrganisationForm(self.donnees(actif="", date_desactivation="2025-03-31", date_ouverture="2025-06-01"),
                             instance=self.e)
        self.assertFalse(f.is_valid())
        self.assertIn("date_ouverture", f.errors)

    def test_sans_valeur_la_date_s_enregistre(self):
        f = OrganisationForm(self.donnees(date_ouverture="2026-03-01"), instance=self.e)
        self.assertTrue(f.is_valid(), f.errors)

    def test_valeurs_avant_la_date_demandent_une_confirmation(self):
        KPI.objects.create(code="EFF", libelle="Effectif", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                           methode_agregation="Somme")
        Reponse.objects.create(periode=P.annuelle(2025), kpi_id="EFF", organisation=self.e, valeur=Decimal(3),
                               origine=Reponse.Origine.SAISIE)
        f = OrganisationForm(self.donnees(date_ouverture="2026-01-01"), instance=self.e)
        self.assertFalse(f.is_valid())
        self.assertEqual(f.valeurs_avant_ouverture, 1)
        self.assertIn("2025", str(f.errors["date_ouverture"]))
        self.assertTrue(OrganisationForm(self.donnees(date_ouverture="2025-12-31"), instance=self.e).is_valid())  # 2025 compte
        self.assertTrue(OrganisationForm(self.donnees(date_ouverture="2026-01-01", confirmer_ouverture="on"),
                                         instance=self.e).is_valid())

    def test_enregistree_par_la_fiche_et_ecrite_au_journal(self):
        self.client.force_login(self.admin)
        rep = self.client.post(reverse("collecte:admin_organisation", args=[self.e.pk]),
                               self.donnees(date_ouverture="2026-03-01", action="enregistrer"))
        self.assertIn(rep.status_code, (200, 302))
        self.e.refresh_from_db()
        self.assertEqual(self.e.date_ouverture, datetime.date(2026, 3, 1))
        self.assertTrue(Journal.objects.filter(action="reglage_organisation", champ="date_ouverture").exists())
        page = self.client.get(reverse("collecte:admin_organisation", args=[self.e.pk]))
        self.assertContains(page, "Ouverte depuis")
