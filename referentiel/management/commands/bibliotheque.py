"""Régénère les paquets JSON de la bibliothèque (referentiel/bibliotheque/*.json) et leur description
(docs/library.md) à partir des socles de referentiel/bibliotheque/socles.py et des modèles de
referentiel/bibliotheque/definitions/ (un fichier par modèle).

``--validate`` : contrôle seulement (rapport par modèle). La génération contrôle d'abord et n'écrit rien si un modèle a
une erreur."""
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from collecte import paquets as P
from referentiel.bibliotheque import controle as C
from referentiel.bibliotheque import socles as S
from referentiel.bibliotheque.documentation import documentation

DOC = Path(settings.BASE_DIR) / "docs" / "library.md"


class Command(BaseCommand):
    help = "Checks, then rebuilds the supplied frameworks (JSON packages) and docs/library.md."

    def add_arguments(self, parser):
        parser.add_argument("--check", "--verifier", dest="verifier", action="store_true", help="Only report whether the files are out of date.")
        parser.add_argument("--validate", "--controler", dest="controler", action="store_true",
                            help="Only check the templates (codes, texts, formulas, aggregations, coverage of the standard).")
        parser.add_argument("--template", "--modele", dest="modele", default="",
                            help="With --validate: check this template only (its code, e.g. VSME).")
        parser.add_argument("--warnings", "--avertissements", dest="avertissements", action="store_true",
                            help="With --validate: also list the warnings.")
        parser.add_argument("--untranslated", dest="famille", default="",
                            help="List the English texts of a family of templates (e.g. esrs) that have no translation yet "
                                 "(referentiel/bibliotheque/traductions), for --language.")
        parser.add_argument("--language", dest="langue", default="", help="With --untranslated: es, de, it, nl or pt.")

    def handle(self, *args, verifier=False, controler=False, modele="", avertissements=False, famille="", langue="", **options):
        if famille:
            return self._non_traduits(famille, langue)
        conflits, rapports = C.controler_tout()
        if modele:
            rapports = [r for r in rapports if r.code.lower() == modele.lower()]
            if not rapports:
                self.stderr.write(f"Unknown template: {modele} ({', '.join(s['code'] for s in S.SOCLES)})")
                raise SystemExit(1)
        en_erreur = conflits or any(not r.ok for r in rapports)
        if controler:
            self._rapport(conflits, rapports, avertissements)
            if en_erreur:
                raise SystemExit(1)
            return
        if en_erreur:
            self._rapport(conflits, rapports, False)
            self.stderr.write("Nothing written: fix the errors above (python3 manage.py bibliotheque --validate).")
            raise SystemExit(1)
        fichiers = {P.BIBLIOTHEQUE / s["fichier"]: P.vers_json(S.paquet(s)) + "\n" for s in S.SOCLES}
        fichiers[DOC] = documentation()
        perimes = [f for f, texte in fichiers.items() if not f.exists() or f.read_text(encoding="utf-8") != texte]
        if verifier:
            if perimes:
                self.stderr.write("To rebuild (python manage.py bibliotheque): " + ", ".join(f.name for f in perimes))
                raise SystemExit(1)
            self.stdout.write("Library up to date.")
            return
        for f in perimes:
            f.write_text(fichiers[f], encoding="utf-8")
        self.stdout.write(f"{len(perimes)} file(s) written: " + ", ".join(f.name for f in perimes) if perimes else "Nothing to change.")

    def _non_traduits(self, famille, langue):
        from referentiel.bibliotheque import traductions as T

        if langue not in T.LANGUES:
            self.stderr.write(f"--language: one of {', '.join(T.LANGUES)}")
            raise SystemExit(1)
        noms, phrases = {}, {}
        for s in S.SOCLES:
            if s.get("traductions") == famille:
                n, f = T.textes_a_traduire(S.paquet({**s, "traductions": ""}))
                noms.update(dict.fromkeys(n))
                phrases.update(dict.fromkeys(f))
        table = T.table(famille, langue)
        manquants = [t for t in (*noms, *phrases) if t not in table]
        for t in manquants:
            self.stdout.write(t)
        self.stdout.write(f"{len(manquants)} text(s) without {langue} translation out of {len(noms) + len(phrases)}.")

    def _rapport(self, conflits, rapports, avertissements):
        for c in conflits:
            self.stderr.write(f"CONFLICT  {c}")
        for r in rapports:
            ch = r.chiffres
            resume = (f"{ch.get('kpi', 0)} KPIs ({ch.get('calcules', 0)} calculated, {ch.get('textes', 0)} written text, "
                      f"{ch.get('facultatifs', 0)} optional), {ch.get('themes', 0)} themes, {ch.get('regles', 0)} rules")
            if "couverture" in ch:
                cv = ch["couverture"]
                resume += (f"; standard coverage {cv['taux']} % ({cv['covered']} covered, {cv['partial']} partial, "
                           f"{cv['automatic']} filled automatically, {cv['out_of_scope']} out of scope, {cv['todo']} to do, out of {cv['total']})")
            self.stdout.write(f"{'OK   ' if r.ok else 'ERROR'}  {r.code}: {resume}")
            for e in r.erreurs:
                self.stdout.write(f"       - {e}")
            if avertissements:
                for a in r.avertissements:
                    self.stdout.write(f"       ~ {a}")
            elif r.avertissements:
                self.stdout.write(f"       ({len(r.avertissements)} warning(s): --warnings to list them)")
