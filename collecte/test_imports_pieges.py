"""Imports piégés (qa/import_traps.py) : échantillon représentatif des fichiers abîmés ou
bizarres essayés par centaines, et non-régression des défauts trouvés. Pour chacun : jamais d'erreur 500, rien d'écrit
quand le fichier est refusé, un message clair, rien d'écrit dans une campagne clôturée par un contributeur."""
import codecs
import datetime
import io
import json
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from openpyxl import Workbook, load_workbook

from . import imports as I
from .models import Journal, Reponse
from .aides_tests.echanges import Base, classeur
from .outils_tests import xlsx
from .aides_tests import aller_retour as TE
from referentiel.models import KPI, Niveau
from . import fichiers as X, saisie as S
from .aides_tests.aller_retour import Base as BaseEchanges, fichier

D = Decimal
ENTETES = ["ID KPI", "Organisation", "Exercice", "Valeur", "Commentaire"]


def csv_fichier(texte, encodage="utf-8", nom="valeurs.csv"):
    return SimpleUploadedFile(nom, texte.encode(encodage) if isinstance(texte, str) else texte)


class ExerciceTests(Base):
    """Une date ou un texte dans la colonne « Exercice » : avant, l'année était cherchée dans les 4 derniers chiffres
    (« 31/12/2025 00:00 » → 0000), puis la ligne allait sans un mot dans la campagne choisie (2026)."""

    def test_date_dans_la_colonne_exercice(self):
        a = I.analyser(self.admin, xlsx([ENTETES, ["EFF", "E2", datetime.datetime(2025, 12, 31), 41]]), campagne_defaut=self.c.pk)
        l = a.lignes[0]
        self.assertEqual(l.campagne, self.c0)  # 2025, pas la campagne 2026 choisie à l'envoi
        self.assertEqual(l.exercice, 2025)

    def test_exercice_illisible_refuse(self):
        for brut in ("abc", "0000", "FY26", 26, 12345, True):
            a = I.analyser(self.contrib, xlsx([ENTETES, ["EFF", "E1", brut, 7]]), campagne_defaut=self.c.pk)
            l = a.lignes[0]
            self.assertEqual(l.action, "rejet", brut)
            self.assertIn("Exercice illisible", l.motif, brut)

    def test_exercices_lisibles(self):
        for brut, attendu in ((2026, 2026), ("2026", 2026), ("FY2026", 2026), ("2026-2027", 2026), (2026.0, 2026),
                              (datetime.date(2026, 6, 30), 2026)):
            self.assertEqual(I._exercice(brut), attendu, brut)
        a = I.analyser(self.contrib, xlsx([ENTETES, ["EFF", "E1", None, 7]]), campagne_defaut=self.c.pk)
        self.assertEqual(a.lignes[0].campagne, self.c)  # cellule vide : la campagne choisie à l'envoi


class CaracteresDeControleTests(Base):
    """Un caractère de contrôle (CSV, copier-coller) dans un commentaire importé rendait tout export Excel impossible
    (erreur 500), et le rapport des lignes rejetées aussi."""

    def test_commentaire_importe_nettoye(self):
        f = csv_fichier("ID KPI;Organisation;Exercice;Valeur;Commentaire\r\nEFF;E1;2026;120;avant\x01après\x00\r\n")
        a, n, _ = I.appliquer(self.contrib, f, "valeurs.csv")
        self.assertEqual(n, 1)
        self.assertEqual(Reponse.objects.get(periode=self.c.periode, kpi=self.eff, organisation=self.e1).commentaire, "avantaprès")

    def test_rapport_des_rejets_avec_caractere_de_controle(self):
        self.client.force_login(self.contrib)
        f = csv_fichier("ID KPI;Organisation;Exercice;Valeur\r\nEFF;E1;2026;\x00\r\nX\x07Y;E1;2026;5\r\n")
        rep = self.client.post(reverse("collecte:echanges_importer"), {"action": "verifier", "fichier": f})
        self.assertEqual(rep.status_code, 200)
        rep = self.client.get(reverse("collecte:echanges_rejets"))
        self.assertEqual(rep.status_code, 200)
        valeurs = [c for ws in classeur(rep).worksheets for row in ws.iter_rows(values_only=True) for c in row if isinstance(c, str)]
        self.assertIn("XY", valeurs)

    def test_export_excel_avec_commentaire_ancien(self):
        """Commentaire enregistré avant la correction (base existante) : l'export Excel se fait, sans le caractère."""
        from . import exports as E

        Reponse.objects.filter(periode=self.c.periode, kpi=self.eff, organisation=self.e1).update(commentaire="ligne\x0bun\x1f")
        for presentation in ("base", "revue"):  # (le tableau n'a pas de commentaires)
            p = E.Parametres.depuis({"presentation": presentation, "exercices": ["courant"], "n1": True,
                                     "contenus": ["valide", "brouillon", "calcule", "a_saisir"]})
            rep = E.exporter(self.admin, p)
            contenu = b"".join(rep.streaming_content) if getattr(rep, "streaming", False) else rep.content
            textes = {c for ws in load_workbook(io.BytesIO(contenu)).worksheets for row in ws.iter_rows(values_only=True) for c in row}
            self.assertIn("ligneun", textes, presentation)

    def test_saisie_nettoyee(self):
        from . import saisie as S

        r = S.enregistrer(self.contrib, self.c, self.eff, self.e1, "111", False, "texte\x08 collé")
        self.assertEqual(r.commentaire, "texte collé")


class CsvTests(Base):
    LIGNES = "ID KPI\tOrganisation\tExercice\tValeur\tCommentaire\r\nEFF\tE1\t2026\t130\tÉté €\r\n"

    def test_texte_unicode_d_excel(self):
        """« Texte Unicode » d'Excel : UTF-16 avec BOM, séparé par des tabulations (avant : colonnes introuvables)."""
        for encodage in ("utf-16", "utf-16-le", "utf-16-be", "utf-32"):
            brut = self.LIGNES.encode(encodage)
            if encodage == "utf-16-le":
                brut = codecs.BOM_UTF16_LE + brut
            if encodage == "utf-16-be":
                brut = codecs.BOM_UTF16_BE + brut
            a = I.analyser(self.contrib, csv_fichier(brut, nom="unicode.txt"))
            self.assertFalse(a.erreur, encodage)
            self.assertEqual([(l.kpi_id, l.commentaire, l.action) for l in a.lignes], [("EFF", "Été €", "modifier")], encodage)

    def test_latin1_et_windows(self):
        for encodage in ("cp1252", "latin-1"):
            a = I.analyser(self.contrib, csv_fichier(self.LIGNES.replace("€", "") + "EFF\tE2\t2026\t1\t\x81\r\n", encodage)
                           if encodage == "latin-1" else csv_fichier(self.LIGNES, encodage))
            self.assertFalse(a.erreur, encodage)
            self.assertEqual(a.lignes[0].commentaire.strip(), "Été €" if encodage == "cp1252" else "Été")

    def test_cellule_immense(self):
        """Une cellule de plus de 131 072 caractères faisait échouer la lecture du CSV (erreur 500)."""
        self.client.force_login(self.contrib)
        texte = "ID KPI;Organisation;Exercice;Valeur;Commentaire\r\nEFF;E1;2026;5;" + "x" * 200_000 + "\r\n"
        rep = self.client.post(reverse("collecte:echanges_importer"), {"action": "verifier", "fichier": csv_fichier(texte)})
        self.assertEqual(rep.status_code, 200)
        self.assertFalse(rep.context["analyse"].erreur)

    def test_guillemet_jamais_ferme(self):
        texte = 'ID KPI;Organisation;Exercice;Valeur\r\nEFF;"E1;2026;5\r\nEFF;E2;2026;6\r\n'
        a = I.analyser(self.admin, csv_fichier(texte))
        self.assertFalse(any(l.action in ("creer", "modifier") and l.org == self.e2 for l in a.lignes))  # pas de ligne inventée

    def test_fichiers_qui_ne_sont_pas_du_texte(self):
        for brut in (b"", codecs.BOM_UTF8, b"\x00" * 3000, codecs.BOM_UTF16_LE + b"\x00\xd8"):
            a = I.analyser(self.contrib, csv_fichier(brut))
            self.assertTrue(a.erreur, brut[:10])


class FichiersAbimesTests(Base):
    """Échantillon de qa/import_traps.py : chaque fichier est envoyé à la page (aperçu puis confirmation)."""

    def _envoyer(self, utilisateur, nom, octets):
        self.client.force_login(utilisateur)
        url = reverse("collecte:echanges_importer")
        avant = (Reponse.objects.count(), Journal.objects.count(),
                 list(Reponse.objects.order_by("pk").values_list("valeur", "commentaire", "statut")))
        rep = self.client.post(url, {"action": "verifier", "campagne": self.c.pk, "fichier": SimpleUploadedFile(nom, octets)})
        self.assertLess(rep.status_code, 500, nom)
        apercu = rep.context.get("analyse") if rep.context else None
        rep2 = self.client.post(url, {"action": "confirmer"})
        self.assertLess(rep2.status_code, 500, nom)
        apres = (Reponse.objects.count(), Journal.objects.count(),
                 list(Reponse.objects.order_by("pk").values_list("valeur", "commentaire", "statut")))
        return apercu, avant, apres

    def test_fichiers_refuses_rien_d_ecrit(self):
        wb = Workbook()
        wb.active.append(ENTETES)
        wb.active.append(["EFF", "E1", 2026, 5])
        t = io.BytesIO()
        wb.save(t)
        bon = t.getvalue()
        for nom, octets in (("tronque.xlsx", bon[: len(bon) // 2]), ("pas-un-zip.xlsx", b"bonjour"), ("vide.xlsx", b""),
                            ("csv-renomme.xlsx", b"ID KPI;Organisation\nEFF;E1\n"), ("excel-renomme.csv", bon),
                            ("sans-entetes.csv", b"EFF;E1;2026;5\n"), ("entetes-trop-bas.csv", b"x\n" * 20 + b"ID KPI;Organisation;Valeur\nEFF;E1;5\n")):
            apercu, avant, apres = self._envoyer(self.contrib, nom, octets)
            self.assertTrue(apercu is None or apercu.erreur, nom)
            self.assertEqual(avant, apres, nom)

    def test_campagne_cloturee_contributeur(self):
        """Le contributeur n'écrit jamais dans une campagne clôturée : lignes refusées, listées, rien d'écrit."""
        octets = "ID KPI;Organisation;Exercice;Valeur\r\nEFF;E1;2025;999\r\nTX;E1;2025;50\r\n".encode()
        apercu, avant, apres = self._envoyer(self.contrib, "cloturee.csv", octets)
        self.assertEqual({l.action for l in apercu.lignes}, {"rejet"})
        self.assertEqual(avant, apres)
        rejets = classeur(self.client.get(reverse("collecte:echanges_rejets")))  # les lignes refusées, à télécharger
        self.assertIn(999, [c for ws in rejets.worksheets for row in ws.iter_rows(values_only=True) for c in row])

    def test_valeurs_bizarres(self):
        """Nombres immenses, négatifs, notation scientifique, erreurs Excel, booléens, dates : jamais d'erreur, motif clair."""
        lignes = [ENTETES]
        valeurs = ["1e400", "-1e400", "NaN", "inf", "1" * 40, "#DIV/0!", True, datetime.datetime(2026, 1, 1), "=1+1", "1,234", "12 %",
                   "１２", "(12)", "1E+16"]
        for v in valeurs:
            lignes.append(["EFF", "E2", 2026, v])
        a = I.analyser(self.admin, xlsx(lignes))
        self.assertFalse(a.erreur)
        for l, v in zip(a.lignes, valeurs):
            if l.action == "rejet":
                self.assertTrue(l.motif and "Error" not in l.motif and "None" not in l.motif, (v, l.motif))

    def test_codes_kpi_en_minuscules_et_espaces(self):
        a = I.analyser(self.contrib, xlsx([ENTETES, ["  eff ", "e1", 2026, 131], [" EFF ", "E1 ", 2026, 131]]))
        self.assertEqual(a.lignes[0].kpi, self.eff)
        self.assertEqual(a.lignes[0].action, "modifier")
        self.assertEqual(a.lignes[1].action, "rejet")  # même case deux fois : la seconde est un doublon
        self.assertIn("2", a.lignes[1].motif)

    def test_doublons_contradictoires(self):
        a = I.analyser(self.contrib, xlsx([ENTETES, ["EFF", "E1", 2026, 1], ["EFF", "E1", 2026, 2]]))
        self.assertEqual([l.action for l in a.lignes], ["modifier", "rejet"])

    def test_onglet_cache_et_cellules_fusionnees(self):
        wb = Workbook()
        ws = wb.active
        ws.title = "Notes"
        ws2 = wb.create_sheet("Saisie")
        for l in (ENTETES, ["EFF", "E1", 2026, 140], ["EFF", "E2", 2026, 41]):
            ws2.append(l)
        ws2.merge_cells("B2:B3")
        ws2.sheet_state = "hidden"
        t = io.BytesIO()
        wb.save(t)
        a = I.analyser(self.admin, SimpleUploadedFile("cache.xlsx", t.getvalue()))
        self.assertFalse(a.erreur)
        self.assertEqual([l.action for l in a.lignes], ["modifier", "rejet"])  # cellule fusionnée : organisation vide

    def test_paquet_json_invalide(self):
        self.client.force_login(self.admin)
        url = reverse("parametres:paquet_importer")
        mauvais = [{"referentiel": "x"}, {"referentiel": {"code": [1, "x"]}}, {"referentiel": {"code": "X", "nom": 5}},
                   {"referentiel": {"code": "X", "description": {"fr": {"a": 1}}}}, {"referentiel": {"code": "X", "mois_debut": "abc"}},
                   {"referentiel": {"code": "X", "frequence": ["annee"]}}, {"referentiel": {"code": "X"}, "kpis": "abc"},
                   {"referentiel": {"code": "X"}, "themes": [1, 2]}, {"referentiel": {"code": "X"}, "langue_reference": 3},
                   {"referentiel": {"code": "X"}, "niveaux": [{"code": "N", "nom": 5}]},
                   {"referentiel": {"code": "X"}, "niveaux": [{"code": "N", "nom": {"fr": {"a": 1}}}]},
                   {"referentiel": {"code": "X"}, "regles": [{"nom": "r", "tolerance": "abc"}]},
                   {"referentiel": {"code": "X"}, "unites": [{"code": "U", "decimales": 10 ** 30}]}]
        for octets in [b"", b"bonjour", b"[1, 2]", "{\"é\": 1}".encode("latin-1"), b"[" * 5000 + b"]" * 5000] + \
                [json.dumps(d).encode() for d in mauvais]:
            rep = self.client.post(url, {"action": "verifier", "fichier": SimpleUploadedFile("p.json", octets)})
            self.assertEqual(rep.status_code, 302, octets[:80])  # retour à la page, avec le message
            messages = [str(m) for m in rep.wsgi_request._messages]
            self.assertTrue(messages and "Error" not in messages[0], (octets[:80], messages))


class ExportLisibleDeposeTests(Base):
    """Un export « Tableau » ou « Revue » déposé dans l'import : un message qui dit quoi faire, pas « colonnes
    introuvables »."""

    def test_tableau_et_revue_refuses_avec_explication(self):
        from . import exports as E

        for presentation in ("tableau", "revue"):
            p = E.Parametres.depuis({"presentation": presentation, "exercices": ["tous"]})
            octets = E.exporter(self.admin, p).content
            a = I.analyser(self.admin, SimpleUploadedFile(f"{presentation}.xlsx", octets))
            self.assertIn("ne s'importe pas", a.erreur, presentation)
        a = I.analyser(self.admin, xlsx([["ID KPI", "Montant"], ["EFF", 5]]))  # fichier quelconque : message habituel
        self.assertIn("Colonnes introuvables", a.erreur)


class DefautsTrouvesTests(Base):
    """Autres défauts trouvés par qa/import_traps.py (erreur 500 avant la correction, ou valeur changée sans le dire)."""

    def _xlsx_abime(self):
        import zipfile

        wb = Workbook()
        wb.active.append(ENTETES)
        wb.active.append(["EFF", "E1", 2026, 5])
        t, sortie = io.BytesIO(), io.BytesIO()
        wb.save(t)
        with zipfile.ZipFile(io.BytesIO(t.getvalue())) as zin, zipfile.ZipFile(sortie, "w") as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename.startswith("xl/worksheets/sheet"):
                    data = data[: len(data) // 2] + b"<<<&&&"
                zout.writestr(item, data)
        return sortie.getvalue()

    def test_feuille_xml_abimee(self):
        """XML d'une feuille invalide : lu au fil de l'eau, l'erreur arrivait après l'ouverture (erreur 500)."""
        a = I.analyser(self.contrib, SimpleUploadedFile("abime.xlsx", self._xlsx_abime()))
        self.assertIn("lire ce fichier Excel", a.erreur)

    def test_fins_de_ligne_mac(self):
        """Lignes terminées par un seul retour chariot (anciens Mac, certains logiciels) : erreur 500 avant."""
        a = I.analyser(self.contrib, csv_fichier("ID KPI;Organisation;Exercice;Valeur\rEFF;E1;2026;130\r"))
        self.assertFalse(a.erreur)
        self.assertEqual([(l.kpi_id, l.action) for l in a.lignes], [("EFF", "modifier")])

    def test_rejet_pourcentage_garde_tel_quel(self):
        """« 12 % » refusé sur un KPI qui n'est pas un pourcentage : le fichier des rejets l'écrivait 12, et le
        réimporter tel quel l'enregistrait sans que personne l'ait corrigé."""
        self.client.force_login(self.contrib)
        url = reverse("collecte:echanges_importer")
        self.client.post(url, {"action": "verifier", "fichier": csv_fichier("ID KPI;Organisation;Exercice;Valeur\r\nEFF;E1;2026;12 %\r\n")})
        rejets = self.client.get(reverse("collecte:echanges_rejets")).content
        a = I.analyser(self.contrib, SimpleUploadedFile("rejets.xlsx", rejets))
        self.assertEqual([l.action for l in a.lignes], ["rejet"])


class RecalculHorsRequeteTests(Base):
    def test_langues_lues_une_fois(self):
        """Hors d'une requête (commande, démarrage, test), le recalcul relisait l'état des langues en base à chaque
        message de calcul : 111 s au lieu de 12 s sur la démo après l'ajout de 5 organisations."""
        from unittest import mock

        from parametres import langues as L

        from .calcul import recalculer_en_cours

        vrai = L.calculer
        with mock.patch.object(L, "calculer", side_effect=vrai) as compte:
            recalculer_en_cours()
        self.assertLessEqual(compte.call_count, 2)


class ImportCheminsTests(TE.Base):
    ENTETE = ["ID KPI", "Organisation", "Exercice", "Valeur", "N/A", "Commentaire"]

    def test_comptage_avec_decimales_refuse(self):
        from parametres.models import Unite

        u = Unite.objects.create(code="pers-test", symbole="pers.", entier=True, decimales=0)
        KPI.objects.create(code="HC", libelle="Effectif", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                           methode_agregation="Somme", unite=u)
        a = I.analyser(self.admin, TE.fichier([self.ENTETE, ["HC", "E1", 2026, "12,5", "", ""], ["HC", "E2", 2026, 12, "", ""]]))
        self.assertEqual([l.action for l in a.lignes], ["rejet", "creer"])
        self.assertIn("n'est pas un nombre entier", a.lignes[0].motif)

    def test_comptage_deja_enregistre_avec_decimales_relu_identique(self):
        # une valeur à décimales déjà en base (saisie avant la) : l'export « Base de données »
        # réimporté sans changement la relit « identique », il ne la rejette pas ; une autre valeur à décimales l'est
        from parametres.models import Unite

        u = Unite.objects.create(code="pers-test", symbole="pers.", entier=True, decimales=0)
        hc = KPI.objects.create(code="HC", libelle="Effectif", type_saisie_id="Saisi", granularite_id=Niveau.ENTITY,
                                methode_agregation="Somme", unite=u)
        Reponse.objects.create(periode=self.c.periode, kpi=hc, organisation=self.e1, valeur=D("571.5"))
        a = I.analyser(self.admin, TE.fichier([self.ENTETE, ["HC", "E1", 2026, "571,5", "", ""], ["HC", "E2", 2026, "3,5", "", ""]]))
        self.assertEqual([l.action for l in a.lignes], ["inchange", "rejet"])

    def test_validation_impossible_gardee_en_brouillon(self):
        self.nrj.preuve_obligatoire = True  # valider demande une preuve : la ligne est écrite, mais reste en brouillon
        self.nrj.save()
        a, n, avertissements = I.appliquer(self.admin, TE.fichier([self.ENTETE, ["NRJ", "E1", 2026, 7, "", ""]]), valider=True)
        self.assertEqual(n, 1)
        r = self.valeur(self.nrj, self.e1)
        self.assertEqual((r.valeur, r.statut), (D(7), Reponse.Statut.BROUILLON))
        self.assertEqual(len(avertissements), 1)
        self.assertIn("gardée en brouillon", avertissements[0])
        self.assertEqual(self.valeur(self.nrj, self.p).valeur, D("-5.5"))  # total recalculé : 7 + (-12,5)


class ImportPourcentageExcelTests(BaseEchanges):
    """P2 : « 12,5 % » tapé dans Excel est rangé 0,125 au format pourcentage ; P10 : « 12 % » sur un KPI qui n'est pas un
    pourcentage est refusé au lieu d'être lu 12."""

    ENTETE = ["ID KPI", "Organisation", "Exercice", "Valeur", "N/A", "Commentaire"]

    def analyser(self, *lignes, **kw):
        return I.analyser(self.admin, fichier([self.ENTETE, *lignes], **kw))

    def test_cellule_au_format_pourcentage(self):
        a = self.analyser(["TX", "E1", 2026, 0.125, "", ""], ["TX", "E2", 2026, 1, "", ""],
                          formats={(2, 4): "0.0%", (3, 4): "0%"})
        self.assertEqual([(l.action, l.valeur) for l in a.lignes], [("modifier", D("0.125")), ("modifier", D(1))])
        self.assertEqual(a.lignes[0].apres, "12,50\u202f%")  # aux décimales du KPI

    def test_format_avec_signe_entre_guillemets_inchange(self):
        # l'export écrit 35 au format « #,##0.00" %" » (texte « % » ajouté, pas un pourcentage Excel) : relu 35 %
        a = self.analyser(["TX", "E1", 2026, 35, "", ""], formats={(2, 4): '#,##0.00" %"'})
        self.assertEqual(a.lignes[0].valeur, D("0.35"))

    def test_pourcentage_excel_au_dela_de_100_refuse(self):
        a = self.analyser(["TX", "E1", 2026, 1.5, "", ""], formats={(2, 4): "0%"})
        self.assertEqual((a.lignes[0].action, a.lignes[0].motif), ("rejet", "Saisissez un pourcentage de 0 à 100."))

    def test_signe_pourcent_sur_un_kpi_qui_n_est_pas_un_pourcentage(self):
        a = self.analyser(["NRJ", "E1", 2026, "12 %", "", ""], ["NRJ", "E2", 2026, 0.5, "", ""], formats={(3, 4): "0%"})
        self.assertEqual([l.action for l in a.lignes], ["rejet", "rejet"])
        self.assertIn("pas un pourcentage", a.lignes[0].motif)

    def test_lecture_du_classeur(self):
        onglets = X.lire(fichier([["Valeur"], [0.125], [35]], formats={(2, 1): "0.0%", (3, 1): '0" %"'}))
        v1, v2 = onglets["Saisie"][1][0], onglets["Saisie"][2][0]
        self.assertIsInstance(v1, X.PourcentExcel)
        self.assertEqual(v1, 0.125)  # la valeur reste celle de la cellule
        self.assertEqual(X.texte(v1), "12,5 %")
        self.assertNotIsInstance(v2, X.PourcentExcel)


class ImportConflitTests(BaseEchanges):
    """P3 : une case modifiée par quelqu'un d'autre entre l'aperçu et la confirmation n'est pas écrasée."""

    ENTETE = ["ID KPI", "Organisation", "Exercice", "Valeur", "N/A", "Commentaire"]

    def test_valeur_validee_entre_apercu_et_confirmation(self):
        from django.urls import reverse

        url = reverse("collecte:echanges_importer")
        self.client.force_login(self.contrib)
        f = fichier([self.ENTETE, ["EFF", "E1", 2026, 5000, "", ""], ["NRJ", "E1", 2026, 7, "", ""]])
        rep = self.client.post(url, {"action": "verifier", "fichier": f})
        self.assertEqual([l.action for l in rep.context["analyse"].lignes], ["modifier", "modifier"])
        # pendant ce temps, l'admin saisit et valide 999 dans le panneau
        S.enregistrer(self.admin, self.c, self.eff, self.e1, "999", False, "Corrigé par l'admin")
        S.valider(self.admin, self.c, self.eff, self.e1)
        rep = self.client.post(url, {"action": "confirmer"})
        self.assertContains(rep, "Import terminé")
        r = self.valeur(self.eff, self.e1)
        self.assertEqual((r.valeur, r.statut), (D(999), Reponse.Statut.VALIDE))  # rien d'écrasé
        self.assertEqual(self.valeur(self.nrj, self.e1).valeur, D(7))  # les autres lignes sont importées
        self.assertEqual(rep.context["ecrites"], 1)
        avert = " ".join(rep.context["avertissements"])
        self.assertIn("depuis l'aperçu, donc non importée", avert)
        self.assertIn("non importée", avert)

    def test_sans_conflit_tout_est_importe(self):
        from django.urls import reverse

        url = reverse("collecte:echanges_importer")
        self.client.force_login(self.contrib)
        f = fichier([self.ENTETE, ["EFF", "E1", 2026, 5000, "", ""]])
        self.client.post(url, {"action": "verifier", "fichier": f})
        rep = self.client.post(url, {"action": "confirmer"})
        self.assertEqual((rep.context["ecrites"], rep.context["avertissements"]), (1, []))
        self.assertEqual(self.valeur(self.eff, self.e1).valeur, D(5000))
