"""Connexion d'entreprise : réglage de l'installation et lien entre un compte et son compte d'entreprise.

Les deux tables vivent dans le registre commun (``espaces.routeur`` : comme les comptes, elles valent pour tous les
espaces) : ni dans la sauvegarde d'un espace, ni dans l'archive du registre (``sauvegardes.MODELES_REGISTRE`` ne les
liste pas). Une restauration du registre les vide : la connexion d'entreprise est alors éteinte, rien d'autre ne change."""
from django.db import models


class ReglageEntreprise(models.Model):
    """Une seule ligne (clé 1), écrite au premier enregistrement depuis Paramètres › Connexion d'entreprise. Éteinte par
    défaut : sans ligne, rien ne change pour personne."""

    actif = models.BooleanField(default=False)
    emetteur = models.CharField(max_length=500, blank=True)  # adresse du fournisseur (« issuer »)
    client_id = models.CharField(max_length=255, blank=True)
    # secret du client, chiffré (``secret.py``) : jamais réaffiché, jamais écrit au journal ni dans une sauvegarde
    secret_chiffre = models.TextField(blank=True)
    secret_le = models.DateTimeField(null=True, blank=True)
    libelle_bouton = models.CharField(max_length=80, blank=True)
    # fournisseur qui ne dit pas si l'adresse est vérifiée (pas de « email_verified ») : refusé, sauf ce choix explicite
    email_non_declare = models.BooleanField(default=False)
    # mot de passe de l'outil quand la connexion d'entreprise est allumée : les gestionnaires des espaces seulement
    # (comptes de secours), sauf ce choix explicite
    mot_de_passe_pour_tous = models.BooleanField(default=False)
    modifie_le = models.DateTimeField(null=True, blank=True)
    modifie_par = models.BigIntegerField(null=True, blank=True)  # numéro du compte au registre commun

    class Meta:
        verbose_name = "réglage de la connexion d'entreprise"
        verbose_name_plural = "réglages de la connexion d'entreprise"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)


class LienEntreprise(models.Model):
    """Compte de l'outil lié, à sa première connexion, au compte d'entreprise qui l'a ouvert (« sub » du fournisseur,
    identifiant stable que l'adresse e-mail n'est pas) : une adresse donnée ensuite à une autre personne chez le
    fournisseur n'ouvre pas ce compte. Le lien se défait dans Paramètres › Connexion d'entreprise ; il ne vaut que pour
    le fournisseur qui l'a créé (un autre fournisseur crée un nouveau lien). ``derniere_le`` : dernière connexion par
    ce compte d'entreprise (les jetons des assistants n'en dépendent plus : ``regles.assistants_permis``)."""

    compte_id = models.BigIntegerField(unique=True)
    emetteur = models.CharField(max_length=500)
    sujet = models.CharField(max_length=255)
    lie_le = models.DateTimeField(auto_now_add=True)
    derniere_le = models.DateTimeField()

    class Meta:
        verbose_name = "lien avec un compte d'entreprise"
        verbose_name_plural = "liens avec un compte d'entreprise"
        indexes = [models.Index(fields=["emetteur", "sujet"], name="lien_entreprise_sujet_idx")]
