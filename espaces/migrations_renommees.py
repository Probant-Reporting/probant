"""Migrations renommées. Une base créée avant le renommage d'une migration la note sous l'ancien nom dans sa table
django_migrations : sans rien faire, Django la croirait jamais appliquée et refuserait l'historique
(InconsistentMigrationHistory : la migration suivante est appliquée, pas celle-ci), et une archive faite avant le
renommage passerait pour une archive d'une version plus récente. D'où :

- ``harmoniser``, appelé par la commande ``migrate`` pour chaque base, avant et après ses migrations (toutes les bases ou
  ``--database`` : démarrage de l'image, mise à jour, restauration, base de test gardée), puis par la création d'un espace
  et par la restauration (``restore`` et ``restore --rebuild``) une fois la base migrée : chaque base d'une installation
  existante finit avec les deux lignes, au nom actuel et à l'ancien nom. L'ancienne ligne n'est recopiée d'une autre base
  (``autres_bases``) que par ``migrate`` de toutes les bases, la création d'un espace et la restauration : jamais par
  ``migrate --database`` seul, que lance aussi la création des bases de test ;
- ``lecture_harmonisee``, pour ``migrate --plan`` et ``migrate --check`` : même lecture, en mémoire, sans rien écrire ;
- ``paires_actuelles``, pour une liste lue ailleurs (descriptif d'une archive, base extraite d'une archive).

Pourquoi les deux lignes : Django ignore une migration notée que son code ne connaît pas ; la version d'avant le
renommage, qui ne connaît que l'ancien nom, démarre donc toujours sur une base mise à jour (retour arrière, même sans
restauration : le registre commun n'est jamais restauré en tant que base). Une base créée après la mise à jour (nouvel
espace, base reconstruite par « restore --rebuild ») reçoit l'ancienne ligne recopiée d'une autre base de la même
installation (registre commun ou base principale). Une installation neuve n'a cette ancienne ligne nulle part : elle n'a
pas de version d'avant à laquelle revenir, rien n'est ajouté.

Une migration renommée est désignée par son application et son numéro, jamais par son ancien nom, qui n'est écrit nulle
part dans le code (il est lu dans les bases) : dans cette application, ce numéro n'a jamais porté qu'une seule migration
(historique du dépôt). Les fonctions qui lisent une base importent Django à leur appel."""
import contextlib

# (application, numéro) : nom actuel. parametres/0002 : renommée (son ancien nom citait une installation).
RENOMMEES = {("parametres", "0002"): "0002_identite"}


def nom_actuel(app, nom):
    """Nom actuel d'une migration (``nom`` lui-même si elle n'a jamais été renommée)."""
    numero = nom.split("_", 1)[0]
    actuel = RENOMMEES.get((app, numero))
    return actuel if actuel and nom.startswith(f"{numero}_") else nom


def paires_actuelles(paires):
    """[[application, nom], …] aux noms actuels, triées, sans doublon (une base mise à jour a les deux noms)."""
    return sorted([a, n] for a, n in {(a, nom_actuel(a, n)) for a, n in paires})


def _enregistreur(connexion):
    from django.db.migrations.recorder import MigrationRecorder

    enregistreur = MigrationRecorder(connexion)
    return enregistreur if enregistreur.has_table() else None


def a_harmoniser(connexion):
    """Migrations renommées que cette base ne note que sous un ancien nom, en paires (application, nom actuel), sans rien
    écrire : le démarrage les compte comme une mise à jour de la base (sauvegarde automatique avant)."""
    enregistreur = _enregistreur(connexion)
    if enregistreur is None:
        return []
    notees = set(enregistreur.migration_qs.values_list("app", "name"))
    return sorted({(a, nom_actuel(a, n)) for a, n in notees if nom_actuel(a, n) != n} - notees)


def anciens_noms(connexions):
    """{(application, numéro): ancien nom} lus dans ces bases (les autres bases de la même installation)."""
    from espaces import contexte as E

    trouves = {}
    with E.toutes_les_bases():  # lecture voulue d'une autre base que celle de l'espace courant (création, restauration)
        for connexion in connexions:
            enregistreur = _enregistreur(connexion)
            if enregistreur is None:
                continue
            for (app, numero), actuel in RENOMMEES.items():
                nom = (enregistreur.migration_qs.filter(app=app, name__startswith=f"{numero}_").exclude(name=actuel)
                       .order_by("applied", "pk").values_list("name", flat=True).first())
                if nom and (app, numero) not in trouves:
                    trouves[(app, numero)] = nom
    return trouves


def autres_bases(alias):
    """Les autres bases de la même installation où lire l'ancienne ligne : base principale et registre commun."""
    from django.db import connections

    from espaces import contexte as E

    return [connections[a] for a in ("default", E.COMMUN) if a != alias]


def harmoniser(connexion, autres=()):
    """Dans django_migrations de la base ``connexion`` : ajoute la ligne au nom actuel d'une migration renommée notée
    seulement sous un ancien nom (même date d'application, l'ancienne ligne reste) ; et, si la base n'a que la ligne au
    nom actuel, recopie l'ancienne ligne lue dans les bases ``autres`` de la même installation (même date que la ligne au
    nom actuel). Lignes verrouillées puis relues dans la transaction : deux démarrages simultanés n'ajoutent qu'une ligne.
    Rend le nombre de lignes ajoutées ; base neuve (sans table) : 0."""
    from django.db import transaction

    enregistreur = _enregistreur(connexion)
    if enregistreur is None:
        return 0
    references = None
    n = 0
    with transaction.atomic(using=connexion.alias):
        for (app, numero), actuel in RENOMMEES.items():
            lignes = list(enregistreur.migration_qs.select_for_update().filter(app=app, name__startswith=f"{numero}_")
                          .order_by("applied", "pk"))
            anciennes = [m for m in lignes if m.name != actuel]
            presente = enregistreur.migration_qs.filter(app=app, name=actuel).first()  # relu après le verrou
            if anciennes and presente is None:
                enregistreur.migration_qs.create(app=app, name=actuel, applied=anciennes[0].applied)
                n += 1
            elif presente is not None and not anciennes:
                if references is None:
                    references = anciens_noms([c for c in autres if c.alias != connexion.alias])
                ancien = references.get((app, numero))
                if ancien and not enregistreur.migration_qs.filter(app=app, name=ancien).exists():
                    enregistreur.migration_qs.create(app=app, name=ancien, applied=presente.applied)
                    n += 1
    return n


@contextlib.contextmanager
def lecture_harmonisee():
    """Pendant le bloc, Django lit l'historique de toute base comme ``harmoniser`` le laisserait (nom actuel d'une
    migration renommée notée sous un ancien nom), sans rien écrire : ``migrate --plan`` et ``migrate --check``."""
    from django.db.migrations.recorder import MigrationRecorder

    origine = MigrationRecorder.applied_migrations

    def appliquees(self):
        sortie = origine(self)
        for (app, nom), m in list(sortie.items()):
            actuel = nom_actuel(app, nom)
            if actuel != nom:
                sortie.setdefault((app, actuel), m)
        return sortie

    MigrationRecorder.applied_migrations = appliquees
    try:
        yield
    finally:
        MigrationRecorder.applied_migrations = origine
