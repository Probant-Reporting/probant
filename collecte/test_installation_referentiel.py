"""Ajouter un référentiel : KPI cochés d'un modèle de la bibliothèque (sélection, sources ajoutées), installation en trois
écrans, complément d'un modèle déjà installé, page « Ajouter un référentiel », niveau de saisie en lot, droits."""
import json

from django.test import TestCase
from django.urls import reverse

from parametres.models import NiveauHierarchique
from referentiel.models import KPI, ElementReferentiel, Referentiel, Theme, Utilisateur

from . import paquets as P
from .models import Journal
from .aides_tests.bibliotheque_essai import BibliothequeEssai

FETCH = {"HTTP_X_REQUESTED_WITH": "fetch"}


def ges():
    return P.fourni("socle_ges.json").paquet


class SelectionTests(BibliothequeEssai, TestCase):
    def test_sources_ajoutees_avec_leur_place(self):
        sous, ajoutes = P.selection(ges(), ["GES-S1-FIXE"])
        self.assertEqual({k["code"] for k in sous.kpis}, {"GES-S1-FIXE", "NRJ-GAZ", "NRJ-FIOUL", "FE-GAZ", "FE-FIOUL"})
        self.assertEqual(dict(ajoutes), {"NRJ-GAZ": ["GES-S1-FIXE"], "NRJ-FIOUL": ["GES-S1-FIXE"], "FE-GAZ": ["GES-S1-FIXE"],
                                         "FE-FIOUL": ["GES-S1-FIXE"]})
        self.assertTrue(all(k["element"] for k in sous.kpis))  # les sources sont placées dans le référentiel, dans leur thème
        self.assertEqual({t["code"] for t in sous.themes}, {"SCOPE1", "COMBUSTION_FIXE", "FACTEURS"})  # thèmes vides retirés
        self.assertEqual(sous.referentiel["identifiant"], ges().referentiel["identifiant"])

    def test_sources_en_cascade_et_n_moins_1(self):
        sous, ajoutes = P.selection(ges(), ["GES-EVOL"])
        codes = {k["code"] for k in sous.kpis}
        self.assertTrue({"GES-TOTAL", "GES-S1", "GES-S3-ACHATS", "FE-ELEC"} <= codes)
        self.assertEqual(dict(ajoutes)["GES-TOTAL"], ["GES-EVOL"])
        self.assertNotIn("GES-EVOL", dict(ajoutes))

    def test_regles_filtrees(self):
        p = P.fourni("socle_social.json").paquet
        sous, _ = P.selection(p, ["SOC-EFF-FEMMES", "SOC-EFFECTIF"])
        self.assertEqual([r["nom"] for r in sous.regles], ["Effectif féminin ≤ effectif total"])
        sous, _ = P.selection(p, ["SOC-EFFECTIF"])
        self.assertEqual(sous.regles, [])

    def test_tout_coche_rien_ajoute(self):
        p = ges()
        sous, ajoutes = P.selection(p, [k["code"] for k in p.kpis])
        self.assertEqual((len(sous.kpis), len(sous.themes), ajoutes), (len(p.kpis), len(p.themes), []))

    def test_installation_partielle(self):
        a, ajoutes = P.analyser_installation(ges(), ["GES-S1-FIXE", "GES-S2-LB"], nom="Mon GES", frequence="semestre")
        self.assertEqual((a.erreur, a.mode, a.compteurs["rejet"]), ("", "nouveau", 0))
        res = P.appliquer(None, a)
        ref = res.referentiel
        self.assertEqual((ref.code, ref.nom, ref.frequence, ref.origine), ("SOCLE_GES", "Mon GES", "semestre", Referentiel.Origine.FOURNI))
        self.assertEqual(ref.elements.count(), 2 + len(ajoutes))
        self.assertEqual(P.fourni("socle_ges.json").installe, ref)
        self.assertEqual(KPI.objects.get(pk="NRJ-GAZ").granularite_id, "Site")
        self.assertEqual(KPI.objects.get(pk="FE-GAZ").granularite_id, "Group")
        resume = P.resume_niveaux(a)
        self.assertEqual([(n.code, nb) for n, nb in resume["parametres"]], [("Group", 4), ("Country", 1)])  # FE-ELEC : Pays

    def test_complement_sans_retrait_ni_changement(self):
        a, _ = P.analyser_installation(ges(), ["GES-S1-FIXE"])
        ref = P.appliquer(None, a).referentiel
        ref.nom = "Renommé"
        ref.save()
        theme = Theme.objects.get(referentiel=ref, code="SCOPE1")
        theme.nom = "Mon scope 1"
        theme.save()
        ElementReferentiel.objects.filter(referentiel=ref, kpi_id="NRJ-FIOUL").update(theme=None, ordre=99)
        avant = set(ref.elements.values_list("kpi_id", flat=True))
        a, ajoutes = P.analyser_installation(ges(), ["GES-S1-MOBILE"], existant=ref)
        self.assertEqual((a.erreur, a.mode), ("", "mise_a_jour"))
        self.assertEqual({c for c, _ in ajoutes}, {"GES-GAZOLE", "GES-ESSENCE", "FE-GAZOLE", "FE-ESSENCE"})
        P.appliquer(None, a)
        ref.refresh_from_db()
        apres = set(ref.elements.values_list("kpi_id", flat=True))
        self.assertEqual(apres - avant, {"GES-S1-MOBILE", "GES-GAZOLE", "GES-ESSENCE", "FE-GAZOLE", "FE-ESSENCE"})
        self.assertTrue(avant <= apres)
        self.assertEqual(ref.nom, "Renommé")
        self.assertEqual(Theme.objects.get(referentiel=ref, code="SCOPE1").nom, "Mon scope 1")
        self.assertIsNone(ElementReferentiel.objects.get(referentiel=ref, kpi_id="NRJ-FIOUL").theme)
        self.assertTrue(Theme.objects.filter(referentiel=ref, code="COMBUSTION_MOBILE").exists())

    def test_deux_modeles_partagent_un_kpi(self):
        for f in ("socle_energie.json", "socle_ges.json"):
            p = P.fourni(f).paquet
            P.appliquer(None, P.analyser_installation(p, ["NRJ-ELEC"] + (["GES-S2-LB"] if "ges" in f else []))[0])
        self.assertEqual(KPI.objects.filter(code="NRJ-ELEC").count(), 1)
        self.assertEqual(ElementReferentiel.objects.filter(kpi_id="NRJ-ELEC").count(), 2)

    def test_arbre_holding_filiale(self):
        NiveauHierarchique.objects.all().delete()
        NiveauHierarchique.objects.create(code="Holding", rang=1, nom="Holding", nom_pluriel="Holding")
        NiveauHierarchique.objects.create(code="Filiale", rang=2, nom="Filiale", nom_pluriel="Filiales")
        a, _ = P.analyser_installation(ges(), ["GES-S1"])
        P.appliquer(None, a)
        self.assertEqual(KPI.objects.get(pk="GES-GAZOLE").granularite_id, "Filiale")
        self.assertEqual(KPI.objects.get(pk="FE-GAZOLE").granularite_id, "Holding")
        self.assertEqual(KPI.objects.get(pk="GES-S1").granularite_id, "Filiale")


class EcransTests(BibliothequeEssai, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = Utilisateur.objects.create_user("admin", "admin@exemple.test", "x", role=Utilisateur.Role.ADMIN)

    def setUp(self):
        self.client.force_login(self.admin)

    def test_modeles_en_espagnol(self):
        """Noms et descriptions des modèles fournis en espagnol (fichiers de langue), même si l'espagnol n'est pas une langue
        des contenus ; ceux du français et de l'anglais sont ceux des paquets."""
        from parametres import libelles as LB

        for f in P.bibliotheque():
            r, code = f.paquet.referentiel, f.paquet.code.lower()
            for lg in ("fr", "en"):
                for champ in ("nom", "description"):
                    self.assertEqual(LB.table(lg)[f"referentiels.socle.{code}.{champ}"], r[champ][lg])
        self.admin.langue = "es"
        self.admin.save()
        for url in (reverse("parametres:installer_modeles"), reverse("parametres:referentiel_nouveau")):
            rep = self.client.get(url)
            with self.subTest(url=url):
                self.assertContains(rep, "Energía (modelo)")
                self.assertContains(rep, "Gases de efecto invernadero")
                self.assertNotContains(rep, "Énergie (modèle)")
                self.assertNotContains(rep, "Gaz à effet de serre")
        rep = self.client.get(reverse("parametres:installer_modeles"))
        self.assertContains(rep, "Plantilla, movimientos, formación")
        self.assertContains(rep, 'aria-label="Elegir «Energía (modelo)»"')

    def test_parcours_complet_tout_coche(self):
        rep = self.client.get(reverse("parametres:installer_modeles"))
        self.assertContains(rep, "Gaz à effet de serre")
        self.assertContains(rep, 'aria-current="step"')
        self.assertContains(rep, reverse("parametres:installer_kpi", args=["SOCLE_GES"]))
        rep = self.client.get(reverse("parametres:installer_kpi", args=["SOCLE_GES"]))
        nb = len(ges().kpis)
        self.assertContains(rep, f"<b data-nb-coches>{nb}</b> KPI cochés sur {nb}", html=False)
        self.assertContains(rep, 'class="calcul-clair"')  # le calcul en clair, avec les noms
        self.assertNotContains(rep, "Niveaux de saisie")
        codes = [k["code"] for k in ges().kpis]
        rep = self.client.post(reverse("parametres:installer_kpi", args=["SOCLE_GES"]), {"action": "continuer", "kpi": codes})
        self.assertRedirects(rep, reverse("parametres:installer_resume", args=["SOCLE_GES"]))
        rep = self.client.get(reverse("parametres:installer_resume", args=["SOCLE_GES"]))
        self.assertContains(rep, f"<b>{nb} KPI</b> vont être installés", html=False)
        # le scope 3 est conseillé au niveau de l'entreprise : le résumé cite les niveaux conseillés (groupe et site)
        self.assertContains(rep, "aux niveaux conseillés par le modèle (<b>Groupe</b> et <b>Site</b>)", html=False)
        self.assertContains(rep, "au niveau <b>Groupe</b>", html=False)
        self.assertNotContains(rep, "Niveaux de saisie")
        self.assertNotContains(rep, "ajouté automatiquement")
        rep = self.client.post(reverse("parametres:installer_resume", args=["SOCLE_GES"]),
                               {"action": "installer", "nom": "Carbone", "frequence": "semestre", "mois_debut": "4", "code": "CARBONE"})
        self.assertRedirects(rep, reverse("parametres:referentiel_contenu", args=["CARBONE"]) + "?installe=1#regler-niveaux",
                             fetch_redirect_response=False)
        ref = Referentiel.objects.get(code="CARBONE")
        self.assertEqual((ref.nom, ref.frequence, ref.mois_debut, ref.elements.count()), ("Carbone", "semestre", 4, nb))
        page = self.client.get(rep["Location"])
        self.assertContains(page, "« Carbone » installé")
        self.assertContains(page, "Régler les niveaux de saisie")
        self.assertContains(page, "data-lot-niveau")
        self.assertIsNone(self.client.session.get("installer_modele"))

    def test_partiel_zero_et_session_expiree(self):
        url = reverse("parametres:installer_kpi", args=["SOCLE_GES"])
        rep = self.client.post(url, {"action": "continuer"})
        self.assertContains(rep, "Cochez au moins un KPI")
        self.assertFalse(Referentiel.objects.exists())
        rep = self.client.post(url, {"action": "rien"})
        self.assertContains(rep, "<b data-nb-coches>0</b>", html=False)
        rep = self.client.post(url, {"action": "continuer", "kpi": ["GES-S1-FIXE", "INCONNU"]})
        rep = self.client.get(reverse("parametres:installer_resume", args=["SOCLE_GES"]))
        self.assertContains(rep, "4 KPI ajoutés automatiquement")
        self.assertContains(rep, "utilisé par GES-S1-FIXE")
        rep = self.client.get(url)  # retour aux choix : la sélection est gardée
        self.assertContains(rep, "<b data-nb-coches>1</b>", html=False)
        session = self.client.session
        del session["installer_modele"]
        session.save()
        rep = self.client.get(reverse("parametres:installer_resume", args=["SOCLE_GES"]))
        self.assertRedirects(rep, url)
        self.assertEqual(self.client.get(reverse("parametres:installer_kpi", args=["INCONNU"])).status_code, 404)
        self.assertEqual(self.client.get(reverse("parametres:installer_resume", args=["INCONNU"])).status_code, 404)

    def test_complement_d_un_modele_installe(self):
        P.appliquer(None, P.analyser_installation(ges(), ["GES-S1-FIXE"])[0])
        ref = Referentiel.objects.get(code="SOCLE_GES")
        rep = self.client.get(reverse("parametres:installer_modeles"))
        self.assertContains(rep, "Ajouter d'autres KPI")
        rep = self.client.get(reverse("parametres:installer_kpi", args=["SOCLE_GES"]))
        self.assertContains(rep, "déjà installé")
        self.assertContains(rep, "<b data-nb-coches>5</b>", html=False)  # les 5 KPI présents, cochés d'avance
        self.client.post(reverse("parametres:installer_kpi", args=["SOCLE_GES"]), {"action": "continuer", "kpi": ["GES-FUGITIVES"]})
        rep = self.client.get(reverse("parametres:installer_resume", args=["SOCLE_GES"]))
        self.assertContains(rep, "va être ajouté à « Gaz à effet de serre")
        rep = self.client.post(reverse("parametres:installer_resume", args=["SOCLE_GES"]), {"action": "installer"})
        self.assertEqual(ref.elements.count(), 6)
        self.assertEqual(Referentiel.objects.count(), 1)

    def test_ancien_formulaire_et_ancienne_adresse(self):
        rep = self.client.post(reverse("parametres:paquet_importer"), {"action": "verifier", "bibliotheque": "socle_social.json"})
        self.assertRedirects(rep, reverse("parametres:installer_kpi", args=["SOCLE_SOCIAL"]))
        rep = self.client.get("/administration/referentiels/nouveau/")
        self.assertRedirects(rep, reverse("parametres:referentiel_nouveau"))
        self.assertEqual(reverse("parametres:referentiel_nouveau"), "/administration/referentiels/ajouter/")

    def test_droits(self):
        for role in ("contributeur", "validateur", "lecteur", "auditeur"):
            u = Utilisateur.objects.create_user(role, f"{role}@exemple.test", "x", role=role)
            self.client.force_login(u)
            for url in (reverse("parametres:installer_modeles"), reverse("parametres:installer_kpi", args=["SOCLE_GES"]),
                        reverse("parametres:installer_resume", args=["SOCLE_GES"]), reverse("parametres:referentiel_nouveau")):
                self.assertEqual(self.client.get(url).status_code, 403, (role, url))
            self.assertEqual(self.client.post(reverse("parametres:installer_kpi", args=["SOCLE_GES"]), {"kpi": ["NRJ-GAZ"]}).status_code, 403)
        self.assertFalse(Referentiel.objects.exists())

    def test_nouvelle_version_sans_reintroduire_les_kpi_laisses_de_cote(self):
        p = P.fourni("socle_social.json").paquet
        P.appliquer(None, P.analyser_installation(p, ["SOC-EFFECTIF", "SOC-EMBAUCHES"])[0])
        ref = Referentiel.objects.get(code="SOCLE_SOCIAL")
        Referentiel.objects.filter(pk=ref.pk).update(version="0.9")
        rep = self.client.get(reverse("parametres:referentiel_partage", args=["SOCLE_SOCIAL"]))
        self.assertContains(rep, reverse("parametres:installer_kpi", args=["SOCLE_SOCIAL"]) + "?version=1")
        rep = self.client.get(reverse("parametres:installer_kpi", args=["SOCLE_SOCIAL"]) + "?version=1")
        self.assertContains(rep, "<b data-nb-coches>2</b>", html=False)
        self.assertContains(rep, "Nouvelle version")
        rep = self.client.post(reverse("parametres:installer_kpi", args=["SOCLE_SOCIAL"]), {"action": "continuer"})
        self.assertRedirects(rep, reverse("parametres:installer_resume", args=["SOCLE_SOCIAL"]))
        self.assertContains(self.client.get(rep["Location"]), "mis à jour en version 1.0")
        self.client.post(rep["Location"], {"action": "installer"})
        ref.refresh_from_db()
        self.assertEqual((ref.version, ref.elements.count()), ("1.0", 2))

    def test_liens_vers_ajouter_un_referentiel(self):
        ajouter = reverse("parametres:referentiel_nouveau")
        rep = self.client.get(ajouter)
        for texte in ("Installer depuis la bibliothèque", "Composer à partir de KPI existants", "Importer un fichier",
                      "Créer un référentiel vide", reverse("parametres:installer_kpi", args=["SOCLE_GES"])):
            self.assertContains(rep, texte)
        rep = self.client.get(reverse("parametres:referentiels"))  # aucun référentiel : la bibliothèque et « Créer »
        self.assertContains(rep, "Aucun référentiel pour l'instant")
        self.assertContains(rep, reverse("parametres:installer_kpi", args=["SOCLE_GES"]))
        self.assertContains(rep, "</svg> Cocher des KPI existants</a>")  # icône « plus » dessinée 
        self.assertContains(rep, "Remplir le modèle Excel")
        rep = self.client.get(reverse("collecte:admin_accueil"))
        self.assertContains(rep, "Aucun référentiel : rien à collecter")
        self.assertContains(rep, f'href="{ajouter}"', count=2)
        rep = self.client.post(ajouter, {"nom": "Tableau de bord", "frequence": "annee", "composer": "1"})
        self.assertRedirects(rep, reverse("parametres:referentiel_choisir", args=["TABLEAU_DE_BORD"]),  # la page à cocher
                             fetch_redirect_response=False)
        rep = self.client.get(reverse("parametres:referentiels"))
        self.assertNotContains(rep, "Composer à partir de KPI existants")
        self.assertNotContains(self.client.get(reverse("collecte:admin_accueil")), "Aucun référentiel : rien à collecter")


class LotNiveauTests(BibliothequeEssai, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = Utilisateur.objects.create_user("admin", "admin@exemple.test", "x", role=Utilisateur.Role.ADMIN)
        P.appliquer(None, P.analyser_installation(ges(), ["GES-S1-MOBILE", "GES-S1-FIXE"])[0])

    def setUp(self):
        self.client.force_login(self.admin)
        self.url = reverse("parametres:referentiel_contenu_action", args=["SOCLE_GES"])

    def lot(self, **corps):
        return self.client.post(self.url, json.dumps({"action": "lot", "operation": "niveau", **corps}), content_type="application/json",
                                **FETCH)

    def test_niveau_en_lot_journal_et_avertissement(self):
        r = self.lot(codes=["GES-GAZOLE", "GES-ESSENCE"], niveau="Entity").json()
        self.assertTrue(r["ok"], r)
        self.assertIn("2 KPI passent au niveau de saisie Entité", r["message"])
        self.assertIn("GES-S1-MOBILE est calculé au niveau Site mais GES-ESSENCE se saisit au niveau Entité", r["message"])
        self.assertEqual(set(KPI.objects.filter(code__in=["GES-GAZOLE", "GES-ESSENCE"]).values_list("granularite_id", flat=True)), {"Entity"})
        self.assertEqual(Journal.objects.filter(action="reglage_kpi", champ="Granularité").count(), 2)
        r = self.lot(codes=["GES-S1-MOBILE"], niveau="Entity").json()  # le calculé suit : plus d'avertissement
        self.assertNotIn("Attention", r["message"])
        r = self.lot(codes=["GES-S1-MOBILE"], niveau="Entity").json()
        self.assertIn("déjà au niveau Entité", r["message"])
        self.assertEqual(self.lot(codes=["GES-GAZOLE"], niveau="Usine").status_code, 400)
        self.assertEqual(self.lot(codes=[], niveau="Site").status_code, 400)

    def test_confirmation_si_reponses_dans_une_campagne_ouverte(self):
        from referentiel.models import Organisation

        from .models import Campagne, Reponse

        ref = Referentiel.objects.get(code="SOCLE_GES")
        c = Campagne.objects.create(referentiel=ref, exercice=2026, statut=Campagne.Statut.OUVERTE)
        site = Organisation.objects.create(nom="Lyon", niveau_id="Site")
        Reponse.objects.create(periode=c.periode, kpi_id="NRJ-GAZ", organisation=site, valeur=10)
        r = self.lot(codes=["NRJ-GAZ"], niveau="Entity").json()
        self.assertFalse(r["ok"])
        self.assertIn("1 réponse saisie", r["confirmer"])
        self.assertEqual(KPI.objects.get(pk="NRJ-GAZ").granularite_id, "Site")  # rien d'écrit avant confirmation
        r = self.lot(codes=["NRJ-GAZ"], niveau="Entity", confirmer=True).json()
        self.assertTrue(r["ok"], r)
        self.assertEqual(KPI.objects.get(pk="NRJ-GAZ").granularite_id, "Entity")

    def test_droits_et_lecture_seule(self):
        for role in ("contributeur", "validateur", "lecteur", "auditeur"):
            u = Utilisateur.objects.create_user(role, f"{role}@exemple.test", "x", role=role)
            self.client.force_login(u)
            self.assertEqual(self.lot(codes=["NRJ-GAZ"], niveau="Entity").status_code, 403, role)
        self.assertEqual(KPI.objects.get(pk="NRJ-GAZ").granularite_id, "Site")

    def test_fiche_kpi_libelle_niveau_de_saisie(self):
        rep = self.client.get(reverse("collecte:referentiel_kpi", args=["NRJ-GAZ"]))
        self.assertContains(rep, "Niveau de saisie")


class RevueParcoursTests(BibliothequeEssai, TestCase):
    """Revue critique du parcours : cas limites d'une installation neuve ou déjà remplie."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = Utilisateur.objects.create_user("admin", "admin@exemple.test", "x", role=Utilisateur.Role.ADMIN)

    def setUp(self):
        self.client.force_login(self.admin)

    def installer(self, modele, kpis, **post):
        self.client.post(reverse("parametres:installer_kpi", args=[modele]), {"action": "continuer", "kpi": kpis})
        return self.client.post(reverse("parametres:installer_resume", args=[modele]), {"action": "installer", **post})

    def test_arbre_a_un_niveau(self):
        NiveauHierarchique.objects.all().delete()
        NiveauHierarchique.objects.create(code="Holding", rang=1, nom="Holding", nom_pluriel="Holding")
        self.client.post(reverse("parametres:installer_kpi", args=["SOCLE_GES"]), {"action": "continuer", "kpi": ["GES-S1"]})
        resume = self.client.get(reverse("parametres:installer_resume", args=["SOCLE_GES"]))
        self.assertContains(resume, "votre arbre n'a qu'un niveau, donc tous les KPI se saisissent au niveau <b>Holding</b>", html=False)
        self.assertNotContains(resume, "(le plus bas)")
        rep = self.installer("SOCLE_GES", [k["code"] for k in ges().kpis])
        self.assertEqual(rep.status_code, 302)
        self.assertEqual(set(KPI.objects.values_list("granularite_id", flat=True)), {"Holding"})
        self.assertEqual(self.client.get(rep["Location"]).status_code, 200)

    def test_double_clic_sur_installer(self):
        r1 = self.installer("SOCLE_GES", ["GES-S1"])
        r2 = self.client.post(reverse("parametres:installer_resume", args=["SOCLE_GES"]), {"action": "installer"})
        self.assertEqual(r2["Location"], r1["Location"])  # même page d'arrivée, sans « Choisir d'abord les KPI »
        self.assertEqual(Referentiel.objects.count(), 1)
        rep = self.client.get(r2["Location"])
        self.assertNotContains(rep, "Choisir d'abord les KPI")

    def test_modele_complet_rien_a_ajouter(self):
        p = P.fourni("socle_energie.json").paquet
        self.installer("SOCLE_ENERGIE", [k["code"] for k in p.kpis])
        rep = self.client.get(reverse("parametres:installer_modeles"))
        self.assertContains(rep, "Tous ses KPI sont installés.")
        rep = self.client.get(reverse("parametres:installer_kpi", args=["SOCLE_ENERGIE"]) + "?version=0")
        self.assertContains(rep, "Tous les KPI de ce modèle sont déjà dans")

    def test_code_reserve_refuse(self):
        self.installer("SOCLE_GES", ["GES-S1"], code="ajouter", nom="Essai")
        self.assertFalse(Referentiel.objects.filter(code="ajouter").exists())
        rep = self.client.post(reverse("parametres:referentiel_nouveau"), {"nom": "Essai", "frequence": "annee", "code": "modeles",
                                                                           "composer": "1"})
        self.assertFalse(Referentiel.objects.filter(code="modeles").exists())
        self.assertEqual(rep.status_code, 200)

    def test_arbre_encore_libre_signale_au_resume(self):
        self.client.post(reverse("parametres:installer_kpi", args=["SOCLE_GES"]), {"action": "continuer", "kpi": ["GES-S1"]})
        rep = self.client.get(reverse("parametres:installer_resume", args=["SOCLE_GES"]))
        self.assertContains(rep, "Votre arbre n'a encore aucune organisation")
        self.assertContains(rep, reverse("parametres:niveaux"))
        from referentiel.models import Organisation

        Organisation.objects.create(nom="Groupe", niveau_id="Group")
        rep = self.client.get(reverse("parametres:installer_resume", args=["SOCLE_GES"]))
        self.assertNotContains(rep, "Votre arbre n'a encore aucune organisation")

    def test_assistant_termine_plus_de_retour_vers_lui(self):
        from parametres.models import Instance

        i = Instance.courante()
        i.mise_en_place_etape, i.mise_en_place_terminee = 5, False
        i.save()
        self.client.get(reverse("parametres:installer_modeles") + "?depuis=mise_en_place")
        self.assertContains(self.client.get(reverse("parametres:installer_modeles")), "Revenir à la mise en place")
        i.mise_en_place_terminee = True
        i.save()
        rep = self.client.get(reverse("parametres:installer_modeles"))
        self.assertNotContains(rep, "Revenir à la mise en place")

    def test_phrase_des_niveaux_sans_parametre_herite(self):
        p = P.fourni("socle_social.json").paquet
        self.client.post(reverse("parametres:installer_kpi", args=["SOCLE_SOCIAL"]), {"action": "continuer", "kpi": [k["code"] for k in p.kpis]})
        rep = self.client.get(reverse("parametres:installer_resume", args=["SOCLE_SOCIAL"]))
        self.assertContains(rep, "les KPI saisis au niveau <b>Site</b>", html=False)
        self.assertNotContains(rep, "facteurs d'émission")
