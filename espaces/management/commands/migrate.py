"""``migrate`` des espaces : sans ``--database``, migre toutes les bases, chacune dans son espace (principal, registre
commun, puis chaque autre espace dont la base porte bien sa marque), puis amorce et réconcilie le registre des comptes. Avec
``--database X`` : la commande de Django, dans l'espace de X (les migrations de données écrivent dans la bonne base).
Migrations renommées (``espaces/migrations_renommees.py``) : chaque base reçoit, avant et après ses migrations, la ligne
au nom actuel et, sans --database, l'ancienne ligne recopiée d'une autre base de l'installation ; --plan et --check lisent
l'historique de la même façon sans rien écrire."""
from django.core.management.commands.migrate import Command as MigrateDjango

from espaces import contexte as E


class Command(MigrateDjango):
    help = "Applies the migrations of all databases (main space, shared registry, other spaces)."

    def add_arguments(self, parser):
        super().add_arguments(parser)
        for action in parser._actions:
            if action.dest == "database":
                action.default = None
                action.help = "A single database (alias). Default: all databases, each in its own space."

    def get_check_kwargs(self, options):
        # Django 5.2 vérifie avant handle() avec [options["database"]] : sans --database ce serait [None] (planterait)
        return {**super().get_check_kwargs(options), "databases": [options.get("database") or "default"]}

    def handle(self, *args, **options):
        alias = options.get("database")
        if alias:
            return self._une(alias, *args, **options)
        from espaces import comptes

        self._une("default", *args, copier=True, **options)
        self._une(E.COMMUN, *args, copier=True, **options)
        if options.get("check_unapplied") or options.get("plan"):
            return
        from espaces.models import Espace

        self.echecs = {}
        # les autres espaces d'abord : la réconciliation des comptes (amorçage) lit leurs copies, qui doivent avoir
        # les colonnes de cette version ; une base qui n'est pas celle de son espace n'est ni migrée ni réconciliée
        for code in Espace.objects.exclude(code=E.PRINCIPAL).values_list("code", flat=True):  # archivés compris
            if E.indisponible(code):
                self.stderr.write(f"Space \"{code}\" marked unavailable at startup: not migrated (fix it, then "
                                  "restart the tool).")
                continue
            try:
                motif = self._base_d_un_autre(code)
                if motif:  # jamais migrée ni réconciliée : on n'écrit pas dans la base d'un autre espace
                    self.stderr.write(f"Space \"{code}\": {motif}; not migrated, marked unavailable.")
                    E.marquer_indisponible(code, motif)
                    continue
                self._une(E.declarer(code), *args, copier=True, **options)
            except Exception as e:  # un espace en défaut ne bloque pas les autres (démarrage : marqué indisponible)
                self.echecs[code] = str(e)
                self.stderr.write(f"Space \"{code}\": migrations failed ({e}).")
                E.marquer_indisponible(code, f"migrations failed ({e})")
        comptes.amorcer(self.stdout.write if options["verbosity"] >= 1 else None)  # puis réconciliation de tous les espaces

    @staticmethod
    def _base_d_un_autre(code):
        """Motif si la base trouvée pour cet espace n'est pas la sienne (marque d'un autre espace ou d'une autre
        installation, ou base sans marque : fichier ou schéma remplacé, vidé, perdu) ; « » sinon. Un espace en création
        n'a pas encore de marque."""
        from django.db import connections

        from espaces import comptes
        from espaces.models import Espace, MarqueEspace

        e = Espace.objects.filter(code=code).first()
        if e is None or e.etat == Espace.Etat.CREATION:
            return ""
        alias = E.declarer(code)
        inst = comptes.installation()
        with E.activer(code):
            if MarqueEspace._meta.db_table not in connections[alias].introspection.table_names():
                return "the database is not the one of this space (database without a mark: empty, replaced or lost)"
            m = MarqueEspace.objects.first()
        if m is None or m.code != code or (inst and m.installation != inst.identifiant):
            return "the database is not the one of this space (different mark)"
        return ""

    def _une(self, alias, *args, copier=False, **options):
        from django.db import connections

        from espaces.migrations_renommees import autres_bases, harmoniser, lecture_harmonisee

        options = {**options, "database": alias}
        if options.get("check_unapplied") or options.get("plan"):  # lecture seule : rien n'est écrit
            with lecture_harmonisee():
                return self._django(alias, *args, **options)
        # migrate de toutes les bases : l'ancienne ligne peut être recopiée des autres bases de l'installation ; jamais
        # avec --database seul (création des bases de test : les autres alias désignent encore les bases réelles)
        autres = autres_bases(alias) if copier else ()
        harmoniser(connections[alias], autres)  # avant que Django lise l'historique de la base
        sortie = self._django(alias, *args, **options)
        harmoniser(connections[alias], autres)  # base créée à l'instant : ancienne ligne recopiée (``autres``)
        return sortie

    def _django(self, alias, *args, **options):
        if alias == E.COMMUN:
            return super().handle(*args, **options)
        with E.activer(E.code_de(alias)):
            return super().handle(*args, **options)
