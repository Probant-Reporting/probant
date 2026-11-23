"""KPI pas demandé dans la période d'une campagne (« demandé depuis » plus tard, ou hors du périmètre noté à la clôture) :
la case, ouverte par son adresse directe, dit la vraie raison (comme une organisation pas encore ouverte) au lieu de
la page 403 générique. Un administrateur reçoit un lien vers le contenu du référentiel. Panneau, pleine page, import.

Données inventées uniquement."""
from django.core.exceptions import PermissionDenied
from django.urls import reverse

from referentiel.models import KPI, Attribution, ElementReferentiel, Utilisateur

from . import imports as I
from . import saisie as S
from .outils_tests import xlsx
from .test_demande_depuis_perimetre import J26, Base


class KpiPasDemandeTests(Base):
    def setUp(self):
        super().setUp()
        self.nouveau()  # ajouté après la clôture de 2025 : demandé depuis 2026 seulement
        ElementReferentiel(referentiel=self.ref, kpi_id="NEW", ordre=9).save()
        self.new = KPI.objects.get(pk="NEW")
        self.contrib = Utilisateur.objects.create(username="contrib", email="c@exemple.test")
        Attribution.objects.create(kpi=self.new, organisation=self.e1, utilisateur=self.contrib)
        self.assertEqual(self.element().demande_depuis, J26)

    def test_droits_disent_la_vraie_raison_avec_le_lien_pour_l_administrateur(self):
        d = S.droits(self.admin, self.camp(2025), self.new, self.e1)
        self.assertTrue(d.voir)
        self.assertFalse(d.modifier)
        self.assertIn("2026", d.motif)  # « demandé depuis 2026 »
        self.assertNotIn("référentiel de cette campagne", d.motif)
        self.assertEqual(d.lien, reverse("parametres:referentiel_contenu", args=[self.ref.code]))
        with self.assertRaises(PermissionDenied):
            S.enregistrer(self.admin, self.camp(2025), self.new, self.e1, "5", False, "")

    def test_contributeur_sans_lien(self):
        d = S.droits(self.contrib, self.camp(2025), self.new, self.e1)
        self.assertTrue(d.voir)
        self.assertEqual(d.lien, "")
        self.assertIn("2026", d.motif)

    def test_sans_date_hors_du_perimetre_note(self):
        ElementReferentiel.objects.filter(referentiel=self.ref, kpi_id="NEW").update(demande_depuis=None)
        d = S.droits(self.admin, self.camp(2025), self.new, self.e1)
        self.assertTrue(d.voir)
        self.assertNotIn("2026", d.motif)
        self.assertNotEqual(d.motif, "")
        self.assertTrue(d.lien)

    def test_hors_referentiel_ne_change_pas_et_sans_role_rien(self):
        KPI.objects.create(code="LIB", libelle="Libre", type_saisie_id="Saisi", granularite_id=self.new.granularite_id)
        d = S.droits(self.admin, self.camp(2025), KPI.objects.get(pk="LIB"), self.e1)
        self.assertFalse(d.voir)
        autre = Utilisateur.objects.create(username="autre", email="a@exemple.test")
        self.assertFalse(S.droits(autre, self.camp(2025), self.new, self.e1).voir)  # pas attribué : rien à voir

    def test_page_directe_et_panneau(self):
        self.client.force_login(self.admin)
        url = reverse("collecte:cellule", args=[self.camp(2025).pk, "NEW", self.e1.pk])
        rep = self.client.get(url)
        self.assertEqual(rep.status_code, 200)
        self.assertContains(rep, reverse("parametres:referentiel_contenu", args=[self.ref.code]))
        self.assertNotContains(rep, " data-auto")  # rien à enregistrer ici
        rep = self.client.get(url, HTTP_X_REQUESTED_WITH="fetch")
        self.assertEqual(rep.status_code, 200)

    def test_import_motif_dans_l_apercu(self):
        a = I.analyser(self.admin, xlsx([["ID KPI", "Organisation", "Exercice", "Valeur"], ["NEW", "E1", 2025, 5]]),
                       campagne_defaut=self.camp(2025).pk)
        l = a.lignes[0]
        self.assertNotIn(l.action, ("creer", "modifier"))
        self.assertIn("2026", l.motif)
