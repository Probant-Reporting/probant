"""Page Cohérence à gros volume : la construction actuelle des contrôles automatiques et des
alertes visibles donne exactement ce que donnait l'ancienne (``aides_tests/coherence_avant.py``), sur des données tirées
au hasard avec une graine fixe : arbre avec organisations fermées, historique incomplet, N/A, zéros, valeurs négatives,
décimales sur un comptage, facteurs d'émission, valeurs saisies au-dessus de la granularité, commentaires, réponses
calculées mêlées aux saisies, règle entre KPI ; puis plusieurs vagues de changements au hasard."""
from parametres import langues as L
from referentiel.models import KPI, Niveau, Utilisateur

from . import coherence as CO
from .aides_tests import coherence_avant as AVANT
from .aides_tests.donnees_tirees import Donnees
from .models import Alerte, Campagne

C = Alerte.Controle


def normaliser(detections):
    """Détections comparables : objets remplacés par leur clé, textes par leur chaîne et leur spécification."""
    return sorted((d["kpi"].pk, d["org"].pk, d["controle"], str(d["message"]), str(d["valeur"]), str(d["reference"]), d["gravite"],
                   d["empreinte"], d["regle"].pk if d["regle"] else None, d["kpis_concernes"], repr(sorted(d["textes"].items())))
                  for d in detections)


def decrire(alertes):
    """Alertes visibles comparables, avec ce que la page lit des objets reliés."""
    return sorted((a.pk, a.kpi.code, a.kpi.nom, a.kpi.symbole, a.organisation.nom, a.organisation.niveau_id,
                   a.regle.nom if a.regle else None, a.justifie_par_id, a.traite_par_id, CO.constat_lisible(a),
                   CO.texte_alerte(a, "valeur"), CO.texte_alerte(a, "reference")) for a in alertes)


class Comparaison(Donnees):
    def comparer(self):
        c = Campagne.objects.get(pk=self.c.pk)
        with L.session():
            avant, apres = AVANT.controles_automatiques(c), CO.controles_automatiques(Campagne.objects.get(pk=c.pk))
            self.assertEqual(normaliser(avant), normaliser(apres))
            # toutes les détections de la page : règles et écart avec le détail avec un calculateur partagé, comme avant
            # avec un calculateur chacun
            regles = CO.controles_regles(Campagne.objects.get(pk=c.pk))
            self.assertTrue(regles)
            self.assertEqual(normaliser(avant + CO.controles_calcul(c) + regles),
                             normaliser(CO._detections(Campagne.objects.get(pk=c.pk), None)[0]))
            for kpis in ([self.kpis[0].pk], [self.kpis[1].pk, self.kpis[3].pk]):  # contrôle limité aux KPI d'une saisie
                self.assertEqual(normaliser(AVANT.controles_automatiques(c, kpis)),
                                 normaliser(CO.controles_automatiques(Campagne.objects.get(pk=c.pk), kpis)))
        CO.controler(c)
        for u in (self.admin, self.contrib, self.valid, self.lect):
            with self.subTest(utilisateur=u.username), L.session():
                u = Utilisateur.objects.get(pk=u.pk)
                self.assertEqual(decrire(AVANT.alertes_visibles(u, c)), decrire(CO.alertes_visibles(u, c)))
        return {d["controle"] for d in avant}



class EquivalenceControles(Comparaison):
    def test_memes_detections_et_memes_alertes_visibles(self):
        vus = self.comparer()
        Alerte.objects.filter(campagne=self.c).update(justifie_par=self.contrib, traite_par=self.admin)
        for _ in range(4):
            self.changer(60)
            vus |= self.comparer()
        # le tirage produit bien tous les contrôles automatiques
        self.assertEqual(vus, {C.DETAIL, C.ECART_N1, C.FE, C.FORMAT, C.HISTORIQUE, C.RUPTURE})

    def test_comparaison_hors_historique(self):
        """Période de comparaison absente de l'historique lu (un seul exercice d'historique) : lue à part, même résultat."""
        from parametres.models import Instance

        Instance.objects.update(historique_annees=1)
        self.c.referentiel.comparaison = "N-1"
        self.comparer()
        self.changer(80)
        self.comparer()


class RequetesAlertesVisibles(Donnees):
    def test_calculs_impossibles_sans_requete_par_alerte(self):
        """Un validateur qui voit des calculs impossibles : le nombre de requêtes ne suit pas le nombre d'alertes (avant :
        deux à trois requêtes par alerte, 13 900 ms pour la page Cohérence de la grosse base)."""
        from .aides_tests.vitesse import requetes

        CO.controler(self.c)
        u = Utilisateur.objects.get(pk=self.valid.pk)
        avant = len(requetes(lambda: CO.alertes_visibles(u, Campagne.objects.get(pk=self.c.pk))))
        a = next(x for x in CO.alertes_visibles(u, self.c) if x.controle == C.CALCUL)
        for i in range(8):  # d'autres calculs impossibles dans les mêmes organisations
            k = KPI.objects.create(code=f"CX{i}", libelle="Calculé", type_saisie_id="Calculé", formule="[NRJ] / 0",
                                   granularite_id=Niveau.SITE, methode_agregation="Aucune")
            Alerte.objects.create(campagne=self.c, kpi=k, organisation=a.organisation, controle=C.CALCUL,
                                  gravite=Alerte.Gravite.INFO, message="Division par zéro.")
        visibles = CO.alertes_visibles(u, Campagne.objects.get(pk=self.c.pk))
        self.assertGreaterEqual(sum(1 for x in visibles if x.controle == C.CALCUL), 9)
        self.assertEqual(avant, len(requetes(lambda: CO.alertes_visibles(u, Campagne.objects.get(pk=self.c.pk)))))
