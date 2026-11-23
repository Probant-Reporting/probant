"""Page Journal : filtres par exercice et par organisation, périmètre de l'auditeur, comptes par personne et textes
traduits, réécrits pour la grosse base (P-A7). Mêmes entrées, mêmes comptes, même page que l'ancienne écriture.

Jeu tiré au hasard (graine fixe) : réponses de trois exercices dans quatre organisations, dont une supprimée ensuite ;
entrées du journal sur ces réponses (types de la vue « saisies » et de la vue « administration », type inconnu), sur un
identifiant de réponse disparu, sur des identifiants presque justes (« 012 », « 12 », « 12x », « abc »), sur d'autres
objets qui portent le même numéro (un KPI « 12 »), avec ou sans auteur. Les anciennes fonctions sont recopiées ici telles
qu'elles étaient (f6503ba) et servent de référence."""
import datetime
import random
import re
from decimal import Decimal
from unittest import mock

from django.db.models import CharField, Count
from django.db.models.functions import Cast
from django.test import TestCase

from collecte import administration as A
from collecte.models import Campagne, Journal, Reponse
from collecte import periodes as P
from parametres import libelles as LB
from parametres import langues as L
from parametres.libelles import libelle
from referentiel.models import KPI, Niveau, Organisation, Referentiel, Utilisateur

GRAINE = 1113


def des_reponses_avant(journal, exercices, orgs, permises):
    reps = Reponse.objects.all() if permises is None else Reponse.objects.filter(organisation_id__in=permises)
    if exercices:
        reps = reps.filter(periode__debut__year__in=exercices)
    if orgs:
        reps = reps.filter(organisation_id__in=orgs)
    return journal.filter(objet="Reponse", objet_id__in=reps.annotate(_texte=Cast("pk", CharField())).values("_texte"))


def par_personne_avant(total, actions_vue, restreint=False):
    return dict(total.values_list("utilisateur_id").annotate(n=Count("pk")))


def motifs_avant():
    sortie = []
    for cle, fr in LB.libelles("admin.journal.motif.", "fr").items():
        if isinstance(fr, str):
            morceaux = re.split(r"\{(\w+)\}", fr)
            expr = "".join(re.escape(m) if i % 2 == 0 else f"(?P<{m}>.+?)" for i, m in enumerate(morceaux))
            sortie.append((re.compile(f"^{expr}$"), cle))
    return sortie


def traduire_avant(v):
    if not v:
        return v
    cle = f"admin.journal.texte.{LB.cle_valeur(v)}"
    if LB.libelle(cle, "fr") == v:
        return libelle(cle)
    for k, fr in LB.libelles("visu.journal.", "fr").items():
        if fr == v:
            return libelle(k)
    if len(v) > A.JOURNAL_MOTIF_MAX or "\n" in v:
        return v
    for expr, k in motifs_avant():
        m = expr.match(v)
        if m:
            return libelle(k, **{c: traduire_avant(x) if c in ("nom", "theme") else x for c, x in m.groupdict().items()})
    return v


def textes_essais():
    """Textes du journal : tous les textes fixes et modèles en français, des modèles remplis, du texte libre."""
    textes = [v for v in LB.libelles("admin.journal.texte.", "fr").values() if isinstance(v, str)]
    textes += [v for v in LB.libelles("visu.journal.", "fr").values() if isinstance(v, str)]
    for v in LB.libelles("admin.journal.motif.", "fr").values():
        if isinstance(v, str):
            textes.append(re.sub(r"\{(\w+)\}", lambda m: {"nom": "texte fourni", "n": "3"}.get(m.group(1), "Valeur"), v))
    return textes + ["", "123", "valide", "Un commentaire libre", "x" * 400, "deux\nlignes", "(retiré)"]


class JournalFiltresTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        h = random.Random(GRAINE)
        g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        cls.orgs = [Organisation.objects.create(nom=f"Filiale {i}", niveau_id=Niveau.ENTITY, parent=g, rang=i) for i in range(4)]
        k = KPI.objects.create(code="EFF", libelle="Effectif", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                               methode_agregation="Somme")
        KPI.objects.create(code="12", libelle="KPI au code numérique", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY)
        ref = Referentiel.objects.create(code="ANN", nom="Annuel", frequence="annee")
        cls.campagnes = [P.campagne(ref, datetime.date(an, 1, 1), statut=Campagne.Statut.CLOTUREE)[0] for an in (2024, 2025, 2026)]
        reps = [Reponse.objects.create(periode=c.periode, kpi=k, organisation=o, valeur=Decimal(i), statut="valide")
                for i, (c, o) in enumerate((c, o) for c in cls.campagnes for o in cls.orgs)]
        disparue = reps.pop()
        disparu = disparue.pk
        disparue.delete()
        cls.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN,
                                               first_name="Alice", is_staff=True, is_superuser=True)
        autres = [Utilisateur.objects.create(username=f"u{i}", email=f"u{i}@exemple.test", first_name=f"Personne {i}")
                  for i in range(4)]
        cls.auditeur = Utilisateur.objects.create(username="auditeur", email="auditeur@exemple.test", role=Utilisateur.Role.AUDITEUR)
        cls.auditeur_limite = Utilisateur.objects.create(username="audit2", email="audit2@exemple.test", role=Utilisateur.Role.AUDITEUR)
        cls.auditeur_limite.perimetre_lecture.set([cls.orgs[1], cls.orgs[2]])
        actions = ["creation", "modification", "valeur_recalculee", "depot_preuve", "alerte_justifier", "import",
                   "reglage_kpi", "attribution", "action_inconnue"]
        textes = textes_essais()
        lignes = []
        for i in range(600):
            r = h.choice(reps)
            objet, oid = "Reponse", str(r.pk)
            tirage = h.random()
            if tirage < 0.05:
                oid = str(disparu)
            elif tirage < 0.08:
                oid = h.choice([f"0{r.pk}", f" {r.pk}", f"{r.pk}x", "abc", ""])
            elif tirage < 0.12:
                objet = h.choice(["KPI", "Organisation", "Campagne"])
            lignes.append(Journal(utilisateur=h.choice(autres + [None]), action=h.choice(actions), objet=objet, objet_id=oid,
                                  champ=h.choice(["valeur", "statut", "commentaire", "reglage"]), avant=h.choice(textes),
                                  apres=h.choice(textes)))
        Journal.objects.bulk_create(lignes)
        for i, j in enumerate(Journal.objects.order_by("pk")):  # dates distinctes : l'ordre de la page ne dépend que d'elles
            Journal.objects.filter(pk=j.pk).update(date=datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc)
                                                   + datetime.timedelta(hours=7 * i))

    def ids(self, qs):
        return sorted(qs.values_list("pk", flat=True))

    def test_memes_entrees_par_exercice_organisation_et_perimetre(self):
        base = Journal.objects.filter(action__in=[a for f, _, acts in A.FAMILLES if f in A.FAMILLES_SAISIE for a in acts])
        o = [str(x.pk) for x in self.orgs]
        cas = [([], [], None), (["2024"], [], None), (["2025", "2026"], [], None), ([], [o[0]], None), ([], [o[1], o[3]], None),
               (["2025"], [o[2]], None), (["1999"], [], None), ([], [], {self.orgs[1].pk, self.orgs[2].pk}),
               (["2026"], [], {self.orgs[1].pk}), ([], [o[0]], {self.orgs[1].pk}), ([], [], set())]
        for exercices, orgs, permises in cas:
            with self.subTest(exercices=exercices, orgs=orgs, permises=permises):
                avant = self.ids(des_reponses_avant(base, exercices, orgs, permises))
                self.assertEqual(self.ids(A.journal_des_reponses(base, exercices, orgs, permises)), avant)
                self.assertEqual(A.journal_des_reponses(base, exercices, orgs, permises).count(), len(avant))
        self.assertTrue(self.ids(des_reponses_avant(base, ["2025"], [], None)))

    def test_memes_comptes_par_personne(self):
        for vue in ("saisies", "admin"):
            actions = [a for f, _, acts in A.FAMILLES if (f in A.FAMILLES_SAISIE) == (vue == "saisies") for a in acts]
            total = Journal.objects.filter(action__in=actions)
            with self.subTest(vue=vue):
                self.assertEqual(A.journal_par_personne(total, actions), par_personne_avant(total, actions))
        restreint = des_reponses_avant(Journal.objects.all(), [], [], {self.orgs[1].pk})
        self.assertEqual(A.journal_par_personne(restreint, [], restreint=True), par_personne_avant(restreint, []))

    def test_memes_textes_traduits(self):
        for langue in ("fr", "en", "es"):
            with L.activer(langue):
                for v in textes_essais():
                    with self.subTest(langue=langue, texte=v[:40]):
                        self.assertEqual(A.traduire_texte_journal(v), traduire_avant(v))

    def page(self, u, url):
        self.client.force_login(u)
        r = self.client.get(url, secure=True)
        self.assertEqual(r.status_code, 200, url)
        html = re.sub(r'nonce="[^"]*"', "", r.content.decode())
        return re.sub(r"\b[A-Za-z0-9]{64}\b", "<jeton>", html)

    def test_memes_pages(self):
        o = self.orgs
        urls = ["", "?exercice=2025", "?exercice=2024&exercice=2026", f"?org={o[0].pk}", f"?org={o[1].pk}&exercice=2025",
                "?q=Valeur", "?famille=saisie&exercice=2025", "?vue=admin", "?tri-journal=auteur&exercice=2026",
                f"?personne={Utilisateur.objects.get(username='u1').pk}&org={o[2].pk}"]
        for u, chemin in ((self.admin, "/administration/journal/"), (self.auditeur, "/historique/"),
                          (self.auditeur_limite, "/historique/")):
            for q in urls:
                with self.subTest(personne=u.username, url=q):
                    with mock.patch.multiple(A, journal_des_reponses=des_reponses_avant, journal_par_personne=par_personne_avant,
                                             traduire_texte_journal=traduire_avant):
                        avant = self.page(u, chemin + q)
                    self.assertEqual(self.page(u, chemin + q), avant)
