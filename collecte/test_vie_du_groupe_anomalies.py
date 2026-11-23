"""Anomalies trouvées par la vie d'un groupe fictif (``qa/group_life``) : un test minimal chacune.

Chaque test décrit le comportement attendu ; il échoue aujourd'hui, d'où ``expectedFailure`` (la suite reste verte).
Quand la correction arrive, le test passe : retirer ``expectedFailure`` et le code de l'anomalie de ``CONNUES``
(``collecte/test_vie_du_groupe.py``). Les anomalies marquées « règle » demandent d'abord une décision de produit : le test décrit la réponse proposée, pas une règle déjà écrite.
"""
import datetime
import io
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from collecte import exports as E
from collecte import imports as I
from collecte import periodes as P
from collecte.administration import changer_statut
from collecte.calcul import recalculer
from collecte.models import Campagne, Reponse
from collecte.test_periodes import Base as BaseMois
from referentiel.composition import composer
from referentiel.models import KPI, Niveau, Organisation, Referentiel, Utilisateur
from django.test import TestCase

D = Decimal


class ExportReimporteTests(BaseMois):
    """Anomalie « reimport_rejects » (``imports._comparer``) : l'export « Base de données » d'un exercice dont un KPI est la
    somme de ses mois, réimporté tel quel, rejette les valeurs annuelles cumulées (« Cette valeur est le total de périodes
    plus courtes ») au lieu de les ignorer comme les autres valeurs calculées (README, « Exports » : « You can import an
    exported file again as it is » ; « Import values » : les KPI calculés et les totaux sont ignorés)."""

    def test_valeur_cumulee_reimportee_telle_quelle_sans_rejet(self):
        for m in range(1, 13):
            if (2026, m) != (2026, 3):
                self.saisir_mois(2026, m, self.e1, 10)
        self.saisir_mois(2026, 3, self.e1, 10)
        recalculer(self.annee)
        self.assertEqual(Reponse.objects.get(periode=self.annee.periode, kpi=self.elec, organisation=self.e1).valeur, D(120))
        p = E.Parametres.depuis({"presentation": "base", "format": "xlsx", "exercices": ["2026"], "periodes": ["annee"],
                                 "referentiel": "RSE"})
        rep = E.exporter(self.admin, p)
        contenu = b"".join(rep.streaming_content) if rep.streaming else rep.content
        a = I.analyser(self.admin, SimpleUploadedFile("export.xlsx", contenu), campagne_defaut=self.annee)
        rejets = [(l.kpi_id, l.motif) for l in a.lignes if l.action == "rejet"]
        self.assertEqual(rejets, [])


class ArbrePasse(TestCase):
    """Groupe > Pays > E1, E2 ; Groupe > Pays 2 > E3 ; exercice 2025 saisi, calculé puis clôturé (comme par l'écran)."""

    def setUp(self):
        self.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.p = Organisation.objects.create(nom="Pays", niveau_id=Niveau.COUNTRY, parent=self.g)
        self.p2 = Organisation.objects.create(nom="Pays 2", niveau_id=Niveau.COUNTRY, parent=self.g)
        self.e1 = Organisation.objects.create(nom="E1", niveau_id=Niveau.ENTITY, parent=self.p)
        self.e2 = Organisation.objects.create(nom="E2", niveau_id=Niveau.ENTITY, parent=self.p)
        self.e3 = Organisation.objects.create(nom="E3", niveau_id=Niveau.ENTITY, parent=self.p2)
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN)
        self.eff = KPI.objects.create(code="EFF", libelle="Effectif", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                                      methode_agregation="Somme")
        self.ref = Referentiel.objects.create(code="RAP", nom="Rapport", ordre=1)
        composer({"EFF": ["Social"]}, self.ref)
        self.c, _ = P.campagne(self.ref, datetime.date(2025, 1, 1), statut=Campagne.Statut.OUVERTE,
                               date_fin_saisie=timezone.localdate() + datetime.timedelta(days=30))
        for org, v in ((self.e1, 10), (self.e2, 20), (self.e3, 5)):
            Reponse.objects.create(periode=self.c.periode, kpi=self.eff, organisation=org, valeur=D(v),
                                   statut=Reponse.Statut.VALIDE, origine=Reponse.Origine.SAISIE)
        recalculer(self.c)
        changer_statut(self.admin, self.c, "cloturer")
        self.assertEqual(self.total(self.p), (D(30), Reponse.Statut.CALCULE))

    def total(self, org, kpi="EFF"):
        r = Reponse.objects.filter(periode=self.c.periode, kpi_id=kpi, organisation=org).first()
        return (r.valeur, r.statut) if r else None

    def rouvrir(self, garder=False):
        """« Rouvrir pour la revue ». : ``garder`` = garder les chiffres de l'époque (rien
        n'est recalculé) ; sinon la période est recalculée avec l'organisation d'aujourd'hui (comportement d'avant)."""
        changer_statut(self.admin, self.c, "rouvrir", garder=garder)


class SiteCreeDepuisTests(ArbrePasse):
    """Anomalie « past_total_becomes_incomplete » : date d'ouverture d'une
    organisation) : une organisation créée après la clôture d'un exercice, sans date d'ouverture, comptait comme ouverte
    pendant la période ; rouvrir l'exercice rendait ses totaux « incomplets ». Avec sa date d'ouverture, elle ne compte
    qu'à partir de cette date, même quand l'exercice est recalculé."""

    def test_rouvrir_un_exercice_garde_ses_totaux_apres_une_creation(self):
        Organisation.objects.create(nom="E4 (créée en 2026)", niveau_id=Niveau.ENTITY, parent=self.p,
                                    date_ouverture=datetime.date(2026, 1, 1))
        self.rouvrir()  # recalculée avec l'organisation d'aujourd'hui
        self.assertEqual(self.total(self.p), (D(30), Reponse.Statut.CALCULE))
        self.assertEqual(self.total(self.g), (D(35), Reponse.Statut.CALCULE))

    def test_sans_date_d_ouverture_rien_ne_change(self):
        """Sans date (toute organisation existante à la mise à jour) : comptée comme ouverte depuis toujours, comme avant."""
        Organisation.objects.create(nom="E4 (créée en 2026)", niveau_id=Niveau.ENTITY, parent=self.p)
        self.rouvrir()
        self.assertEqual(self.total(self.p), (None, Reponse.Statut.INCOMPLET))

    def test_garder_les_chiffres_de_l_epoque(self):
        Organisation.objects.create(nom="E4 (créée en 2026)", niveau_id=Niveau.ENTITY, parent=self.p)
        self.rouvrir(garder=True)  # rien n'est recalculé, même sans date d'ouverture
        self.assertEqual(self.total(self.p), (D(30), Reponse.Statut.CALCULE))


class EntiteDeplaceeTests(ArbrePasse):
    """Anomalie « past_figure_changes » (le choix à la réouverture) : l'arbre n'a pas
    d'historique ; une entité rattachée à un autre pays après la clôture déplaçait ses valeurs passées dans le total de son
    nouveau pays quand l'exercice était rouvert. « Garder les chiffres de l'époque » : les totaux publiés restent ;
    « recalculer avec l'organisation d'aujourd'hui » : comportement d'avant, voulu."""

    def test_rouvrir_un_exercice_garde_les_totaux_des_pays_apres_un_deplacement(self):
        Organisation.objects.filter(pk=self.e2.pk).update(parent=self.p2)
        self.rouvrir(garder=True)
        self.assertEqual(self.total(self.p), (D(30), Reponse.Statut.CALCULE))
        self.assertEqual(self.total(self.p2), (D(5), Reponse.Statut.CALCULE))

    def test_recalculer_avec_l_organisation_d_aujourd_hui(self):
        Organisation.objects.filter(pk=self.e2.pk).update(parent=self.p2)
        self.rouvrir(garder=False)
        self.assertEqual(self.total(self.p), (D(10), Reponse.Statut.CALCULE))
        self.assertEqual(self.total(self.p2), (D(25), Reponse.Statut.CALCULE))


class KpiAjouteDepuisTests(ArbrePasse):
    """Anomalie « past_year_gets_new_cells » : une période ne calcule que
    les KPI de ses campagnes, et une période rouverte garde le périmètre qu'elle avait) : un KPI ajouté au référentiel
    après la clôture apparaissait dans l'exercice passé quand on le rouvrait (cases « incomplètes » créées), alors qu'il
    n'était pas demandé cette année-là. Même chose pour les KPI d'un autre référentiel sans campagne sur la période. Les
    tests rouvrent en recalculant (le choix « garder les chiffres » ne crée de toute façon aucune case)."""

    def test_rouvrir_un_exercice_ne_cree_pas_les_cases_d_un_kpi_ajoute_depuis(self):
        nouveau = KPI.objects.create(code="NEW", libelle="Nouveau", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                                     methode_agregation="Somme")
        composer({"NEW": ["Social"]}, self.ref)
        self.rouvrir()
        self.assertFalse(Reponse.objects.filter(periode=self.c.periode, kpi=nouveau).exists())

    def test_rouvrir_un_exercice_ne_cree_pas_les_cases_d_un_autre_referentiel(self):
        autre = KPI.objects.create(code="SOC", libelle="Social", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                                   methode_agregation="Somme")
        composer({"SOC": ["Social"]}, Referentiel.objects.create(code="SOCIAL", nom="Social", ordre=2))
        self.rouvrir()
        self.assertFalse(Reponse.objects.filter(periode=self.c.periode, kpi=autre).exists())


# ---------------------------------------------------------------- quatrième année (qa/group_life/year4.py), règles à trancher
class UniteChangeeTests(ArbrePasse):
    """Anomalie « unit_changed_with_values » (règle du projet : refuser, comme pour le format ;
    ``reglages.motif_unite_figee``, toutes les portes dans ``test_motif_unite_figee.py``) : l'unité d'un KPI qui a des
    valeurs changeait sans un mot. L'unité est celle du KPI, pas de chaque valeur : EFF passé de « personnes » à « milliers
    de personnes » après 2025 faisait lire les 30 personnes de 2025 « 30 milliers » à côté de 2026, dans l'écran, les
    exports et la comparaison N-1."""

    def test_unite_d_un_kpi_qui_a_des_valeurs_figee(self):
        from collecte import reglages as R
        from parametres.models import Unite

        personnes = Unite.objects.create(code="pers", symbole="pers.", libelle="personnes", ordre=90)
        milliers = Unite.objects.create(code="kpers", symbole="k pers.", libelle="milliers de personnes", ordre=91)
        KPI.objects.filter(pk="EFF").update(unite=personnes, type_reponse_id="Numérique")
        k = KPI.objects.get(pk="EFF")
        form = R.KPIForm(instance=k)
        donnees = {n: form[n].value() for n in form.fields if form[n].value() not in (None, False, "")}
        donnees.update(unite=milliers.pk, version=R.version_kpi(k), confirmer="on")
        self.assertFalse(R.KPIForm(donnees, instance=k).is_valid())


class LecteurGardeSesAttributionsTests(ArbrePasse):
    """Anomalie « reader_keeps_assignments » (règle du projet : retirer ses attributions avec le
    changement de rôle, une ligne dans l'historique ; ``attributions_lecture_seule``, détail dans
    ``test_retirer_attributions_lecture_seule.py``) : un validateur devenu lecteur gardait ses attributions de validateur ;
    la page Attributions le nommait encore validateur de son pays. La fiche refuse d'enregistrer tant que le retrait n'est
    pas confirmé (case qui annonce le nombre d'attributions retirées) : c'est ce que vérifie ce test."""

    def test_passage_en_lecture_seule_refuse_tant_qu_il_reste_des_attributions(self):
        from collecte.administration import CompteForm
        from referentiel.models import Attribution

        v = Utilisateur.objects.create(username="val", email="val@exemple.test", role=Utilisateur.Role.VALIDATEUR,
                                       first_name="Val", last_name="Idateur")
        Attribution.objects.create(kpi=self.eff, organisation=self.p, utilisateur=v, role=Attribution.Role.VALIDATEUR)
        donnees = {"first_name": "Val", "last_name": "Idateur", "email": "val@exemple.test", "role": Utilisateur.Role.LECTEUR,
                   "is_active": "on"}
        self.assertFalse(CompteForm(donnees, instance=v, moi=self.admin).is_valid())


del io
