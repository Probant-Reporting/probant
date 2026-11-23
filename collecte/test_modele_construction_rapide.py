"""Fichier à remplir et exports Excel construits plus vite : le fichier produit est le même, partie
par partie et octet par octet (onglets, styles, textes, commentaires ; seules les dates du document changent), que
celui de l'ancienne construction (``aides_tests/fichier_a_remplir_avant.py``), sur la démo avec une campagne ouverte :
chaque rôle qui saisit, un onglet par organisation, tous les référentiels en cours, fichier vierge, trois langues ;
puis les exports fournis qui écrivent un tableau (base de données, tableau, cases restant à saisir, revue)."""
import datetime
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from referentiel.models import Utilisateur
from referentiel.plans import Plan

from . import exports as E
from . import fichiers as X
from . import imports_modele as I
from .aides_tests import fichier_a_remplir_avant as AVANT
from .aides_tests.classeurs import differences
from .models import Campagne, ReglageExport

FIGE = datetime.datetime(2026, 11, 13, 21, 0, tzinfo=datetime.timezone.utc)  # « généré le » identique dans les deux fichiers


def octets(reponse):
    return b"".join(reponse.streaming_content) if getattr(reponse, "streaming", False) else reponse.content


class FichierARemplirIdentique(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("load_demo", "--language", "fr", stdout=StringIO())  # Exemplia : exercice 2026 ouvert
        cls.campagne = Campagne.objects.filter(statut=Campagne.Statut.OUVERTE).order_by("pk").first()

    def comparer(self, utilisateur, langue="fr", par_organisation=False, vierge=False, tous=False):
        u = Utilisateur.objects.get(username=utilisateur)
        c = Campagne.objects.get(pk=self.campagne.pk)
        if tous:
            lignes = I.lignes_modele_en_cours(u)
        else:
            lignes = [] if vierge else I.lignes_modele(u, c, plan=Plan(c.referentiel))
        with mock.patch("django.utils.timezone.now", return_value=FIGE):
            avant = octets(AVANT.ancien_modele(u, c, lignes, par_organisation=par_organisation, langue=langue))
            apres = octets(I.modele(u, c, lignes, par_organisation=par_organisation, langue=langue))
        self.assertEqual(differences(avant, apres), [])
        return lignes

    def test_meme_fichier_pour_chaque_role_et_chaque_langue(self):
        for u in ("admin", "validateur", "contributeur"):
            for langue in ("fr", "en", "es"):
                with self.subTest(utilisateur=u, langue=langue):
                    self.assertTrue(self.comparer(u, langue))

    def test_meme_fichier_par_organisation_tous_referentiels_et_vierge(self):
        self.comparer("admin", par_organisation=True)
        self.comparer("admin", tous=True)
        self.comparer("contributeur", tous=True)
        self.comparer("admin", vierge=True)

    def test_memes_exports_fournis(self):
        """Exports qui écrivent un tableau (``fichiers.ecrire_tableau``) : même fichier qu'avec l'ancienne écriture."""
        E.creer_modeles_fournis()
        self.client.force_login(Utilisateur.objects.get(username="admin"))
        for code in ("powerbi", "tableau", "manquantes", "revue"):
            m = ReglageExport.objects.get(nom=E.PRESETS[code][0])
            url = f"/import-export/exporter/?modele={m.pk}&telecharger=1"
            with self.subTest(export=code), mock.patch("django.utils.timezone.now", return_value=FIGE):
                with mock.patch.object(X, "ecrire_tableau", AVANT.ecrire_tableau):
                    avant = octets(self.client.get(url, secure=True))
                apres = octets(self.client.get(url, secure=True))
                self.assertTrue(avant.startswith(b"PK"))
                self.assertEqual(differences(avant, apres), [])

    def test_fichier_date_du_moment(self):
        """Garde-fou du test : sans la date figée, le fichier dit bien quand il a été produit."""
        self.assertNotEqual(timezone.now(), FIGE)
