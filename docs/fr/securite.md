# Politique de sécurité

Version française de [`SECURITY.md`](../../SECURITY.md). En cas d'écart, la version anglaise fait foi.

## Signaler une faille

N'ouvrez pas de ticket public pour un problème de sécurité.

Signalez-le en privé sur GitHub :

1. Ouvrez la page du dépôt sur GitHub.
2. Sélectionnez **Security**.
3. Sélectionnez **Report a vulnerability**.
4. Décrivez le problème, puis sélectionnez **Submit report**.

Seuls les mainteneurs peuvent lire le signalement.

Indiquez si possible :

- La version de Probant. Elle s'affiche en bas de chaque page de l'outil.
- Le type d'installation : Docker ou hébergement clé en main, SQLite ou PostgreSQL.
- Le rôle du compte utilisé : administrateur, validateur, contributeur, lecteur ou auditeur.
- Les étapes pour reproduire le problème.
- Ce qu'un attaquant peut lire ou modifier.

Ne joignez aucune donnée réelle : ni valeurs, ni adresses e-mail, ni noms de personnes ou d'organisations.

## À quoi vous attendre

| Étape | Délai |
|---|---|
| Nous confirmons la réception du signalement | 7 jours au plus |
| Nous vous disons si le problème est confirmé, et ce que nous prévoyons | 30 jours au plus |
| Nous publions une version corrigée | Dès que la correction est testée |

Nous vous prévenons quand la version corrigée est disponible. Nous vous demandons de ne pas rendre le problème public
avant.

## Versions suivies

| Version | Corrections de sécurité |
|---|---|
| 1.0.x (la dernière version) | Oui |

Une correction de sécurité est une nouvelle version de l'image Docker. Pour l'appliquer, voir
[Mettre à jour l'outil](installation.md).

## Périmètre

Dans le périmètre : le code de ce dépôt, et l'image Docker qu'il construit.

Hors périmètre : le serveur, le nom de domaine, HTTPS, le compte SMTP et les copies des sauvegardes. L'équipe IT de
chaque installation les gère. Voir [Installation](installation.md).
