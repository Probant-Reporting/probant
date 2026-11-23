"""Cumul de l'année depuis les mois (``Calculateur._cumul``) × organisation ouverte pendant une partie de l'année.

README (« a closed site counts in the years when it was open », « a site counts only from its opening date ») : le cumul
ne porte que sur les mois où l'organisation est ouverte (dans l'arbre de chaque mois). Avant, l'année d'un site fermé
le 30/06 restait « Incomplet : juillet… » et disparaissait du total du pays (24 au lieu de 30) ; celle d'un site ouvert
le 15/03 restait « Incomplet : janvier, février » pour toujours, et avec elle le pays et le groupe . Données inventées."""
import datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from referentiel.composition import composer
from referentiel.models import KPI, Frequence, Niveau, Organisation, Referentiel, Utilisateur

from . import calcul as C
from . import periodes as P
from . import saisie as S
from .models import Campagne, Reponse

D = Decimal
FIN = timezone.localdate() + datetime.timedelta(days=30)


def rep(periode, kpi, org, v):
    Reponse.objects.update_or_create(periode=periode, kpi_id=kpi, organisation=org,
                                     defaults=dict(valeur=D(v), statut=Reponse.Statut.VALIDE, origine=Reponse.Origine.SAISIE))


def lue(periode, kpi, org):
    r = Reponse.objects.filter(periode=periode, kpi_id=kpi, organisation=org).first()
    return None if r is None else (r.valeur, r.statut)


class CumulMoisOuvertsTests(TestCase):
    def setUp(self):
        self.admin = Utilisateur.objects.create(username="admin", email="a@exemple.test", role=Utilisateur.Role.ADMIN)
        self.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.p = Organisation.objects.create(nom="Pays", niveau_id=Niveau.COUNTRY, parent=self.g)
        self.e1 = Organisation.objects.create(nom="E1", niveau_id=Niveau.ENTITY, parent=self.p)
        self.e2 = Organisation.objects.create(nom="E2", niveau_id=Niveau.ENTITY, parent=self.p)
        KPI.objects.create(code="X", libelle="X", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY, methode_agregation="Somme")
        self.mens = Referentiel.objects.create(code="M", nom="Mensuel", ordre=1, frequence=Frequence.MOIS)
        composer({"X": ["S"]}, self.mens)

    def annee(self, e4, mois_e4):
        """Douze mois saisis (1 par mois) pour E1 et E2, ``mois_e4`` pour E4 ; puis les recalculs ; renvoie l'année."""
        cs = []
        for m in range(1, 13):
            cm, _ = P.campagne(self.mens, datetime.date(2025, m, 1), statut=Campagne.Statut.OUVERTE, date_fin_saisie=FIN)
            cs.append(cm)
            for o in (self.e1, self.e2):
                rep(cm.periode, "X", o, 1)
            if m in mois_e4:
                rep(cm.periode, "X", e4, 1)
        for cm in cs:
            C.recalculer(cm)
        return cs, P.obtenir(Frequence.ANNEE, datetime.date(2025, 1, 1), 1)

    def test_site_ferme_le_30_juin_compte_pour_ses_six_mois(self):
        e4 = Organisation.objects.create(nom="E4", niveau_id=Niveau.ENTITY, parent=self.p, actif=False,
                                         date_desactivation=datetime.date(2025, 6, 30))
        _, an = self.annee(e4, range(1, 7))
        C.recalculer(an)
        self.assertEqual(lue(an, "X", e4), (D(6), Reponse.Statut.CALCULE))  # avant : (None, incomplet)
        self.assertEqual(lue(an, "X", self.p), (D(30), Reponse.Statut.CALCULE))  # avant : 24, E4 perdu en silence
        self.assertEqual(lue(an, "X", self.g), (D(30), Reponse.Statut.CALCULE))
        # un mois manquant pendant qu'il était ouvert rend toujours son année incomplète
        Reponse.objects.filter(periode__debut=datetime.date(2025, 3, 1), periode__type=Frequence.MOIS, kpi_id="X",
                               organisation=e4).delete()
        C.recalculer(an)
        self.assertEqual(lue(an, "X", e4)[1], Reponse.Statut.INCOMPLET)
        self.assertIn("2025", Reponse.objects.get(periode=an, kpi_id="X", organisation=e4).message_calcul)

    def test_site_ouvert_le_15_mars_compte_de_mars_a_decembre(self):
        e4 = Organisation.objects.create(nom="E4", niveau_id=Niveau.ENTITY, parent=self.p, date_ouverture=datetime.date(2025, 3, 15))
        cs, an = self.annee(e4, range(3, 13))
        # ses cases de janvier et février ne sont pas proposées, et le taux de remplissage des mois est complet
        self.assertFalse(any(o.id == e4.id for _, o in S.cellules(self.admin, campagne=cs[0])))
        C.recalculer(an)
        self.assertEqual(lue(an, "X", e4), (D(10), Reponse.Statut.CALCULE))  # avant : « Incomplet : janvier, février »
        self.assertEqual(lue(an, "X", self.p), (D(34), Reponse.Statut.CALCULE))  # avant : incomplet (E4)
        self.assertEqual(lue(an, "X", self.g), (D(34), Reponse.Statut.CALCULE))

    def test_le_calcul_a_la_lecture_donne_la_meme_valeur(self):
        """``Calculateur.valeur`` (pages, Visualisation) : même règle que ce qui est enregistré."""
        e4 = Organisation.objects.create(nom="E4", niveau_id=Niveau.ENTITY, parent=self.p, actif=False,
                                         date_desactivation=datetime.date(2025, 6, 30))
        _, an = self.annee(e4, range(1, 7))
        calc = C.Calculateur(an)
        self.assertEqual(calc.valeur("X", e4.id), D(6))
        self.assertEqual(calc.valeur("X", self.p.id), D(30))

    def test_saisie_d_un_mois_refait_l_annee(self):
        """Recalcul ciblé après une saisie dans un mois : l'année du site fermé et ses totaux suivent."""
        e4 = Organisation.objects.create(nom="E4", niveau_id=Niveau.ENTITY, parent=self.p, actif=False,
                                         date_desactivation=datetime.date(2025, 6, 30))
        cs, an = self.annee(e4, range(1, 7))
        C.recalculer(an)
        rep(cs[1].periode, "X", e4, 5)
        C.recalculer(cs[1], ["X"], organisations=[e4.id])
        self.assertEqual(lue(an, "X", e4), (D(10), Reponse.Statut.CALCULE))
        self.assertEqual(lue(an, "X", self.p), (D(34), Reponse.Statut.CALCULE))

    def test_site_ferme_avec_un_mois_manquant_rend_le_pays_incomplet(self):
        """README (« everything counts ») : une organisation fermée pendant la période qui y a des valeurs
        rend le total incomplet s'il lui manque une valeur. Ses valeurs des mois de l'année cumulée en sont : avant, son
        année incomplète était écartée du total du pays sans un mot (24, comme si elle n'avait rien saisi)."""
        e4 = Organisation.objects.create(nom="E4", niveau_id=Niveau.ENTITY, parent=self.p, actif=False,
                                         date_desactivation=datetime.date(2025, 6, 30))
        _, an = self.annee(e4, range(1, 6))  # juin manque
        C.recalculer(an)
        self.assertEqual(lue(an, "X", e4)[1], Reponse.Statut.INCOMPLET)
        self.assertEqual(lue(an, "X", self.p), (None, Reponse.Statut.INCOMPLET))
        self.assertIn("E4", Reponse.objects.get(periode=an, kpi_id="X", organisation=self.p).message_calcul)
        # sans aucune valeur dans les mois : toujours écartée (fermée avant d'avoir rien saisi)
        Reponse.objects.filter(organisation=e4).delete()
        C.recalculer(an)
        self.assertEqual(lue(an, "X", self.p), (D(24), Reponse.Statut.CALCULE))

    def test_mise_a_jour_recalcule_les_exercices_ouverts_jamais_les_clos(self):
        """Installation existante (``collecte/0045``) : la fin de « migrate » recalcule les campagnes non clôturées (le
        site fermé y retrouve ses six mois) ; un exercice clos garde ses chiffres publiés, même calculés avec l'ancienne
        règle."""
        from importlib import import_module

        from django.apps import apps as django_apps

        from referentiel.models import TravailApresMiseAJour

        from .mise_a_jour import MOTIFS_EN, faire_les_travaux

        e4 = Organisation.objects.create(nom="E4", niveau_id=Niveau.ENTITY, parent=self.p, actif=False,
                                         date_desactivation=datetime.date(2024, 6, 30))
        for annee, statut in ((2024, Campagne.Statut.CLOTUREE), (2025, Campagne.Statut.OUVERTE)):
            if annee == 2025:
                Organisation.objects.filter(pk=e4.pk).update(date_desactivation=datetime.date(2025, 6, 30))
            for m in range(1, 13):
                cm, _ = P.campagne(self.mens, datetime.date(annee, m, 1), statut=statut, date_fin_saisie=FIN)
                for o in (self.e1, self.e2) + ((e4,) if m <= 6 else ()):
                    rep(cm.periode, "X", o, 1)
            an = P.obtenir(Frequence.ANNEE, datetime.date(annee, 1, 1), 1)
            # cases de l'année telles que l'ancienne règle les a écrites
            for o, v, st in ((e4, None, Reponse.Statut.INCOMPLET), (self.p, D(24), Reponse.Statut.CALCULE)):
                Reponse.objects.create(periode=an, kpi_id="X", organisation=o, valeur=v, statut=st,
                                       origine=Reponse.Origine.CUMUL if o == e4 else Reponse.Origine.AGREGATION)
        clos = P.obtenir(Frequence.ANNEE, datetime.date(2024, 1, 1), 1)
        avant = sorted(Reponse.objects.filter(periode=clos).values_list("kpi_id", "organisation_id", "valeur", "statut"))
        import_module("collecte.migrations.0045_recalcul_cumuls_mois_ouverts").poser_recalcul(django_apps, None)
        self.assertIn(TravailApresMiseAJour.objects.get(code="recalcul").motif, MOTIFS_EN)  # message anglais pour l'IT
        self.assertEqual(faire_les_travaux(), ["recalcul"])
        ouvert = P.obtenir(Frequence.ANNEE, datetime.date(2025, 1, 1), 1)
        self.assertEqual(lue(ouvert, "X", e4), (D(6), Reponse.Statut.CALCULE))
        self.assertEqual(lue(ouvert, "X", self.p), (D(30), Reponse.Statut.CALCULE))
        self.assertEqual(sorted(Reponse.objects.filter(periode=clos).values_list("kpi_id", "organisation_id", "valeur",
                                                                                 "statut")), avant)
