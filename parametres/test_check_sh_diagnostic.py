"""``check.sh`` : contrôle du serveur avant l'installation, sans rien changer sur la machine.

Chaque contrôle a un cas bon et un cas mauvais, joués avec de faux programmes dans le PATH
(``parametres/aides_tests/faux_diagnostic.py``) : système, architecture, Docker, Compose, service Docker et droits,
mémoire, processeurs, disque, ports, nom de domaine (dont le serveur derrière un routeur, « non vérifié » plutôt qu'un
faux « non »), accès au registre et à GitHub (proxy compris), horloge. Une ligne par contrôle, puis une seule
conclusion ; code de sortie 0 (prêt) ou 1 (il manque quelque chose)."""
import socket
import subprocess

from django.test import SimpleTestCase

from parametres.aides_tests.faux_diagnostic import date_http, journal_reseau, preparer_faux
from parametres.aides_tests.scripts_installation import IMAGE_PUBLIQUE, RACINE, AidesScripts

IMAGE = f"{IMAGE_PUBLIQUE}:9.9.1"


class AidesDiagnostic(AidesScripts):
    def diagnostic(self, *options, absents=(), **valeurs):
        """Lance check.sh ; ``valeurs`` remplace les réponses bonnes des faux (F_…), ou ajoute une variable."""
        tmp = self.dossier()
        chemin, variables = preparer_faux(tmp, absents)
        variables.update(valeurs)
        env = self.environnement(tmp, chemin=chemin, diagnostic=True, **variables)
        r = self.lancer(["sh", str(RACINE / "check.sh"), *options], cwd=tmp, env=env)
        r.tmp = tmp
        return r

    def ligne(self, r, debut):
        """La ligne du contrôle qui commence par ``debut`` : (état, texte)."""
        for x in r.stdout.splitlines():
            etat, texte = x[2:14].strip(), x[15:]
            if texte.startswith(debut):
                return etat, texte
        raise AssertionError(f"aucune ligne « {debut} » :\n{r.stdout}")

    def assertEtat(self, r, debut, etat, *mots):
        e, texte = self.ligne(r, debut)
        self.assertEqual(e, etat, texte)
        for m in mots:
            self.assertIn(m, texte)
        return texte

    def assertPret(self, r):
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("\nReady", r.stdout)
        self.assertNotIn("To fix", r.stdout)

    def assertManque(self, r, *mots):
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        conclusion = r.stdout[r.stdout.index("Here is what is missing:"):]
        for m in mots:
            self.assertIn(m, conclusion)
        self.assertNotIn("Ready", r.stdout)


class ConclusionTests(AidesDiagnostic, SimpleTestCase):
    def test_tout_bon_pret(self):
        r = self.diagnostic("--image", IMAGE)
        self.assertPret(r)
        self.assertEqual(r.stdout.strip().splitlines()[-1], "Ready.")
        etats = {self.ligne(r, d)[0] for d in ("System", "Architecture", "Docker:", "Docker Compose", "Docker service",
                                               "Memory", "Processors", "Disk", "Port 8000", "ghcr.io", "github.com",
                                               "raw.githubusercontent.com", "pkg-containers", "Clock")}
        self.assertEqual(etats, {"OK"})

    def test_un_point_a_corriger_une_seule_conclusion(self):
        r = self.diagnostic("--image", IMAGE, F_MEMOIRE="480")
        self.assertManque(r, "Memory: 480 MB")
        self.assertEqual(r.stdout.count("Here is what is missing:"), 1)
        # la conclusion reprend le point, avec ce qu'il faut faire
        self.assertIn("  - Memory: 480 MB. The tool needs at least 1 GB", r.stdout)

    def test_rien_n_est_ecrit_sur_la_machine(self):
        r = self.diagnostic("--image", IMAGE, "--domain", "reporting.example.com", F_ADRESSES_DU_NOM="203.0.113.10")
        self.assertPret(r)
        avant = sorted(p.name for p in r.tmp.iterdir())
        self.assertEqual(avant, sorted(["faux-diagnostic", "systeme-diagnostic", "os-release", "docker-data",
                                        "reseau.txt", "journal.txt"]))
        self.assertEqual(list((r.tmp / "docker-data").iterdir()), [])
        # seules des lectures : aucune commande docker autre que version, compose version et info
        self.assertFalse([x for x in journal_reseau(r.tmp) if x.startswith("docker ")])

    def test_options(self):
        self.assertEqual(self.diagnostic("--port", "huit").returncode, 2)
        self.assertEqual(self.diagnostic("--inconnue").returncode, 2)
        self.assertEqual(self.diagnostic("--port").returncode, 2)
        r = self.diagnostic("--help")
        self.assertEqual(r.returncode, 0)
        self.assertIn("changes nothing", r.stdout)


class SystemeTests(AidesDiagnostic, SimpleTestCase):
    def test_systeme(self):
        self.assertEtat(self.diagnostic(), "System", "OK", "Linux (Ubuntu 24.04.1 LTS)")
        r = self.diagnostic(F_SYSTEME="Darwin")
        self.assertEtat(r, "System", "To fix", "Linux only")
        self.assertManque(r, "System: Darwin")

    def test_architecture(self):
        self.assertEtat(self.diagnostic("--image", IMAGE), "Architecture", "OK", "x86_64")
        # image publiée : x86_64 seulement ; construite sur le serveur (Git) : arm64 convient
        r = self.diagnostic("--image", IMAGE, F_ARCH="aarch64")
        self.assertEtat(r, "Architecture", "To fix", "install with Git")
        self.assertEqual(r.returncode, 1)
        self.assertEtat(self.diagnostic("--offline", F_ARCH="aarch64"), "Architecture", "To fix")
        self.assertEtat(self.diagnostic(F_ARCH="aarch64"), "Architecture", "OK", "builds the image")
        self.assertEtat(self.diagnostic(F_ARCH="i686"), "Architecture", "To fix", "64-bit")


class DockerTests(AidesDiagnostic, SimpleTestCase):
    def test_version_de_docker(self):
        self.assertEtat(self.diagnostic(F_DOCKER_SERVEUR="24.0.7"), "Docker:", "OK", "24.0.7")
        r = self.diagnostic(F_DOCKER_SERVEUR="20.10.24", F_DOCKER_CLIENT="20.10.24")
        self.assertEtat(r, "Docker:", "To fix", "Version 24 or later")
        self.assertManque(r, "20.10.24")

    def test_docker_absent(self):
        r = self.diagnostic(absents=("docker",))
        self.assertEtat(r, "Docker:", "To fix", "./install.sh", "offers to install Docker")
        self.assertEqual(r.returncode, 1)
        # pendant l'installation : install.sh propose ensuite de l'installer, ce n'est pas bloquant
        r = self.diagnostic("--installing", absents=("docker",))
        self.assertEtat(r, "Docker:", "Not checked", "offers to install it next")
        self.assertPret(r)
        # sans Internet, install.sh ne peut pas l'installer
        r = self.diagnostic("--installing", "--offline", absents=("docker",))
        self.assertEtat(r, "Docker:", "To fix", "package mirror")
        self.assertEqual(r.returncode, 1)

    def test_compose(self):
        self.assertEtat(self.diagnostic(F_COMPOSE="v2.24.1"), "Docker Compose", "OK", "v2.24.1")
        self.assertEtat(self.diagnostic(F_COMPOSE="5.7.1"), "Docker Compose", "OK")
        self.assertEtat(self.diagnostic(F_COMPOSE="2.20.3"), "Docker Compose", "To fix", "2.24 or later")
        r = self.diagnostic(F_COMPOSE="absent")
        self.assertEtat(r, "Docker Compose", "To fix", "docker-compose-plugin")
        self.assertEqual(r.returncode, 1)

    def test_service_et_droits(self):
        self.assertEtat(self.diagnostic(), "Docker service", "OK", "responds")
        r = self.diagnostic(F_DOCKER_SERVICE="droits")
        self.assertEtat(r, "Docker service", "To fix", "sudo", "docker group")
        self.assertEqual(r.returncode, 1)
        r = self.diagnostic(F_DOCKER_SERVICE="arrete")
        self.assertEtat(r, "Docker service", "To fix", "systemctl start docker")
        self.assertEqual(r.returncode, 1)


class RessourcesTests(AidesDiagnostic, SimpleTestCase):
    def test_memoire(self):
        self.assertEtat(self.diagnostic(F_MEMOIRE="960"), "Memory", "OK", "960 MB")  # serveur de « 1 Go »
        self.assertEtat(self.diagnostic(F_MEMOIRE="512"), "Memory", "To fix", "at least 1 GB")
        r = self.diagnostic(absents=("free",))
        self.assertEtat(r, "Memory", "Not checked", "free is missing")
        self.assertPret(r)

    def test_processeurs(self):
        self.assertEtat(self.diagnostic(F_PROCESSEURS="1"), "Processors", "OK", "1")
        self.assertEtat(self.diagnostic(F_PROCESSEURS="0"), "Processors", "To fix")
        self.assertEtat(self.diagnostic(absents=("nproc",)), "Processors", "Not checked")

    def test_disque_du_dossier_de_docker(self):
        r = self.diagnostic(F_DISQUE_KO="41000000")
        self.assertEtat(r, "Disk", "OK", "41 GB free", str(r.tmp / "docker-data"))
        self.assertIn(f"df {r.tmp / 'docker-data'}", journal_reseau(r.tmp))
        r = self.diagnostic(F_DISQUE_KO="2100000")
        self.assertEtat(r, "Disk", "To fix", "2100 MB free", "at least 5 GB")
        self.assertEqual(r.returncode, 1)
        # Docker pas encore installé : le dossier qu'il prendra, ou le plus proche qui existe
        r = self.diagnostic("--installing", absents=("docker",))
        self.assertEtat(r, "Disk", "OK")
        self.assertTrue([x for x in journal_reseau(r.tmp) if x.startswith("df /")])


class PortsTests(AidesDiagnostic, SimpleTestCase):
    def test_port_libre_ou_pris(self):
        self.assertEtat(self.diagnostic(F_ECOUTE="22 5432"), "Port 8000", "OK", "free")
        r = self.diagnostic(F_ECOUTE="22 8000")
        self.assertEtat(r, "Port 8000", "To fix", "--port")
        self.assertEqual(r.returncode, 1)
        # le port demandé, pas un autre qui le contient
        self.assertEtat(self.diagnostic("--port", "8080", F_ECOUTE="8000 18080"), "Port 8080", "OK")

    def test_https_ports_80_et_443(self):
        r = self.diagnostic("--domain", "reporting.example.com", F_ADRESSES_DU_NOM="203.0.113.10", F_ECOUTE="80")
        self.assertEtat(r, "Port 80", "To fix", "ports 80 and 443")
        self.assertEtat(r, "Port 443", "OK")
        self.assertEtat(r, "Port 8000", "OK")  # le port de l'outil, ouvert au seul serveur (Caddy devant)
        self.assertEqual(r.returncode, 1)

    def test_sans_ss_les_ports_du_systeme(self):
        """Sans ``ss`` (paquet iproute2 absent) : la table des connexions du noyau, ici avec un vrai port à l'écoute."""
        prise = socket.socket()
        self.addCleanup(prise.close)
        prise.bind(("127.0.0.1", 0))
        prise.listen()
        pris = prise.getsockname()[1]
        self.assertEtat(self.diagnostic("--port", str(pris), absents=("ss",)), f"Port {pris}", "To fix")
        libre = socket.socket()
        libre.bind(("127.0.0.1", 0))
        port_libre = libre.getsockname()[1]
        libre.close()
        self.assertEtat(self.diagnostic("--port", str(port_libre), absents=("ss",)), f"Port {port_libre}", "OK")


class NomDeDomaineTests(AidesDiagnostic, SimpleTestCase):
    def domaine(self, nom_pointe, adresses, **valeurs):
        return self.diagnostic("--domain", "reporting.example.com", F_ADRESSES_DU_NOM=nom_pointe,
                               F_MES_ADRESSES=adresses, **valeurs)

    def test_le_nom_pointe_vers_ce_serveur(self):
        r = self.domaine("203.0.113.10", "10.0.0.4 203.0.113.10 2001:db8::4")
        self.assertEtat(r, "Domain name reporting.example.com", "OK", "this server (203.0.113.10)")
        self.assertPret(r)

    def test_nom_absent_du_dns(self):
        r = self.domaine("", "203.0.113.10")
        self.assertEtat(r, "Domain name", "To fix", "DNS record")
        self.assertEqual(r.returncode, 1)

    def test_nom_vers_une_autre_machine(self):
        r = self.domaine("198.51.100.7", "203.0.113.10")
        self.assertEtat(r, "Domain name", "To fix", "points to 198.51.100.7", "203.0.113.10")
        self.assertEqual(r.returncode, 1)

    def test_derriere_un_routeur_non_verifie_plutot_qu_un_faux_non(self):
        r = self.domaine("198.51.100.7", "192.168.1.20")
        self.assertEtat(r, "Domain name", "Not checked", "only private addresses", "198.51.100.7")
        self.assertPret(r)
        self.assertIn("Ready. 1 point(s) not checked", r.stdout)
        # adresse privée d'une autre machine : jamais un certificat automatique depuis Internet
        self.assertEtat(self.domaine("192.168.1.30", "192.168.1.20"), "Domain name", "To fix")

    def test_sans_domaine_aucun_controle_du_nom(self):
        r = self.diagnostic()
        self.assertNotIn("Domain name", r.stdout)
        self.assertNotIn("Port 80:", r.stdout)


class ReseauTests(AidesDiagnostic, SimpleTestCase):
    def test_image_publiee_registre_et_github(self):
        r = self.diagnostic("--image", IMAGE)
        appels = journal_reseau(r.tmp)
        for url in ("https://ghcr.io/v2/", "https://pkg-containers.githubusercontent.com/",
                    "https://github.com/Probant-Reporting/probant", "https://raw.githubusercontent.com/"):
            self.assertTrue([a for a in appels if a.startswith("curl ") and a.endswith(" " + url)], (url, appels))
        self.assertEtat(r, "ghcr.io (image)", "OK", "reachable")

    def test_registre_inaccessible(self):
        r = self.diagnostic("--image", IMAGE, F_BLOQUES="ghcr.io")
        self.assertEtat(r, "ghcr.io (image)", "To fix", "TCP 443", "HTTPS_PROXY")
        self.assertManque(r, "ghcr.io")

    def test_github_inaccessible(self):
        r = self.diagnostic("--image", IMAGE, F_BLOQUES="raw.githubusercontent.com")
        self.assertEtat(r, "raw.githubusercontent.com (files of the version)", "To fix")
        self.assertEqual(r.returncode, 1)

    def test_construction_sur_le_serveur(self):
        r = self.diagnostic()
        for hote in ("registry-1.docker.io", "pypi.org", "files.pythonhosted.org", "github.com"):
            self.assertEtat(r, hote, "OK")
        self.assertNotIn("ghcr.io", r.stdout)
        self.assertEtat(self.diagnostic(F_BLOQUES="pypi.org"), "pypi.org", "To fix")

    def test_registre_sur_la_machine_en_http(self):
        r = self.diagnostic("--image", "127.0.0.1:5000/probant:9.9.1")
        self.assertEtat(r, "127.0.0.1:5000 (image)", "OK")
        self.assertTrue([a for a in journal_reseau(r.tmp) if a.endswith(" http://127.0.0.1:5000/v2/")])
        # avec un proxy, une adresse de NO_PROXY n'y passe pas : la ligne ne le dit pas
        r = self.diagnostic("--image", "127.0.0.1:5000/probant:9.9.1", HTTPS_PROXY="http://proxy.test:3128")
        self.assertEqual(self.assertEtat(r, "127.0.0.1:5000 (image)", "OK"), "127.0.0.1:5000 (image): reachable")
        self.assertEtat(r, "github.com", "OK", "through the proxy http://proxy.test:3128")

    def test_par_un_proxy_sans_son_mot_de_passe(self):
        proxy = {"HTTPS_PROXY": "http://compte:secret@proxy.test:3128", "F_DOCKER_PROXY": "http://proxy.test:3128"}
        r = self.diagnostic("--image", IMAGE, **proxy)
        self.assertEtat(r, "ghcr.io (image)", "OK", "through the proxy http://proxy.test:3128")
        self.assertNotIn("secret", r.stdout)
        r = self.diagnostic("--image", IMAGE, F_BLOQUES="ghcr.io", **proxy)
        self.assertEtat(r, "ghcr.io (image)", "To fix", "allow ghcr.io on the proxy")
        self.assertNotIn("secret", r.stdout)

    def test_proxy_que_docker_n_utilise_pas(self):
        proxy = {"HTTPS_PROXY": "http://proxy.test:3128"}
        r = self.diagnostic("--image", IMAGE, F_DIRECT="non", **proxy)
        self.assertEtat(r, "Proxy of Docker", "To fix", "docs.docker.com/engine/daemon/proxy")
        self.assertEqual(r.returncode, 1)
        # le registre répond aussi sans le proxy : rien à régler
        self.assertEtat(self.diagnostic("--image", IMAGE, F_DIRECT="oui", **proxy), "Proxy of Docker", "OK")
        # Docker a son proxy, ou pas de proxy du tout : aucune ligne
        self.assertNotIn("Proxy of Docker", self.diagnostic("--image", IMAGE, F_DIRECT="non", F_DOCKER_PROXY="http://p:3128", **proxy).stdout)
        self.assertNotIn("Proxy of Docker", self.diagnostic("--image", IMAGE, F_DIRECT="non").stdout)

    def test_sans_curl(self):
        r = self.diagnostic("--image", IMAGE, absents=("curl",))
        self.assertEtat(r, "curl", "To fix", "apt-get install -y curl")
        self.assertEqual(r.returncode, 1)

    def test_hors_ligne_aucune_requete(self):
        r = self.diagnostic("--offline")
        self.assertPret(r)
        self.assertEtat(r, "Network", "Not checked", "--offline")
        self.assertFalse([a for a in journal_reseau(r.tmp) if a.startswith("curl")])


class HorlogeTests(AidesDiagnostic, SimpleTestCase):
    def test_horloge_juste(self):
        self.assertEtat(self.diagnostic(F_DATE=date_http(-90)), "Clock", "OK", "compared with github.com")

    def test_horloge_decalee(self):
        r = self.diagnostic(F_DATE=date_http(-2 * 3600))
        self.assertEtat(r, "Clock", "To fix", "120 minutes", "timedatectl set-ntp true")
        self.assertEqual(r.returncode, 1)

    def test_date_impossible(self):
        r = self.diagnostic(F_MAINTENANT="0")
        self.assertEtat(r, "Clock", "To fix", "1970-01-01")
        self.assertEqual(r.returncode, 1)
        self.assertEtat(self.diagnostic("--offline", F_MAINTENANT="0"), "Clock", "To fix")

    def test_sans_reference(self):
        self.assertEtat(self.diagnostic(F_DATE=""), "Clock", "Not checked", "No reference time")
        self.assertEtat(self.diagnostic("--offline"), "Clock", "OK", "plausible")


class ScriptTests(SimpleTestCase):
    def test_posix_et_executable(self):
        self.assertEqual(subprocess.run(["sh", "-n", str(RACINE / "check.sh")]).returncode, 0)
        self.assertTrue((RACINE / "check.sh").stat().st_mode & 0o111)

    def test_minimums_du_guide(self):
        """Les minimums du contrôle sont ceux de la section 1 du guide d'installation."""
        guide = (RACINE / "docs" / "installation.md").read_text(encoding="utf-8")
        self.assertIn("1 CPU, 1 GB of memory, 5 GB of disk", guide)
        self.assertIn("Docker Engine 24 or later with the Compose plugin v2.24 or later", guide)
        script = (RACINE / "check.sh").read_text(encoding="utf-8")
        self.assertIn('MIN_DOCKER="24.0.0" ; MIN_COMPOSE="2.24.0"', script)
