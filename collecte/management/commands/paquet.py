"""Paquets référentiels en ligne de commande (mêmes règles que la page Bibliothèque et échange) :

    python manage.py package export RSE -o paquet-rse.xlsx       (ou .json)
    python manage.py package import paquet-rse.xlsx              aperçu seulement
    python manage.py package import paquet-rse.xlsx --confirm    aperçu puis import (choix par défaut, ou --choices)
    python manage.py package import vs_base.json --library --confirm

Anciens noms encore acceptés : paquet, exporter / importer, --sortie, --bibliotheque, --confirmer, --choix.
"""
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from collecte import paquets as P
from parametres import langues as L
from parametres.libelles import libelle
from parametres.vues_paquets import MOTIFS_NIVEAU


STATUTS_EN = {"conflit": "conflict", "rejet": "rejected", "modifie": "modified"}  # statuts d'une ligne de l'aperçu


class Command(BaseCommand):
    help = "Exports a framework as a framework file, or imports a framework file (preview, then --confirm)."

    def add_arguments(self, parser):
        # noms anglais (export, import, --output…) ; les anciens noms français restent acceptés
        parser.add_argument("action", choices=["export", "import", "exporter", "importer"])
        parser.add_argument("cible", metavar="target",
                            help="export: code of the framework; import: .xlsx or .json file (or name of a supplied framework)")
        parser.add_argument("-o", "--output", "--sortie", dest="sortie", metavar="FILE",
                            help="file written by export (.xlsx by default, .json possible)")
        parser.add_argument("--library", "--bibliotheque", dest="bibliotheque", action="store_true",
                            help="import: a framework supplied with the tool (e.g. vs_base.json)")
        parser.add_argument("--confirm", "--confirmer", dest="confirmer", action="store_true", help="import: apply after the preview")
        parser.add_argument("--choices", "--choix", dest="choix", nargs="*", default=[], metavar="CHOICE",
                            help="import: choices of the preview, e.g. mode=nouveau code=RSE2 kpi:A=renommer code:A=A2")

    def handle(self, action, cible, sortie=None, bibliotheque=False, confirmer=False, choix=(), **o):
        if action in ("export", "exporter"):
            from referentiel.models import Referentiel

            ref = Referentiel.objects.filter(code=cible).first()
            if ref is None:
                raise CommandError(f"Unknown framework: {cible} ({', '.join(Referentiel.objects.values_list('code', flat=True))}).")
            p = P.extraire(ref)
            chemin = Path(sortie or f"{P.nom_fichier(p)}.xlsx")
            if chemin.suffix == ".json":
                chemin.write_text(P.vers_json(p), encoding="utf-8")
            else:
                P.classeur(p).save(chemin)
            self.stdout.write(self.style.SUCCESS(f"{chemin}: \"{ref}\" version {ref.version}, {p.nb_elements} KPIs, {len(p.themes)} themes."))
            return
        # lecture et aperçu avec les textes de l'interface en anglais (messages pour l'IT) ; l'import lui-même
        # (``appliquer``) garde la langue de l'installation
        with L.activer_interface("en"):
            try:
                if bibliotheque:
                    f = P.fourni(cible)
                    p, fourni, nom = f.paquet, True, f.nom_fichier
                else:
                    with open(cible, "rb") as fichier:
                        p, fourni, nom = P.lire(fichier), False, Path(cible).name
            except (OSError, P.PaquetInvalide) as e:
                raise CommandError(str(e))
            valeurs = dict(c.split("=", 1) for c in choix if "=" in c)
            a = P.analyser(p, valeurs, source=nom, fourni=fourni)
            if a.erreur:
                raise CommandError(a.erreur)
            self._apercu(p, a)
        if not confirmer:
            self.stdout.write("Preview only: add --confirm to import.")
            return
        res = P.appliquer(None, a, nom)
        self.stdout.write(self.style.SUCCESS(
            f"Imported: \"{res.referentiel}\" ({res.referentiel.code}); {res.kpis_crees} KPIs created, {res.kpis_modifies} modified, "
            f"{res.elements} places, {res.themes} themes, {res.reglages} settings, {res.regles} rules."))

    def _apercu(self, p, a):
        c = a.compteurs
        self.stdout.write(f"\"{p.nom()}\" version {p.version}: "
                          + (f"new framework {a.code}" if a.mode == "nouveau" else f"update of {a.code} (version {a.existant.version})"))
        self.stdout.write(f"KPIs: {c['nouveau']} new, {c['modifie']} modified, {c['conflit']} conflicts, {c['inchange']} unchanged, "
                          f"{c['rejet']} rejected; {c['ajoute']} added to the framework, {c['retire']} missing from this version.")
        self.stdout.write("Levels: " + ", ".join(
            f"{n['code']} → {local or libelle('referentiels.apercu.motif.auto')} "
            f"({libelle(MOTIFS_NIVEAU[motif]) if motif in MOTIFS_NIVEAU else motif})" for n, local, motif, u in a.niveaux if u))
        if a.reglages_crees:
            self.stdout.write("Settings created: " + ", ".join(f"{r.libelle_local}" for r in a.reglages_crees))
        for l in a.kpis:
            if l.statut in ("conflit", "rejet", "modifie"):
                self.stdout.write(f"  {STATUTS_EN[l.statut]:8} {l.code} {l.motif} " + "; ".join(f"{x}: {av} → {ap}" for x, av, ap in l.differences[:4]))
        for x in a.avertissements:
            self.stdout.write(f"  ! {x}")
        if a.aucune_difference:
            self.stdout.write(self.style.SUCCESS("No difference with the installed framework."))
