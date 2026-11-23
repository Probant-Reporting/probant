"""Brouillon enregistré automatiquement depuis le panneau de saisie : même chemin que
« Enregistrer le brouillon » (droits, lecture de la valeur, version), jamais une validation, une valeur validée jamais
modifiée ainsi, séparateur ambigu et valeur illisible refusés avec leur motif, lecture seule et saisie fermée refusées,
une ligne de journal par enregistrement automatique et par champ changé, jamais réécrite."""
from decimal import Decimal

from django.urls import reverse

from referentiel.models import Utilisateur

from . import saisie as S
from .models import Campagne, Journal, Reponse
from .aides_tests.saisie import Base

FETCH = {"HTTP_X_REQUESTED_WITH": "fetch"}


def _n(t):
    """Nombre écrit au journal, sans les zéros de la base (« 12.0000000000 » → « 12 »)."""
    return format(Decimal(t).normalize(), "f") if t else ""


class BrouillonAutoTests(Base):
    def setUp(self):
        super().setUp()
        self.url = reverse("collecte:cellule", args=[self.c.pk, "EFF", self.e1.pk])
        self.client.force_login(self.contrib)

    def auto(self, valeur, version=None, commentaire="", na=False, **autres):
        if version is None:
            version = S.version(S.reponse_de(self.c, self.eff, self.e1))
        donnees = {"action": "enregistrer", "auto": "1", "valeur": valeur, "commentaire": commentaire, "version": version}
        if na:
            donnees["non_applicable"] = "on"
        return self.client.post(self.url, {**donnees, **autres}, **FETCH)

    def lignes(self, champ=None):
        r = S.reponse_de(self.c, self.eff, self.e1)
        q = Journal.objects.filter(objet="Reponse", objet_id=str(r.pk)) if r else Journal.objects.none()
        return list(q.filter(champ=champ).order_by("pk") if champ else q.order_by("pk"))

    def test_enregistre_en_brouillon_sans_redessiner_le_panneau(self):
        rep = self.auto("120").json()
        r = S.reponse_de(self.c, self.eff, self.e1)
        self.assertTrue(rep["ok"])
        self.assertEqual((r.valeur, r.statut, r.saisi_par_id), (120, Reponse.Statut.BROUILLON, self.contrib.pk))
        self.assertEqual(rep["version"], S.version(r))  # la version suivante part de celle-ci (pas de conflit avec soi-même)
        self.assertEqual(rep["statut"], "brouillon")
        self.assertNotIn("html", rep)
        self.assertIn(f"EFF|{self.e1.pk}", rep["lignes"])
        self.assertRegex(rep["heure"], r"^\d\d:\d\d$")
        # deuxième enregistrement avec la version renvoyée : accepté
        self.assertTrue(self.auto("121", version=rep["version"]).json()["ok"])
        self.assertEqual(S.reponse_de(self.c, self.eff, self.e1).valeur, 121)

    def test_jamais_valide(self):
        self.auto("120", action_suivante="valider")
        self.assertEqual(S.reponse_de(self.c, self.eff, self.e1).statut, Reponse.Statut.BROUILLON)
        # une action autre qu'« enregistrer » avec auto=1 suit son chemin habituel (pas d'enregistrement automatique)
        rep = self.client.post(self.url, {"action": "valider", "auto": "1", "valeur": "120",
                                          "version": S.version(S.reponse_de(self.c, self.eff, self.e1))}, **FETCH).json()
        self.assertIn("html", rep)

    def test_valeur_validee_jamais_modifiee_automatiquement(self):
        self.enregistrer("100")
        S.valider(self.contrib, self.c, self.eff, self.e1)
        rep = self.auto("110").json()
        r = S.reponse_de(self.c, self.eff, self.e1)
        self.assertFalse(rep["ok"])
        self.assertIn("Enregistrer la modification", rep["motif"])
        self.assertEqual((r.valeur, r.statut), (100, Reponse.Statut.VALIDE))
        # le panneau marque le formulaire : le script n'envoie rien tant que la valeur est validée
        html = self.client.get(self.url, **FETCH).json()["html"]
        self.assertIn('data-auto data-statut-enregistre="valide"', html)

    def test_valeur_illisible_et_separateur_ambigu_refuses(self):
        rep = self.auto("abc").json()
        self.assertEqual((rep["ok"], rep["valeur_refusee"], rep["conflit"]), (False, True, False))
        self.assertIn("Saisissez un nombre", rep["motif"])
        self.assertIsNone(S.reponse_de(self.c, self.eff, self.e1))
        rep = self.auto("1,234").json()
        self.assertFalse(rep["ok"])
        self.assertIn("« 1,234 » peut se lire de deux façons", rep["motif"])
        self.assertIsNone(S.reponse_de(self.c, self.eff, self.e1))
        # la valeur enregistrée elle-même (« 1,234 » choisi à l'enregistrement explicite) n'est pas redemandée
        self.enregistrer("1.234")
        self.assertTrue(self.auto("1,234", commentaire="vu").json()["ok"])

    def test_conflit_de_version(self):
        version = S.version(S.reponse_de(self.c, self.eff, self.e1))
        S.enregistrer(self.valid, self.c, self.eff, self.e1, "90", False, "")  # le validateur, au même moment
        rep = self.auto("120", version=version).json()
        self.assertEqual((rep["ok"], rep["conflit"]), (False, True))
        self.assertIn("a modifié cette case à", rep["motif"])
        self.assertEqual(S.reponse_de(self.c, self.eff, self.e1).valeur, 90)

    def test_lecture_seule_et_saisie_fermee(self):
        auditeur = Utilisateur.objects.create(username="audit", email="audit@exemple.test", role=Utilisateur.Role.AUDITEUR)
        self.client.force_login(auditeur)
        self.assertEqual(self.auto("120").status_code, 403)
        self.assertNotIn("data-auto", self.client.get(self.url, **FETCH).json()["html"])
        self.client.force_login(self.contrib)
        Campagne.objects.filter(pk=self.c.pk).update(statut=Campagne.Statut.CLOTUREE)
        self.assertEqual(self.auto("120").status_code, 403)
        self.assertNotIn("data-auto", self.client.get(self.url, **FETCH).json()["html"])
        self.assertIsNone(S.reponse_de(self.c, self.eff, self.e1))

    def test_journal_ne_fait_que_grandir(self):
        """Une ligne par enregistrement automatique et par champ réellement changé ; rien si rien n'a changé ; aucune
        ligne existante n'est jamais modifiée ni retirée (le journal est une piste d'audit)."""
        for v in ("1", "12", "120"):
            self.assertTrue(self.auto(v).json()["ok"])
        self.assertEqual([(_n(j.avant), _n(j.apres)) for j in self.lignes("valeur")], [("", "1"), ("1", "12"), ("12", "120")])
        self.assertEqual(len(self.lignes("statut")), 1)  # brouillon dès le premier : pas de ligne de plus ensuite
        figees = {j.pk: (j.date, j.avant, j.apres) for j in self.lignes()}
        n = len(figees)
        self.auto("120")  # même saisie : aucune ligne
        self.assertEqual(len(self.lignes()), n)
        self.auto("120", commentaire="Source : paie")  # seul le commentaire a changé : une ligne
        self.assertEqual((self.lignes("commentaire")[-1].avant, self.lignes("commentaire")[-1].apres), ("", "Source : paie"))
        self.assertEqual(len(self.lignes()), n + 1)
        self.assertEqual({j.pk: (j.date, j.avant, j.apres) for j in self.lignes() if j.pk in figees}, figees)

    def test_saisie_remise_comme_avant_ecrit_une_nouvelle_ligne(self):
        """« Annuler mes modifications » : la valeur remise est une nouvelle ligne ; la série reste au journal."""
        self.enregistrer("100")
        self.auto("150")
        self.auto("100")
        self.assertEqual([(_n(j.avant), _n(j.apres)) for j in self.lignes("valeur")], [("", "100"), ("100", "150"), ("150", "100")])
        self.assertEqual(S.reponse_de(self.c, self.eff, self.e1).valeur, 100)

    def test_lignes_de_chaque_personne(self):
        self.auto("10")
        self.client.force_login(self.valid)
        self.auto("11")
        self.assertEqual([(j.utilisateur_id, j.apres) for j in self.lignes("valeur")], [(self.contrib.pk, "10"), (self.valid.pk, "11")])

    def test_panneau_ne_redemande_rien_quand_tout_est_enregistre(self):
        html = self.client.get(self.url, **FETCH).json()["html"]
        self.assertIn("data-auto", html)
        self.assertIn("data-annuler-auto", html)
        self.assertIn("data-brouillon-garde", html)
        self.assertIn('role="status" data-repere', html)
