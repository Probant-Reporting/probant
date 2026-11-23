"""Certificat de clôture partiel d'un auditeur limité à des organisations : chaque chiffre comparé à un calcul direct sur ses
organisations (``Utilisateur.orgs_permises``, la règle des autres écrans), aucune fuite hors périmètre dans la page,
empreintes (complète inchangée, partielle stable et différente), droits des autres rôles, lecture seule.

Équivalence : sur des valeurs tirées au hasard (graine fixe), le certificat complet donne exactement ce que donnait le
calcul d'avant (copie ci-dessous de l'ancienne empreinte et de l'ancien compte des valeurs)."""
import hashlib
import json
import random
from collections import Counter
from decimal import Decimal

from django.core.files.base import ContentFile
from django.urls import reverse


from referentiel.models import KPI, Attribution, Niveau, Organisation, Utilisateur

from . import administration as A
from . import certificat_cloture as CE
from . import saisie as S
from .aides_tests.lecture_seule import Base
from .models import Alerte, Campagne, DemandeForcage, Journal, Preuve, Reponse

D = Decimal
PDF = b"%PDF-1.4\n1 0 obj\n<< >>\nendobj\n"
CACHES = ("Sommet Invisible Kappa", "Pays Invisible Zeta", "Filiale Invisible Omega")


def ancienne_empreinte(campagne):
    """Empreinte telle que la calculait le certificat avant le certificat partiel (copie figée, pour l'équivalence)."""
    codes = S.codes_campagne(campagne)
    retenus = None if codes is None else codes[1]
    lignes = []
    for kpi, org, valeur, na, texte in Reponse.objects.filter(periode=campagne.periode).values_list(
            "kpi_id", "organisation__code", "valeur", "non_applicable", "texte"):
        if retenus is not None and kpi not in retenus:
            continue
        if valeur is None and not na and not texte:
            continue
        lignes.append((kpi, org, CE._nombre_stable(valeur), bool(na), texte or ""))
    lignes.sort(key=lambda x: (x[0], x[1]))
    h = hashlib.sha256()
    entete = ["probant-certificat-1", campagne.referentiel_id, campagne.periode.debut.isoformat(), campagne.periode.fin.isoformat()]
    h.update(json.dumps(entete, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    for l in lignes:
        h.update(b"\n")
        h.update(json.dumps(list(l), ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    return h.hexdigest(), len(lignes)


class AvecPartiel(Base):
    """Arbre : Sommet › Pays (E1, E2) et Sommet › Pays Invisible › Filiale Invisible. L'auditeur limité voit Pays et ses
    entités ; le sommet et l'autre branche lui sont cachés."""

    def setUp(self):
        super().setUp()
        self.g.nom = CACHES[0]
        self.g.save()
        self.p2 = Organisation.objects.create(nom=CACHES[1], niveau_id=Niveau.COUNTRY, parent=self.g)
        self.e3 = Organisation.objects.create(nom=CACHES[2], niveau_id=Niveau.ENTITY, parent=self.p2)
        S.enregistrer(self.admin, self.c, self.eff, self.e3, "7777", False, "")
        S.enregistrer(self.admin, self.c, self.taux, self.e3, "12", False, "")
        S.valider(self.contrib, self.c, self.eff, self.e1)
        r1 = Reponse.objects.get(periode=self.c.periode, kpi=self.eff, organisation=self.e1)
        r3 = Reponse.objects.get(periode=self.c.periode, kpi=self.eff, organisation=self.e3)
        for r in (r1, r3, r3):
            Preuve.objects.create(reponse=r, fichier=ContentFile(PDF, name="f.pdf"), nom_fichier="f.pdf", taille=len(PDF),
                                  depose_par=self.admin)
        Alerte.objects.create(campagne=self.c, kpi=self.eff, organisation=self.e2, controle=Alerte.Controle.FORMAT,
                              gravite=Alerte.Gravite.ALERTE, message="Alerte visible Beta")
        Alerte.objects.create(campagne=self.c, kpi=self.eff, organisation=self.e3, controle=Alerte.Controle.FORMAT,
                              gravite=Alerte.Gravite.BLOQUANTE, message="Alerte invisible Gamma")
        Alerte.objects.create(campagne=self.c, kpi=self.taux, organisation=self.e3, controle=Alerte.Controle.HISTORIQUE,
                              message="Alerte invisible Delta", statut=Alerte.Statut.CORRIGEE)
        A.changer_statut(self.admin, self.c, "cloturer")
        self.c.refresh_from_db()
        self.url = reverse("collecte:certificat_cloture", args=[self.c.pk])
        self.limite = Utilisateur.objects.create(username="audit-limite", email="audit-limite@exemple.test",
                                                 role=Utilisateur.Role.AUDITEUR)
        self.limite.perimetre_lecture.add(self.p)
        self.limite = Utilisateur.objects.get(pk=self.limite.pk)
        self.permises = {self.p.id, self.e1.id, self.e2.id}

    def page(self, user, langue="en"):
        self.client.force_login(user)
        self.client.post(reverse("langue"), {"langue": langue})
        return self.client.get(self.url)


class PerimetrePartielTests(AvecPartiel):
    def test_meme_regle_que_les_autres_ecrans(self):
        self.assertEqual(CE.organisations_permises(self.limite), self.limite.orgs_permises())
        self.assertEqual(CE.organisations_permises(self.limite), self.permises)
        self.assertIsNone(CE.organisations_permises(self.admin))
        self.assertIsNone(CE.organisations_permises(self.auditeur))

    def test_chaque_chiffre_egal_au_calcul_direct(self):
        d = CE.construire(self.limite, self.c)
        self.assertTrue(d["partiel"])
        # périmètre par niveau : organisations permises de l'arbre
        attendu = Counter(Organisation.objects.filter(id__in=self.permises).values_list("niveau_id", flat=True))
        self.assertEqual(sorted(t for _, t, _ in d["par_niveau"]), sorted(attendu.values()))
        self.assertEqual((d["nb_orgs"], d["nb_ouvertes"]), (3, 3))
        self.assertEqual(d["nb_campagne"], 6)  # seul chiffre de toute la campagne : M
        self.assertEqual(d["sommets"], ["Pays"])
        # valeurs et preuves : réponses non vides des organisations permises
        codes = S.codes_campagne(self.c)
        reps = [r for r in Reponse.objects.filter(periode=self.c.periode, organisation_id__in=self.permises)
                if (codes is None or r.kpi_id in codes[1]) and (r.valeur is not None or r.non_applicable or r.texte)]
        v = d["valeurs"]
        self.assertEqual(v["total"], len(reps))
        self.assertEqual(v["validees"], sum(r.statut == Reponse.Statut.VALIDE for r in reps))
        self.assertEqual(v["calculees"], sum(r.origine in (Reponse.Origine.CALCUL, Reponse.Origine.AGREGATION, Reponse.Origine.CUMUL)
                                             for r in reps))
        self.assertEqual(d["preuves"], Preuve.objects.filter(reponse__periode=self.c.periode,
                                                             reponse__organisation_id__in=self.permises).count())
        self.assertEqual(d["preuves"], 1)
        # remplissage : les lignes de l'administrateur, gardées sur les organisations permises
        plan_total = CE.remplissage(self.admin, self.c)
        from referentiel.plans import Plan

        plan = Plan(self.c.referentiel)
        lignes = [l for l in S.lignes(self.admin, self.c, plan=plan, legere=True) if l.organisation.id in self.permises]
        direct = S.tableau_de_bord(lignes, plan)["total"]
        c = d["remplissage"]
        self.assertEqual((c.total, c.valide, c.brouillon, c.a_saisir), (direct.total, direct.valide, direct.brouillon, direct.a_saisir))
        self.assertLess(c.total, plan_total.total)
        # alertes : celles des organisations permises
        n = d["alertes"]
        alertes = list(Alerte.objects.filter(campagne=self.c, organisation_id__in=self.permises))
        self.assertEqual(n["total"], len(alertes))
        self.assertEqual(n["ouvertes"], sum(a.statut in Alerte.A_TRAITER for a in alertes))
        self.assertEqual([a["message"] for a in d["alertes_ouvertes"]], ["Alerte visible Beta"])

    def test_aucun_total_d_un_ancetre_cache(self):
        """Limité à E1 : le total du pays (E1 + E2) n'est ni compté ni haché, comme la Visualisation qui ne le lui montre pas."""
        u = Utilisateur.objects.create(username="audit-e1", email="audit-e1@exemple.test", role=Utilisateur.Role.AUDITEUR)
        u.perimetre_lecture.add(self.e1)
        u = Utilisateur.objects.get(pk=u.pk)
        self.assertTrue(Reponse.objects.filter(periode=self.c.periode, organisation=self.p).exclude(valeur=None).exists())
        d = CE.construire(u, self.c)
        self.assertEqual({x[1] for x in CE.lignes_empreinte(self.c, u.orgs_permises())}, {self.e1.code})
        self.assertEqual((d["nb_orgs"], d["sommets"]), (1, ["E1"]))
        self.assertEqual(d["valeurs"]["total"], Reponse.objects.filter(periode=self.c.periode, organisation=self.e1)
                         .exclude(valeur=None, non_applicable=False, texte="").count())

    def test_organisation_hors_campagne(self):
        """Une organisation choisie qui n'existe pas dans l'arbre de la période : rien n'est compté, la page le dit."""
        u = Utilisateur.objects.create(username="audit-neuf", email="audit-neuf@exemple.test", role=Utilisateur.Role.AUDITEUR)
        neuve = Organisation.objects.create(nom="Nouvelle", niveau_id=Niveau.ENTITY, parent=None)
        u.perimetre_lecture.add(neuve)
        u = Utilisateur.objects.get(pk=u.pk)
        Organisation.objects.filter(pk=neuve.pk).update(date_ouverture=self.c.periode.fin.replace(year=self.c.periode.fin.year + 1))
        d = CE.construire(u, self.c)
        self.assertEqual(d["valeurs"]["total"], 0)
        self.client.force_login(u)
        self.client.post(reverse("langue"), {"langue": "en"})
        self.assertEqual(self.client.get(self.url).status_code, 200)


class FuitePartielleTests(AvecPartiel):
    def test_page_partielle_sans_rien_hors_perimetre(self):
        for langue in ("en", "fr", "de"):
            with self.subTest(langue=langue):
                rep = self.page(self.limite, langue)
                self.assertEqual(rep.status_code, 200)
                t = rep.content.decode()
                for nom in CACHES + ("Alerte invisible Gamma", "Alerte invisible Delta", "7777", "7 777"):
                    self.assertNotIn(nom, t)
                complete = CE.empreinte(self.c)[0]
                for i in range(0, 64, 16):
                    self.assertNotIn(complete[i:i + 16], t)
                self.assertIn("Alerte visible Beta", t)
                self.assertEqual(t.count('data-partiel'), 2)  # en tête de la page et dans l'en-tête répété à l'impression

    def test_mention_et_explication_en_anglais(self):
        t = self.page(self.limite).content.decode()
        self.assertIn("Partial certificate: 3 of 6 organisations", t)
        self.assertIn("It covers Pays and the organisations below them.", t)
        self.assertIn("It is different from the fingerprint of the full certificate", t)
        self.assertNotIn("suivi.certificat.", t)

    def test_certificat_complet_sans_mention(self):
        for u in (self.admin, self.auditeur):
            t = self.page(u).content.decode()
            self.assertNotIn("data-partiel", t)
            self.assertNotIn("Partial certificate", t)
            self.assertIn(CACHES[2], t)  # alerte de la filiale listée (l'auditeur sans limite voit tout)


class EmpreintesPartiellesTests(AvecPartiel):
    def test_empreinte_complete_inchangee(self):
        attendu = ancienne_empreinte(self.c)
        self.assertEqual(CE.empreinte(self.c), attendu)
        for u in (self.admin, self.auditeur):
            d = CE.construire(u, self.c)
            self.assertEqual((d["empreinte"], d["nb_hachees"]), attendu)

    def test_empreinte_partielle_documentee_stable_et_differente(self):
        d = CE.construire(self.limite, self.c)
        self.assertEqual(CE.construire(self.limite, self.c)["empreinte"], d["empreinte"])
        self.assertNotEqual(d["empreinte"], CE.empreinte(self.c)[0])
        # calcul écrit à la main d'après docs/calculation_rules.md
        codes = S.codes_campagne(self.c)
        lignes = []
        for r in Reponse.objects.filter(periode=self.c.periode, organisation_id__in=self.permises).select_related("organisation"):
            if (codes is not None and r.kpi_id not in codes[1]) or (r.valeur is None and not r.non_applicable and not r.texte):
                continue
            lignes.append([r.kpi_id, r.organisation.code, None if r.valeur is None else format(r.valeur.normalize(), "f"),
                           r.non_applicable, r.texte])
        lignes.sort(key=lambda x: (x[0], x[1]))
        p = self.c.periode
        morceaux = [json.dumps(["probant-certificat-1-partiel", self.c.referentiel_id, p.debut.isoformat(), p.fin.isoformat(),
                                [self.p.code]], separators=(",", ":"), ensure_ascii=False)]
        morceaux += [json.dumps(l, separators=(",", ":"), ensure_ascii=False) for l in lignes]
        self.assertEqual(d["empreinte"], hashlib.sha256("\n".join(morceaux).encode("utf-8")).hexdigest())
        self.assertEqual(d["nb_hachees"], len(lignes))

    def test_une_valeur_cachee_ne_change_pas_l_empreinte_partielle(self):
        avant = CE.construire(self.limite, self.c)["empreinte"]
        Reponse.objects.filter(periode=self.c.periode, organisation=self.e3, kpi=self.eff).update(valeur=D("1"))
        self.assertEqual(CE.construire(self.limite, self.c)["empreinte"], avant)
        Reponse.objects.filter(periode=self.c.periode, organisation=self.e2, kpi=self.eff).update(valeur=D("41"))
        self.assertNotEqual(CE.construire(self.limite, self.c)["empreinte"], avant)

    def test_equivalence_sur_cas_generes(self):
        """Graine fixe : 30 tirages de valeurs, N/A et textes ; le certificat complet donne la même empreinte et les mêmes
        comptes que le calcul d'avant le certificat partiel."""
        hasard = random.Random(20261118)
        orgs = [self.e1, self.e2, self.e3, self.p, self.p2, self.g]
        for _ in range(30):
            # écrit sans passer par la saisie (ni recalcul ni signal) : seules les lignes lues par le certificat comptent
            for o in orgs:
                for k in (self.eff, self.taux, self.calc):
                    choix = hasard.random()
                    valeur = None if choix < 0.25 else D(hasard.randint(-500, 50000)) / D(10 ** hasard.randint(0, 3))
                    champs = {"valeur": valeur, "non_applicable": 0.25 <= choix < 0.3, "texte": "x" if choix > 0.95 else "",
                              "statut": hasard.choice([Reponse.Statut.VALIDE, Reponse.Statut.BROUILLON])}
                    if not Reponse.objects.filter(periode=self.c.periode, kpi=k, organisation=o).update(**champs):
                        Reponse.objects.bulk_create([Reponse(periode=self.c.periode, kpi=k, organisation=o, **champs)])
            self.assertEqual(CE.empreinte(self.c), ancienne_empreinte(self.c))
            nouveau = CE.valeurs(self.c)
            n = Counter()
            for r in Reponse.objects.filter(periode=self.c.periode):
                if r.valeur is None and not r.non_applicable and not r.texte:
                    continue
                n["total"] += 1
                n["validees"] += r.statut == Reponse.Statut.VALIDE
            self.assertEqual((nouveau[0]["total"], nouveau[0]["validees"]), (n["total"], n["validees"]))
            self.assertEqual(nouveau[1], Preuve.objects.filter(reponse__periode=self.c.periode).count())


class DroitsPartielsTests(AvecPartiel):
    def test_auditeur_limite_200_autres_roles_refuses(self):
        self.assertEqual(self.page(self.limite).status_code, 200)
        valideur = Utilisateur.objects.create(username="v2", email="v2@exemple.test", role=Utilisateur.Role.VALIDATEUR)
        Attribution.objects.create(kpi=self.eff, organisation=self.p, utilisateur=valideur, role=Attribution.Role.VALIDATEUR)
        lecteur_limite = Utilisateur.objects.create(username="l2", email="l2@exemple.test", role=Utilisateur.Role.LECTEUR)
        lecteur_limite.perimetre_lecture.add(self.p)
        for u in (self.contrib, valideur, self.lecteur, lecteur_limite):
            with self.subTest(u=u.username):
                self.assertEqual(self.page(u).status_code, 403)

    def test_envoi_refuse_et_rien_ecrit(self):
        self.page(self.limite)  # la langue choisie s'écrit au journal : avant de compter
        modeles = (Reponse, Journal, Alerte, Preuve, DemandeForcage, Campagne, Utilisateur, Attribution, KPI)
        avant = {m.__name__: m.objects.count() for m in modeles}
        etat = list(Reponse.objects.order_by("pk").values_list("pk", "valeur", "statut", "date_maj"))
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertEqual(self.client.post(self.url, {"action": "cloturer"}).status_code, 403)
        self.assertEqual({m.__name__: m.objects.count() for m in modeles}, avant)
        self.assertEqual(list(Reponse.objects.order_by("pk").values_list("pk", "valeur", "statut", "date_maj")), etat)

    def test_liste_dans_l_historique(self):
        self.client.force_login(self.limite)
        t = self.client.get(reverse("collecte:historique")).content.decode()
        self.assertIn(self.url, t)
