"""Seconde recette (B3) : un gros export prêt dont les droits de la personne ont changé.
- Mes exports ne le montre plus « Prêt » : il est retiré (fichier supprimé sans être donné) et la page dit pourquoi.
- Un lien de téléchargement gardé (autre onglet, page restée ouverte) donne le message des droits, jamais « Ce fichier
  n'est plus disponible (les fichiers volumineux sont gardés 7 jours) »."""
from unittest import mock

from django.core.files.storage import default_storage
from django.urls import reverse

from parametres.libelles import libelle
from referentiel.models import Attribution

from . import exports as E
from . import exports_arriere_plan as EAP
from . import imports_arriere_plan as AP
from . import saisie as S
from .models import TacheExport
from .test_exports_arriere_plan import EXPORT_BASE, seuil
from .aides_tests.lecture_seule import Base

T = TacheExport.Statut


@mock.patch.object(EAP, "BATTEMENT", 0)
@mock.patch.object(AP, "planificateur_actif", lambda: False)
@mock.patch.object(EAP, "demarrer_fil", lambda code: None)
class DroitsChangesTests(Base):
    def setUp(self):
        super().setUp()
        S.enregistrer(self.contrib, self.c, self.taux, self.e1, "40", False, "")
        seuil(1)
        self.client.force_login(self.contrib)
        self.client.post(reverse("collecte:echanges_exporter"), {**EXPORT_BASE, "niveaux": E.N.codes()})
        self.t = EAP.executer(EAP.prendre())
        self.assertEqual(self.t.statut, T.PRET)
        Attribution.objects.filter(utilisateur=self.contrib, kpi=self.taux).delete()  # droits changés

    def test_mes_exports_ne_montre_plus_pret_et_dit_pourquoi(self):
        page = self.client.get(reverse("collecte:echanges")).content.decode()
        self.assertNotIn(reverse("collecte:echanges_export_fichier", args=[self.t.pk]), page)
        self.assertIn(libelle("suivi.echanges.msg.export_fond_droits").split(":")[0], page)
        self.t.refresh_from_db()
        self.assertEqual((self.t.statut, self.t.erreur), (T.EXPIRE, "droits"))
        self.assertFalse(default_storage.exists(self.t.chemin))

    def test_lien_garde_donne_le_message_des_droits(self):
        url = reverse("collecte:echanges_export_fichier", args=[self.t.pk])
        self.client.get(url, follow=True)  # premier clic : refusé, fichier supprimé, message lu
        rep = self.client.get(url, follow=True)  # second clic sur le même lien
        texte = rep.content.decode()
        self.assertIn(libelle("suivi.echanges.msg.export_fond_droits").split(":")[0], texte)
        self.assertNotIn(libelle("suivi.echanges.msg.export_fond_expire", n=EAP.jours()).replace("'", "&#x27;"), texte)
