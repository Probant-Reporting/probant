"""Plusieurs processus (``backup --schedule`` et ``check_data --schedule``, plusieurs machines) lancent les alertes en
même temps : un seul passage réservé (``alertes._reserver``, écriture conditionnelle au registre commun), un seul e-mail
par destinataire. Une restauration d'espace ne fait rien repartir : l'état est au registre commun. À lancer aussi sous
PostgreSQL (``DATABASE_URL``)."""
import threading

from django.core import mail
from django.db import connections
from django.test import TransactionTestCase

from espaces.models import EtatAlertes
from parametres import alertes as AL
from parametres import sauvegardes as SV
from parametres.aides_tests.alertes import T0, DossierAlertes, disque_plein, passer
from referentiel.models import Utilisateur


class ConcurrenceTests(DossierAlertes, TransactionTestCase):
    databases = {"default", "commun"}
    adresses = "it@exemple.example"

    def en_meme_temps(self, action, n=6):
        barriere, resultats, erreurs = threading.Barrier(n), [], []

        def fil():
            try:
                barriere.wait()
                resultats.append(action())
            except Exception as e:  # noqa: BLE001 - dit par le test
                erreurs.append(e)
            finally:
                for c in connections.all():
                    c.close()

        fils = [threading.Thread(target=fil) for _ in range(n)]
        for f in fils:
            f.start()
        for f in fils:
            f.join(30)
        self.assertEqual(erreurs, [])
        return resultats

    def test_une_seule_reservation(self):
        EtatAlertes.objects.get_or_create(pk=1)
        self.assertEqual(sorted(self.en_meme_temps(lambda: AL._reserver(T0))), [False] * 5 + [True])

    def test_un_seul_e_mail_pour_des_passages_simultanes(self):
        with disque_plein():
            resultats = self.en_meme_temps(passer)
        faits = [r for r in resultats if r.get("fait")]
        self.assertEqual(len(faits), 1)
        self.assertEqual([m.to for m in mail.outbox], [["it@exemple.example"]])
        self.assertEqual(list(EtatAlertes.objects.get().problemes), ["disque.panne"])

    def test_restaurer_un_espace_ne_relance_rien(self):
        Utilisateur.objects.create(username="adm", email="adm@exemple.example", role=Utilisateur.Role.ADMIN)
        a = SV.creer("avant", format_base="json")
        with disque_plein():
            passer()
            self.assertEqual(len(mail.outbox), 2)
            SV.restaurer(a.chemin, exiger_signature=False, sauvegarder_avant=False)
            mail.outbox = []
            r = passer(16)
        self.assertEqual((r["nouveaux"], r["toujours"], mail.outbox), ([], ["disque.panne"], []))
