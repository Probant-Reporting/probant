"""Gros exports en arrière-plan (``exports_arriere_plan.executer``) : le fichier n'est fabriqué qu'avec les droits de la
demande. Des droits élargis puis rendus entre la demande et le téléchargement (tâche en attente, reprise après un
redémarrage) ne doivent jamais donner un fichier au contenu des droits élargis ; de même si les droits changent pendant la
fabrication ; un compte désactivé ou passé en lecteur ne reçoit rien."""
from unittest import mock

from django.core.files.storage import default_storage
from django.urls import reverse

from parametres.rangement import EXPORTS
from referentiel.models import Attribution, Utilisateur

from . import exports_arriere_plan as EAP
from . import imports_arriere_plan as AP
from . import saisie as S
from .aides_tests.lecture_seule import Base
from .models import TacheExport
from .test_exports_arriere_plan import EXPORT_BASE, seuil

T = TacheExport.Statut


@mock.patch.object(EAP, "BATTEMENT", 0)
@mock.patch.object(AP, "planificateur_actif", lambda: False)
@mock.patch.object(EAP, "demarrer_fil", lambda code: None)
class DroitsAuMomentDeLaFabricationTests(Base):
    def demander(self, user):
        self.client.force_login(user)
        return self.client.post(self.url, {**EXPORT_BASE, "niveaux": self.niveaux})

    def setUp(self):
        super().setUp()
        for org, v in ((self.e1, "12"), (self.e2, "30")):
            S.enregistrer(self.admin, self.c, self.eff, org, v, False, "")
        S.enregistrer(self.contrib, self.c, self.taux, self.e1, "40", False, "")
        self.url = reverse("collecte:echanges_exporter")
        self.niveaux = EAP.E.N.codes()

    def elargir(self):
        return Attribution.objects.create(kpi=self.eff, organisation=self.e2, utilisateur=self.contrib)

    def refuse(self, t):
        t.refresh_from_db()
        self.assertEqual((t.statut, t.chemin, t.taille), (T.ECHEC, "", 0))
        self.assertIn("Vos accès ont changé depuis votre demande", t.erreur)
        self.client.force_login(self.contrib)
        page = self.client.get(reverse("collecte:echanges"))
        self.assertContains(page, "Vos accès ont changé depuis votre demande")
        rep = self.client.get(reverse("collecte:echanges_export_fichier", args=[t.pk]))
        self.assertEqual(rep.status_code, 302)  # jamais de fichier

    def test_droits_elargis_avant_la_fabrication_puis_rendus(self):
        seuil(1)
        self.demander(self.contrib)
        a = self.elargir()  # tâche en attente (ou reprise après un redémarrage) : droits élargis
        t = EAP.executer(EAP.prendre())
        a.delete()  # droits rendus avant le téléchargement : empreintes de nouveau égales
        self.refuse(t)
        self.assertFalse(default_storage.exists(EXPORTS) and default_storage.listdir(EXPORTS)[1])  # rien d'écrit

    def test_droits_changes_pendant_la_fabrication(self):
        seuil(1)
        self.demander(self.contrib)
        vrai = EAP.fabriquer
        etat = {}

        def fabriquer(t):
            etat["a"] = self.elargir()  # pendant la fabrication
            return vrai(t)

        with mock.patch.object(EAP, "fabriquer", fabriquer):
            t = EAP.executer(EAP.prendre())
        etat["a"].delete()
        self.refuse(t)

    def test_compte_desactive_ou_passe_lecteur_ne_recoit_rien(self):
        for motif, changer in (("désactivé", {"is_active": False}), ("lecteur", {"role": Utilisateur.Role.LECTEUR})):
            with self.subTest(motif):
                seuil(1)
                self.demander(self.contrib)
                Utilisateur.objects.filter(pk=self.contrib.pk).update(**changer)
                try:
                    with mock.patch.object(EAP, "fabriquer", side_effect=AssertionError("fabriqué")):
                        t = EAP.executer(EAP.prendre())
                    self.assertEqual((t.statut, t.chemin), (T.ECHEC, ""))
                    self.assertIn("Vos accès ont changé depuis votre demande", t.erreur)
                finally:
                    Utilisateur.objects.filter(pk=self.contrib.pk).update(is_active=True, role=Utilisateur.Role.CONTRIBUTEUR)
                    TacheExport.objects.all().delete()

    def test_droits_inchanges_fichier_fabrique(self):
        seuil(1)
        self.demander(self.contrib)
        t = EAP.executer(EAP.prendre())
        self.assertEqual(t.statut, T.PRET)
        self.client.force_login(self.contrib)
        self.assertEqual(self.client.get(reverse("collecte:echanges_export_fichier", args=[t.pk])).status_code, 200)
