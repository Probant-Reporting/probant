# Installer Probant

> Version française du guide anglais [docs/installation.md](../installation.md), qui fait référence.

Ce guide s'adresse à l'équipe informatique. Il explique comment installer Probant sur un serveur Linux avec Docker,
puis comment le mettre en place, le sauvegarder, le mettre à jour et le superviser. Vous n'avez pas besoin de
connaître Django ni Python.

L'outil tourne dans **un seul conteneur Docker**. Toutes ses données sont dans **un seul volume**, `/data` : base,
preuves, logo, sauvegardes et clé secrète.

Ce tableau indique la façon de faire selon votre cas :

| Votre cas | Suivez | Durée |
|---|---|---|
| Un serveur Linux qui a accès à Internet (le cas courant) | [Installer en une commande](#installer-en-une-commande) | 2 minutes environ |
| Vous voulez que le serveur construise l'image à partir du code | [Installer avec Git](#installer-avec-git) | 3 à 5 minutes |
| Un serveur sans accès à Internet | [Installer sans accès à Internet](#installer-sans-accès-à-internet) | |
| Vous ne voulez pas gérer de serveur | [Hébergement clé en main (Clever Cloud)](hebergement_cle_en_main.md) | 30 minutes environ |
| Un essai par une personne, sur un ordinateur Windows ou Mac | La version tout-en-un : `probant-windows.zip` ou `probant-mac.zip` sur la page de la dernière release (https://github.com/Probant-Reporting/probant/releases/latest). Elle ne demande ni installation, ni droits d'administration. Pour passer ensuite ses données sur un serveur, voir [De la version tout-en-un à un serveur](du_pc_au_serveur.md). | |

Avant de commencer, il vous faut un serveur Linux 64 bits avec 1 Go de mémoire, et un compte qui peut utiliser
`sudo`. Sur Debian ou Ubuntu, vous n'avez pas à installer Docker d'abord : l'installeur propose de l'installer. La
liste complète est à la section 1. La liste de ce que l'IT prépare est dans [Ce qu'il faut préparer](demande_it.md),
et le dossier pour une revue de sécurité est dans le [Dossier de sécurité](dossier_securite.md).

Juste après l'installation, ouvrez l'adresse de l'outil et créez le compte administrateur (section 3).

Ce tableau présente les opérations courantes, dans le dossier de l'outil :

| Opération | Commande | Durée |
|---|---|---|
| Mettre à jour | `./update.sh` | 1 à 3 minutes |
| Sauvegarder | Rien : automatique chaque nuit. Tout de suite : `docker compose exec web python manage.py backup` | Quelques secondes |
| Restaurer | `docker compose exec web python manage.py restore <archive>` | Quelques secondes |

## 1. Prérequis

Ce tableau présente ce qu'il faut avant d'installer l'outil :

| Besoin | Minimum conseillé |
|---|---|
| Serveur | Linux 64 bits sur `x86_64` (sur `arm64`, seulement avec l'installation par Git), par exemple Debian 12 ou plus récent, ou Ubuntu 22.04 ou plus récent. 1 processeur, 1 Go de mémoire, 5 Go de disque |
| Logiciels | Sur Debian ou Ubuntu : rien à installer d'avance, sauf `curl` s'il manque. L'installeur propose d'installer Docker, et attend votre oui. Sur un autre système Linux : installez d'abord Docker Engine 24 ou plus récent avec l'extension Compose v2.24 ou plus récente (`docker compose version`). Git seulement pour installer avec Git |
| Compte | Un compte qui peut utiliser `sudo` |
| Réseau, accès interne | 1 port ouvert vers le serveur (8000 par défaut) |
| Réseau, accès HTTPS | Un nom de domaine qui pointe vers le serveur (par exemple `reporting.example.com`), et les ports 80 et 443 (TCP, et UDP 443 pour HTTP/3) ouverts depuis Internet (certificat Let's Encrypt automatique). Avec le certificat de votre entreprise, Internet n'a pas besoin de joindre le serveur : voir « Réseau d'entreprise » |
| Réseau, téléchargements | Connexions HTTPS sortantes (TCP 443) du serveur, pendant l'installation et chaque mise à jour : `github.com` et `raw.githubusercontent.com` (fichiers), `objects.githubusercontent.com` et `release-assets.githubusercontent.com` (liste des empreintes des fichiers, jointe à la release), `ghcr.io` et `pkg-containers.githubusercontent.com` (image de l'outil et conteneur de cosign), `tuf-repo-cdn.sigstore.dev` (racine de confiance de Sigstore, pour vérifier les signatures). Avec le HTTPS (`--domain`) : aussi Docker Hub (image de Caddy). Avec Git : aussi Docker Hub et PyPI (le serveur construit l'image). Avec les mises à jour automatiques (section 6), le serveur ouvre les mêmes connexions la nuit. Pour installer Docker par l'installeur : `download.docker.com` et les miroirs de paquets du système. Sans accès à Internet : aucune (voir « Installer sans accès à Internet ») |
| E-mails (facultatif) | Un compte SMTP (serveur, port, identifiant, mot de passe, adresse d'expédition) |
| Assistant IA (facultatif) | Connexions HTTPS sortantes (TCP 443) du serveur vers `api.anthropic.com`, seulement si un administrateur allume l'assistant. Voir « Assistant IA » à la section 4 |

Le serveur n'a besoin ni de Python, ni d'un serveur web, ni d'une base de données. Tout est dans l'image.

### Installer Docker sur Debian ou Ubuntu

Si Docker manque, l'installeur pose cette question :
`Install Docker now, from Docker's apt repository (download.docker.com)? [y/N]`. Tapez `y` pour l'installer. Toute
autre réponse arrête l'installeur, et rien ne change.

L'installeur suit la procédure officielle de Docker (https://docs.docker.com/engine/install/) : il ajoute le dépôt apt
de Docker, vérifié par la clé de Docker, puis installe les paquets `docker-ce`, `docker-ce-cli`, `containerd.io`,
`docker-buildx-plugin` et `docker-compose-plugin`. Ses règles sont les suivantes :

- Il n'installe jamais Docker sans un oui. Sans terminal (un déploiement automatique, par exemple), ajoutez l'option
  `--yes` pour répondre oui.
- Il n'installe Docker que sur Debian et Ubuntu. Sur un autre système, il s'arrête : installez Docker vous-même, puis
  relancez l'installeur.
- Il a besoin des droits d'administration : lancez-le en `root` ou avec `sudo`. Sinon, il s'arrête et ne change rien.

Pour utiliser Docker sans `sudo`, ajoutez votre compte au groupe `docker` (`sudo usermod -aG docker $USER`), puis
déconnectez-vous et reconnectez-vous. Un membre de ce groupe a les mêmes droits que `root` sur le serveur.

## 2. Installer l'outil

Vous pouvez installer l'outil de deux façons. Ce tableau les compare :

| Façon | Ce qu'il faut sur le serveur, en plus de Docker | Durée |
|---|---|---|
| En une commande (conseillé) | `curl` | 2 minutes environ : le serveur télécharge l'image publiée |
| Avec Git | Git | 3 à 5 minutes : le serveur construit l'image |

Les deux façons donnent le même outil, avec les mêmes réglages et les mêmes sauvegardes. Seule l'installation en une
commande pose les mises à jour automatiques (section 6). Pour un serveur sans accès à Internet, voir « Installer sans
accès à Internet ».

### Vérifier le serveur avant d'installer

Vous n'avez pas à lancer ce contrôle vous-même : l'installeur le lance au début d'une installation neuve. Lancez-le
avant si vous voulez savoir ce qui manque sans rien installer. Le contrôle lit le serveur et ne change rien. C'est le
script `check.sh`, dans les fichiers de chaque version.

Pour vérifier le serveur avant une installation en une commande, lancez la commande de l'installation avec
`--check` :

```bash
curl -fsSL https://github.com/Probant-Reporting/probant/raw/main/get.sh | sudo sh -s -- --check
```

Ajoutez les options de l'installation, par exemple `--domain reporting.example.com` ou `--port 8080`. La commande
télécharge le contrôle de la version dans un dossier temporaire, le lance, puis supprime le dossier. Dans un dossier
qui contient les fichiers de l'outil (une installation avec Git, par exemple), lancez `./install.sh --check`, avec les
mêmes options.

Ce tableau présente ce que vérifie le contrôle :

| Contrôle | Ce qu'il vérifie |
|---|---|
| Système et architecture | Linux, 64 bits. L'image publiée est pour `x86_64` : sur `arm64`, installez avec Git. |
| Docker et Compose | Docker Engine 24 ou plus récent, extension Compose v2.24 ou plus récente (section 1). |
| Service Docker | Docker répond, et le compte a le droit de l'utiliser (`sudo`, ou le groupe `docker`). |
| Mémoire, processeurs, disque | Au moins 1 Go de mémoire, 1 processeur, et 5 Go libres dans le dossier de Docker. |
| Ports | Le port HTTP est libre (8000, ou `--port`). Avec `--domain` : aussi les ports 80 et 443. |
| Nom de domaine | Avec `--domain` : le nom pointe vers une adresse du serveur. |
| Réseau | Le registre de l'image et GitHub (fichiers de la version) répondent en HTTPS, par `HTTPS_PROXY` s'il est réglé. Avec un proxy, il vérifie aussi que le service Docker peut télécharger l'image. |
| Horloge | L'heure du serveur est juste : 5 minutes au plus d'écart avec l'heure de GitHub. |

Le contrôle affiche une ligne par contrôle :

- `OK` : rien à faire.
- `To fix` (à corriger) : la ligne dit quoi faire, en une phrase.
- `Not checked` (non vérifié) : la ligne dit pourquoi. Par exemple, un serveur derrière un routeur (NAT) ne connaît pas
  son adresse publique. Le contrôle ne peut pas savoir si le nom de domaine pointe vers lui. Vérifiez vous-même
  l'enregistrement DNS et le routeur.

À la fin, le contrôle affiche `Ready` (prêt), ou `Here is what is missing` (ce qui manque) avec la liste des points à
corriger. Il se termine avec le code de sortie 0 (prêt) ou 1 (il manque quelque chose).

Au début d'une installation neuve (un dossier sans `.env`), si un point est à corriger, l'installeur s'arrête et
n'installe rien. Un Docker absent ne l'arrête pas : l'installeur propose ensuite d'installer Docker. Pour installer
sans le contrôle, ajoutez `--skip-check`. N'utilisez cette option que si vous savez
pourquoi le contrôle échoue. Par exemple, derrière un proxy que le contrôle ne sait pas utiliser.

Si le réseau passe par un proxy, réglez-le avant le contrôle : `sudo HTTPS_PROXY=http://proxy.example.com:3128 sh …`.
Avec `sudo`, les variables de votre session ne passent pas au script. Docker télécharge l'image lui-même : réglez aussi
le proxy du service Docker (https://docs.docker.com/engine/daemon/proxy/).

### Installer en une commande

La commande utilise l'image publiée de l'outil, `ghcr.io/probant-reporting/probant`. Le serveur ne construit rien, et
il n'a pas besoin de Git.

Pour installer l'outil :

1. Connectez-vous au serveur avec un compte qui peut utiliser `sudo`.
2. Allez dans le dossier qui contiendra le dossier de l'outil (par exemple `cd /opt`).
3. Lancez la commande :

   ```bash
   curl -fsSL https://github.com/Probant-Reporting/probant/raw/main/get.sh | sudo sh
   ```

   Pour le HTTPS avec un nom de domaine, ajoutez les options après `sh -s --` :

   ```bash
   curl -fsSL https://github.com/Probant-Reporting/probant/raw/main/get.sh | sudo sh -s -- --domain reporting.example.com
   ```

   La commande affiche l'adresse à ouvrir et le dossier de l'installation.
4. Allez dans le dossier de l'outil : `cd probant`. Lancez les autres commandes de ce guide dans ce dossier.

> **Remarque :** les mises à jour automatiques sont allumées après cette installation : le serveur installe chaque
> nouvelle version la nuit, 3 jours après sa publication. Pour installer sans elles, ajoutez `--auto-update off`.
> Voir « Mises à jour automatiques » (section 6).

La commande effectue ces étapes, dans cet ordre :

1. Elle trouve la dernière version publiée de l'outil.
2. Elle crée le dossier `probant`. Si ce dossier contient déjà une installation, la commande s'arrête et ne change
   rien.
3. Elle télécharge dans ce dossier les seuls fichiers qui font tourner l'outil : `docker-compose.yml`, `.env.example`,
   `install.sh`, `update.sh`, `check.sh`, `docker/Caddyfile` et `auto-update.sh`. Ils viennent de l'étiquette de
   cette version dans le dépôt public (https://github.com/Probant-Reporting/probant), en HTTPS seulement.
4. Elle contrôle chaque fichier avec la liste des empreintes SHA-256 (une empreinte par fichier) jointe à la release
   de cette version (`probant-X.Y.Z-files.sha256`). La release est la page de la version sur GitHub, avec ses
   fichiers. La commande vérifie aussi la signature de cette liste avec cosign (l'outil de signature de Sigstore),
   quand cosign est sur le serveur ou quand Docker répond. Si la liste manque, si sa signature est refusée, ou si un
   seul fichier ne correspond pas, la commande s'arrête et n'installe rien. La commande dit ce qu'elle a vérifié.
5. Elle lance `./install.sh` avec l'image publiée de cette version. Voir « Ce que fait l'installeur ».
6. Elle pose la minuterie des mises à jour automatiques (voir la remarque plus haut).

Ce tableau présente les options de la commande :

| Option | Effet |
|---|---|
| `--version X.Y.Z` | Installe cette version au lieu de la dernière. |
| `--dir DOSSIER` | Installe dans ce dossier au lieu de `probant`. |
| `--check` | Vérifie seulement le serveur, et n'installe rien. Voir « Vérifier le serveur avant d'installer ». |
| `--auto-update off` | Installe sans les mises à jour automatiques (section 6). |
| `--domain`, `--port`, `--yes`, `--skip-check` | Options de `./install.sh`. Voir le tableau de « Ce que fait l'installeur ». |

Le contrôle des fichiers apporte cette protection :

- Il trouve un fichier changé ou abîmé en chemin (un proxy, un miroir, un cache), et une étiquette déplacée après la
  release.
- Avec la signature vérifiée, seul le workflow `image.yml` du dépôt public, pour cette étiquette, peut faire la liste.
  Chaque signature est inscrite dans le journal public de transparence de Sigstore.
- Il ne protège pas d'une personne qui peut changer le dépôt et lancer son workflow.
- Il ne contrôle ni `get.sh` lui-même (voir « Lire le script avant de le lancer »), ni la signature de l'image (voir
  « Vérifier l'image »).

Les versions publiées avant ces listes (1.0.0 et 1.0.1) n'en ont pas : la commande les refuse. Juste après une
publication, la liste peut manquer pendant une heure au plus : réessayez plus tard.

### Lire le script avant de le lancer

Si vos règles de sécurité n'autorisent pas un script à se lancer dès son téléchargement, suivez ces étapes :

1. Téléchargez le script : `curl -fsSLO https://github.com/Probant-Reporting/probant/raw/main/get.sh`.
2. Lisez-le : `less get.sh`. Le script est court, et des commentaires expliquent chaque étape. Hors du dossier de
   l'installation, il ne change que deux choses : Docker, si vous acceptez de l'installer, et la minuterie des mises
   à jour automatiques (sauf avec `--auto-update off`).
3. Lancez-le, avec les mêmes options que la commande : `sudo sh get.sh` (ou `sudo sh get.sh --domain reporting.example.com`).

Le script lance ensuite le `install.sh` de la version. Avant, vous pouvez lire `install.sh` et `update.sh` dans le
dépôt public, à l'étiquette de la version (`vX.Y.Z`).

Pour vérifier le script avant de le lancer, téléchargez-le depuis l'étiquette de la version, avec la liste des
empreintes SHA-256 de la release. Remplacez `X.Y.Z` par la version (la dernière est sur
https://github.com/Probant-Reporting/probant/releases/latest) :

```bash
curl -fsSLO https://github.com/Probant-Reporting/probant/raw/refs/tags/vX.Y.Z/get.sh
curl -fsSLO https://github.com/Probant-Reporting/probant/releases/download/vX.Y.Z/probant-X.Y.Z-files.sha256
curl -fsSLO https://github.com/Probant-Reporting/probant/releases/download/vX.Y.Z/probant-X.Y.Z-files.sha256.sigstore.json
sha256sum -c --ignore-missing probant-X.Y.Z-files.sha256
```

La dernière commande affiche `get.sh: OK`. Pour vérifier la liste elle-même, utilisez cosign version 3 ou plus
récente. Si la signature est correcte, cosign affiche `Verified OK` :

```bash
cosign verify-blob probant-X.Y.Z-files.sha256 \
  --bundle probant-X.Y.Z-files.sha256.sigstore.json \
  --certificate-identity https://github.com/Probant-Reporting/probant/.github/workflows/image.yml@refs/tags/vX.Y.Z \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

Lancez ensuite `sudo sh get.sh --version X.Y.Z`, avec les mêmes options que la commande.

### Ce que fait l'installeur

L'installeur est `./install.sh`. Il effectue ces étapes, dans cet ordre :

1. Pour une installation neuve, il vérifie le serveur (voir « Vérifier le serveur avant d'installer »). Si un point
   est à corriger, il s'arrête et n'installe rien.
2. Il vérifie que Docker répond. Si Docker manque, il propose de l'installer (voir « Installer Docker sur Debian ou
   Ubuntu »).
3. Il crée le fichier de réglages `.env` à partir de `.env.example`. Il ne remplace pas un fichier `.env` existant.
4. Il récupère l'image : il télécharge l'image publiée si `IMAGE` est renseigné dans `.env`, sinon il construit l'image.
5. Il démarre l'outil et attend qu'il réponde.
6. Il affiche l'adresse à ouvrir.

Ce tableau présente les options de `./install.sh` :

| Option | Effet |
|---|---|
| Sans option | L'outil s'ouvre en HTTP sur `http://ADRESSE-DU-SERVEUR:8000`. Utilisez-la pour un réseau interne ou un essai. |
| `--domain reporting.example.com` | L'outil s'ouvre en HTTPS. L'installeur ajoute Caddy, le proxy HTTPS fourni, devant l'outil. Caddy obtient le certificat auprès de Let's Encrypt automatiquement. Le port 8000 n'est alors ouvert qu'au serveur lui-même. |
| `--port 8080` | L'outil utilise un autre port HTTP. |
| `--image ghcr.io/probant-reporting/probant:X.Y.Z` | L'outil utilise cette image publiée (le réglage `IMAGE` de `.env`). Le serveur la télécharge et ne la construit pas. |
| `--yes` | Si Docker manque, l'installeur l'installe sans poser la question. |
| `--check` | Vérifie seulement le serveur, avec les autres options, et n'installe rien. |
| `--skip-check` | Installe sans le contrôle du serveur. |
| `--offline probant-image-X.Y.Z.tar.gz` | Installe sans accès à Internet, avec l'image du paquet hors ligne. Voir « Installer sans accès à Internet ». |
| `--cert FICHIER --key FICHIER` | Avec `--domain` : Caddy sert le certificat HTTPS de votre entreprise, et ne contacte jamais Let's Encrypt. Sur une installation qui tourne : renouvelle le certificat. Voir « Réseau d'entreprise ». |
| `--ca-cert FICHIER` | Ajoute une autorité de certification de votre entreprise pour les connexions sortantes de l'outil. Répétez l'option pour plusieurs autorités. Voir « Réseau d'entreprise ». |
| `--auto-update on` ou `off` | Pose ou retire la minuterie des mises à jour automatiques, avec une image publiée seulement. `--auto-update-time HH:MM` choisit son heure (04:00 par défaut). Voir « Mises à jour automatiques » (section 6). |

### Installer avec Git

Utilisez cette façon pour installer l'outil à partir du code, par exemple pour suivre le dépôt avec `git pull`.

Pour installer l'outil avec Git :

1. Récupérez le code et allez dans son dossier :

   ```bash
   git clone https://github.com/Probant-Reporting/probant.git probant
   cd probant
   ```

2. Lancez l'installeur :

   ```bash
   ./install.sh                      # ou : ./install.sh --domain reporting.example.com
   ```

   Le serveur construit l'image. Pour cela, il télécharge l'image de base depuis Docker Hub et les paquets Python
   depuis PyPI. Pour utiliser l'image publiée à la place, ajoutez `--image ghcr.io/probant-reporting/probant:X.Y.Z`,
   avec la version du code.

### Installer sans le script

Pour faire la même installation à la main, dans le dossier du code (voir « Installer avec Git ») :

1. Créez le fichier de réglages : `cp .env.example .env`.
2. Ouvrez le fichier (`nano .env`) et réglez au moins `DOMAIN`.
3. Construisez et démarrez l'outil : `docker compose up -d --build`.

### Vérifier l'image

Cette partie est facultative. Elle concerne une installation qui utilise l'image publiée (`IMAGE` dans `.env`, voir
la section 4). L'installation et `./update.sh` ne vérifient pas la signature de l'image : faites-le vous-même ici si
vos règles de sécurité le demandent. Les mises à jour automatiques la vérifient avant chaque installation (section 6).

Chaque image, depuis la version 1.1.0, a ces trois éléments (les images des versions 1.0.0 et 1.0.1 n'en ont aucun) :

| Élément | Ce que c'est | Où le trouver |
|---|---|---|
| Signature | La preuve que l'image vient du workflow `image.yml` du dépôt `Probant-Reporting/probant`, pour l'étiquette de la version. Elle est faite avec cosign, sans clé : le certificat nomme le workflow et l'étiquette. | Dans le registre, à côté de l'image |
| SBOM (nomenclature logicielle) | La liste des composants de l'image (paquets du système et bibliothèques Python), au format SPDX JSON. Elle est aussi attachée à l'image sous forme d'attestation signée. | Release de la version : `probant-<version>-sbom.spdx.json` |
| Rapport des failles | Les failles connues de ces composants le jour de la construction, établies par Grype. Un tableau en texte et un fichier JSON. | Release de la version : `probant-<version>-vulnerabilities.txt` et `.json` |

La page des releases est `https://github.com/Probant-Reporting/probant/releases`. Si un fichier n'est pas dans la
release, il est dans l'artefact `probant-image-reports` de l'exécution « Docker image » de l'étiquette (onglet
**Actions**).

Pour vérifier la signature d'une image :

1. Installez cosign, version 3 ou plus récente (https://docs.sigstore.dev/cosign/system_config/installation/).
2. Lancez cette commande. Remplacez `X.Y.Z` par la version (par exemple `1.1.0`), dans l'image et dans l'étiquette :

   ```bash
   cosign verify ghcr.io/probant-reporting/probant:X.Y.Z \
     --certificate-identity https://github.com/Probant-Reporting/probant/.github/workflows/image.yml@refs/tags/vX.Y.Z \
     --certificate-oidc-issuer https://token.actions.githubusercontent.com
   ```

   Si la signature est correcte, cosign liste les contrôles faits, puis affiche la signature avec l'empreinte de
   l'image (`sha256:…`). Sinon, cosign affiche une erreur et s'arrête. Dans ce cas, n'utilisez pas l'image et
   signalez le problème (voir `SECURITY.md`).

3. Facultatif : pour être sûr que le serveur fait tourner exactement l'image vérifiée, mettez cette empreinte dans
   `IMAGE`. Par exemple : `IMAGE=ghcr.io/probant-reporting/probant@sha256:…`.

Pour récupérer le SBOM depuis l'image et vérifier son attestation en une seule étape, lancez cette commande :

```bash
cosign verify-attestation --type spdxjson ghcr.io/probant-reporting/probant:X.Y.Z \
  --certificate-identity https://github.com/Probant-Reporting/probant/.github/workflows/image.yml@refs/tags/vX.Y.Z \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  | jq -r '.payload' | base64 -d | jq '.predicate' > probant-sbom.spdx.json
```

Pour lire le rapport des failles :

- Ouvrez `probant-<version>-vulnerabilities.txt`. Chaque ligne est une faille connue d'un composant : le nom du
  composant, la version installée, la version qui corrige la faille (vide s'il n'y a pas encore de correction),
  l'identifiant (CVE ou GHSA) et la gravité (Critical, High, Medium, Low, Negligible).
- La plupart des lignes concernent des paquets du système de l'image de base (`python:3.12-slim`). Beaucoup n'ont pas
  encore de correction, ou concernent une fonction que l'outil n'utilise pas.
- Le rapport informe seulement : une faille n'arrête pas la publication de l'image. La correction d'un composant
  arrive avec la version suivante de l'image.
- Le rapport donne l'état du jour de la construction. Pour refaire le contrôle plus tard avec les failles connues ce
  jour-là, analysez le SBOM. Par exemple, avec Grype : `grype sbom:probant-<version>-sbom.spdx.json`.
- Le fichier JSON a le même contenu, pour un outil de sécurité de votre organisation.

### Installer sans accès à Internet

Utilisez cette façon pour un serveur qui ne peut pas joindre Internet. Chaque version, depuis la 1.1.0, a
un paquet hors ligne : l'image de l'outil et les fichiers qui l'installent et le mettent à jour, en un seul fichier.
Rien n'est téléchargé pendant l'installation. Il n'y a pas de mises à jour automatiques : pour mettre à jour, prenez
le paquet de la nouvelle version (voir « Mettre à jour sans accès à Internet », section 6).

Ce tableau présente les fichiers du paquet hors ligne, sur la page de la version
(`https://github.com/Probant-Reporting/probant/releases`) :

| Fichier | Ce que c'est |
|---|---|
| `probant-X.Y.Z-offline.tar` | Le paquet : un dossier `probant` avec l'archive de l'image (`probant-image-X.Y.Z.tar.gz`), l'archive de l'image de Caddy (`caddy-image.tar.gz`, pour le HTTPS), `docker-compose.yml`, `.env.example`, `install.sh`, `update.sh`, `check.sh`, `docker/Caddyfile`, `VERSION` et `SHA256SUMS` (l'empreinte SHA-256 de chaque fichier) |
| `probant-X.Y.Z-offline.tar.sha256` | L'empreinte SHA-256 du paquet |
| `probant-X.Y.Z-offline.tar.sigstore.json` | La signature du paquet (paquet de signature cosign). Il contient tout ce dont cosign a besoin pour vérifier le paquet sans réseau. |

Sans accès à Internet, vous pouvez utiliser :

- L'outil, avec sa base SQLite (le réglage par défaut). Le paquet contient l'image de l'outil et l'image de Caddy.
  Il ne contient pas l'image de PostgreSQL (profil `postgres`) : voir « PostgreSQL sans accès à Internet » plus bas.
- Le HTTP sur le réseau interne (`http://ADRESSE-DU-SERVEUR:8000`).
- Le HTTPS avec le proxy de votre entreprise devant l'outil : le proxy porte le certificat et envoie les requêtes au
  port TCP 8000 du serveur, avec les en-têtes `X-Forwarded-Proto` et `X-Forwarded-For`. Réglez `DJANGO_HTTPS=1` et
  `DOMAIN` dans `.env` (section 4), puis lancez `docker compose up -d`.
- Le HTTPS avec Caddy et le certificat de votre entreprise : ajoutez `--domain`, `--cert` et `--key` à la commande de
  l'étape 7 (voir « Réseau d'entreprise »).

Sans accès à Internet, il n'y a pas de certificat automatique : l'installeur refuse `--offline` avec `--domain` seul.

Pour installer l'outil sans accès à Internet :

1. Sur un ordinateur qui a accès à Internet, téléchargez les trois fichiers de la version depuis la page de la version.
2. Sur cet ordinateur, vérifiez le paquet :
   - L'empreinte : `sha256sum -c probant-X.Y.Z-offline.tar.sha256`. La commande affiche `OK`.
   - La signature, avec cosign version 3 ou plus récente. Remplacez `X.Y.Z` par la version, dans les noms des fichiers
     et dans l'étiquette :

     ```bash
     cosign verify-blob probant-X.Y.Z-offline.tar \
       --bundle probant-X.Y.Z-offline.tar.sigstore.json \
       --certificate-identity https://github.com/Probant-Reporting/probant/.github/workflows/image.yml@refs/tags/vX.Y.Z \
       --certificate-oidc-issuer https://token.actions.githubusercontent.com
     ```

     Si la signature est correcte, cosign affiche `Verified OK`. Sinon, n'utilisez pas le paquet, et signalez le
     problème (voir `SECURITY.md`).
3. Facultatif : pour vérifier la signature aussi sur un ordinateur sans accès à Internet, cosign a besoin de la racine
   de confiance de Sigstore. Sur l'ordinateur qui a accès à Internet, après une première utilisation de cosign (ou
   `cosign initialize`), trouvez-la avec `find ~/.sigstore -name '*trusted_root.json'`, et copiez-la avec le paquet.
   Ajoutez ensuite `--trusted-root <ce fichier>` à la commande de l'étape 2.
4. Installez Docker Engine et son extension Compose sur le serveur, depuis le miroir de paquets de votre entreprise.
   Sans accès à Internet, l'installeur ne peut pas installer Docker.
5. Copiez `probant-X.Y.Z-offline.tar` sur le serveur, dans le dossier où vous voulez le dossier de l'outil.
6. Extrayez le paquet et allez dans son dossier :

   ```bash
   tar -xf probant-X.Y.Z-offline.tar
   cd probant
   ```

7. Lancez l'installeur avec l'archive de l'image. Ajoutez `--port 8080` pour un autre port :

   ```bash
   ./install.sh --offline probant-image-X.Y.Z.tar.gz
   ```

L'installeur effectue ces étapes, dans cet ordre :

1. Il vérifie chaque fichier du dossier avec `SHA256SUMS`. Si un fichier est abîmé ou modifié, il s'arrête et ne
   change rien.
2. Il vérifie le serveur (voir « Vérifier le serveur avant d'installer »), sans les contrôles du réseau.
3. Il crée le fichier `.env`, charge l'image dans Docker (`docker load`) et règle `IMAGE` dans `.env` sur le nom de
   cette image.
4. Il démarre l'outil sans aucun téléchargement, et attend qu'il réponde.

Après l'installation, le dossier contient encore l'archive de l'image. Vous pouvez la supprimer quand l'outil marche :
Docker garde l'image.

#### PostgreSQL sans accès à Internet

Le paquet ne contient pas l'image de PostgreSQL. Pour utiliser le profil `postgres` (section 8) sans accès à Internet,
apportez l'image vous-même :

1. Sur un ordinateur qui a accès à Internet, enregistrez l'image nommée dans `docker-compose.yml` (service `db`) :

   ```bash
   docker pull postgres:16
   docker save postgres:16 | gzip > postgres-16.tar.gz
   ```

2. Copiez `postgres-16.tar.gz` sur le serveur, puis chargez-la : `docker load -i postgres-16.tar.gz`.
3. Réglez le profil `postgres` et `DATABASE_URL` dans `.env` (section 8), puis lancez `docker compose up -d --pull never`.

### Réseau d'entreprise

Cette partie est facultative. Elle concerne un serveur sur le réseau d'une entreprise, avec un ou plusieurs de ces
éléments : un certificat que votre entreprise donne pour l'adresse HTTPS, une autorité de certification de votre
entreprise (le certificat qui signe ses certificats internes) pour les connexions sortantes, et un proxy. Si votre
réseau n'utilise rien de cela, passez cette partie.

Les fichiers de cette partie vont dans le dossier `certificates/` de l'installation, à côté de `.env` :

| Dossier | Contenu | Qui le lit |
|---|---|---|
| `certificates/https/` | `certificate.pem` et `key.pem` : le certificat HTTPS de votre entreprise et sa clé privée (clé en mode `0600`, dossier en mode `0700`) | Caddy seulement. Le conteneur de l'outil ne reçoit jamais la clé : une sauvegarde de l'outil ne la contient donc jamais. |
| `certificates/ca/` | Les autorités de certification de votre entreprise (fichiers `.pem`, `.crt` ou `.cer`, mode `0644`) | L'outil, en lecture seule |

Gardez les fichiers d'origine là où votre entreprise garde ses certificats : les sauvegardes de l'outil ne les
contiennent pas.

#### Utiliser le certificat HTTPS de votre entreprise

Caddy peut servir un certificat que votre entreprise donne, à la place du certificat automatique. Utilisez-le pour une
adresse qu'Internet ne peut pas joindre, ou quand la politique de sécurité de votre entreprise le demande. Caddy ne
contacte alors jamais Let's Encrypt, et le serveur n'a pas besoin d'être joignable depuis Internet.

Ce tableau montre les deux fichiers qu'il vous faut, au format PEM :

| Fichier | Contenu |
|---|---|
| Certificat | Le certificat du serveur pour le nom de domaine, puis les certificats intermédiaires (la chaîne complète) |
| Clé privée | La clé privée de ce certificat, sans mot de passe |

Pour installer l'outil avec ce certificat :

```bash
./install.sh --domain reporting.example.com --cert reporting.pem --key reporting.key
```

Avec l'installation en une commande, ajoutez les mêmes options après `sh -s --`. Sans accès à Internet, ajoutez
`--offline probant-image-X.Y.Z.tar.gz` : l'installeur charge l'image de Caddy depuis le paquet.

Avant tout changement, l'installeur contrôle les fichiers (avec `check.sh`, qui a besoin de la commande `openssl`). Ce
tableau montre les contrôles :

| Contrôle | S'il échoue |
|---|---|
| La clé privée correspond au certificat | À corriger : l'installeur s'arrête |
| Le certificat couvre le nom de domaine | À corriger : l'installeur s'arrête |
| Le certificat n'a pas expiré | À corriger : l'installeur s'arrête. Moins de 30 jours restants : un avertissement seulement |
| La chaîne est complète, jusqu'à une autorité du système ou de votre entreprise (`--ca-cert`) | Un avertissement seulement : certains navigateurs refusent une chaîne incomplète |

Avec le certificat de votre entreprise, un nom de domaine que ce serveur ne trouve pas dans le DNS ne donne qu'un
avertissement : ce sont les personnes qui ouvrent l'outil qui ont besoin du nom, pas Caddy.

Pour renouveler ou remplacer le certificat, lancez cette commande dans le dossier de l'installation :

```bash
./install.sh --cert nouveau-certificat.pem --key nouvelle-cle.key
```

La commande contrôle les nouveaux fichiers, les met en place et recharge le certificat dans Caddy, sans coupure et
sans téléchargement (aussi sans accès à Internet). La même commande fait passer une installation qui utilise le
certificat automatique au certificat de votre entreprise. Pour contrôler de nouveaux fichiers avant de renouveler,
sans rien changer : `sh check.sh --certificate-only --domain reporting.example.com --cert nouveau-certificat.pem --key nouvelle-cle.key`.

Pour remplacer les fichiers à la main : copiez-les dans `certificates/https/certificate.pem` et
`certificates/https/key.pem`, puis lancez `docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile --force`.
Pour revenir au certificat automatique : videz `HTTPS_CERTIFICATE=` dans `.env`, puis lancez `docker compose up -d`.

#### Faire confiance à l'autorité de certification de votre entreprise

Une connexion de l'outil à un serveur qui a un certificat d'une autorité interne échoue tant que l'outil ne fait pas
confiance à cette autorité. Par exemple : le serveur d'e-mails de votre entreprise, ou un proxy qui inspecte le trafic
HTTPS. L'erreur dit « certificate verify failed ».

Pour ajouter l'autorité, donnez son certificat (format PEM) à l'installeur. Répétez l'option pour plusieurs autorités :

```bash
./install.sh --ca-cert autorite-racine-entreprise.pem
```

Sur une installation qui tourne, la même commande ajoute l'autorité et redémarre l'outil. À chaque démarrage, l'outil
réunit les autorités de `certificates/ca/` avec celles du système dans un seul fichier, `/data/ca-bundle.pem`. Toutes
les connexions sortantes de l'outil utilisent ce fichier : le serveur d'e-mails (STARTTLS et SSL), l'assistant IA et
toute autre connexion HTTPS. Les autorités publiques restent de confiance.

L'outil n'utilise que le certificat d'une autorité. Un fichier qu'il ne peut pas lire, qui ne contient aucun
certificat, ou qui contient un certificat de serveur, est écrit dans le journal au démarrage (`docker compose logs web`)
et laissé de côté : l'outil démarre quand même. **Administration › Paramètres › Santé** montre les autorités en
service, avec leur date d'expiration, aux gestionnaires des espaces et aux administrateurs de l'espace principal. La
ligne passe à « À regarder » 30 jours avant l'expiration d'une autorité.

Pour retirer une autorité, supprimez son fichier de `certificates/ca/`, puis lancez `docker compose restart web`.

Sans Docker (hébergement géré, ou `python manage.py runserver`), réglez `EXTRA_CA_CERTS` sur le fichier, ou sur le
dossier des fichiers. Séparez-en plusieurs par `:`. Le dossier des données doit être modifiable : l'outil y écrit
`ca-bundle.pem`. Avec Python 3.13 ou plus récent, les certificats doivent avoir les identifiants de clé que demande la
RFC 5280.

Le contrôle du serveur utilise aussi l'autorité : `sh check.sh --ca-cert autorite-racine-entreprise.pem` (l'installeur
lui passe les options). Les autorités de `certificates/ca/` d'une installation sont lues sans l'option.

Docker télécharge les images lui-même, en dehors de l'outil. Derrière un proxy qui inspecte le trafic, le service
Docker doit aussi faire confiance à l'autorité : sur Debian et Ubuntu, copiez-la dans `/usr/local/share/ca-certificates/`
avec l'extension `.crt`, puis lancez `sudo update-ca-certificates` et `sudo systemctl restart docker`
(https://docs.docker.com/engine/network/ca-certs/). Une image construite sur le serveur (« Installer avec Git »)
télécharge aussi des paquets Python pendant la construction : derrière un tel proxy, utilisez l'image publiée ou le
paquet hors ligne.

#### Utiliser un proxy pour les connexions sortantes

L'outil peut passer par un proxy pour ses connexions HTTPS sortantes. Ce tableau montre quoi régler :

| Quoi | Comment |
|---|---|
| HTTPS sortant de l'outil (assistant IA, et les autres connexions HTTPS) | `HTTPS_PROXY=http://proxy.example.com:3128` dans `.env`, et `NO_PROXY` pour les adresses à joindre directement. Puis lancez `docker compose up -d`. |
| Serveur d'e-mails | La connexion SMTP n'utilise pas le proxy : ouvrez le port SMTP du serveur vers le serveur d'e-mails. |
| Contrôle du serveur | `sudo HTTPS_PROXY=http://proxy.example.com:3128 sh check.sh …` (voir « Vérifier le serveur avant d'installer ») |
| Téléchargements de Docker | Le proxy du service Docker : https://docs.docker.com/engine/daemon/proxy/ |
| Proxy qui inspecte le trafic HTTPS | Donnez son autorité avec `--ca-cert` (voir plus haut) |

## 3. Mettre en place l'outil au premier lancement

À la première ouverture, l'outil n'a encore aucun compte. L'assistant **Mise en place** s'ouvre à la place de la page
de connexion. Il compte 8 étapes.

> **Important : créez le compte administrateur tout de suite.** Tant que l'étape 1 n'est pas faite, la première
> personne qui ouvre l'adresse de l'outil crée le compte administrateur. Après l'étape 1, l'assistant ne s'ouvre plus
> qu'à ce compte.

L'outil ne demande aucun code d'installation. Tant que rien n'est créé, l'outil ne contient aucune donnée sensible.
Ce qui le protège, c'est l'ordre des étapes : vous créez le compte administrateur juste après l'installation, avant de
communiquer l'adresse.

Pour mettre en place l'outil :

1. Juste après l'installation (ou le déploiement), ouvrez l'adresse de l'outil. L'assistant **Mise en place**
   s'ouvre. Pour voir plutôt la démo, chargez-la maintenant, avant l'étape 1 : voir « Démarrer vide, ou avec la
   démo ».
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

Le compte de l'étape 1 est aussi le premier **gestionnaire des espaces**. Seuls les gestionnaires des espaces changent
les réglages de toute l'installation : le serveur d'e-mails, les alertes par e-mail, les mises à jour automatiques, la
copie externe des sauvegardes et la connexion d'entreprise. Les autres administrateurs ne peuvent pas les changer. Voir
[docs/spaces.md](../spaces.md) (en anglais).

![Premier lancement : l'assistant s'ouvre sur le compte administrateur](../screenshots/fr/setup-admin-account.png)

![Étape 5 : choisir un référentiel dans la bibliothèque, le composer ou importer le sien](../screenshots/fr/setup-frameworks.png)

![Étape 8 : la première campagne, période en cours proposée](../screenshots/fr/setup-campaign.png)

Après la mise en place, chaque personne se connecte avec son adresse e-mail. Le **Tableau de bord** montre
l'avancement de la collecte :

![Page de connexion](../screenshots/fr/login.png)

![Tableau de bord](../screenshots/fr/dashboard.png)

La saisie fonctionne aussi sur téléphone :

![Saisie sur téléphone](../screenshots/fr/entry-phone.png)

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

### Faire relire les textes traduits

L'interface existe en français, anglais, espagnol, allemand, italien, néerlandais et portugais. Une IA a traduit les
textes qui ne sont ni en français ni en anglais. Avant d'ouvrir une langue aux utilisateurs, demandez à une personne de
l'entreprise qui la parle de relire ses textes. Les textes sont dans les fichiers `libelles/*.<code>.json` du dépôt
public (par exemple `libelles/*.es.json`). La personne n'a besoin d'aucune compétence technique : elle relit seulement
les textes.

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
| `DJANGO_SECRET_KEY` | Générée | La clé qui chiffre les sessions, signe les sauvegardes et chiffre les secrets enregistrés dans l'outil (mot de passe du serveur d'e-mails, secrets de la copie externe, secret du client de la connexion d'entreprise). Si elle est vide, l'outil la crée au premier démarrage dans `/data/.secret_key`. Si vous la changez, l'outil n'accepte plus les sauvegardes faites avant dans **Administration › Paramètres › Hébergement** : restaurez-les en ligne de commande avec `--unsigned`. Les secrets enregistrés dans l'outil sont alors à saisir de nouveau. |
| `DJANGO_HSTS_SECONDS`, `DJANGO_HSTS_SUBDOMAINS`, `DJANGO_HSTS_PRELOAD` | 1 an, `1`, `0` | Les réglages HSTS. Ils s'appliquent quand `DJANGO_HTTPS=1`. |
| `CONTENT_SECURITY_POLICY_MODE` | `enforce` | La politique de sécurité des contenus des pages. `enforce` bloque ce que la politique ne permet pas. `report-only` ne bloque rien : le navigateur signale seulement, dans sa console, ce qu'il bloquerait. Voir « Sécurité, déjà active » plus bas. |
| `SMTP_…` | Vide | E-mails. Quand `SMTP_HOST` est rempli, ces réglages passent avant les réglages des e-mails saisis dans l'outil. Voir la section 7. |
| `AI_SOCKET` | `on` | `off` coupe l'assistant IA facultatif pour toute l'installation : aucun bouton IA et rien n'est envoyé, quels que soient les réglages des administrateurs. Voir « Assistant IA » plus bas. |
| `DEFAULT_LANGUAGE` | `en` | La langue d'une nouvelle installation (interface et contenus) : l'une des sept langues de l'interface (`en`, `fr`, `es`, `de`, `it`, `nl`, `pt`). L'outil ne la lit qu'à la création de la base. Ensuite, changez-la dans **Administration › Paramètres › Langues**. Pour une installation en français, mettez `fr` avant le premier démarrage. |
| `GUIDED_TOUR` | `on` | `off` retire la courte visite guidée que les personnes voient à leur première connexion. La visite ne change que l'affichage. |
| `TIME_ZONE` | `Europe/Brussels` | Le fuseau horaire de l'installation, sous la forme d'un nom de la liste IANA, par exemple `Europe/Paris` ou `America/New_York`. L'heure des relances automatiques, de la sauvegarde automatique et du contrôle de chaque nuit, « aujourd'hui », et les dates des exports et du journal suivent ce fuseau. **Administration › Paramètres › Hébergement** l'affiche à côté de l'heure du serveur. Si le nom est inconnu, l'outil ne démarre pas et le journal montre l'erreur. |
| `MAX_EVIDENCE_SIZE_MB`, `MAX_IMPORT_SIZE_MB` | `5`, `10` | La taille maximale, en Mo, d'une preuve et d'un fichier d'import. |
| `MAX_BACKUP_UPLOAD_MB` | `2048` | La taille maximale, en Mo, d'une sauvegarde déposée dans l'outil par un administrateur (**Hébergement** › **Restaurer**). L'outil refuse toute autre requête plus grosse que la plus grande des tailles `MAX_EVIDENCE_SIZE_MB` et `MAX_IMPORT_SIZE_MB` (plus 1 Mo), avant de la recevoir. Avec le proxy HTTPS, `CADDY_MAX_SIZE` (50 Mo par défaut) s'applique aussi : augmentez-le pour déposer une sauvegarde plus grosse. |
| `MAX_XLSX_UNCOMPRESSED_MB` | 20 × `MAX_IMPORT_SIZE_MB` | La taille maximale, en Mo, d'un fichier Excel une fois décompressé. L'outil refuse un fichier plus gros avant de l'ouvrir. Un texte de cellule de plus de 32 767 caractères (la limite d'Excel) est aussi refusé. Les mêmes limites s'appliquent aux commandes d'import lancées sur le serveur (`import_kpi`, `import_organisations`, `import_valeurs`) : pour importer un fichier plus gros par une commande, augmentez `MAX_XLSX_UNCOMPRESSED_MB` le temps de cette commande. |
| `BACKGROUND_IMPORT_ROWS` | `5000` | Un import de valeurs (**Import / Export › Importer des valeurs**) de plus de lignes que ce nombre se fait en arrière-plan. La personne voit une barre d'avancement, et peut quitter la page et revenir. Le processus `run_imports --schedule` fait ces imports. L'image le lance d'elle-même : vous n'installez rien. `0` veut dire jamais : tout import se fait dans la page, qui ne peut durer que 120 s. |
| `DISK_ALERT_MB` | `100` | Quand la place libre sur le disque des données passe sous cette valeur, en Mo, `/sante/` répond `503` (« disk almost full »). |
| `BACKUP_AUTO`, `BACKUP_TIME`, `BACKUPS_KEEP` | `1`, `02:30`, `14` | Valeurs de départ seulement. Ensuite, ces valeurs se règlent dans l'outil, dans **Administration › Paramètres › Hébergement** : sauvegarde automatique activée ou non, fréquence (6 h, 12 h, jour, semaine), heure et nombre de sauvegardes gardées. |
| `DATA_CHECK_TIME` | `03:30` | L'heure du contrôle et du ménage de chaque nuit. Le contrôle lit la base et ne modifie rien. Le ménage efface les sessions terminées et les éléments supprimés depuis plus longtemps que le délai de la corbeille. Voir la section 9. |
| `GUNICORN_WORKERS`, `GUNICORN_THREADS` | 1 processus par processeur (de 2 à 4), `4` | Capacité du serveur. Un processus utilise 1 processeur à la fois et environ 170 Mo de mémoire. La valeur par défaut convient à un serveur de 2 à 4 processeurs. Voir « Capacité » à la section 8. |
| `GUNICORN_TIMEOUT`, `GUNICORN_KEEPALIVE` | `120`, `75` | La durée maximale d'une requête, en secondes, et la durée pendant laquelle une connexion inutilisée reste ouverte. Gardez `GUNICORN_KEEPALIVE` au-dessus du délai du proxy placé devant l'outil. Le Caddy fourni ferme les connexions inutilisées après 60 s. Si la valeur est plus basse, un enregistrement peut de temps en temps échouer avec l'erreur 502. |
| `DJANGO_LOG_LEVEL` | `INFO` | Le niveau de détail du journal (`INFO`, `WARNING`, `ERROR`). |
| `IMAGE` | Vide (image construite sur le serveur) | L'image publiée à utiliser, par exemple `ghcr.io/probant-reporting/probant:latest`. |
| `HTTPS_CERTIFICATE` | Vide (certificat automatique) | `files` : Caddy sert le certificat de votre entreprise, depuis `certificates/https/`, et ne contacte jamais Let's Encrypt. `./install.sh --cert --key` le règle. Voir « Réseau d'entreprise » en section 2. |
| `PUBLIC_URL` | Vide | L'adresse de l'outil, par exemple `https://reporting.example.com`, dans les e-mails (relances, alertes par e-mail) et dans l'adresse de retour (redirect URI) de la connexion d'entreprise. Vide : les e-mails prennent la première valeur de `DOMAIN`, et la connexion d'entreprise l'adresse de la page. |
| `COMPANY_SIGN_IN`, `COMPANY_SIGN_IN_TIMEOUT` | `on`, `5` | `off` coupe la connexion d'entreprise pour toute l'installation, quel que soit le réglage des gestionnaires des espaces : le bouton disparaît et chacun peut utiliser son mot de passe. Le délai est l'attente la plus longue, en secondes, de chaque appel au fournisseur d'identité. Voir « Connexion avec le compte d'entreprise » plus bas. |
| `EXTRA_CA_CERTS` | `/etc/probant/ca` dans l'image | Sans Docker seulement : le fichier ou le dossier des autorités de certification de votre entreprise, pour les connexions sortantes. Séparez-en plusieurs par `:`. Avec Docker, mettez les fichiers dans `certificates/ca/` (`./install.sh --ca-cert`). Voir « Réseau d'entreprise » en section 2. |

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

Une personne peut brancher son propre assistant IA sur l'outil, par le Model Context Protocol (MCP). L'assistant lit
et modifie alors les données avec les droits de cette personne. Le serveur MCP fait partie de l'outil, à l'adresse
`/mcp/` de chaque espace (`/espace/<code>/mcp/` pour un autre espace). Il tourne dans le même conteneur, sur le même
port, derrière le même HTTPS : aucun service, aucun port, aucune variable, rien à installer. Il reste éteint tant
qu'un administrateur ne l'a pas allumé dans **Administration › Paramètres › Assistants**. Seule condition : le proxy
transmet l'en-tête `Authorization` à l'outil (Caddy, profil `https`, et Clever Cloud le font sans réglage). Les jetons
des assistants ne sont jamais dans les sauvegardes. Le journal de l'outil montre les jetons refusés
(`serveur_mcp: MCP: token refused`). Détails : [`assistants_mcp.md`](assistants_mcp.md), section 7.

### Assistant IA (facultatif)

C'est une autre fonction : ici, c'est l'outil lui-même qui appelle un fournisseur d'IA (Claude, d'Anthropic). L'outil
lui demande des propositions : expliquer une alerte de cohérence, relier les KPI d'un ancien fichier, traduire des
libellés. Il est **éteint** dans chaque espace. Un administrateur de l'espace l'allume dans **Administration ›
Paramètres › Assistant IA**, avec la clé d'API du compte de votre organisation chez le fournisseur. La page dit
exactement ce que chaque usage envoie. Description complète : `docs/fr/prise_ia.md`.

Ce que fait l'IT :

| Élément | Valeur |
|---|---|
| Réseau | Permettre les connexions HTTPS sortantes (TCP 443) du serveur vers `api.anthropic.com`. Rien n'entre. |
| Proxy | Si le serveur sort par un proxy, mettre `HTTPS_PROXY=http://proxy:port` dans `.env`. |
| Clé | Rien à faire : l'administrateur la saisit dans l'outil. L'outil la garde dans `ai-keys/` du dossier des données, lisible par l'outil seul, jamais en base ni dans une sauvegarde. Après une restauration sur un autre serveur, l'administrateur la saisit de nouveau. |
| L'interdire | `AI_SOCKET=off` dans `.env`, puis `docker compose up -d`. |

Tant que l'assistant est éteint dans un espace, l'outil n'ouvre aucune connexion vers le fournisseur.

### Connexion avec le compte d'entreprise

Chacun peut se connecter avec son compte d'entreprise (connexion unique, OpenID Connect). Elle est éteinte par
défaut. Un gestionnaire des espaces la règle dans **Administration › Paramètres › Connexion d'entreprise**. Ce que
fait l'IT :

| Élément | Valeur |
|---|---|
| Réseau | Autorisez les connexions HTTPS sortantes (TCP 443) du serveur vers le fournisseur d'identité. Rien n'entre. |
| Adresse | Réglez `PUBLIC_URL` dans `.env` : l'outil en tire l'adresse de retour (redirect URI). |
| Secours | Si aucun gestionnaire des espaces ne peut se connecter, réglez `COMPANY_SIGN_IN=off` dans `.env`, puis lancez `docker compose up -d`. Chacun peut de nouveau utiliser son mot de passe. |

Détails : [`docs/fr/connexion_entreprise.md`](connexion_entreprise.md).

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
| Sauvegarder automatiquement | Rien. Par défaut, l'outil fait une sauvegarde chaque jour à 02:30 et garde 14 archives. Un administrateur règle la fréquence dans **Administration › Paramètres › Hébergement**. |
| Sauvegarder maintenant | Lancez `docker compose exec web python manage.py backup`. Un administrateur peut aussi cliquer sur **Créer et télécharger une sauvegarde** dans **Administration › Paramètres › Hébergement**. |
| Lister les sauvegardes | Lancez `docker compose exec web python manage.py backup --list`. |
| Copier les sauvegardes hors du serveur | **À faire par l'IT** : par défaut, les sauvegardes restent sur le même serveur que l'outil. Copiez-les dans l'outil, ou par vos propres moyens : voir [Copier les sauvegardes hors du serveur](#copier-les-sauvegardes-hors-du-serveur). |

**Sans Docker**, planifiez la même sauvegarde avec cron : `30 2 * * * cd /opt/reporting && python manage.py backup`.

![Administration › Paramètres › Hébergement : version, sauvegardes, e-mail de test](../screenshots/fr/hosting.png)

### Copier les sauvegardes hors du serveur

Les sauvegardes restent dans le volume `/data`, sur le même serveur que l'outil. Si le serveur est perdu, elles le
sont aussi. Copiez-les hors du serveur d'une de ces deux façons. Les deux façons peuvent fonctionner ensemble.

#### Dans l'outil

Cette copie est éteinte tant qu'un gestionnaire des espaces ne l'a pas réglée. L'outil peut alors copier lui-même
chaque sauvegarde vers un stockage que l'IT fournit. Un gestionnaire des espaces le
règle dans **Administration › Paramètres › Hébergement**, encart **Copie hors du serveur**, avec **Régler une copie hors du serveur** :

- **Stockage objet compatible S3** : un compartiment chez un hébergeur, ou MinIO sur votre réseau. Indiquez l'adresse du
  service (`https://…` ; `http://` n'est accepté que pour une adresse du réseau interne), la région, le compartiment,
  un dossier facultatif dans le compartiment, l'identifiant de la clé d'accès et la clé secrète. Le style d'adresse est
  automatique ; choisissez « chemin » ou « hôte virtuel » seulement si l'hébergeur le demande.
- **Serveur SFTP** : un serveur ou un NAS. Indiquez le serveur, le port, le nom du compte, un mot de passe ou une clé
  privée (format OpenSSH ou PEM, sans phrase secrète, créée pour cette copie seulement), et le dossier.

![Administration › Paramètres › Hébergement › Copie hors du serveur : état de la copie et destination S3](../screenshots/fr/hosting-external-copy.png)

Cliquez ensuite sur **Essayer la destination**. L'outil dépose un petit fichier d'essai, le relit, puis le supprime.
Avec SFTP, le premier essai montre l'empreinte SHA-256 de la clé du serveur. Comparez-la à l'empreinte que donne le
serveur (sur le serveur : `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`), puis cliquez sur **Confirmer cette
clé**. Ensuite, l'outil refuse toute autre clé, avant d'envoyer le mot de passe ou la clé. Si le serveur change de
clé, la copie s'arrête et part en alerte, jusqu'à ce qu'un gestionnaire des espaces confirme la nouvelle clé.

Ce que fait ensuite l'outil :

- Il copie chaque nouvelle archive de chaque espace **et** chaque archive du registre commun des comptes
  (`backups/shared/`), dans la minute qui suit la sauvegarde. C'est la tâche de fond des sauvegardes qui le fait
  (`backup --schedule`), jamais une page de l'outil. Pour copier tout de suite :
  `docker compose exec web python manage.py backup --copy`.
- À la destination, il garde le rangement du dossier `backups`, dans un dossier au nom de l'identifiant de
  l'installation : `<dossier ou préfixe>/<identifiant>/backup-….zip` (espace principal), `…/spaces/<code>/backup-….zip`
  (autres espaces), `…/shared/registry-….zip` (registre).
- Si une copie échoue (réseau, droits, stockage plein…), il réessaie plus tard (après 5 minutes, puis 15 minutes,
  jusqu'à 6 heures) et copie tout ce qui attend. **Paramètres › Santé** et `/sante/` (`external_copy`) montrent la
  dernière copie et les archives qui attendent ; une alerte par e-mail part si les alertes sont allumées (section 9).
- Par défaut, il **ne supprime rien** à la destination. Si un gestionnaire des espaces règle **Copies gardées par espace**,
  l'outil garde ce nombre de copies les plus récentes de chaque espace et du registre, et ne supprime que les archives
  plus anciennes qu'il a faites lui-même (dossier et nom qu'il reconnaît). Il ne supprime jamais un autre fichier, ni la
  dernière archive faite. Pour protéger les copies de toute suppression, donnez au compte le droit d'écrire mais pas
  celui de supprimer, et gardez `0`.
- S3 : le service vérifie l'empreinte SHA-256 de chaque morceau que l'outil envoie ; après l'envoi, l'outil relit la
  taille et l'empreinte. Une grosse archive part en morceaux de 16 Mo. SFTP : l'outil écrit un fichier caché `.part`,
  le renomme, puis vérifie la taille.

> **Attention :** Les copies contiennent toutes les données de l'outil, les empreintes des mots de passe (sauvegardes
> du registre) et les secrets enregistrés dans l'outil, chiffrés avec la clé secrète de l'installation. Choisissez une
> destination privée que seule l'IT peut ouvrir. L'outil ne chiffre pas les archives.

L'outil enregistre la clé secrète S3, et le mot de passe ou la clé privée SFTP, chiffrés avec la clé secrète de
l'installation. Il ne les réaffiche jamais. Après une restauration sur un autre serveur, un gestionnaire des espaces
les saisit de nouveau. Pour les garder, laissez les champs vides quand vous enregistrez. Si vous changez la destination (S3 :
adresse, région, compartiment ou identifiant de la clé d'accès ; SFTP : serveur, port ou compte), l'outil redemande le
secret, pour qu'il ne parte jamais vers une autre destination. En SFTP, un autre serveur ou un autre port oublie aussi
la clé du serveur confirmée.

La connexion utilise les autorités de certification du système et celles que l'IT ajoute (`certificates/ca/`, voir
[Faire confiance à l'autorité de certification de votre entreprise](#faire-confiance-à-lautorité-de-certification-de-votre-entreprise)).
Avec `HTTPS_PROXY`, un service S3 public est joint par le proxy ; une adresse du réseau interne est jointe directement.
SFTP demande une connexion directe. L'outil ne se connecte jamais au serveur lui-même, à une adresse locale au lien
(métadonnées de l'hébergeur) ni à une adresse réservée.

La version tout-en-un (Windows ou Mac) n'a pas cette fonction : copiez vous-même le dossier des sauvegardes.

#### Par vos propres moyens

Pour copier le dossier `/data/backups` avec votre outil de sauvegarde habituel, suivez ces étapes :

1. Copiez les archives hors du conteneur : `docker compose cp web:/data/backups/. ../probant-backups/`. Cette
   commande copie les archives, sous-dossiers compris, dans le dossier `probant-backups` à côté du dossier de l'outil.
   Ne les copiez pas dans le dossier de l'outil : la mise à jour construit l'image à partir de ce dossier.
2. Copiez `probant-backups` hors du serveur avec votre outil de sauvegarde habituel (rsync, Veeam…), de façon
   planifiée.

Les fichiers copiés gardent leurs droits : seul le compte qui a lancé `docker compose cp` peut les lire (fichiers
`0600`, dossiers `0700`). Si votre outil de sauvegarde tourne sous un autre compte, donnez à ce compte l'accès à
`probant-backups`, par exemple avec `chown -R`. Ne changez pas les droits dans le volume.

### Reconstruire un serveur à partir de la copie externe

Si le serveur est perdu, l'IT reconstruit l'installation sur un nouveau serveur à partir de la seule copie :

1. Installez l'outil sur le nouveau serveur (section 2), dans la même version ou une version plus récente. Ne créez
   pas de compte.
2. Récupérez à la destination le dossier au nom de l'identifiant de l'installation (outil S3 ou SFTP de votre choix),
   et copiez son contenu, sous-dossiers compris, dans le dossier des sauvegardes du nouveau serveur :
   `docker compose cp ./<identifiant>/. web:/data/backups/`.
3. Restaurez la sauvegarde la plus récente du registre commun, puis la plus récente de l'espace principal, puis la plus
   récente de chaque autre espace :

   ```bash
   docker compose exec web python manage.py restore --shared registry-AAAAMMJJ-HHMMSS-auto.zip --yes
   docker compose exec web python manage.py restore --unsigned backup-AAAAMMJJ-HHMMSS-auto.zip --yes
   docker compose exec -e SPACE=<code> web python manage.py restore --unsigned backup-AAAAMMJJ-HHMMSS-auto.zip --yes
   docker compose restart web
   ```

   Les archives ont été signées par l'ancien serveur : `--unsigned` est nécessaire, sauf si vous remettez l'ancienne
   clé secrète (`/data/.secret_key` ou `DJANGO_SECRET_KEY`).
4. Chacun se connecte avec son mot de passe habituel. Un gestionnaire des espaces saisit de nouveau les secrets : le
   mot de passe du serveur d'e-mails et le secret de la copie externe. Seule la clé secrète de l'ancien serveur les lit.
   Si vous avez gardé cette clé en lieu sûr et l'avez remise avant l'étape 3, ils fonctionnent tout de suite.

Si vous n'avez que la sauvegarde d'un espace, sans celle du registre commun, un gestionnaire des espaces peut aussi la
restaurer depuis l'outil, sur le nouveau serveur : voyez
[Restaurer une sauvegarde d'une autre installation](#restaurer-une-sauvegarde-dune-autre-installation). Les mots de
passe ne passent pas dans ce cas : seule la personne qui restaure garde le sien.

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
à la commande `restore`. Sans cette option, la commande refuse l'archive et ne change rien. Un gestionnaire des espaces
peut aussi la restaurer depuis l'outil : voyez
[Restaurer une sauvegarde d'une autre installation](#restaurer-une-sauvegarde-dune-autre-installation).

Toute restauration d'une base SQLite, depuis l'outil ou en ligne de commande, avec ou sans `--unsigned`, refuse une base
avec des déclencheurs, des vues ou des colonnes calculées, ou d'une autre structure que celle que l'outil attend
(colonnes, contraintes, index et clés étrangères, tels que SQLite les lit). Les sauvegardes faites par l'outil n'en ont
jamais. Si une restauration échoue après le remplacement de la base, l'outil revient seul à l'archive
« before-restore ». Sans cette archive (`--no-backup-before`, ou base illisible), il ne le peut pas : la restauration
reste notée comme interrompue, `/sante/` le signale, et l'IT restaure une archive en ligne de commande.

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

### Restaurer une sauvegarde d'une autre installation

Un gestionnaire des espaces peut restaurer depuis l'outil une sauvegarde que cette installation n'a pas faite : après un
changement de serveur, après la perte d'un serveur, ou avec une sauvegarde de la version tout-en-un. La ligne de
commande ne change pas.

L'outil ne peut pas vérifier un tel fichier, car la clé secrète de l'autre installation ne quitte jamais son serveur.
L'outil ne fait donc pas confiance à son contenu, et ces règles s'appliquent :

- Une sauvegarde ne compte comme faite par cette installation que si sa signature est valide et qu'elle nomme cette
  installation et cet espace. La sauvegarde d'une autre installation qui a la même clé secrète (serveur reconstruit
  avec le même `DJANGO_SECRET_KEY`, `.env` recopié) a une signature valide, mais vient d'une autre installation : ces
  règles s'appliquent à elle aussi. La sauvegarde d'un autre espace de cette installation reste pour l'IT
  (`restore --other-space`).

- Seul un gestionnaire des espaces peut le faire. Pour les autres administrateurs et les autres rôles, la page refuse
  le fichier, comme avant. Une sauvegarde faite par cette installation garde les contrôles habituels, pour tout le monde.
- **Installation vide.** L'IT installe l'outil. Un administrateur crée son compte à l'étape 1 de l'assistant de mise en
  place. À partir de l'étape 2, l'assistant propose **Partir d'une sauvegarde** tant que l'installation est vide :
  espace principal seul, un seul compte, aucune organisation, aucun KPI, aucune campagne, aucune valeur, et l'assistant
  n'est pas terminé. Un visiteur non connecté ne le voit jamais.
- **Installation en service.** Dans **Administration › Paramètres › Hébergement**, ouvrez **Restaurer depuis un fichier
  .zip téléchargé auparavant**, choisissez le fichier, puis cliquez sur **Vérifier le fichier**. L'outil range le
  fichier à part : il n'est pas dans la liste des sauvegardes, et la copie externe ne le copie pas. L'outil l'efface
  après la restauration, ou au bout d'un jour.
- La sauvegarde va dans l'espace courant, comme avec `restore --other-space`. Les autres espaces et le registre commun
  des comptes ne changent pas.

La page de confirmation affiche le nom de l'installation, la date et la version que donne le fichier. Elle dit que
l'outil ne peut pas vérifier le fichier, ce que la sauvegarde remplace, ce que deviennent les comptes, et les
administrateurs de la sauvegarde. Cochez les deux cases, saisissez `RESTAURER`, puis cliquez sur **Restaurer cette
sauvegarde**. L'outil sauvegarde d'abord l'état actuel de l'espace (archive « before-restore »). Ensuite, il vous
déconnecte : reconnectez-vous avec votre propre mot de passe.

Ce que deviennent les comptes :

- Vous gardez votre compte, votre mot de passe et votre rôle de gestionnaire des espaces. Après la restauration, votre
  compte est administrateur actif de l'espace : l'outil l'ajoute, ou lui rend ce rôle, et l'écrit dans l'historique.
- Les autres comptes de la sauvegarde n'ont pas de mot de passe. Les sauvegardes ne contiennent jamais de mot de passe,
  et l'outil ne lit aucun mot de passe dans un tel fichier. Donnez-leur un mot de passe provisoire dans
  **Administration › Comptes**.
- Un compte qui a le même numéro et le même e-mail qu'un compte d'un autre espace de cette installation est la même
  personne. Il garde son mot de passe et son rôle dans les autres espaces.
- Les comptes qui n'existaient que dans cet espace, sauf le vôtre, quittent le registre commun : les comptes de la
  sauvegarde les remplacent. Leurs sessions et leurs liens avec un compte d'entreprise sont supprimés. Un gestionnaire
  des espaces parmi eux perd ce rôle.
- Si un compte de la sauvegarde a le numéro, l'e-mail ou l'identifiant d'une autre personne qui a un compte dans un
  autre espace, l'outil refuse la sauvegarde et ne change rien. L'IT peut la restaurer en ligne de commande.

Ce qui change aussi :

- Les jetons des assistants (MCP) de l'espace ne fonctionnent plus. Chaque personne en crée un nouveau.
- Les relances automatiques, l'assistant IA et les assistants (MCP) de l'espace sont éteints après la restauration, et
  les imports et exports en arrière-plan qui attendaient sont arrêtés. Rallumez-les dans la page **Relances** et dans
  **Paramètres** si besoin.
- Les droits de chaque compte viennent de son seul rôle : un administrateur de la sauvegarde a le mode expert, aucun
  autre compte ne l'a. Les groupes et permissions écrits dans le fichier ne sont pas repris.
- Les réglages de toute l'installation restent tels quels : serveur d'e-mails, copie externe, alertes par e-mail,
  connexion d'entreprise et clé de l'IA. La sauvegarde d'un espace n'en contient aucun, ni aucun de leurs secrets.

L'outil refuse aussi, avant de changer quoi que ce soit : une sauvegarde faite par une version plus récente, une
sauvegarde PostgreSQL faite avec d'autres migrations de la base, une sauvegarde SQLite sur PostgreSQL, un fichier trop
gros pour la place libre du disque, un fichier modifié après la page de confirmation, un fichier JSON avec des données
qu'une sauvegarde de l'outil ne contient jamais, et une base SQLite avec des déclencheurs, des vues ou des colonnes
calculées, ou d'une autre structure que celle que l'outil attend. Dans une base SQLite, une table en plus (laissée par
une version antérieure) est admise : l'outil ne la lit pas. Une sauvegarde d'une version antérieure est contrôlée juste
après sa mise à jour, avant que le registre commun des comptes change. Si quoi que ce soit échoue après le remplacement
de la base, l'outil revient seul à l'état d'avant la restauration, et la page le dit ; les jetons des assistants (MCP)
de l'espace sont alors perdus.

Avec plusieurs espaces, restaurez la sauvegarde de chaque espace dans son propre espace, l'espace principal d'abord. Les
sauvegardes des espaces d'une même installation donnent le même numéro à une personne qui travaille dans plusieurs
espaces : l'outil reconnaît donc cette personne. L'historique des restaurations (page **Hébergement** et
`restores.jsonl`) note « autre installation » et son nom. Pour faire passer aussi les mots de passe, l'IT suit
[Reconstruire un serveur à partir de la copie externe](#reconstruire-un-serveur-à-partir-de-la-copie-externe).

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

Pour installer une version donnée au lieu de la dernière, après une installation en une commande, lancez
`./update.sh --version X.Y.Z`. Le script refuse une version plus ancienne que la version installée : pour revenir en
arrière, voir « Revenir à la version précédente ».

Vous pouvez mettre à jour depuis n'importe quelle version publiée, sans installer les versions intermédiaires. Un test automatique l'essaie depuis chaque version publiée.

Le script effectue ces étapes, dans cet ordre :

1. Il fait une sauvegarde nommée « before-update » de chaque espace, avec la version installée. Si la sauvegarde d'un
   espace échoue, la mise à jour s'arrête et ne change rien.
2. Il récupère la nouvelle version :
   - Après une installation en une commande (un dossier sans Git, avec `IMAGE` réglé sur une version de
     `ghcr.io/probant-reporting/probant`) : il télécharge les fichiers de la nouvelle version et les contrôle, comme
     l'installation (voir « Installer en une commande »). Il règle ensuite `IMAGE` dans `.env` sur l'image de cette
     version et la télécharge. Il garde les autres réglages de `.env` et les données. Si un téléchargement échoue, si
     la liste des empreintes manque, si sa signature est refusée, ou si un seul fichier ne correspond pas, la mise à
     jour s'arrête et ne change rien (code de sortie 3 pour le contrôle des fichiers).
   - Après une installation avec Git : avec `git pull`, puis une nouvelle construction de l'image
   - Ou, si `IMAGE` est renseigné dans `.env` avec une autre image, avec `docker compose pull`
3. Il redémarre l'outil. L'outil applique les changements de structure de la base automatiquement au démarrage. Si
   la base doit changer, l'outil fait d'abord une sauvegarde automatique.
4. Il attend que l'outil réponde.

À chaque démarrage, le journal (`docker compose logs web`) affiche un court résumé en anglais. Par exemple :

```text
Probant, version 1.1.0 (3f2a9c1d7e4b)
Database: PostgreSQL (db/probant), 0 migration(s) applied; installation "Probant", 23 account(s)
Data: /data; backups: /data/backups (14 archive(s))
Address(es): reporting.example.com; HTTPS: yes
E-mails: SMTP smtp.example.com:587
```

Quand la base doit changer, le journal affiche cette ligne et le chemin de l'archive avant le résumé :
`Updating space "principal" (3 migration(s)): automatic backup before.` (mise à jour de l'espace principal :
sauvegarde automatique avant).

Le numéro de version est affiché en bas de chaque page et dans **Administration › Paramètres › Hébergement**.

Une seule mise à jour tourne à la fois : si la mise à jour automatique tourne (voir « Mises à jour automatiques »),
`./update.sh` s'arrête et ne change rien.

### Mises à jour automatiques

Après une installation en une commande, les mises à jour automatiques sont allumées. Une minuterie du serveur (appelée
**Tâche du serveur** dans l'outil) installe chaque nouvelle version la nuit, et revient à la version précédente si la
nouvelle ne fonctionne pas. Les autres installations ne les ont pas : voir le tableau plus bas. Le script
`auto-update.sh` du dossier de l'outil fait tout le travail, sur le serveur. L'outil lui-même ne se connecte jamais à Internet, ne compare jamais deux versions et n'a
aucun accès à Docker : aucun socket Docker n'est donné à son conteneur, et aucun autre outil (comme Watchtower) n'est
utilisé.

Le choix se fait dans **Administration › Paramètres › Hébergement**, « Mises à jour automatiques ». Seuls les
gestionnaires des espaces peuvent le changer :

| Choix | Effet |
|---|---|
| L'installer automatiquement | Le serveur installe chaque nouvelle version la nuit. |
| Prévenir seulement | Le serveur vérifie chaque nuit. L'outil montre la nouvelle version, aussi sur la page **Paramètres › Santé** et dans les alertes par e-mail si elles sont allumées. L'IT l'installe avec `./update.sh`. |
| Éteint | Le serveur ne vérifie rien. |
| Attendre après la publication | 0, 1, 3, 7 ou 14 jours (3 par défaut). Le serveur n'installe une version que lorsqu'elle a été publiée depuis ce nombre de jours. Entre-temps, une version qui a un problème peut être corrigée. Avec « Prévenir seulement », l'alerte vient tout de suite. |

![Administration › Paramètres › Hébergement, Mises à jour automatiques : tâche du serveur, dernière vérification et choix](../screenshots/fr/hosting-auto-updates.png)

Ce tableau montre le réglage au départ :

| Installation | Minuterie du serveur | Choix dans l'outil |
|---|---|---|
| Installation neuve en une commande (`get.sh`) | Posée | L'installer automatiquement, attendre 3 jours |
| Installation existante, mise à jour vers une version qui a les mises à jour automatiques | Pas posée : lancer `./install.sh --auto-update on` | Éteint |
| Installation avec Git, sans accès à Internet (`--offline`), ou avec une autre image | Pas disponible | — |
| Hébergement géré, version tout-en-un | Pas disponible : l'écran le dit | — |

#### Ce que fait un passage

1. Il s'arrête tout de suite si une autre mise à jour tourne (le verrou `.update.lock` du dossier, partagé avec
   `./update.sh`), si l'installation n'utilise pas une version publiée, si l'outil est arrêté, ou si le choix est
   « Éteint ».
2. Il trouve la dernière version publiée, comme `./update.sh`, et télécharge son image. Si l'empreinte (digest) de
   cette image est celle de l'image qui tourne, il n'y a rien à faire.
3. Il vérifie la signature de la nouvelle image (voir « Signature de la nouvelle image »). Si la signature manque, si
   elle n'est pas correcte, ou si la vérification est impossible, rien n'est installé.
4. Il s'arrête là dans ces cas :
   - Le choix est « Prévenir seulement ».
   - L'attente après la publication n'est pas finie.
   - La mise à jour automatique de cette image a déjà échoué.
   - La version change le registre commun des comptes. Ce changement ne se défait pas automatiquement : l'IT installe
     cette version avec `./update.sh`.
5. Il ne met pas à jour pendant une restauration, une sauvegarde, un gros import ou un gros export de l'outil. Il
   réessaie la nuit suivante.
6. Il télécharge la liste des empreintes SHA-256 des fichiers de cette version, depuis sa release, et vérifie la
   signature de cette liste (voir « Signature de la nouvelle image »). Si la liste manque, ou si sa signature n'est
   pas vérifiée, rien n'est installé. Il lance ensuite `./update.sh` pour cette version, avec cette liste et avec
   l'image épinglée sur l'empreinte vérifiée (`IMAGE=ghcr.io/probant-reporting/probant:X.Y.Z@sha256:…`).
   `./update.sh` fait d'abord la sauvegarde « before-update » de chaque espace, comme toujours, et contrôle chaque
   fichier avec la liste avant d'en mettre un seul en place.
7. Il contrôle `/sante/`, puis de nouveau 30 secondes plus tard.

Si la nouvelle version ne répond pas, le script revient en arrière automatiquement :

1. Il remet les fichiers et le `.env` d'avant (gardés dans `.auto-update/previous/`) et l'image d'avant (elle reste sur
   le serveur).
2. Il compare les migrations de chaque base avec celles d'avant. Si la nouvelle version a changé la base d'un espace,
   il restaure la sauvegarde « before-update » de cet espace faite par `./update.sh`, avec `restore --rebuild` (SQLite
   et PostgreSQL). Un espace qui n'a pas changé n'est pas restauré : rien n'est perdu.
3. Il démarre la version d'avant et contrôle `/sante/`.

L'écran dit alors « Le serveur est revenu à la version X.Y.Z », comme la page **Paramètres › Santé** et les alertes par
e-mail. La même image n'est pas réessayée : quand la cause est connue, l'IT lance `sudo ./auto-update.sh --retry`.

Si le retour arrière ne réussit pas entièrement (une restauration échoue, le registre commun a changé, ou la version
d'avant ne répond pas), le résultat est un échec. L'alerte dit « Appelez votre équipe IT maintenant », et l'IT suit
« Revenir à la version précédente ». Plus rien n'est fait automatiquement, pas même les nuits suivantes, tant que l'IT
n'a pas lancé `sudo ./auto-update.sh --retry`.

#### Signature de la nouvelle image

Le script vérifie la signature avec cosign dans son conteneur officiel, `ghcr.io/sigstore/cosign/cosign`, épinglé par
son empreinte dans `auto-update.sh`. Docker contrôle cette empreinte quand il télécharge le conteneur : rien à installer
à la main. Le conteneur tourne en lecture seule, sans aucun privilège, et sans aucun dossier du serveur sauf les
autorités de certification de votre entreprise (`certificates/ca/`). Le contrôle est celui de « Vérifier l'image »
(section 2) : l'image doit être signée par le workflow `image.yml` du dépôt `Probant-Reporting/probant`, pour
l'étiquette de cette version, avec l'émetteur `https://token.actions.githubusercontent.com`. La signature nomme
l'empreinte de l'image, et le script installe exactement cette empreinte.

Le script vérifie de la même façon la liste des empreintes SHA-256 des fichiers de la version, avec le même conteneur
et la même identité (`cosign verify-blob`). Pour ce contrôle, le conteneur ne lit que le dossier de la liste, en
lecture seule, sous l'utilisateur du script. Ici, une liste qui ne peut pas être vérifiée arrête toujours la mise à
jour.

#### Allumer ou éteindre la minuterie

Dans le dossier de l'outil, en root (`sudo`) :

- `./install.sh --auto-update on` pose la minuterie : chaque nuit vers 04:00, heure du serveur, avec un délai au hasard
  d'une heure au plus. Pour choisir l'heure : `./install.sh --auto-update on --auto-update-time 01:30`. Avec systemd,
  la minuterie est `probant-auto-update-<numéro>.timer`. Sans systemd, c'est un fichier de `/etc/cron.d/`. Sans root,
  c'est une ligne de la crontab de l'utilisateur.
- `./install.sh --auto-update off` retire la minuterie. Rien d'autre ne change.

Sur une installation existante, ces commandes ne changent que la minuterie : le choix dans l'outil reste celui des
gestionnaires des espaces. Avant de supprimer le dossier de l'outil, lancez `./install.sh --auto-update off`. Si le dossier est
déjà supprimé, retirez la minuterie à la main : `sudo systemctl disable --now probant-auto-update-<numéro>.timer`, puis
supprimez les deux fichiers `/etc/systemd/system/probant-auto-update-<numéro>.*` (ou le fichier de `/etc/cron.d/`).

#### Lire le journal

- `auto-update.log`, dans le dossier de l'outil : chaque étape de chaque passage, et la sortie de `./update.sh`.
- Avec systemd : `journalctl -u 'probant-auto-update-*'`, et le prochain passage : `systemctl list-timers 'probant-auto-update-*'`.
- `./auto-update.sh --status` : le dernier résultat.
- `sudo ./auto-update.sh` : un passage maintenant, le même que celui de la minuterie.

L'outil montre le dernier résultat dans **Paramètres › Hébergement**, et dit quand la minuterie a tourné pour la
dernière fois. Si elle n'a pas tourné depuis 3 jours, la page **Paramètres › Santé** le dit, comme les alertes par
e-mail si elles sont allumées.

#### Réseau du serveur

Le script a besoin du même HTTPS sortant (TCP 443) que l'installation, depuis le serveur, pas depuis le conteneur :
voir « Réseau, téléchargements » à la section 1. Derrière un proxy, réglez `HTTPS_PROXY` dans l'environnement de la minuterie (par exemple
`systemctl edit probant-auto-update-<numéro>.service`), et le proxy de Docker pour le téléchargement des images.

### Mettre à jour sans accès à Internet

Pour mettre à jour une installation sans accès à Internet, utilisez le paquet hors ligne de la nouvelle version :

1. Téléchargez le paquet de la nouvelle version et vérifiez-le, comme aux étapes 1 à 3 de « Installer sans accès à
   Internet » (section 2).
2. Copiez le paquet sur le serveur, et extrayez-le dans un autre dossier que le dossier de l'outil. Par exemple :

   ```bash
   mkdir /tmp/probant-new
   tar -xf probant-X.Y.Z-offline.tar -C /tmp/probant-new
   ```

3. Dans le dossier de l'outil, lancez la mise à jour avec l'archive de la nouvelle image :

   ```bash
   ./update.sh --offline /tmp/probant-new/probant/probant-image-X.Y.Z.tar.gz
   ```

4. Quand l'outil marche, supprimez le dossier de l'étape 2 : `rm -rf /tmp/probant-new`.

Le script vérifie les fichiers du paquet avec son `SHA256SUMS`, et refuse une version plus ancienne que la version
installée : dans les deux cas, il ne change rien. Ensuite, il effectue les étapes de la mise à jour, sans aucun
téléchargement :

1. Il fait la sauvegarde « before-update » de chaque espace, avec la version installée.
2. Il met en place les fichiers du paquet (`docker-compose.yml`, `install.sh`, `update.sh`…). Il garde `.env` et les
   données. Il charge la nouvelle image dans Docker et règle `IMAGE` dans `.env` sur elle.
3. Il redémarre l'outil et attend qu'il réponde.

L'image d'avant reste sur le serveur. Pour revenir en arrière, voir « Revenir à la version précédente ». Une
installation faite en une commande, ou depuis un autre paquet hors ligne, se met à jour de la même façon.

### Revenir à la version précédente

> **Avertissement :** revenir en arrière remplace tout ce qui a été fait depuis la sauvegarde « before-update ».
> Prévenez les équipes, et faites-le quand personne ne saisit.

La mise à jour fait une sauvegarde « before-update » de chaque espace avant de changer quoi que ce soit. Listez les
sauvegardes : `docker compose exec web python manage.py backup --list` (ajoutez `-e SPACE=<code>` pour un autre espace).
Les archives d'un autre espace sont dans `/data/backups/spaces/<code>/`, celle du registre commun dans
`/data/backups/shared/`. La version qui a fait une archive sait toujours la lire : pour revenir en arrière, prenez la
plus ancienne archive « before-update » de la mise à jour. La rotation des sauvegardes garde toujours les archives
« before-update » de la dernière mise à jour : le retour arrière reste possible jusqu'à la mise à jour suivante.

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
   - Avec une image publiée (une installation en une commande, par exemple) : mettez l'image précédente dans
     `IMAGE=` du fichier `.env`, puis lancez `docker compose pull web`. À la fin d'une mise à jour, le script affiche
     l'image d'avant la mise à jour (« Image before the update: … »).
   - Sans accès à Internet : l'image d'avant est encore sur le serveur (`docker image ls`). Mettez-la dans `IMAGE=` du
     fichier `.env`, sans `docker compose pull`.
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

Avec Git, pour mettre l'outil à jour plus tard, revenez d'abord sur la branche principale : `git checkout main`, puis
`./update.sh`. Après `git checkout <version-précédente>`, `git pull` refuse de s'exécuter (« You are not currently on a
branch ») et `update.sh` s'arrête. Après une installation en une commande, lancez `./update.sh` : il réinstalle la
dernière version.

#### Restaurer une sauvegarde PostgreSQL sur un nouveau serveur

Une sauvegarde PostgreSQL ne se restaure qu'avec la version de l'outil qui l'a faite, ou avec `--rebuild`. Sur un
nouveau serveur, installez l'outil, restaurez le registre commun (`restore --shared`), puis l'espace principal et chaque
autre espace (étapes 3 et 4 ci-dessus). Le nouveau serveur a une autre clé secrète : ajoutez `--unsigned` à la
restauration de chaque espace, ou copiez le fichier `.secret_key` de l'ancien dossier des données dans le nouveau avant
le premier démarrage.

## 7. Configurer les e-mails (SMTP)

L'outil envoie les e-mails par le serveur d'e-mails (SMTP) de votre entreprise : relances, alertes par e-mail
(section 9) et e-mails de test. Vous pouvez régler ce serveur de deux façons. Les réglages valent pour toute l'installation, pour tous les espaces.

| Façon | Qui | Quand l'utiliser |
|---|---|---|
| Dans l'outil : **Administration › Paramètres › Hébergement**, cadre **E-mails** | Un gestionnaire des espaces | La façon habituelle. L'IT donne seulement les réglages d'un compte d'envoi. Aucun redémarrage. |
| Dans le fichier `.env` (réglages `SMTP_…`) | L'IT | Quand l'IT veut garder les réglages sur le serveur. Ces réglages passent en priorité. |

Sans l'un ni l'autre, l'outil n'envoie aucun e-mail. Il écrit seulement les messages dans le journal
(`docker compose logs web`).

### Configurer les e-mails dans l'outil

Avant de commencer, demandez à l'IT les réglages d'un compte d'envoi : serveur, port, sécurité (STARTTLS ou SSL/TLS),
identifiant, mot de passe et adresse d'expédition. Le **Message à envoyer à l'IT** du cadre **E-mails** donne un texte
prêt.

Pour configurer les e-mails dans l'outil :

1. Allez dans **Administration › Paramètres › Hébergement**. Le cadre **E-mails** montre les champs du serveur d'envoi.
2. Saisissez le **Serveur d'envoi (SMTP)**, par exemple `smtp.example.com`, sans `smtp://` et sans le port.
3. Saisissez le **Port** et choisissez la **Sécurité** : **STARTTLS** (souvent le port 587) ou **SSL/TLS** (souvent le
   port 465). Avec ces deux choix, l'outil vérifie le certificat du serveur. **Aucune** envoie le mot de passe sans
   chiffrement : ne l'utilisez que sur un réseau interne fermé. Avec **Aucune** et un mot de passe, l'outil demande une confirmation.
4. Saisissez l'**Identifiant**, le **Mot de passe** et l'**Adresse d'expédition**.
5. Cliquez sur **Enregistrer**.
6. Sous **E-mail de test**, cliquez sur **Envoyer un e-mail de test**. Le test utilise les réglages enregistrés. Si
   l'e-mail ne part pas, un message donne la cause en clair : serveur introuvable, connexion refusée, délai dépassé,
   certificat, sécurité, identifiant ou mot de passe refusé, adresse d'expédition refusée.

![Administration › Paramètres › Hébergement, cadre E-mails : serveur d'envoi réglé dans l'outil](../screenshots/fr/hosting-emails.png)

Le mot de passe fonctionne ainsi :

- L'outil ne réaffiche jamais le mot de passe. Il ne l'écrit jamais dans l'historique, dans le journal, ni dans le
  fichier de configuration que vous exportez.
- Pour garder le mot de passe enregistré, laissez le champ vide quand vous enregistrez. Pour l'effacer, cliquez sur
  **Effacer le mot de passe**.
- Si vous changez le serveur, le port ou l'identifiant, ou si vous passez la sécurité à « Aucune », l'outil efface le
  mot de passe enregistré, pour qu'il ne parte jamais vers un autre serveur. Saisissez-le de nouveau dans le même
  enregistrement. Sinon, l'écran vous le dit.
- L'outil garde le mot de passe chiffré avec la clé secrète de l'installation (`DJANGO_SECRET_KEY`, ou le fichier
  `/data/.secret_key`). La sauvegarde d'un espace ne contient jamais les réglages des e-mails. La sauvegarde du registre
  commun (`backups/shared`, réservée à l'IT) les contient, avec le mot de passe chiffré.
- Si la clé secrète change, ou si l'IT restaure le registre commun sur un autre serveur, l'outil ne peut plus lire le
  mot de passe. Le cadre **E-mails** et **Paramètres › Santé** disent alors qu'il faut le saisir de nouveau. Aucun
  e-mail ne part d'ici là. Saisissez de nouveau le mot de passe et enregistrez.

Pour éviter qu'on détourne le bouton de test, l'outil accepte au plus 5 e-mails de test toutes les 15 minutes avec les
réglages de l'outil, et attend le serveur 10 secondes au plus. Le message d'erreur ne montre jamais la réponse du
serveur. Chaque test qui échoue est écrit dans l'historique.

Seul un gestionnaire des espaces peut changer ces réglages. Les autres administrateurs voient le serveur et l'adresse
d'expédition, et peuvent envoyer un e-mail de test avec les réglages enregistrés.

### Configurer les e-mails dans le fichier `.env`

Pour configurer les e-mails dans le fichier `.env` :

1. Ajoutez ces valeurs dans `.env` :

   ```
   SMTP_HOST=smtp.example.com
   SMTP_PORT=587
   SMTP_SECURITY=starttls        # starttls (587), ssl (465) ou none
   SMTP_USER=reporting@example.com
   SMTP_PASSWORD=…
   SMTP_FROM=reporting@example.com
   ```

2. Lancez `docker compose up -d`.
3. Allez dans **Administration › Paramètres › Hébergement**, puis cliquez sur **Envoyer un e-mail de test**. Si
   l'e-mail ne part pas, un message donne la cause.

> **Remarque :** Quand `SMTP_HOST` est rempli, le fichier `.env` passe avant les réglages saisis dans l'outil. Le cadre
> **E-mails** montre alors les réglages du fichier `.env` en lecture seule (sans le mot de passe), avec la mention
> « Réglé par l'IT dans le fichier de réglages ». Pour revenir aux réglages de l'outil, videz `SMTP_HOST` et
> redémarrez l'outil.

### Relances

Les administrateurs et les validateurs envoient les e-mails de relance dans **Tableau de bord › Relancer…**. Chaque
personne reçoit un seul e-mail, sans copie. L'e-mail liste ce qui lui reste à saisir. Avant d'envoyer l'e-mail,
l'outil affiche l'aperçu exact du message. Un administrateur règle le modèle.

Un administrateur peut activer les relances automatiques dans la même page. L'outil les envoie aux jours choisis
avant la fin de la saisie. Il les vérifie chaque jour à `REMINDER_TIME` (09:00 par défaut). `PUBLIC_URL` donne
l'adresse mise dans ces e-mails. Par défaut, l'outil déduit cette adresse de `DOMAIN`.

![Tableau de bord › Relances : personnes, aperçu du message, modèle et relances automatiques](../screenshots/fr/reminders.png)

## 8. Utiliser PostgreSQL (facultatif)

SQLite est la base par défaut. Vous n'avez aucun serveur de base de données à gérer. SQLite écrit un enregistrement à
la fois. Les autres enregistrements attendent leur tour, jusqu'à 60 secondes. Quand beaucoup de personnes
enregistrent au même moment, passez à PostgreSQL : voir « Capacité ».

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
pas de commande pour cela. Un essai de ce passage a comparé les données de l'installation PostgreSQL à celles de
l'installation SQLite, table par table, pour deux espaces : elles sont identiques (seuls les numéros des lignes d'accès
du registre changent).

### Plusieurs espaces avec PostgreSQL

Chaque espace (département) ouvre ses propres connexions à la base. Avant de créer beaucoup d'espaces, vérifiez la
limite de connexions de votre offre (petites offres Clever Cloud). Voir [docs/spaces.md](../spaces.md) (en anglais).

## 9. Superviser l'outil et lire les journaux

### Recevoir un e-mail quand quelque chose ne va pas

L'outil vous prévient par e-mail : vous n'avez aucune supervision à brancher. Sur une installation neuve, les alertes
par e-mail sont allumées d'office. Elles ont besoin du serveur d'e-mails (section 7) : sans lui, l'outil n'envoie
rien. Une installation qui existait avant les alertes par e-mail les garde éteintes après une mise à jour, tant qu'un
gestionnaire des espaces ne les allume pas. Une fois éteintes, elles le restent.

Un gestionnaire des espaces règle les alertes dans **Administration › Paramètres › Santé**, encart **Alertes par
e-mail**, et choisit les destinataires : par défaut les administrateurs de l'espace principal et les gestionnaires des
espaces, plus d'autres adresses, par exemple la boîte de l'équipe IT.

![Administration › Paramètres › Santé, encart Alertes par e-mail : alertes allumées, destinataires et alerte d'essai](../screenshots/fr/admin-health-alerts.png)

Les alertes viennent des mêmes contrôles que la page **Santé** et `/sante/`. Ces contrôles envoient une alerte :

| Contrôle | Alerte quand |
|---|---|
| Base de données | Une base ne répond pas, ou le contrôle du démarrage a trouvé une base abîmée |
| Données de démonstration | La base est celle de la démo, et des comptes de démo ont encore le mot de passe public (jamais en mode développement ni dans la version tout-en-un). L'outil démarre quand même. La ligne disparaît quand plus aucun compte de démo actif n'a le mot de passe public. |
| Fichiers | L'outil ne peut pas écrire dans son dossier des données |
| Dernière sauvegarde | La sauvegarde automatique a échoué ou est en retard, la dernière sauvegarde ne se lit pas, ou le dossier des sauvegardes ne se lit pas |
| Espace disque | Moins de 10 fois `DISK_ALERT_MB` libres (« À regarder »), ou moins de `DISK_ALERT_MB` (« En panne ») |
| E-mails | Les relances ont échoué, ou le mot de passe enregistré du serveur d'e-mails ne se lit plus |
| Tâches de fond | Une tâche de fond s'est arrêtée, un import ou un export est bloqué, ou le contrôle des données de la nuit est en retard ou a trouvé des erreurs |
| Mise à jour de la base | Des migrations ne sont pas appliquées |
| Copie externe | Une copie des sauvegardes échoue, ou est en retard (section 5) |
| Mises à jour automatiques | Une nouvelle version est installée, ou attend (« Prévenir seulement »). Une signature est refusée. Le serveur est revenu à la version précédente, ou n'a pas pu y revenir. La minuterie ou la vérification ne fonctionne plus depuis 3 jours (section 6) |

Ces états n'envoient pas d'alerte : aucune sauvegarde encore, sauvegardes automatiques éteintes, restauration qui se
termine seule, HTTPS (il dépend de la requête).

Les règles :

- L'outil vérifie toutes les 15 minutes, dans les processus `check_data --schedule` et `backup --schedule`. Une seule
  vérification à la fois pour toute l'installation, même avec plusieurs processus, espaces ou serveurs.
- Un e-mail quand un problème apparaît. Tout ce qui change dans une même vérification part dans un seul e-mail.
- Un rappel au plus une fois par jour tant qu'un problème dure, un seul e-mail pour tous les problèmes.
- Un e-mail quand un problème est résolu (absent à deux vérifications de suite).
- Chaque personne reçoit l'e-mail dans sa langue. Les autres adresses le reçoivent dans la langue de l'installation.
  L'e-mail donne le nom de l'espace, ce qui se passe, depuis quand, quoi faire et le lien vers la page **Santé**
  (`PUBLIC_URL`). Il ne contient jamais de données, de dossier du disque ni le détail pour l'IT.
- Si l'e-mail ne part pas (serveur d'e-mails en panne), rien ne plante : le problème reste sur la page **Santé** et dans
  `/sante/`, le journal donne la cause (`Email alerts not sent through …`) et l'outil réessaie à la vérification
  suivante.
- L'état des alertes est gardé dans le registre commun, hors de la base de chaque espace : la restauration d'un espace
  ne renvoie pas les alertes. Après une restauration du registre commun, les alertes des problèmes qui restent repartent
  une fois.
- **Envoyer une alerte d'essai** envoie aux destinataires enregistrés un e-mail avec les problèmes du moment.

**Limite :** quand le serveur est éteint, ou quand le registre commun ne répond pas, l'outil ne peut prévenir personne.
Pour être prévenu aussi dans ce cas, gardez une supervision externe de `/sante/` (ci-dessous), en plus des alertes par
e-mail.

Sans tâches de fond (hébergement géré avec des tâches planifiées, voir [Hébergement géré](hebergement_cle_en_main.md)),
planifiez `python manage.py check_data --alerts` toutes les 15 minutes. La version tout-en-un ne lance aucune tâche de
fond et n'envoie aucune alerte.

### Vérifier que l'outil va bien

En plus des alertes par e-mail, votre supervision peut appeler `/sante/`. `GET /sante/` répond avec l'un de ces codes :

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
| `external_copy` | La copie externe des sauvegardes ([Copier les sauvegardes hors du serveur](#copier-les-sauvegardes-hors-du-serveur)) : `state` (`off`, `ok`, `failing`, `late`, `host key to confirm`, `unavailable` dans la version tout-en-un), `last_success`, `pending` (archives pas encore copiées). Une copie en échec ne cause jamais de `503` : elle est dans `avertissement`. |

Un problème de données ou un contrôle en retard ne fait **jamais** répondre `503` à `/sante/`. `503` veut dire
« l'outil ne répond pas ». Docker ou Clever Cloud redémarrent alors l'outil, et un redémarrage ne corrige ni un
chiffre ni un planificateur arrêté. Pour surveiller le contrôle de chaque nuit, créez une alerte sur
`controle_donnees.etat` = `late`. Les alertes par e-mail de l'outil le disent aussi.

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

Les gros imports de valeurs se font en arrière-plan, dans le processus `run_imports --schedule`. L'image lance ce
processus à côté des sauvegardes, des relances et du contrôle des données. Le même processus fabrique les gros exports
(au-delà du seuil que l'administrateur règle dans **Administration › Paramètres › Hébergement › Gros exports**). Leurs
fichiers sont dans `files/exports/` du dossier des données, effacés après 7 jours, et jamais dans les sauvegardes :
rien à copier. Le détail de `/sante/` donne
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
| Tout le monde doit se reconnecter après un redémarrage | Le fichier `.secret_key` du dossier des données a été supprimé ou était vide. L'outil a créé une nouvelle clé (journal : « New secret key created »). Les sauvegardes faites avant sont refusées dans **Paramètres › Hébergement** (restaurez-les en ligne de commande avec `--unsigned`). Les secrets enregistrés dans l'outil sont à saisir de nouveau : le mot de passe du serveur d'e-mails, les secrets de la copie externe et le secret du client de la connexion d'entreprise (les écrans le disent). Rien d'autre n'est perdu. |
| Horloge du serveur fausse (date dans le futur, puis corrigée) | L'outil garde les sauvegardes datées dans le futur, mais ne les compte pas dans la rotation. La prochaine sauvegarde automatique se fait à l'heure habituelle. `/sante/` le signale (`avertissement`). Corrigez l'horloge (NTP). |
| « database is locked » | Un enregistrement a attendu son tour plus de 60 secondes : SQLite écrit un enregistrement à la fois. C'est rare, car SQLite fonctionne en mode WAL. Quand cela arrive, le serveur est surchargé. Vérifiez que l'outil a ses processeurs pour lui seul (`docker stats`). Évitez **Refaire tous les calculs** et les gros imports aux heures les plus chargées. Puis donnez plus de processeurs au serveur, ou passez à PostgreSQL (section 8). |
| L'e-mail de test ou l'alerte d'essai échoue | Le message donne la cause (identifiant refusé, port bloqué, TLS…). Vérifiez les réglages du serveur d'e-mails avec le fournisseur de messagerie : dans **Administration › Paramètres › Hébergement**, encart **E-mails**, ou les réglages `SMTP_…` du fichier `.env` si votre équipe IT les y a mis (ils passent en premier). Le journal donne la cause technique (`Test email to …` ou `Email alerts not sent through …`). |
| **Santé** dit qu'une tâche de fond s'est arrêtée, alors qu'elle a été retirée exprès | L'outil se souvient de chaque tâche de fond qui a tourné sur le serveur (`.tasks/` dans le dossier des données). Supprimez le fichier de la tâche retirée, par exemple `docker compose exec web rm /data/.tasks/imports`. |
| L'assistant IA dit « Le serveur ne peut pas joindre le fournisseur » | Ouvrez les connexions HTTPS sortantes vers `api.anthropic.com` dans le pare-feu, ou réglez `HTTPS_PROXY` (section 4, « Assistant IA »). |
| Mot de passe administrateur perdu | Un autre administrateur le réinitialise dans **Administration › Comptes**. S'il n'y a pas d'autre administrateur, lancez `docker compose exec web python manage.py changepassword <e-mail>`. |
| Plus aucun compte n'ouvre **Administration** | L'outil ne laisse jamais le dernier administrateur actif perdre son rôle ou son accès. Cela peut tout de même arriver après la restauration d'une ancienne sauvegarde, ou après un changement fait directement dans la base. Rendez le rôle d'administrateur à un compte existant : `docker compose exec web python manage.py grant_admin <e-mail>`. L'outil inscrit le changement dans l'historique. |
| Tout recommencer depuis zéro (essai) | **Avertissement :** cela **efface toutes les données**. Lancez `docker compose down -v`, puis `./install.sh`. |

## 11. Tester l'installation

Cette partie s'adresse aux personnes qui modifient le code de l'outil. Vous n'en avez pas besoin pour installer
l'outil. Les scripts d'essai sont dans le code (dossier `docker/`), pas dans le dossier d'une installation en une
commande.

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

Le script `bash docker/test_get.sh` teste l'installation en une commande. Il sert une copie locale du dépôt public et
un registre d'images local, puis lance `get.sh` par un tube, comme à la section 2. Les listes d'empreintes des
releases locales sont signées avec une clé d'essai de cosign. Avant, il vérifie les refus : un fichier de l'étiquette
changé, la liste changée après sa signature, et une release sans liste. Ensuite, il vérifie la mise à jour vers une
version plus récente et le retour à la version précédente (section 6). Les variables `PROBANT_TEST_SOURCE`,
`PROBANT_TEST_IMAGE`, `PROBANT_TEST_OS_RELEASE`, `PROBANT_TEST_SKIP_CHECK`, `PROBANT_TEST_COSIGN_KEY` et
`PROBANT_TEST_COSIGN_IMAGE` des scripts servent seulement à ces tests : ne les réglez pas sur un serveur. Les deux
variables de cosign ne sont lues qu'avec une source ou une image d'essai (`PROBANT_TEST_SOURCE`, `PROBANT_TEST_IMAGE`) :
les fichiers et l'image du dépôt public sont toujours vérifiés avec son identité.

Le script `bash docker/test_offline.sh` teste l'installation sans accès à Internet. Il fabrique les paquets hors ligne
de deux versions avec `docker/make_offline_package.sh`, à partir de l'image du dossier. Ensuite, il joue un serveur sans
accès à Internet : le nom de l'image pointe vers un registre où rien ne répond, `curl` et `wget` échouent, Docker ne
doit télécharger aucune image et, quand le système le permet, les scripts tournent sans aucun réseau (`unshare --net`). Il vérifie l'installation (`./install.sh --offline`), la mise à jour vers la seconde
version (`./update.sh --offline`), le refus d'un paquet plus ancien, et le retour à la première version (section 6).

Le script `bash docker/test_custom_certificate.sh` teste le réseau d'entreprise (section 2, « Réseau d'entreprise »).
Il crée une autorité de certification d'essai et un certificat de serveur signé par elle. Ensuite, il installe l'outil
avec `--domain`, `--cert`, `--key` et `--ca-cert`, et vérifie ces points : Caddy sert ce certificat (`curl --cacert`),
la page de santé répond en HTTPS, Caddy ne contacte jamais Let's Encrypt, la clé n'entre jamais dans le conteneur de
l'outil, une connexion HTTPS sortante de l'outil fait confiance à l'autorité, et le renouvellement. Puis il refait le
même essai sans accès à Internet, depuis un paquet hors ligne. `TEST_HTTPS_PORT` et `TEST_HTTP_PORT` choisissent
d'autres ports que 443 et 80.

Le script `bash docker/test_auto_update.sh` teste les mises à jour automatiques (section 6), avec un registre d'images
local, une copie locale du dépôt public et une clé d'essai de cosign. Sur une installation faite par `get.sh`, il joue
les choix « Éteint » et « Prévenir seulement », l'attente après la publication, une signature absente ou fausse, une
liste d'empreintes absente ou modifiée, une nouvelle version qui ne démarre pas (retour arrière, avec et sans
restauration), le verrou partagé avec `./update.sh`, et une mise à jour réussie. Il demande Docker et cosign 3
(`COSIGN_BINARY`). La signature faite par le workflow du dépôt public ne se vérifie que sur GitHub, à chaque version
publiée.
