# Security policy

## Report a vulnerability

Do not open a public issue for a security problem.

Report it in private on GitHub:

1. Open the repository page on GitHub.
2. Select **Security**.
3. Select **Report a vulnerability**.
4. Describe the problem, then select **Submit report**.

Only the maintainers can read the report.

Include these items when you can:

- The version of Probant. The version is shown at the bottom of each page of the tool.
- The type of installation: Docker or managed hosting, SQLite or PostgreSQL.
- The role of the account that you used: administrator, validator, contributor, reader or auditor.
- The steps to reproduce the problem.
- What an attacker can read or change.

Do not include real data: no values, no email addresses, no names of people or of organisations.

## What to expect

| Step | Time |
|---|---|
| We confirm that we received the report | 7 days or less |
| We tell you if we confirm the problem, and what we plan to do | 30 days or less |
| We publish a corrected version | As soon as the correction is tested |

We tell you when the corrected version is available. We ask you not to make the problem public before that.

## Supported versions

| Version | Security corrections |
|---|---|
| 1.0.x (the latest version) | Yes |

A security correction is a new version of the Docker image. To apply it, see
[Update the tool](docs/installation.md).

Each published image is signed, and each release has the list of the components of the image (SBOM) and a report of
their known vulnerabilities. To verify them, see “Verify the image” in [Installation](docs/installation.md).

## Scope

In scope: the code of this repository, and the Docker image that it builds.

Out of scope: the server, the domain name, HTTPS, the SMTP account and the copies of the backups. The IT team of
each installation manages them. See [Installation](docs/installation.md). The identity provider used for the sign-in with
a company account is also out of scope: the tool only checks its answers (see [Company sign-in](docs/single_sign_on.md)).
