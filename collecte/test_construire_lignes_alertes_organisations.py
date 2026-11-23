"""Alertes des lignes (``saisie.construire_lignes``, échelle, lot D) : seules les alertes des organisations affichées
sont lues (une alerte ne va qu'à une ligne de son organisation : sa case, ou une règle entre KPI dans la même
organisation). Mêmes alertes, dans le même ordre, que l'ancienne lecture de toutes les alertes de la campagne, recopiée
ici (035536f).

Jeu de ``test_lignes_legeres_compteurs`` (tous les rôles), puis 400 alertes tirées au hasard à graine fixe : toutes les
organisations (dans et hors du périmètre de chacun), tous les contrôles, règles qui citent plusieurs KPI, KPI hors de la
campagne, tous les statuts (à traiter ou non), calculs impossibles ; pour chaque personne : toutes ses lignes, « Pour
moi », une organisation avec les calculés."""
import random

from django.db.models import Q
from django.test import TestCase

from collecte import saisie as S
from collecte import test_lignes_legeres_compteurs as LL
from collecte.coherence import AVEC_KPI, visible
from collecte.models import Alerte
from referentiel.models import KPI, Organisation

GRAINE = 20261114


def alertes_avant(campagne, lignes, cases_visibles):
    """Ancienne lecture (035536f) : toutes les alertes à traiter de la campagne, puis le tri par case."""
    cles = {(l.kpi.code, l.organisation.id) for l in lignes}
    kpi_ids = {k for k, _ in cles}
    alertes = {}
    qs = (Alerte.objects.filter(campagne=campagne, statut__in=Alerte.A_TRAITER).exclude(controle=Alerte.Controle.CALCUL)
          .select_related(*AVEC_KPI).filter(Q(kpi_id__in=kpi_ids) | Q(controle=Alerte.Controle.REGLE)))
    for a in qs if cles else ():
        if cases_visibles is not None and not visible(a, cases_visibles):
            continue
        for k in (a.kpis_concernes.split() if a.controle == Alerte.Controle.REGLE else [a.kpi_id]):
            if (k, a.organisation_id) in cles:
                alertes.setdefault((k, a.organisation_id), []).append(a.pk)
    return alertes


class AlertesDesLignesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        LL.LignesLegeresTests.setUpTestData.__func__(cls)
        h = random.Random(GRAINE)
        kpis = list(KPI.objects.all())
        orgs = list(Organisation.objects.all())
        controles = [c for c, _ in Alerte.Controle.choices]
        nouvelles = []
        for _ in range(400):
            controle = h.choice(controles)
            k = h.choice(kpis)
            cites = " ".join(x.code for x in h.sample(kpis, h.randint(1, 4))) if controle == Alerte.Controle.REGLE else ""
            nouvelles.append(Alerte(campagne=h.choice([cls.c, cls.c, cls.c2, cls.cm]), kpi=k, organisation=h.choice(orgs),
                                    controle=controle, kpis_concernes=cites, message="Essai",
                                    statut=h.choice([s for s, _ in Alerte.Statut.choices]),
                                    gravite=h.choice([g for g, _ in Alerte.Gravite.choices])))
        Alerte.objects.bulk_create(nouvelles, ignore_conflicts=True)

    def test_memes_alertes_que_l_ancienne_lecture(self):
        vues = 0
        for u in self.personnes:
            for c in (self.c, self.c2, self.cm, self.c25):
                visibles = None if u.voit_tout and u.orgs_permises() is None else {(k.code, o.id) for k, o in S.cellules(u, False, c)}
                perso = {(k.code, o.id) for k, o in S.cellules(u, True, c)}
                cas = [("toutes", S.lignes(u, c), visibles), ("pour moi", S.lignes(u, c, personnel=True), visibles if visibles is None else perso)]
                cas += [(f"org {o.pk}", S.lignes(u, c, org=o, calculees=True), visibles)
                        for o, *_ in S.organisations_visibles(u, c)[:3]]
                for nom, lignes, cases in cas:
                    with self.subTest(personne=u.username, campagne=str(c), lignes=nom):
                        avant = alertes_avant(c, lignes, cases)
                        apres = {(l.kpi.code, l.organisation.id): [a.pk for a in l.alertes] for l in lignes if l.alertes}
                        self.assertEqual(apres, avant)
                        vues += sum(len(v) for v in avant.values())
        self.assertGreater(vues, 300)
