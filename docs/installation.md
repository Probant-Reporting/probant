# Install Probant

This guide is for the IT team. It tells you how to install Probant on a Linux server with Docker, then how to set it
up, back it up, update it, and monitor it. You do not need to know Django or Python.

The tool runs in **a single Docker container**. All its data is in **a single volume**, `/data`: database, evidence
files, logo, backups, and secret key.

This table shows which way to follow:

| Your case | Follow | Duration |
|---|---|---|
| A Linux server with Internet access (the usual case) | [Install with one command](#install-with-one-command) | About 2 minutes |
| You want the server to build the image from the code | [Install with Git](#install-with-git) | 3 to 5 minutes |
| A server without Internet access | [Install without Internet access](#install-without-internet-access) | |
| You do not want to manage a server | [Managed hosting (Clever Cloud)](managed_hosting.md) | About 30 minutes |
| A trial by one person on one Windows or Mac computer | The all-in-one version: `probant-windows.zip` or `probant-mac.zip` on the page of the latest release (https://github.com/Probant-Reporting/probant/releases/latest). It needs no installation and no administrator rights. To move its data to a server later, see [From the all-in-one version to a server](from_pc_to_server.md). | |

Before you start, you need a 64-bit Linux server with 1 GB of memory, and an account that can use `sudo`. On Debian or
Ubuntu, you do not have to install Docker first: the installer offers to install it. The full list is in section 1.
The list of what IT prepares is in [What to prepare](it_request.md), and the file for a security review is in
[Security overview](security_overview.md).

Right after the installation, open the address of the tool and create the administrator account (section 3).

This table shows the everyday operations, in the folder of the tool:

| Operation | Command | Duration |
|---|---|---|
| Update | `./update.sh` | 1 to 3 minutes |
| Back up | Nothing: automatic every night. Now: `docker compose exec web python manage.py backup` | A few seconds |
| Restore | `docker compose exec web python manage.py restore <archive>` | A few seconds |

## 1. Prerequisites

This table shows what you need before you install the tool:

| Need | Recommended minimum |
|---|---|
| Server | 64-bit Linux on `x86_64` (on `arm64`, install with Git only), for example Debian 12 or later, or Ubuntu 22.04 or later. 1 CPU, 1 GB of memory, 5 GB of disk |
| Software | On Debian or Ubuntu: nothing to install first, except `curl` if it is missing. The installer offers to install Docker, and waits for your yes. On another Linux system: first install Docker Engine 24 or later with the Compose plugin v2.24 or later (`docker compose version`). Git only to install with Git |
| Account | An account that can use `sudo` |
| Network, internal access | 1 port open to the server (8000 by default) |
| Network, HTTPS access | A domain name that points to the server (for example, `reporting.example.com`), and ports 80 and 443 (TCP, and UDP 443 for HTTP/3) open from the Internet (automatic Let's Encrypt certificate). With the certificate of your company, the Internet does not need to reach the server: see “Company network” |
| Network, downloads | Outgoing HTTPS (TCP 443) from the server, during the installation and each update: `github.com` and `raw.githubusercontent.com` (files), `objects.githubusercontent.com` and `release-assets.githubusercontent.com` (list of the sums of the files, attached to the release), `ghcr.io` and `pkg-containers.githubusercontent.com` (image of the tool and container of cosign), `tuf-repo-cdn.sigstore.dev` (trusted root of Sigstore, to verify the signatures). With HTTPS (`--domain`): also Docker Hub (image of Caddy). With Git: also Docker Hub and PyPI (the server builds the image). With the automatic updates (section 6), the server opens the same connections at night. To install Docker with the installer: `download.docker.com` and the package mirrors of the system. Without Internet access: none (see “Install without Internet access”) |
| Emails (optional) | An SMTP account (server, port, username, password, sender address) |
| AI assistant (optional) | Outgoing HTTPS (TCP 443) from the server to `api.anthropic.com`, only if an administrator turns the assistant on. See “AI assistant” in section 4 |

The server does not need Python, a web server, or a database. Everything is in the image.

### Install Docker on Debian or Ubuntu

If Docker is missing, the installer asks this question:
`Install Docker now, from Docker's apt repository (download.docker.com)? [y/N]`. Type `y` to install it. Any other
answer stops the installer, and nothing changes.

The installer uses the official procedure of Docker (https://docs.docker.com/engine/install/): it adds the apt
repository of Docker, checked with the key of Docker, then installs the packages `docker-ce`, `docker-ce-cli`,
`containerd.io`, `docker-buildx-plugin` and `docker-compose-plugin`. Its rules are these:

- It never installs Docker without a yes. Without a terminal (an automatic deployment, for example), add the option
  `--yes` to answer yes.
- It installs Docker only on Debian and Ubuntu. On another system, it stops: install Docker yourself, then run the
  installer again.
- It needs administrator rights: run it as `root` or with `sudo`. Otherwise, it stops and changes nothing.

To use Docker without `sudo`, add your account to the `docker` group (`sudo usermod -aG docker $USER`), then sign out
and sign in again. A member of this group has the same rights as `root` on the server.

## 2. Install the tool

You can install the tool in two ways. This table compares them:

| Way | What the server needs, besides Docker | Duration |
|---|---|---|
| With one command (recommended) | `curl` | About 2 minutes: the server downloads the published image |
| With Git | Git | 3 to 5 minutes: the server builds the image |

The two ways give the same tool, with the same settings and backups. Only the installation with one command sets up
the automatic updates (section 6). For a server without Internet access, see “Install without Internet access”.

### Check the server before you install

You do not have to run this check yourself: the installer runs it at the start of a new installation. Run it before,
if you want to know what is missing without installing anything. The check reads the server and changes nothing. It
is the script `check.sh`, in the files of each version.

To check the server before an installation with one command, run the command of the installation with `--check`:

```bash
curl -fsSL https://github.com/Probant-Reporting/probant/raw/main/get.sh | sudo sh -s -- --check
```

Add the options of the installation, for example `--domain reporting.example.com` or `--port 8080`. The command
downloads the check of the version into a temporary folder, runs it, then deletes the folder. In a folder with the
files of the tool (an installation with Git, for example), run `./install.sh --check`, with the same options.

This table shows what the check verifies:

| Check | What it verifies |
|---|---|
| System and architecture | Linux, 64-bit. The published image is for `x86_64`: on `arm64`, install with Git. |
| Docker and Compose | Docker Engine 24 or later, Compose plugin v2.24 or later (section 1). |
| Docker service | Docker responds, and the account has the right to use it (`sudo`, or the `docker` group). |
| Memory, processors, disk | At least 1 GB of memory, 1 processor, and 5 GB free in the folder of Docker. |
| Ports | The HTTP port is free (8000, or `--port`). With `--domain`: also ports 80 and 443. |
| Domain name | With `--domain`: the name points to an address of the server. |
| Network | The registry of the image and GitHub (files of the version) answer over HTTPS, through `HTTPS_PROXY` if it is set. With a proxy, it also checks that the Docker service can download the image. |
| Clock | The time of the server is right: at most 5 minutes from the time of GitHub. |

The check shows one line for each check:

- `OK`: nothing to do.
- `To fix`: the line says what to do, in one sentence.
- `Not checked`: the line says why. For example, a server behind a router (NAT) does not know its public address. The
  check cannot know if the domain name points to it. Check the DNS record and the router yourself.

At the end, the check shows `Ready`, or `Here is what is missing` with the list of the points to fix. It ends with the
exit code 0 (ready) or 1 (something is missing).

At the start of a new installation (a folder without `.env`), if a point is to fix, the installer stops and installs
nothing. A missing Docker does not stop it: the installer offers to install Docker next. To install without the
check, add `--skip-check`. Use this option only if you know why the check fails. For example, behind a proxy that the
check cannot use.

If the network uses a proxy, set it before the check: `sudo HTTPS_PROXY=http://proxy.example.com:3128 sh …`. With
`sudo`, the variables of your session do not pass to the script. Docker downloads the image itself: set the proxy of
the Docker service too (https://docs.docker.com/engine/daemon/proxy/).

### Install with one command

The command uses the published image of the tool, `ghcr.io/probant-reporting/probant`. The server does not build
anything, and it does not need Git.

To install the tool:

1. Sign in to the server with an account that can use `sudo`.
2. Go to the folder that will contain the folder of the tool (for example, `cd /opt`).
3. Run the command:

   ```bash
   curl -fsSL https://github.com/Probant-Reporting/probant/raw/main/get.sh | sudo sh
   ```

   For HTTPS with a domain name, add the options after `sh -s --`:

   ```bash
   curl -fsSL https://github.com/Probant-Reporting/probant/raw/main/get.sh | sudo sh -s -- --domain reporting.example.com
   ```

   The command shows the address to open and the folder of the installation.
4. Go to the folder of the tool: `cd probant`. Run the other commands of this guide in this folder.

> **Note:** The automatic updates are on after this installation: the server installs each new version at night,
> 3 days after its publication. To install without them, add `--auto-update off`. See “Automatic updates”
> (section 6).

The command does these steps, in this order:

1. It finds the latest published version of the tool.
2. It creates the folder `probant`. If this folder already contains an installation, the command stops and changes
   nothing.
3. It downloads into this folder only the files that run the tool: `docker-compose.yml`, `.env.example`,
   `install.sh`, `update.sh`, `check.sh`, `docker/Caddyfile` and `auto-update.sh`. They come from the tag of this
   version in the public repository (https://github.com/Probant-Reporting/probant), over HTTPS only.
4. It checks each file against the list of the SHA-256 sums (one fingerprint per file) attached to the release of
   this version (`probant-X.Y.Z-files.sha256`). The release is the page of the version on GitHub, with its files. The
   command also verifies the signature of this list with cosign (the signature tool of Sigstore), when cosign is on
   the server or when Docker responds. If the list is missing, if its signature is refused, or if one file does not
   match, the command stops and installs nothing. The command says what it verified.
5. It runs `./install.sh` with the published image of this version. See “What the installer does”.
6. It sets up the timer of the automatic updates (see the note above).

This table shows the options of the command:

| Option | Effect |
|---|---|
| `--version X.Y.Z` | Installs this version instead of the latest one. |
| `--dir FOLDER` | Installs into this folder instead of `probant`. |
| `--check` | Only checks the server, and installs nothing. See “Check the server before you install”. |
| `--auto-update off` | Installs without the automatic updates (section 6). |
| `--domain`, `--port`, `--yes`, `--skip-check` | Options of `./install.sh`. See the table in “What the installer does”. |

The check of the files gives this protection:

- It finds a file changed or damaged on the way (a proxy, a mirror, a cache), and a tag moved after the release.
- With the signature verified, only the workflow `image.yml` of the public repository, for this tag, can make the
  list. Each signature is in the public transparency log of Sigstore.
- It does not protect against a person who can change the repository and run its workflow.
- It does not check `get.sh` itself (see “Read the script before you run it”), or the signature of the image (see
  “Verify the image”).

The versions published before these lists (1.0.0 and 1.0.1) have none: the command refuses them. Just after a
publication, the list can be missing for up to an hour: try again later.

### Read the script before you run it

If your security rules do not allow a script to run as soon as it is downloaded, do these steps:

1. Download the script: `curl -fsSLO https://github.com/Probant-Reporting/probant/raw/main/get.sh`.
2. Read it: `less get.sh`. The script is short, and comments explain each step. Outside the folder of the
   installation, it changes only two things: Docker, if you accept to install it, and the timer of the automatic
   updates (unless you add `--auto-update off`).
3. Run it, with the same options as the command: `sudo sh get.sh` (or `sudo sh get.sh --domain reporting.example.com`).

The script then runs `install.sh` of the version. Before, you can read `install.sh` and `update.sh` in the public
repository, at the tag of the version (`vX.Y.Z`).

To verify the script before you run it, download it from the tag of the version, with the list of the SHA-256 sums
of the release. Replace `X.Y.Z` with the version (the latest one is on
https://github.com/Probant-Reporting/probant/releases/latest):

```bash
curl -fsSLO https://github.com/Probant-Reporting/probant/raw/refs/tags/vX.Y.Z/get.sh
curl -fsSLO https://github.com/Probant-Reporting/probant/releases/download/vX.Y.Z/probant-X.Y.Z-files.sha256
curl -fsSLO https://github.com/Probant-Reporting/probant/releases/download/vX.Y.Z/probant-X.Y.Z-files.sha256.sigstore.json
sha256sum -c --ignore-missing probant-X.Y.Z-files.sha256
```

The last command shows `get.sh: OK`. To verify the list itself, use cosign version 3 or later. If the signature is
correct, cosign shows `Verified OK`:

```bash
cosign verify-blob probant-X.Y.Z-files.sha256 \
  --bundle probant-X.Y.Z-files.sha256.sigstore.json \
  --certificate-identity https://github.com/Probant-Reporting/probant/.github/workflows/image.yml@refs/tags/vX.Y.Z \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

Then run `sudo sh get.sh --version X.Y.Z`, with the same options as the command.

### What the installer does

The installer is `./install.sh`. It does these steps, in this order:

1. For a new installation, it checks the server (see “Check the server before you install”). If a point is to fix,
   it stops and installs nothing.
2. It checks that Docker responds. If Docker is missing, it offers to install it (see “Install Docker on Debian or
   Ubuntu”).
3. It creates the `.env` settings file from `.env.example`. It does not replace an existing `.env` file.
4. It gets the image: it downloads the published image if `IMAGE` is set in `.env`, or else it builds the image.
5. It starts the tool and waits for it to respond.
6. It shows the address to open.

This table shows the options of `./install.sh`:

| Option | Effect |
|---|---|
| No option | The tool opens over HTTP at `http://SERVER-ADDRESS:8000`. Use it for an internal network or a trial. |
| `--domain reporting.example.com` | The tool opens over HTTPS. The installer adds Caddy, the HTTPS proxy provided, in front of the tool. Caddy gets the certificate from Let's Encrypt automatically. Port 8000 is then open only to the server itself. |
| `--port 8080` | The tool uses another HTTP port. |
| `--image ghcr.io/probant-reporting/probant:X.Y.Z` | The tool uses this published image (the setting `IMAGE` in `.env`). The server downloads it and does not build it. |
| `--yes` | If Docker is missing, the installer installs it without the question. |
| `--check` | Only checks the server, with the other options, and installs nothing. |
| `--skip-check` | Installs without the check of the server. |
| `--offline probant-image-X.Y.Z.tar.gz` | Installs without Internet access, with the image of the offline package. See “Install without Internet access”. |
| `--cert FILE --key FILE` | With `--domain`: Caddy serves the HTTPS certificate of your company, and never contacts Let's Encrypt. On an installation that runs: renews the certificate. See “Company network”. |
| `--ca-cert FILE` | Adds a certificate authority of your company for the outgoing connections of the tool. Repeat the option for several authorities. See “Company network”. |
| `--auto-update on` or `off` | Sets up or removes the timer of the automatic updates, with a published image only. `--auto-update-time HH:MM` chooses its time (04:00 by default). See “Automatic updates” (section 6). |

### Install with Git

Use this way to install the tool from the code, for example to follow the repository with `git pull`.

To install the tool with Git:

1. Get the code and go to its folder:

   ```bash
   git clone https://github.com/Probant-Reporting/probant.git probant
   cd probant
   ```

2. Run the installer:

   ```bash
   ./install.sh                      # or: ./install.sh --domain reporting.example.com
   ```

   The server builds the image. For this, it downloads the base image from Docker Hub and the Python packages from
   PyPI. To use the published image instead, add `--image ghcr.io/probant-reporting/probant:X.Y.Z`, with the version
   of the code.

### Install without the script

To do the same installation by hand, in the folder of the code (see “Install with Git”):

1. Create the settings file: `cp .env.example .env`.
2. Open the file (`nano .env`) and set at least `DOMAIN`.
3. Build and start the tool: `docker compose up -d --build`.

### Verify the image

This part is optional. It is for an installation that uses the published image (`IMAGE` in `.env`, see section 4).
The installation and `./update.sh` do not verify the signature of the image: do it yourself here if your security
rules ask for it. The automatic updates verify it before each installation (section 6).

Each image, from version 1.1.0, has these three items (the images of versions 1.0.0 and 1.0.1 have none):

| Item | What it is | Where to find it |
|---|---|---|
| Signature | Proof that the image comes from the workflow `image.yml` of the repository `Probant-Reporting/probant`, for the tag of the version. It is made with cosign, without a key: the certificate names the workflow and the tag. | In the registry, next to the image |
| SBOM (software bill of materials) | The list of the components of the image (system packages and Python libraries), in SPDX JSON. It is also attached to the image as a signed attestation. | Release of the version: `probant-<version>-sbom.spdx.json` |
| Vulnerability report | The known vulnerabilities of those components on the day of the build, made by Grype. A text table and a JSON file. | Release of the version: `probant-<version>-vulnerabilities.txt` and `.json` |

The release page is `https://github.com/Probant-Reporting/probant/releases`. If a file is not in the release, it is
in the artifact `probant-image-reports` of the “Docker image” run of the tag (**Actions** tab).

To verify the signature of an image:

1. Install cosign version 3 or later (https://docs.sigstore.dev/cosign/system_config/installation/).
2. Run this command. Replace `X.Y.Z` with the version (for example, `1.1.0`), in the image and in the tag:

   ```bash
   cosign verify ghcr.io/probant-reporting/probant:X.Y.Z \
     --certificate-identity https://github.com/Probant-Reporting/probant/.github/workflows/image.yml@refs/tags/vX.Y.Z \
     --certificate-oidc-issuer https://token.actions.githubusercontent.com
   ```

   If the signature is correct, cosign lists the checks that it made, then shows the signature with the digest of
   the image (`sha256:…`). If not, cosign shows an error and stops. In that case, do not use the image, and report
   the problem (see `SECURITY.md`).

3. Optional: to be sure that the server runs exactly the verified image, set `IMAGE` to that digest. For example:
   `IMAGE=ghcr.io/probant-reporting/probant@sha256:…`.

To get the SBOM from the image and verify its attestation in the same step, run this command:

```bash
cosign verify-attestation --type spdxjson ghcr.io/probant-reporting/probant:X.Y.Z \
  --certificate-identity https://github.com/Probant-Reporting/probant/.github/workflows/image.yml@refs/tags/vX.Y.Z \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  | jq -r '.payload' | base64 -d | jq '.predicate' > probant-sbom.spdx.json
```

To read the vulnerability report:

- Open `probant-<version>-vulnerabilities.txt`. Each line is one known vulnerability of one component: the name of
  the component, the installed version, the version that corrects the vulnerability (empty if there is no correction
  yet), the identifier (CVE or GHSA), and the severity (Critical, High, Medium, Low, Negligible).
- Most lines are system packages of the base image (`python:3.12-slim`). Many have no correction yet, or concern a
  function that the tool does not use.
- The report gives information only: a vulnerability does not stop the publication of the image. A correction of a
  component comes with the next version of the image.
- The report shows the state on the day of the build. To check again later with the vulnerabilities known today, scan
  the SBOM. For example, with Grype: `grype sbom:probant-<version>-sbom.spdx.json`.
- The JSON file has the same content, for a security tool of your organisation.

### Install without Internet access

Use this way for a server that cannot reach the Internet. Each version, from 1.1.0, has an offline package:
the image of the tool and the files that install and update it, in one file. Nothing is downloaded during the
installation. There are no automatic updates: to update, use the package of the new version (see “Update without
Internet access”, section 6).

This table shows the files of the offline package, on the release page of the version
(`https://github.com/Probant-Reporting/probant/releases`):

| File | What it is |
|---|---|
| `probant-X.Y.Z-offline.tar` | The package: a folder `probant` with the archive of the image (`probant-image-X.Y.Z.tar.gz`), the archive of the image of Caddy (`caddy-image.tar.gz`, for HTTPS), `docker-compose.yml`, `.env.example`, `install.sh`, `update.sh`, `check.sh`, `docker/Caddyfile`, `VERSION`, and `SHA256SUMS` (the SHA-256 sum of each file) |
| `probant-X.Y.Z-offline.tar.sha256` | The SHA-256 sum of the package |
| `probant-X.Y.Z-offline.tar.sigstore.json` | The signature of the package (cosign bundle). It contains everything that cosign needs to verify the package without network. |

Without Internet access, you can use:

- The tool, with its SQLite database (the default). The package holds the image of the tool and the image of Caddy.
  It does not hold the image of PostgreSQL (`postgres` profile): see “PostgreSQL without Internet access” below.
- HTTP on the internal network (`http://SERVER-ADDRESS:8000`).
- HTTPS with the proxy of your company in front of the tool: the proxy has the certificate and sends the requests to
  TCP 8000 of the server, with the headers `X-Forwarded-Proto` and `X-Forwarded-For`. Set `DJANGO_HTTPS=1` and
  `DOMAIN` in `.env` (section 4), then run `docker compose up -d`.
- HTTPS with Caddy and the certificate of your company: add `--domain`, `--cert` and `--key` to the command of step 7
  (see “Company network”).

Without Internet access, there is no automatic certificate: the installer refuses `--offline` with `--domain` alone.

To install the tool without Internet access:

1. On a computer with Internet access, download the three files of the version from the release page.
2. On this computer, verify the package:
   - The sum: `sha256sum -c probant-X.Y.Z-offline.tar.sha256`. The command shows `OK`.
   - The signature, with cosign version 3 or later. Replace `X.Y.Z` with the version, in the file names and in the tag:

     ```bash
     cosign verify-blob probant-X.Y.Z-offline.tar \
       --bundle probant-X.Y.Z-offline.tar.sigstore.json \
       --certificate-identity https://github.com/Probant-Reporting/probant/.github/workflows/image.yml@refs/tags/vX.Y.Z \
       --certificate-oidc-issuer https://token.actions.githubusercontent.com
     ```

     If the signature is correct, cosign shows `Verified OK`. If not, do not use the package, and report the problem
     (see `SECURITY.md`).
3. Optional: to verify the signature on a computer without Internet access too, cosign needs the trusted root of
   Sigstore. On the computer with Internet access, after one use of cosign (or `cosign initialize`), find it with
   `find ~/.sigstore -name '*trusted_root.json'`, and copy it with the package. Then add
   `--trusted-root <that file>` to the command of step 2.
4. Install Docker Engine and its Compose plugin on the server, from the package mirror of your company. Without
   Internet access, the installer cannot install Docker.
5. Copy `probant-X.Y.Z-offline.tar` to the server, in the folder where you want the folder of the tool.
6. Extract the package and go to its folder:

   ```bash
   tar -xf probant-X.Y.Z-offline.tar
   cd probant
   ```

7. Run the installer with the archive of the image. Add `--port 8080` for another port:

   ```bash
   ./install.sh --offline probant-image-X.Y.Z.tar.gz
   ```

The installer does these steps, in this order:

1. It checks each file of the folder against `SHA256SUMS`. If a file is damaged or changed, it stops and changes
   nothing.
2. It checks the server (see “Check the server before you install”), without the network checks.
3. It creates the `.env` file, loads the image into Docker (`docker load`), and sets `IMAGE` in `.env` to the name of
   this image.
4. It starts the tool without any download, and waits for it to respond.

After the installation, the folder still contains the archive of the image. You can delete it when the tool works:
Docker keeps the image.

#### PostgreSQL without Internet access

The package does not hold the image of PostgreSQL. To use the `postgres` profile (section 8) without Internet access,
bring the image yourself:

1. On a computer with Internet access, save the image named in `docker-compose.yml` (service `db`):

   ```bash
   docker pull postgres:16
   docker save postgres:16 | gzip > postgres-16.tar.gz
   ```

2. Copy `postgres-16.tar.gz` to the server, then load it: `docker load -i postgres-16.tar.gz`.
3. Set the `postgres` profile and `DATABASE_URL` in `.env` (section 8), then run `docker compose up -d --pull never`.

### Company network

This part is optional. It is for a server on the network of a company, with one or more of these items: a
certificate that your company gives for the HTTPS address, a certificate authority of your company (the certificate
that signs its internal certificates) for the outgoing connections, and a proxy. If your network uses none of them,
skip this part.

The files of this part go into the folder `certificates/` of the installation, next to `.env`:

| Folder | Content | Who reads it |
|---|---|---|
| `certificates/https/` | `certificate.pem` and `key.pem`: the HTTPS certificate of your company and its private key (key in mode `0600`, folder in mode `0700`) | Caddy only. The container of the tool never receives the key, so a backup of the tool never contains it. |
| `certificates/ca/` | The certificate authorities of your company (`.pem`, `.crt` or `.cer` files, mode `0644`) | The tool, read only |

Keep the original files where your company keeps its certificates: the backups of the tool do not contain them.

#### Use the HTTPS certificate of your company

Caddy can serve a certificate that your company gives, instead of the automatic certificate. Use it for an address
that the Internet cannot reach, or when the security policy of your company asks for it. Caddy then never contacts
Let's Encrypt, and the server does not need to be reachable from the Internet.

This table shows the two files that you need, in PEM format:

| File | Content |
|---|---|
| Certificate | The certificate of the server for the domain name, then the intermediate certificates (the full chain) |
| Private key | The private key of this certificate, without a password |

To install the tool with this certificate:

```bash
./install.sh --domain reporting.example.com --cert reporting.pem --key reporting.key
```

With the installation with one command, add the same options after `sh -s --`. Without Internet access, add
`--offline probant-image-X.Y.Z.tar.gz`: the installer loads the image of Caddy from the package.

Before any change, the installer checks the files (with `check.sh`, which needs the `openssl` command). This table
shows the checks:

| Check | If it fails |
|---|---|
| The private key matches the certificate | To fix: the installer stops |
| The certificate covers the domain name | To fix: the installer stops |
| The certificate has not expired | To fix: the installer stops. Less than 30 days left: a warning only |
| The chain is complete, up to an authority of the system or of your company (`--ca-cert`) | A warning only: some browsers refuse an incomplete chain |

With the certificate of your company, a domain name that this server cannot find in the DNS gives a warning only:
the people who open the tool need the name, not Caddy.

To renew or replace the certificate, run this command in the folder of the installation:

```bash
./install.sh --cert new-certificate.pem --key new-key.key
```

The command checks the new files, puts them in place, and reloads the certificate in Caddy, without a break and
without a download (also without Internet access). The same command changes an installation that uses the automatic
certificate to the certificate of your company. To check new files before you renew, without any change:
`sh check.sh --certificate-only --domain reporting.example.com --cert new-certificate.pem --key new-key.key`.

To replace the files by hand: copy them to `certificates/https/certificate.pem` and `certificates/https/key.pem`, then
run `docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile --force`. To go back to the automatic
certificate: empty `HTTPS_CERTIFICATE=` in `.env`, then run `docker compose up -d`.

#### Trust the certificate authority of your company

A connection of the tool to a server that has a certificate of an internal authority fails until the tool trusts that
authority. For example: the email server of your company, or a proxy that inspects the HTTPS traffic. The error says
“certificate verify failed”.

To add the authority, give its certificate (PEM format) to the installer. Repeat the option for several authorities:

```bash
./install.sh --ca-cert company-root-ca.pem
```

On an installation that runs, the same command adds the authority and restarts the tool. At each start, the tool joins
the authorities of `certificates/ca/` with those of the system in one file, `/data/ca-bundle.pem`. Every outgoing
connection of the tool uses this file: the email server (STARTTLS and SSL), the AI assistant, and every other HTTPS
connection. The public authorities stay trusted.

The tool uses only the certificate of an authority. A file that it cannot read, that holds no certificate, or that
holds a server certificate, is written in the log at the start (`docker compose logs web`) and ignored: the tool
starts all the same. **Administration › Settings › Health** shows the authorities in use, with their expiry dates,
to the space managers and to the administrators of the main space. The line becomes “To check” 30 days before an
authority expires.

To remove an authority, delete its file from `certificates/ca/`, then run `docker compose restart web`.

Without Docker (managed hosting, or `python manage.py runserver`), set `EXTRA_CA_CERTS` to the file, or to the folder
of the files. Separate several with `:`. The data folder must be writable: the tool writes `ca-bundle.pem` there. With
Python 3.13 or later, the certificates must have the key identifiers that RFC 5280 asks for.

The check of the server uses the authority too: `sh check.sh --ca-cert company-root-ca.pem` (the installer gives it
the options). The authorities of `certificates/ca/` of an installation are read without the option.

Docker downloads the images itself, outside the tool. Behind a proxy that inspects the traffic, the Docker service must
trust the authority too: on Debian and Ubuntu, copy it to `/usr/local/share/ca-certificates/` with the extension
`.crt`, then run `sudo update-ca-certificates` and `sudo systemctl restart docker`
(https://docs.docker.com/engine/network/ca-certs/). An image built on the server (“Install with Git”) also downloads
Python packages during the build: behind such a proxy, use the published image or the offline package.

#### Use a proxy for the outgoing connections

The tool can use a proxy for its outgoing HTTPS connections. This table shows what to set:

| What | How |
|---|---|
| Outgoing HTTPS of the tool (AI assistant, and the other HTTPS connections) | `HTTPS_PROXY=http://proxy.example.com:3128` in `.env`, and `NO_PROXY` for the addresses to reach directly. Then run `docker compose up -d`. |
| Email server | The SMTP connection does not use the proxy: open the SMTP port from the server to the email server. |
| Check of the server | `sudo HTTPS_PROXY=http://proxy.example.com:3128 sh check.sh …` (see “Check the server before you install”) |
| Downloads of Docker | The proxy of the Docker service: https://docs.docker.com/engine/daemon/proxy/ |
| Proxy that inspects the HTTPS traffic | Give its authority with `--ca-cert` (see above) |

## 3. Set up the tool on first launch

When you first open the tool, it has no account yet. The **Setup** wizard opens in place of the sign-in page. It has
8 steps.

> **Important: create the administrator account right away.** Until step 1 is done, the first person who opens the
> address of the tool creates the administrator account. After step 1, the wizard opens only for that account.

The tool asks for no installation code. As long as nothing is created, the tool holds no sensitive data. What
protects it is the order of the steps: you create the administrator account right after the installation, and
before you share the address.

To set up the tool:

1. Right after the installation (or deployment), open the address of the tool. The **Setup** wizard opens. To look at
   the demo instead, load it now, before step 1: see “Start empty, or with the demo”.
2. Complete step 1, **Administrator account**, before you share the address.
3. Complete the other steps, or give the address to the person who does the setup.

If step 1 has to wait, keep the tool unreachable from the Internet until then. For example, do not set the domain
name yet.

This table shows the 8 steps of the wizard:

| Step | Name | What you set |
|---|---|---|
| 1 | **Administrator account** | The account of the administrator |
| 2 | **Your organisation** | The name, logo, and colours of the tool |
| 3 | **Languages** | The default language and the content languages |
| 4 | **Organisation** | The levels of the tree and the organisations |
| 5 | **Frameworks** | The KPI frameworks: the KPIs to collect |
| 6 | **KPI sheet** | Description categories, units, types, and fields |
| 7 | **Team** | The accounts of contributors and validators |
| 8 | **First campaign** | The period, the dates, and the opening of data entry |

You can stop and continue later. The person who does the setup does not need the IT team, except for emails
(section 7).

The account of step 1 is also the first **space manager**. Only the space managers change the settings of the whole
installation: the email server, the email alerts, the automatic updates, the external copy of the backups, and the
company sign-in. The other administrators cannot change them. See [docs/spaces.md](spaces.md).

![First launch: the wizard opens on the administrator account](screenshots/en/setup-admin-account.png)

![Step 5: choose a framework from the library, compose it or import your own](screenshots/en/setup-frameworks.png)

![Step 8: the first campaign, current period suggested](screenshots/en/setup-campaign.png)

After the setup, each person signs in with their email address. The **Dashboard** shows the progress of the
collection:

![Sign-in page](screenshots/en/login.png)

![Dashboard](screenshots/en/dashboard.png)

Data entry also works on a phone:

![Data entry on a phone](screenshots/en/entry-phone.png)

### Start empty, or with the demo

A new installation is empty: you set up your own structure with the wizard. This is the way to start for real.

To look at the tool first, you can load the demo instead: Exemplia, a fictitious company, with its organisations,
its KPIs and three reporting years. Do it before step 1 of the wizard, on the empty database:

```bash
docker compose exec web python manage.py load_demo
```

The command shows the demo accounts and their password.

> **Important:** the password of the demo accounts is public. Load the demo only on an installation that you use for
> an evaluation, and do not leave it open to the internet. The command refuses a database that already holds your
> data. To start for real afterwards, delete the evaluation and its data (`docker compose down -v`), then install
> again: the tool starts empty.

### Have the translated texts proofread

The interface exists in French, English, Spanish, German, Italian, Dutch, and Portuguese. An AI translated the texts
that are not in French or English. Before you open a language to users, ask a person in the company who speaks it to
proofread its texts. The texts are in the files `libelles/*.<code>.json` of the public repository (for example
`libelles/*.es.json`). The person needs no technical skills: they only read the texts.

## 4. Change the settings (`.env` file)

The settings are in the `.env` file. The `.env.example` file explains each line. To apply a change, run
`docker compose up -d`. A setting with no value keeps its default value.

The tool still accepts the former French names of the settings (`DOMAINE`, `PORT_HTTP`, `SMTP_HOTE`…). They can be in
older `.env` files. Use the names in the table that follows.

This table shows each setting, its default value, and what it does:

| Setting | Default | Purpose |
|---|---|---|
| `DOMAIN` | IP address of the server (set by the installer) | The domain name or address that people use to open the tool. Separate several values with commas. The tool refuses any other address (error 400). |
| `DJANGO_HTTPS` | `0` | Set to `1` behind Caddy or another HTTPS proxy. This turns on secure cookies, redirection to HTTPS, and HSTS. |
| `HTTP_PORT` | `8000` | The port of the tool. To expose it only to the proxy, write `127.0.0.1:8000`. |
| `COMPOSE_PROFILES` | Empty | `https` adds Caddy. `postgres` adds PostgreSQL. For both, write `https,postgres`. |
| `DATABASE_URL` | Empty (SQLite) | The address of the PostgreSQL database. See section 8. |
| `DJANGO_SECRET_KEY` | Generated | The key that encrypts the sessions, signs the backups, and encrypts the secrets saved in the tool (password of the email server, secrets of the external copy, client secret of company sign-in). If it is empty, the tool creates it on first startup in `/data/.secret_key`. If you change it, the tool no longer accepts the backups made before in **Administration › Settings › Hosting**: restore them from the command line with `--unsigned`. The secrets saved in the tool must then be entered again. |
| `DJANGO_HSTS_SECONDS`, `DJANGO_HSTS_SUBDOMAINS`, `DJANGO_HSTS_PRELOAD` | 1 year, `1`, `0` | The HSTS settings. They apply when `DJANGO_HTTPS=1`. |
| `CONTENT_SECURITY_POLICY_MODE` | `enforce` | The content security policy of the pages. `enforce` blocks what the policy does not allow. `report-only` blocks nothing: the browser only reports, in its console, what it would block. See “Security, already active” below. |
| `SMTP_…` | Empty | Emails. When `SMTP_HOST` is set, these settings take priority over the email settings entered in the tool. See section 7. |
| `AI_SOCKET` | `on` | `off` turns off the optional AI assistant for the whole installation: no AI button anywhere and nothing sent, whatever the administrators set. See “AI assistant” below. |
| `DEFAULT_LANGUAGE` | `en` | The language of a new installation (interface and contents): one of the seven languages of the interface (`en`, `fr`, `es`, `de`, `it`, `nl`, `pt`). The tool reads it only when it creates the database. Afterwards, change it in **Administration › Settings › Languages**. For a French installation, set `fr` before the first start. |
| `GUIDED_TOUR` | `on` | `off` removes the short guided tour that people see at their first sign-in. The tour only changes the display. |
| `TIME_ZONE` | `Europe/Brussels` | The time zone of the installation, as a name from the IANA list, for example `Europe/Paris` or `America/New_York`. The times of the automatic reminders, of the automatic backup and of the nightly data check, "today", and the dates in the exports and in the log use this time zone. **Administration › Settings › Hosting** shows it next to the server time. If the name is unknown, the tool does not start and the log shows the error. |
| `MAX_EVIDENCE_SIZE_MB`, `MAX_IMPORT_SIZE_MB` | `5`, `10` | The maximum size, in MB, of an evidence file and of an import file. |
| `MAX_BACKUP_UPLOAD_MB` | `2048` | The maximum size, in MB, of a backup that an administrator uploads in the tool (**Hosting** › **Restore**). The tool refuses every other request larger than the larger of `MAX_EVIDENCE_SIZE_MB` and `MAX_IMPORT_SIZE_MB` (plus 1 MB) before it receives it. With the HTTPS proxy, `CADDY_MAX_SIZE` (50 MB by default) also applies: increase it to upload a larger backup. |
| `MAX_XLSX_UNCOMPRESSED_MB` | 20 × `MAX_IMPORT_SIZE_MB` | The maximum size, in MB, of an Excel file once uncompressed. The tool refuses a larger file before it opens it. A cell text longer than 32,767 characters (the limit of Excel) is also refused. The same limits apply to the import commands that you run on the server (`import_kpi`, `import_organisations`, `import_valeurs`): to import a larger file with a command, increase `MAX_XLSX_UNCOMPRESSED_MB` for that run. |
| `BACKGROUND_IMPORT_ROWS` | `5000` | A value import (**Import / Export › Import values**) with more rows than this number runs in the background. The person sees a progress bar, and can leave the page and come back. The `run_imports --schedule` process runs these imports. The image starts it automatically, so you install nothing. `0` means never: every import runs within the page, which can last 120 s at most. |
| `DISK_ALERT_MB` | `100` | When the free space on the data disk is below this value, in MB, `/sante/` answers `503` (“disk almost full”). |
| `BACKUP_AUTO`, `BACKUP_TIME`, `BACKUPS_KEEP` | `1`, `02:30`, `14` | Starting values only. After that, you set these values in the tool, in **Administration › Settings › Hosting**: automatic backup on or off, frequency (6 h, 12 h, day, week), time, and number of backups kept. |
| `DATA_CHECK_TIME` | `03:30` | The time of the nightly data check and clean-up. The check reads the database and changes nothing. The clean-up erases the expired sessions and the deleted items older than the trash delay. See section 9. |
| `GUNICORN_WORKERS`, `GUNICORN_THREADS` | 1 worker per processor (2 to 4), `4` | Server capacity. A worker uses 1 processor at a time and about 170 MB of memory. The default suits a server with 2 to 4 processors. See “Capacity” in section 8. |
| `GUNICORN_TIMEOUT`, `GUNICORN_KEEPALIVE` | `120`, `75` | The longest time for a request, in seconds, and the time that an idle connection stays open. Keep `GUNICORN_KEEPALIVE` above the idle timeout of the proxy in front of the tool. The Caddy provided closes idle connections after 60 s. If the value is lower, a save can sometimes fail with error 502. |
| `DJANGO_LOG_LEVEL` | `INFO` | The level of detail of the log (`INFO`, `WARNING`, `ERROR`). |
| `IMAGE` | Empty (image built on the server) | The published image to use, for example `ghcr.io/probant-reporting/probant:latest`. |
| `HTTPS_CERTIFICATE` | Empty (automatic certificate) | `files`: Caddy serves the certificate of your company, from `certificates/https/`, and never contacts Let's Encrypt. `./install.sh --cert --key` sets it. See “Company network” in section 2. |
| `PUBLIC_URL` | Empty | The address of the tool, for example `https://reporting.example.com`, in the emails (reminders, email alerts) and in the redirect URI of company sign-in. Empty: the emails use the first value of `DOMAIN`, and company sign-in uses the address of the page. |
| `COMPANY_SIGN_IN`, `COMPANY_SIGN_IN_TIMEOUT` | `on`, `5` | `off` turns company sign-in off for the whole installation, whatever the space managers set: the button disappears and everyone can use their password. The timeout is the longest wait, in seconds, for each call to the identity provider. See “Sign-in with a company account” below. |
| `EXTRA_CA_CERTS` | `/etc/probant/ca` in the image | Without Docker only: the file or the folder of the certificate authorities of your company, for the outgoing connections. Separate several with `:`. With Docker, put the files in `certificates/ca/` (`./install.sh --ca-cert`). See “Company network” in section 2. |

### Security, already active

With no particular setting, the tool applies these protections:

- Debug mode is turned off.
- The server is gunicorn. It runs without root rights (user 1000).
- The code of the tool in the image (`/app`) belongs to root: the tool can read it but cannot change it. The tool
  writes only in the data folder (`/data`). Files and folders there are readable by the tool only (`0600` and
  `0700`).
- The archives of a space contain no password hashes, and the tool signs each archive. The page **Hosting** restores
  only the archives of this installation, unchanged.
- WhiteNoise serves the static files, with browser caching.
- The tool sends the pages compressed.
- The tool sends the headers `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, and
  `Referrer-Policy: same-origin`.
- Each page has a content security policy (`Content-Security-Policy` header). The browser runs only the scripts and
  the styles of the tool. A script or a style that comes from elsewhere does not run, even if someone puts it in a
  text. The page loads nothing from another site, and no other site can show it in a frame. The evidence files and the
  logo keep their own, stricter policy.
- A session expires after 12 hours.
- The tool serves the evidence files only after it checks the permissions. There is never direct access to them.
- After 5 failed sign-ins for the same identifier from the same address, the tool refuses sign-in for 15 minutes.
  It does the same after 50 failed sign-ins from the same address (all identifiers), and after 20 failed sign-ins on
  the same account from all addresses (the same person in every space; an unknown identifier is counted the same way,
  so the message does not tell whether the account exists). The message is the same for each limit. The limit applies
  to the sign-in page of the tool and to expert mode (`/admin/`). It never closes a session that is already open, and
  it does not stop the tokens of AI assistants (MCP), which do not use the password. Known and accepted drawback:
  somebody who knows the identifier of a person can block the password sign-in of this person on purpose for
  15 minutes. The server log has a line for each blocking.
- In **My account**, after 5 wrong current passwords, the tool does not check the current password for 15 minutes,
  even the right one, and says so. The session stays open. This count is per person, separate from the sign-in.
  All the server processes share these counts, and they stay after a restart: the tool keeps them in the
  `sign-in-attempts/` folder of the data folder. There is nothing to set up.
- The tool reads the address of the visitor from `X-Forwarded-For` only when `DJANGO_HTTPS=1`. Caddy or the other
  HTTPS proxy must add this header.

Over HTTPS, `python manage.py check --deploy` reports no warning.

If a screen does not work after an update (a button does nothing, a page has no colors), the content security policy
can be the cause. To find out:

1. In the `.env` file, set `CONTENT_SECURITY_POLICY_MODE=report-only`.
2. Restart the tool: `docker compose up -d`.
3. Open the screen again. If it works now, open the console of the browser (F12): each line that starts with
   `[Report Only]` names what the policy would block. Send these lines with the version of the tool.
4. When a corrected version is installed, remove the line or set `CONTENT_SECURITY_POLICY_MODE=enforce`, and restart.

With `report-only`, the protection is off: keep this value only for the time of the check.

### AI assistants (MCP): nothing to do

A person can connect their own AI assistant to the tool, with the Model Context Protocol (MCP). The assistant then
reads and changes data with the rights of this person. The MCP server is part of the tool, at the address `/mcp/` of each
space (`/espace/<code>/mcp/` for another space). It runs in the same container, on the same port, behind the same
HTTPS: there is no service, no port, no variable and nothing to install. It stays off until an administrator turns it
on in **Administration › Settings › Assistants**. The only condition is that the reverse proxy passes the
`Authorization` header to the tool: Caddy (the `https` profile) and Clever Cloud do it without any setting. Assistant
tokens are never in the backups. The log of the tool shows the refused tokens (`serveur_mcp: MCP: token refused`).
Details: [`docs/mcp.md`](mcp.md), section 7.

### AI assistant (optional)

This is a different function: here, the tool itself calls an AI provider (Claude, by Anthropic). The tool asks it for
proposals: explain a consistency alert, match the KPIs of a former file, translate labels. It is **off** in every
space. An administrator of the space turns it on in **Administration › Settings › AI assistant**, with the API key of
your organisation's own account at the provider. The page lists exactly what each use sends. Full description:
`docs/ai_socket.md`.

What IT does:

| Item | Value |
|---|---|
| Network | Allow outgoing HTTPS (TCP 443) from the server to `api.anthropic.com`. Nothing comes in. |
| Proxy | If the server goes out through a proxy, set `HTTPS_PROXY=http://proxy:port` in `.env`. |
| Key | Nothing to do: the administrator enters it in the tool. The tool keeps it in `ai-keys/` in the data folder, readable by the tool only, never in the database and never in a backup. After a restore on another server, the administrator enters it again. |
| Forbid it | `AI_SOCKET=off` in `.env`, then `docker compose up -d`. |

While the assistant is off in a space, the tool opens no connection to the provider.

### Sign-in with a company account

People can sign in with their company account (single sign-on, OpenID Connect). It is off by default. A space
manager sets it up in **Administration › Settings › Company sign-in**. What IT does:

| Item | Value |
|---|---|
| Network | Allow outgoing HTTPS (TCP 443) from the server to the identity provider. Nothing comes in. |
| Address | Set `PUBLIC_URL` in `.env`: the tool builds the redirect URI from it. |
| Rescue | If no space manager can sign in, set `COMPANY_SIGN_IN=off` in `.env`, then run `docker compose up -d`. Everyone can use their password again. |

Details: [`docs/single_sign_on.md`](single_sign_on.md).

## 5. Back up and restore

### What the `/data` volume contains

The tool organises this folder itself and writes a `README.txt` file in it:

- Databases and key: at the root
- Documents added to the tool: in `files/` (`evidence/<period>/<organisation>/<KPI>/`, `settings/logo/`,
  `pending-imports/`)
- Archives: in `backups/`
- Other spaces: in `spaces-data/<code>/`

Do not move anything in this folder by hand. For details, see [`docs/file_layout.md`](file_layout.md).

Only the user of the tool can read what is in this folder: the tool creates files with mode `0600` and folders with
mode `0700`, also when you run a command with `docker compose exec`. At each start, it removes the rights of the group
and of the others from the files that an older version made.

### What a backup contains

A backup is a dated `.zip` archive in `/data/backups`. It contains:

- The complete database: accounts, frameworks, campaigns, values, history, and the sign-in history of the last days
  (Administration › Settings › Hosting sets how many)
- The files added to the tool: evidence files and logo
- A description: the version of the tool and the number of rows per table

The archive contains confidential data. Keep it in a safe place.

The archive of a space contains no passwords, not even their hashes. An administrator of the space can download it, so
the tool removes the hashes from it. The passwords stay in the shared account registry, which has its own backups in
`/data/backups/shared/`. Only IT can reach these backups: the tool never lists them and never lets anyone download
them. They contain the password hashes. Keep them in a safe place and copy them with the other backups.

> **Note:** Archives made by an earlier version of the tool can still contain the password hashes. This includes the archives that
> administrators downloaded and the copies that IT made off the server. Delete them when you no longer need them, or
> keep them in a place that only IT can open.

### Back up the tool

This table shows how to back up the tool:

| To… | Do |
|---|---|
| Back up automatically | Nothing. By default, the tool makes a backup every day at 02:30 and keeps 14 archives. An administrator sets the frequency in **Administration › Settings › Hosting**. |
| Back up now | Run `docker compose exec web python manage.py backup`. An administrator can also click **Create and download a backup** in **Administration › Settings › Hosting**. |
| List the backups | Run `docker compose exec web python manage.py backup --list`. |
| Copy the backups outside the server | **To do by IT**: by default, the backups stay on the same server as the tool. Copy them in the tool, or by your own means: see [Copy the backups outside the server](#copy-the-backups-outside-the-server). |

**Without Docker**, schedule the same backup with cron: `30 2 * * * cd /opt/reporting && python manage.py backup`.

![Administration › Settings › Hosting: version, backups, test email](screenshots/en/hosting.png)

### Copy the backups outside the server

The backups stay in the `/data` volume, on the same server as the tool. If the server is lost, they are lost too. Copy
them outside the server in one of these two ways. Both ways can run together.

#### In the tool

This copy is off until a space manager sets it up. The tool can then copy each backup itself to a storage that IT
provides. A space manager sets it in
**Administration › Settings › Hosting**, box **Copy outside the server**, with **Set up a copy outside the server**:

- **S3-compatible object storage**: a bucket at a provider, or MinIO on your network. Give the address of the service
  (`https://…`; `http://` is accepted only for an address of the internal network), the region, the bucket, an
  optional folder in the bucket, the access key ID and the secret access key. The address style is automatic; choose
  "path" or "virtual host" only if the provider asks for it.
- **SFTP server**: a server or a NAS. Give the server, the port, the username, a password or a private key (OpenSSH or
  PEM format, without a passphrase, made for this copy only), and the folder.

![Administration › Settings › Hosting › Copy outside the server: status of the copy and S3 destination](screenshots/en/hosting-external-copy.png)

Then click **Test the destination**. The tool writes a small test file, reads it back, and deletes it. With SFTP, the
first test shows the SHA-256 fingerprint of the key of the server. Compare it with the fingerprint that the server
gives (on the server: `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`), then click **Confirm this key**. After that,
the tool refuses any other key, before it sends the password or the key. If the server changes its key, the copy stops
and sends an alert, until a space manager confirms the new key.

What the tool does next:

- It copies each new archive of each space **and** each archive of the shared account registry (`backups/shared/`),
  within a minute after the backup. The background task of the backups does it (`backup --schedule`), never a page of
  the tool. To copy at once: `docker compose exec web python manage.py backup --copy`.
- At the destination, it keeps the layout of the `backups` folder, in a folder named after the identifier of the
  installation: `<folder or prefix>/<identifier>/backup-….zip` (main space), `…/spaces/<code>/backup-….zip` (other
  spaces), `…/shared/registry-….zip` (registry).
- If a copy fails (network, rights, full storage…), it tries again later (after 5 minutes, then 15 minutes, up to
  6 hours) and copies everything that waits. **Settings › Health** and `/sante/` (`external_copy`) show the last copy
  and the archives that wait; an email alert leaves if the alerts are on (section 9).
- By default, it **deletes nothing** at the destination. If a space manager sets **Copies kept per space**, the tool
  keeps that number of the most recent copies of each space and of the registry, and deletes only the older archives
  that it made itself (folder and name that it recognises). It never deletes another file, and never the last archive
  made. To keep the copies safe from deletion, give the account the right to write but not to delete, and keep `0`.
- S3: the service checks the SHA-256 checksum of each part that the tool sends; after the upload, the tool reads the
  size and the checksum again. A large archive goes in parts of 16 MB. SFTP: the tool writes a hidden `.part` file, then
  renames it, and checks the size.

> **Warning:** The copies contain all the data of the tool, the password hashes (backups of the registry), and the
> secrets saved in the tool, encrypted with the secret key of the installation. Use a private destination that only IT
> can open. The tool does not encrypt the archives.

The tool saves the secret key of S3, and the password or the private key of SFTP, encrypted with the secret key of the
installation. It never shows them again. After a restore on another server, a space manager enters them again.
To keep them, leave the fields empty when you save. If you change the destination (S3: address, region, bucket or
access key ID; SFTP: server, port or username), the tool asks for the secret again, so that it never goes to another
destination. With SFTP, a new server or port also forgets the confirmed key of the server.

The connection uses the certificate authorities of the system and those that IT adds (`certificates/ca/`, see
[Trust the certificate authority of your company](#trust-the-certificate-authority-of-your-company)). With
`HTTPS_PROXY`, a public S3 service is reached through the proxy; an address of the internal network is reached
directly. SFTP needs a direct connection. The tool never connects to the server itself, to a link-local address
(cloud metadata), or to a reserved address.

The all-in-one version (Windows or Mac) does not have this function: copy the backups folder yourself.

#### By your own means

To copy the `/data/backups` folder with your usual backup tool, do these steps:

1. Copy the archives out of the container: `docker compose cp web:/data/backups/. ../probant-backups/`. This copies
   the archives, subfolders included, to the folder `probant-backups` next to the folder of the tool. Do not copy
   them into the folder of the tool: the update builds the image from this folder.
2. Copy `probant-backups` outside the server with your usual backup tool (rsync, Veeam…), on a schedule.

The copied files keep their rights: only the account that ran `docker compose cp` can read them (files `0600`,
folders `0700`). If your backup tool runs under another account, give this account access to `probant-backups`, for
example with `chown -R`. Do not change the rights inside the volume.

### Rebuild a server from the external copy

If the server is lost, IT rebuilds the installation on a new server from the copy alone:

1. Install the tool on the new server (section 2), with the same version or a more recent one. Do not create an
   account.
2. Get the folder named after the identifier of the installation from the destination (S3 or SFTP tool of your
   choice), and copy its content, subfolders included, into the backups folder of the new server:
   `docker compose cp ./<identifier>/. web:/data/backups/`.
3. Restore the most recent backup of the shared registry, then the most recent backup of the main space, then the most
   recent backup of each other space:

   ```bash
   docker compose exec web python manage.py restore --shared registry-YYYYMMDD-HHMMSS-auto.zip --yes
   docker compose exec web python manage.py restore --unsigned backup-YYYYMMDD-HHMMSS-auto.zip --yes
   docker compose exec -e SPACE=<code> web python manage.py restore --unsigned backup-YYYYMMDD-HHMMSS-auto.zip --yes
   docker compose restart web
   ```

   The archives were signed by the old server: `--unsigned` is needed, unless you put back the old secret key
   (`/data/.secret_key` or `DJANGO_SECRET_KEY`).
4. People sign in with their usual password. A space manager enters the secrets again: the password of the email
   server, and the secret of the external copy. Only the secret key of the old server can read them. If you kept that
   key in a safe place and put it back before step 3, they work at once.

If you have only the backup of a space, and not the backup of the shared registry, a space manager can also restore it
from the tool, on the new server: see [Restore a backup from another installation](#restore-a-backup-from-another-installation).
The passwords do not move in this case: only the person who restores keeps theirs.

### Backups and deleted evidence

An administrator can delete the evidence files of sensitive KPIs in **Administration › Evidence to delete**. The tool deletes the file at once. A backup keeps the evidence files that existed when it was made. So the backups that already exist keep the file until the tool replaces them.

- The number of backups kept sets how long a deleted file stays. With the default values (one backup a day, 14 kept), it stays up to 14 days. If the data is very sensitive, lower the number in **Administration › Settings › Hosting**.
- A restore brings the deleted file back, and it appears again in **Evidence to delete**. After a restore, the administrator deletes it again.
- The copies that you make off the server also keep the file. Delete the old copies on a schedule that matches how long you may keep sensitive data, and tell the administrators how long the copies last.

### Restore a backup

A restore does these steps:

1. It asks for confirmation.
2. It first backs up the current state (“before-restore” archive).
3. It replaces the database and the files added to the tool.

> **Warning:** A restore replaces everything done since the date of the backup. Other people who are signed in can be
> signed out. Warn the teams, and do not restore during a data entry period.

To restore a backup from the tool:

1. Go to **Administration › Settings › Hosting**.
2. Next to the backup in the list, click **Restore…**. The confirmation page opens.

   To use a `.zip` file downloaded earlier, open **Restore from a .zip file downloaded earlier**. Choose the file,
   then click **Check the file**. The tool adds the file to the list.
3. Select the box, then enter `RESTORE`.
4. Click **Restore this backup**. The tool backs up the current state first. Then the sign-in page shows “Restore
   complete. The tool is back to the state of …”.
5. Sign in with an administrator account from the restored database.

The tool restores only the backups that it made itself, unchanged. When it makes a backup, it signs the archive with a
key that comes from the secret key of the installation (`/data/.secret_key` or `DJANGO_SECRET_KEY`). The page
refuses an archive without a valid signature, also when you add a `.zip` file: “This backup was not made by this
installation, or it was changed after it was made”. These archives have no valid signature:

- Archives made by an earlier version of the tool (before the signature existed)
- Archives made by another server, or before a change of `DJANGO_SECRET_KEY`
- Archives that someone changed after the backup

IT can still restore such an archive from the command line, if it trusts the archive: add `--unsigned` to the
`restore` command. Without this option, the command refuses the archive and changes nothing. A space manager can also
restore it from the tool: see [Restore a backup from another installation](#restore-a-backup-from-another-installation).

Every restore of an SQLite database, from the tool or from the command line, with or without `--unsigned`, refuses a
database with triggers, views, or calculated columns, or with another structure than the tool expects (columns,
constraints, indexes, and foreign keys, as SQLite reads them). The backups that the tool makes never have them. If a
restore fails after the database was replaced, the tool goes back to the “before-restore” archive by itself. Without
this archive (`--no-backup-before`, or a database that could not be read), it cannot: the restore stays marked as
interrupted, `/sante/` reports it, and IT restores an archive from the command line.

To restore an archive from the server (if the tool no longer starts):

1. Run `docker compose exec web python manage.py restore backup-20261026-023000-auto.zip`. For an archive without a
   valid signature, add `--unsigned`.
2. Run `docker compose restart web`.

To restore an archive that you downloaded:

1. Copy the archive into the backups folder: `docker compose cp archive.zip web:/data/backups/`.
2. Do the 2 steps of the previous procedure.

After a restore, people sign in with the password that the shared account registry has for them: their current
password. The archive of a space contains no passwords. If the registry does not know an account, this account has no
password after the restore. This occurs when you restore an archive on another server, or when an account was deleted
after the backup. The restore says it (“… account(s) of this space have no password on this server”). Then do one of
these:

- Restore the backup of the shared registry made at the same time, from `/data/backups/shared/`:
  `docker compose exec web python manage.py restore --shared <registry-….zip> --yes`. On a new server, copy the whole
  `backups` folder first, subfolders included.
- Give new passwords: `docker compose exec web python manage.py changepassword <username>` for one administrator.
  This administrator then gives the other accounts a temporary password in **Administration › Accounts**.

With SQLite, you can restore an archive made with an older version of the tool into a more recent version. The tool
updates the database automatically. The tool refuses the reverse. With PostgreSQL, an archive restores only with the
version of the tool that made it: see [Going back to the previous version](#going-back-to-the-previous-version) and
[Restore a PostgreSQL backup on a new server](#restore-a-postgresql-backup-on-a-new-server).

To restore a PostgreSQL archive made by an older version after an update:

1. Try the restore. The more recent version refuses the archive and says so. Nothing changes.
2. Go back to the version that made the archive (the restore shows its version, also in `backup.json`), and restore the
   archive with that version: see [Going back to the previous version](#going-back-to-the-previous-version).
3. Update the tool again with `./update.sh`. The update brings the restored data to the new version.

### Restore a backup from another installation

A space manager can restore from the tool a backup that this installation did not make: after a change of server,
after the loss of a server, or with a backup of the all-in-one version. The command line does not change.

The tool cannot check such a file, because the secret key of the other installation never leaves its server. So the
tool does not trust its content, and these rules apply:

- A backup counts as made by this installation only if its signature is valid and it names this installation and
  this space. A backup of another installation that has the same secret key (a server rebuilt with the same
  `DJANGO_SECRET_KEY`, a copied `.env`) has a valid signature, but it is from another installation: these rules apply
  to it too. A backup of another space of this installation stays for IT (`restore --other-space`).

- Only a space manager can do it. For the other administrators and the other roles, the page refuses the file, as
  before. A backup that this installation made keeps the usual checks, for everyone.
- **Empty installation.** IT installs the tool. An administrator creates their account at step 1 of the setup wizard.
  From step 2, the wizard shows **Start from a backup** while the installation is empty: main space only, one
  account, no organisation, no KPI, no campaign, no value, and the wizard is not finished. A visitor who is not signed
  in never sees it.
- **Installation in service.** In **Administration › Settings › Hosting**, open **Restore from a .zip file downloaded
  earlier**, choose the file, then click **Check the file**. The tool keeps the file apart: it is not in the list of
  backups, and the external copy does not copy it. The tool deletes it after the restore, or after one day.
- The backup goes into the current space, as with `restore --other-space`. The other spaces and the shared account
  registry do not change.

The confirmation page shows the name of the installation, the date, and the version that the file gives. It says that
the tool cannot check the file, what the backup replaces, what happens to the accounts, and the administrators of the
backup. Select the two boxes, enter `RESTORE`, then click **Restore this backup**. The tool backs up the current state
of the space first (“before-restore” archive). Then it signs you out: sign in again with your own password.

What happens to the accounts:

- You keep your account, your password, and your role of space manager. After the restore, your account is an active
  administrator of the space: the tool adds it, or gives the role back, and writes it in the history.
- The other accounts of the backup have no password. Backups never contain passwords, and the tool reads no password
  from such a file. Give them a temporary password in **Administration › Accounts**.
- An account with the same number and the same email as an account of another space of this installation is the same
  person. It keeps its password and its role in the other spaces.
- The accounts that existed only in this space, except yours, leave the shared registry: the accounts of the backup
  replace them. Their sessions and their links with a company account are deleted. A space manager among them loses
  this role.
- If an account of the backup has the number, the email, or the user name of another person who has an account in
  another space, the tool refuses the backup and changes nothing. IT can restore it from the command line.

What else changes:

- The assistant tokens (MCP) of the space stop working. Each person creates a new one.
- The automatic reminders, the AI assistant, and the assistants (MCP) of the space are off after the restore, and the
  background imports and exports that were waiting are stopped. Turn them on again on the **Reminders** page and in
  **Settings** if you need them.
- The rights of each account come from its role only: an administrator of the backup has the expert mode, no other
  account has it. The groups and permissions written in the file are not kept.
- The settings of the whole installation stay as they are: email server, external copy, email alerts, company sign-in,
  and AI key. The backup of a space contains none of them, and none of their secrets.

The tool also refuses, before it changes anything: a backup made by a more recent version, a PostgreSQL backup made
with other database migrations, an SQLite backup on PostgreSQL, a file too large for the free disk space, a file that
changed after the confirmation page, a JSON file with data that a backup of the tool never contains, and an SQLite
database with triggers, views, or calculated columns, or with another structure than the tool expects. In an SQLite
database, an extra table (left by an earlier version) is accepted: the tool does not read it. A backup made by an
earlier version is checked just after its update, before the shared account registry changes. If anything fails after
the database was replaced, the tool goes back to the state before the restore by itself, and the page says so; the
assistant tokens (MCP) of the space are then lost.

With several spaces, restore the backup of each space in its own space, the main space first. The backups of the
spaces of one installation give the same number to a person who works in several spaces, so the tool recognises this
person. The history of the restores (**Hosting** page and `restores.jsonl`) notes “other installation” and its name.
To move the passwords too, IT uses [Rebuild a server from the external copy](#rebuild-a-server-from-the-external-copy).

### If a restore is interrupted

If a restore is interrupted (server stopped, container stopped, disk full), nothing is lost:

- The tool first extracts the files of the archive to a separate place. If the disk is full, the restore stops before
  anything changes.
- Then the tool replaces the database in one step and swaps the files.
- If the restore stops after that point, the tool **finishes it automatically at the next start**. The log shows
  “the restore of …, interrupted, has been finished”. Until then, `/sante/` answers `503` (“interrupted restore”).

> **Warning:** Never copy `db.sqlite3` by hand. An old `db.sqlite3-wal` file next to it can damage it, with no error
> message. Always use `restore`.

### Back up and restore several spaces

An installation can have several spaces (departments). Each space has its own backups, in
`/data/backups/spaces/<code>/`. The shared account registry has its own backups, in `/data/backups/shared/`.
**Copy the whole of `/data/backups`, subfolders included.**

To run a command for one space, add `SPACE=<code>`. For example:
`docker compose exec -e SPACE=achats web python manage.py backup`. For details, see
[docs/spaces.md](spaces.md), § 2.

## 6. Update the tool

To update the tool:

1. Go to the folder of the tool (`probant`). For example: `cd probant`.
2. Run `./update.sh`. The script shows the new version when the update is complete.

To install a given version instead of the latest one, after an installation with one command, run
`./update.sh --version X.Y.Z`. The script refuses a version older than the installed version: to go back, see “Going
back to the previous version”.

You can update from any published version directly, without installing the versions in between. An automatic test tries it from every published version.

The script does these steps, in this order:

1. It makes a backup named “before-update” of each space, with the version that is installed now. If the backup of
   a space fails, the update stops and changes nothing.
2. It gets the new version:
   - After an installation with one command (a folder without Git, with `IMAGE` set to a version of
     `ghcr.io/probant-reporting/probant`): it downloads the files of the new version and checks them, as the
     installation does (see “Install with one command”). Then it sets `IMAGE` in `.env` to the image of this version
     and downloads it. It keeps the other settings of `.env` and the data. If a download fails, if the list of the
     sums is missing, if its signature is refused, or if one file does not match, the update stops and changes
     nothing (exit code 3 for the check of the files).
   - After an installation with Git: with `git pull`, followed by a new build of the image
   - Or, if `IMAGE` is set in `.env` to another image, with `docker compose pull`
3. It restarts the tool. The tool applies the changes to the database structure automatically at startup. If the
   database must change, the tool first makes an automatic backup.
4. It waits for the tool to respond.

At each start, the log (`docker compose logs web`) shows a short summary in English. For example:

```text
Probant, version 1.1.0 (3f2a9c1d7e4b)
Database: PostgreSQL (db/probant), 0 migration(s) applied; installation "Probant", 23 account(s)
Data: /data; backups: /data/backups (14 archive(s))
Address(es): reporting.example.com; HTTPS: yes
E-mails: SMTP smtp.example.com:587
```

When the database must change, the log shows this line and the path of the archive before the summary:
`Updating space "principal" (3 migration(s)): automatic backup before.`

The version number is shown at the bottom of every page and in **Administration › Settings › Hosting**.

Only one update runs at a time: if the automatic update runs (see “Automatic updates”), `./update.sh` stops and
changes nothing.

### Automatic updates

After an installation with one command, the automatic updates are on. A timer of the server (shown as **Task of the
server** in the tool) installs each new version at night, and goes back to the previous version if the new one does
not work. The other installations do not have them: see the table below. The script `auto-update.sh` of the folder of
the tool does all the work, on the server. The tool itself never connects to the Internet, never compares two
versions, and has no access to Docker: no Docker socket is given to its container, and no other tool (such as
Watchtower) is used.

The choice is in **Administration › Settings › Hosting**, “Automatic updates”. Only the space managers can change
it:

| Choice | Effect |
|---|---|
| Install it automatically | The server installs each new version at night. |
| Notify only | The server checks every night. The tool shows the new version, also on the page **Settings › Health** and in the email alerts if they are on. IT installs it with `./update.sh`. |
| Off | The server does not check. |
| Wait after the publication | 0, 1, 3, 7 or 14 days (3 by default). The server installs a version only when it was published this number of days ago. In the meantime, a version with a problem can be corrected. With “Notify only”, the alert comes at once. |

![Administration › Settings › Hosting, Automatic updates: task of the server, last check and choice](screenshots/en/hosting-auto-updates.png)

This table shows the setting at the start:

| Installation | Timer of the server | Choice in the tool |
|---|---|---|
| New installation with one command (`get.sh`) | Set up | Install it automatically, wait 3 days |
| Installation that already exists, updated to a version with automatic updates | Not set up: run `./install.sh --auto-update on` | Off |
| Installation with Git, without Internet access (`--offline`), or with another image | Not available | — |
| Managed hosting, all-in-one version | Not available: the screen says so | — |

#### What one run does

1. It stops at once if another update runs (the lock `.update.lock` of the folder, shared with `./update.sh`), if
   the installation does not use a published version, if the tool is stopped, or if the choice is “Off”.
2. It finds the latest published version, as `./update.sh` does, and downloads its image. If the digest of this image
   is the digest of the image that runs, there is nothing to do.
3. It verifies the signature of the new image (see “Signature of the new image”). If the signature is absent or not
   correct, or if the verification is not possible, nothing is installed.
4. It stops here in these cases:
   - The choice is “Notify only”.
   - The wait after the publication is not over.
   - The automatic update of this image failed before.
   - The version changes the shared registry of the accounts. That change cannot be undone automatically: IT
     installs this version with `./update.sh`.
5. It does not update during a restore, a backup, a large import or a large export of the tool. It tries again the
   next night.
6. It downloads the list of the SHA-256 sums of the files of this version, from its release, and verifies the
   signature of this list (see “Signature of the new image”). If the list is missing, or if its signature is not
   verified, nothing is installed. Then it runs `./update.sh` for this version, with this list and with the image
   pinned to the verified digest (`IMAGE=ghcr.io/probant-reporting/probant:X.Y.Z@sha256:…`). `./update.sh` makes the
   “before-update” backup of each space first, as always, and checks each file against the list before it puts any in
   place.
7. It checks `/sante/`, then again 30 seconds later.

If the new version does not respond, the script goes back automatically:

1. It puts back the files and the `.env` of before (kept in `.auto-update/previous/`) and the image of before (it stays
   on the server).
2. It compares the migrations of each database with the migrations of before. If the new version changed the database
   of a space, it restores the “before-update” backup of this space made by `./update.sh`, with
   `restore --rebuild` (SQLite and PostgreSQL). A space that did not change is not restored, so nothing is lost.
3. It starts the version of before and checks `/sante/`.

The screen then says “The server went back to version X.Y.Z”, and so do the page **Settings › Health** and the email
alerts. The same image is not tried again: when the cause is known, IT runs `sudo ./auto-update.sh --retry`.

If going back does not work completely (a restore fails, the shared registry changed, or the version of before does
not respond), the result is a failure. The email alert says “Call your IT team now”, and IT follows “Going back to the previous
version”. Nothing more is done automatically, not even the next nights, until IT runs `sudo ./auto-update.sh --retry`.

#### Signature of the new image

The script verifies the signature with cosign in its official container, `ghcr.io/sigstore/cosign/cosign`, pinned by
its digest in `auto-update.sh`. Docker checks this digest when it downloads the container: nothing to install by hand.
The container runs read only, without any capability, and with no folder of the server except the certificate
authorities of your company (`certificates/ca/`). The check is the same as in “Verify the image” (section 2): the image
must be signed by the workflow `image.yml` of the repository `Probant-Reporting/probant`, for the tag of this version,
with the issuer `https://token.actions.githubusercontent.com`. The signature names the digest of the image, and the
script installs exactly this digest.

The script verifies the list of the SHA-256 sums of the files of the version in the same way, with the same container
and the same identity (`cosign verify-blob`). For this check, the container reads only the folder of the list, read
only, as the user of the script. Here, a list that cannot be verified always stops the update.

#### Turn the timer on or off

In the folder of the tool, as root (`sudo`):

- `./install.sh --auto-update on` sets up the timer: every night at about 04:00, time of the server, with a random
  delay of up to 1 hour. To choose the time: `./install.sh --auto-update on --auto-update-time 01:30`. With systemd,
  the timer is `probant-auto-update-<number>.timer`. Without systemd, it is a file in `/etc/cron.d/`. Without root, it
  is a line in the crontab of the user.
- `./install.sh --auto-update off` removes the timer. Nothing else changes.

On an installation that already exists, these commands change only the timer: the choice in the tool stays the choice
of the space managers. Before you delete the folder of the tool, run `./install.sh --auto-update off`. If the folder is
already deleted, remove the timer by hand: `sudo systemctl disable --now probant-auto-update-<number>.timer`, then
delete the two files `/etc/systemd/system/probant-auto-update-<number>.*` (or the file in `/etc/cron.d/`).

#### Read the log

- `auto-update.log`, in the folder of the tool: each step of each run, and the output of `./update.sh`.
- With systemd: `journalctl -u 'probant-auto-update-*'`, and the next run: `systemctl list-timers 'probant-auto-update-*'`.
- `./auto-update.sh --status`: the last result.
- `sudo ./auto-update.sh`: one run now, the same as the timer.

The tool shows the last result in **Settings › Hosting**, and says when the timer ran for the last time. If the timer
has not run for 3 days, the page **Settings › Health** says so, and so do the email alerts if they are on.

#### Network of the server

The script needs the same outgoing HTTPS (TCP 443) as the installation, from the server, not from the container: see
“Network, downloads” in section 1. Through a proxy, set `HTTPS_PROXY` in the environment of the timer (for example
`systemctl edit probant-auto-update-<number>.service`), and the proxy of Docker for the downloads of images.

### Update without Internet access

To update an installation without Internet access, use the offline package of the new version:

1. Download the package of the new version and verify it, as in steps 1 to 3 of “Install without Internet access”
   (section 2).
2. Copy the package to the server, and extract it into another folder than the folder of the tool. For example:

   ```bash
   mkdir /tmp/probant-new
   tar -xf probant-X.Y.Z-offline.tar -C /tmp/probant-new
   ```

3. In the folder of the tool, run the update with the archive of the new image:

   ```bash
   ./update.sh --offline /tmp/probant-new/probant/probant-image-X.Y.Z.tar.gz
   ```

4. When the tool works, delete the folder of step 2: `rm -rf /tmp/probant-new`.

The script checks the files of the package against its `SHA256SUMS`, and refuses a version older than the installed
version: in both cases, it changes nothing. Then it does the steps of the update, without any download:

1. It makes the “before-update” backup of each space, with the version that is installed now.
2. It puts the files of the package in place (`docker-compose.yml`, `install.sh`, `update.sh`…). It keeps `.env` and
   the data. It loads the new image into Docker and sets `IMAGE` in `.env` to it.
3. It restarts the tool, and waits for it to respond.

The image of before stays on the server. To go back, see “Going back to the previous version”. An installation made
with one command, or from another offline package, updates in the same way.

### Going back to the previous version

> **Warning:** Going back replaces everything done since the “before-update” backup. Warn the teams, and do it when
> nobody enters data.

The update makes a “before-update” backup of each space before it changes anything. List the backups:
`docker compose exec web python manage.py backup --list` (add `-e SPACE=<code>` for another space). The archives of
another space are in `/data/backups/spaces/<code>/`, and the archive of the shared registry is in
`/data/backups/shared/`. The version that made an archive can always read it: to go back, use the oldest
“before-update” archive of the update. The rotation of the backups always keeps the “before-update” archives of the
last update, so going back stays possible until the next update.

The steps depend on the database:

- **SQLite** (default): do the steps below, without `--rebuild`.
- **PostgreSQL**: a PostgreSQL backup (JSON format) restores only into a database that has exactly its migrations.
  After an update, the database has more migrations. The option `--rebuild` of `restore` drops the tables of the space,
  creates them again for the version that is installed, then loads the backup. It does all of this in one step: if a
  step fails, the database does not change.

To go back to the previous version:

1. Stop the tool: `docker compose stop web`.
2. Get the previous version, without starting it:
   - With `git`: find it (`git log --oneline -5`), then run `git checkout <previous-version>` and
     `docker compose build web`.
   - With a published image (an installation with one command, for example): set `IMAGE=` to the previous image in
     `.env`, then run `docker compose pull web`. At the end of an update, the script shows the image of before the
     update (“Image before the update: …”).
   - Without Internet access: the image of before is still on the server (`docker image ls`). Set `IMAGE=` to it in
     `.env`, without `docker compose pull`.
3. Restore the “before-update” archive of the main space:
   `docker compose run --rm web python manage.py restore <before-update archive> --yes --rebuild`
   (SQLite: without `--rebuild`).
4. For each other space, restore its own archive:
   `docker compose run --rm -e SPACE=<code> web python manage.py restore <archive of this space> --yes --rebuild`.
5. Optional: to bring back the accounts and passwords as they were before the update, restore the shared registry:
   `docker compose run --rm web python manage.py restore --shared <registry-…-before-update.zip> --yes`.
   Without this step, everyone keeps their current password.
6. Start the tool: `docker compose up -d`.

If a restore says that the archive has no valid signature of this installation (an archive made on another server,
for example), run the same command again with `--unsigned`.

Each restore first backs up the current state (“before-restore” archive). Keep these archives until the tool works
again.

With Git, to update the tool again later, go back to the main branch first: `git checkout main`, then `./update.sh`. After
`git checkout <previous-version>`, `git pull` refuses to run (“You are not currently on a branch”), and `update.sh`
stops. After an installation with one command, run `./update.sh`: it installs the latest version again.

#### Restore a PostgreSQL backup on a new server

A PostgreSQL backup restores only with the version of the tool that made it, or with `--rebuild`. On a new server,
install the tool, restore the shared registry (`restore --shared`), then the main space and each other space (steps 3
and 4 above). The new server has another secret key: add `--unsigned` to the restore of each space, or copy the file
`.secret_key` of the former data folder into the new one before the first start.

## 7. Set up emails (SMTP)

The tool sends emails through the email server (SMTP) of your company: reminders, email alerts (section 9), and test
emails. You can set up this server in two ways. The settings apply to the whole installation, for all spaces.

| Way | Who | When to use it |
|---|---|---|
| In the tool: **Administration › Settings › Hosting**, **Emails** box | A space manager | The usual way. IT only gives the settings of a sending account. No restart. |
| In the `.env` file (`SMTP_…` settings) | IT | When IT wants to keep the settings on the server. These settings take priority. |

Without either, the tool sends no email. It only writes the messages in the log (`docker compose logs web`).

### Set up emails in the tool

Before you start, ask IT for the settings of a sending account: server, port, security (STARTTLS or SSL/TLS),
username, password, and sending address. The **Message to send to IT** in the **Emails** box gives a ready text.

To set up emails in the tool:

1. Go to **Administration › Settings › Hosting**. The **Emails** box shows the fields of the sending server.
2. Enter the **Sending server (SMTP)**, for example `smtp.example.com`, without `smtp://` and without the port.
3. Enter the **Port** and choose the **Security**: **STARTTLS** (usually port 587) or **SSL/TLS** (usually port 465).
   With these two choices, the tool checks the certificate of the server. **None** sends the password without
   encryption: use it only on a closed internal network. With **None** and a password, the tool asks you to confirm.
4. Enter the **Username**, the **Password** and the **Sending address**.
5. Click **Save**.
6. Under **Test email**, click **Send a test email**. The test uses the saved settings. If the email is not sent, a
   message gives the cause in plain words: server not found, connection refused, time limit exceeded, certificate,
   security setting, username or password refused, sending address refused.

![Administration › Settings › Hosting, Emails box: sending server set up in the tool](screenshots/en/hosting-emails.png)

The password works like this:

- The tool never shows the password again. It never writes it in the history, in the log, or in the configuration
  file that you export.
- To keep the saved password, leave the field empty when you save. To remove it, click **Remove the password**.
- If you change the server, the port or the username, or set the security to “None”, the tool deletes the saved
  password, so that it never goes to another server. Enter it again in the same save. If you do not, the screen says
  so.
- The tool keeps the password encrypted with the secret key of the installation (`DJANGO_SECRET_KEY`, or the file
  `/data/.secret_key`). The backup of a space never contains the email settings. The backup of the shared registry
  (`backups/shared`, only for IT) contains them, with the password encrypted.
- If the secret key changes, or if IT restores the shared registry on another server, the tool can no longer read the
  password. The **Emails** box and **Settings › Health** then say that the password must be entered again. No email
  is sent until then. Enter the password again and save.

To limit the misuse of the test button, the tool allows at most 5 test emails every 15 minutes with the settings of
the tool, and waits 10 seconds at most for the server. The error message never shows the answer of the server. Each
failed test is written in the history.

Only a space manager can change these settings. The other administrators see the server and the sending address, and
can send a test email with the saved settings.

### Set up emails in the `.env` file

To set up emails in the `.env` file:

1. Add these values to `.env`:

   ```
   SMTP_HOST=smtp.example.com
   SMTP_PORT=587
   SMTP_SECURITY=starttls        # starttls (587), ssl (465) or none
   SMTP_USER=reporting@example.com
   SMTP_PASSWORD=…
   SMTP_FROM=reporting@example.com
   ```

2. Run `docker compose up -d`.
3. Go to **Administration › Settings › Hosting**, and click **Send a test email**. If the email is not sent, a message
   gives the cause.

> **Note:** When `SMTP_HOST` is set, the `.env` file takes priority over the settings entered in the tool. The
> **Emails** box then shows the settings of the `.env` file read-only (without the password), with the mention
> "Set by IT in the settings file". To go back to the settings of the tool, empty `SMTP_HOST` and restart the tool.

### Reminders

The administrators and the validators send the reminder emails in **Dashboard › Remind…**. Each person receives a
single email, with no copy. The email lists what the person still has to enter. Before the tool sends the email, it
shows the exact preview of the message. An administrator sets the template.

An administrator can turn on automatic reminders on the same page. The tool sends them on the chosen days before
the end of data entry. It checks for them every day at `REMINDER_TIME` (09:00 by default). `PUBLIC_URL` gives the
address in these emails. By default, the tool takes this address from `DOMAIN`.

![Dashboard › Reminders: people, message preview, template and automatic reminders](screenshots/en/reminders.png)

## 8. Use PostgreSQL (optional)

SQLite is the default database. You do not need to manage a database server.
SQLite writes one save at a time. The other saves wait for their turn, for up to 60 seconds. When many people save at
the same moment, use PostgreSQL: see “Capacity”.

### Capacity

Two load tests measured the capacity. The capacity depends on the size of the database, because each save
recalculates the totals that it changes. This table shows the results:

| Database | Measure | Result |
|---|---|---|
| Small (the demo) | Load test, SQLite, server with 2 to 4 processors used only by the tool | Comfortable with up to about 100 people who enter data at the same moment |
| Large (679 organisations, 1.27 million answers) | Load test (`qa/load/README.md`). Each simulated person works about ten times faster than a real person. | SQLite: 10 very active people without an error. From 15 to 20 people, some saves fail with "database is locked". PostgreSQL: 50 people without an error and without a lost save, but saves wait in a queue. |

Recommendation: use PostgreSQL when more than about twenty people are active at the same moment. Also use PostgreSQL if
the server runs other heavy programs, and give the server more processors.

During the busiest days of a campaign, avoid the operations that rewrite everything at once:

- **Redo all calculations** on a campaign
- Reopening a closed campaign
- Adding or deactivating an organisation
- An import of several thousand rows

The tool writes an import in blocks of 100 rows. Other people are not blocked, but the import takes longer. Above
`BACKGROUND_IMPORT_ROWS` rows, the import runs in the background, one import at a time.

### Switch to PostgreSQL

You can switch to PostgreSQL in 2 ways. This table shows the settings in `.env` for each way:

| Option | Setting in `.env` |
|---|---|
| PostgreSQL provided in the same file | `COMPOSE_PROFILES=postgres` and `DATABASE_URL=postgres://probant:PASSWORD@db:5432/probant`, where `PASSWORD` is the value of `POSTGRES_PASSWORD`. |
| Existing PostgreSQL server | `DATABASE_URL=postgres://user:password@server:5432/database`. Encode a special character in the password. For example, `@` becomes `%40`. |

With PostgreSQL, the backup contains the database in JSON format. You can restore it only with the version of the tool
that made it. To go back to the previous version after an update, see
[Going back to the previous version](#going-back-to-the-previous-version).

After a large load in one step, the tool updates the statistics of the PostgreSQL planner (`ANALYZE` on the tables of
the space). A large load is a restore, the installation or update of a library template, the import of a configuration
file, or a data takeover. The database user must own the tables of the tool. This is the case when the tool creates
them. If `ANALYZE` fails, the operation is kept and the log shows a warning. PostgreSQL then updates the statistics
itself, a few minutes later.

### Move an existing SQLite installation to PostgreSQL

Do this when nobody works in the tool: whatever people enter after the backups of step 1 is lost. Keep the same data folder
(the same `/data` volume), use an empty PostgreSQL database, and keep the same version of the tool.

The move needs these archives: one backup in JSON format for **each space**, and one archive of the **shared registry**
(accounts, list of spaces, access). The new PostgreSQL registry has a new identity. Without the archive of the registry, the
tool refuses the backup of the main space (“another installation”).

Do these steps in this order:

1. Back up each space in JSON format. Run `docker compose exec web python manage.py backup --json` for the main space, and
   `docker compose exec -e SPACE=<code> web python manage.py backup --json` for each other space. The command
   `docker compose exec web python manage.py spaces` lists the spaces and their codes.
2. Make an archive of the shared registry:
   `docker compose exec web python manage.py shell -c "from parametres import sauvegardes as SV; print(SV.creer_registre('before-postgresql'))"`.
   The tool also makes one every day in `backups/shared/`: use it only if nobody created or changed an account since then.
3. Write down the name of each archive: `backups/` (main space), `backups/spaces/<code>/` (other spaces), `backups/shared/`
   (registry). Copy the three folders off the server.
4. Change `DATABASE_URL` in `.env`.
5. Run `docker compose up -d`. The tool starts with an empty database and shows the setup wizard. Do not use the wizard.
6. Restore the shared registry: `docker compose exec web python manage.py restore --shared <registry archive> --yes`.
   The command can end with a database error about a table that does not exist (`relation "referentiel_utilisateur"
   does not exist`). This is expected, because the other spaces have no tables yet. The registry is restored. Run
   `docker compose exec web python manage.py spaces` to check that it lists your spaces.
7. Restore the main space: `docker compose exec web python manage.py restore <archive of the main space> --yes`.
8. Restore each other space: `docker compose exec -e SPACE=<code> web python manage.py restore <archive of this space> --yes --rebuild`.
   The option `--rebuild` creates the tables of the space in PostgreSQL before it loads the archive.
9. Run `docker compose restart web`. Sign in, and check the values of each space.

If the installation has only the main space, you can make it shorter. Skip steps 2, 6, and 8, and add `--other-space` to
step 7. This way, the tool creates the registry again from the accounts of the main space. The tool does not keep the
name of the space or the accounts that exist only in another space.

The command `python manage.py shell` in step 2 is the only way to make an archive of the registry on demand. The tool does not
have a command for it. A test of this move compared the data of the PostgreSQL installation with the SQLite installation,
table by table, for two spaces: it is identical (only the numbers of the access rows of the registry change).

### Several spaces with PostgreSQL

Each space (department) opens its own connections to the database. Before you create many spaces, check the
connection limit of your plan (small Clever Cloud plans). See [docs/spaces.md](spaces.md).

## 9. Monitor the tool and read the logs

### Get an email when something goes wrong

The tool alerts you by email: you have no monitoring to connect. On a new installation, the email alerts are on from
the start. They need the email server (section 7): without it, the tool sends nothing. An installation that existed
before the email alerts keeps them off after an update, until a space manager turns them on. Once turned off, they
stay off.

A space manager sets the alerts in **Administration › Settings › Health**, box **Email alerts**, and chooses the
recipients: by default the administrators of the main space and the space managers, plus other addresses, for example
the mailbox of the IT team.

![Administration › Settings › Health, Email alerts box: alerts on, recipients and test alert](screenshots/en/admin-health-alerts.png)

The alerts come from the same checks as the **Health** page and `/sante/`. These checks send an alert:

| Check | Alert when |
|---|---|
| Database | A database does not answer, or the startup check found a damaged database |
| Demo data | The database is the demo, and demo accounts still have the public password (never in development mode or in the all-in-one version). The tool starts all the same. The line goes away when no active demo account has the public password. |
| Files | The tool cannot write in its data folder |
| Last backup | The automatic backup failed or is late, the latest backup cannot be read, or the backup folder cannot be read |
| Disk space | Less than 10 times `DISK_ALERT_MB` free (“To check”), or less than `DISK_ALERT_MB` (“Failure”) |
| Email | The reminders failed, or the saved password of the email server can no longer be read |
| Background tasks | A background task stopped, an import or an export is stuck, or the night data check is late or found errors |
| Database update | Migrations are not applied |
| External copy | A copy of the backups fails, or is late (section 5) |
| Automatic updates | A new version is installed, or waits (“Notify only”). A signature is refused. The server went back to the previous version, or could not go back. The timer or the check has not worked for 3 days (section 6) |

These states do not send an alert: no backup yet, automatic backups turned off, a restore that finishes by itself,
HTTPS (it depends on the request).

The rules:

- The tool checks every 15 minutes, in the `check_data --schedule` and `backup --schedule` processes. Only one check
  runs at a time for the whole installation, even with several processes, spaces or servers.
- One email when a problem appears. All the changes of one check go in one email.
- A reminder at most once a day while a problem lasts, one email for all the problems.
- An email when a problem is resolved (absent at two checks in a row).
- Each person gets the email in their language. The other addresses get it in the language of the installation. The
  email gives the name of the space, what happens, since when, what to do, and the link to the **Health** page
  (`PUBLIC_URL`). It never contains data, folders of the disk, or the detail for IT.
- If the email cannot be sent (email server down), nothing fails: the problem stays on the **Health** page and in
  `/sante/`, the log gives the cause (`Email alerts not sent through …`), and the tool tries again at the next check.
- The state of the alerts is kept in the shared registry, outside the database of each space: a restore of a space
  does not send the alerts again. After a restore of the shared registry, the alerts of the problems that remain are
  sent again once.
- **Send a test alert** sends to the saved recipients an email with the problems of the moment.

**Limit:** when the server is off, or when the shared registry does not answer, the tool cannot warn anyone. To be
warned in this case too, keep an external monitoring of `/sante/` (below), in addition to the email alerts.

Without background tasks (managed hosting with scheduled tasks, see [Managed hosting](managed_hosting.md)), schedule
`python manage.py check_data --alerts` every 15 minutes. The all-in-one version runs no background task and sends no
alert.

### Check that the tool is healthy

In addition to the email alerts, your monitoring can call `/sante/`. `GET /sante/` answers with one of these codes:

- `200` with `{"etat": "ok"}`: the tool works.
- `503` with `{"etat": "erreur"}`: the database or the storage has a problem, the database is damaged, a restore was
  interrupted, or the disk is almost full (less than 100 MB free, `DISK_ALERT_MB` setting). The details give the
  cause in `alerte`.

The page needs no sign-in and shows no sensitive data. Docker uses it too: `docker compose ps` shows `healthy`.

The tool gives the details of the whole installation only to a call from the server itself (from `127.0.0.1`, with
none of the headers that a proxy adds: `X-Forwarded-For`, `X-Real-IP`, `Forwarded`), to a signed-in space manager,
and to a signed-in administrator of the main space. The administrator of another space gets the details of their own
space only: the shared registry and the disk are measured, but the names, failures and stuck tasks of the other spaces
and the folders of the disk are not shown. Other people get the state only. The reason is that the exact version can
help to find an installation that is not up to date, and that the administrator of one space does not have to know the
other spaces. To see the details from the server, run this command:

```bash
docker compose exec web python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/sante/').read().decode())"
```

This table shows the fields of the details:

| Field | Content |
|---|---|
| `version`, `base`, `stockage`, `derniere_sauvegarde` | The version, the state of the database and of the storage, and the date of the latest backup |
| `alerte` | The cause of a `503` answer |
| `avertissement` | A warning that does not cause `503`, for example a stuck import or export, or a backup dated in the future |
| `controle_donnees` | The latest data check: `etat` (`ok`, `problems`, `late` if there is no data check for 48 hours, `never`), `date`, `erreurs`, `avertissements` |
| `background_imports` | The state of the background imports (see “Check that a large import is not stuck”) |
| `background_exports` | The state of the large exports in the background: `running`, `waiting`, `stuck` (same section) |
| `external_copy` | The external copy of the backups ([Copy the backups outside the server](#copy-the-backups-outside-the-server)): `state` (`off`, `ok`, `failing`, `late`, `host key to confirm`, `unavailable` in the all-in-one version), `last_success`, `pending` (archives not copied yet). A failing copy never causes `503`: it is in `avertissement`. |

A data problem or a late check **never** makes `/sante/` answer `503`. `503` means “the tool does not answer”. Docker
or Clever Cloud then restart the tool, and a restart fixes neither a figure nor a stopped scheduler. To watch the
nightly check, set an alert on `controle_donnees.etat` = `late`. The email alerts of the tool also say it.

![Response of /sante/](screenshots/en/health.png)

The administrators read the same measures, in plain words, in **Administration › Settings › Health**: one line per
check (version, database, files, last backup, disk space, email, background tasks, database update, HTTPS), with
**Good**, **To check** or **Failure** and what to do. The detail for IT (names of the spaces, folders on the disk,
messages of `/sante/`) is shown only to the space managers and to the administrators of the main space. The same rule
applies to the “For IT” box of **Settings › Hosting**: in another space, the administrator who is not a space manager
does not see the data folder, the allowed addresses, the database server, the SMTP username or the backups folder.

### Check that the data is consistent

Every night at `DATA_CHECK_TIME` (03:30), the tool checks the database of each space. It **changes nothing**. It
checks these points:

- Every stored total and calculation, in the periods that are not closed: the tool calculates it again in memory and
  compares (for closed periods, it only reports)
- No value attached to a deleted KPI or organisation, to a period without a campaign, or recorded twice
- Consistent statuses
- Plausible percentages (−100% to 1,000%)
- Figures of calculated KPIs imported as they are in an open period
- Assignments of open campaigns to inactive or read-only accounts, or to closed organisations
- Evidence files present on the disk (and files left over in `files/evidence`)
- Formulas and their stored dependencies
- A tree with no loop and with consistent levels
- A readable latest backup (valid zip, `backup.json`)

The tool keeps the last 10 results in `backups/data-checks.json`, outside the database, like `restores.jsonl`. The
administrator sees them in **Administration › Settings › Hosting**, in the **Data check** box. This box has the
**Check now** button. When the check finds something, it also shows in **To be handled**.

To run the check by hand, run `docker compose exec web python manage.py check_data`. The French name
`controler_donnees` also works. The command has these options and results:

- Output: readable text in English, or JSON with `--json`
- `--no-save`: the tool does not keep the result
- `SPACE=<code>`: only one space
- Exit code 1 if the check finds an error
- Duration: a few seconds (6 s on the demo, with 6 reporting years)

### Deleted items (trash) and expired sessions

When a person deletes a saved export, a KPI list or a Visualisation view, the tool keeps it in a trash, so that the
person can undo the deletion or restore the item from **My account › Recently deleted**. An administrator sees the
items of everyone in **Administration › History › Recently deleted**. The trash keeps the items for 30 days by
default. An administrator sets this delay, from 1 to 365 days, in **Administration › Settings › Hosting**, box
**Deleted items**. After the delay, the tool erases the item for good.

The `check_data --schedule` process also does a clean-up every night at `DATA_CHECK_TIME`, and once when it starts:

- It erases the expired sessions, like `manage.py clearsessions`. The sessions of all the spaces are in the shared
  registry. A session that is still valid is never erased.
- It erases the deleted items older than the delay, in each space.
- It writes one line in the log: `Nightly clean-up: N expired session(s) and N deleted item(s) erased for good`.

You have nothing to schedule. The tool also does this at each start (`manage.py startup`), and erases the old deleted
items each time someone deletes something. To erase the deleted items by hand, run
`docker compose exec web python manage.py purge_deleted` (French name: `purger_corbeille`; `SPACE=<code>` for only
one space). To erase the expired sessions by hand, run `docker compose exec web python manage.py clearsessions`.

### Check that a large import is not stuck

Large value imports run in the background, in the `run_imports --schedule` process. The image starts this process
next to the backups, the reminders, and the data check. The same process makes the large exports (above the threshold
that the administrator sets in **Administration › Settings › Hosting › Large exports**). Their files are in
`files/exports/` of the data folder, are deleted after 7 days, and are never in the backups: nothing to copy. The details of `/sante/` give `background_imports` for the imports and `background_exports` for the
large exports, with the same three fields:

- `running`: the number of imports (or exports) that run
- `waiting`: the number of imports (or exports) that wait
- `stuck`, with a `message` (also in `avertissement`): an import (or an export) that gives no sign of life, or that
  waits for more than 10 minutes

If an import or an export is stuck:

1. Check that the process runs: `docker compose logs web | grep "Background"`.
2. If necessary, restart the tool: `docker compose restart web`.

A stuck import or export never makes `/sante/` answer `503`. If a restart stops a task, the task starts again once
automatically. After that, the tool marks it as “interrupted”. It tells the person to import the file again, or to ask
for the export again.

### Read the log and manage the services

This table shows the other monitoring operations:

| To… | Do |
|---|---|
| Read the log | Run `docker compose logs -f web`. Each line has the date. The log contains the startup (version, database, addresses, emails), each request (address, page, code, duration), the backups, and the errors. Like the output of the `manage.py` commands, the log is always in English, whatever the language of the interface. |
| See the state of the services | Run `docker compose ps`. |
| Restart | Run `docker compose restart web`. |
| Stop, then start again | Run `docker compose down`, then `docker compose up -d`. The data stays in the volume. |

## 10. Troubleshooting

This table shows common problems, their likely cause, and the solution:

| Symptom | Likely cause and solution |
|---|---|
| `Bad Request (400)` when you open the tool | The address is not in `DOMAIN`. Add it to `.env` (separate several values with commas). Then run `docker compose up -d`. |
| The page does not open | Check that the service runs (`docker compose ps`). Check that the firewall opens the port. Then read `docker compose logs web`. |
| Redirect loop or CSRF error (403) over HTTPS | `DJANGO_HTTPS=1` is set, but the proxy does not send `X-Forwarded-Proto: https`. Caddy sends it automatically. With another proxy (nginx, Traefik…), add this header. |
| No HTTPS certificate | The domain name must point to the server, and ports 80 and 443 must be open. Read `docker compose logs caddy`. |
| “The folder /data is not writable by the tool” | A folder mounted in place of the volume belongs to another user. Run `sudo chown -R 1000:1000 <folder>`. |
| “Database unreachable” | With PostgreSQL, check `DATABASE_URL`. Then read `docker compose logs db`. |
| “DAMAGED DATABASE” in the log, `/sante/` answers `503` “damaged database” | The startup check (or a backup) found that the SQLite file is damaged (disk fault, file copied by hand next to an old `-wal` file…). The tool starts without updating the database and refuses to back it up, so the good archives stay. The log gives the last good archive. Restore it: `docker compose exec web python manage.py restore <that archive> --yes`. Then run `docker compose restart web`. The tool keeps the damaged state: a “before-restore-damaged” archive, or the file renamed `db.sqlite3.damaged-<date>` if it no longer opens. If no archive is good, use the external copy of the backups. |
| “Not enough disk space” (backup, update, or restore), `/sante/` “disk almost full” | Nothing is half-written. The tool does not keep the backup and does not apply the update (the database does not change). It cancels the restore. Free some space: copy old archives off the server, or enlarge the disk. Then run the command again, or run `docker compose restart web`. People who try to save see “Saving is not possible for now”. Nothing that they did is half-saved. |
| “This archive has no valid signature of this installation” (restore command), or “This backup was not made by this installation” (Hosting page) | Nothing was changed. The archive was made by an earlier version, by another server, or before a change of `DJANGO_SECRET_KEY`, or someone changed it. If you trust it, restore it from the command line with `--unsigned`: `docker compose exec web python manage.py restore <archive> --yes --unsigned`. If you do not know where it comes from, do not restore it. |
| “The database was updated by a more recent version of the tool” or “made with other database migrations” (restore, PostgreSQL) | Nothing was changed. The message gives the exact command. To go back after an update, see [Going back to the previous version](#going-back-to-the-previous-version). To restore on a new server, install first the version that made the backup. To restore an older archive after an update: restore it with the version that made it, then update again with `./update.sh`. |
| “the restore of … was interrupted and could not be finished” | The archive in the message is missing or cannot be read. Restore it again (`python manage.py restore <name> --yes`). To go back to the state before, restore the “before-restore” archive. |
| Everyone must sign in again after a restart | The `.secret_key` file of the data folder was deleted or empty. The tool created a new key (log: “New secret key created”). The backups made before are refused in **Settings › Hosting** (restore them from the command line with `--unsigned`). The secrets saved in the tool must be entered again: the password of the email server, the secrets of the external copy, and the client secret of company sign-in (the screens say so). Nothing else is lost. |
| Wrong server clock (date in the future, then corrected) | The tool keeps the backups dated in the future, but does not count them in the rotation. The next automatic backup runs at the usual time. `/sante/` gives a warning (`avertissement`). Fix the clock (NTP). |
| “database is locked” | A save waited more than 60 seconds for its turn: SQLite writes one save at a time. This is rare, because SQLite runs in WAL mode. When it occurs, the server is overloaded. Check that the tool has its processors to itself (`docker stats`). Avoid **Redo all calculations** and large imports during the busiest hours. Then give the server more processors, or switch to PostgreSQL (section 8). |
| The test email or the test alert fails | The message gives the cause (username refused, port blocked, TLS…). Check the settings of the email server with the email provider: in **Administration › Settings › Hosting**, box **Emails**, or the `SMTP_…` settings of the `.env` file if your IT team set them there (they come first). The log gives the technical cause (`Test email to …` or `Email alerts not sent through …`). |
| **Health** says that a background task stopped, but it was removed on purpose | The tool remembers each background task that ran on the server (`.tasks/` in the data folder). Delete the file of the task that you removed, for example `docker compose exec web rm /data/.tasks/imports`. |
| The AI assistant says “The provider cannot be reached from the server” | Allow outgoing HTTPS to `api.anthropic.com` in the firewall, or set `HTTPS_PROXY` (section 4, “AI assistant”). |
| Administrator password lost | Another administrator resets it in **Administration › Accounts**. If there is no other administrator, run `docker compose exec web python manage.py changepassword <email>`. |
| No account can open **Administration** any more | The tool never lets the last active administrator lose the role or the access. This can still occur after a restore of an old backup, or after a change made directly in the database. Give the administrator role back to an existing account: `docker compose exec web python manage.py grant_admin <email>`. The tool records the change in the history. |
| Start again from scratch (trial) | **Warning:** this **deletes all the data**. Run `docker compose down -v`, then `./install.sh`. |

## 11. Test the installation

This part is for the people who change the code of the tool. You do not need it to install the tool. The test
scripts are in the code (folder `docker/`), not in the folder of an installation with one command.

The script `bash docker/test_installation.sh` reproduces an installation on a blank machine. It copies the repository
into an empty folder and runs `./install.sh`. Then it checks these points:

- The health page
- The wizard, shown in place of the sign-in page
- The static files and the compression
- The security headers
- `check --deploy` over HTTPS
- The backup
- The update, with a backup made first
- The data, kept after the update

At the end, the script deletes everything that it created. To run the same test with the test suite, run
`TESTER_DOCKER=1 python manage.py test parametres.test_hebergement`.

The script `bash docker/test_get.sh` tests the installation with one command. It serves a local copy of the public
repository and a local image registry, then runs `get.sh` through a pipe, as in section 2. The lists of sums of the
local releases are signed with a test key of cosign. Before, it checks the refusals: a file of the tag changed, the
list changed after its signature, and a release without a list. Then it checks the update to a newer version and the
way back to the previous version (section 6). The variables `PROBANT_TEST_SOURCE`, `PROBANT_TEST_IMAGE`,
`PROBANT_TEST_OS_RELEASE`, `PROBANT_TEST_SKIP_CHECK`, `PROBANT_TEST_COSIGN_KEY` and `PROBANT_TEST_COSIGN_IMAGE` of the
scripts are only for these tests: do not set them on a server. The two cosign variables are read only with a test
source or a test image (`PROBANT_TEST_SOURCE`, `PROBANT_TEST_IMAGE`): the files and the image of the public repository
are always verified against its identity.

The script `bash docker/test_offline.sh` tests the installation without Internet access. It makes the offline
packages of two versions with `docker/make_offline_package.sh`, from the image of the folder. Then it plays a server
without Internet access: the name of the image points to a registry where nothing answers, `curl` and `wget` fail,
Docker must download no image, and, where the system allows it, the scripts run without any network (`unshare --net`). It checks the installation (`./install.sh --offline`), the update to the second version
(`./update.sh --offline`), the refusal of an older package, and the way back to the first version (section 6).

The script `bash docker/test_custom_certificate.sh` tests the company network (section 2, “Company network”). It
creates a test certificate authority and a server certificate signed by it. Then it installs the tool with `--domain`,
`--cert`, `--key` and `--ca-cert`, and checks these points: Caddy serves this certificate (`curl --cacert`), the
health page answers through HTTPS, Caddy never contacts Let's Encrypt, the key never enters the container of the tool,
an outgoing HTTPS connection of the tool trusts the authority, and the renewal. Then it does the same without Internet
access, from an offline package. `TEST_HTTPS_PORT` and `TEST_HTTP_PORT` choose other ports than 443 and 80.

The script `bash docker/test_auto_update.sh` tests the automatic updates (section 6), with a local image registry, a
local copy of the public repository, and a test key of cosign. On one installation made by `get.sh`, it plays the
choices “Off” and “Notify only”, the wait after the publication, a missing or wrong signature, a missing or changed list
of sums, a new version that does not start (going back, with and without a restore), the lock shared with
`./update.sh`, and a successful update. It needs Docker and cosign 3 (`COSIGN_BINARY`). The signature made by the
workflow of the public repository can only be checked on GitHub, at each published version.
