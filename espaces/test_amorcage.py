"""Amorçage du registre commun sur une installation existante, réconciliation, sauvegardes sans le registre."""
from django.contrib.auth.hashers import make_password
from django.test import TestCase

from parametres import sauvegardes as SV
from referentiel.models import Utilisateur

from . import comptes
from .models import AccesEspace, Compte, Espace, Installation, MarqueEspace


def anciens_comptes():
    """Base d'une version d'avant les espaces : des comptes aux numéros non contigus, registre vide."""
    mdp = make_password("ancien-mot-de-passe-2026")
    Utilisateur.objects.bulk_create([
        Utilisateur(pk=5, username="ada", email="ada@exemple.example", password=mdp, role="admin", first_name="Ada"),
        Utilisateur(pk=12, username="bob", email="bob@exemple.example", password=mdp, role="contributeur", doit_changer_mdp=True),
        Utilisateur(pk=40, username="cyd", email="cyd@exemple.example", password=mdp, role="admin", is_active=False),
    ])
    Compte.objects.all().delete()


class AmorcageTests(TestCase):
    def test_registre_identique_a_l_espace_principal(self):
        anciens_comptes()
        avant = SV.comptes()
        comptes.amorcer()
        self.assertEqual(Installation.objects.count(), 1)
        self.assertEqual(list(Espace.objects.values_list("code", "etat")), [("principal", "actif")])
        marque = MarqueEspace.objects.get()
        self.assertEqual((marque.code, marque.installation), ("principal", Installation.objects.get().identifiant))
        for u in Utilisateur.objects.all():
            c = Compte.objects.get(pk=u.pk)
            for f in comptes.COMMUNS:
                self.assertEqual(getattr(c, f), getattr(u, f), f)
        self.assertEqual(set(Compte.objects.filter(gestionnaire=True).values_list("username", flat=True)), {"ada"})
        self.assertEqual(AccesEspace.objects.filter(espace__code="principal").count(), Utilisateur.objects.count())
        self.assertFalse(AccesEspace.objects.get(compte_id=40).actif)
        self.assertEqual(SV.comptes(), avant)  # aucune table de l'outil ne bouge

    def test_idempotent(self):
        anciens_comptes()
        comptes.amorcer()
        etat = sorted(Compte.objects.values_list("pk", "email", "password", "gestionnaire"))
        ident = Installation.objects.get().identifiant
        comptes.amorcer()
        self.assertEqual(sorted(Compte.objects.values_list("pk", "email", "password", "gestionnaire")), etat)
        self.assertEqual(Installation.objects.get().identifiant, ident)
        self.assertEqual(MarqueEspace.objects.count(), 1)

    def test_numeros_suivants_au_dessus(self):
        anciens_comptes()
        comptes.amorcer()
        c = Compte.objects.create(username="neuf", email="neuf@exemple.example", password="x")
        self.assertGreater(c.pk, 40)

    def test_registre_perdu_reprend_l_identifiant_de_la_base(self):
        anciens_comptes()
        comptes.amorcer()
        ident = Installation.objects.get().identifiant
        Installation.objects.all().delete()
        Compte.objects.all().delete()
        comptes.amorcer()
        self.assertEqual(Installation.objects.get().identifiant, ident)
        self.assertEqual(Compte.objects.count(), 3)

    def test_marque_d_une_autre_installation_refusee(self):
        MarqueEspace.objects.create(code="principal", installation="autre")
        Installation.objects.create(identifiant="celle-ci")
        with self.assertRaises(comptes.ConflitInstallation):
            comptes.amorcer()

    def test_reconciliation_sans_fusion_silencieuse(self):
        anciens_comptes()
        comptes.amorcer()
        Compte.objects.filter(pk=12).update(email="autre@exemple.example")  # numéro au registre pour une autre personne
        Compte.objects.filter(pk=5).update(first_name="Adèle")  # champ commun changé dans le registre
        with self.assertLogs("reporting.espaces", "ERROR"):
            conflits = comptes.reconcilier()
        self.assertEqual([c[1] for c in conflits], [12])
        self.assertFalse(Utilisateur.objects.get(pk=12).is_active)
        self.assertEqual(Utilisateur.objects.get(pk=5).first_name, "Adèle")

    def test_sauvegarde_d_un_espace_sans_le_registre(self):
        labels = {m._meta.label_lower for m in SV.modeles_sauvegardes()}
        self.assertIn("referentiel.utilisateur", labels)
        self.assertIn("espaces.marqueespace", labels)
        for commun in ("espaces.compte", "espaces.espace", "espaces.accesespace", "espaces.installation", "sessions.session"):
            self.assertNotIn(commun, labels)


class SauvegardeAvantMiseAJourTests(TestCase):
    """PostgreSQL : la sauvegarde automatique faite au démarrage, avant les migrations, suit les tables et colonnes qui
    existent vraiment (migrations déjà appliquées) ; sinon la nouvelle table des espaces la faisait échouer et l'outil
    ne démarrait plus."""

    def etat_sans_les_espaces(self):
        from django.db import connection as principale
        from django.db.migrations.loader import MigrationLoader

        loader = MigrationLoader(principale)
        noeuds = [n for n in loader.applied_migrations if n[0] != "espaces"]
        return loader.project_state(noeuds, at_end=True).apps

    def test_modeles_selon_les_migrations_appliquees(self):
        labels = {m._meta.label_lower for m in SV.modeles_sauvegardes(self.etat_sans_les_espaces())}
        self.assertNotIn("espaces.marqueespace", labels)
        self.assertIn("referentiel.kpi", labels)
        self.assertIn("referentiel.utilisateur", labels)

    def test_base_a_jour_modeles_du_code(self):
        self.assertIsNone(SV.modeles_de_la_base())

    def test_export_lisible_par_loaddata(self):
        import io
        import json
        from unittest import mock

        Utilisateur.objects.create(username="ada", email="ada@exemple.example", role="admin")
        sortie = io.StringIO()
        with mock.patch.object(SV, "modeles_de_la_base", return_value=self.etat_sans_les_espaces()):
            SV.exporter_json(sortie)
        objets = json.loads(sortie.getvalue())
        modeles = {o["model"] for o in objets}
        self.assertIn("referentiel.utilisateur", modeles)
        self.assertNotIn("espaces.marqueespace", modeles)
        from django.core import serializers

        self.assertEqual(len(list(serializers.deserialize("json", sortie.getvalue()))), len(objets))
