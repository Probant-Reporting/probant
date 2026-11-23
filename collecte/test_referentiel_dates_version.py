"""Dates de la version d'un référentiel (règle du projet) : date du contenu de la version (bibliothèque,
fichier importé, ou posée quand la version change dans Réglages) et date de la dernière installation ou mise à jour ;
fichiers JSON et Excel, reprise par la migration referentiel/0018, pages, contrôle de la bibliothèque."""
import copy
import datetime
import importlib
import io
import json
import tempfile
from pathlib import Path
from unittest import mock

from django.apps import apps
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from referentiel.bibliotheque import controle as C
from referentiel.bibliotheque import socles as S
from referentiel.bibliotheque.socles_retires import SOCLES_RETIRES
from referentiel.models import Referentiel, Utilisateur

from . import paquets as P
from .aides_tests.paquets import vider
from .models import Journal
from .aides_tests.bibliotheque_essai import BibliothequeEssai, dossier

DATE_SOCLES = datetime.date(2026, 11, 12)


def installer(paquet, fourni=True):
    a = P.analyser(paquet, source="essai", fourni=fourni)
    assert a.erreur == "", a.erreur
    return P.appliquer(None, a)


class DatesInstallationTests(BibliothequeEssai, TestCase):
    def test_installation_puis_nouvelle_version(self):
        vider()
        avant = timezone.now()
        p = P.fourni("socle_ges.json").paquet
        self.assertEqual(p.date_version, DATE_SOCLES)
        installer(p)
        ref = Referentiel.objects.get(code="SOCLE_GES")
        self.assertEqual(ref.date_version, DATE_SOCLES)
        self.assertGreaterEqual(ref.mis_a_jour_le, avant)
        self.assertTrue(P.analyser(p, fourni=True).aucune_difference)  # même version, même date : rien à mettre à jour
        # nouvelle version du modèle, datée
        p2 = copy.deepcopy(p)
        p2.referentiel.update(version="1.1", date_version="2026-12-01")
        a = P.analyser(p2, fourni=True)
        self.assertIn(("Date de la version", "2026-11-12", "2026-12-01"), a.referentiel_differences)
        premiere = ref.mis_a_jour_le
        P.appliquer(None, a)
        ref.refresh_from_db()
        self.assertEqual((ref.version, ref.date_version), ("1.1", datetime.date(2026, 12, 1)))
        self.assertGreater(ref.mis_a_jour_le, premiere)
        self.assertTrue(Journal.objects.filter(objet_id="SOCLE_GES", champ="Date de la version", apres="2026-12-01").exists())

    def test_fichiers_json_et_excel(self):
        vider()
        installer(P.fourni("socle_social.json").paquet)
        ref = Referentiel.objects.get(code="SOCLE_SOCIAL")
        p = P.extraire(ref)
        self.assertEqual(p.referentiel["date_version"], "2026-11-12")
        self.assertEqual(P.depuis_json(P.vers_json(p)).date_version, DATE_SOCLES)
        flux = io.BytesIO()
        P.classeur(p).save(flux)
        flux.seek(0)
        flux.name = "social.xlsx"
        relu = P.lire(flux)
        self.assertEqual(relu.referentiel["date_version"], "2026-11-12")
        self.assertTrue(P.analyser(relu).aucune_difference)
        # fichier sans date : rien de changé ; date illisible dans un JSON : refusé avec le champ en cause
        ref.date_version = None
        ref.save()
        self.assertEqual(P.extraire(ref).referentiel["date_version"], "")
        d = json.loads(P.vers_json(p))
        d["referentiel"]["date_version"] = "12/11/2026"
        with self.assertRaisesMessage(P.PaquetInvalide, "date_version"):
            P.depuis_dict(d)


class DatesPagesTests(BibliothequeEssai, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = Utilisateur.objects.create_user("admin", "admin@exemple.test", "x", role=Utilisateur.Role.ADMIN)

    def setUp(self):
        self.client.force_login(self.admin)

    def reglages(self, ref, **champs):
        donnees = {"ref": ref.code, "action": "enregistrer", f"nom__{ref.code}": ref.nom, f"couleur__{ref.code}": ref.couleur,
                   f"frequence__{ref.code}": ref.frequence, f"mois_debut__{ref.code}": ref.mois_debut,
                   f"comparaison__{ref.code}": ref.comparaison, f"actif__{ref.code}": "on", f"version__{ref.code}": ref.version,
                   f"date_version__{ref.code}": ref.date_version.isoformat() if ref.date_version else ""}
        donnees.update({f"{k}__{ref.code}": v for k, v in champs.items()})
        self.client.post(reverse("parametres:referentiels"), donnees)
        ref.refresh_from_db()

    def test_pages_et_reglages(self):
        vider()
        installer(P.fourni("socle_energie.json").paquet)
        ref = Referentiel.objects.get(code="SOCLE_ENERGIE")
        html = self.client.get(reverse("parametres:referentiel_contenu", args=[ref.code])).content.decode()
        self.assertIn("version 1.0 du 12/11/2026", html)
        html = self.client.get(reverse("parametres:referentiel_partage", args=[ref.code])).content.decode()
        self.assertIn(f"Installé ou mis à jour le {timezone.localtime(ref.mis_a_jour_le):%d/%m/%Y}", html)
        html = self.client.get(reverse("parametres:referentiels")).content.decode()
        self.assertIn("Version 1.0 du 12/11/2026", html)
        # Réglages : nouvelle version sans date choisie → aujourd'hui ; date choisie → gardée ; même version → date gardée
        self.reglages(ref, version="1.1")
        self.assertEqual((ref.version, ref.date_version), ("1.1", timezone.localdate()))
        self.assertTrue(Journal.objects.filter(objet_id=ref.code, champ="date_version").exists())
        self.reglages(ref, version="1.2", date_version="2026-10-01")
        self.assertEqual((ref.version, ref.date_version), ("1.2", datetime.date(2026, 10, 1)))
        self.reglages(ref, nom="Énergie du groupe")
        self.assertEqual((ref.nom, ref.date_version), ("Énergie du groupe", datetime.date(2026, 10, 1)))
        self.reglages(ref, date_version="pas une date")
        self.assertEqual(ref.date_version, datetime.date(2026, 10, 1))


class MigrationRepriseTests(BibliothequeEssai, TestCase):
    """referentiel/0018 : date de la dernière installation reprise du journal ; date de la version reprise de la
    bibliothèque pour un modèle installé dans la même version. Un référentiel créé dans l'outil reste sans date."""

    def test_reprise(self):
        vider()
        migration = importlib.import_module("referentiel.migrations.0018_dates_version")
        installer(P.fourni("socle_ges.json").paquet)
        installer(P.fourni("socle_social.json").paquet)
        Referentiel.objects.filter(code__in=["SOCLE_GES", "SOCLE_SOCIAL"]).update(date_version=None, mis_a_jour_le=None)
        Referentiel.objects.filter(code="SOCLE_SOCIAL").update(version="0.9")  # version plus ancienne que la bibliothèque
        Referentiel.objects.create(code="MAISON", nom="Créé dans l'outil")
        Journal.objects.filter(objet_id="SOCLE_GES", action="import_paquet").update(date=datetime.datetime(2026, 11, 1, 9, tzinfo=datetime.UTC))
        with mock.patch.object(migration, "BIBLIOTHEQUE", dossier()):  # bibliothèque d'avant la mise à jour (socles compris)
            migration.reprendre(apps, None)
        ges, social, maison = (Referentiel.objects.get(code=c) for c in ("SOCLE_GES", "SOCLE_SOCIAL", "MAISON"))
        self.assertEqual((ges.date_version, ges.mis_a_jour_le), (DATE_SOCLES, datetime.datetime(2026, 11, 1, 9, tzinfo=datetime.UTC)))
        self.assertIsNone(social.date_version)
        self.assertIsNotNone(social.mis_a_jour_le)
        self.assertEqual((maison.date_version, maison.mis_a_jour_le), (None, None))

    def test_reprise_d_un_socle_retire(self):
        """Mise à jour depuis une version d'avant referentiel/0018 avec un socle retiré : la bibliothèque n'a
        plus son fichier, la date de la version reste vide (rien d'inventé), la date d'installation est reprise du journal."""
        vider()
        migration = importlib.import_module("referentiel.migrations.0018_dates_version")
        installer(P.fourni("socle_ges.json").paquet)
        Referentiel.objects.filter(code="SOCLE_GES").update(date_version=None, mis_a_jour_le=None)
        migration.reprendre(apps, None)  # bibliothèque du dépôt : la norme VS seulement
        ges = Referentiel.objects.get(code="SOCLE_GES")
        self.assertIsNone(ges.date_version)
        self.assertIsNotNone(ges.mis_a_jour_le)


class DatesControleTests(SimpleTestCase):
    def socle(self, **champs):
        return {**next(s for s in SOCLES_RETIRES if s["code"] == "SOCLE_ENERGIE"), **champs}

    def test_date_obligatoire_et_valide(self):
        for date, attendu in (("13/11/2026", "date de la version invalide"), ("2999-01-01", "date de la version dans le futur")):
            self.assertIn(attendu, " ".join(C.controler(self.socle(date=date)).erreurs))
        self.assertIn("date de la version invalide", " ".join(C.controler(self.socle(date="", module="x")).erreurs))

    def test_la_date_suit_la_version(self):
        with tempfile.TemporaryDirectory() as d:
            chemin = Path(d) / "socle_energie.json"
            chemin.write_text(P.vers_json(S.paquet(self.socle())), encoding="utf-8")
            r = C.Rapport("SOCLE_ENERGIE")
            C.controler_version(self.socle(version="1.1"), chemin, r)
            self.assertIn("nouvelle version 1.1 avec la date de la précédente", " ".join(r.erreurs))
            r = C.Rapport("SOCLE_ENERGIE")
            C.controler_version(self.socle(version="1.1", date="2026-11-13"), chemin, r)
            self.assertEqual((r.erreurs, r.avertissements), ([], []))
            r = C.Rapport("SOCLE_ENERGIE")
            C.controler_version(self.socle(couleur="#000000"), chemin, r)
            self.assertIn("contenu changé sans nouvelle version", " ".join(r.avertissements))
            r = C.Rapport("SOCLE_ENERGIE")
            C.controler_version(self.socle(date="2026-11-13"), chemin, r)
            self.assertIn("date changée sans nouvelle version", " ".join(r.avertissements))
