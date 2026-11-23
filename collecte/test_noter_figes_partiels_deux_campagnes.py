"""Règle « Figer ses chiffres » (règle du projet) : deux campagnes sur un même exercice, l'une
clôturée, l'autre ouverte. Les KPI que demande la campagne clôturée (``calcul.noter_figes_partiels``) gardent leurs
chiffres : un changement de l'arbre, une désactivation, un recalcul à la mise à jour, « Recalculer » ou une saisie
dans l'autre campagne ne réécrivent plus leurs totaux, et toutes les pages les montrent avec l'arbre du jour de la
clôture. Un KPI commun aux deux campagnes est figé lui aussi (sa saisie est déjà bloquée dans la campagne ouverte).
Une correction importée dans la campagne clôturée refait l'organisation corrigée et ses totaux de l'époque.
Avant : la période n'était figée que quand toutes ses campagnes l'étaient, un total publié passait de 30 à 10
(``qa/calculation_fuzz.py --v3``, graine 194 entre autres).

Groupe > Pays > E1, E2 ; Groupe > Pays 2 > E3. Référentiel A (clôturé) : X, Z = 2 × X, C ; référentiel B (ouvert) : Y,
C. Données inventées."""
import datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from referentiel.composition import composer
from referentiel.models import KPI, Frequence, Niveau, Organisation, Referentiel, Utilisateur

from . import calcul as C
from . import periodes as P
from .administration import changer_statut
from .models import Campagne, Periode, Reponse
from .signals import en_lot, signaler

D = Decimal
FIN = timezone.localdate() + datetime.timedelta(days=30)


class DeuxCampagnes(TestCase):
    def setUp(self):
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN)
        self.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.p = Organisation.objects.create(nom="Pays", niveau_id=Niveau.COUNTRY, parent=self.g)
        self.p2 = Organisation.objects.create(nom="Pays 2", niveau_id=Niveau.COUNTRY, parent=self.g)
        self.e1 = Organisation.objects.create(nom="E1", niveau_id=Niveau.ENTITY, parent=self.p)
        self.e2 = Organisation.objects.create(nom="E2", niveau_id=Niveau.ENTITY, parent=self.p)
        self.e3 = Organisation.objects.create(nom="E3", niveau_id=Niveau.ENTITY, parent=self.p2)
        for code in ("X", "Y", "C"):
            KPI.objects.create(code=code, libelle=code, type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                               methode_agregation="Somme")
        KPI.objects.create(code="Z", libelle="Z", type_saisie_id="Calculé", granularite_id=Niveau.ENTITY,
                           methode_agregation="Somme", formule="[X]*2")
        self.ref_a = Referentiel.objects.create(code="A", nom="Annuel A", ordre=1, frequence=Frequence.ANNEE)
        self.ref_b = Referentiel.objects.create(code="B", nom="Annuel B", ordre=2, frequence=Frequence.ANNEE)
        composer({"X": ["S"], "Z": ["S"], "C": ["S"]}, self.ref_a)
        composer({"Y": ["S"], "C": ["S"]}, self.ref_b)
        debut = datetime.date(2025, 1, 1)
        self.ca, _ = P.campagne(self.ref_a, debut, statut=Campagne.Statut.OUVERTE, date_fin_saisie=FIN)
        self.cb, _ = P.campagne(self.ref_b, debut, statut=Campagne.Statut.OUVERTE, date_fin_saisie=FIN)
        self.periode = self.ca.periode
        for kpi, valeurs in (("X", (10, 20, 5)), ("Y", (1, 2, 3)), ("C", (100, 200, 300))):
            for org, v in zip((self.e1, self.e2, self.e3), valeurs):
                Reponse.objects.create(periode=self.periode, kpi_id=kpi, organisation=org, valeur=D(v),
                                       statut=Reponse.Statut.VALIDE, origine=Reponse.Origine.SAISIE)
        C.recalculer(self.ca)
        changer_statut(self.admin, self.ca, "cloturer")

    def total(self, kpi, org):
        r = Reponse.objects.get(periode=self.periode, kpi_id=kpi, organisation=org)
        return r.valeur

    def deplacer_e2(self):
        """Comme la fiche de l'organisation : E2 rattachée à Pays 2, puis les campagnes non clôturées recalculées."""
        self.e2.parent = self.p2
        self.e2.save()
        C.recalculer_en_cours()

    def importer(self, kpi, org, valeur):
        """Comme ``imports._ecrire_historique`` dans la campagne clôturée : import validé, recalcul en fin de lot."""
        with en_lot():
            r = Reponse.objects.filter(periode=self.periode, kpi_id=kpi, organisation=org).first() or Reponse(
                periode=self.periode, kpi_id=kpi, organisation=org)
            r.valeur, r.statut, r.origine = D(valeur), Reponse.Statut.VALIDE, Reponse.Origine.IMPORT
            r.save()
            signaler(r)


class NoteTests(DeuxCampagnes):
    def test_kpi_de_la_campagne_close_et_sources_et_commun_figes(self):
        self.assertFalse(C.figee(self.periode))
        self.assertEqual(C.kpis_figes(self.periode), {"X", "Z", "C"})  # Y : seule la campagne ouverte le demande
        d = Periode.objects.get(pk=self.periode.pk).figes_partiels
        lignes = {o[0]: o for o in d["arbres"][d["kpis"]["X"]]["o"]}
        self.assertEqual(lignes[self.e2.pk][1], self.p.pk)  # arbre du jour de la clôture

    def test_reouverture_rend_les_kpi_au_calcul(self):
        self.deplacer_e2()
        changer_statut(self.admin, self.ca, "rouvrir")
        self.assertEqual(C.kpis_figes(self.periode), frozenset())
        self.assertIsNone(Periode.objects.get(pk=self.periode.pk).figes_partiels)
        self.assertEqual(self.total("X", self.p), D(10))  # recalculé avec l'arbre d'aujourd'hui (comme avant)
        self.assertEqual(self.total("X", self.p2), D(25))

    def test_cloture_de_la_seconde_campagne_garde_la_note(self):
        changer_statut(self.admin, self.cb, "cloturer")
        self.assertTrue(C.figee(self.periode))
        self.assertEqual(C.kpis_figes(self.periode), {"X", "Z", "C"})

    def test_mise_a_jour_note_sans_rien_recalculer(self):
        """Installation existante : campagne déjà clôturée à côté d'une ouverte, rien noté à l'époque. La mise à jour note
        les KPI et l'arbre du jour, sans réécrire aucun chiffre."""
        Periode.objects.filter(pk=self.periode.pk).update(figes_partiels=None)
        self.e2.parent = self.p2
        self.e2.save()
        avant = sorted(Reponse.objects.values_list("pk", "valeur", "statut"))
        self.assertEqual(C.noter_figes_partiels_existants(), 1)
        self.assertEqual(sorted(Reponse.objects.values_list("pk", "valeur", "statut")), avant)
        self.assertEqual(C.kpis_figes(self.periode), {"X", "Z", "C"})
        d = Periode.objects.get(pk=self.periode.pk).figes_partiels
        lignes = {o[0]: o for o in d["arbres"][d["kpis"]["X"]]["o"]}
        self.assertEqual(lignes[self.e2.pk][1], self.p2.pk)  # arbre du jour de la mise à jour
        self.assertEqual(C.noter_figes_partiels_existants(), 0)

    def test_mise_a_jour_ne_touche_pas_un_exercice_entierement_clos(self):
        changer_statut(self.admin, self.cb, "cloturer")
        Periode.objects.filter(pk=self.periode.pk).update(figes_partiels=None)
        self.assertEqual(C.noter_figes_partiels_existants(), 0)
        self.assertIsNone(Periode.objects.get(pk=self.periode.pk).figes_partiels)


class ChiffresGardesTests(DeuxCampagnes):
    def test_deplacement_ne_reecrit_pas_les_totaux_figes(self):
        self.deplacer_e2()
        self.assertEqual(self.total("X", self.p), D(30))  # avant : 10
        self.assertEqual(self.total("X", self.p2), D(5))  # avant : 25
        self.assertEqual(self.total("X", self.g), D(35))
        self.assertEqual(self.total("Z", self.p), D(60))
        self.assertEqual(self.total("C", self.p), D(300))  # KPI commun : figé aussi
        self.assertEqual(self.total("Y", self.p), D(1))  # KPI de la seule campagne ouverte : arbre d'aujourd'hui
        self.assertEqual(self.total("Y", self.p2), D(5))

    def test_desactivation_ne_reecrit_pas_les_totaux_figes(self):
        self.e2.actif, self.e2.date_desactivation = False, datetime.date(2024, 12, 31)
        self.e2.save()
        C.recalculer_en_cours()
        self.assertEqual(self.total("X", self.p), D(30))
        self.assertEqual(self.total("Y", self.p), D(1))  # E2 fermée avant l'exercice : plus comptée pour Y

    def test_recalculer_et_saisie_dans_la_campagne_ouverte(self):
        from . import saisie as S

        self.deplacer_e2()
        C.recalculer(self.cb)  # bouton « Recalculer » de la campagne ouverte
        S.enregistrer(self.admin, self.cb, KPI.objects.get(code="Y"), self.e2, "7", False, "")
        self.assertEqual(self.total("X", self.p), D(30))
        self.assertEqual(self.total("Y", self.p2), D(10))  # 3 + 7

    def test_correction_importee_refait_l_organisation_et_ses_totaux_de_l_epoque(self):
        self.deplacer_e2()
        self.importer("X", self.e1, 15)
        self.assertEqual(self.total("X", self.p), D(35))  # 15 + 20 : E2 sous Pays, comme à la clôture
        self.assertEqual(self.total("X", self.p2), D(5))  # parent d'aujourd'hui de E2 : chiffre gardé
        self.assertEqual(self.total("X", self.g), D(40))
        self.assertEqual(self.total("Z", self.e1), D(30))
        self.assertEqual(self.total("Z", self.p), D(70))
        self.assertEqual(self.total("Y", self.p), D(1))

    def test_correction_d_une_organisation_deplacee(self):
        self.deplacer_e2()
        self.importer("X", self.e2, 21)
        self.assertEqual(self.total("X", self.p), D(31))  # son parent de l'époque
        self.assertEqual(self.total("X", self.p2), D(5))  # jamais compté deux fois
        self.assertEqual(self.total("X", self.g), D(36))

    def test_reouverture_recalculer_d_un_exercice_clos(self):
        """Exercice entièrement clos, rouvert « recalculer » pour A : les KPI de B (toujours clôturée) gardent leurs
        chiffres, avec l'arbre de la clôture de l'exercice ; ceux de A seulement suivent l'arbre d'aujourd'hui."""
        changer_statut(self.admin, self.ca, "rouvrir")
        changer_statut(self.admin, self.cb, "cloturer")
        changer_statut(self.admin, self.ca, "cloturer")
        self.deplacer_e2()
        changer_statut(self.admin, self.ca, "rouvrir", garder=False)
        self.assertEqual(C.kpis_figes(self.periode), {"Y", "C"})
        self.assertEqual(self.total("Y", self.p), D(3))  # 1 + 2 : E2 sous Pays, comme à la clôture (avant : 1)
        self.assertEqual(self.total("C", self.p), D(300))
        self.assertEqual(self.total("X", self.p), D(10))  # recalculé avec l'arbre d'aujourd'hui
        self.assertEqual(self.total("X", self.p2), D(25))

    def test_campagne_creee_sur_un_exercice_clos(self):
        """Une campagne ouverte créée sur un exercice clos (second référentiel) : les KPI de la campagne clôturée gardent
        leurs chiffres, avec l'arbre de la clôture."""
        changer_statut(self.admin, self.cb, "cloturer")
        Campagne.objects.filter(pk=self.cb.pk).delete()  # l'exercice n'a plus que A, clôturée
        ref_c = Referentiel.objects.create(code="CC", nom="Annuel C", ordre=3, frequence=Frequence.ANNEE)
        composer({"Y": ["S"]}, ref_c)
        self.deplacer_e2()
        P.campagne(ref_c, datetime.date(2025, 1, 1), statut=Campagne.Statut.OUVERTE, date_fin_saisie=FIN)
        C.recalculer_en_cours()
        self.assertEqual(C.kpis_figes(self.periode), {"X", "Z", "C"})
        self.assertEqual(self.total("X", self.p), D(30))


class PagesTests(DeuxCampagnes):
    """Mêmes chiffres partout, avec l'arbre de l'époque pour les KPI figés."""

    def setUp(self):
        super().setUp()
        self.deplacer_e2()

    def test_detail_d_un_total(self):
        from .vues_cellule import detail_agregat

        detail = detail_agregat(self.cb, KPI.objects.get(code="X"), self.p)
        self.assertEqual(sorted(n["org"].nom for n in detail), ["E1", "E2"])
        detail = detail_agregat(self.cb, KPI.objects.get(code="Y"), self.p)
        self.assertEqual([n["org"].nom for n in detail], ["E1"])

    def test_visualisation_et_serveur_mcp(self):
        from . import visualisation as V

        for codes in (None, ["X"]):
            s = V.Source(self.admin, codes)
            self.assertEqual(s.point("X", self.p, self.periode).valeur, D(30))
            self.assertEqual(sorted(o.nom for o in s.enfants(self.p, self.periode, "X")), ["E1", "E2"])
            parts, total = s.repartition("X", self.p, self.periode)
            self.assertEqual((total, sum(v for _, v, _, _ in parts)), (D(30), D(30)))
            self.assertEqual(V.CalculateurValide(codes).valeur("X", self.p.id, self.periode), D(30))
        s = V.Source(self.admin, ["Y"])
        self.assertEqual([o.nom for o in s.enfants(self.p, self.periode, "Y")], ["E1"])

    def test_consolidation(self):
        from . import consolidation as CO

        t = CO.tableau(self.admin, self.periode, [KPI.objects.get(code="X")])
        lignes = {l.org.nom: l for l in t.lignes}
        self.assertEqual(lignes["E2"].parent_id, self.p.pk)
        self.assertEqual(lignes["Pays"].cases[0].point.valeur, D(30))
        t = CO.tableau(self.admin, self.periode, [KPI.objects.get(code="Y")])
        self.assertEqual({l.org.nom: l for l in t.lignes}["E2"].parent_id, self.p2.pk)

    def test_export(self):
        from . import exports as E

        p = E.Parametres(niveaux=[Niveau.GROUP, Niveau.COUNTRY, Niveau.ENTITY], exercices=["2025"])
        lignes = E.collecter(self.admin, p)
        x = {l.org.nom: l for l in lignes if l.kpi.code == "X"}
        y = {l.org.nom: l for l in lignes if l.kpi.code == "Y"}
        self.assertEqual(x["E2"].org.parent_id, self.p.pk)
        self.assertEqual(x["Pays"].reponse.valeur, D(30))
        self.assertEqual(y["E2"].org.parent_id, self.p2.pk)

    def test_grille_de_la_campagne_close(self):
        from . import saisie as S

        e4 = Organisation.objects.create(nom="E4", niveau_id=Niveau.ENTITY, parent=self.p)  # créée après la clôture
        cases = {(k.code, o.nom) for k, o in S.cellules(self.admin, campagne=Campagne.objects.get(pk=self.ca.pk))}
        self.assertIn(("X", "E2"), cases)
        self.assertNotIn(("X", e4.nom), cases)  # pas dans l'arbre du jour de la clôture
        cases = {(k.code, o.nom) for k, o in S.cellules(self.admin, campagne=Campagne.objects.get(pk=self.cb.pk))}
        self.assertIn(("Y", e4.nom), cases)  # campagne ouverte : arbre d'aujourd'hui
