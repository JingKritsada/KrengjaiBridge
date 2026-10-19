---
name: huawei-cloud-provision
description: Provision and deploy Kreng-jai Bridge on Huawei Cloud with the official Python SDK, including managed PostgreSQL RDS and DCS Redis, or inspect and remove its managed databases.
---

# Kreng-jai Bridge on Huawei Cloud

Use when asked to stand up this repository's cloud stack or switch its ECS deployment
from container PostgreSQL/Redis to managed RDS/DCS. Run from the repository root.
Read [README.md](README.md) for configuration and SDK references. Use the adjacent
`provision.py` via `uv run`; its PEP 723 dependencies do not change the app's lockfile.
The script provisions infrastructure; the agent performs the SSH deployment below.

## Prerequisites: check before provisioning

The competition IAM user currently cannot use APIs or create RDS/DCS. If blocked,
stop and give the admin this exact request; never substitute container services
and claim managed RDS/DCS were provisioned:

> IAM user: enable programmatic access and issue an AK/SK pair.
> Grant policies: RDS FullAccess and DCS FullAccess.
> Scope: enterprise project HC-2026a-02.
> VPC/ECS permissions are already present; retain them.

Require `uv`, SSH/rsync, and exported `HUAWEICLOUD_SDK_AK`, `HUAWEICLOUD_SDK_SK`.
Set `HUAWEICLOUD_REGION=ap-southeast-1` (CN-Hong Kong).
Project discovery needs `eps:enterpriseProjects:list`; alternatively ask the admin
for HC-2026a-02's UUID and set `HUAWEICLOUD_ENTERPRISE_PROJECT_ID` to it.
`HUAWEICLOUD_PROJECT_ID` optionally supplies the regional IAM project ID; this is
different from the enterprise project UUID and avoids SDK IAM project discovery.
Read-only checks cannot prove create permissions; a 403 requires the grants above.

Use a secret manager or silent terminal input to export `RDS_PASSWORD` (RDS admin),
`PG_PASSWORD` (app user `kjb`) and `REDIS_PASSWORD`; use distinct strong passwords.
Passwords must be 8–32 characters with three of uppercase/lowercase/digits/symbols;
the provider may impose additional rules. Existing passwords are never reset.
For apply, set `HUAWEICLOUD_SSH_CIDR` to the administrator's public IPv4 `/32`.
If ECS is absent, also set `HUAWEICLOUD_IMAGE_ID` to a regional Ubuntu 24.04 x86_64
public image UUID and `HUAWEICLOUD_KEY_NAME` to an existing regional SSH keypair.
Have its matching private key locally. Optional `HUAWEICLOUD_AVAILABILITY_ZONE`
constrains new resources; leave unset for automatic available RDS/DCS zones.

## Provision and deploy

1. Run `uv run skills/huawei-cloud-provision/provision.py plan`.
   This reads APIs only: no creation, password changes, or deployment. Review the
   exact-name resources, catalog choices, missing inputs, SG rules and DCS whitelist.
   Resolve ambiguous names, wrong enterprise projects and configuration drift first.
2. Run `uv run skills/huawei-cloud-provision/provision.py apply`.
   Reuse exact-name resources; create only missing VPC/subnet/SG, ECS, RDS and DCS.
   RDS: PostgreSQL 16 single, smallest available RAM/vCPU flavor, 40 GB disk.
   DCS: Redis 7.0 single, 0.125 GB; fail if unavailable, without upsizing.
   ECS: `c9.large.2`, 40 GB SSD, 5 Mbit/s traffic-billed EIP if created.
   Wait for VPC `OK`, subnet/ECS/RDS `ACTIVE`, DCS `RUNNING` (its ready state).
   Create database user `kjb` and database `kjb` owned by it, and enable a DCS
   whitelist for the ECS private `/32`. Print endpoints without passwords.
   A timeout/error leaves resources intact; run plan before retrying. Use one
   provisioner at a time; exact-name checks do not provide a distributed lock.
3. Generate URLs into a private temporary file outside the repository:
   ```sh
   umask 077
   KJB_URLS=$(mktemp)
   uv run skills/huawei-cloud-provision/provision.py env > "$KJB_URLS"
   ```
   Proceed only if the command succeeds. Copy the two lines into the existing
   `.env.server`, replacing only `DATABASE_URL` and `REDIS_URL`; preserve all LINE,
   LLM, encryption and other settings. Never overwrite the full file with two lines.
   URLs encode passwords, use PostgreSQL `sslmode=require`, and use private endpoints.
   Keep the existing `PG_PASSWORD`/`REDIS_PASSWORD` values for fallback containers.
   For an existing deployment, back up `.env.server` privately before editing.
   Set mode 600 and remove the temporary URL file after use.
4. Set `KJB_SSH` to the image's SSH user and ECS EIP (for example `root@EIP`),
   configure the matching SSH key, and verify the server host key via the console.
   On a fresh ECS, install Docker Engine/Compose v2 and Caddy from trusted Ubuntu
   repositories (e.g. `sudo apt-get update && sudo apt-get install -y docker.io
   docker-compose-v2 caddy`). Check `sudo docker compose version` before deployment.
   Then transfer the source and the secret environment file separately:
   ```sh
   ssh "$KJB_SSH" 'mkdir -p ~/kreng-jai-bridge'
   rsync -az --exclude=.git --exclude=.venv --exclude='__pycache__' \
     --exclude='.env*' --exclude=data ./ "$KJB_SSH:kreng-jai-bridge/"
   rsync -az .env.server "$KJB_SSH:kreng-jai-bridge/.env.server"
   ssh "$KJB_SSH" 'cd ~/kreng-jai-bridge && chmod 600 .env.server && sudo docker compose --env-file .env.server -f deploy/docker-compose.yml up -d --build'
   ```
   The explicit `--env-file` supplies Compose's `${PG_PASSWORD}`/`${REDIS_PASSWORD}`
   interpolation; app `env_file` alone does not supply Compose interpolation.
5. On a fresh host, replace the example hostname in the deployed `deploy/Caddyfile`
   with the actual EIP's sslip.io name or configured DNS name. Install it as
   `/etc/caddy/Caddyfile`, run `sudo caddy validate --config /etc/caddy/Caddyfile`,
   then `sudo systemctl enable --now caddy && sudo systemctl reload caddy`.
   Verify locally with `curl -fsS http://127.0.0.1:8000/api/health` over SSH, then
   verify HTTPS `/api/health` externally and confirm DB/Redis connectivity. For an
   existing deployment retain its working Caddy hostname and LINE webhook URL.
   If a new hostname is used, update the LINE webhook configuration explicitly.

Switching backends requires `.env.server` edits only; do not edit app code or Compose.
The existing Compose `depends_on` still starts local PostgreSQL/Redis containers;
keep these and their volumes for rollback. RDS starts with an empty app database;
this workflow does not migrate historical data. If data must be retained, arrange
a separate verified migration before switching URLs. Do not reset demo data implicitly.

## Rollback, removal, cost and security

- Roll back by restoring the prior `.env.server` and repeating Compose `up -d --build`;
  fallback URLs point to `postgres:5432` and `redis:6379` with the original passwords.
  Data written to RDS after cutover is not copied back automatically.
- Only an explicit deletion request permits
  `uv run skills/huawei-cloud-provision/provision.py destroy --yes-delete`.
  The typed flag is mandatory. It deletes only `rds-kjb` and `dcs-kjb`, including
  their live data; snapshot/export important data first. It waits for deletion.
- Pay-per-use only; resources bill until deleted. No price promises: verify console
  estimates. ECS/EIP/disks and retained RDS backups can bill after destroy. Single
  instances are a competition/demo choice with no high availability.
- Never commit AK/SK, passwords, `.env.server` or generated URLs; disable shell tracing
  and avoid displaying secret output in agent logs. Provisioning credentials stay
  off ECS. Use a separate RDS app user, never the RDS admin account in the app.
- SG: public TCP 80/443, SSH 22 only from administrator CIDR, PostgreSQL 5432 only
  from `sg-kjb`; egress supports package downloads/APIs. No public DB/Redis ports.
  DCS Redis 7 uses its IP whitelist, not SG ingress; existing whitelist groups are
  preserved. Existing world-open SSH/DB SG rules block apply until restricted.
  DCS is password-protected/private; this demo creates Redis without TLS. Use
  provider-supported TLS and certificate verification before production use.
