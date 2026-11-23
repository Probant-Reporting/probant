"""Page Journal d'un auditeur au périmètre restreint (échelle, lot D) : tous les comptes de la page (par type, par
personne, total lisible, entrées filtrées) lus en une seule requête groupée au lieu de quatre. Mêmes nombres que
l'ancienne construction, recopiée ici (035536f), sur des cas tirés au hasard à graine fixe : périmètres (dont vide),
exercices, organisations, types et personnes choisis ; entrées sur des réponses supprimées, sur des identifiants presque
justes, sur d'autres objets, sans auteur. Les pages de l'administrateur, de l'auditeur et des auditeurs restreints sont
aussi comparées à celles de l'ancienne construction."""
import datetime
import random
import re
from decimal import Decimal
from unittest import mock

from django.db.models import Count
from django.test import TestCase

from collecte import administration as A
from collecte import periodes as P
from collecte.models import Campagne, Journal, Reponse
from referentiel.models import KPI, Niveau, Organisation, Referentiel, Utilisateur

GRAINE = 20261114


def des_reponses_avant(journal, exercices, orgs, permises):
    """``journal_des_reponses`` d'origine (f6503ba) : la référence des entrées."""
    from django.db.models import CharField
    from django.db.models.functions import Cast

    reps = Reponse.objects.all() if permises is None else Reponse.objects.filter(organisation_id__in=permises)
    if exercices:
        reps = reps.filter(periode__debut__year__in=exercices)
    if orgs:
        reps = reps.filter(organisation_id__in=orgs)
    return journal.filter(objet="Reponse", objet_id__in=reps.annotate(_texte=Cast("pk", CharField())).values("_texte"))


def compteurs_avant(journal, actions, personnes, exercices, orgs, permises):
    """Ancienne construction de la vue (035536f) : total, puis qs filtré, puis quatre comptes séparés."""
    total = des_reponses_avant(journal, [], [], permises)
    qs = journal
    if actions:
        qs = qs.filter(action__in=actions)
    if personnes:
        qs = qs.filter(utilisateur_id__in=personnes)
    qs = des_reponses_avant(qs, exercices, orgs, permises)
    par_action = dict(total.values_list("action").annotate(n=Count("pk")))
    par_personne = dict(total.values_list("utilisateur_id").annotate(n=Count("pk")).order_by())
    return par_action, par_personne, total.count(), qs.count()


class JournalCompteursRestreintsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        h = random.Random(GRAINE)
        g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        cls.orgs = [Organisation.objects.create(nom=f"Filiale {i}", niveau_id=Niveau.ENTITY, parent=g, rang=i) for i in range(6)]
        k = KPI.objects.create(code="EFF", libelle="Effectif", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                               methode_agregation="Somme")
        k2 = KPI.objects.create(code="12", libelle="KPI au code numérique", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY)
        ref = Referentiel.objects.create(code="ANN", nom="Annuel", frequence="annee")
        cls.campagnes = [P.campagne(ref, datetime.date(an, 1, 1), statut=Campagne.Statut.CLOTUREE)[0] for an in (2023, 2024, 2025, 2026)]
        reps = [Reponse.objects.create(periode=c.periode, kpi=kk, organisation=o, valeur=Decimal(i), statut="valide")
                for i, (c, o, kk) in enumerate((c, o, kk) for c in cls.campagnes for o in cls.orgs for kk in (k, k2))]
        disparus = []
        for r in h.sample(reps, 4):
            reps.remove(r)
            disparus.append(r.pk)
            r.delete()
        cls.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN,
                                               first_name="Alice", is_staff=True, is_superuser=True)
        cls.autres = [Utilisateur.objects.create(username=f"u{i}", email=f"u{i}@exemple.test", first_name=f"Personne {i}")
                      for i in range(5)]
        cls.auditeur = Utilisateur.objects.create(username="auditeur", email="auditeur@exemple.test", role=Utilisateur.Role.AUDITEUR)
        cls.restreints = []
        for i, orgs in enumerate(([1, 2], [0], [3, 4, 5])):
            u = Utilisateur.objects.create(username=f"audit{i}", email=f"audit{i}@exemple.test", role=Utilisateur.Role.AUDITEUR)
            u.perimetre_lecture.set([cls.orgs[j] for j in orgs])
            cls.restreints.append(u)
        cls.actions = [a for f, _, acts in A.FAMILLES if f in A.FAMILLES_SAISIE for a in acts]
        autres_actions = ["reglage_kpi", "attribution", "action_inconnue"]
        lignes = []
        for _ in range(900):
            r = h.choice(reps)
            objet, oid = "Reponse", str(r.pk)
            tirage = h.random()
            if tirage < 0.05:
                oid = str(h.choice(disparus))
            elif tirage < 0.08:
                oid = h.choice([f"0{r.pk}", f" {r.pk}", f"{r.pk}x", "abc", ""])
            elif tirage < 0.12:
                objet = h.choice(["KPI", "Organisation", "Campagne"])
            action = h.choice(cls.actions) if h.random() < 0.85 else h.choice(autres_actions)
            lignes.append(Journal(utilisateur=h.choice(cls.autres + [None]), action=action, objet=objet, objet_id=oid,
                                  champ="valeur", avant=str(h.randint(0, 99)), apres=str(h.randint(0, 99))))
        Journal.objects.bulk_create(lignes)
        for i, j in enumerate(Journal.objects.order_by("pk")):  # dates distinctes : l'ordre de la page ne dépend que d'elles
            Journal.objects.filter(pk=j.pk).update(date=datetime.datetime(2023, 1, 1, tzinfo=datetime.timezone.utc)
                                                   + datetime.timedelta(hours=5 * i))

    def cas_tires(self, n):
        h = random.Random(GRAINE + 1)
        ids = [o.pk for o in self.orgs]
        personnes = [str(u.pk) for u in self.autres] + ["999999"]
        for _ in range(n):
            permises = set(h.sample(ids, h.randint(0, len(ids))))
            exercices = h.sample(["2023", "2024", "2025", "2026", "1999"], h.choice([0, 0, 1, 2]))
            orgs = [str(x) for x in h.sample(ids, h.choice([0, 0, 1, 2]))]
            actions = h.sample(self.actions, h.choice([0, 0, 1, 3]))
            choisies = h.sample(personnes, h.choice([0, 0, 1, 2]))
            yield actions, choisies, exercices, orgs, permises

    def test_memes_comptes_que_l_ancienne_construction(self):
        journal = Journal.objects.filter(action__in=self.actions)
        vus_filtres = 0
        for actions, personnes, exercices, orgs, permises in self.cas_tires(150):
            with self.subTest(actions=actions, personnes=personnes, exercices=exercices, orgs=orgs, permises=permises):
                avant = compteurs_avant(journal, actions, personnes, exercices, orgs, permises)
                self.assertEqual(A.journal_compteurs_restreints(journal, actions, personnes, exercices, orgs, permises), avant)
                vus_filtres += 0 < avant[3] < avant[2]
        self.assertGreater(vus_filtres, 30)  # le jeu fait varier les comptes filtrés, pas seulement 0 ou tout

    def page(self, u, url):
        self.client.force_login(u)
        r = self.client.get(url, secure=True)
        self.assertEqual(r.status_code, 200, url)
        html = re.sub(r'nonce="[^"]*"', "", r.content.decode())
        return re.sub(r"\b[A-Za-z0-9]{64}\b", "<jeton>", html)

    def test_memes_pages_pour_tous_les_roles(self):
        o = self.orgs
        u1 = self.autres[1].pk
        urls = ["", "?exercice=2025", "?exercice=2024&exercice=2026", f"?org={o[0].pk}", f"?org={o[1].pk}&exercice=2025",
                "?q=12", "?famille=saisie&exercice=2025", "?famille=preuve&famille=coherence", "?vue=admin",
                "?tri-journal=auteur&exercice=2026", f"?personne={u1}&org={o[2].pk}", f"?personne={u1}&famille=saisie"]
        comptes = [(self.admin, "/administration/journal/"), (self.auditeur, "/historique/")]
        comptes += [(u, "/historique/") for u in self.restreints]
        for u, chemin in comptes:
            for q in urls:
                with self.subTest(personne=u.username, url=q):
                    with mock.patch.object(A, "journal_compteurs_restreints", compteurs_avant):
                        avant = self.page(u, chemin + q)
                    self.assertEqual(self.page(u, chemin + q), avant)

    def test_une_seule_lecture_groupee_pour_l_auditeur_restreint(self):
        self.client.force_login(self.restreints[0])
        with mock.patch.object(A, "journal_compteurs_restreints", wraps=A.journal_compteurs_restreints) as espion:
            self.assertEqual(self.client.get("/historique/?exercice=2025", secure=True).status_code, 200)
        espion.assert_called_once()
