# Rangement des fichiers

> Version française du guide anglais [docs/file_layout.md](../file_layout.md), qui fait référence.

Cette page indique où va chaque sorte de document : dans le dossier des données d'une installation, ou dans le dossier
du code.

La règle est simple : **chaque sorte de document a son dossier, et rien n'est mélangé**. Ce qui est fourni avec
l'outil (le code, le référentiel de départ) reste dans le dossier du code. Ce qui est propre à une installation
(bases, preuves, logo, sauvegardes) va dans **son dossier des données**, jamais dans le dossier du code. Un seul
endroit définit le rangement : `parametres/rangement.py`.

## 1. Le dossier des données d'une installation

### Trouver le dossier des données

Le tableau indique où se trouve le dossier des données, pour chaque sorte d'installation :

| Où | Dossier des données |
|---|---|
| Image Docker (serveur de l'IT) | `/data` (le volume) |
| Poste de développement, Codespace | `local-data/` dans le dossier du projet (jamais versionné) |
| Version tout-en-un (Windows, Mac) | `data/` à côté de `Start.bat` / `Start.command` (déjà rangé dans le paquet, que fabrique `portable/build_package.py`) |
| Hébergeur clé en main | Le dossier persistant réglé par `DATA_DIR` |

### Contenu du dossier des données

L'outil range lui-même le dossier des données. Un fichier `README.txt` dans le dossier rappelle ce rangement à l'IT :

```
<dossier des données>/
├── README.txt                   ce plan
├── db.sqlite3                   base de l'espace principal (SQLite ; avec PostgreSQL, la base est ailleurs)
├── shared.sqlite3               registre des comptes, commun à tous les espaces
├── .secret_key                  clé de l'installation : à ne jamais partager
├── .secret_key_all_in_one       clé de la version tout-en-un : à ne jamais partager (un serveur crée la sienne)
├── files/                       DOCUMENTS DÉPOSÉS DANS L'OUTIL (espace principal)
│   ├── evidence/                documents de preuve des contributeurs
│   │   └── <période>/<organisation>/<KPI>/<fichier>
│   │       exemple : evidence/2026/ES-COM/100245/facture-gaz.pdf
│   ├── settings/
│   │   └── logo/                logo de l'installation (Administration › Paramètres › Identité)
│   ├── pending-imports/         fichiers déposés pour un import ; effacés après usage, jamais sauvegardés
│   └── exports/                 gros exports fabriqués en arrière-plan ; effacés après 7 jours (réglable), jamais sauvegardés
├── sign-in-attempts/            compteur des connexions manquées, partagé par les processus du serveur (jamais sauvegardé)
├── ai-keys/<code>.key           clé de l'assistant IA de chaque espace (docs/fr/prise_ia.md) : jamais en base, jamais sauvegardée
├── ca-bundle.pem                autorités de certification du système et celles ajoutées par l'IT, réunies à chaque démarrage (seulement quand l'IT en ajoute, docs/fr/installation.md, « Réseau d'entreprise ») ; jamais sauvegardé
├── backups/                     ARCHIVES DATÉES (base + fichiers)
│   ├── backup-AAAAMMJJ-HHMMSS-<motif>.zip    espace principal
│   ├── restores.jsonl           historique des restaurations
│   ├── data-checks.json         derniers résultats du contrôle des données de chaque nuit (check_data)
│   ├── .restore-in-progress.json  seulement pendant une restauration (ou si elle a été interrompue : terminée au démarrage suivant)
│   ├── .database-damaged        seulement si le contrôle d'intégrité a échoué (signalé par /sante/)
│   ├── shared/                  archives du registre des comptes
│   └── spaces/<code>/           archives des autres espaces
└── spaces-data/                 AUTRES ESPACES (Achats, RH…)
    └── <code>/
        ├── database.sqlite3
        └── files/               même rangement que ci-dessus (evidence/, settings/logo/, pending-imports/, exports/)
```

Les noms des dossiers et des fichiers sont en anglais, par exemple `evidence/` pour les preuves et `backups/` pour
les sauvegardes. L'interface de l'outil existe en français, anglais, espagnol, allemand, italien, néerlandais et portugais.

### Motifs dans le nom des archives de sauvegarde

Le motif à la fin du nom d'une archive dit pourquoi l'outil l'a faite :

| Motif | L'archive vient de |
|---|---|
| `auto` | La sauvegarde automatique |
| `manuelle` | Le bouton **Créer et télécharger une sauvegarde**, dans **Administration › Paramètres › Hébergement** |
| `before-update` | La sauvegarde avant une mise à jour |
| `before-restore` | La sauvegarde avant une restauration |
| `uploaded` | Une archive importée dans l'outil |
| Aucun motif | La commande `backup`, sans `--reason` |

### Où va chaque sorte de document

Le tableau indique qui ajoute chaque sorte de document, où il va, et si les sauvegardes le contiennent :

| Sorte de document | Qui l'ajoute | Où il va | Sauvegardé |
|---|---|---|---|
| Preuve (PDF, JPG, PNG) | Contributeur, validateur, administrateur, depuis la case d'un KPI | `files/evidence/<période>/<organisation>/<KPI>/` | Oui |
| Logo | Administrateur (**Administration › Paramètres › Identité**) | `files/settings/logo/` | Oui |
| Fichier d'import (valeurs, configuration, référentiel, reprise) | Administrateur | `files/pending-imports/`, effacé après l'import ou au bout d'un jour | Non (temporaire) |
| Gros export (au-delà du seuil de **Paramètres › Hébergement › Gros exports**) | Toute personne qui peut exporter | `files/exports/<nom au hasard>.xlsx` ou `.csv`, jusqu'au téléchargement, 7 jours au plus (réglable) ; puis effacé par le planificateur, aussi au démarrage | Non (refait sur demande) |
| Archive de sauvegarde | Automatique, ou administrateur / IT | `backups/` | — |
| Copie d'une archive de sauvegarde hors du serveur | L'outil, quand une destination est réglée (**Paramètres › Hébergement › Copie externe**) | À la destination : `<dossier ou préfixe>/<identifiant de l'installation>/`, rangé comme `backups/` (`backup-….zip`, `spaces/<code>/`, `shared/`). Ce qui est déjà copié est noté dans le registre commun des comptes, jamais dans un fichier du dossier des données. | — |
| Export Excel ou CSV | Tout utilisateur | Téléchargé directement, jamais gardé sur le serveur | — |

### Dossiers des preuves

Le dossier d'une preuve suit le chemin d'un auditeur :

1. La période : « 2026 », ou « 2026-03 » pour une période plus courte
2. L'organisation : son code, qui ne change pas quand vous renommez l'organisation
3. Le KPI

Le nom du fichier est le nom du fichier que la personne a ajouté, sans caractère spécial. Deux fichiers de même nom
dans la même case ne s'écrasent jamais : le second fichier reçoit un suffixe.

## 2. Le dossier du code

Le dossier du code contient l'outil et les contenus fournis avec lui :

```
collecte/  parametres/  referentiel/  espaces/  serveur_mcp/  config/   le code de l'outil
templates/  static/  libelles/                           pages, styles, textes (sept langues)
resources/                                               fichiers de travail locaux, jamais versionnés (vide dans le dépôt)
docs/                                                    guides (installation, recette, rangement…), en anglais
docs/fr/                                                 traduction française des principaux guides
docs/guides/, docs/<langue>/guides/                      guides par rôle dans les sept langues (fr, es, de, it, nl, pt), servis par l'outil (Aide)
docs/screenshots/<langue>/                               captures des guides (faites par qa/guide_screenshots.js)
qa/  docker/  portable/  .devcontainer/                  outils de vérification et d'installation
local-data/                                              données de développement (ignoré par git)
```

Un vrai fichier de travail (données réelles, noms, e-mails) ne va jamais dans `resources/`. Importez-le dans l'outil,
ou placez-le dans le dossier des données de l'installation.

## 3. Passage à ce rangement, sans perte

Une installation passe toute seule à ce rangement quand vous la mettez à jour. Rien n'est perdu.

### Fichiers de chaque espace

Au démarrage, puis par la migration `collecte/0029`, l'outil change ces dossiers pour chaque espace :

| Avant | Après |
|---|---|
| `media/` | `files/` |
| `evidence/<période>/<KPI>/<n° d'organisation>_<fichier>` | `evidence/<période>/<organisation>/<KPI>/<fichier>` |
| `identite/` (logo) | `settings/logo/` |
| `imports/` | `pending-imports/` |

L'outil déplace les fichiers : il ne les copie jamais et ne les écrase jamais. Le nom de chaque fichier en base suit
le déplacement. Un fichier déjà absent garde son nom.

### Poste de développement et Codespace

Au premier lancement, les bases, fichiers et sauvegardes restés à la racine du projet passent tout seuls dans
`local-data/`.

### Anciennes archives de sauvegarde

Vous pouvez toujours restaurer une ancienne archive de sauvegarde. La migration range ses fichiers, comme ceux d'une
installation mise à jour.
