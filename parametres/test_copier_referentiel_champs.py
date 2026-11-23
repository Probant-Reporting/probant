"""« Dupliquer » un référentiel (``copier_referentiel``) recopie tous les champs de ses KPI, y compris ceux ajoutés plus tard
(« demandé depuis » de chaque KPI) et la date de la version du référentiel. Données inventées."""
import datetime

from django.test import TestCase

from parametres.vues_referentiels import copier_referentiel
from referentiel.models import KPI, ElementReferentiel, Niveau, Referentiel, Utilisateur


class CopieChampsTests(TestCase):
    def setUp(self):
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN)
        self.ref = Referentiel.objects.create(code="R1", nom="Référentiel 1", version="2.1", date_version=datetime.date(2026, 3, 1))
        for code, depuis in (("A", datetime.date(2026, 1, 1)), ("B", None)):
            k = KPI.objects.create(code=code, type_saisie_id="Saisi", granularite_id=Niveau.ENTITY, methode_agregation="Somme")
            e = ElementReferentiel(referentiel=self.ref, kpi=k, ordre=1, demande_depuis=depuis)
            e.depuis_choisi = True
            e.save()

    def test_demande_depuis_et_date_de_version_recopiees(self):
        c = copier_referentiel(self.admin, self.ref, "Copie", code="R2")
        self.assertEqual(dict(c.elements.values_list("kpi_id", "demande_depuis")), {"A": datetime.date(2026, 1, 1), "B": None})
        self.assertEqual((c.version, c.date_version), ("2.1", datetime.date(2026, 3, 1)))

    def test_tous_les_champs_d_un_element_recopies(self):
        """Garde-fou : un champ ajouté plus tard à ElementReferentiel doit être recopié (ou écarté ici, exprès)."""
        propres = {"id", "referentiel"}  # propres à la copie
        champs = {f.name for f in ElementReferentiel._meta.concrete_fields} - propres
        c = copier_referentiel(self.admin, self.ref, "Copie", code="R2")
        for e in self.ref.elements.all():
            copie = c.elements.get(kpi_id=e.kpi_id)
            for nom in champs - {"theme"}:
                self.assertEqual(getattr(copie, nom), getattr(e, nom), nom)
