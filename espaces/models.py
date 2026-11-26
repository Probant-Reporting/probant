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


class ServeurEnvoi(models.Model):
    """Serveur d'envoi des e-mails réglé dans l'outil (Administration › Paramètres › Hébergement) : une seule ligne
    (numéro 1) pour toute l'installation, au registre commun. ``SMTP_HOST`` dans le fichier de réglages garde la priorité ;
    lecture et écriture : ``parametres/envoi_emails.py`` (le seul point de passage des envois). Le mot de passe n'est
    gardé que chiffré avec le secret de l'installation (``parametres/chiffrement.py``)."""

    class Securite(models.TextChoices):  # mêmes valeurs que SMTP_SECURITY
        STARTTLS = "starttls", "STARTTLS"
        SSL = "ssl", "SSL"
        AUCUNE = "none", "none"

    hote = models.CharField(max_length=253, blank=True)  # vide : rien n'est réglé dans l'outil
    port = models.PositiveIntegerField(default=587)
    securite = models.CharField(max_length=10, choices=Securite.choices, default=Securite.STARTTLS)
    identifiant = models.CharField(max_length=254, blank=True)
    mot_de_passe_chiffre = models.TextField(blank=True)
    mot_de_passe_le = models.DateTimeField(null=True, blank=True)
    expediteur = models.CharField(max_length=254, blank=True)
    modifie_le = models.DateTimeField(null=True, blank=True)
    modifie_par = models.BigIntegerField(null=True, blank=True)  # numéro du compte (registre commun)
    essais = models.JSONField(default=list, blank=True)  # dates des derniers e-mails de test (limite d'essais)

    def __str__(self):
        return f"{self.hote}:{self.port}" if self.hote else "—"


class ReglageAlertes(models.Model):
    """Alertes par e-mail de la santé de l'installation (Administration › Paramètres › Santé) : une seule ligne
    (numéro 1) pour toute l'installation, au registre commun, réglée par qui voit le détail de l'installation. Sans
    ligne : allumées sur une installation neuve, éteintes sur une installation existante inchangée à la mise à jour
    (``alertes.installation_neuve``). Lecture et écriture :
    ``parametres/alertes.py``. Sauvegardée avec le registre commun (``sauvegardes.MODELES_REGISTRE``)."""

    actives = models.BooleanField(default=False)
    aux_comptes = models.BooleanField(default=True)  # les personnes qui voient le détail de l'installation
    adresses = models.TextField(blank=True)  # autres destinataires, une adresse par ligne (boîte de l'IT…)
    modifie_le = models.DateTimeField(null=True, blank=True)
    modifie_par = models.BigIntegerField(null=True, blank=True)  # numéro du compte (registre commun)

    def __str__(self):
        return "on" if self.actives else "off"


class EtatAlertes(models.Model):
    """Ce que les alertes ont déjà dit (une ligne, numéro 1, registre commun, jamais dans une sauvegarde) : hors des
    bases des espaces, une restauration d'espace ne fait rien repartir. ``passage_le`` : dernier passage réservé (un
    seul processus à la fois, ``alertes._reserver``) ; ``problemes`` : {clé: {depuis, vu_le, absent, cle, espace, titre}}."""

    passage_le = models.DateTimeField(null=True, blank=True)
    problemes = models.JSONField(default=dict, blank=True)
    envoye_le = models.DateTimeField(null=True, blank=True)  # dernier e-mail d'alerte parti (rappel au plus par jour)
    echec_le = models.DateTimeField(null=True, blank=True)  # dernier e-mail d'alerte qui n'est pas parti
    echec = models.CharField(max_length=40, blank=True)  # cause (envoi_emails.cle_cause)
    echec_resume = models.CharField(max_length=200, blank=True)  # envoi_emails.resume_technique

    def __str__(self):
        return f"{len(self.problemes or {})} problem(s)"


class ProblemeSignale(models.Model):
    """Problème signalé par une autre partie de l'outil (``alertes.signaler``), montré sur la page Santé et envoyé
    comme les autres constats ; supprimé par ``alertes.resoudre``. Textes : des clés de libellé (``titre``,
    ``constat``, ``quoi``) et leurs paramètres, rendus dans la langue de qui lit. ``detail`` : pour l'IT seulement,
    jamais dans un e-mail."""

    cle = models.CharField(max_length=80, unique=True)
    espace = models.CharField(max_length=20, blank=True)  # vide : toute l'installation
    etat = models.CharField(max_length=10, default="panne")  # « panne » ou « regarder » (sante_installation)
    titre = models.CharField(max_length=120)
    constat = models.CharField(max_length=120)
    quoi = models.CharField(max_length=120, blank=True)
    params = models.JSONField(default=dict, blank=True)
    detail = models.CharField(max_length=300, blank=True)
    depuis = models.DateTimeField(default=timezone.now)
    modifie_le = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return self.cle


class DestinationCopie(models.Model):
    """Copie externe des sauvegardes (Administration › Paramètres › Hébergement › Copie externe) : une seule ligne
    (numéro 1) pour toute l'installation, au registre commun, réglée par qui voit le détail de l'installation. Sans ligne,
    ou ``genre`` vide : aucune copie (installation existante inchangée à la mise à jour). Lecture et écriture :
    ``parametres/copie_externe.py``. Les secrets (clé secrète S3, mot de passe ou clé privée SFTP) ne sont gardés que
    chiffrés avec le secret de l'installation (``parametres/chiffrement.py``), jamais renvoyés au navigateur. Sauvegardée
    avec le registre commun (``sauvegardes.MODELES_REGISTRE``) : secrets chiffrés, illisibles sur un autre serveur."""

    class Genre(models.TextChoices):
        AUCUNE = "", "—"
        S3 = "s3", "S3"
        SFTP = "sftp", "SFTP"

    genre = models.CharField(max_length=10, choices=Genre.choices, blank=True, default="")
    # stockage objet compatible S3
    adresse = models.CharField(max_length=300, blank=True)  # adresse du service (https://…)
    region = models.CharField(max_length=60, blank=True)
    compartiment = models.CharField(max_length=63, blank=True)
    style = models.CharField(max_length=10, blank=True, default="auto")  # auto, path, virtual
    # SFTP
    hote = models.CharField(max_length=253, blank=True)
    port = models.PositiveIntegerField(default=22)
    cle_serveur = models.TextField(blank=True)  # clé du serveur épinglée : « type base64 »
    cle_serveur_le = models.DateTimeField(null=True, blank=True)
    cle_serveur_par = models.BigIntegerField(null=True, blank=True)
    cle_proposee = models.TextField(blank=True)  # clé montrée au dernier essai, pas encore confirmée
    cle_proposee_le = models.DateTimeField(null=True, blank=True)
    # communs
    identifiant = models.CharField(max_length=254, blank=True)  # identifiant de la clé d'accès S3, ou nom du compte SFTP
    chemin = models.CharField(max_length=500, blank=True)  # préfixe dans le compartiment, ou dossier du serveur SFTP
    secret_chiffre = models.TextField(blank=True)  # clé secrète S3, ou mot de passe SFTP
    cle_privee_chiffree = models.TextField(blank=True)  # SFTP : clé privée (à la place du mot de passe)
    secret_le = models.DateTimeField(null=True, blank=True)
    conserver = models.PositiveIntegerField(default=0)  # copies gardées par dossier à distance ; 0 : ne rien supprimer
    modifie_le = models.DateTimeField(null=True, blank=True)
    modifie_par = models.BigIntegerField(null=True, blank=True)  # numéro du compte (registre commun)

    def __str__(self):
        return self.genre or "—"


class EtatCopie(models.Model):
    """Ce que la copie externe a déjà fait (une ligne, numéro 1, registre commun, jamais dans une sauvegarde) : hors des
    bases des espaces, une restauration d'espace ne fait rien recopier. ``copiees`` : {chemin relatif dans le dossier des
    sauvegardes: {taille, sha256, le}} ; ``destination`` : empreinte de la destination de ces copies (une autre
    destination : tout est à recopier) ; ``en_cours_le`` : passage réservé (un seul processus à la fois)."""

    destination = models.CharField(max_length=64, blank=True)
    copiees = models.JSONField(default=dict, blank=True)
    reussie_le = models.DateTimeField(null=True, blank=True)  # dernier passage où tout ce qui attendait est parti
    derniere_copie_le = models.DateTimeField(null=True, blank=True)  # dernière archive déposée
    echec_le = models.DateTimeField(null=True, blank=True)
    echec = models.CharField(max_length=40, blank=True)  # cause (copie_externe.CAUSES)
    echec_resume = models.CharField(max_length=200, blank=True)  # nom de l'erreur, jamais la réponse du service
    echecs_suite = models.PositiveIntegerField(default=0)
    prochain_essai = models.DateTimeField(null=True, blank=True)  # après un échec : pas avant (attente croissante)
    en_cours_le = models.DateTimeField(null=True, blank=True)
    essais = models.JSONField(default=list, blank=True)  # dates des derniers essais (bouton « Essayer la destination »)

    def __str__(self):
        return f"{len(self.copiees or {})} copied"
