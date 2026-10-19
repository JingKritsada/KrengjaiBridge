# Huawei Cloud provisioning skill

Tell your coding agent: “Load `skills/huawei-cloud-provision/SKILL.md` and provision
and deploy Kreng-jai Bridge on Huawei Cloud.” The skill guides the agent through
prerequisites, read-only planning, SDK provisioning, secret URL generation and SSH
deployment. No application dependencies or lockfiles are changed by the script.

```sh
uv run skills/huawei-cloud-provision/provision.py --help
uv run skills/huawei-cloud-provision/provision.py plan
uv run skills/huawei-cloud-provision/provision.py apply
uv run skills/huawei-cloud-provision/provision.py env  # SECRET output; redirect privately
uv run skills/huawei-cloud-provision/provision.py destroy --yes-delete
```

The current IAM user needs programmatic access (AK/SK), `RDS FullAccess` and
`DCS FullAccess`, scoped to enterprise project `HC-2026a-02`; existing VPC/ECS
permissions must remain. Without credentials, commands fail before calling APIs.
Plan checks read access; it cannot guarantee create authorization or quota.

Configuration comes exclusively from environment variables:

| Variable | Purpose |
| --- | --- |
| `HUAWEICLOUD_SDK_AK`, `HUAWEICLOUD_SDK_SK` | Required API credentials; never store in git |
| `HUAWEICLOUD_REGION` | Default `ap-southeast-1` (CN-Hong Kong) |
| `HUAWEICLOUD_ENTERPRISE_PROJECT_ID` | Optional admin-confirmed `HC-2026a-02` UUID; skips EPS discovery |
| `HUAWEICLOUD_PROJECT_ID` | Optional regional IAM project ID; avoids SDK IAM discovery |
| `HUAWEICLOUD_SSH_CIDR` | Required for apply; trusted administrator IPv4 CIDR |
| `HUAWEICLOUD_IMAGE_ID`, `HUAWEICLOUD_KEY_NAME` | Required when ECS is missing; Ubuntu 24.04 x86_64 image and existing keypair |
| `HUAWEICLOUD_AVAILABILITY_ZONE` | Optional AZ constraint for new instances |
| `HUAWEICLOUD_EIP_TYPE` | Default `5_bgp`; regional EIP type for a new ECS |
| `RDS_PASSWORD` | Admin password, required only when creating RDS |
| `PG_PASSWORD` | App database user password; required for apply/env |
| `REDIS_PASSWORD` | Required when creating DCS and generating URLs |

All passwords need 8–32 characters and three character classes. The script does
not recover or rotate existing passwords; supply the original values. `env` emits
only two dotenv lines on stdout; diagnostics go to stderr. PostgreSQL URLs assume
the app's SQLAlchemy psycopg 3 driver. Existing resources are validated and reused,
never resized or replaced. Run one provisioner at a time. After an uncertain
create result, inspect the console and rerun plan rather than blindly retrying.

Resources: `vpc-kjb`, `subnet-kjb` (`192.168.0.0/24`), `sg-kjb`, `ecs-kjb`
(`c9.large.2`), `rds-kjb` (PostgreSQL 16, single, smallest available RAM/vCPU,
40 GB), `dcs-kjb` (Redis 7.0, single, 0.125 GB). Everything created is pay-per-use.
RDS includes a dedicated `kjb` user and owned `kjb` database. DCS uses an ECS IP
whitelist. Availability/quotas are checked live only when you run a cloud command.
Destroy removes only RDS/DCS; ECS, EIP, disks, backups and networks remain.
Existing local database volumes remain available for rollback; data is not migrated.

SDK request classes (service namespace distinguishes duplicate class names):

- EPS v1: `ListEnterpriseProjectRequest`.
- VPC v2: `ListVpcsRequest`, `ShowVpcRequest`, `CreateVpcRequest`,
  `ListSubnetsRequest`, `ShowSubnetRequest`, `CreateSubnetRequest`,
  `ListSecurityGroupsRequest`, `CreateSecurityGroupRequest`,
  `ListSecurityGroupRulesRequest`, `CreateSecurityGroupRuleRequest`.
- ECS v2: `ListServersDetailsRequest`, `ListServerInterfacesRequest`,
  `CreatePostPaidServersRequest`, `ShowJobRequest`, `ShowServerRequest`.
- RDS v3: `ListInstancesRequest`, `ListFlavorsRequest`, `CreateInstanceRequest`
  (`CustomerCreateInstanceReq` body), `ListPostgresqlDbUserPaginatedRequest`,
  `CreatePostgresqlDbUserRequest`, `ListPostgresqlDatabasesRequest`,
  `CreatePostgresqlDatabaseRequest`, `DeleteInstanceRequest`.
- DCS v2: `ListInstancesRequest`, `ShowInstanceRequest`, `ListFlavorsRequest`,
  `CreateInstanceRequest` (`CreateInstanceBody` body), `ShowIpWhitelistRequest`,
  `UpdateIpWhitelistRequest`, `DeleteSingleInstanceRequest`.

References: [official Python SDK](https://github.com/huaweicloud/huaweicloud-sdk-python-v3),
[RDS create API](https://support.huaweicloud.com/api-rds/rds_01_0002.html),
[DCS create API](https://support.huaweicloud.com/api-dcs/CreateInstance.html),
[DCS whitelist controls](https://support.huaweicloud.com/intl/en-us/usermanual-dcs/dcs-ug-190812001.html).

Offline validation covers help, missing credentials and Python syntax. Actual cloud
creation and SSH deployment require an authorized account and have not been tested
by those offline checks.
