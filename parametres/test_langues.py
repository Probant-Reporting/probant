"""Langues des contenus : langues réglables, langue de chaque utilisateur, traductions avec repli (noms, descriptions,
thèmes, libellés, valeurs de listes), page Paramètres › Langues et Traductions, fiche KPI par langue, exports dans une
langue, réponses de liste importées dans n'importe quelle langue, classeur de configuration multilingue."""
import datetime
import io

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from openpyxl import Workbook, load_workbook

from collecte import configuration as C
from collecte import exports as E
from collecte import imports as I
from collecte import reglages as R
from collecte import saisie as S
from collecte.calcul import recalculer
from collecte.models import Campagne, Journal
from referentiel.echange import enregistrer_descriptions
from referentiel.composition import composer
from referentiel.models import KPI, Attribution, Niveau, Organisation, Theme, Utilisateur
from referentiel.plans import Plan

from . import langues as L
from . import traductions as TR
from .models import Instance, Langue, NiveauHierarchique, TypeReponse, Unite
from collecte.outils_tests import xlsx
from collecte.aides_tests.echanges import Base as BaseEchanges
from parametres.referentiel import traduire_unite, unite_depuis_symbole
from collecte.outils_tests import html_de

FETCH = {"HTTP_X_REQUESTED_WITH": "fetch"}


class Base(TestCase):
    def setUp(self):
        Langue.objects.create(code="es", libelle="Español", ordre=3)
        self.g = Organisation.objects.create(nom="Groupe", niveau_id=Niveau.GROUP)
        self.p = Organisation.objects.create(nom="Pays", niveau_id=Niveau.COUNTRY, parent=self.g)
        self.e1 = Organisation.objects.create(nom="E1", niveau_id=Niveau.ENTITY, parent=self.p)
        self.e2 = Organisation.objects.create(nom="E2", niveau_id=Niveau.ENTITY, parent=self.p)
        self.c = Campagne.objects.create(exercice=2026, statut=Campagne.Statut.OUVERTE,
                                         date_fin_saisie=timezone.localdate() + datetime.timedelta(days=30))
        self.certif = TypeReponse.objects.create(code="Certif", libelle="Certification", format="liste", ordre=11,
                                                 valeurs=["Certifié", "En cours", "Non engagé"],
                                                 traductions={"en": {"valeurs": ["Certified", "In progress", "Not engaged"]},
                                                              "es": {"libelle": "Certificación", "valeurs": ["Certificado", "En curso", ""]}})
        self.oui_non = TypeReponse.objects.create(code="OuiNon", libelle="Oui / non", format="oui_non", ordre=10,
                                                  traductions={"es": {"valeurs": ["Sí", "No"]}})
        self.eff = KPI.objects.create(code="EFF", libelle="Effectif", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                                      methode_agregation="Somme", traductions={"en": {"libelle": "Headcount"}})
        self.cert = KPI.objects.create(code="CERT", libelle="Certification du site", type_saisie_id="Saisi", type_reponse=self.certif,
                                       granularite_id=Niveau.ENTITY, methode_agregation="Décompte")
        self.pol = KPI.objects.create(code="POL", libelle="Politique formalisée", type_saisie_id="Saisi", type_reponse=self.oui_non,
                                      granularite_id=Niveau.ENTITY, methode_agregation="Décompte")
        composer({"EFF": ["Social"], "CERT": ["Environnement"], "POL": ["Social"]})
        env = Theme.objects.get(nom="Environnement")
        L.definir(env, "nom", "es", "Medio ambiente")
        env.save()
        enregistrer_descriptions(self.eff, {"description": "Effectif au 31/12."})
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN)
        self.contrib = Utilisateur.objects.create(username="contrib", email="contrib@exemple.test", langue="es")
        for k in (self.eff, self.cert, self.pol):
            Attribution.objects.create(kpi=k, organisation=self.e1, utilisateur=self.contrib)


class LanguesTests(Base):
    def test_langues_d_installation_et_reference(self):
        self.assertEqual(L.reference(), "fr")
        self.assertEqual(L.defaut(), "fr")
        self.assertEqual(L.codes_actifs(), ["fr", "en", "es"])

    def test_repli_vers_la_langue_par_defaut_puis_une_autre(self):
        with L.activer("en"):
            self.assertEqual(self.eff.nom, "Headcount")
            self.assertEqual(self.cert.nom, "Certification du site")  # pas traduit : la référence
        with L.activer("es"):
            self.assertEqual(self.eff.nom, "Effectif")
            self.assertEqual(Plan().titres("CERT")[0], "Medio ambiente")
            self.assertEqual(Plan().titres("EFF")[0], "Social")
            self.assertEqual(self.eff.texte_description("description"), "Effectif au 31/12.")  # repli
        anglais = KPI.objects.create(code="EN", libelle="", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                                     traductions={"en": {"libelle": "Only in English"}})
        self.assertEqual(anglais.nom, "Only in English")  # pas de nom de référence : une autre langue

    def test_reponses_de_liste_stockees_en_reference_affichees_traduites(self):
        S.enregistrer(self.admin, self.c, self.cert, self.e1, "Certified", False, "")  # écrit en anglais
        r = S.reponse_de(self.c, self.cert, self.e1)
        self.assertEqual(r.texte, "Certifié")
        S.enregistrer(self.admin, self.c, self.pol, self.e1, "sí", False, "")
        self.assertEqual(S.reponse_de(self.c, self.pol, self.e1).texte, "Oui")
        with L.activer("es"):
            self.assertEqual(self.cert.reponse_affichee("Certifié"), "Certificado")
            self.assertEqual(self.cert.reponse_affichee("Non engagé"), "Non engagé")  # valeur non traduite : la référence
            self.assertEqual(self.pol.reponse_affichee("Oui : 2 · Non : 1"), "Sí : 2 · No : 1")  # décompte

    def test_decompte_affiche_dans_la_langue(self):
        for o, v in ((self.e1, "Certifié"), (self.e2, "En cours")):
            S.enregistrer(self.admin, self.c, self.cert, o, v, False, "")
            S.valider(self.admin, self.c, self.cert, o)
        recalculer(self.c)
        from collecte.templatetags.collecte import valeur

        r = S.reponse_de(self.c, self.cert, self.p)
        with L.activer("en"):
            self.assertEqual(valeur(r, self.cert), "Certified : 1 · In progress : 1")

    def test_utilisateur_lit_dans_sa_langue(self):
        self.client.force_login(self.contrib)
        rep = self.client.get(reverse("collecte:saisie"))
        self.assertContains(rep, "Medio ambiente")
        html = self.client.get(reverse("collecte:cellule", args=[self.c.pk, "CERT", self.e1.id]), **FETCH).json()["html"]
        self.assertIn("Certificado", html)
        self.assertIn('value="Certifié"', html)  # la valeur envoyée reste la référence
        Langue.objects.filter(code="es").update(active=False)  # langue désactivée : retour à la langue par défaut
        self.assertContains(self.client.get(reverse("collecte:saisie")), "Environnement")

    def test_mon_compte_choisir_sa_langue(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("collecte:mon_compte"), {"action": "langue", "langue": "en"})
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.langue, "en")
        self.client.post(reverse("collecte:mon_compte"), {"action": "langue", "langue": "xx"})  # inconnue : ignorée
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.langue, "en")


class PageLanguesTests(Base):
    URL = reverse("parametres:langues")

    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)

    def test_reserve_a_l_admin(self):
        self.client.force_login(self.contrib)
        self.assertEqual(self.client.get(self.URL).status_code, 403)

    def test_ajouter_une_langue_puis_la_supprimer(self):
        """Une langue sans texte fourni par l'outil (le japonais) : ajoutée, montée, supprimée. L'allemand, l'italien, le
        néerlandais et le portugais ont des textes de départ (parametres/0036) : comme l'anglais et l'espagnol, ils comptent
        comme utilisés (voir ``test_langue_a_textes_fournis_compte_comme_utilisee``)."""
        rep = self.client.post(self.URL, {"action": "ajouter", "code": "ja", "libelle": "日本語"})
        self.assertEqual(rep.status_code, 302)
        self.assertEqual(Langue.objects.get(code="ja").ordre, 4)
        self.assertContains(self.client.post(self.URL, {"action": "ajouter", "code": "JA!"}), "Code de langue")
        self.assertContains(self.client.post(self.URL, {"action": "ajouter", "code": "ja"}), "existe déjà")
        self.client.post(self.URL, {"monter": "ja"})
        self.assertEqual(list(Langue.objects.values_list("code", flat=True)), ["fr", "en", "ja", "es"])
        self.client.post(self.URL, {"supprimer": "ja"})
        self.assertFalse(Langue.objects.filter(code="ja").exists())
        self.assertTrue(Journal.objects.filter(action="reglage_langues").exists())

    def test_langue_a_textes_fournis_compte_comme_utilisee(self):
        from parametres import langues as L

        self.assertTrue({"en", "es", "de", "it", "nl", "pt"} <= L.langues_utilisees())
        self.client.post(self.URL, {"action": "ajouter", "code": "de", "libelle": "Deutsch"})
        self.client.post(self.URL, {"supprimer": "de"})
        self.assertTrue(Langue.objects.filter(code="de").exists())

    def test_langue_utilisee_ne_se_supprime_pas(self):
        rep = self.client.post(self.URL, {"supprimer": "es"})  # préférence d'un compte, traductions
        self.assertContains(rep, "est utilisée")
        self.assertContains(self.client.post(self.URL, {"supprimer": "fr"}), "est utilisée")

    def test_langue_par_defaut_et_activation(self):
        donnees = {"action": "enregistrer", "defaut": "es", "libelle__fr": "Français", "libelle__en": "English", "libelle__es": "Español",
                   "active__en": "on"}  # es reste active : c'est la langue par défaut ; fr : la référence
        self.client.post(self.URL, donnees)
        self.assertEqual(Instance.courante().langue, "es")
        self.assertTrue(Langue.objects.get(code="es").active and Langue.objects.get(code="fr").active)
        with L.session():
            self.assertEqual(Plan().titres("CERT")[0], "Medio ambiente")  # hors requête : langue par défaut
        donnees.update(defaut="fr")
        donnees.pop("active__en")
        self.client.post(self.URL, donnees)
        self.assertFalse(Langue.objects.get(code="en").active)
        self.assertNotIn("en", L.codes_actifs())

    def test_page_traductions(self):
        url = reverse("parametres:traductions", args=["es"])
        rep = self.client.get(url + "?section=kpi")
        self.assertContains(rep, "Certification du site")
        self.client.post(url + "?section=kpi", {"kpi|CERT": "Certificación del centro", "kpi|EFF": ""})
        self.cert.refresh_from_db()
        with L.activer("es"):
            self.assertEqual(self.cert.nom, "Certificación del centro")
        self.client.post(url + "?section=descriptions", {"desc|description|EFF": "Plantilla a 31/12."})
        self.assertEqual(self.eff.texte_description("description", "es", repli=False), "Plantilla a 31/12.")
        social = Theme.objects.get(nom="Social")
        self.client.post(url + "?section=themes", {f"theme|{social.pk}": "Social (ES)"})
        social.refresh_from_db()
        self.assertEqual(social.tr("nom", "es"), "Social (ES)")
        self.client.post(url + "?section=libelles", {"obj|niveaux|nom|Entity": "Entidad", "val|types-reponse|2|Certif": "No comprometido"})
        self.assertEqual(NiveauHierarchique.objects.get(pk="Entity").tr("nom", "es"), "Entidad")
        self.certif.refresh_from_db()
        self.assertEqual(self.certif.choix_traduits("es")[2], ("Non engagé", "No comprometido"))
        self.assertTrue(Journal.objects.filter(action="traduction").exists())
        faits, total = TR.completude("es")[1]
        self.assertGreater(faits, 0)
        self.assertLessEqual(faits, total)

    def test_symbole_d_unite_facultatif(self):
        Unite.objects.create(code="kWh2", symbole="kWh", libelle="kilowattheure")
        a_traduire = [e.cle for e in TR.elements("es", "libelles")]
        self.assertIn("obj|unites|libelle|kWh2", a_traduire)
        self.assertNotIn("obj|unites|symbole|kWh2", a_traduire)


class FicheKPILanguesTests(Base):
    def fiche(self, kpi, **changes):
        donnees = {c: getattr(kpi, f"{c}_id" if c in ("granularite", "type_saisie", "type_reponse", "unite") else c)
                   for c in R.CHAMPS_FICHE}
        donnees.update({f"nom__{l}": L.texte(kpi, "libelle", l) for l in ("fr", "en", "es")})  # tous les champs, comme la page
        donnees.update(changes)
        return {c: v for c, v in donnees.items() if v is not False and v is not None}

    def test_traduire_un_kpi_dans_la_fiche(self):
        self.client.force_login(self.admin)
        url = reverse("collecte:referentiel_kpi", args=["EFF"])
        html = self.client.get(url, **FETCH).json()["html"]
        self.assertIn('data-onglet-langue="es"', html)
        self.assertIn("0/2", html)  # espagnol : nom et description à traduire (le thème se traduit avec le référentiel)
        res = self.client.post(url, self.fiche(self.eff, nom__es="Plantilla", desc_description__es="Plantilla a 31/12."), **FETCH).json()
        self.assertTrue(res["ok"], res["html"])
        self.eff.refresh_from_db()
        with L.activer("es"):
            self.assertEqual(self.eff.nom, "Plantilla")
            self.assertEqual(self.eff.texte_description("description"), "Plantilla a 31/12.")
        self.assertEqual(L.texte(self.eff, "libelle", "en"), "Headcount")  # les autres langues restent
        self.assertTrue(Journal.objects.filter(action="reglage_kpi", champ="Nom (ES)").exists())
        # référentiel : filtre « à traduire »
        rep = self.client.get(reverse("collecte:referentiel"))
        self.assertContains(rep, 'id="filtre-traduction"')
        self.assertContains(rep, 'data-a-traduire="en es"')  # CERT : nom à traduire en anglais et en espagnol


class EchangesLanguesTests(Base):
    def test_exporter_en_espagnol(self):
        S.enregistrer(self.admin, self.c, self.cert, self.e1, "Certifié", False, "")
        NiveauHierarchique.objects.filter(pk="Entity").update(traductions={"es": {"nom": "Entidad", "nom_pluriel": "Entidades"}})
        self.cert.traductions = {"es": {"libelle": "Certificación del centro"}}
        self.cert.save()
        p = E.Parametres.depuis({"presentation": "base", "langue": "es"})
        wb = load_workbook(io.BytesIO(E.exporter(self.admin, p).content))
        self.assertEqual(wb.sheetnames, ["Léame", "Valores", "KPI", "Organizaciones"])  # termes de l'outil en espagnol (suivi.es.json)
        ws = wb["Valores"]
        tete = [c.value for c in ws[1]]
        self.assertIn("Indicador", tete)
        self.assertIn("Entidad", tete)  # colonne du niveau
        ligne = next(r for r in ws.iter_rows(min_row=2, values_only=True) if r[tete.index("ID KPI")] == "CERT" and r[tete.index("Organización")] == "E1")
        self.assertEqual((ligne[tete.index("Indicador")], ligne[tete.index("Tema")], ligne[tete.index("Valor")]),
                         ("Certificación del centro", "Medio ambiente", "Certificado"))
        # une langue des contenus sans fichiers de langue (ni français, anglais, espagnol) : termes en anglais, comme avant
        Langue.objects.update_or_create(code="ja", defaults={"libelle": "日本語", "active": True})
        wb = load_workbook(io.BytesIO(E.exporter(self.admin, E.Parametres.depuis({"presentation": "base", "langue": "ja"})).content))
        self.assertEqual(wb.sheetnames, ["Read me", "Values", "KPI", "Organisations"])
        self.assertEqual(E.Parametres.depuis({"langue": "xx"}).langue, "")  # langue inconnue : celle de la personne

    def test_importer_une_reponse_de_liste_en_anglais(self):
        f = xlsx(onglet=None, lignes=[["ID KPI", "Organisation", "Exercice", "Valeur"], ["CERT", "E1", 2026, "in progress"], ["POL", "E1", 2026, "No"]])
        a = I.analyser(self.admin, f)
        self.assertEqual([(l.kpi_id, l.action, l.texte) for l in a.lignes], [("CERT", "creer", "En cours"), ("POL", "creer", "Non")])
        f.seek(0)
        I.appliquer(self.admin, f, "fichier.xlsx")
        self.assertEqual(S.reponse_de(self.c, self.cert, self.e1).texte, "En cours")

    def test_classeur_de_configuration_multilingue(self):
        wb = load_workbook(io.BytesIO(C.exporter().content))
        self.assertIn("Langues", wb.sheetnames)
        self.assertIn("Thèmes", wb.sheetnames)
        tete = [c.value for c in wb["KPI"][1]]
        for t in ("Nom (FR)", "Nom (EN)", "Nom (ES)", "Description (FR)", "Description (ES)"):
            self.assertIn(t, tete)
        self.assertIn("Valeurs possibles (EN)", [c.value for c in wb["Types de réponse"][1]])
        self.assertIn("Nom au pluriel (ES)", [c.value for c in wb["Niveaux"][1]])
        flux = io.BytesIO()
        wb.save(flux)
        a = C.analyser(SimpleUploadedFile("config.xlsx", flux.getvalue()))
        self.assertFalse(a.erreur)
        self.assertEqual({c.action for cs in a.onglets.values() for c in cs}, {"inchange"})  # aller-retour sans changement
        # modifier : un nom espagnol, une valeur de liste anglaise, un thème, une nouvelle langue
        ws = wb["KPI"]
        ligne = next(r[0].row for r in ws.iter_rows(min_row=2) if r[0].value == "CERT")
        ws.cell(ligne, tete.index("Nom (ES)") + 1, "Certificación del centro")
        tr = wb["Types de réponse"]
        tt = [c.value for c in tr[1]]
        lc = next(r[0].row for r in tr.iter_rows(min_row=2) if r[0].value == "Certif")
        tr.cell(lc, tt.index("Valeurs possibles (EN)") + 1, "Certified ; Ongoing ; Not engaged")
        th = wb["Thèmes"]
        tt = [c.value for c in th[1]]
        ls = next(r[0].row for r in th.iter_rows(min_row=2) if r[tt.index("Code")].value == "Social")
        th.cell(ls, tt.index("Nom (EN)") + 1, "Social affairs")
        wb["Langues"].append(["it", "Italiano", 9, "Non", "Non"])
        flux = io.BytesIO()
        wb.save(flux)
        f = SimpleUploadedFile("config.xlsx", flux.getvalue())
        a = C.analyser(f)
        changes = {(nom, c.cle): c.action for nom, cs in a.onglets.items() for c in cs if c.action != "inchange"}
        self.assertEqual(changes, {("KPI", "CERT"): "modifier", ("Types de réponse", "Certif"): "modifier", ("Thèmes", "REPORTING · Social"): "modifier",
                                   ("Langues", "it"): "creer"})
        f.seek(0)
        C.appliquer(self.admin, f, "config.xlsx")
        self.cert.refresh_from_db()
        self.certif.refresh_from_db()
        self.assertEqual(L.texte(self.cert, "libelle", "es"), "Certificación del centro")
        self.assertEqual(self.certif.choix_traduits("en")[1], ("En cours", "Ongoing"))
        self.assertEqual(Theme.objects.get(nom="Social").tr("nom", "en"), "Social affairs")
        self.assertFalse(Langue.objects.get(code="it").active)

    def test_ancien_classeur_sans_langue_accepte(self):
        """En-têtes d'avant les langues (« Nom (FR) », « Description », « Libellé ») : la langue de référence."""
        wb = Workbook()
        ws = wb.active
        ws.title = "KPI"
        ws.append(["Code", "Thème", "Nom (FR)", "Nom (EN)", "Type de saisie", "Type de réponse", "Granularité", "Agrégation", "Description"])
        ws.append(["NEUF", "Social", "Nouveau KPI", "New KPI", "Saisi", "Numérique", "Entité", "Somme", "Texte de référence"])
        flux = io.BytesIO()
        wb.save(flux)
        f = SimpleUploadedFile("ancien.xlsx", flux.getvalue())
        C.appliquer(self.admin, f, "ancien.xlsx")
        k = KPI.objects.get(pk="NEUF")
        self.assertEqual((k.libelle, L.texte(k, "libelle", "en"), k.texte_description("description", "fr", repli=False)),
                         ("Nouveau KPI", "New KPI", "Texte de référence"))
        e = k.elements.get()  # ancienne colonne « Thème » : rangé dans le référentiel par défaut, thème existant réutilisé
        self.assertEqual((e.referentiel_id, e.theme), ("REPORTING", Theme.objects.get(nom="Social")))


class TraductionsFichierTests(Base):
    """Paramètres › Langues › Traductions : exporter ce qui manque, traduire hors de l'outil (IA…), réimporter avec aperçu."""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.admin)

    def _fichier(self, rep):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(rep.content))
        ws = wb["Traductions"]
        rangs = [list(r) for r in ws.iter_rows(values_only=True)]
        return wb, ws, rangs, SimpleUploadedFile

    def test_export_traduction_import_avec_apercu(self):
        url = reverse("parametres:traductions_export", args=["es"])
        wb, ws, rangs, Fichier = self._fichier(self.client.get(url))
        self.assertEqual(rangs[0], ["Clé", "Section", "Élément", "Texte de départ", "Traduction (ES)"])
        cles = {r[0]: i for i, r in enumerate(rangs)}
        self.assertIn("kpi|EFF", cles)
        self.assertNotIn("theme|" + str(Theme.objects.get(nom="Environnement").pk), cles)  # déjà traduit en espagnol
        self.assertIn("Lisez-moi", wb.sheetnames)
        # traduction (comme le ferait une IA) : une ligne remplie, une laissée vide
        ws.cell(cles["kpi|EFF"] + 1, 5, "Plantilla")
        ws.cell(cles["desc|description|EFF"] + 1, 5, "Plantilla a 31/12.")
        flux = io.BytesIO()
        wb.save(flux)
        rep = self.client.post(reverse("parametres:traductions_import", args=["es"]),
                               {"fichier": Fichier("trad.xlsx", flux.getvalue())})
        self.assertContains(rep, "Plantilla")
        self.assertContains(rep, "2</strong> traductions à enregistrer")
        self.eff.refresh_from_db()
        self.assertEqual(L.texte(self.eff, "libelle", "es"), "")  # rien d'enregistré avant confirmation
        self.client.post(reverse("parametres:traductions_import", args=["es"]), {"action": "appliquer"})
        self.eff.refresh_from_db()
        self.assertEqual(L.texte(self.eff, "libelle", "es"), "Plantilla")
        self.assertEqual(self.eff.texte_description("description", "es", repli=False), "Plantilla a 31/12.")

    def test_tout_exporter_en_csv_et_cellule_vide_n_efface_rien(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        rep = self.client.get(reverse("parametres:traductions_export", args=["es"]) + "?tout=1&format=csv")
        texte = rep.content.decode("utf-8-sig")
        self.assertIn("Medio ambiente", texte)  # « tout » : aussi ce qui est déjà traduit
        vide = texte.replace("Medio ambiente", "")
        rep = self.client.post(reverse("parametres:traductions_import", args=["es"]),
                               {"fichier": SimpleUploadedFile("t.csv", vide.encode("utf-8"))})
        self.assertContains(rep, "Aucun changement")
        self.assertEqual(L.texte(Theme.objects.get(nom="Environnement"), "nom", "es"), "Medio ambiente")

    def test_un_fichier_pour_toutes_les_langues(self):
        Langue.objects.filter(code__in=["en", "es"]).update(active=True)
        wb, ws, rangs, Fichier = self._fichier(self.client.get(reverse("parametres:traductions_export", args=["toutes"])))
        self.assertEqual(rangs[0][4:], ["Traduction (EN)", "Traduction (ES)"])
        cles = {r[0]: i for i, r in enumerate(rangs)}
        self.assertEqual(rangs[cles["kpi|EFF"]][4], "Headcount")  # déjà traduit en anglais, manque en espagnol
        ws.cell(cles["kpi|POL"] + 1, 5, "Formal policy")
        ws.cell(cles["kpi|POL"] + 1, 6, "Política formal")
        flux = io.BytesIO()
        wb.save(flux)
        rep = self.client.post(reverse("parametres:traductions_import", args=["toutes"]), {"fichier": Fichier("t.xlsx", flux.getvalue())})
        self.assertContains(rep, "Enregistrer les 2 traductions")
        self.client.post(reverse("parametres:traductions_import", args=["toutes"]), {"action": "appliquer"})
        self.pol.refresh_from_db()
        self.assertEqual((L.texte(self.pol, "libelle", "en"), L.texte(self.pol, "libelle", "es")), ("Formal policy", "Política formal"))
        self.assertContains(self.client.get(reverse("parametres:langues")), "Traduire toutes les langues d'un coup")


class TraductionsDesTypesFournisTests(TestCase):
    """Une installation neuve a les types de réponse fournis traduits en anglais (« Number »,
    « Percentage ») ; une installation qui a déjà des KPI garde ses libellés (migration parametres/0015)."""

    def test_installation_neuve_traduite(self):
        from .models import TypeReponse

        self.assertEqual({t.code: (t.traductions or {}).get("en", {}).get("libelle") for t in TypeReponse.objects.all()},
                         {"Numérique": "Number", "Pourcentage": "Percentage", "TexteRedige": "Written text"})

    def test_installation_existante_inchangee(self):
        import importlib

        from django.apps import apps

        from .models import TypeReponse

        migration = importlib.import_module("parametres.migrations.0015_types_reponse_en")
        t = TypeReponse.objects.get(code="Numérique")
        t.traductions = {}
        t.save()
        KPI.objects.create(code="K1", libelle="Un KPI", type_saisie_id="Saisi", granularite_id=Niveau.SITE)
        migration.traduire(apps, None)
        t.refresh_from_db()
        self.assertEqual(t.traductions, {})  # déjà des KPI : rien ne change
        KPI.objects.all().delete()
        migration.traduire(apps, None)
        t.refresh_from_db()
        self.assertEqual(t.traductions, {"en": {"libelle": "Number"}})


class UnitesTraduitesTests(BaseEchanges):
    def test_unite_anglaise_creee_en_francais_avec_traductions(self):
        u = unite_depuis_symbole("employees")
        self.assertEqual((u.code, u.symbole), ("employees", "salariés"))  # le code, clé des fichiers, ne change pas
        self.assertEqual((u.tr("symbole", "en"), u.tr("symbole", "es")), ("employees", "empleados"))
        self.assertEqual(unite_depuis_symbole("employees"), u)  # réimport du référentiel : la même unité, pas un doublon

    def test_traduction_saisie_jamais_remplacee_et_unite_inconnue_intacte(self):
        u = Unite(code="members", symbole="members", traductions={"es": {"symbole": "socios"}})
        self.assertTrue(traduire_unite(u, "fr"))
        self.assertEqual((u.symbole, u.traductions["es"]["symbole"], u.traductions["en"]["symbole"]), ("membres", "socios", "members"))
        v = Unite(code="kWh", symbole="kWh")
        self.assertFalse(traduire_unite(v, "fr"))
        self.assertEqual((v.symbole, v.traductions or {}), ("kWh", {}))

    def test_unite_anglaise_creee_par_le_classeur_de_configuration(self):
        """Unité citée dans l'onglet KPI du classeur de configuration, inconnue : créée traduite, comme à l'import d'un
        référentiel (parametres.referentiel.nouvelle_unite) ; son code reste le texte du fichier."""
        from openpyxl import load_workbook

        from collecte import configuration as C

        from collecte.models import Reponse

        Reponse.objects.filter(kpi_id="EFF").delete()  # désormais, un KPI qui a des valeurs garde son unité
        wb = load_workbook(io.BytesIO(C.exporter().content))
        ws = wb["KPI"]
        tete = [c.value for c in ws[1]]
        ligne = next(r for r in ws.iter_rows(min_row=2) if r[tete.index("ID KPI")].value == "EFF")
        ligne[tete.index("Unité")].value = "interns"
        flux = io.BytesIO()
        wb.save(flux)
        C.appliquer(self.admin, SimpleUploadedFile("config.xlsx", flux.getvalue()), "config.xlsx")
        u = Unite.objects.get(code="interns")
        self.assertEqual((u.symbole, u.tr("symbole", "en"), u.tr("symbole", "es")), ("stagiaires", "interns", "becarios"))
        self.assertEqual(self.eff.__class__.objects.get(pk="EFF").unite_id, "interns")

    def test_unite_anglaise_deja_fournie_n_est_pas_creee_en_double(self):
        """« employees » est la traduction anglaise de l'unité fournie « salariés » (parametres/0036) : le classeur de
        configuration la retrouve et ne crée pas une seconde unité."""
        from openpyxl import load_workbook

        from collecte import configuration as C

        from collecte.models import Reponse

        Reponse.objects.filter(kpi_id="EFF").delete()  # désormais, un KPI qui a des valeurs garde son unité
        wb = load_workbook(io.BytesIO(C.exporter().content))
        ws = wb["KPI"]
        tete = [c.value for c in ws[1]]
        ligne = next(r for r in ws.iter_rows(min_row=2) if r[tete.index("ID KPI")].value == "EFF")
        ligne[tete.index("Unité")].value = "employees"
        flux = io.BytesIO()
        wb.save(flux)
        C.appliquer(self.admin, SimpleUploadedFile("config.xlsx", flux.getvalue()), "config.xlsx")
        self.assertFalse(Unite.objects.filter(code="employees").exists())
        self.assertEqual(self.eff.__class__.objects.get(pk="EFF").unite_id, "salariés")


class BaseAdminFr(TestCase):
    def setUp(self):
        self.admin = Utilisateur.objects.create(username="admin", email="admin@exemple.test", role=Utilisateur.Role.ADMIN,
                                                langue="fr")
        self.client.force_login(self.admin)


class LanguesPageTests(BaseAdminFr):
    URL = reverse("parametres:langues")

    def setUp(self):
        super().setUp()
        Langue.objects.get_or_create(code="fr", defaults={"libelle": "Français"})
        Langue.objects.get_or_create(code="en", defaults={"libelle": "English"})
        Instance.objects.filter(pk=Instance.courante().pk).update(langue="en")

    def test_reference_et_defaut_expliques_sur_les_cartes(self):
        html = html_de(self.client, self.URL)
        # chaque mot est suivi de sa définition, sur la carte de la langue qui porte ce rôle
        self.assertIn("Langue de référence</span></dt><dd>Vous écrivez les KPI et les réglages dans cette langue.", html)
        self.assertIn("Langue par défaut</span></dt><dd>L'outil l'affiche aux personnes qui n'ont pas choisi leur langue", html)
        self.assertEqual(html.count("<dd>Vous écrivez les KPI"), 1)  # une seule langue de référence
        self.assertEqual(html.count("<dd>L'outil l'affiche aux personnes"), 1)  # une seule langue par défaut
        self.assertNotIn("Référence ou par défaut ?", html)  # plus répété dans « Bon à savoir »

    def test_etapes_en_liste(self):
        html = html_de(self.client, self.URL)
        if "Traduire toutes les langues" in html:  # affiché seulement s'il reste des textes à traduire
            for etape in ("<li>Exportez ce qui reste à traduire.</li>", "<li>Remplissez le fichier à la main ou avec une IA.",
                          "<li>Importez le fichier."):
                self.assertIn(etape, html)
        self.assertNotIn("<strong>1.</strong>", html)
