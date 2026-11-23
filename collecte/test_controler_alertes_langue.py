"""Chacun lit le texte d'une alerte dans sa langue, et la langue de la personne qui lance un
contrôle ou un recalcul ne change rien à l'alerte enregistrée.
- Une alerte « calcul impossible » est recomposée dans la langue du lecteur (avant : le texte du recalcul, dans la langue
  de qui l'avait lancé) ; son empreinte ne dépend plus de la langue : une alerte ignorée n'est plus rouverte par un
  recalcul lancé dans une autre langue.
- Un contrôle lancé dans une autre langue ne réécrit pas une alerte inchangée (date de mise à jour gardée)."""
from decimal import Decimal

from parametres import langues as L
from referentiel.models import KPI, Niveau

from . import calcul
from . import coherence as CO
from .aides_tests.saisie import Base
from .models import Alerte, Reponse


class AlertesLangueTests(Base):
    def setUp(self):
        super().setUp()
        self.ratio = KPI.objects.create(code="RAT", libelle="Ratio", type_saisie_id="Calculé", formule="[EFF] / [TX]",
                                        granularite_id=Niveau.ENTITY, methode_agregation="Aucune")
        from referentiel.models import ElementReferentiel

        for k in (self.eff, self.taux, self.ratio):
            ElementReferentiel.objects.get_or_create(referentiel=self.c.referentiel, kpi=k)
        Reponse.objects.update_or_create(periode=self.c.periode, kpi=self.eff, organisation=self.e1,
                                         defaults={"valeur": Decimal(10), "statut": "brouillon"})
        Reponse.objects.update_or_create(periode=self.c.periode, kpi=self.taux, organisation=self.e1,
                                         defaults={"valeur": Decimal(0), "statut": "brouillon"})

    def recalculer_et_controler(self, langue):
        with L.activer_interface(langue):
            calcul.recalculer(self.c)
            CO.controler(self.c)

    def alerte_calcul(self):
        return Alerte.objects.get(campagne=self.c, kpi=self.ratio, organisation=self.e1, controle=Alerte.Controle.CALCUL)

    def test_calcul_impossible_ignore_reste_ignore_apres_un_recalcul_dans_une_autre_langue(self):
        self.recalculer_et_controler("fr")
        a = self.alerte_calcul()
        CO.traiter(self.admin, a, "ignorer")
        self.recalculer_et_controler("en")
        self.assertEqual(self.alerte_calcul().statut, Alerte.Statut.IGNOREE)
        self.recalculer_et_controler("de")
        self.assertEqual(self.alerte_calcul().statut, Alerte.Statut.IGNOREE)

    def test_calcul_impossible_lu_dans_la_langue_du_lecteur(self):
        self.recalculer_et_controler("de")
        a = self.alerte_calcul()
        with L.activer_interface("fr"):
            fr = CO.constat_lisible(a)
        with L.activer_interface("en"):
            en = CO.constat_lisible(a)
        self.assertIn("zéro", fr.lower())
        self.assertIn("zero", en.lower())
        self.assertNotEqual(fr, en)

    def test_controle_dans_une_autre_langue_ne_reecrit_pas_une_alerte_inchangee(self):
        # valeur négative à séparateur de milliers : son texte brut dépendait de la langue de qui lançait le contrôle
        Reponse.objects.update_or_create(periode=self.c.periode, kpi=self.eff, organisation=self.e2,
                                         defaults={"valeur": Decimal(-12345), "statut": "brouillon"})
        self.recalculer_et_controler("fr")
        self.assertTrue(Alerte.objects.filter(campagne=self.c, kpi=self.eff, organisation=self.e2).exists())
        avant = {a.pk: (a.date_maj, a.message, a.valeur, a.reference) for a in Alerte.objects.filter(campagne=self.c)}
        self.assertTrue(avant)
        for langue in ("en", "de", "es"):
            with L.activer_interface(langue):
                CO.controler(self.c)
        apres = {a.pk: (a.date_maj, a.message, a.valeur, a.reference) for a in Alerte.objects.filter(campagne=self.c)}
        self.assertEqual(apres, avant)


class MigrationAlertesCalculTests(AlertesLangueTests):
    """Migration collecte/0040 : alertes « calcul impossible » d'avant (empreinte = texte du motif, sans clés) converties ;
    statut, justification, texte et date de mise à jour ne bougent pas ; le contrôle suivant ne les rouvre pas."""

    def ancienne(self):
        self.recalculer_et_controler("fr")
        a = self.alerte_calcul()
        Alerte.objects.filter(pk=a.pk).update(textes={}, empreinte=a.message, statut=Alerte.Statut.IGNOREE,
                                              justification="Formule en cours de revue")  # état d'une installation 1.2
        return Alerte.objects.get(pk=a.pk)

    def convertir(self):
        import importlib

        from django.apps import apps

        importlib.import_module("collecte.migrations.0040_alertes_calcul_recomposables").convertir(apps, None)

    def test_conversion_sans_perte_puis_aucune_reouverture(self):
        a = self.ancienne()
        self.convertir()
        b = Alerte.objects.get(pk=a.pk)
        self.assertEqual((b.statut, b.justification, b.message, b.date_maj), (a.statut, a.justification, a.message, a.date_maj))
        self.assertTrue(b.empreinte.startswith("calc:"))
        self.assertEqual(b.textes["message"]["cle"], "messages.calcul.erreur")
        self.recalculer_et_controler("en")
        self.assertEqual(self.alerte_calcul().statut, Alerte.Statut.IGNOREE)
        self.convertir()  # deux fois : rien de plus
        self.assertEqual(Alerte.objects.get(pk=a.pk).empreinte, b.empreinte)

    def test_sans_la_conversion_le_controle_rouvrirait(self):
        self.ancienne()
        CO.controler(self.c)
        self.assertEqual(self.alerte_calcul().statut, Alerte.Statut.OUVERTE)  # d'où la migration
    test_calcul_impossible_ignore_reste_ignore_apres_un_recalcul_dans_une_autre_langue = None
    test_calcul_impossible_lu_dans_la_langue_du_lecteur = None
    test_controle_dans_une_autre_langue_ne_reecrit_pas_une_alerte_inchangee = None
