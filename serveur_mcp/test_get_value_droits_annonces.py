"""Les droits que ``get_value`` annonce pour une case sont ceux que les outils d'écriture appliquent (``save_value`` ↔
``can_change``, ``mark_not_applicable`` ↔ ``can_answer_na``, ``validate_value`` ↔ ``can_validate``) : sur un jeu varié de
cases (périmètre, autre organisation, calculée, au-dessus de la granularité, exercice clos, organisation pas encore
ouverte, KPI pas demandé, KPI commun à une campagne clôturée, N/A réservé à certains rôles, N/A déjà posé), pour chaque
rôle. Une case que ``get_value`` refuse l'est aussi par chaque outil d'écriture.

Données inventées uniquement."""
import datetime
import json

from django.db import transaction

from collecte.models import Campagne, Reponse
from parametres.models import Instance
from referentiel.models import ElementReferentiel, Organisation, Referentiel

from .aides_tests import MODERNE, BaseMCP

ROLES = ("admin", "validateur", "contributeur", "autre", "lecteur", "auditeur")


class Annulee:
    """Bloc dont toutes les écritures sont annulées à la sortie."""

    def __enter__(self):
        self.atomic = transaction.atomic()
        self.atomic.__enter__()

    def __exit__(self, *exc):
        transaction.set_rollback(True)
        return self.atomic.__exit__(*exc)


class DroitsAnnoncesTests(BaseMCP):
    def cases(self):
        return {"eff_e1": self.case(), "eff_e2": self.case(org=self.e2), "taux_e1": self.case(kpi=self.taux),
                "calcule": self.case(kpi=self.calc), "pays": self.case(org=self.p), "cloturee": self.case(campagne=self.c0)}

    def erreur(self, res):
        return json.loads(res["content"][0]["text"])["error"]["type"] if res["isError"] else None

    def verifier(self, scenario):
        """Annoncé par ``get_value`` = appliqué par chaque outil d'écriture, pour chaque rôle et chaque case."""
        vues = 0
        for role in ROLES:
            for cle, a in self.cases().items():
                with self.subTest(scenario=scenario, role=role, case=cle):
                    _, res, v = self.outil(role, "get_value", a, MODERNE)
                    version = v["version"] if not res["isError"] else ""
                    droits = None if res["isError"] else v["rights"]
                    with Annulee():
                        _, r, _ = self.outil(role, "save_value", {**a, "value": "7", "version": version}, MODERNE)
                        ecrit = not r["isError"]
                    with Annulee():
                        _, r, _ = self.outil(role, "mark_not_applicable", {**a, "comment": "Raison", "version": version}, MODERNE)
                        na = not r["isError"]
                    with Annulee():
                        _, r, _ = self.outil(role, "validate_value", a, MODERNE)
                        valide = self.erreur(r) != "permission_denied"
                        deja_validee = droits is not None and v["status"] == "valide"
                    if droits is None:
                        self.assertEqual((ecrit, na, valide), (False, False, False), "case refusée par get_value")
                        continue
                    vues += 1
                    self.assertEqual(ecrit, droits["can_change"], "save_value")
                    self.assertEqual(na, droits["can_answer_na"], "mark_not_applicable")
                    if not deja_validee:  # déjà validée : l'outil le dit sans rien écrire, pour qui voit la case
                        self.assertEqual(valide, droits["can_validate"], "validate_value")
        self.assertGreater(vues, 10)

    def test_normal(self):
        self.verifier("normal")

    def test_na_reserve_a_certains_roles(self):
        Instance.courante()
        Instance.objects.update(na_roles="admin")
        self.verifier("na réservé")

    def test_na_deja_pose(self):
        Instance.objects.update(na_roles="admin")
        Reponse.objects.filter(periode=self.c.periode, kpi=self.eff, organisation=self.e1).update(
            valeur=None, non_applicable=True, commentaire="Sans objet")
        self.verifier("na déjà posé")

    def test_organisation_pas_ouverte(self):
        Organisation.objects.filter(pk=self.p.pk).update(date_ouverture=datetime.date(2027, 1, 1))
        self.verifier("org pas ouverte")

    def test_kpi_pas_demande(self):
        ElementReferentiel.objects.update_or_create(referentiel=self.c.referentiel, kpi=self.eff,
                                                    defaults={"demande_depuis": datetime.date(2027, 1, 1)})
        ElementReferentiel.objects.get_or_create(referentiel=self.c.referentiel, kpi=self.taux)
        ElementReferentiel.objects.filter(referentiel=self.c.referentiel, kpi=self.calc).delete()  # sinon EFF, sa source, reste demandé
        _, res, v = self.outil("admin", "get_value", self.case(), MODERNE)
        self.assertFalse(res["isError"], v)  # la raison est lue, rien n'est à modifier
        self.assertFalse(v["rights"]["can_change"])
        self.assertIn("2027", v["rights"]["reason"])
        self.verifier("kpi pas demandé")

    def test_kpi_commun_a_une_campagne_cloturee(self):
        for k in (self.eff, self.taux):
            ElementReferentiel.objects.get_or_create(referentiel=self.c.referentiel, kpi=k)
        autre = Referentiel.objects.create(code="AUTRE", nom="Cadre voisin", ordre=99)
        ElementReferentiel.objects.create(referentiel=autre, kpi=self.eff)
        Campagne.objects.create(referentiel=autre, periode=self.c.periode, exercice=self.c.exercice,
                                statut=Campagne.Statut.CLOTUREE)
        self.verifier("kpi commun clos")
