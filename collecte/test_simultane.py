"""Saisies simultanées : pas d'écrasement silencieux d'une case ou d'une fiche KPI, première saisie simultanée sans erreur."""
import datetime
from unittest import mock

from django.core.exceptions import ValidationError
from django.urls import reverse

from . import reglages as R
from . import saisie as S
from .models import Reponse
from .aides_tests.saisie import Base

FETCH = {"HTTP_X_REQUESTED_WITH": "fetch"}


class SaisieSimultaneeTests(Base):
    def test_deux_personnes_sur_la_meme_case(self):
        vue_contrib = vue_valid = S.version(S.reponse_de(self.c, self.eff, self.e1))  # les deux ouvrent la case vide
        S.enregistrer(self.contrib, self.c, self.eff, self.e1, "120", False, "", version_vue=vue_contrib)
        with self.assertRaisesMessage(ValidationError, "vient d'être modifiée par"):  # le validateur saisissait 115 en même temps
            S.enregistrer(self.valid, self.c, self.eff, self.e1, "115", False, "", version_vue=vue_valid)
        r = S.reponse_de(self.c, self.eff, self.e1)
        self.assertEqual(r.valeur, 120)  # la saisie du contributeur n'est pas écrasée
        S.enregistrer(self.valid, self.c, self.eff, self.e1, "115", False, "", version_vue=S.version(r))  # en connaissance de cause
        self.assertEqual(S.reponse_de(self.c, self.eff, self.e1).valeur, 115)

    def test_sans_conflit_les_saisies_successives_passent(self):
        r = S.enregistrer(self.contrib, self.c, self.eff, self.e1, "120", False, "", version_vue="")
        r = S.enregistrer(self.contrib, self.c, self.eff, self.e1, "121", False, "", version_vue=S.version(r))
        self.assertEqual(r.valeur, 121)
        S.enregistrer(self.contrib, self.c, self.eff, self.e1, "122", False, "")  # sans version (import, outil) : pas de contrôle

    def test_premiere_saisie_simultanee_sans_erreur(self):
        # une autre personne crée la réponse (vide) entre la lecture et l'écriture : mise à jour normale, pas d'erreur
        Reponse.objects.create(periode=self.c.periode, kpi=self.eff, organisation=self.e1, statut=Reponse.Statut.A_SAISIR)
        with mock.patch.object(S, "reponse_de", return_value=None):
            r = S.enregistrer(self.contrib, self.c, self.eff, self.e1, "120", False, "", version_vue="")
        self.assertEqual((r.valeur, Reponse.objects.filter(kpi=self.eff, organisation=self.e1).count()), (120, 1))

    def test_panneau(self):
        self.client.force_login(self.contrib)
        url = reverse("collecte:cellule", args=[self.c.pk, "EFF", self.e1.pk])
        S.enregistrer(self.valid, self.c, self.eff, self.e1, "100", False, "")
        version = S.version(S.reponse_de(self.c, self.eff, self.e1))
        self.assertIn(f'name="version" value="{version}"', self.client.get(url, **FETCH).json()["html"])
        rep = self.client.post(url, {"action": "enregistrer", "valeur": "90", "version": "2020-01-01T00:00:00+00:00"}, **FETCH)
        self.assertIn("vient d&#x27;être modifiée", rep.json()["html"])
        self.assertIn("data-non-enregistre", rep.json()["html"])  # la saisie refusée reste gardée dans le panneau
        self.assertNotIn("aria-invalid", rep.json()["html"])  # conflit : la valeur tapée n'est pas invalide
        self.assertIn('aria-describedby="erreurs-saisie"', rep.json()["html"])
        self.assertIn("Fermez la case sans enregistrer pour voir sa saisie", rep.json()["html"])
        # la question de fermeture dit que l'enregistrement remplacerait la saisie de l'autre personne ; « Fermer sans
        # enregistrer » passe en premier (il reçoit le focus : Entrée ne remplace rien)
        self.assertIn('aria-describedby="question-fermeture-conflit"', rep.json()["html"])
        self.assertIn("Une autre personne a modifié cette case. Si vous enregistrez, votre valeur remplace la sienne.", rep.json()["html"])
        self.assertIn("Remplacer par ma saisie et fermer", rep.json()["html"])
        self.assertNotIn("{#", rep.json()["html"])
        self.assertNotIn("Enregistrer le brouillon et fermer", rep.json()["html"])
        question = rep.json()["html"].split('class="question-actions">')[1]
        self.assertLess(question.index("Fermer sans enregistrer"), question.index("Remplacer par ma saisie"))
        self.assertEqual(S.reponse_de(self.c, self.eff, self.e1).valeur, 100)


class FicheSimultaneeTests(Base):
    def test_deux_admins_sur_la_meme_fiche(self):
        self.client.force_login(self.admin)
        url = reverse("collecte:referentiel_kpi", args=["EFF"])
        form = R.KPIForm(instance=self.eff)
        donnees = {n: form[n].value() for n in form.fields if form[n].value() not in (None, False, "")}
        ancienne = R.version_kpi(self.eff)
        self.eff.equipe_responsable = "RH"  # l'autre admin enregistre d'abord
        self.eff.save()
        self.eff.refresh_from_db()
        rep = self.client.post(url, {**donnees, "equipe_responsable": "Finance", "version": ancienne}, **FETCH).json()
        self.assertFalse(rep["ok"])
        self.assertIn("vient d&#x27;être modifiée", rep["html"])
        self.eff.refresh_from_db()
        self.assertEqual(self.eff.equipe_responsable, "RH")
        rep = self.client.post(url, {**donnees, "equipe_responsable": "Finance", "version": R.version_kpi(self.eff)}, **FETCH).json()
        self.assertTrue(rep["ok"], rep["html"])


import threading  # noqa: E402

from django.db import connection  # noqa: E402
from django.test import TransactionTestCase, skipUnlessDBFeature  # noqa: E402


def _reglages_des_migrations():
    """Ce que les migrations fournissent et dont ce test a besoin : un test transactionnel passé avant lui (tests de
    migration) vide toute la base, réglages compris."""
    from parametres.models import NiveauHierarchique, TypeReponse, TypeSaisie
    from referentiel.models import Niveau

    c6 = dict(couleur="#000000", couleur_fond="#FFFFFF", couleur_texte="#000000")
    for code, rang, nom in ((Niveau.GROUP, 1, "Groupe"), (Niveau.COUNTRY, 2, "Pays"), (Niveau.ENTITY, 3, "Entité")):
        NiveauHierarchique.objects.get_or_create(code=code, defaults=dict(rang=rang, nom=nom, nom_pluriel=f"{nom}s",
                                                                          couleur_pale="#FFFFFF", **c6))
    TypeSaisie.objects.get_or_create(code="Saisi", defaults=dict(libelle="Saisie", abrege="S", **c6))
    TypeReponse.objects.get_or_create(code="Num", defaults=dict(libelle="Nombre", format=TypeReponse.Format.NOMBRE))


@skipUnlessDBFeature("has_select_for_update")
class RecalculSimultaneTests(TransactionTestCase):
    """PostgreSQL : deux saisies au même instant sur deux organisations d'un même parent ; le total du parent est juste."""

    def test_total_juste_apres_deux_saisies_simultanees(self):
        from django.utils import timezone

        from parametres.referentiel import unite_depuis_symbole as U
        from referentiel.models import KPI, Niveau, Organisation, Utilisateur

        from .models import Campagne

        _reglages_des_migrations()
        p = Organisation.objects.create(nom="Pays", niveau_id=Niveau.COUNTRY)
        e1 = Organisation.objects.create(nom="E1", niveau_id=Niveau.ENTITY, parent=p)
        e2 = Organisation.objects.create(nom="E2", niveau_id=Niveau.ENTITY, parent=p)
        c = Campagne.objects.create(exercice=2026, statut=Campagne.Statut.OUVERTE,
                                    date_fin_saisie=timezone.localdate() + datetime.timedelta(days=30))
        eff = KPI.objects.create(code="EFF", libelle="Effectif", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                                 methode_agregation="Somme", unite=U("ETP"))
        admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN)
        depart = threading.Barrier(2)
        erreurs = []

        def saisir(org, v):
            try:
                depart.wait()
                S.enregistrer(admin, c, eff, org, v, False, "")
            except Exception as e:  # noqa: BLE001
                erreurs.append(e)
            finally:
                connection.close()

        for _ in range(5):
            fils = [threading.Thread(target=saisir, args=(e1, "10")), threading.Thread(target=saisir, args=(e2, "20"))]
            [f.start() for f in fils]
            [f.join() for f in fils]
            self.assertEqual(erreurs, [])
            self.assertEqual(Reponse.objects.get(periode=c.periode, kpi=eff, organisation=p).valeur, 30)
            Reponse.objects.filter(organisation__in=[e1, e2]).delete()
            depart.reset()

    def test_trois_mois_saisis_en_meme_temps_annee_juste(self):
        """Trois saisies au même instant dans trois mois d'un référentiel mensuel : chacune refait l'année qui les
        contient (cumul des mois) ; l'année compte les trois mois, sans erreur (jamais deux créations de la même case)."""
        from django.utils import timezone

        from referentiel.composition import composer
        from referentiel.models import KPI, Niveau, Organisation, Referentiel, Utilisateur

        from . import periodes as P
        from .calcul import recalculer
        from .models import Campagne

        _reglages_des_migrations()
        p = Organisation.objects.create(nom="Pays", niveau_id=Niveau.COUNTRY)
        e1 = Organisation.objects.create(nom="E1", niveau_id=Niveau.ENTITY, parent=p)
        elec = KPI.objects.create(code="ELEC", libelle="Électricité", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                                  methode_agregation="Somme")
        annuel = Referentiel.objects.create(code="RSE", nom="Reporting", ordre=1)
        mensuel = Referentiel.objects.create(code="NRG", nom="Énergie", ordre=2, frequence="mois")
        composer({"ELEC": ["Environnement"]}, annuel)
        composer({"ELEC": ["Consommations"]}, mensuel)
        fin = timezone.localdate() + datetime.timedelta(days=30)
        annee, _ = P.campagne(annuel, datetime.date(2026, 1, 1), statut=Campagne.Statut.OUVERTE, date_fin_saisie=fin)
        mois = [P.campagne(mensuel, datetime.date(2026, m, 1), statut=Campagne.Statut.OUVERTE, date_fin_saisie=fin)[0]
                for m in range(1, 13)]
        for c in mois:  # les douze mois connus : l'année est leur somme (sinon incomplète)
            Reponse.objects.create(periode=c.periode, kpi=elec, organisation=e1, valeur=1, statut=Reponse.Statut.VALIDE)
        recalculer(annee)
        self.assertEqual(Reponse.objects.get(periode=annee.periode, kpi=elec, organisation=p).valeur, 12)
        admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN)
        depart = threading.Barrier(3)
        erreurs = []

        def saisir(c, v):
            try:
                depart.wait()
                S.enregistrer(admin, c, elec, e1, v, False, "")
            except Exception as e:  # noqa: BLE001
                erreurs.append(e)
            finally:
                connection.close()

        for essai in range(4):
            fils = [threading.Thread(target=saisir, args=(c, str(10 * (essai + 1) + i)))
                    for i, c in enumerate(mois[essai:essai + 3])]
            [f.start() for f in fils]
            [f.join() for f in fils]
            self.assertEqual(erreurs, [])
            attendu = sum(Reponse.objects.filter(kpi=elec, organisation=e1, periode__type="mois").values_list("valeur", flat=True))
            for org in (e1, p):
                self.assertEqual(Reponse.objects.get(periode=annee.periode, kpi=elec, organisation=org).valeur, attendu, (essai, org))
            depart.reset()
