# Installer Probant

> Version française du guide anglais [docs/installation.md](../installation.md), qui fait référence.

Ce guide explique comment installer, mettre en place, sauvegarder, mettre à jour et superviser Probant avec
Docker. Il s'adresse à l'équipe informatique. Vous n'avez pas besoin de connaître Django ni Python.

L'outil tourne dans **un seul conteneur Docker**. Toutes ses données sont dans **un seul volume**, `/data` : base,
preuves, logo, sauvegardes et clé secrète.

Ce tableau présente les principales opérations :

| Opération | Commande | Durée |
|---|---|---|
| Installer | `./install.sh` | 3 à 5 minutes |
| Mettre à jour | `./update.sh` | 1 à 3 minutes |
| Sauvegarder | Automatique chaque nuit, ou `docker compose exec web python manage.py backup` | Quelques secondes |
| Restaurer | `docker compose exec web python manage.py restore <archive>` | Quelques secondes |

Si vous ne voulez pas gérer de serveur, voir [Hébergement clé en main (Clever Cloud)](hebergement_cle_en_main.md).

## 1. Prérequis

Ce tableau présente ce qu'il faut avant d'installer l'outil :

| Besoin | Minimum conseillé |
|---|---|
| Serveur | Linux 64 bits (Debian 12, Ubuntu 22.04 ou plus récent), 1 processeur, 1 Go de mémoire, 5 Go de disque |
| Logiciels | Docker Engine 24 ou plus récent avec le module Compose v2.24 ou plus récent (`docker compose version`), Git |
| Réseau, accès interne | 1 port ouvert vers le serveur (8000 par défaut) |
| Réseau, accès HTTPS | Un nom de domaine qui pointe vers le serveur (par exemple `reporting.example.com`), et les ports 80 et 443 ouverts depuis Internet (certificat Let's Encrypt automatique) |
| E-mails (facultatif) | Un compte SMTP (serveur, port, identifiant, mot de passe, adresse d'expédition) |
| Assistant IA (facultatif) | Connexions HTTPS sortantes (TCP 443) du serveur vers `api.anthropic.com`, seulement si le client allume l'assistant. Voir « Assistant IA » à la section 4 |

Le serveur n'a besoin ni de Python, ni d'un serveur web, ni d'une base de données. Tout est dans l'image.

### Installer Docker sur Debian ou Ubuntu

La procédure officielle est sur https://docs.docker.com/engine/install/. En résumé, lancez ces commandes :

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER     # puis se déconnecter et se reconnecter
docker compose version            # doit afficher v2.24 ou plus
```

## 2. Installer l'outil

Pour installer l'outil :

1. Récupérez le code et allez dans son dossier :

   ```bash
   git clone https://github.com/Probant-Reporting/probant.git probant
   cd probant
   ```

2. Lancez l'installeur :

   ```bash
   ./install.sh                      # ou : ./install.sh --domain reporting.example.com
   ```

   Le script affiche l'adresse à ouvrir.

Le script effectue ces étapes, dans cet ordre :

1. Il vérifie que Docker répond.
2. Il crée le fichier de réglages `.env` à partir de `.env.example`. Il ne remplace pas un fichier `.env` existant.
3. Il construit l'image et démarre l'outil.
4. Il attend que l'outil réponde.
5. Il affiche l'adresse à ouvrir.

Ce tableau présente les options de `./install.sh` :

| Option | Effet |
|---|---|
| Sans option | L'outil s'ouvre en HTTP sur `http://ADRESSE-DU-SERVEUR:8000`. Utilisez-la pour un réseau interne ou un essai. |
| `--domain reporting.example.com` | L'outil s'ouvre en HTTPS. Le script ajoute Caddy devant l'outil, et Caddy obtient le certificat automatiquement. Le port 8000 n'est alors ouvert qu'au serveur lui-même. |
| `--port 8080` | L'outil utilise un autre port HTTP. |

### Installer sans le script

Pour faire la même installation à la main :

1. Créez le fichier de réglages : `cp .env.example .env`.
2. Ouvrez le fichier (`nano .env`) et réglez au moins `DOMAIN`.
3. Construisez et démarrez l'outil : `docker compose up -d --build`.

## 3. Mettre en place l'outil au premier lancement

À la première ouverture, l'outil n'a encore aucun compte. L'assistant **Mise en place** s'ouvre à la place de la page
de connexion. Il compte 8 étapes.

> **Important : créez le compte administrateur tout de suite.** Tant que l'étape 1 n'est pas faite, la première
> personne qui ouvre l'adresse de l'outil crée le compte administrateur. Après l'étape 1, l'assistant ne s'ouvre plus
> qu'à ce compte.

### Démarrer vide, ou avec la démo

Une nouvelle installation est vide : vous mettez en place votre propre structure avec l'assistant. C'est la façon de
démarrer pour de bon.

Pour d'abord faire le tour de l'outil, vous pouvez charger la démo à la place : Exemplia, une société fictive, avec
ses organisations, ses KPI et trois exercices. Faites-le avant l'étape 1 de l'assistant, sur la base vide :

```bash
docker compose exec web python manage.py load_demo
```

La commande affiche les comptes de démonstration et leur mot de passe.

> **Important :** le mot de passe des comptes de démonstration est public. Ne chargez la démo que sur une installation
> qui sert à une évaluation, et ne la laissez pas ouverte sur internet. La commande refuse une base qui contient déjà
> vos données. Pour démarrer ensuite pour de bon, supprimez l'évaluation et ses données (`docker compose down -v`),
> puis installez de nouveau : l'outil démarre vide.

L'outil ne demande aucun code d'installation. Tant que rien n'est créé, l'outil ne contient aucune donnée sensible.
Ce qui le protège, c'est l'ordre des étapes : vous créez le compte administrateur juste après l'installation, avant de
communiquer l'adresse.

Pour mettre en place l'outil :

1. Juste après l'installation (ou le déploiement), ouvrez l'adresse de l'outil. L'assistant **Mise en place**
   s'ouvre.
2. Faites l'étape 1, **Compte administrateur**, avant de communiquer l'adresse.
3. Faites les autres étapes, ou donnez l'adresse à la personne qui fait la mise en place.

Si l'étape 1 doit attendre, laissez l'outil inaccessible depuis Internet jusque-là. Par exemple, ne réglez pas encore
le nom de domaine.

Ce tableau présente les 8 étapes de l'assistant :

| Étape | Nom | Ce que vous réglez |
|---|---|---|
| 1 | **Compte administrateur** | Le compte de l'administrateur |
| 2 | **Votre structure** | Le nom, le logo et les couleurs de l'outil |
| 3 | **Langues** | La langue par défaut et les langues des contenus |
| 4 | **Organisation** | Les niveaux de l'arbre et les organisations |
| 5 | **Référentiels** | Les référentiels KPI : les KPI à collecter |
| 6 | **Fiche KPI** | Les catégories de description, les unités, les types et les champs |
| 7 | **Équipe** | Les comptes des contributeurs et des validateurs |
| 8 | **Première campagne** | La période, les dates et l'ouverture de la saisie |

Vous pouvez vous arrêter et reprendre plus tard. La personne qui fait la mise en place n'a pas besoin de l'équipe
informatique, sauf pour les e-mails (section 7).

![Premier lancement : l'assistant s'ouvre sur le compte administrateur](../screenshots/fr/setup-admin-account.png)

![Étape 5 : choisir un référentiel dans la bibliothèque, le composer ou importer le sien](../screenshots/fr/setup-frameworks.png)

![Étape 8 : la première campagne, période en cours proposée](../screenshots/fr/setup-campaign.png)

Après la mise en place, chaque personne se connecte avec son adresse e-mail. Le **Tableau de bord** montre
l'avancement de la collecte :

![Page de connexion](../screenshots/fr/login.png)

![Tableau de bord](../screenshots/fr/dashboard.png)

La saisie fonctionne aussi sur téléphone :

![Saisie sur téléphone](../screenshots/fr/entry-phone.png)

### Faire relire les textes traduits

L'interface existe en français, anglais, espagnol, allemand, italien, néerlandais et portugais. Une IA a traduit les
textes qui ne sont ni en français ni en anglais. Avant d'ouvrir une langue aux utilisateurs, demandez à une personne de
l'entreprise qui la parle de relire ses textes. Les textes sont dans les fichiers `libelles/*.<code>.json` (par exemple
`libelles/*.es.json`). La personne n'a besoin d'aucune compétence technique : elle relit seulement les textes.

## 4. Modifier les réglages (fichier `.env`)

Les réglages sont dans le fichier `.env`. Le fichier `.env.example` explique chaque ligne. Pour appliquer une
modification, lancez `docker compose up -d`. Un réglage sans valeur garde sa valeur par défaut.

L'outil accepte encore les anciens noms français des réglages (`DOMAINE`, `PORT_HTTP`, `SMTP_HOTE`…). Ils peuvent être dans
d'anciens fichiers `.env`. Utilisez les noms du tableau qui suit.

Ce tableau présente chaque réglage, sa valeur par défaut et son rôle :

| Réglage | Par défaut | Rôle |
|---|---|---|
| `DOMAIN` | Adresse IP du serveur (réglée par l'installeur) | Le nom de domaine ou l'adresse que les personnes utilisent pour ouvrir l'outil. Séparez plusieurs valeurs par des virgules. L'outil refuse toute autre adresse (erreur 400). |
| `DJANGO_HTTPS` | `0` | À mettre à `1` derrière Caddy ou un autre proxy HTTPS. Cela active les cookies sécurisés, la redirection vers HTTPS et HSTS. |
| `HTTP_PORT` | `8000` | Le port de l'outil. Pour ne l'exposer qu'au proxy, écrivez `127.0.0.1:8000`. |
| `COMPOSE_PROFILES` | Vide | `https` ajoute Caddy. `postgres` ajoute PostgreSQL. Pour les deux, écrivez `https,postgres`. |
| `DATABASE_URL` | Vide (SQLite) | L'adresse de la base PostgreSQL. Voir la section 8. |
| `DJANGO_SECRET_KEY` | Générée | La clé qui chiffre les sessions et signe les sauvegardes. Si elle est vide, l'outil la crée au premier démarrage dans `/data/.secret_key`. Si vous la changez, l'outil n'accepte plus les sauvegardes faites avant dans **Administration › Paramètres › Hébergement** : restaurez-les en ligne de commande avec `--unsigned`. |
| `DJANGO_HSTS_SECONDS`, `DJANGO_HSTS_SUBDOMAINS`, `DJANGO_HSTS_PRELOAD` | 1 an, `1`, `0` | Les réglages HSTS. Ils s'appliquent quand `DJANGO_HTTPS=1`. |
| `CONTENT_SECURITY_POLICY_MODE` | `enforce` | La politique de sécurité des contenus des pages. `enforce` bloque ce que la politique ne permet pas. `report-only` ne bloque rien : le navigateur signale seulement, dans sa console, ce qu'il bloquerait. Voir « Sécurité, déjà active » plus bas. |
| `SMTP_…` | Vide | E-mails. Voir la section 7. |
| `AI_SOCKET` | `on` | `off` coupe l'assistant IA facultatif pour toute l'installation : aucun bouton IA et rien n'est envoyé, quels que soient les réglages des administrateurs. Voir « Assistant IA » plus bas. |
| `DEFAULT_LANGUAGE` | `en` | La langue d'une nouvelle installation (interface et contenus) : l'une des sept langues de l'interface (`en`, `fr`, `es`, `de`, `it`, `nl`, `pt`). L'outil ne la lit qu'à la création de la base. Ensuite, changez-la dans **Administration › Paramètres › Langues**. Pour une installation en français, mettez `fr` avant le premier démarrage. |
| `GUIDED_TOUR` | `on` | `off` retire la courte visite guidée que les personnes voient à leur première connexion. La visite ne change que l'affichage. |
| `MAX_EVIDENCE_SIZE_MB`, `MAX_IMPORT_SIZE_MB` | `5`, `10` | La taille maximale, en Mo, d'une preuve et d'un fichier d'import. |
| `MAX_BACKUP_UPLOAD_MB` | `2048` | La taille maximale, en Mo, d'une sauvegarde déposée dans l'outil par un administrateur (**Hébergement** › **Restaurer**). L'outil refuse toute autre requête plus grosse que la plus grande des tailles `MAX_EVIDENCE_SIZE_MB` et `MAX_IMPORT_SIZE_MB` (plus 1 Mo), avant de la recevoir. Avec le proxy HTTPS, `CADDY_MAX_SIZE` (50 Mo par défaut) s'applique aussi : augmentez-le pour déposer une sauvegarde plus grosse. |
| `MAX_XLSX_UNCOMPRESSED_MB` | 20 × `MAX_IMPORT_SIZE_MB` | La taille maximale, en Mo, d'un fichier Excel une fois décompressé. L'outil refuse un fichier plus gros avant de l'ouvrir. Un texte de cellule de plus de 32 767 caractères (la limite d'Excel) est aussi refusé. Les mêmes limites s'appliquent aux commandes d'import lancées sur le serveur (`import_kpi`, `import_organisations`, `import_valeurs`) : pour importer un fichier plus gros par une commande, augmentez `MAX_XLSX_UNCOMPRESSED_MB` le temps de cette commande. |
| `BACKGROUND_IMPORT_ROWS` | `5000` | Un import de valeurs (**Import / Export › Importer des valeurs**) de plus de lignes que ce nombre se fait en arrière-plan. La personne voit une barre d'avancement, et peut quitter la page et revenir. Le processus `run_imports --schedule` fait ces imports. L'image le lance d'elle-même : vous n'installez rien. `0` veut dire jamais : tout import se fait dans la page, qui ne peut durer que 120 s. |
| `DISK_ALERT_MB` | `100` | Quand la place libre sur le disque des données passe sous cette valeur, en Mo, `/sante/` répond `503` (« disk almost full »). |
| `BACKUP_AUTO`, `BACKUP_TIME`, `BACKUPS_KEEP` | `1`, `02:30`, `14` | Valeurs de départ seulement. Ensuite, ces valeurs se règlent dans l'outil, dans **Administration › Paramètres › Hébergement** : sauvegarde automatique activée ou non, fréquence (6 h, 12 h, jour, semaine), heure et nombre de sauvegardes gardées. |
| `TIME_ZONE` | `Europe/Brussels` | Le fuseau horaire de l'installation, sous la forme d'un nom de la liste IANA, par exemple `Europe/Paris` ou `America/New_York`. L'heure des relances automatiques, de la sauvegarde automatique et du contrôle de chaque nuit, « aujourd'hui », et les dates des exports et du journal suivent ce fuseau. **Administration › Paramètres › Hébergement** l'affiche à côté de l'heure du serveur. Si le nom est inconnu, l'outil ne démarre pas et le journal montre l'erreur. |
| `DATA_CHECK_TIME` | `03:30` | L'heure du contrôle et du ménage de chaque nuit. Le contrôle lit la base et ne modifie rien. Le ménage efface les sessions terminées et les éléments supprimés depuis plus longtemps que le délai de la corbeille. Voir la section 9. |
| `GUNICORN_WORKERS`, `GUNICORN_THREADS` | 1 processus par processeur (de 2 à 4), `4` | Capacité du serveur. Un processus utilise 1 processeur à la fois et environ 170 Mo de mémoire. La valeur par défaut convient à un serveur de 2 à 4 processeurs. Voir « Capacité » à la section 8. |
| `GUNICORN_TIMEOUT`, `GUNICORN_KEEPALIVE` | `120`, `75` | La durée maximale d'une requête, en secondes, et la durée pendant laquelle une connexion inutilisée reste ouverte. Gardez `GUNICORN_KEEPALIVE` au-dessus du délai du proxy placé devant l'outil. Le Caddy fourni ferme les connexions inutilisées après 60 s. Si la valeur est plus basse, un enregistrement peut de temps en temps échouer avec l'erreur 502. |
| `DJANGO_LOG_LEVEL` | `INFO` | Le niveau de détail du journal (`INFO`, `WARNING`, `ERROR`). |
| `IMAGE` | Vide (image construite sur le serveur) | L'image publiée à utiliser, par exemple `ghcr.io/probant-reporting/probant:latest`. |

### Sécurité, déjà active

Sans réglage particulier, l'outil applique ces protections :

- Le mode de débogage est désactivé.
- Le serveur est gunicorn. Il tourne sans droits root (utilisateur 1000).
- Le code de l'outil dans l'image (`/app`) appartient à root : l'outil peut le lire mais pas le modifier. L'outil
  n'écrit que dans le dossier des données (`/data`). Les fichiers et dossiers qui s'y trouvent ne sont lisibles que par
  l'outil (`0600` et `0700`).
- Les archives d'un espace ne contiennent aucune empreinte de mot de passe, et l'outil signe chaque archive. La page
  **Hébergement** ne restaure que les archives de cette installation, intactes.
- WhiteNoise sert les fichiers statiques, avec un cache navigateur.
- L'outil envoie les pages compressées.
- L'outil envoie les en-têtes `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff` et
  `Referrer-Policy: same-origin`.
- Chaque page a une politique de sécurité des contenus (en-tête `Content-Security-Policy`). Le navigateur n'exécute
  que les scripts et les styles de l'outil. Un script ou un style venu d'ailleurs ne s'exécute pas, même si quelqu'un
  le glisse dans un texte. La page ne charge rien depuis un autre site, et aucun autre site ne peut l'afficher dans un
  cadre. Les preuves et le logo gardent leur propre politique, plus stricte.
- Une session expire au bout de 12 heures.
- L'outil sert les preuves seulement après avoir contrôlé les droits. Il n'y a jamais d'accès direct.
- Après 5 échecs de connexion pour un même identifiant depuis une même adresse, l'outil refuse la connexion pendant
  15 minutes. Il fait de même après 50 échecs depuis une même adresse (tous identifiants confondus), et après 20 échecs
  sur un même compte depuis toutes les adresses (la même personne dans tous les espaces ; un identifiant inconnu est
  compté de la même façon, pour que le message ne dise pas si le compte existe). Le message est le même pour chaque
  limite. La limite vaut pour la page de connexion de l'outil et pour le mode expert (`/admin/`). Elle ne ferme jamais
  une session déjà ouverte et n'arrête pas les jetons des assistants IA (MCP), qui n'utilisent pas le mot de passe.
  Contrepartie connue et acceptée : quelqu'un qui connaît l'identifiant d'une personne peut bloquer exprès sa
  connexion par mot de passe pendant 15 minutes. Le journal du serveur a une ligne à chaque blocage.
- Dans **Mon compte**, après 5 mots de passe actuels faux, l'outil ne vérifie plus le mot de passe actuel pendant
  15 minutes, même le bon, et le dit. La session reste ouverte. Ce compte est par personne, distinct de la connexion.
  Tous les processus du serveur partagent ces comptes, qui restent après un redémarrage : l'outil les garde dans le
  dossier `sign-in-attempts/` du dossier des données. Rien à régler.
- L'outil lit l'adresse du visiteur dans `X-Forwarded-For` seulement quand `DJANGO_HTTPS=1`. Caddy ou l'autre proxy
  HTTPS doit ajouter cet en-tête.

En HTTPS, `python manage.py check --deploy` ne signale aucun avertissement.

Si un écran ne fonctionne plus après une mise à jour (un bouton ne fait rien, une page n'a plus de couleurs), la
politique de sécurité des contenus peut en être la cause. Pour le savoir :

1. Dans le fichier `.env`, mettez `CONTENT_SECURITY_POLICY_MODE=report-only`.
2. Redémarrez l'outil : `docker compose up -d`.
3. Rouvrez l'écran. S'il fonctionne maintenant, ouvrez la console du navigateur (F12) : chaque ligne qui commence par
   `[Report Only]` nomme ce que la politique bloquerait. Envoyez ces lignes avec la version de l'outil.
4. Quand une version corrigée est installée, retirez la ligne ou mettez `CONTENT_SECURITY_POLICY_MODE=enforce`, puis
   redémarrez.

Avec `report-only`, la protection est coupée : ne gardez cette valeur que le temps de la vérification.

### Assistants IA (MCP) : rien à faire

L'outil contient un serveur pour les assistants IA (Model Context Protocol), à l'adresse `/mcp/` de chaque espace
(`/espace/<code>/mcp/` pour un autre espace). Il tourne dans le même conteneur, sur le même port, derrière le même
HTTPS : aucun service, aucun port, aucune variable, rien à installer. Il reste éteint tant qu'un administrateur ne l'a
pas permis dans **Administration › Paramètres › Assistants**. Seule condition : le proxy transmet l'en-tête
`Authorization` à l'outil (Caddy, profil `https`, et Clever Cloud le font sans réglage). Les jetons des assistants ne
sont jamais dans les sauvegardes. Le journal de l'outil montre les jetons refusés (`serveur_mcp: MCP: token refused`).
Détails : [`assistants_mcp.md`](assistants_mcp.md), section 7.

### Assistant IA (facultatif)

L'outil peut demander des propositions à un fournisseur d'IA (Claude, d'Anthropic) : expliquer une alerte de
cohérence, relier les KPI d'un ancien fichier, traduire des libellés. Il est **éteint** dans chaque espace. Un
administrateur de l'espace l'allume dans **Administration › Paramètres › Assistant IA**, avec la clé d'API du compte du
client chez le fournisseur. La page dit exactement ce que chaque usage envoie. Description complète :
`docs/fr/prise_ia.md`.

Ce que fait l'IT :

| Élément | Valeur |
|---|---|
| Réseau | Permettre les connexions HTTPS sortantes (TCP 443) du serveur vers `api.anthropic.com`. Rien n'entre. |
| Proxy | Si le serveur sort par un proxy, mettre `HTTPS_PROXY=http://proxy:port` dans `.env`. |
| Clé | Rien à faire : l'administrateur la saisit dans l'outil. L'outil la garde dans `ai-keys/` du dossier des données, lisible par l'outil seul, jamais en base ni dans une sauvegarde. Après une restauration sur un autre serveur, l'administrateur la saisit de nouveau. |
| L'interdire | `AI_SOCKET=off` dans `.env`, puis `docker compose up -d`. |

Tant que l'assistant est éteint dans un espace, l'outil n'ouvre aucune connexion vers le fournisseur.

## 5. Sauvegarder et restaurer

### Ce que contient le volume `/data`

L'outil range lui-même ce dossier et y écrit un fichier `README.txt` :

- Bases et clé : à la racine
- Documents ajoutés à l'outil : dans `files/` (`evidence/<période>/<organisation>/<KPI>/`, `settings/logo/`,
  `pending-imports/`)
- Archives : dans `backups/`
- Autres espaces : dans `spaces-data/<code>/`

Ne déplacez rien dans ce dossier à la main. Pour le détail, voir [rangement_des_fichiers.md](rangement_des_fichiers.md).

Seul l'utilisateur de l'outil peut lire ce que contient ce dossier : l'outil crée les fichiers avec les droits `0600` et
les dossiers avec les droits `0700`, aussi quand vous lancez une commande avec `docker compose exec`. À chaque
démarrage, il retire les droits du groupe et des autres aux fichiers qu'une version plus ancienne a faits.

### Ce que contient une sauvegarde

Une sauvegarde est une archive `.zip` datée, dans `/data/backups`. Elle contient :

- La base complète : comptes, référentiels, campagnes, valeurs, historique, et l'historique des connexions des derniers
  jours (Administration › Paramètres › Hébergement en règle le nombre)
- Les fichiers ajoutés à l'outil : preuves et logo
- Un descriptif : la version de l'outil et le nombre de lignes par table

L'archive contient des données confidentielles. Gardez-la en lieu sûr.

L'archive d'un espace ne contient aucun mot de passe, pas même leurs empreintes. Un administrateur de l'espace peut la
télécharger : l'outil en retire donc les empreintes. Les mots de passe restent dans le registre commun des comptes, qui
a ses propres sauvegardes dans `/data/backups/shared/`. Seule l'IT y a accès : l'outil ne les liste jamais et ne permet
à personne de les télécharger. Elles contiennent les empreintes des mots de passe. Gardez-les en lieu sûr et copiez-les
avec les autres sauvegardes.

> **Remarque :** les archives faites par une version antérieure de l'outil peuvent encore contenir les empreintes
> des mots de passe. Cela comprend les archives que des administrateurs ont téléchargées et les copies que l'IT a faites
> hors du serveur. Supprimez-les quand vous n'en avez plus besoin, ou gardez-les dans un endroit que seule l'IT peut
> ouvrir.

### Sauvegarder l'outil

Ce tableau présente comment sauvegarder l'outil :

| Pour… | Faire |
|---|---|
| Sauvegarder automatiquement | Rien. Par défaut, l'outil fait une sauvegarde chaque jour à 02:30 et garde 14 archives. L'équipe responsable règle la fréquence dans **Administration › Paramètres › Hébergement**. **Copiez régulièrement le dossier des sauvegardes hors du serveur.** |
| Sauvegarder maintenant | Lancez `docker compose exec web python manage.py backup`. Un administrateur peut aussi cliquer sur **Créer et télécharger une sauvegarde** dans **Administration › Paramètres › Hébergement**. |
| Lister les sauvegardes | Lancez `docker compose exec web python manage.py backup --list`. |
| Copier les sauvegardes hors du serveur | Lancez `docker compose cp web:/data/backups/. ../probant-backups/`. Cette commande copie les archives, sous-dossiers compris, dans le dossier `probant-backups` à côté du dossier de l'outil. Ne les copiez pas dans le dossier de l'outil : la mise à jour construit l'image à partir de ce dossier. Copiez ensuite `probant-backups` hors du serveur avec votre outil de sauvegarde habituel (rsync, Veeam…), de façon planifiée. Les fichiers copiés gardent leurs droits : seul le compte qui a lancé `docker compose cp` peut les lire (fichiers `0600`, dossiers `0700`). Si votre outil de sauvegarde tourne sous un autre compte, donnez à ce compte l'accès à `probant-backups`, par exemple avec `chown -R`. Ne changez pas les droits dans le volume. |

**Sans Docker**, planifiez la même sauvegarde avec cron : `30 2 * * * cd /opt/reporting && python manage.py backup`.

![Administration › Paramètres › Hébergement : version, sauvegardes, e-mail de test](../screenshots/fr/hosting.png)

### Sauvegardes et preuves supprimées

Un administrateur peut supprimer les fichiers de preuve des KPI sensibles dans **Administration › Preuves à supprimer**. L'outil supprime le fichier aussitôt. Une sauvegarde garde les fichiers de preuve qui existaient au moment où elle a été faite. Les sauvegardes déjà faites gardent donc le fichier jusqu'à ce que l'outil les remplace.

- Le nombre de sauvegardes gardées fixe la durée pendant laquelle un fichier supprimé reste. Avec les valeurs par défaut (une sauvegarde par jour, 14 gardées), il reste jusqu'à 14 jours. Si les données sont très sensibles, baissez ce nombre dans **Administration › Paramètres › Hébergement**.
- Une restauration remet le fichier supprimé, et il réapparaît dans **Preuves à supprimer**. Après une restauration, l'administrateur le supprime de nouveau.
- Les copies que vous faites hors du serveur gardent aussi le fichier. Supprimez les anciennes copies selon un calendrier qui respecte la durée pendant laquelle vous pouvez garder des données sensibles, et dites aux administrateurs combien de temps les copies durent.

### Restaurer une sauvegarde

Une restauration effectue ces étapes :

1. Elle demande une confirmation.
2. Elle sauvegarde d'abord l'état actuel (archive « before-restore »).
3. Elle remplace la base et les fichiers ajoutés à l'outil.

> **Avertissement :** une restauration remplace tout ce qui a été fait depuis la date de la sauvegarde. Les autres
> personnes connectées peuvent être déconnectées. Prévenez les équipes, et ne restaurez pas pendant une période de
> saisie.

Pour restaurer une sauvegarde depuis l'outil :

1. Allez dans **Administration › Paramètres › Hébergement**.
2. À côté de la sauvegarde dans la liste, cliquez sur **Restaurer…**. La page de confirmation s'ouvre.

   Pour utiliser un fichier `.zip` téléchargé auparavant, ouvrez **Restaurer depuis un fichier .zip téléchargé
   auparavant**. Choisissez le fichier, puis cliquez sur **Vérifier le fichier**. L'outil ajoute le fichier à la
   liste.
3. Cochez la case, puis saisissez `RESTAURER`.
4. Cliquez sur **Restaurer cette sauvegarde**. L'outil sauvegarde d'abord l'état actuel. Ensuite, la page de
   connexion affiche « Restauration réussie. L'outil est revenu à l'état du … ».
5. Connectez-vous avec un compte administrateur de la base restaurée.

L'outil ne restaure que les sauvegardes qu'il a faites lui-même, intactes. Quand il fait une sauvegarde, il signe
l'archive avec une clé tirée de la clé secrète de l'installation (`/data/.secret_key` ou `DJANGO_SECRET_KEY`). La page
refuse une archive sans signature valide, aussi quand vous ajoutez un fichier `.zip` : « Cette sauvegarde n'a pas été
faite par cette installation, ou elle a été modifiée après sa création ». Ces archives n'ont pas de signature valide :

- Les archives faites par une version antérieure de l'outil (avant l'existence de la signature)
- Les archives faites par un autre serveur, ou avant un changement de `DJANGO_SECRET_KEY`
- Les archives que quelqu'un a modifiées après la sauvegarde

L'IT peut toujours restaurer une telle archive en ligne de commande, si elle lui fait confiance : ajoutez `--unsigned`
à la commande `restore`. Sans cette option, la commande refuse l'archive et ne change rien.

Pour restaurer une archive du serveur (si l'outil ne démarre plus) :

1. Lancez `docker compose exec web python manage.py restore backup-20261026-023000-auto.zip`. Pour une archive sans
   signature valide, ajoutez `--unsigned`.
2. Lancez `docker compose restart web`.

Pour restaurer une archive que vous avez téléchargée :

1. Copiez l'archive dans le dossier des sauvegardes : `docker compose cp archive.zip web:/data/backups/`.
2. Faites les 2 étapes de la procédure précédente.

Après une restauration, chacun se connecte avec le mot de passe que le registre commun des comptes a pour lui : son
mot de passe actuel. L'archive d'un espace ne contient aucun mot de passe. Si le registre ne connaît pas un compte, ce
compte n'a plus de mot de passe après la restauration. Cela arrive quand vous restaurez une archive sur un autre
serveur, ou quand un compte a été supprimé après la sauvegarde. La restauration le dit (« … account(s) of this space
have no password on this server »). Faites alors l'une de ces actions :

- Restaurez la sauvegarde du registre commun faite au même moment, depuis `/data/backups/shared/` :
  `docker compose exec web python manage.py restore --shared <registry-….zip> --yes`. Sur un nouveau serveur, copiez
  d'abord tout le dossier `backups`, sous-dossiers compris.
- Donnez de nouveaux mots de passe : `docker compose exec web python manage.py changepassword <identifiant>` pour un
  administrateur. Cet administrateur donne ensuite aux autres comptes un mot de passe provisoire dans
  **Administration › Comptes**.

Avec SQLite, vous pouvez restaurer une archive faite avec une version plus ancienne de l'outil dans une version plus
récente. L'outil met la base à jour automatiquement. L'outil refuse l'inverse. Avec PostgreSQL, une archive ne se
restaure qu'avec la version de l'outil qui l'a faite : voyez [Revenir à la version précédente](#revenir-à-la-version-précédente)
et [Restaurer une sauvegarde PostgreSQL sur un nouveau serveur](#restaurer-une-sauvegarde-postgresql-sur-un-nouveau-serveur).

Pour restaurer, après une mise à jour, une archive PostgreSQL faite par une version plus ancienne :

1. Essayez la restauration. La version plus récente refuse l'archive et le dit. Rien ne change.
2. Revenez à la version qui a fait l'archive (la restauration affiche sa version, aussi dans `backup.json`), et
   restaurez l'archive avec cette version : voyez [Revenir à la version précédente](#revenir-à-la-version-précédente).
3. Mettez de nouveau l'outil à jour avec `./update.sh`. La mise à jour amène les données restaurées à la nouvelle version.

### Si une restauration est interrompue

Si une restauration est interrompue (serveur arrêté, conteneur arrêté, disque plein), rien n'est perdu :

- L'outil extrait d'abord les fichiers de l'archive à part. Si le disque est plein, la restauration s'arrête avant
  tout changement.
- Ensuite, l'outil remplace la base d'un coup et échange les fichiers.
- Si la restauration s'arrête après ce point, l'outil la **termine automatiquement au démarrage suivant**. Le
  journal affiche « the restore of …, interrupted, has been finished » (la restauration interrompue est terminée).
  D'ici là, `/sante/` répond `503` (« interrupted restore »).

> **Avertissement :** ne copiez jamais `db.sqlite3` à la main. Un ancien fichier `db.sqlite3-wal` resté à côté peut
> l'abîmer, sans message d'erreur. Passez toujours par `restore`.

### Sauvegarder et restaurer plusieurs espaces

Une installation peut compter plusieurs espaces (départements). Chaque espace a ses propres sauvegardes, dans
`/data/backups/spaces/<code>/`. Le registre commun des comptes a les siennes, dans `/data/backups/shared/`.
**Copiez tout `/data/backups`, sous-dossiers compris.**

Pour lancer une commande pour un seul espace, ajoutez `SPACE=<code>`. Par exemple :
`docker compose exec -e SPACE=achats web python manage.py backup`. Pour le détail (en anglais), voir
[docs/spaces.md](../spaces.md), § 2.

## 6. Mettre à jour l'outil

Pour mettre à jour l'outil :

1. Allez dans le dossier de l'outil (`probant`). Par exemple : `cd probant`.
2. Lancez `./update.sh`. Le script affiche la nouvelle version quand la mise à jour est terminée.

Le script effectue ces étapes, dans cet ordre :

1. Il fait une sauvegarde nommée « before-update » de chaque espace, avec la version installée. Si la sauvegarde d'un
   espace échoue, la mise à jour s'arrête et ne change rien.
2. Il récupère la nouvelle version :
   - Avec `git pull`, puis une nouvelle construction de l'image
   - Ou, si `IMAGE` est renseigné dans `.env`, avec `docker compose pull`
3. Il redémarre l'outil. L'outil applique les changements de structure de la base automatiquement au démarrage. Si
   la base doit changer, l'outil fait d'abord une sauvegarde automatique.
4. Il attend que l'outil réponde.

À chaque démarrage, le journal (`docker compose logs web`) affiche un court résumé en anglais. Par exemple :

```text
Probant, version 1.0.0 (3f2a9c1d7e4b)
Database: PostgreSQL (db/probant), 0 migration(s) applied; installation "Probant", 23 account(s)
Data: /data; backups: /data/backups (14 archive(s))
Address(es): reporting.example.com; HTTPS: yes
E-mails: SMTP smtp.example.com:587
```

Quand la base doit changer, le journal affiche cette ligne et le chemin de l'archive avant le résumé :
`Updating space "principal" (3 migration(s)): automatic backup before.` (mise à jour de l'espace principal :
sauvegarde automatique avant).

Le numéro de version est affiché en bas de chaque page et dans **Administration › Paramètres › Hébergement**.

### Revenir à la version précédente

> **Avertissement :** revenir en arrière remplace tout ce qui a été fait depuis la sauvegarde « before-update ».
> Prévenez les équipes, et faites-le quand personne ne saisit.

La mise à jour fait une sauvegarde « before-update » de chaque espace avant de changer quoi que ce soit. Listez les
sauvegardes : `docker compose exec web python manage.py backup --list` (ajoutez `-e SPACE=<code>` pour un autre espace).
Les archives d'un autre espace sont dans `/data/backups/spaces/<code>/`, celle du registre commun dans
`/data/backups/shared/`. La version qui a fait une archive sait toujours la lire : pour revenir en arrière, prenez la
plus ancienne archive « before-update » de la mise à jour.

Les étapes dépendent de la base :

- **SQLite** (par défaut) : faites les étapes ci-dessous, sans `--rebuild`.
- **PostgreSQL** : une sauvegarde PostgreSQL (format JSON) ne se restaure que dans une base qui a exactement ses
  migrations. Après une mise à jour, la base en a davantage. L'option `--rebuild` de `restore` supprime les tables de
  l'espace, les recrée pour la version installée, puis charge la sauvegarde. Elle fait tout cela en une seule étape : si
  une étape échoue, la base ne change pas.

Pour revenir à la version précédente :

1. Arrêtez l'outil : `docker compose stop web`.
2. Récupérez la version précédente, sans la démarrer :
   - Avec `git` : repérez-la (`git log --oneline -5`), puis lancez `git checkout <version-précédente>` et
     `docker compose build web`.
   - Avec une image publiée : mettez l'image précédente dans `IMAGE=` du fichier `.env`, puis lancez
     `docker compose pull web`.
3. Restaurez l'archive « before-update » de l'espace principal :
   `docker compose run --rm web python manage.py restore <archive before-update> --yes --rebuild`
   (SQLite : sans `--rebuild`).
4. Pour chaque autre espace, restaurez sa propre archive :
   `docker compose run --rm -e SPACE=<code> web python manage.py restore <archive de cet espace> --yes --rebuild`.
5. Facultatif : pour retrouver les comptes et les mots de passe d'avant la mise à jour, restaurez le registre commun :
   `docker compose run --rm web python manage.py restore --shared <registry-…-before-update.zip> --yes`.
   Sans cette étape, chacun garde son mot de passe actuel.
6. Démarrez l'outil : `docker compose up -d`.

Si une restauration dit que l'archive n'a pas de signature valide de cette installation (archive faite sur un autre
serveur, par exemple), relancez la même commande avec `--unsigned`.

Chaque restauration sauvegarde d'abord l'état actuel (archive « before-restore »). Gardez ces archives jusqu'à ce que
l'outil fonctionne de nouveau.

Pour mettre l'outil à jour plus tard, revenez d'abord sur la branche principale : `git checkout main`, puis
`./update.sh`. Après `git checkout <version-précédente>`, `git pull` refuse de s'exécuter (« You are not currently on a
branch ») et `update.sh` s'arrête.

#### Restaurer une sauvegarde PostgreSQL sur un nouveau serveur

Une sauvegarde PostgreSQL ne se restaure qu'avec la version de l'outil qui l'a faite, ou avec `--rebuild`. Sur un
nouveau serveur, installez l'outil, restaurez le registre commun (`restore --shared`), puis l'espace principal et chaque
autre espace (étapes 3 et 4 ci-dessus). Le nouveau serveur a une autre clé secrète : ajoutez `--unsigned` à la
restauration de chaque espace, ou copiez le fichier `.secret_key` de l'ancien dossier des données dans le nouveau avant
le premier démarrage.

## 7. Configurer les e-mails (SMTP)

Pour configurer les e-mails :

1. Ajoutez ces valeurs dans `.env` :

   ```
   SMTP_HOST=smtp.office365.com
   SMTP_PORT=587
   SMTP_SECURITY=starttls        # starttls (587), ssl (465) ou none
   SMTP_USER=reporting@example.com
   SMTP_PASSWORD=…
   SMTP_FROM=reporting@example.com
   ```

2. Lancez `docker compose up -d`.
3. Allez dans **Administration › Paramètres › Hébergement**, puis cliquez sur **Envoyer un e-mail de test**. Si
   l'e-mail ne part pas, un message donne la cause exacte.

Sans SMTP, l'outil n'envoie aucun e-mail. Il écrit seulement les messages dans le journal (`docker compose logs web`).

### Relances

L'équipe responsable gère les e-mails de relance dans **Tableau de bord › Relancer…**. Chaque personne reçoit un seul
e-mail, sans copie. L'e-mail liste ce qui lui reste à saisir. Avant d'envoyer l'e-mail, l'outil affiche l'aperçu exact
du message. L'équipe responsable règle le modèle.

L'équipe responsable peut activer les relances automatiques dans la même page. L'outil les envoie aux jours choisis
avant la fin de la saisie. Il les vérifie chaque jour à `REMINDER_TIME` (09:00 par défaut). `PUBLIC_URL` donne
l'adresse mise dans ces e-mails. Par défaut, l'outil déduit cette adresse de `DOMAIN`.

![Tableau de bord › Relances : personnes, aperçu du message, modèle et relances automatiques](../screenshots/fr/reminders.png)

## 8. Utiliser PostgreSQL (facultatif)

SQLite est la base par défaut. Vous n'avez aucun serveur de base de données à gérer. SQLite écrit un enregistrement à
la fois. Les autres enregistrements attendent leur tour, jusqu'à 60 secondes.

### Capacité

Deux essais de charge ont mesuré la capacité. La capacité dépend de la taille de la base, car chaque enregistrement
recalcule les totaux qu'il change. Ce tableau présente les résultats :

| Base | Mesure | Résultat |
|---|---|---|
| Petite (la démo) | Essai de charge, SQLite, serveur de 2 à 4 processeurs utilisés par l'outil seul | Confortable jusqu'à une centaine de personnes qui saisissent au même moment |
| Grosse (679 organisations, 1,27 million de réponses) | Essai de charge (`qa/load/README.md`, en anglais). Chaque personne simulée travaille environ dix fois plus vite qu'une vraie personne. | SQLite : 10 personnes très actives sans erreur. À partir de 15 à 20 personnes, des enregistrements échouent avec « base verrouillée » (« database is locked »). PostgreSQL : 50 personnes sans erreur ni enregistrement perdu, mais les enregistrements attendent leur tour. |

Conseil : passez à PostgreSQL au-delà d'une vingtaine de personnes actives en même temps. Passez aussi à PostgreSQL si le
serveur fait tourner d'autres programmes lourds, et donnez plus de processeurs au serveur.

Pendant les jours les plus chargés d'une campagne, évitez les opérations qui refont tout d'un coup :

- **Refaire tous les calculs** d'une campagne
- Rouvrir une campagne clôturée
- Ajouter ou désactiver une organisation
- Un import de plusieurs milliers de lignes

L'outil écrit un import par paquets de 100 lignes. Les autres personnes ne sont pas bloquées, mais l'import dure plus
longtemps. Au-delà de `BACKGROUND_IMPORT_ROWS` lignes, l'import se fait en arrière-plan, un import à la fois.

### Passer à PostgreSQL

Vous pouvez passer à PostgreSQL de 2 façons. Ce tableau présente les réglages dans `.env` pour chaque façon :

| Option | Réglage dans `.env` |
|---|---|
| PostgreSQL fourni dans le même fichier | `COMPOSE_PROFILES=postgres` et `DATABASE_URL=postgres://probant:MOT_DE_PASSE@db:5432/probant`, où `MOT_DE_PASSE` est la valeur de `POSTGRES_PASSWORD`. |
| Serveur PostgreSQL existant | `DATABASE_URL=postgres://utilisateur:motdepasse@serveur:5432/base`. Encodez un caractère spécial du mot de passe. Par exemple, `@` devient `%40`. |

Avec PostgreSQL, la sauvegarde contient la base au format JSON. Vous ne pouvez la restaurer qu'avec la version de
l'outil qui l'a faite. Pour revenir à la version précédente après une mise à jour, voyez
[Revenir à la version précédente](#revenir-à-la-version-précédente).

Après un gros chargement en une seule étape, l'outil met à jour les statistiques du planificateur de PostgreSQL
(`ANALYZE` sur les tables de l'espace). Un gros chargement est une restauration, l'installation ou la mise à jour d'un
modèle de la bibliothèque, l'import d'un fichier de configuration ou une reprise de données. L'utilisateur de la base
doit être propriétaire des tables de l'outil. C'est le cas quand l'outil les crée. Si `ANALYZE` échoue, l'opération est
gardée et le journal affiche un avertissement. PostgreSQL met alors à jour les statistiques lui-même, quelques minutes
plus tard.

### Passer d'une installation SQLite existante à PostgreSQL

Faites ce passage quand personne ne travaille dans l'outil : tout ce que les personnes saisissent après les sauvegardes de
l'étape 1 est perdu. Gardez le même dossier des données (le même volume `/data`), utilisez une base PostgreSQL vide et
gardez la même version de l'outil.

Le passage demande ces archives : une sauvegarde au format JSON pour **chaque espace**, et une archive du **registre
commun** (comptes, liste des espaces, accès). Le nouveau registre PostgreSQL a une nouvelle identité. Sans l'archive du
registre, l'outil refuse la sauvegarde de l'espace principal (« une autre installation »).

Faites ces étapes dans cet ordre :

1. Sauvegardez chaque espace au format JSON. Lancez `docker compose exec web python manage.py backup --json` pour l'espace
   principal, et `docker compose exec -e SPACE=<code> web python manage.py backup --json` pour chaque autre espace. La
   commande `docker compose exec web python manage.py spaces` liste les espaces et leurs codes.
2. Faites une archive du registre commun :
   `docker compose exec web python manage.py shell -c "from parametres import sauvegardes as SV; print(SV.creer_registre('before-postgresql'))"`.
   L'outil en fait aussi une chaque jour dans `backups/shared/` : utilisez-la seulement si personne n'a créé ni modifié de
   compte depuis.
3. Notez le nom de chaque archive : `backups/` (espace principal), `backups/spaces/<code>/` (autres espaces),
   `backups/shared/` (registre). Copiez les trois dossiers hors du serveur.
4. Changez `DATABASE_URL` dans `.env`.
5. Lancez `docker compose up -d`. L'outil démarre avec une base vide et affiche l'assistant de mise en place. N'utilisez pas
   l'assistant.
6. Restaurez le registre commun : `docker compose exec web python manage.py restore --shared <archive du registre> --yes`.
   La commande peut se terminer par une erreur de base de données sur une table qui n'existe pas (`relation
   "referentiel_utilisateur" does not exist`). C'est normal, car les autres espaces n'ont pas encore de tables. Le registre
   est restauré. Lancez `docker compose exec web python manage.py spaces` pour vérifier qu'il liste vos espaces.
7. Restaurez l'espace principal : `docker compose exec web python manage.py restore <archive de l'espace principal> --yes`.
8. Restaurez chaque autre espace : `docker compose exec -e SPACE=<code> web python manage.py restore <archive de cet espace> --yes --rebuild`.
   L'option `--rebuild` crée les tables de l'espace dans PostgreSQL avant de charger l'archive.
9. Lancez `docker compose restart web`. Connectez-vous et vérifiez les valeurs de chaque espace.

Si l'installation n'a que l'espace principal, vous pouvez faire plus court. Sautez les étapes 2, 6 et 8, et ajoutez
`--other-space` à l'étape 7. L'outil recrée alors le registre à partir des comptes de l'espace principal. Il ne garde ni le
nom de l'espace, ni les comptes qui n'existent que dans un autre espace.

La commande `python manage.py shell` de l'étape 2 est le seul moyen de faire une archive du registre à la demande : l'outil n'a
pas de commande pour cela. Nous avons comparé les données de l'installation PostgreSQL à celles de l'installation SQLite,
table par table, pour deux espaces : elles sont identiques (seuls les numéros des lignes d'accès du registre changent).

### Plusieurs espaces avec PostgreSQL

Chaque espace (département) ouvre ses propres connexions à la base. Avant de créer beaucoup d'espaces, vérifiez la
limite de connexions de votre offre (petites offres Clever Cloud). Voir [docs/spaces.md](../spaces.md) (en anglais).

## 9. Superviser l'outil et lire les journaux

### Vérifier que l'outil va bien

`GET /sante/` répond avec l'un de ces codes :

- `200` avec `{"etat": "ok"}` : l'outil fonctionne.
- `503` avec `{"etat": "erreur"}` : la base ou le stockage a un problème, la base est abîmée, une restauration a été
  interrompue, ou le disque est presque plein (moins de 100 Mo libres, réglage `DISK_ALERT_MB`). Le détail donne la
  cause dans `alerte`.

La page ne demande aucune connexion et n'expose aucune donnée sensible. Docker s'en sert aussi : `docker compose ps`
affiche `healthy`.

L'outil ne donne le détail de toute l'installation qu'à un appel depuis le serveur lui-même (depuis `127.0.0.1`, sans
aucun des en-têtes qu'ajoute un proxy : `X-Forwarded-For`, `X-Real-IP`, `Forwarded`), à un gestionnaire des espaces
connecté et à un administrateur de l'espace principal connecté. L'administrateur d'un autre espace reçoit le détail de
son espace seulement : le registre commun et le disque sont mesurés, mais les noms, pannes et tâches bloquées des autres
espaces et les dossiers du disque ne sont pas montrés. Les autres personnes reçoivent l'état seul. La raison : la version
exacte aiderait à repérer une installation pas à jour, et l'administrateur d'un espace n'a pas à connaître les autres
espaces. Pour voir le détail depuis le serveur, lancez cette commande :

```bash
docker compose exec web python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/sante/').read().decode())"
```

Ce tableau présente les champs du détail :

| Champ | Contenu |
|---|---|
| `version`, `base`, `stockage`, `derniere_sauvegarde` | La version, l'état de la base et du stockage, et la date de la dernière sauvegarde |
| `alerte` | La cause d'une réponse `503` |
| `avertissement` | Un avertissement qui ne cause pas de `503`, par exemple un import ou un export bloqué, ou une sauvegarde datée dans le futur |
| `controle_donnees` | Le dernier contrôle des données : `etat` (`ok`, `problems`, `late` sans contrôle des données depuis 48 heures, `never`), `date`, `erreurs`, `avertissements` |
| `background_imports` | L'état des imports en arrière-plan (voir « Vérifier qu'un gros import n'est pas bloqué ») |
| `background_exports` | L'état des gros exports en arrière-plan : `running`, `waiting`, `stuck` (même section) |

Un problème de données ou un contrôle en retard ne fait **jamais** répondre `503` à `/sante/`. `503` veut dire
« l'outil ne répond pas ». Docker ou Clever Cloud redémarrent alors l'outil, et un redémarrage ne corrige ni un
chiffre ni un planificateur arrêté. Pour surveiller le contrôle de chaque nuit, créez une alerte sur
`controle_donnees.etat` = `late`.

![Réponse de /sante/](../screenshots/fr/health.png)

Les administrateurs lisent les mêmes mesures, en clair, dans **Administration › Paramètres › Santé** : une ligne par
contrôle (version, base de données, fichiers, dernière sauvegarde, espace disque, e-mails, tâches de fond, mise à jour de
la base, HTTPS), avec **Bon**, **À regarder** ou **En panne** et que faire. Le détail pour l'IT (noms des espaces, dossiers
du disque, messages de `/sante/`) n'est montré qu'aux gestionnaires des espaces et aux administrateurs de l'espace principal.
La même règle vaut pour le volet « Pour l'IT » de **Paramètres › Hébergement** : dans un autre espace, l'administrateur qui
n'est pas gestionnaire des espaces ne voit ni le dossier des données, ni les adresses permises, ni le serveur de la base,
ni l'identifiant SMTP, ni le dossier des sauvegardes.

### Vérifier que les données sont cohérentes

Chaque nuit à `DATA_CHECK_TIME` (03:30), l'outil vérifie la base de chaque espace. Il **ne modifie rien**. Il vérifie
ces points :

- Chaque total et chaque calcul enregistré, dans les périodes non clôturées : l'outil le refait en mémoire et compare
  (pour les périodes clôturées, il signale seulement)
- Aucune valeur rattachée à un KPI ou une organisation supprimés, à une période sans campagne, ou enregistrée deux fois
- Des statuts cohérents
- Des pourcentages plausibles (−100 % à 1 000 %)
- Les chiffres de KPI calculés importés tels quels dans une période ouverte
- Les attributions des campagnes ouvertes à des comptes inactifs ou en lecture seule, ou à des organisations fermées
- Les fichiers des preuves présents sur le disque (et les fichiers restés dans `files/evidence`)
- Les formules et leurs dépendances enregistrées
- Un arbre sans boucle, aux niveaux cohérents
- Une dernière sauvegarde lisible (zip valide, `backup.json`)

L'outil garde les 10 derniers résultats dans `backups/data-checks.json`, hors de la base, comme `restores.jsonl`.
L'administrateur les voit dans **Administration › Paramètres › Hébergement**, dans l'encart **Contrôle des données**.
Cet encart a le bouton **Contrôler maintenant**. Quand le contrôle trouve un problème, il apparaît aussi dans
**À traiter**.

Pour lancer le contrôle à la main, lancez `docker compose exec web python manage.py check_data`. Le nom français
`controler_donnees` fonctionne aussi. La commande a ces options et ces résultats :

- Sortie : texte lisible en anglais, ou JSON avec `--json`
- `--no-save` : l'outil ne garde pas le résultat
- `SPACE=<code>` : un seul espace
- Code de sortie 1 si le contrôle trouve une erreur
- Durée : quelques secondes (6 s sur la démo, avec 6 exercices)

### Éléments supprimés (corbeille) et sessions terminées

Quand une personne supprime un export enregistré, une liste de KPI ou une vue de la Visualisation, l'outil le garde
dans une corbeille, pour que la personne puisse annuler la suppression ou restaurer l'élément depuis
**Mon compte › Récemment supprimés**. Un administrateur voit les éléments de tous dans
**Administration › Historique › Récemment supprimés**. La corbeille garde les éléments 30 jours par défaut. Un
administrateur règle ce délai, de 1 à 365 jours, dans **Administration › Paramètres › Hébergement**, encart
**Éléments supprimés**. Après ce délai, l'outil efface l'élément pour de bon.

Le processus `check_data --schedule` fait aussi un ménage chaque nuit à `DATA_CHECK_TIME`, et une fois à son lancement :

- Il efface les sessions terminées, comme `manage.py clearsessions`. Les sessions de tous les espaces sont dans le
  registre commun. Une session encore valide n'est jamais effacée.
- Il efface les éléments supprimés depuis plus longtemps que le délai, dans chaque espace.
- Il écrit une ligne dans le journal : `Nightly clean-up: N expired session(s) and N deleted item(s) erased for good`.

Vous n'avez rien à planifier. L'outil le fait aussi à chaque démarrage (`manage.py startup`), et efface les anciens
éléments supprimés à chaque suppression. Pour effacer les éléments supprimés à la main, lancez
`docker compose exec web python manage.py purge_deleted` (nom français : `purger_corbeille` ; `SPACE=<code>` pour un
seul espace). Pour effacer les sessions terminées à la main, lancez
`docker compose exec web python manage.py clearsessions`.

### Vérifier qu'un gros import n'est pas bloqué

Le même processus fabrique les gros exports (au-delà du seuil que l'administrateur règle dans **Administration ›
Paramètres › Hébergement › Gros exports**) : leurs fichiers sont dans `files/exports/` du dossier des données, effacés
après 7 jours, jamais dans les sauvegardes (rien à copier).

Les gros imports de valeurs se font en arrière-plan, dans le processus `run_imports --schedule`. L'image lance ce
processus à côté des sauvegardes, des relances et du contrôle des données. Le détail de `/sante/` donne
`background_imports` pour les imports et `background_exports` pour les gros exports, avec les trois mêmes champs :

- `running` : le nombre d'imports (ou d'exports) qui tournent
- `waiting` : le nombre d'imports (ou d'exports) qui attendent
- `stuck`, avec un `message` (repris dans `avertissement`) : un import (ou un export) qui ne donne plus signe de vie,
  ou qui attend depuis plus de 10 minutes

Si un import ou un export est bloqué :

1. Vérifiez que le processus tourne : `docker compose logs web | grep "Background"`.
2. Si besoin, redémarrez l'outil : `docker compose restart web`.

Un import ou un export bloqué ne fait jamais répondre `503` à `/sante/`. Si un redémarrage arrête une tâche, la tâche
reprend une fois d'elle-même. Ensuite, l'outil la marque « interrompue » : il invite la personne à réimporter le
fichier, ou à redemander l'export.

### Lire le journal et gérer les services

Ce tableau présente les autres opérations de supervision :

| Pour… | Faire |
|---|---|
| Lire le journal | Lancez `docker compose logs -f web`. Chaque ligne porte la date. Le journal contient le démarrage (version, base, adresses, e-mails), chaque requête (adresse, page, code, durée), les sauvegardes et les erreurs. Comme ce qu'affichent les commandes `manage.py`, le journal est toujours en anglais, quelle que soit la langue de l'interface. |
| Voir l'état des services | Lancez `docker compose ps`. |
| Redémarrer | Lancez `docker compose restart web`. |
| Arrêter, puis relancer | Lancez `docker compose down`, puis `docker compose up -d`. Les données restent dans le volume. |

## 10. Dépannage

Ce tableau présente les problèmes courants, leur cause probable et la solution :

| Symptôme | Cause probable et solution |
|---|---|
| `Bad Request (400)` à l'ouverture | L'adresse n'est pas dans `DOMAIN`. Ajoutez-la dans `.env` (séparez plusieurs valeurs par des virgules). Puis lancez `docker compose up -d`. |
| La page ne s'ouvre pas | Vérifiez que le service tourne (`docker compose ps`). Vérifiez que le pare-feu ouvre le port. Puis lisez `docker compose logs web`. |
| Boucle de redirection ou erreur CSRF (403) en HTTPS | `DJANGO_HTTPS=1` est réglé, mais le proxy ne transmet pas `X-Forwarded-Proto: https`. Caddy le transmet automatiquement. Avec un autre proxy (nginx, Traefik…), ajoutez cet en-tête. |
| Pas de certificat HTTPS | Le nom de domaine doit pointer vers le serveur, et les ports 80 et 443 doivent être ouverts. Lisez `docker compose logs caddy`. |
| « The folder /data is not writable by the tool » (le dossier /data n'est pas modifiable) | Un dossier monté à la place du volume appartient à un autre utilisateur. Lancez `sudo chown -R 1000:1000 <dossier>`. |
| « Database unreachable » (base de données injoignable) | Avec PostgreSQL, vérifiez `DATABASE_URL`. Puis lisez `docker compose logs db`. |
| « DAMAGED DATABASE » (base abîmée) dans le journal, `/sante/` répond `503` « damaged database » | Le contrôle du démarrage (ou d'une sauvegarde) a trouvé le fichier SQLite abîmé (panne de disque, fichier copié à la main à côté d'un ancien fichier `-wal`…). L'outil démarre sans mettre la base à jour et refuse de la sauvegarder : les bonnes archives restent. Le journal donne la dernière bonne archive. Restaurez-la : `docker compose exec web python manage.py restore <cette archive> --yes`. Puis lancez `docker compose restart web`. L'outil garde l'état abîmé : une archive « before-restore-damaged », ou le fichier renommé `db.sqlite3.damaged-<date>` s'il ne s'ouvre plus. Si aucune archive n'est bonne, prenez la copie externe des sauvegardes. |
| « Not enough disk space » (plus de place : sauvegarde, mise à jour ou restauration), `/sante/` « disk almost full » | Rien n'est écrit à moitié. L'outil ne garde pas la sauvegarde et n'applique pas la mise à jour (la base ne change pas). Il annule la restauration. Libérez de la place : copiez les anciennes archives hors du serveur, ou agrandissez le disque. Puis relancez la commande, ou lancez `docker compose restart web`. Les personnes qui enregistrent voient « Enregistrement impossible pour l'instant ». Rien de ce qu'elles ont fait n'est enregistré à moitié. |
| « This archive has no valid signature of this installation » (commande de restauration), ou « Cette sauvegarde n'a pas été faite par cette installation » (page Hébergement) | Rien n'a changé. L'archive a été faite par une version antérieure, par un autre serveur, ou avant un changement de `DJANGO_SECRET_KEY`, ou quelqu'un l'a modifiée. Si vous lui faites confiance, restaurez-la en ligne de commande avec `--unsigned` : `docker compose exec web python manage.py restore <archive> --yes --unsigned`. Si vous ne savez pas d'où elle vient, ne la restaurez pas. |
| « The database was updated by a more recent version of the tool » ou « made with other database migrations » (restauration, PostgreSQL) | Rien n'a changé. Le message donne la commande exacte. Pour revenir en arrière après une mise à jour, voyez [Revenir à la version précédente](#revenir-à-la-version-précédente). Pour restaurer sur un nouveau serveur, installez d'abord la version qui a fait la sauvegarde. Pour restaurer une archive plus ancienne après une mise à jour : restaurez-la avec la version qui l'a faite, puis mettez de nouveau l'outil à jour avec `./update.sh`. |
| « the restore of … was interrupted and could not be finished » (restauration interrompue, pas terminée) | L'archive nommée dans le message manque ou ne se lit pas. Restaurez-la de nouveau (`python manage.py restore <nom> --yes`). Pour revenir à l'état d'avant, restaurez l'archive « before-restore ». |
| Tout le monde doit se reconnecter après un redémarrage | Le fichier `.secret_key` du dossier des données a été supprimé ou était vide. L'outil a créé une nouvelle clé (journal : « New secret key created »). Rien d'autre n'est perdu. |
| Horloge du serveur fausse (date dans le futur, puis corrigée) | L'outil garde les sauvegardes datées dans le futur, mais ne les compte pas dans la rotation. La prochaine sauvegarde automatique se fait à l'heure habituelle. `/sante/` le signale (`avertissement`). Corrigez l'horloge (NTP). |
| « database is locked » | Un enregistrement a attendu son tour plus de 60 secondes : SQLite écrit un enregistrement à la fois. C'est rare, car SQLite fonctionne en mode WAL. Quand cela arrive, le serveur est surchargé. Vérifiez que l'outil a ses processeurs pour lui seul (`docker stats`). Évitez **Refaire tous les calculs** et les gros imports aux heures les plus chargées. Puis donnez plus de processeurs au serveur, ou passez à PostgreSQL (section 8). |
| L'e-mail de test échoue | Le message donne la cause (identifiant refusé, port bloqué, TLS…). Vérifiez les réglages `SMTP_…` avec le fournisseur de messagerie. |
| L'assistant IA dit « Le serveur ne peut pas joindre le fournisseur » | Ouvrez les connexions HTTPS sortantes vers `api.anthropic.com` dans le pare-feu, ou réglez `HTTPS_PROXY` (section 4, « Assistant IA »). |
| Mot de passe administrateur perdu | Un autre administrateur le réinitialise dans **Administration › Comptes**. S'il n'y a pas d'autre administrateur, lancez `docker compose exec web python manage.py changepassword <e-mail>`. |
| Plus aucun compte n'ouvre **Administration** | L'outil ne laisse jamais le dernier administrateur actif perdre son rôle ou son accès. Cela peut tout de même arriver après la restauration d'une ancienne sauvegarde, ou après un changement fait directement dans la base. Rendez le rôle d'administrateur à un compte existant : `docker compose exec web python manage.py grant_admin <e-mail>`. L'outil inscrit le changement dans l'historique. |
| Tout recommencer depuis zéro (essai) | **Avertissement :** cela **efface toutes les données**. Lancez `docker compose down -v`, puis `./install.sh`. |

## 11. Tester l'installation

Le script `bash docker/test_installation.sh` reproduit une installation sur une machine vierge. Il copie le dépôt dans
un dossier vide et lance `./install.sh`. Ensuite, il vérifie ces points :

- La page de santé
- L'assistant, affiché à la place de la page de connexion
- Les fichiers statiques et la compression
- Les en-têtes de sécurité
- `check --deploy` en HTTPS
- La sauvegarde
- La mise à jour, avec une sauvegarde faite avant
- Les données, gardées après la mise à jour

À la fin, le script supprime tout ce qu'il a créé. Pour lancer le même test avec les tests de l'outil, lancez
`TESTER_DOCKER=1 python manage.py test parametres.test_hebergement`.
