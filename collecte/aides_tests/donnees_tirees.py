"""Données tirées au hasard avec une graine fixe, pour les tests d'équivalence à gros volume :
arbre avec organisations fermées, historique de cinq exercices incomplet, N/A, zéros, valeurs négatives, décimales sur
un comptage, facteurs d'émission, valeurs saisies au-dessus de la granularité, commentaires, réponses calculées mêlées
aux saisies, calculs impossibles, règle entre KPI, comptes des quatre rôles ; ``changer`` fait une vague de changements."""
import random
from datetime import date
from decimal import Decimal

from django.test import TestCase

from parametres.referentiel import unite_depuis_symbole as U
from referentiel.models import KPI, Attribution, Niveau, Organisation, Utilisateur

from collecte.models import Campagne, RegleCoherence, Reponse

D = Decimal
ORIGINES = [Reponse.Origine.SAISIE] * 6 + [Reponse.Origine.IMPORT] * 3 + [Reponse.Origine.AGREGATION]


class Donnees(TestCase):
    """Arbre, KPI, historique et comptes tirés au hasard (graine fixe)."""
    graine = 20261113

    def setUp(self):
        self.h = random.Random(self.graine)
        h = self.h
        g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.orgs = [g]
        self.entites, self.sites = [], []
        for i in range(2):
            pays = Organisation.objects.create(nom=f"Pays {i}", niveau_id=Niveau.COUNTRY, parent=g)
            self.orgs.append(pays)
            for j in range(2):
                e = Organisation.objects.create(nom=f"Filiale {i}{j}", niveau_id=Niveau.ENTITY, parent=pays)
                self.entites.append(e)
                for s in range(3):
                    site = Organisation.objects.create(nom=f"Site {i}{j}{s}", niveau_id=Niveau.SITE, parent=e)
                    self.sites.append(site)
        # sites fermés : pendant l'exercice contrôlé (encore contrôlés), avant (plus contrôlés), sans date (plus contrôlés)
        for site, fin in zip(self.sites[:3], (date(2026, 6, 30), date(2025, 3, 31), None)):
            site.actif, site.date_desactivation = False, fin
            site.save()
        self.orgs += self.entites + self.sites
        self.anciennes = [Campagne.objects.create(exercice=ex, statut=Campagne.Statut.CLOTUREE) for ex in range(2021, 2026)]
        self.c = Campagne.objects.create(exercice=2026, statut=Campagne.Statut.OUVERTE, seuil_ecart=D("0.2"))
        sal, kwh = U("employees"), U("kWh")
        self.kpis = [
            KPI.objects.create(code="EFF", libelle="Effectif", type_saisie_id="Saisi", granularite_id=Niveau.SITE, unite=sal,
                               methode_agregation="Somme", saisie_au_dessus=True),
            KPI.objects.create(code="NRJ", libelle="Énergie", type_saisie_id="Saisi", granularite_id=Niveau.SITE, unite=kwh,
                               methode_agregation="Somme"),
            KPI.objects.create(code="TX", libelle="Taux", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                               type_reponse_id="Pourcentage", methode_agregation="Aucune"),
            KPI.objects.create(code="FE1", libelle="Facteur", type_saisie_id="FE", granularite_id=Niveau.ENTITY,
                               unite=U("kgCO2eq/L"), methode_agregation="Aucune"),
            KPI.objects.create(code="OFF", libelle="Inactif", type_saisie_id="Saisi", granularite_id=Niveau.SITE, unite=kwh,
                               methode_agregation="Somme", actif=False),
            KPI.objects.create(code="CAL", libelle="Calculé", type_saisie_id="Calculé", formule="[NRJ] / [EFF]",
                               granularite_id=Niveau.SITE, methode_agregation="Aucune"),
        ]
        self.regle = RegleCoherence.objects.create(nom="Taux ≤ 30 %", gauche="[TX]", operateur="<=", droite="0.3",
                                                   niveau_id=Niveau.ENTITY)
        for periode in [c.periode for c in self.anciennes] + [self.c.periode]:
            for k in self.kpis:
                for o in self.orgs:
                    if o.niveau_id == k.granularite_id or (k.code == "EFF" and o.niveau_id == Niveau.ENTITY):
                        if h.random() < 0.85:
                            self.reponse(periode, k, o)
        # calculs impossibles (information visible de l'admin et des validateurs, pas des contributeurs)
        Reponse.objects.filter(periode=self.c.periode, kpi=self.kpis[5], organisation__in=self.sites[2:8]).update(
            statut=Reponse.Statut.ERREUR, message_calcul="Division par zéro.")
        self.admin = Utilisateur.objects.create(username="adm", email="adm@exemple.test", role=Utilisateur.Role.ADMIN)
        self.contrib = Utilisateur.objects.create(username="ctb", email="ctb@exemple.test")
        self.valid = Utilisateur.objects.create(username="vld", email="vld@exemple.test", role=Utilisateur.Role.VALIDATEUR)
        self.lect = Utilisateur.objects.create(username="lct", email="lct@exemple.test", role=Utilisateur.Role.LECTEUR)
        for k in self.kpis[:4]:
            for o in self.sites[:6] + self.entites[:2]:
                Attribution.objects.create(kpi=k, organisation=o, utilisateur=self.contrib)
        Attribution.objects.create(kpi=self.kpis[0], organisation=self.entites[1], utilisateur=self.valid,
                                   role=Attribution.Role.VALIDATEUR)

    def valeur(self, k):
        h = self.h
        tirage = h.random()
        if tirage < 0.05:
            return None, True  # N/A
        if tirage < 0.1:
            return D(0), False
        if tirage < 0.13:
            return D(-h.randint(1, 50)), False
        if k.code == "TX":
            return D(h.randint(0, 60)) / 100, False
        if k.code == "FE1":
            return h.choice([D("2.5"), D("2.5"), D("2.52"), D("3.1")]), False
        base = D(h.choice([100, 100, 120, 400, 5]))
        if h.random() < 0.1:
            base += D("0.5")  # décimales sur un comptage
        return base, False

    def reponse(self, periode, k, o):
        """Réponse écrite sans recalcul ni contrôle (pas de signal) : seules les données brutes comptent ici."""
        v, na = self.valeur(k)
        champs = {"valeur": v, "non_applicable": na, "statut": Reponse.Statut.VALIDE,
                  "origine": Reponse.Origine.CALCUL if k.est_calcule else self.h.choice(ORIGINES),
                  "commentaire": self.h.choice(["", "", "", "   ", "Nouveau site"])}
        if not Reponse.objects.filter(periode=periode, kpi=k, organisation=o).update(**champs):
            Reponse.objects.bulk_create([Reponse(periode=periode, kpi=k, organisation=o, **champs)])

    def changer(self, n):
        """Vague de changements au hasard dans l'exercice contrôlé et son historique (valeurs, N/A, retraits, ajouts)."""
        h = self.h
        periodes = [c.periode for c in self.anciennes[-3:]] + [self.c.periode] * 3
        for _ in range(n):
            p, k, o = h.choice(periodes), h.choice(self.kpis), h.choice(self.orgs)
            if h.random() < 0.15:
                Reponse.objects.filter(periode=p, kpi=k, organisation=o).delete()
            else:
                self.reponse(p, k, o)
