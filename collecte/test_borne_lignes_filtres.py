"""Garde-fou du nombre de lignes d'un export Excel (``exports._borne_lignes``) : un filtre par thème, par référentiel, ou
sans les KPI calculés ne s'exprime pas en SQL ; la borne SQL n'est alors pas utilisée (0), pour ne jamais refuser à tort
un export filtré qui tient dans la feuille. Le contrôle sur les lignes réellement collectées reste fait après."""
from unittest import mock

from referentiel.models import ElementReferentiel, Theme

from . import exports as E
from .aides_tests.vitesse import Base


class BorneLignesFiltresTests(Base):
    def setUp(self):
        super().setUp()
        self.admin.is_superuser = True
        self.admin.save()
        self.ajouter_kpis(3)  # 3 KPI x 4 entités x 2 périodes : 24 réponses
        ref = self.c.referentiel
        self.theme = Theme.objects.create(referentiel=ref, code="T0", nom="Thème du seul K0")
        autre = Theme.objects.create(referentiel=ref, code="T1", nom="Autres KPI")
        for i, k in enumerate(self.kpis):
            ElementReferentiel.objects.update_or_create(referentiel=ref, kpi=k,
                                                        defaults={"theme": self.theme if i == 0 else autre, "ordre": i})

    def parametres(self, **kw):
        return E.Parametres(exercices=["2025", "2026"], presentation="base", **kw)

    def test_pas_de_borne_sql_avec_un_filtre_non_exprimable(self):
        self.assertEqual(E._borne_lignes(self.admin, self.parametres()), 24)  # témoin : sans filtre, la borne compte
        for kw in ({"themes": [str(self.theme.pk)]}, {"referentiel": self.c.referentiel_id},
                   {"contenus": ["valide", "brouillon"]}):
            with self.subTest(**kw):
                self.assertEqual(E._borne_lignes(self.admin, self.parametres(**kw)), 0)

    def test_export_filtre_par_theme_pres_de_la_limite_accepte(self):
        """24 réponses dans la base, 8 dans le thème exporté : 8 + 10 lignes d'en-tête tiennent dans 30 ; la borne des 24
        réponses (34 lignes) refuserait l'export à tort."""
        p = self.parametres(themes=[str(self.theme.pk)])
        self.assertEqual(len(E.collecter(self.admin, p)), 8)
        with mock.patch.object(E, "MAX_LIGNES_EXCEL", 30), mock.patch.object(E, "LIGNES_ENTETE_EXCEL", 10):
            E._exporter(self.admin, p)  # pas d'ExportTropGros
            with self.assertRaises(E.ExportTropGros):  # témoin : sans le filtre, l'export est bien refusé
                E._exporter(self.admin, self.parametres())
