"""Filet de tests des droits par rôle, sur toutes les adresses de l'outil : figent le comportement actuel.

- Lecteur et auditeur : tout envoi (POST) est refusé, sauf leurs préférences personnelles et les exports (lectures) ;
  après un balayage de toutes les adresses, aucune donnée de l'outil n'a changé ; leurs tableaux, exports et listes
  enregistrés ne sont jamais partagés et ils ne touchent pas à ceux des autres.
- Contributeur et validateur : les pages d'administration et de paramétrage leur sont refusées.
- Sans connexion : tout renvoie à la page de connexion, sauf la supervision et le logo.
- Droits sur une case (saisir, valider, repasser en brouillon) selon le rôle et l'état de la campagne."""
import datetime
import re

from django.urls import URLResolver, get_resolver, reverse
from django.utils import timezone

from referentiel.models import KPI, Attribution, Organisation, Utilisateur

from . import exports as E
from . import forcage as FO
from . import lecture_seule as LS
from . import saisie as S
from .models import Campagne, ReglageExport, Reponse, SelectionKPI, TableauVisu, VueVisu
from .aides_tests.lecture_seule import Base

PERSONNELS = {"TableauVisu", "VueVisu", "PreferenceVisu", "ReglageExport", "SelectionKPI"}  # préférences de la personne, permises au lecteur et à l'auditeur


def routes():
    """[(espace de noms, nom, motif)] de toutes les adresses, hors administration technique de Django."""
    sortie = []

    def parcourir(r, ns=None, prefixe=""):
        for p in r.url_patterns:
            if isinstance(p, URLResolver):
                parcourir(p, p.namespace or ns, prefixe + str(p.pattern))
            else:
                sortie.append((ns, p.name, prefixe + str(p.pattern)))
    parcourir(get_resolver())
    return [r for r in sortie if r[0] != "admin"]


def instantane():
    """Contenu de toutes les tables de l'outil (hors préférences personnelles et date de dernière connexion)."""
    from django.apps import apps

    etat = {}
    for app in ("collecte", "referentiel", "parametres"):
        for m in apps.get_app_config(app).get_models():
            if m.__name__ in PERSONNELS:
                continue
            champs = [f.attname for f in m._meta.concrete_fields if f.attname != "last_login"]
            etat[m.__name__] = sorted(map(repr, m.objects.values_list(*champs)))
    return etat


class Balayage(Base):
    def setUp(self):
        super().setUp()
        self.validateur = Utilisateur.objects.create(username="val", email="val@exemple.test", role=Utilisateur.Role.VALIDATEUR)
        Attribution.objects.create(kpi=self.eff, organisation=self.p, utilisateur=self.validateur, role=Attribution.Role.VALIDATEUR)
        self.tableau_admin = TableauVisu.objects.create(nom="Comité", proprietaire=self.admin, partage=True,
                                                        tuiles=[{"type": "chiffre", "kpi": "EFF"}])
        self.valeurs = {"campagne_id": self.c.pk, "org_id": self.e1.pk, "kpi_id": "EFF", "code": "EFF", "pk": self.tableau_admin.pk,
                        "user_id": self.contrib.pk, "nom": "x", "nom_fichier": "x", "etape": 1, "type_": "vue", "langue": "en", "guide": "administrator"}

    def url(self, motif):
        return "/" + re.sub(r"<(?:\w+:)?(\w+)>", lambda m: str(self.valeurs[m.group(1)]), motif)


class LectureSeuleBalayageTests(Balayage):
    def test_tout_envoi_refuse_hors_preferences(self):
        avant = instantane()
        for u in (self.lecteur, self.auditeur):
            self.client.force_login(u)
            for ns, nom, motif in routes():
                if nom in LS.LIBRES or nom in LS.ECRITURES_PERMISES or (ns == "parametres" and nom in LS.PARAMETRES_LIBRES):
                    continue
                rep = self.client.post(self.url(motif), {"action": "enregistrer", "valeur": "999", "nom": "Essai"})
                self.assertEqual(rep.status_code, 403, f"{u.role} POST {ns}:{nom}")
        self.assertEqual(instantane(), avant)

    def test_pages_ouvertes_au_lecteur_et_a_l_auditeur(self):
        from django.test import RequestFactory

        rf, ouvertes, envois = RequestFactory(), {}, {}
        for u in (self.lecteur, self.auditeur):
            ouvertes[u.role] = {f"{ns}:{nom}" for ns, nom, motif in routes() if not LS.motif_refus(u, rf.get(self.url(motif)))}
            envois[u.role] = {f"{ns}:{nom}" for ns, nom, motif in routes() if not LS.motif_refus(u, rf.post(self.url(motif)))}
        libres = {"None:login", "None:logout", "None:langue", "parametres:logo", "parametres:sante"}
        self.assertEqual(ouvertes["lecteur"] - libres, {f"collecte:{n}" for n in LS.PAGES_LECTEUR})
        self.assertEqual(ouvertes["auditeur"] - libres, {f"collecte:{n}" for n in LS.PAGES_AUDITEUR})
        self.assertEqual(LS.PAGES_AUDITEUR - LS.PAGES_LECTEUR,
                         {"saisie", "cellule", "preuve", "coherence", "alerte", "historique", "echanges", "echanges_exporter",
                          "certificat_cloture",  # page à imprimer d'une campagne clôturée, en lecture (partielle si limité)
                          "historique_connexions",  # historique des connexions, en lecture 
                          "echanges_resume", "echanges_listes_page", "echanges_listes", "echanges_supprimer_reglage",
                          # gros export fabriqué en arrière-plan : son état et son fichier, en lecture (GET) seulement
                          "echanges_export_etat", "echanges_export_fichier"})
        self.assertFalse({"echanges_export_etat", "echanges_export_fichier"} & LS.ECRITURES_PERMISES)
        self.assertEqual(envois["lecteur"] - libres, {"collecte:mon_compte",
                                                      # Visualisation : données et Excel (lecture), vues personnelles
                                                      "collecte:visu_donnees", "collecte:visu_excel", "collecte:visu_vue_creer",
                                                      "collecte:visu_vue_enregistrer", "collecte:visu_vue_dupliquer",
                                                      "collecte:visu_vue_supprimer", "collecte:visu_vues_ordre",
                                                      "collecte:visu_vue_preferee",
                                                      "collecte:corbeille_restaurer"})  # « Annuler » une suppression faite soi-même
        self.assertEqual(envois["auditeur"] - libres, {f"collecte:{n}" for n in LS.ECRITURES_PERMISES})
        self.assertNotIn("collecte:cellule", envois["auditeur"])
        self.assertNotIn("collecte:echanges_importer", ouvertes["auditeur"])

    def test_envois_permis_ne_touchent_que_les_preferences(self):
        avant = instantane()
        self.client.force_login(self.auditeur)
        rep = self.client.post(reverse("collecte:echanges_exporter"), {"action": "telecharger", "presentation": "base", "exercices": ["courant"],
                                                                     "niveaux": E.N.codes()})
        self.assertEqual(rep.status_code, 200)
        self.assertIn("spreadsheetml", rep["Content-Type"])  # le fichier, pas le constructeur avec une erreur
        self.client.post(reverse("collecte:echanges_exporter"), {"action": "enregistrer", "nom": "Mon export", "partage": "on",
                                                                  "presentation": "base", "exercices": ["courant"]})
        r = ReglageExport.objects.get(nom="Mon export")  # enregistré pour lui seul
        self.assertEqual((r.proprietaire, r.partage), (self.auditeur, False))
        commun = ReglageExport.objects.create(nom="Export commun", proprietaire=self.admin, partage=True, parametres={})
        self.client.post(reverse("collecte:echanges_exporter"), {"action": "enregistrer", "modele": commun.pk, "nom": "Renommé",
                                                                  "presentation": "base", "exercices": ["courant"]})
        commun.refresh_from_db()
        self.assertEqual((commun.nom, commun.partage), ("Export commun", True))  # celui de l'admin reste intact
        self.assertEqual(self.client.post(reverse("collecte:echanges_supprimer_reglage", args=[commun.pk])).status_code, 403)
        self.assertTrue(ReglageExport.objects.filter(pk=commun.pk).exists())
        self.client.post(reverse("collecte:echanges_listes"), {"nom": "Ma liste", "kpis": ["EFF"], "partage": "on"})
        s = SelectionKPI.objects.get(nom="Ma liste")
        self.assertEqual((s.proprietaire, s.partage), (self.auditeur, False))
        self.client.post(reverse("collecte:echanges_resume"), {"presentation": "base", "exercices": ["courant"]})
        self.assertEqual(instantane(), avant)

    def test_vue_partagee_de_l_admin_ni_modifiee_ni_supprimee(self):
        vue = VueVisu.objects.create(nom="Comité", proprietaire=self.admin, partage=True, visuels=[{"id": "a", "type": "chiffre", "kpis": ["EFF"]}])
        for u in (self.lecteur, self.auditeur):
            self.client.force_login(u)
            rep = self.client.post(reverse("collecte:visu_vue_enregistrer", args=[vue.pk]), '{"version": 1, "nom": "Piraté"}',
                                   content_type="application/json")
            self.assertEqual(rep.status_code, 403, u.role)
            self.assertEqual(self.client.post(reverse("collecte:visu_vue_supprimer", args=[vue.pk])).status_code, 403)
            self.assertEqual(self.client.post(reverse("collecte:visu_tableau_modifier", args=[self.tableau_admin.pk])).status_code, 403)
        vue.refresh_from_db()
        self.assertEqual(vue.nom, "Comité")

    def test_superutilisateur_jamais_en_lecture_seule(self):
        u = Utilisateur.objects.create(username="su", email="su@exemple.test", role=Utilisateur.Role.LECTEUR, is_superuser=True)
        self.assertEqual((u.lecture_seule, u.est_admin, u.est_lecteur, u.est_auditeur, u.voit_tout), (False, True, False, False, True))
        self.assertIsNone(u.orgs_permises())

    def test_droits_sur_une_case_en_lecture_seule(self):
        for u in (self.lecteur, self.auditeur):
            d = S.droits(u, self.c, self.eff, self.e1)
            self.assertEqual((d.voir, d.modifier, d.repasser_brouillon), (True, False, False), u.role)
            self.assertEqual(d.motif, "Compte en lecture seule : vous ne pouvez rien modifier.")
            self.assertTrue(S.lecture_seule(u, self.c))
            with self.assertRaises(Exception):
                S.enregistrer(u, self.c, self.eff, self.e1, "1", False, "")
            with self.assertRaises(Exception):
                S.valider(u, self.c, self.eff, self.e1)
            self.assertEqual(S.cellules(u, personnel=True), [])  # jamais SPOC

    def test_certificat_de_cloture_par_role_et_perimetre(self):
        """Certificat de clôture : administrateur et auditeur (complet), auditeur limité à des organisations (partiel, seul
        cas passé du refus à la page) ; lecteur, limité ou non, contributeur et validateur refusés ; aucun envoi permis."""
        from . import administration as AD

        AD.changer_statut(self.admin, self.c, "cloturer")
        url = reverse("collecte:certificat_cloture", args=[self.c.pk])
        limite = Utilisateur.objects.create(username="aud-lim", email="aud-lim@exemple.test", role=Utilisateur.Role.AUDITEUR)
        limite.perimetre_lecture.add(self.e1)
        lecteur_limite = Utilisateur.objects.create(username="lec-lim", email="lec-lim@exemple.test", role=Utilisateur.Role.LECTEUR)
        lecteur_limite.perimetre_lecture.add(self.e1)
        avant = instantane()
        for u, attendu, partiel in ((self.admin, 200, False), (self.auditeur, 200, False), (limite, 200, True),
                                    (self.lecteur, 403, None), (lecteur_limite, 403, None), (self.contrib, 403, None),
                                    (self.validateur, 403, None)):
            self.client.force_login(u)
            rep = self.client.get(url)
            self.assertEqual(rep.status_code, attendu, u.username)
            if partiel is not None:
                self.assertEqual("data-partiel" in rep.content.decode(), partiel, u.username)
            if u.lecture_seule:
                self.assertEqual(self.client.post(url).status_code, 403, u.username)
        self.assertEqual(instantane(), avant)

    def test_perimetre_de_consultation_et_descendantes(self):
        self.lecteur.perimetre_lecture.add(self.p)
        u = Utilisateur.objects.get(pk=self.lecteur.pk)
        self.assertEqual(u.orgs_permises(), {self.p.id, self.e1.id, self.e2.id})
        self.assertIsNone(S.role_sur(u, self.eff, self.g))
        self.assertEqual(S.role_sur(u, self.eff, self.e2), "lecture")
        self.assertFalse(S.voit_calcules(u, self.g))
        self.assertTrue(S.voit_calcules(u, self.p))


class AutresRolesBalayageTests(Balayage):
    def admin_seulement(self):
        for ns, nom, motif in routes():
            if ns == "parametres" and nom not in ("sante", "logo"):
                yield ns, nom, motif
            elif ns == "collecte" and nom and (nom.startswith(("admin_", "referentiel", "regle")) or nom in ("attribuer",)):
                yield ns, nom, motif
            elif ns == "serveur_mcp" and nom == "reglages":  # Paramètres › Assistants (docs/mcp.md)
                yield ns, nom, motif

    def test_administration_refusee_au_contributeur_et_au_validateur(self):
        avant = instantane()
        for u in (self.contrib, self.validateur):
            self.client.force_login(u)
            for ns, nom, motif in self.admin_seulement():
                url = self.url(motif)
                self.assertIn(self.client.get(url).status_code, (403, 405), f"{u.role} GET {ns}:{nom}")
                self.assertEqual(self.client.post(url, {"action": "enregistrer"}).status_code, 403, f"{u.role} POST {ns}:{nom}")
        self.assertEqual(instantane(), avant)

    def test_assistant_ia_dans_le_balayage(self):
        """Prise IA (docs/ai_socket.md) : réglages, traductions et correspondances de reprise sont dans les pages
        d'administration balayées ci-dessus ; l'explication d'une alerte n'est jamais permise au lecteur ni à l'auditeur
        (une demande écrit au journal et compte dans un plafond payant), même en lecture (GET)."""
        admin = {f"{ns}:{nom}" for ns, nom, _ in self.admin_seulement()}
        self.assertTrue({"parametres:ia", "parametres:traductions_ia", "collecte:admin_reprise_ia"} <= admin)
        self.assertNotIn("alerte_ia", LS.PAGES_AUDITEUR | LS.ECRITURES_PERMISES)
        url = reverse("collecte:alerte_ia", args=[1])
        for u in (self.lecteur, self.auditeur):
            self.client.force_login(u)
            self.assertEqual(self.client.post(url).status_code, 403, u.role)
            self.assertEqual(self.client.get(url).status_code, 403, u.role)

    def test_sante_installation_dans_le_balayage(self):
        """Paramètres › Santé : page des Paramètres, réservée à l'administrateur de l'espace ; balayée
        ci-dessus pour le contributeur et le validateur, et pour le lecteur et l'auditeur (tout envoi refusé)."""
        admin = {f"{ns}:{nom}" for ns, nom, _ in self.admin_seulement()}
        self.assertIn("parametres:sante_installation", admin)
        url = reverse("parametres:sante_installation")
        for u in (self.lecteur, self.auditeur, self.contrib, self.validateur):
            self.client.force_login(u)
            self.assertEqual(self.client.get(url).status_code, 403, u.role)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_historique_des_connexions_dans_le_balayage(self):
        """Administration › Comptes › Historique des connexions : réservé à l'administrateur comme Comptes ;
        balayé ci-dessus pour le contributeur et le validateur, et pour le lecteur et l'auditeur (tout envoi refusé)."""
        admin = {f"{ns}:{nom}" for ns, nom, _ in self.admin_seulement()}
        self.assertIn("collecte:admin_connexions", admin)
        self.assertNotIn("admin_connexions", LS.PAGES_AUDITEUR | LS.PAGES_LECTEUR | LS.ECRITURES_PERMISES)
        url = reverse("collecte:admin_connexions")
        for u in (self.lecteur, self.auditeur, self.contrib, self.validateur):
            self.client.force_login(u)
            self.assertEqual(self.client.get(url).status_code, 403, u.role)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(url).status_code, 200)
        # l'auditeur la lit par son Historique : adresse à lui, lecture (GET) seulement
        self.assertIn("historique_connexions", LS.PAGES_AUDITEUR)
        self.assertNotIn("historique_connexions", LS.PAGES_LECTEUR | LS.ECRITURES_PERMISES)
        url = reverse("collecte:historique_connexions")
        for u in (self.lecteur, self.contrib, self.validateur):
            self.client.force_login(u)
            self.assertEqual(self.client.get(url).status_code, 403, u.role)
        for u, attendu in ((self.auditeur, 200), (self.admin, 200)):
            self.client.force_login(u)
            self.assertEqual(self.client.get(url).status_code, attendu, u.role)
        self.client.force_login(self.auditeur)
        self.assertEqual(self.client.post(url).status_code, 403)

    def test_comptes_en_lecture_seule_avec_attributions_dans_le_balayage(self):
        """Page des comptes en lecture seule qui ont encore des attributions : réservée à
        l'administrateur comme Comptes et Attributions ; balayée ci-dessus pour le contributeur et le validateur, et pour
        le lecteur et l'auditeur (tout envoi refusé)."""
        admin = {f"{ns}:{nom}" for ns, nom, _ in self.admin_seulement()}
        self.assertIn("collecte:admin_attributions_lecture_seule", admin)
        self.assertNotIn("admin_attributions_lecture_seule", LS.PAGES_AUDITEUR | LS.PAGES_LECTEUR | LS.ECRITURES_PERMISES)
        url = reverse("collecte:admin_attributions_lecture_seule")
        for u in (self.lecteur, self.auditeur):
            self.client.force_login(u)
            self.assertEqual(self.client.get(url).status_code, 403, u.role)

    def test_choix_validateurs_des_attributions_dans_le_balayage(self):
        """Choix Validateurs des Attributions : même adresse (« ?role=validateur ») et même envoi
        (« attribuer » avec « role ») que la grille des contributeurs, réservés à l'administrateur pour tous les autres rôles."""
        import json

        admin = {f"{ns}:{nom}" for ns, nom, _ in self.admin_seulement()}
        self.assertTrue({"collecte:admin_attributions", "collecte:attribuer"} <= admin)
        avant = instantane()
        corps = json.dumps({"cles": [f"EFF|{self.e2.pk}"], "utilisateur": self.validateur.pk, "role": "validateur", "format": "cellule"})
        for u in (self.contrib, self.validateur, self.lecteur, self.auditeur):
            self.client.force_login(u)
            self.assertEqual(self.client.get(reverse("collecte:admin_attributions"), {"role": "validateur"}).status_code, 403, u.role)
            self.assertEqual(self.client.post(reverse("collecte:attribuer"), corps, content_type="application/json").status_code, 403, u.role)
        self.assertEqual(instantane(), avant)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("collecte:admin_attributions"), {"role": "validateur"}).status_code, 200)

    def test_monnaie_de_reference_dans_le_balayage(self):
        """Monnaie de référence (Paramètres › Unités et formats, parametres/monnaies.py) : même adresse que la page des
        unités, balayée ci-dessus ; l'envoi qui la règle est refusé à tous les rôles sauf l'administrateur."""
        from parametres.models import Instance

        admin = {f"{ns}:{nom}" for ns, nom, _ in self.admin_seulement()}
        self.assertIn("parametres:referentiel", admin)
        url = reverse("parametres:referentiel") + "?section=unites"
        avant = instantane()
        for u in (self.contrib, self.validateur, self.lecteur, self.auditeur):
            self.client.force_login(u)
            self.assertEqual(self.client.post(url, {"action": "monnaie", "monnaie": "USD"}).status_code, 403, u.role)
        self.assertEqual(instantane(), avant)
        self.assertEqual(Instance.courante().monnaie, "EUR")
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(url, {"action": "monnaie", "monnaie": "USD"}).status_code, 302)
        self.assertEqual(Instance.courante().monnaie, "USD")

    def test_relances_reservees_au_validateur_et_a_l_admin(self):
        self.client.force_login(self.contrib)
        self.assertEqual(self.client.get(reverse("collecte:relances")).status_code, 403)
        self.client.force_login(self.validateur)
        self.assertEqual(self.client.get(reverse("collecte:relances")).status_code, 200)

    def test_sans_connexion_renvoi_vers_la_connexion(self):
        self.client.logout()
        for ns, nom, motif in routes():
            # sans nom : anciennes adresses, redirigées ; « Données et confidentialité » : ouverte à tous (page de connexion)
            if nom in (None, "login", "logout", "sante", "logo", "langue", "confidentialite"):
                continue
            if (ns, nom) == ("serveur_mcp", "point"):  # assistants : jeton, jamais de session (serveur_mcp/test_*)
                self.assertEqual(self.client.get(self.url(motif)).status_code, 405)
                self.assertEqual(self.client.post(self.url(motif), "{}", content_type="application/json").status_code, 403)
                continue
            rep = self.client.get(self.url(motif))
            self.assertEqual(rep.status_code, 302, f"{ns}:{nom}")
            self.assertTrue(rep["Location"].startswith(reverse("login")), f"{ns}:{nom} → {rep['Location']}")
        self.assertEqual(self.client.get(reverse("parametres:sante")).status_code, 200)


class DroitsCaseTests(Balayage):
    def test_contributeur_selon_l_etat_de_la_campagne(self):
        d = S.droits(self.contrib, self.c, self.eff, self.e1)
        self.assertEqual((d.voir, d.modifier, d.repasser_brouillon), (True, True, True))
        self.assertEqual(S.role_sur(self.contrib, self.eff, self.e1), "contributeur")
        self.assertIsNone(S.role_sur(self.contrib, self.eff, self.e2))  # pas attribuée
        self.assertFalse(S.droits(self.contrib, self.c, self.eff, self.e2).voir)
        self.c.date_fin_saisie = timezone.localdate() - datetime.timedelta(days=1)
        self.c.save()
        c = Campagne.objects.get(pk=self.c.pk)
        d = S.droits(self.contrib, c, self.eff, self.e1)
        self.assertEqual((d.voir, d.modifier, d.repasser_brouillon), (True, False, False))
        d = S.droits(self.validateur, c, self.eff, self.e1)  # le validateur peut encore repasser en brouillon
        self.assertEqual((d.voir, d.modifier, d.repasser_brouillon), (True, False, True))
        d = S.droits(self.admin, c, self.eff, self.e1)
        self.assertEqual((d.modifier, d.repasser_brouillon), (True, True))
        c.statut = Campagne.Statut.CLOTUREE
        c.save()
        d = S.droits(self.admin, c, self.eff, self.e1)
        self.assertEqual((d.voir, d.modifier, d.repasser_brouillon), (True, False, False))  # clôturée : figée pour tous

    def test_validateur_voit_le_dessous_de_son_organisation(self):
        self.assertEqual(S.role_sur(self.validateur, self.eff, self.e1), "validateur")
        self.assertEqual(S.role_sur(self.validateur, self.eff, self.e2), "validateur")
        self.assertIsNone(S.role_sur(self.validateur, self.taux, self.e1))  # attribution pour EFF seulement
        self.assertTrue(S.voit_calcules(self.validateur, self.p))
        self.assertFalse(S.voit_calcules(self.validateur, self.g))
        d = S.droits(self.validateur, self.c, self.eff, self.p)  # agrégat : vu, jamais saisi
        self.assertEqual((d.voir, d.modifier, d.motif), (True, False, "Valeur calculée : vous ne pouvez pas la saisir."))
        self.assertFalse(S.droits(self.contrib, self.c, self.eff, self.p).voir)

    def test_kpi_ou_organisation_inactifs_hors_perimetre(self):
        KPI.objects.filter(code="EFF").update(actif=False)
        self.assertIsNone(S.role_sur(self.contrib, KPI.objects.get(code="EFF"), self.e1))
        KPI.objects.filter(code="EFF").update(actif=True)
        Organisation.objects.filter(pk=self.e1.pk).update(actif=False)
        self.assertIsNone(S.role_sur(self.contrib, self.eff, Organisation.objects.get(pk=self.e1.pk)))

    def test_contributeur_ne_valide_pas_hors_de_ses_cases(self):
        S.enregistrer(self.admin, self.c, self.eff, self.e2, "5", False, "")
        with self.assertRaises(Exception):
            S.valider(self.contrib, self.c, self.eff, self.e2)
        self.assertNotEqual(Reponse.objects.get(periode=self.c.periode, kpi=self.eff, organisation=self.e2).statut, Reponse.Statut.VALIDE)

    def test_seul_l_admin_attribue(self):
        with self.assertRaises(Exception):
            S.attribuer(self.validateur, [(self.eff, self.e2)], self.contrib)
        self.assertEqual(S.attribuer(self.admin, [(self.eff, self.e2)], self.contrib), 1)
        self.assertEqual(S.role_sur(self.contrib, self.eff, self.e2), "contributeur")

    def test_revenir_au_calcul_selon_le_role_par_la_page(self):
        """« Revenir au calcul » sur une valeur forcée, par le panneau de la case (vues_cellule) : l'administrateur et le
        validateur de l'organisation seulement ; le contributeur responsable du résultat, un contributeur sans attribution,
        le lecteur et l'auditeur sont refusés (403) et la valeur forcée reste en place."""
        Attribution.objects.create(kpi=self.calc, organisation=self.e1, utilisateur=self.contrib)  # responsable du résultat
        url = self.cellule("DBL")

        def case():
            return Reponse.objects.get(periode=self.c.periode, kpi=self.calc, organisation=self.e1)

        def forcer():
            FO.demander(self.admin, self.c, self.calc, self.e1, "75", False, "Chiffre publié")
            self.assertEqual(case().origine, Reponse.Origine.FORCEE)

        forcer()
        for u in (self.contrib, self.autre, self.lecteur, self.auditeur):
            self.client.force_login(u)
            rep = self.client.post(url, {"action": "revenir_calcul", "motif": "Essai"}, HTTP_X_REQUESTED_WITH="fetch")
            self.assertEqual(rep.status_code, 403, u.username)
            self.assertEqual((case().origine, case().valeur), (Reponse.Origine.FORCEE, 75), u.username)
        for u in (self.validateur, self.admin):
            self.client.force_login(u)
            rep = self.client.post(url, {"action": "revenir_calcul", "motif": "Détail complet"}, HTTP_X_REQUESTED_WITH="fetch")
            self.assertEqual(rep.status_code, 200, u.username)
            self.assertTrue(rep.json()["ok"], u.username)
            self.assertEqual((case().origine, case().valeur), (Reponse.Origine.CALCUL, 220), u.username)  # 110 × 2
            forcer()
