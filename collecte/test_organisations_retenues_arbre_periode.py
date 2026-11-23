"""Export (``exports.organisations_retenues``) × arbre gardé à la clôture : le filtre des niveaux se lit dans l'arbre de
la période exportée, comme les lignes et la colonne du niveau (soupçon, confirmé).

2025 est clos avec E2 au niveau Entité sous Pays ; E2 devient ensuite un Site sous E1. L'export de 2025 filtré sur le
niveau Entité doit garder la ligne de E2 (une entité en 2025, avec son total de l'époque) ; avant, le filtre lisait le
niveau d'aujourd'hui (Site) et la ligne disparaissait, alors que E2 compte dans le total de Pays exporté. Données
inventées."""
from referentiel.models import Niveau, Organisation

from . import exports as E
from .test_changer_statut_reouverture import Reouverture


class OrganisationsRetenuesArbrePeriodeTests(Reouverture):
    def lignes(self, niveaux):
        p = E.Parametres(niveaux=niveaux, exercices=["2025"])
        return {l.org.nom: l for l in E.collecter(self.admin, p) if l.kpi.code == "EFF"}

    def test_niveau_de_l_epoque(self):
        Organisation.objects.filter(pk=self.e2.pk).update(niveau_id=Niveau.SITE, parent=self.e1)
        lignes = self.lignes([Niveau.ENTITY])
        self.assertIn("E2", lignes)  # avant : absente (Site aujourd'hui)
        self.assertEqual(lignes["E2"].org.niveau_id, Niveau.ENTITY)
        self.assertEqual(sorted(lignes), ["E1", "E2", "E3"])
        # filtré sur Site : E2 n'était pas un site en 2025, rien
        self.assertNotIn("E2", self.lignes([Niveau.SITE]))

    def test_choix_d_organisations_inchange(self):
        """Une liste d'organisations cochées garde son sens (mêmes identifiants), dans l'arbre de l'époque."""
        Organisation.objects.filter(pk=self.e2.pk).update(niveau_id=Niveau.SITE, parent=self.e1)
        p = E.Parametres(niveaux=[Niveau.ENTITY], exercices=["2025"], organisations=[self.e2.pk])
        self.assertEqual([l.org.nom for l in E.collecter(self.admin, p) if l.kpi.code == "EFF"], ["E2"])
