"""Espaces : registre commun (installation, espaces, comptes, accès) et marque de chaque base d'espace.

Le registre (``Installation``, ``Espace``, ``Compte``, ``AccesEspace``) vit dans la base ``commun`` ; ``MarqueEspace``
vit dans chaque base d'espace (une ligne : à quel espace et à quelle installation appartient cette base). Voir
docs/spaces.md."""
from django.db import models
from django.utils import timezone


class Installation(models.Model):
    """Une seule ligne : identifiant de l'installation, inscrit dans chaque base d'espace et dans chaque sauvegarde."""

    identifiant = models.CharField(max_length=32, unique=True)
    creee_le = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.identifiant


class Espace(models.Model):
    class Etat(models.TextChoices):
        CREATION = "creation", "En création"
        ACTIF = "actif", "Actif"
        ARCHIVE = "archive", "Archivé"

    code = models.CharField(max_length=20, unique=True)  # « principal » pour la base d'origine ; ne change jamais
    nom = models.CharField(max_length=80)
    etat = models.CharField(max_length=10, choices=Etat.choices, default=Etat.CREATION)
    rang = models.PositiveSmallIntegerField(default=0)
    cree_le = models.DateTimeField(auto_now_add=True)
    cree_par = models.BigIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["rang", "nom"]

    def __str__(self):
        return self.nom

    @property
    def principal(self):
        return self.code == "principal"


class Compte(models.Model):
    """Identité commune d'une personne : même numéro que sa copie (``referentiel.Utilisateur``) dans chaque espace."""

    username = models.CharField(max_length=150, unique=True)
    email = models.EmailField(unique=True)
    password = models.CharField(max_length=128)
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    doit_changer_mdp = models.BooleanField(default=False)
    actif = models.BooleanField(default=True)  # connexion permise (tous les espaces)
    gestionnaire = models.BooleanField(default=False)  # crée et gère les espaces
    last_login = models.DateTimeField(null=True, blank=True)
    date_joined = models.DateTimeField(default=timezone.now)
    dernier_espace = models.CharField(max_length=20, blank=True)

    def __str__(self):
        return self.email or self.username


class AccesEspace(models.Model):
    """Index tenu à jour depuis les copies : qui a accès à quel espace, avec quel rôle (sélecteur, page Espaces)."""

    compte_id = models.BigIntegerField(db_index=True)
    espace = models.ForeignKey(Espace, on_delete=models.CASCADE, related_name="acces")
    role = models.CharField(max_length=20)
    actif = models.BooleanField(default=True)

    class Meta:
        unique_together = [("compte_id", "espace")]


class MarqueEspace(models.Model):
    """Dans chaque base d'espace, une ligne : l'espace et l'installation à qui appartient cette base."""

    code = models.CharField(max_length=20)
    installation = models.CharField(max_length=32)
