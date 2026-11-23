"""Organisation désactivée qui n'est pas ouverte pendant la période (sans date de désactivation, ou désactivée avant le
début de la période) : aucune écriture, par aucune porte. Avant, ``organisation_pas_ouverte``
ne refusait que la date d'ouverture : l'import, le serveur MCP et la case ouverte par son adresse enregistraient une
valeur qui ne comptait dans aucun total (``calcul.ouverte`` la dit fermée) et que la Saisie ne listait pas. Même règle
que pour une organisation pas encore ouverte : motif, et lien vers la fiche pour un administrateur. Désactivée pendant
la période : ouverte, rien ne change.

Données inventées uniquement."""
import datetime

from django.core.exceptions import PermissionDenied
from django.urls import reverse

from referentiel.models import Organisation

from . import calcul as C
from . import imports as I
from . import saisie as S
from .aides_tests.echanges import Base
from .models import Campagne, Reponse
from .outils_tests import xlsx

ENTETES = ["ID KPI", "Organisation", "Exercice", "Valeur", "Commentaire"]


class OrganisationDesactiveeTests(Base):
    def desactiver(self, date=None):
        Organisation.objects.filter(pk=self.e2.pk).update(actif=False, date_desactivation=date)
        self.c = Campagne.objects.get(pk=self.c.pk)  # objet relu (l'arbre est lu une fois par objet campagne)
        self.e2 = Organisation.objects.get(pk=self.e2.pk)

    def test_sans_date_refusee_partout(self):
        self.desactiver()
        self.assertFalse(C.ouverte(self.e2, self.c.periode))  # elle ne compte dans aucun total
        d = S.droits(self.admin, self.c, self.eff, self.e2)
        self.assertTrue(d.voir)
        self.assertFalse(d.modifier)
        self.assertIn("E2", d.motif)
        self.assertEqual(d.lien, reverse("collecte:admin_organisation", args=[self.e2.pk]))
        with self.assertRaises(PermissionDenied):
            S.enregistrer(self.admin, self.c, self.eff, self.e2, "41", False, "")
        self.assertEqual(Reponse.objects.get(periode=self.c.periode, kpi=self.eff, organisation=self.e2).valeur, 40)
        self.client.force_login(self.admin)
        page = self.client.get(reverse("collecte:cellule", args=[self.c.pk, "EFF", self.e2.pk])).content.decode()
        self.assertIn(reverse("collecte:admin_organisation", args=[self.e2.pk]), page)
        a = I.analyser(self.admin, xlsx([ENTETES, ["EFF", "E2", 2026, 41, ""]]), campagne_defaut=self.c.pk)
        self.assertNotIn(a.lignes[0].action, ("creer", "modifier"))
        self.assertIn("E2", a.lignes[0].motif)

    def test_contributeur_refuse_motif_sans_lien(self):
        from referentiel.models import Attribution

        Attribution.objects.create(kpi=self.eff, organisation=self.e2, utilisateur=self.contrib)
        self.desactiver()
        d = S.droits(self.contrib, self.c, self.eff, self.e2)
        self.assertFalse(d.modifier)  # déjà refusé avant (« pas dans votre périmètre ») : rien ne change pour lui
        self.assertEqual(d.lien, "")
        self.assertIn("administra", S.organisation_pas_ouverte(self.contrib, self.c, self.e2)[0])

    def test_desactivee_avant_la_periode_refusee(self):
        self.desactiver(datetime.date(2025, 6, 30))
        self.assertFalse(S.droits(self.admin, self.c, self.eff, self.e2).modifier)

    def test_desactivee_pendant_la_periode_rien_ne_change(self):
        self.desactiver(datetime.date(2026, 6, 30))
        self.assertTrue(C.ouverte(self.e2, self.c.periode))
        self.assertTrue(S.droits(self.admin, self.c, self.eff, self.e2).modifier)
        S.enregistrer(self.admin, self.c, self.eff, self.e2, "41", False, "")
