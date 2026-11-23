"""Recalcul ciblé après une saisie (``calcul.organisations_touchees``) : preuve d'équivalence avec le recalcul de toutes
les organisations.

Sur des cas générés (arbres de plusieurs niveaux, organisations fermées pendant la période, rattachement souple, KPI en
somme / décompte / formule imbriquée, paramètres hérités, formules [X@N-1] / [X@P-1] / [X@AAAA], agrégation des mois
dans l'année, N/A, valeurs forcées, imports dans une campagne clôturée ; générateur de ``qa/calculation_fuzz.py``, avec
des arbres plus larges), une suite de modifications au hasard (saisie, N/A, effacement, validation, valeur forcée, retour
au calcul, import d'historique, lot de saisies comme un paquet d'import). Après CHAQUE modification, en partant de
l'état réel laissé par les modifications précédentes (aucun rafraîchissement préalable) : la modification, puis le
recalcul ciblé ; retour au point de sauvegarde ; la même modification, puis le recalcul de toutes les organisations
(celui d'avant le ciblage, mêmes KPI : ``kpis_a_refaire``) ; la table des réponses (valeur, statut, origine, N/A,
message, commentaire, auteurs) et le journal sont identiques ; l'état continue depuis le second. Graines fixes.

Import dans une campagne clôturée : depuis la, la période clôturée elle-même ne refait que
l'organisation corrigée et ses totaux au-dessus (``test_recalculer_correction_cloturee.py``) ; la référence est alors ce
recalcul de la période clôturée, suivi du recalcul de toutes les organisations des périodes ouvertes qui en dépendent
(``calcul.CIBLAGE_PERIODES_OUVERTES`` à False).

Arbre gardé à chaque clôture : dans la plupart des cas, après la construction, l'arbre change
(organisations déplacées, créées, fermées) puis une campagne clôturée est rouverte en gardant les chiffres de l'époque
(``arbre_change``) ; ses corrections se calculent dans l'arbre de sa clôture, les périodes ouvertes dans celui
d'aujourd'hui, et le recalcul ciblé reste identique à la référence.

Données inventées uniquement."""
import datetime
import os
import random
import sys
from pathlib import Path
from unittest import mock

from django.db import transaction
from django.test import TestCase

from referentiel.models import KPI, Niveau, Organisation

from . import calcul as C
from .models import Campagne, Journal, Reponse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "qa"))

COLONNES = ("valeur", "texte", "non_applicable", "statut", "origine", "message_calcul", "commentaire", "saisi_par_id",
            "valide_par_id")


def _arbre_large(R, L, annees):
    """Arbre de L niveaux, plus large que celui du générateur (plusieurs branches par niveau) ; fermetures comme lui."""
    orgs = [dict(id="O0", rank=1, parent=None, active=True, closed=None)]
    for r in range(2, L + 1):
        for _ in range(R.randint(2, 2 + r)):
            plus_haut = [o for o in orgs if o["rank"] < r]
            juste = [o for o in plus_haut if o["rank"] == r - 1]
            parent = R.choice(juste) if juste and R.random() < 0.85 else R.choice(plus_haut)  # rattachement souple
            orgs.append(dict(id=f"O{len(orgs)}", rank=r, parent=parent["id"], active=True, closed=None))
    for o in orgs[1:]:
        if R.random() < 0.15:
            o["active"] = False
            if R.random() < 0.8:
                a = R.choice(annees + [annees[0] - 1])
                o["closed"] = datetime.date(a, R.randint(1, 12), R.choice([1, 15, 28])).isoformat()
    par_id = {o["id"]: o for o in orgs}
    for o in orgs:  # une organisation ferme au plus tard avec son parent
        p = par_id.get(o["parent"]) if o["parent"] else None
        if p is not None and not p["active"]:
            if o["active"] or (o["closed"] and (p["closed"] is None or o["closed"] > p["closed"])) or (
                    o["closed"] is None and p["closed"]):
                o["active"], o["closed"] = False, p["closed"]
    return orgs


def generer(graine):
    """Cas du générateur des cas au hasard, avec un arbre plus large ; None s'il n'a pas assez de niveaux ou de KPI."""
    import calculation_fuzz as CF

    cas = CF.generate(graine)
    if cas["levels"] < 3 or not any(k["comp"] == "calcul" for k in cas["kpis"]):
        return None
    R = random.Random(graine * 7919 + 1)
    annees = sorted({int(p["debut"][:4]) for p in cas["periods"] if p["type"] == "annee"})
    cas["orgs"] = _arbre_large(R, cas["levels"], annees)
    cas["inputs"], cas["changes"] = [], []
    CF._saisies(R, cas)
    cas["changes"] = []
    return cas


class RecalculCibleEquivalenceTests(TestCase):
    """Après chaque modification, recalcul ciblé = recalcul de toutes les organisations (même état de départ)."""

    CAS = int(os.environ.get("PROBANT_CALCUL_CIBLE_CAS", 5))  # nombre de cas (arbres et référentiels différents)
    PAS = int(os.environ.get("PROBANT_CALCUL_CIBLE_PAS", 70))  # modifications par cas (plus : hors de la suite)

    def etat(self):
        lignes = {(r[0], r[1], r[2]): r[3:] for r in Reponse.objects.values_list("periode_id", "kpi_id", "organisation_id",
                                                                                 *COLONNES)}
        journal = sorted(Journal.objects.values_list("action", "objet_id", "champ", "avant", "apres"))
        return lignes, journal

    def comparer(self, appliquer, periode, kpi_ids, orgs, contexte):
        """Renvoie les organisations ciblées (None : toutes)."""
        appliquer()
        kpis = C.kpis_a_refaire(kpi_ids, orgs, periode)  # tous les KPI si une organisation fermée peut changer de statut
        touchees = C.organisations_touchees(kpis, orgs)
        point = transaction.savepoint()
        C.recalculer(periode, kpi_ids, organisations=orgs)
        cible = self.etat()
        transaction.savepoint_rollback(point)
        # référence : la période clôturée ciblée, les périodes ouvertes refaites en entier ; de même quand une période
        # est rouverte en gardant les chiffres de l'époque : elle ne se refait que par une correction
        # ciblée (organisations données), jamais par un recalcul d'ensemble
        if C.figee(periode) or Campagne.objects.filter(chiffres_gardes=True).exclude(statut=Campagne.Statut.CLOTUREE).exists():
            with mock.patch.object(C, "CIBLAGE_PERIODES_OUVERTES", False):
                C.recalculer(periode, kpi_ids, organisations=orgs)
        else:
            C.recalculer(periode, kpis)  # référence : toutes les organisations, mêmes KPI ; l'état continue d'ici
        complet = self.etat()
        if cible != complet:
            a, b = cible[0], complet[0]
            ecarts = {k: (a.get(k), b.get(k)) for k in set(a) | set(b) if a.get(k) != b.get(k)}
            hors = {k: touchees is not None and k[2] not in touchees for k in ecarts}
            self.fail(f"{contexte} : {len(ecarts)} case(s) différente(s) (ciblé, complet) : "
                      f"{dict(list(ecarts.items())[:5])} ; hors des organisations ciblées : {hors} ; "
                      f"journal identique : {cible[1] == complet[1]}")
        return touchees

    def test_recalcul_cible_identique_au_recalcul_complet(self):
        import calculation_fuzz as CF

        choisies = [int(g) for g in os.environ.get("PROBANT_CALCUL_CIBLE_GRAINES", "").split(",") if g]  # rejouer un cas
        faits, graine, compte = 0, 0, {"pas": 0, "cibles": 0}
        while faits < (len(choisies) or self.CAS):
            graine = choisies[faits] if choisies else graine + 1
            cas = generer(graine)
            if cas is None:
                faits += bool(choisies)
                continue
            faits += 1
            R = random.Random(graine * 1009 + 20261112)  # modifications : propres à chaque cas (rejouables seules)
            with self.subTest(graine=graine), transaction.atomic():
                CF._executer(cas, [])  # construit le cas et le calcule (deux passages)
                compte["arbres"] = compte.get("arbres", 0) + self.arbre_change(random.Random(graine * 31 + 7), cas)
                self.modifications(R, cas, graine, compte)
                transaction.set_rollback(True)
        if os.environ.get("PROBANT_CALCUL_CIBLE_CAS"):
            print(f"\nrecalcul ciblé : {compte}")
        # le test n'est pas vide : la plupart des recalculs ont bien été ciblés
        self.assertGreater(compte["cibles"], compte["pas"] // 2)

    def arbre_change(self, R, cas):
        """Après la clôture : organisations déplacées, créées, fermées, puis une campagne clôturée rouverte en gardant
        les chiffres de l'époque (arbre de sa clôture). Renvoie 1 si c'est fait (tirage propre : les modifications de
        chaque cas restent celles d'avant)."""
        from .administration import changer_statut

        closes = list(Campagne.objects.filter(statut=Campagne.Statut.CLOTUREE).select_related("periode").order_by("pk"))
        if not closes or R.random() < 0.25:
            return 0
        orgs = {o.nom: o for o in Organisation.objects.order_by("pk")}
        rangs = {o["id"]: o["rank"] for o in cas["orgs"]}
        for _ in range(R.randint(2, 4)):
            feuilles = [o for o in orgs.values() if o.parent_id and not any(x.parent_id == o.id for x in orgs.values())]
            t = R.random()
            if t < 0.5 and feuilles:
                o = R.choice(feuilles)
                parents = [x for x in orgs.values() if rangs[x.nom] < rangs[o.nom] and x.id != o.parent_id and x.actif]
                if parents:
                    o.parent = R.choice(parents)
                    o.save()
            elif t < 0.8:
                r = R.randint(2, cas["levels"])
                parents = [x for x in orgs.values() if rangs[x.nom] < r and x.actif]
                if parents:
                    nom = f"N{len(orgs)}"
                    orgs[nom] = Organisation.objects.create(nom=nom, niveau_id=f"N{r}", parent=R.choice(parents))
                    rangs[nom] = r
                    cas["orgs"].append(dict(id=nom, rank=r, parent=orgs[nom].parent.nom, active=True, closed=None))
            elif feuilles:
                o = R.choice(feuilles)
                o.actif, o.date_desactivation = False, datetime.date(2020, 1, 1)
                o.save()
        C.recalculer_en_cours()
        changer_statut(None, R.choice(closes), "rouvrir", garder=True)
        return 1

    def modifications(self, R, cas, graine, compte):
        import calculation_fuzz as CF

        orgs = {o.nom: o for o in Organisation.objects.select_related("niveau")}
        rangs = {o["id"]: o["rank"] for o in cas["orgs"]}
        kpis = {k.code: k for k in KPI.objects.select_related("type_saisie") if k.actif}
        campagnes = list(Campagne.objects.select_related("periode"))
        libres = [c.periode for c in campagnes if not C.figee(c.periode)]
        figees = [c.periode for c in campagnes if C.figee(c.periode)]

        def ouvertes(p):
            return [o for o in orgs.values() if C.ouverte(o, p)]

        def case_saisie(p):
            """(KPI, organisation) d'une case qui se saisit : du niveau du KPI, au-dessus (option) ou paramètre hérité."""
            saisis = [k for k in kpis.values() if not k.est_calcule]
            for _ in range(20):
                k = R.choice(saisis)
                rk = int(k.granularite_id[1:])
                possibles = [o for o in ouvertes(p) if rangs[o.nom] == rk or (k.est_herite and rangs[o.nom] > rk)
                             or (k.saisie_au_dessus and rangs[o.nom] < rk)]
                if possibles:
                    return k, R.choice(possibles)
            return None, None

        def valeur(k):
            fmt = {"oui_non": "oui_non", "liste": "liste", "texte": "texte"}.get(k.type_reponse.format if k.type_reponse_id else "",
                                                                               "pourcentage" if k.est_pourcentage else "nombre")
            return CF._champs(CF._valeur_au_hasard(R, {"fmt": fmt}, 0.15))

        def poser(p, k, o, origine, statut, champs):
            """La modification, rejouable (sans signal : les recalculs sont lancés à la main)."""
            def appliquer():
                if not Reponse.objects.filter(periode=p, kpi=k, organisation=o).update(origine=origine, statut=statut, **champs):
                    Reponse.objects.bulk_create([Reponse(periode=p, kpi=k, organisation=o, origine=origine, statut=statut,
                                                         **champs)])
            return appliquer

        def maj(pk, **champs):
            return lambda: Reponse.objects.filter(pk=pk).update(**champs)

        for pas in range(self.PAS):
            t = R.random()
            p = R.choice(libres) if libres and (t < 0.92 or not figees) else R.choice(figees or libres)
            if p in figees:  # import d'historique dans une campagne clôturée
                k, o = case_saisie(p)
                if k is None:
                    continue
                appliquer, kpi_ids, mod = poser(p, k, o, Reponse.Origine.IMPORT, Reponse.Statut.VALIDE, valeur(k)), [k.code], {o.id}
            elif t < 0.45:  # saisie, N/A
                k, o = case_saisie(p)
                if k is None:
                    continue
                appliquer, kpi_ids, mod = poser(p, k, o, Reponse.Origine.SAISIE, Reponse.Statut.BROUILLON, valeur(k)), [k.code], {o.id}
            elif t < 0.62:  # effacement ou validation d'une saisie existante
                r = list(Reponse.objects.filter(periode=p, origine=Reponse.Origine.SAISIE, kpi__in=list(kpis)).order_by("pk"))
                if not r:
                    continue
                r = R.choice(r)
                appliquer = maj(r.pk, valeur=None, texte="", non_applicable=False, statut=Reponse.Statut.A_SAISIR) \
                    if t < 0.55 else maj(r.pk, statut=Reponse.Statut.VALIDE)
                kpi_ids, mod = [r.kpi_id], {r.organisation_id}
            elif t < 0.75:  # valeur forcée (KPI calculé), ou retour au calcul
                forcees = list(Reponse.objects.filter(periode=p, origine=Reponse.Origine.FORCEE, kpi__in=list(kpis)).order_by("pk"))
                if forcees and R.random() < 0.4:
                    r = R.choice(forcees)
                    appliquer = maj(r.pk, origine=Reponse.Origine.CALCUL, statut=Reponse.Statut.CALCULE)
                    kpi_ids, mod = [r.kpi_id], {r.organisation_id}
                else:
                    calcules = [k for k in kpis.values() if k.est_calcule]
                    if not calcules:
                        continue
                    k = R.choice(calcules)
                    possibles = [o for o in ouvertes(p) if rangs[o.nom] <= int(k.granularite_id[1:])]
                    if not possibles:
                        continue
                    o = R.choice(possibles)
                    champs = valeur(k) if R.random() < 0.3 else CF._champs(CF._nombre(R))
                    if champs["texte"]:
                        champs = CF._champs("7")
                    appliquer = poser(p, k, o, Reponse.Origine.FORCEE, Reponse.Statut.VALIDE, champs)
                    kpi_ids, mod = [k.code], {o.id}
            else:  # lot de saisies dans une période (paquet d'import : un recalcul en fin de paquet)
                etapes, kpi_ids, mod = [], set(), set()
                for _ in range(R.randint(2, 5)):
                    k, o = case_saisie(p)
                    if k is not None:
                        etapes.append(poser(p, k, o, Reponse.Origine.SAISIE, Reponse.Statut.BROUILLON, valeur(k)))
                        kpi_ids.add(k.code)
                        mod.add(o.id)
                if not etapes:
                    continue
                appliquer, kpi_ids = (lambda etapes=etapes: [e() for e in etapes]), sorted(kpi_ids)
            touchees = self.comparer(appliquer, p, kpi_ids, mod, f"graine {graine}, pas {pas}")
            compte["pas"] += 1
            compte["cibles"] += touchees is not None


class OrganisationsToucheesTests(TestCase):
    """La règle elle-même, sur un petit arbre : ancêtres ; descendants pour un paramètre hérité ; recalcul complet dans
    le doute."""

    def setUp(self):
        self.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.p = Organisation.objects.create(nom="Pays", niveau_id=Niveau.COUNTRY, parent=self.g)
        self.p2 = Organisation.objects.create(nom="Pays 2", niveau_id=Niveau.COUNTRY, parent=self.g)
        self.e1 = Organisation.objects.create(nom="E1", niveau_id=Niveau.ENTITY, parent=self.p)
        self.e2 = Organisation.objects.create(nom="E2", niveau_id=Niveau.ENTITY, parent=self.p2)
        self.s1 = Organisation.objects.create(nom="S1", niveau_id=Niveau.SITE, parent=self.e1)
        KPI.objects.create(code="A", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY, methode_agregation="Somme")
        KPI.objects.create(code="FE", type_saisie_id="FE", granularite_id=Niveau.COUNTRY, methode_agregation="Aucune")

    def test_ancetres_seulement(self):
        self.assertEqual(C.organisations_touchees(["A"], {self.e1.id}), {self.e1.id, self.p.id, self.g.id})

    def test_parametre_herite_descend(self):
        self.assertEqual(C.organisations_touchees(["FE"], {self.p.id}), {self.g.id, self.p.id, self.e1.id, self.s1.id})

    def test_dans_le_doute_tout(self):
        self.assertIsNone(C.organisations_touchees(None, {self.e1.id}))
        self.assertIsNone(C.organisations_touchees(["A"], None))
        self.assertIsNone(C.organisations_touchees(["A"], {987654}))  # organisation inconnue
        self.assertIsNone(C.organisations_touchees(["FE"], {self.g.id}))  # tout l'arbre : recalcul complet

    def test_organisation_fermee_qui_change_de_statut_tout_est_refait(self):
        import datetime as dt

        from .models import Campagne

        c = Campagne.objects.create(exercice=2026, statut=Campagne.Statut.OUVERTE)
        self.e1.actif, self.e1.date_desactivation = False, dt.date(2026, 6, 30)  # fermée pendant la période
        self.e1.save()
        tous = sorted(KPI.objects.values_list("code", flat=True))
        self.assertEqual(C.kpis_a_refaire(["A"], {self.e2.id}, c.periode), ["A"])  # lignée sans organisation fermée
        Reponse.objects.bulk_create([Reponse(periode=c.periode, kpi_id="A", organisation=self.e1, valeur=1)])
        # première valeur de la branche fermée : elle entre dans les totaux de tous les KPI au-dessus
        self.assertEqual(sorted(C.kpis_a_refaire(["A"], {self.e1.id}, c.periode)), tous)
        self.assertEqual(sorted(C.kpis_a_refaire(["A"], {self.s1.id}, c.periode)), tous)  # sous la fermée aussi
        Reponse.objects.bulk_create([Reponse(periode=c.periode, kpi_id="FE", organisation=self.s1, valeur=2)])
        self.assertEqual(C.kpis_a_refaire(["A"], {self.e1.id}, c.periode), ["A"])  # déjà d'autres valeurs : rien ne change


class RecalculCibleArbresDifferentsTests(TestCase):
    """Recalcul ciblé × arbre gardé × formules d'une autre période. 2024 est clos, E2
    passe de Pays à Pays 2, puis 2024 est rouvert en gardant les chiffres de l'époque (arbre de la clôture : E2 sous
    Pays) ; 2025 suit l'arbre d'aujourd'hui (E2 sous Pays 2). Une case d'une période lit la même organisation dans
    l'autre période ; le ciblage doit donc partir des organisations touchées dans l'arbre de la période corrigée, puis
    les refermer vers le haut dans l'arbre de la période refaite. Avant, il partait de l'arbre de la période refaite :
    les chiffres restaient faux jusqu'au recalcul complet suivant. Données inventées."""

    FIN = datetime.date.today() + datetime.timedelta(days=30)

    def setUp(self):
        from referentiel.composition import composer
        from referentiel.models import Referentiel, Utilisateur

        self.admin = Utilisateur.objects.create(username="admin", email="a@exemple.test", role=Utilisateur.Role.ADMIN)
        self.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.p = Organisation.objects.create(nom="Pays", niveau_id=Niveau.COUNTRY, parent=self.g)
        self.p2 = Organisation.objects.create(nom="Pays 2", niveau_id=Niveau.COUNTRY, parent=self.g)
        self.e1 = Organisation.objects.create(nom="E1", niveau_id=Niveau.ENTITY, parent=self.p)
        self.e2 = Organisation.objects.create(nom="E2", niveau_id=Niveau.ENTITY, parent=self.p)
        self.e3 = Organisation.objects.create(nom="E3", niveau_id=Niveau.ENTITY, parent=self.p2)
        KPI.objects.create(code="EFF", libelle="Eff", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY, methode_agregation="Somme")
        KPI.objects.create(code="FE", libelle="FE", type_saisie_id="FE", granularite_id=Niveau.COUNTRY, methode_agregation="Aucune")
        KPI.objects.create(code="EVOL", libelle="Evol", type_saisie_id="Calculé", granularite_id=Niveau.ENTITY,
                           methode_agregation="Formule", formule="[EFF]-[EFF@N-1]")
        KPI.objects.create(code="CO2", libelle="CO2", type_saisie_id="Calculé", granularite_id=Niveau.ENTITY,
                           methode_agregation="Somme", formule="[EFF]*[FE@N-1]")
        KPI.objects.create(code="FUT", libelle="Fut", type_saisie_id="Calculé", granularite_id=Niveau.ENTITY,
                           methode_agregation="Formule", formule="[EFF@2025]-[EFF]")  # 2024 lit 2025
        self.ref = Referentiel.objects.create(code="RAP", nom="Rapport", ordre=1)
        composer({"EFF": ["S"], "FE": ["S"], "EVOL": ["S"], "CO2": ["S"], "FUT": ["S"]}, self.ref)

    def construire(self, garder=True):
        from . import periodes as P
        from .administration import changer_statut

        def rep(c, kpi, o, v):
            Reponse.objects.create(periode=c.periode, kpi_id=kpi, organisation=o, valeur=v, statut=Reponse.Statut.VALIDE)

        c24, _ = P.campagne(self.ref, datetime.date(2024, 1, 1), statut=Campagne.Statut.OUVERTE, date_fin_saisie=self.FIN)
        c25, _ = P.campagne(self.ref, datetime.date(2025, 1, 1), statut=Campagne.Statut.OUVERTE, date_fin_saisie=self.FIN)
        for kpi, o, v in (("EFF", self.e1, 1), ("EFF", self.e2, 2), ("EFF", self.e3, 3), ("FE", self.p, 2), ("FE", self.p2, 3)):
            rep(c24, kpi, o, v)
        for kpi, o, v in (("EFF", self.e1, 10), ("EFF", self.e2, 20), ("EFF", self.e3, 30), ("FE", self.p, 7), ("FE", self.p2, 7)):
            rep(c25, kpi, o, v)
        C.recalculer(c24)
        C.recalculer(c25)
        changer_statut(self.admin, c24, "cloturer")
        Organisation.objects.filter(pk=self.e2.pk).update(parent=self.p2)  # déplacée après la clôture de 2024
        C.recalculer_en_cours()
        if garder is not None:
            changer_statut(self.admin, Campagne.objects.get(pk=c24.pk), "rouvrir", garder=garder)
        return Campagne.objects.get(pk=c24.pk), Campagne.objects.get(pk=c25.pk)

    def lue(self, c, kpi, o):
        return Reponse.objects.get(periode=c.periode, kpi_id=kpi, organisation=o).valeur

    def assertComme_recalcul_complet(self, c, kpi, orgs):
        calc = C.Calculateur(c)
        for o in orgs:
            self.assertEqual(self.lue(c, kpi, o), calc.valeur(kpi, o.pk), f"{kpi} {o.nom} {c.periode}")

    def test_formule_refaite_au_dessus_lit_l_annee_figee(self):
        """(a) EVOL = [EFF] - [EFF@N-1] refait au-dessus : correction de EFF de E2 en 2024 (2 -> 7)."""
        from . import saisie as S

        c24, c25 = self.construire()
        self.assertEqual(self.lue(c25, "EVOL", self.p), 10 - 3)  # Pays : 10 (E1) - 3 (E1 + E2 de 2024)
        S.enregistrer(self.admin, c24, KPI.objects.get(code="EFF"), self.e2, "7", False, "correction")
        self.assertEqual(self.lue(c24, "EFF", self.p), 8)  # arbre de l'époque : E1 + E2
        self.assertEqual(self.lue(c25, "EVOL", self.p), 2)  # avant : 7, jusqu'au recalcul complet suivant
        self.assertEqual(self.lue(c25, "EVOL", self.p2), 50 - 3)
        self.assertEqual(self.lue(c25, "EVOL", self.g), 60 - 11)
        self.assertComme_recalcul_complet(c25, "EVOL", (self.e1, self.e2, self.e3, self.p, self.p2, self.g))

    def test_parametre_herite_lu_par_n_1(self):
        """(b) CO2 = [EFF] * [FE@N-1] : correction du facteur de Pays en 2024 (2 -> 4) ; E2 le lit dans l'arbre de 2024."""
        from . import saisie as S

        c24, c25 = self.construire()
        self.assertEqual(self.lue(c25, "CO2", self.e2), 40)
        S.enregistrer(self.admin, c24, KPI.objects.get(code="FE"), self.p, "4", False, "correction")
        self.assertEqual(self.lue(c25, "CO2", self.e2), 80)  # avant : 40
        self.assertEqual(self.lue(c25, "CO2", self.p2), 80 + 30 * 3)
        self.assertEqual(self.lue(c25, "CO2", self.e1), 40)
        self.assertComme_recalcul_complet(c25, "CO2", (self.e1, self.e2, self.e3, self.p, self.p2, self.g))

    def test_saisie_de_l_annee_courante_lue_par_l_annee_gardee(self):
        """Autre sens : 2024, rouvert « garder », lit 2025 par [EFF@2025]. Une saisie de E2 en 2025 refait E2 et ses
        ancêtres de l'époque en 2024 (Pays), et Pays 2, dont la formule refaite au-dessus lit Pays 2 en 2025 (avant :
        oublié). Comportement voulu par ``ciblage`` (seules les organisations touchées, jamais toute la période)."""
        from . import saisie as S

        c24, c25 = self.construire()
        S.enregistrer(self.admin, c25, KPI.objects.get(code="EFF"), self.e2, "25", False, "")
        self.assertEqual(self.lue(c24, "FUT", self.e2), 25 - 2)
        self.assertEqual(self.lue(c24, "FUT", self.p), 10 - 3)  # Pays : E1 en 2025 (aujourd'hui) - E1 + E2 de l'époque
        self.assertEqual(self.lue(c24, "FUT", self.p2), (30 + 25) - 3)  # avant : 50 - 3, resté faux
        self.assertEqual(self.lue(c24, "FUT", self.e1), 10 - 1)  # inchangée

    def test_exercice_clos_jamais_reecrit_par_une_saisie_d_une_autre_annee(self):
        """Un exercice clos (non rouvert) n'est jamais réécrit par une saisie d'une autre année, même s'il la cite
        ([EFF@2025]) : toutes ses cases restent telles qu'enregistrées."""
        from . import saisie as S

        c24, c25 = self.construire(garder=None)
        avant = sorted(Reponse.objects.filter(periode=c24.periode).values_list("kpi_id", "organisation_id", "valeur",
                                                                               "statut", "message_calcul"))
        S.enregistrer(self.admin, c25, KPI.objects.get(code="EFF"), self.e2, "25", False, "")
        S.enregistrer(self.admin, c25, KPI.objects.get(code="FE"), self.p2, "9", False, "")
        C.recalculer(c25, ["EFF", "FE"], organisations=[self.e2.id, self.e1.id, self.p2.id])
        apres = sorted(Reponse.objects.filter(periode=c24.periode).values_list("kpi_id", "organisation_id", "valeur",
                                                                               "statut", "message_calcul"))
        self.assertEqual(avant, apres)
        self.assertEqual(self.lue(c25, "EFF", self.p2), 55)  # 2025 a bien suivi

    def test_ciblage_dans_chaque_arbre(self):
        """La règle elle-même : les organisations touchées dans l'arbre de la période corrigée sont refermées vers le
        haut dans l'arbre de la période refaite."""
        c24, c25 = self.construire()
        epoque, aujourdhui = C.lignes_arbre(c24.periode), C.lignes_arbre(None)
        self.assertEqual(epoque[self.e2.id][0], self.p.id)
        self.assertEqual(aujourdhui[self.e2.id][0], self.p2.id)
        cibles = C.cibles_par_arbre(["EFF"], [self.e2.id], [epoque, aujourdhui])
        self.assertEqual(cibles[0], {self.e2.id, self.p.id, self.g.id, self.p2.id})
        self.assertEqual(cibles[1], {self.e2.id, self.p2.id, self.g.id, self.p.id})
        # un seul arbre : la règle d'avant (``organisations_touchees``)
        self.assertEqual(C.cibles_par_arbre(["EFF"], [self.e1.id], [aujourdhui])[0],
                         C.organisations_touchees(["EFF"], [self.e1.id], aujourdhui))
