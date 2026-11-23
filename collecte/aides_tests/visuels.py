"""Aides des tests des visuels : base avec KPI supplémentaires et construction d'une vue."""
from decimal import Decimal


from collecte import visuels as VS
from collecte.models import Reponse
from collecte.aides_tests.echanges import Base
from parametres.models import TypeReponse
from referentiel.models import KPI, Niveau


D = Decimal


def vue(*visuels):
    return [{"id": f"v{i}", **v} for i, v in enumerate(visuels, start=1)]


class AvecKpis(Base):
    def setUp(self):
        super().setUp()
        oui_non, _ = TypeReponse.objects.get_or_create(code="OuiNonEssai", defaults={"libelle": "Oui / non", "format": "oui_non"})
        self.oui = KPI.objects.create(code="OUI", libelle="Politique formalisée", type_saisie_id="Saisi",
                                      granularite_id=Niveau.ENTITY, type_reponse=oui_non, methode_agregation="Décompte")
        self.grp = KPI.objects.create(code="GRP", libelle="Score du groupe", type_saisie_id="Saisi", granularite_id=Niveau.GROUP,
                                      methode_agregation="Aucune")
        self.eff2 = KPI.objects.create(code="EFF2", libelle="Effectif intérimaire", type_saisie_id="Saisi",
                                       granularite_id=Niveau.ENTITY, methode_agregation="Somme", unite=self.eff.unite, decimales=0)
        for o, r in ((self.e1, "Oui"), (self.e2, "Non")):
            Reponse.objects.create(periode=self.c0.periode, kpi=self.oui, organisation=o, texte=r, statut="valide", origine="import")
            Reponse.objects.create(periode=self.c0.periode, kpi=self.eff2, organisation=o, valeur=D(5), statut="valide", origine="import")
        Reponse.objects.create(periode=self.c0.periode, kpi=self.eff, organisation=self.e2, valeur=D(30), statut="valide", origine="import")
        Reponse.objects.create(periode=self.c0.periode, kpi=self.grp, organisation=self.g, valeur=D(72), statut="valide", origine="import")
        from collecte import calcul as C

        C.recalculer(self.c0)

    def donnees(self, utilisateur, *visuels, filtres=None, parametres=None):
        propre, erreurs = VS.valider_vue({"nom": "Essai", "visuels": vue(*visuels)}, utilisateur)
        self.assertEqual(erreurs, [])
        return VS.donnees(utilisateur, filtres or {}, propre["visuels"], parametres, campagne_choisie=self.c)
