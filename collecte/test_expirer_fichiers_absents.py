"""Gros exports « prêts » dont le fichier n'a pas suivi la base (``exports_arriere_plan.expirer_fichiers_absents``) : après
une restauration (files/exports n'est jamais sauvegardé) et dans la version tout-en-un construite avec les données
(``portable/build_package.py --data``), ils passent « expirés » ; au clic sur un fichier manquant, le message donne la
vraie raison, jamais « gardés 7 jours ». Données inventées."""
from unittest import mock

from django.core.files.storage import default_storage
from django.test import TransactionTestCase
from django.urls import reverse

from parametres import sauvegardes as SV
from parametres.aides_tests.hebergement import DossiersTemporaires
from parametres.libelles import libelle

from . import exports as E
from . import exports_arriere_plan as EAP
from . import imports_arriere_plan as AP
from . import saisie as S
from .aides_tests.lecture_seule import Base
from .models import TacheExport
from .test_exports_arriere_plan import EXPORT_BASE, seuil

T = TacheExport.Statut


def message_absent():
    return libelle("suivi.echanges.msg.export_fond_absent").split(":")[0].replace("'", "&#x27;")


class Pret:
    def preparer(self):
        S.enregistrer(self.contrib, self.c, self.taux, self.e1, "40", False, "")
        seuil(1)
        self.client.force_login(self.contrib)
        self.client.post(reverse("collecte:echanges_exporter"), {**EXPORT_BASE, "niveaux": E.N.codes()})
        self.t = EAP.executer(EAP.prendre())
        self.assertEqual(self.t.statut, T.PRET)


@mock.patch.object(EAP, "BATTEMENT", 0)
@mock.patch.object(AP, "planificateur_actif", lambda: False)
@mock.patch.object(EAP, "demarrer_fil", lambda code: None)
class FichierAbsentTests(Pret, Base):
    def setUp(self):
        super().setUp()
        with mock.patch.object(EAP, "BATTEMENT", 0), mock.patch.object(AP, "planificateur_actif", lambda: False), \
                mock.patch.object(EAP, "demarrer_fil", lambda code: None):  # aucun fil : la tâche est faite ici
            self.preparer()

    def test_fichier_present_garde(self):
        self.assertEqual(EAP.expirer_fichiers_absents(), 0)
        self.t.refresh_from_db()
        self.assertEqual(self.t.statut, T.PRET)

    def test_expire_avec_son_motif_puis_message_juste(self):
        default_storage.delete(self.t.chemin)
        self.assertEqual(EAP.expirer_fichiers_absents(), 1)
        self.t.refresh_from_db()
        self.assertEqual((self.t.statut, self.t.erreur), (T.EXPIRE, EAP.FICHIER_ABSENT))
        texte = self.client.get(reverse("collecte:echanges_export_fichier", args=[self.t.pk]), follow=True).content.decode()
        self.assertIn(message_absent(), texte)
        self.assertNotIn(libelle("suivi.echanges.msg.export_fond_expire", n=EAP.jours()).split("(")[0].replace("'", "&#x27;"), texte)

    def test_clic_sur_un_fichier_manquant_sans_restauration(self):
        default_storage.delete(self.t.chemin)  # tâche encore « prête », dans sa durée de conservation
        texte = self.client.get(reverse("collecte:echanges_export_fichier", args=[self.t.pk]), follow=True).content.decode()
        self.assertIn(message_absent(), texte)
        self.t.refresh_from_db()
        self.assertEqual((self.t.statut, self.t.erreur), (T.EXPIRE, EAP.FICHIER_ABSENT))


class RestaurationTests(DossiersTemporaires, TransactionTestCase):
    """Sauvegarde faite avec une tâche prête, fichier effacé ensuite (durée passée), puis restauration : la tâche de la base
    restaurée n'est plus « prête » ; une tâche dont le fichier est encore là le reste."""

    def test_apres_une_restauration(self):
        from django.core.files.base import ContentFile
        from django.utils import timezone

        from parametres.rangement import EXPORTS
        from referentiel.models import Utilisateur

        u = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN)
        taches = []
        for nom in ("parti.xlsx", "garde.xlsx"):
            chemin = default_storage.save(f"{EXPORTS}/{nom}", ContentFile(b"x"))
            taches.append(TacheExport.objects.create(utilisateur=u, titre=nom, statut=T.PRET, chemin=chemin, nom_fichier=nom,
                                                     expire_le=timezone.now() + timezone.timedelta(days=7)))
        archive = SV.creer("essai", "json")
        default_storage.delete(taches[0].chemin)
        SV.restaurer(archive.chemin)
        etats = {t.titre: (t.statut, t.erreur) for t in TacheExport.objects.all()}
        self.assertEqual(etats, {"parti.xlsx": (T.EXPIRE, EAP.FICHIER_ABSENT), "garde.xlsx": (T.PRET, "")})
