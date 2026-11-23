"""Création d'un espace depuis l'outil (gestionnaires) : ligne au registre, base (fichier SQLite ou schéma PostgreSQL),
migrations sous l'espace, marque, identité reprise de l'espace actuel, créateur administrateur, assistant de mise en place
à l'étape 2. Interrompue, elle se reprend (chaque étape est idempotente)."""
import logging
import re
import unicodedata

from django.core.files.base import ContentFile
from django.core.management import call_command
from django.db import connections

from parametres.libelles import libelle

from . import comptes as EC
from . import contexte as E
from .migrations_renommees import autres_bases, harmoniser
from .models import Espace, MarqueEspace

journal = logging.getLogger("reporting.espaces")

CHAMPS_IDENTITE = ["nom", "titre", "sous_titre", "sigle", "contact", "palette", "couleur_principale", "couleur_accent",
                   "couleur_fond", "couleur_texte"]


class ErreurEspace(Exception):
    pass


def code_propose(nom):
    """« Achats & Logistique » → « achatslogistique » (minuscules, sans accent ni signe, 20 caractères au plus)."""
    t = unicodedata.normalize("NFKD", nom or "").encode("ascii", "ignore").decode().lower()
    t = re.sub(r"[^a-z0-9]", "", t)
    t = re.sub(r"^[0-9]+", "", t)[:20]
    return t if len(t) >= 2 else ""


def verifier_code(code):
    if not E.CODE.match(code or ""):
        raise ErreurEspace(libelle("espaces.erreur.code"))
    if code in E.RESERVES:
        raise ErreurEspace(libelle("espaces.erreur.code_reserve", code=code))
    if Espace.objects.filter(code=code).exists():
        raise ErreurEspace(libelle("espaces.erreur.code_pris", code=code))


def _base_deja_utilisee(code):
    """Vrai si la base de ce code existe déjà avec des tables (fichier ou schéma laissé par une autre installation)."""
    alias = E.declarer(code)
    E.dossier_espace(code).mkdir(parents=True, exist_ok=True)  # dossier retiré depuis la déclaration (démo réinitialisée)
    with E.toutes_les_bases():
        return bool(connections[alias].introspection.table_names())


def creer(nom, code, createur, reprendre_identite=True):
    """Nouvel espace « nom » à l'adresse /espace/<code>/ ; renvoie l'espace (actif)."""
    nom = (nom or "").strip()
    if not nom:
        raise ErreurEspace(libelle("espaces.erreur.nom_vide"))
    if len(nom) > Espace._meta.get_field("nom").max_length:
        raise ErreurEspace(libelle("espaces.erreur.nom_long", max=Espace._meta.get_field("nom").max_length))
    if Espace.objects.filter(nom__iexact=nom).exists():
        raise ErreurEspace(libelle("espaces.erreur.nom_pris", nom=nom))
    verifier_code(code)
    if _base_deja_utilisee(code):
        raise ErreurEspace(libelle("espaces.erreur.base_existante", code=code))
    rang = (Espace.objects.order_by("-rang").values_list("rang", flat=True).first() or 0) + 1
    e = Espace.objects.create(code=code, nom=nom, etat=Espace.Etat.CREATION, rang=rang, cree_par=createur.pk)
    return poursuivre(e, createur, reprendre_identite)


def poursuivre(e, createur, reprendre_identite=True):
    """Étapes de la création (reprise possible après une interruption)."""
    from parametres.models import Instance

    if e.etat != Espace.Etat.CREATION:
        raise ErreurEspace(libelle("espaces.erreur.deja_cree"))
    identite = None
    palette = None
    if reprendre_identite:
        from parametres.models import PaletteEnregistree

        source = Instance.courante()
        identite = {f: getattr(source, f) for f in CHAMPS_IDENTITE}
        # palette enregistrée de l'espace actuel (charte) : elle suit, sinon le nouvel espace ne la connaîtrait pas
        p = PaletteEnregistree.depuis_code(source.palette)
        if p:
            palette = {f: getattr(p, f) for f in ("nom", "principale", "accent", "fond", "texte", "gamme")}
        if source.logo_disponible:
            with source.logo.open("rb") as f:
                identite["_logo"] = (source.logo.name.rsplit("/", 1)[-1], f.read())
    inst = EC.installation()
    alias = E.declarer(e.code)
    with E.activer(e.code):
        call_command("migrate", database=alias, interactive=False, verbosity=0)
        # migration renommée : l'ancienne ligne des autres bases de l'installation, pour que la version d'avant démarre
        harmoniser(connections[alias], autres_bases(alias))
        if not MarqueEspace.objects.exists():
            MarqueEspace.objects.create(code=e.code, installation=inst.identifiant if inst else "")
        i = Instance.courante()
        if identite:
            logo = identite.pop("_logo", None)
            for f, v in identite.items():
                setattr(i, f, v)
            if logo and not i.logo:
                i.logo.save(logo[0], ContentFile(logo[1]), save=False)
            if palette:
                from parametres.models import PaletteEnregistree

                copie = PaletteEnregistree.objects.filter(**{f: v for f, v in palette.items() if f != "gamme"}).first()
                i.palette = (copie or PaletteEnregistree.objects.create(**palette)).code  # reprise : pas de doublon
        i.mise_en_place_etape = max(i.mise_en_place_etape, 2)
        i.save()
        from referentiel.models import Utilisateur

        if not Utilisateur.objects.filter(pk=createur.pk).exists():
            # langue de la personne : la sienne, pas celle du nouvel espace (l'assistant de
            # mise en place s'ouvrait en anglais pour un créateur dont le compte est en français)
            u = Utilisateur(username=createur.username, email=createur.email, first_name=createur.first_name,
                            last_name=createur.last_name, role=Utilisateur.Role.ADMIN, is_staff=True, is_superuser=True,
                            langue=getattr(createur, "langue", "") or "")
            u.set_unusable_password()  # remplacé par le mot de passe du registre (rattachement)
            u.save()
    e.etat = Espace.Etat.ACTIF
    e.save(update_fields=["etat"])
    EC.reconcilier([e.code])  # comptes changés pendant une création interrompue
    journal.info("Space \"%s\" (/espace/%s/) created by account no. %s", e.nom, e.code, createur.pk)
    return e
