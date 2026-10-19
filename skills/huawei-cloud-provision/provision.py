#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "huaweicloudsdkcore==3.1.218",
#   "huaweicloudsdkvpc==3.1.218",
#   "huaweicloudsdkecs==3.1.218",
#   "huaweicloudsdkrds==3.1.218",
#   "huaweicloudsdkdcs==3.1.218",
#   "huaweicloudsdkeps==3.1.218",
# ]
# ///
"""Provision the KJB demo; deployment instructions are in the adjacent SKILL.md.

No Huawei Cloud calls happen during import, argument parsing, or missing-credential
validation. SDK credentials and passwords are never written to disk or logged.
"""

import argparse
import ipaddress
import os
import re
import sys
import time
from urllib.parse import quote

from huaweicloudsdkcore.auth.credentials import BasicCredentials, GlobalCredentials
from huaweicloudsdkcore.exceptions import exceptions
from huaweicloudsdkcore.http.http_config import HttpConfig
from huaweicloudsdkvpc import v2 as vpc
from huaweicloudsdkvpc.v2.region.vpc_region import VpcRegion
from huaweicloudsdkecs import v2 as ecs
from huaweicloudsdkecs.v2.region.ecs_region import EcsRegion
from huaweicloudsdkrds import v3 as rds
from huaweicloudsdkrds.v3.region.rds_region import RdsRegion
from huaweicloudsdkdcs import v2 as dcs
from huaweicloudsdkdcs.v2.region.dcs_region import DcsRegion
from huaweicloudsdkeps import v1 as eps


ENTERPRISE_PROJECT = "HC-2026a-02"
NAMES = {"vpc": "vpc-kjb", "subnet": "subnet-kjb", "sg": "sg-kjb",
         "ecs": "ecs-kjb", "rds": "rds-kjb", "dcs": "dcs-kjb"}
CIDR = "192.168.0.0/24"
ADMIN_GRANTS = """Admin prerequisites:
  IAM user: enable programmatic access and issue an AK/SK pair.
  Grant policies: RDS FullAccess and DCS FullAccess.
  Scope: enterprise project HC-2026a-02.
  VPC/ECS permissions are already present; retain them.
  Set HUAWEICLOUD_SDK_AK / HUAWEICLOUD_SDK_SK / HUAWEICLOUD_REGION.
  Enterprise-project discovery also needs eps:enterpriseProjects:list, or supply
  the admin-confirmed HC-2026a-02 UUID in HUAWEICLOUD_ENTERPRISE_PROJECT_ID.
"""


class ProvisionError(Exception):
    """A short, actionable error safe to display without a traceback."""


def log(message):
    print(message, file=sys.stderr)


def required(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise ProvisionError(f"Missing required environment variable: {name}")
    return value


def password(name):
    # Do not strip passwords: the supplied value is also used by `env`.
    value = os.environ.get(name, "")
    if not 8 <= len(value) <= 32 or any(c in value for c in "\r\n\x00"):
        raise ProvisionError(f"{name} must contain 8–32 characters, without newlines/NUL.")
    if sum(bool(re.search(p, value)) for p in (r"[a-z]", r"[A-Z]", r"[0-9]", r"[^a-zA-Z0-9]")) < 3:
        raise ProvisionError(f"{name} needs at least three of lowercase, uppercase, digits, symbols.")
    return value


def one(items, name):
    matches = [item for item in items if item.name == name]
    if len(matches) > 1:
        raise ProvisionError(f"Multiple resources named {name}; resolve ambiguity in the console.")
    return matches[0] if matches else None


def ensure(condition, message):
    if not condition:
        raise ProvisionError(message)


class Cloud:
    def __init__(self, timeout):
        missing = [key for key in ("HUAWEICLOUD_SDK_AK", "HUAWEICLOUD_SDK_SK")
                   if not os.environ.get(key, "").strip()]
        if missing:
            raise ProvisionError("Missing credentials: " + ", ".join(missing) + "\n" + ADMIN_GRANTS)
        self.region = os.environ.get("HUAWEICLOUD_REGION", "ap-southeast-1")
        self.timeout = timeout
        ak, sk = required("HUAWEICLOUD_SDK_AK"), required("HUAWEICLOUD_SDK_SK")
        credentials = BasicCredentials(ak, sk, os.environ.get("HUAWEICLOUD_PROJECT_ID"))
        config = HttpConfig.get_default_config()
        config.timeout = 30
        self.vpc = vpc.VpcClient.new_builder().with_credentials(credentials).with_region(
            VpcRegion.value_of(self.region)).with_http_config(config).build()
        self.ecs = ecs.EcsClient.new_builder().with_credentials(credentials).with_region(
            EcsRegion.value_of(self.region)).with_http_config(config).build()
        self.rds = rds.RdsClient.new_builder().with_credentials(credentials).with_region(
            RdsRegion.value_of(self.region)).with_http_config(config).build()
        self.dcs = dcs.DcsClient.new_builder().with_credentials(credentials).with_region(
            DcsRegion.value_of(self.region)).with_http_config(config).build()
        project_id = os.environ.get("HUAWEICLOUD_ENTERPRISE_PROJECT_ID", "")
        if project_id:
            ensure(bool(re.fullmatch(r"[0-9a-fA-F-]{36}", project_id)),
                   "HUAWEICLOUD_ENTERPRISE_PROJECT_ID must be the UUID for HC-2026a-02, not 0.")
            self.ep = project_id
        else:
            client = eps.EpsClient.new_builder().with_credentials(GlobalCredentials(ak, sk)).with_endpoint(
                "https://eps.myhuaweicloud.com").with_http_config(config).build()
            projects = self.offset_pages(client.list_enterprise_project, eps.ListEnterpriseProjectRequest,
                                         "enterprise_projects", name=ENTERPRISE_PROJECT, status=1)
            project = one(projects, ENTERPRISE_PROJECT)
            ensure(project is not None, f"Enterprise project {ENTERPRISE_PROJECT} was not found.")
            self.ep = project.id

    @staticmethod
    def offset_pages(method, request, field, page_number=False, **kwargs):
        offset = 1 if page_number else 0
        items = []
        while True:
            batch = getattr(method(request(offset=offset, limit=100, **kwargs)), field) or []
            items.extend(batch)
            if len(batch) < 100:
                return items
            # ECS uses a page number; RDS/DCS/EPS use an item offset.
            offset += 1 if page_number else len(batch)

    @staticmethod
    def marker_pages(method, request, field, **kwargs):
        items, marker = [], None
        while True:
            batch = getattr(method(request(marker=marker, limit=100, **kwargs)), field) or []
            items.extend(batch)
            if len(batch) < 100:
                return items
            ensure(batch[-1].id != marker, "Pagination did not advance; refusing partial discovery.")
            marker = batch[-1].id

    def inventory(self):
        # Read RDS/DCS first: the competition IAM user currently lacks these policies.
        databases = self.offset_pages(self.rds.list_instances, rds.ListInstancesRequest,
                                     "instances", eps_id=self.ep)
        caches = self.offset_pages(self.dcs.list_instances, dcs.ListInstancesRequest,
                                  "instances", name=NAMES["dcs"], name_equal="true")
        cache = one(caches, NAMES["dcs"])
        if cache:
            cache = self.dcs.show_instance(dcs.ShowInstanceRequest(instance_id=cache.instance_id))
            ensure(cache.enterprise_project_id == self.ep,
                   "dcs-kjb belongs to another enterprise project; refusing to reuse/delete it.")
        result = {
            "rds": one(databases, NAMES["rds"]), "dcs": cache,
            "vpc": one(self.marker_pages(self.vpc.list_vpcs, vpc.ListVpcsRequest, "vpcs",
                                         enterprise_project_id=self.ep), NAMES["vpc"]),
            "sg": one(self.marker_pages(self.vpc.list_security_groups, vpc.ListSecurityGroupsRequest,
                                        "security_groups", enterprise_project_id=self.ep), NAMES["sg"]),
            "ecs": one(self.offset_pages(self.ecs.list_servers_details, ecs.ListServersDetailsRequest,
                                         "servers", page_number=True, enterprise_project_id=self.ep), NAMES["ecs"]),
        }
        result["subnet"] = one(self.marker_pages(self.vpc.list_subnets, vpc.ListSubnetsRequest,
                                                "subnets"), NAMES["subnet"])
        self.validate(result)
        return result

    def validate(self, found):
        network, subnet, group = (found[key] for key in ("vpc", "subnet", "sg"))
        if network:
            ensure(ipaddress.ip_network(CIDR).subnet_of(ipaddress.ip_network(network.cidr)),
                   "vpc-kjb does not contain 192.168.0.0/24; resolve network drift manually.")
        if subnet:
            ensure(network and subnet.vpc_id == network.id and subnet.cidr == CIDR,
                   "subnet-kjb has a different VPC/CIDR; refusing replacement.")
        if group:
            ensure(network and group.vpc_id in (None, "", network.id),
                   "sg-kjb belongs to a different VPC.")
        for key in ("rds", "dcs"):
            obj = found[key]
            if not obj:
                continue
            ensure(network and subnet and obj.vpc_id == network.id
                   and obj.subnet_id == subnet.neutron_network_id,
                   f"{NAMES[key]} uses a different VPC/subnet; refusing reuse/deletion.")
            if key == "rds":
                ensure(group and obj.security_group_id == group.id
                       and obj.datastore.type == "PostgreSQL" and obj.datastore.version.startswith("16")
                       and obj.type.lower() == "single" and obj.volume.size == 40,
                       "rds-kjb differs from PostgreSQL 16 / single / 40 GB / sg-kjb.")
                ensure(obj.charge_info and obj.charge_info.charge_mode == "postPaid",
                       "rds-kjb is not pay-per-use; refusing to manage it.")
            else:
                capacity = float(obj.capacity_minor or obj.capacity or 0)
                ensure(obj.engine == "Redis" and obj.engine_version.startswith("7")
                       and obj.cache_mode == "single" and capacity == 0.125
                       and str(obj.charging_mode) == "0" and not obj.enable_publicip
                       and str(obj.no_password_access).lower() == "false",
                       "dcs-kjb differs from private/password-protected Redis 7 / single / 0.125 GB / pay-per-use.")
        if found["ecs"]:
            server = found["ecs"]
            ensure(network and subnet and group and server.flavor.id == "c9.large.2",
                   "ecs-kjb requires the existing network and c9.large.2 flavor.")
            nics = self.ecs.list_server_interfaces(ecs.ListServerInterfacesRequest(server_id=server.id))
            ensure(any(nic.net_id == subnet.neutron_network_id for nic in nics.interface_attachments or []),
                   "ecs-kjb is not connected to subnet-kjb.")
            ensure(any(g.id == group.id for g in server.security_groups or []),
                   "ecs-kjb does not have sg-kjb attached.")

    def wait(self, label, fetch, ready):
        deadline = time.monotonic() + self.timeout
        previous = None
        while time.monotonic() < deadline:
            obj = fetch()
            status = getattr(obj, "status", "pending") if obj else "pending"
            if status != previous:
                log(f"{label}: {status}")
                previous = status
            ensure(str(status).upper() not in {"ERROR", "FAILED", "FAIL", "FROZEN", "CREATEFAILED"},
                   f"{label} entered {status}; inspect it in the console before rerunning.")
            if obj and ready(obj):
                return obj
            time.sleep(10)
        raise ProvisionError(f"Timed out waiting for {label}. Resources may still be billing; rerun plan.")

    def rds_by_id(self, instance_id):
        instances = self.rds.list_instances(rds.ListInstancesRequest(id=instance_id)).instances or []
        return next((item for item in instances if item.id == instance_id), None)

    def catalogs(self, found):
        selected = {}
        zone = os.environ.get("HUAWEICLOUD_AVAILABILITY_ZONE")
        if not found["rds"]:
            flavors = self.rds.list_flavors(rds.ListFlavorsRequest(
                database_name="PostgreSQL", version_name="16")).flavors or []
            available = [(f, az) for f in flavors if f.instance_mode == "single"
                         for az, status in (f.az_status or {}).items()
                         if status == "normal" and (not zone or az == zone)]
            ensure(available, "No PostgreSQL 16 single flavor is on sale in the selected region/AZ.")
            flavor, az = min(available, key=lambda pair: (int(pair[0].ram), int(pair[0].vcpus),
                                                        pair[0].spec_code, pair[1]))
            # Storage types are tied to the selected flavor family.
            disk = {"general": "CLOUDSSD", "dedicated": "CLOUDSSD", "rapid": "ESSD",
                    "armlocalssd": "LOCALSSD", "normallocalssd": "LOCALSSD"}.get(
                        flavor.group_type, "ULTRAHIGH")
            selected["rds"] = (flavor.spec_code, az, disk)
            log(f"RDS selection: {flavor.spec_code}, {flavor.ram} GB RAM, {flavor.vcpus} vCPU, {az}, {disk} 40 GB")
        if not found["dcs"]:
            flavors = self.dcs.list_flavors(dcs.ListFlavorsRequest(
                cache_mode="single", engine="Redis", engine_version="7.0", capacity="0.125")).flavors or []
            available = [(f.spec_code, az) for f in flavors
                         if f.cache_mode == "single" and "Hourly" in (f.billing_mode or [])
                         for stock in f.flavors_available_zones or [] if float(stock.capacity) == 0.125
                         for az in stock.az_codes or [] if not zone or az == zone]
            ensure(available, "Redis 7.0 single 0.125 GB pay-per-use is unavailable in this region/AZ; no larger fallback.")
            selected["dcs"] = sorted(available)[0]
            log(f"DCS selection: {selected['dcs'][0]}, {selected['dcs'][1]}, 0.125 GB")
        return selected

    def rules(self, group_id, ssh_cidr, apply=False):
        existing = self.marker_pages(self.vpc.list_security_group_rules, vpc.ListSecurityGroupRulesRequest,
                                     "security_group_rules", security_group_id=group_id) if group_id else []
        desired = [("ingress", 80, "0.0.0.0/0", None), ("ingress", 443, "0.0.0.0/0", None),
                   ("ingress", 5432, None, group_id), ("egress", None, "0.0.0.0/0", None)]
        if ssh_cidr:
            desired.append(("ingress", 22, ssh_cidr, None))
        for direction, port, cidr, remote_group in desired:
            if any(rule.direction == direction and rule.ethertype == "IPv4"
                   and rule.protocol == ("tcp" if port else None)
                   and rule.port_range_min == port and rule.port_range_max == port
                   and rule.remote_ip_prefix == cidr and rule.remote_group_id == remote_group
                   for rule in existing):
                continue
            log(f"{'Add' if apply else 'Would add'} SG {direction}: {port or 'all'} from/to {cidr or 'sg-kjb'}")
            if apply:
                self.vpc.create_security_group_rule(vpc.CreateSecurityGroupRuleRequest(
                    body=vpc.CreateSecurityGroupRuleRequestBody(security_group_rule=vpc.CreateSecurityGroupRuleOption(
                        security_group_id=group_id, direction=direction, ethertype="IPv4",
                        protocol="tcp" if port else None, port_range_min=port, port_range_max=port,
                        remote_ip_prefix=cidr, remote_group_id=remote_group))))
        # Never silently delete existing rules: surface broad database/SSH exposure.
        for rule in existing:
            if rule.direction == "ingress" and rule.remote_ip_prefix in {"0.0.0.0/0", "::/0"}:
                lo, hi = rule.port_range_min or 0, rule.port_range_max or 65535
                if rule.protocol in (None, "tcp", "6") and any(lo <= p <= hi for p in (22, 5432, 6379)):
                    raise ProvisionError("sg-kjb exposes SSH/database ports to the world; restrict that rule in the console.")

    def database(self, instance_id, apply=False):
        users = []
        page = 1
        while True:
            batch = self.rds.list_postgresql_db_user_paginated(rds.ListPostgresqlDbUserPaginatedRequest(
                instance_id=instance_id, page=page, limit=100)).users or []
            users.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        databases = self.rds.list_postgresql_databases(rds.ListPostgresqlDatabasesRequest(
            instance_id=instance_id, db="kjb", page=1, limit=100)).databases or []
        db = one(databases, "kjb")
        if db:
            ensure(db.owner == "kjb", "Existing kjb database is not owned by kjb; resolve permissions manually.")
        if not any(user.name == "kjb" for user in users):
            log("Create database user kjb" if apply else "Would create database user kjb")
            if apply:
                self.rds.create_postgresql_db_user(rds.CreatePostgresqlDbUserRequest(
                    instance_id=instance_id, body=rds.PostgresqlUserForCreation(name="kjb", password=password("PG_PASSWORD"))))
        if not db:
            log("Create database kjb owned by kjb" if apply else "Would create database kjb owned by kjb")
            if apply:
                self.rds.create_postgresql_database(rds.CreatePostgresqlDatabaseRequest(
                    instance_id=instance_id, body=rds.PostgresqlDatabaseForCreation(
                        name="kjb", owner="kjb", character_set="UTF8", is_revoke_public_privilege=True)))

    @staticmethod
    def addresses(server, kind):
        return [address.addr for addresses in (server.addresses or {}).values() for address in addresses
                if address.os_ext_ip_stype == kind and str(address.version) == "4"]

    def whitelist(self, cache, server, apply=False):
        ips = self.addresses(server, "fixed")
        ensure(ips, "ecs-kjb has no private IPv4 address for the DCS whitelist.")
        wanted = sorted(f"{ip}/32" for ip in ips if ipaddress.ip_address(ip) in ipaddress.ip_network(CIDR))
        ensure(wanted, "ecs-kjb has no private address in subnet-kjb.")
        current = self.dcs.show_ip_whitelist(dcs.ShowIpWhitelistRequest(instance_id=cache.instance_id))
        groups = current.whitelist or []
        managed = next((group for group in groups if group.group_name == "kjb-ecs"), None)
        if current.enable_whitelist and managed and sorted(managed.ip_list or []) == wanted:
            return
        ensure(managed is not None or len(groups) < 4, "DCS already has four whitelist groups; free one slot.")
        log("Set DCS whitelist kjb-ecs to ECS private /32" if apply else "Would enable/update DCS whitelist kjb-ecs")
        if apply:
            groups = [group for group in groups if group.group_name != "kjb-ecs"]
            groups.append(dcs.Whitelist(group_name="kjb-ecs", ip_list=wanted))
            self.dcs.update_ip_whitelist(dcs.UpdateIpWhitelistRequest(instance_id=cache.instance_id,
                body=dcs.ModifyIpWhitelistBody(instance_id=cache.instance_id, enable_whitelist=True, whitelist=groups)))

    def apply(self, found, selected, ssh_cidr):
        # Check every local input before creating any billable or network resource.
        password("PG_PASSWORD")
        if not found["rds"]:
            password("RDS_PASSWORD")
        if not found["dcs"]:
            password("REDIS_PASSWORD")
        if not found["ecs"]:
            required("HUAWEICLOUD_IMAGE_ID")  # Ubuntu 24.04 x86_64, selected in this region's console.
            required("HUAWEICLOUD_KEY_NAME")
        if not found["vpc"]:
            found["vpc"] = self.vpc.create_vpc(vpc.CreateVpcRequest(body=vpc.CreateVpcRequestBody(
                vpc=vpc.CreateVpcOption(name=NAMES["vpc"], cidr=CIDR, enterprise_project_id=self.ep)))).vpc
        network = found["vpc"]
        self.wait(NAMES["vpc"], lambda: self.vpc.show_vpc(vpc.ShowVpcRequest(vpc_id=network.id)).vpc,
                  lambda obj: obj.status == "OK")
        if not found["subnet"]:
            found["subnet"] = self.vpc.create_subnet(vpc.CreateSubnetRequest(body=vpc.CreateSubnetRequestBody(
                subnet=vpc.CreateSubnetOption(name=NAMES["subnet"], vpc_id=network.id, cidr=CIDR,
                    gateway_ip="192.168.0.1", dhcp_enable=True, primary_dns="100.125.1.250",
                    secondary_dns="100.125.21.250")))).subnet
        subnet = found["subnet"]
        subnet = self.wait(NAMES["subnet"], lambda: self.vpc.show_subnet(vpc.ShowSubnetRequest(subnet_id=subnet.id)).subnet,
                           lambda obj: obj.status == "ACTIVE")
        ensure(subnet.neutron_network_id, "Subnet has no network ID yet; rerun plan.")
        if not found["sg"]:
            found["sg"] = self.vpc.create_security_group(vpc.CreateSecurityGroupRequest(
                body=vpc.CreateSecurityGroupRequestBody(security_group=vpc.CreateSecurityGroupOption(
                    name=NAMES["sg"], vpc_id=network.id, enterprise_project_id=self.ep)))).security_group
        group = found["sg"]
        self.rules(group.id, ssh_cidr, apply=True)
        if not found["ecs"]:
            server = ecs.PostPaidServer(name=NAMES["ecs"], count=1, is_auto_rename=False,
                flavor_ref="c9.large.2", image_ref=required("HUAWEICLOUD_IMAGE_ID"),
                key_name=required("HUAWEICLOUD_KEY_NAME"), vpcid=network.id,
                availability_zone=os.environ.get("HUAWEICLOUD_AVAILABILITY_ZONE"),
                nics=[ecs.PostPaidServerNic(subnet_id=subnet.neutron_network_id)],
                root_volume=ecs.PostPaidServerRootVolume(volumetype="SSD", size=40),
                security_groups=[ecs.PostPaidServerSecurityGroup(id=group.id)],
                extendparam=ecs.PostPaidServerExtendParam(charging_mode=0, enterprise_project_id=self.ep),
                publicip=ecs.PostPaidServerPublicip(delete_on_termination=True, eip=ecs.PostPaidServerEip(
                    iptype=os.environ.get("HUAWEICLOUD_EIP_TYPE", "5_bgp"),
                    bandwidth=ecs.PostPaidServerEipBandwidth(size=5, sharetype="PER", chargemode="traffic"))))
            response = self.ecs.create_post_paid_servers(ecs.CreatePostPaidServersRequest(
                body=ecs.CreatePostPaidServersRequestBody(server=server)))
            ensure(response.job_id, "ECS create returned no job ID; inspect the console and rerun plan.")
            self.wait("ECS job", lambda: self.ecs.show_job(ecs.ShowJobRequest(job_id=response.job_id)),
                      lambda obj: obj.status == "SUCCESS")
            # Discover by exact name after the asynchronous job, never reissue create.
            found["ecs"] = one(self.offset_pages(self.ecs.list_servers_details, ecs.ListServersDetailsRequest,
                                                 "servers", page_number=True, enterprise_project_id=self.ep), NAMES["ecs"])
            ensure(found["ecs"], "ECS job finished but ecs-kjb is not visible; rerun plan.")
        server_id = found["ecs"].id
        found["ecs"] = self.wait(NAMES["ecs"], lambda: self.ecs.show_server(ecs.ShowServerRequest(server_id=server_id)).server,
                                  lambda obj: obj.status == "ACTIVE")
        if not found["rds"]:
            flavor, az, disk = selected["rds"]
            response = self.rds.create_instance(rds.CreateInstanceRequest(body=rds.CustomerCreateInstanceReq(
                name=NAMES["rds"], datastore=rds.Datastore(type="PostgreSQL", version="16"),
                password=password("RDS_PASSWORD"), flavor_ref=flavor, volume=rds.Volume(type=disk, size=40),
                region=self.region, availability_zone=az, vpc_id=network.id, subnet_id=subnet.neutron_network_id,
                security_group_id=group.id, enterprise_project_id=self.ep, charge_info=rds.ChargeInfo(charge_mode="postPaid"))))
            ensure(response.instance and response.instance.id, "RDS create returned no instance ID; inspect the console.")
            found["rds"] = response.instance
        instance_id = found["rds"].id
        found["rds"] = self.wait(NAMES["rds"], lambda: self.rds_by_id(instance_id), lambda obj: obj.status == "ACTIVE")
        self.database(instance_id, apply=True)
        if not found["dcs"]:
            spec, az = selected["dcs"]
            response = self.dcs.create_instance(dcs.CreateInstanceRequest(body=dcs.CreateInstanceBody(
                name=NAMES["dcs"], engine="Redis", engine_version="7.0", capacity=0.125,
                spec_code=spec, az_codes=[az], vpc_id=network.id, subnet_id=subnet.neutron_network_id,
                enterprise_project_id=self.ep, password=password("REDIS_PASSWORD"),
                no_password_access=False, enable_publicip=False, enable_ssl=False)))
            ensure(response.instances and len(response.instances) == 1,
                   "DCS create returned an unexpected instance count; inspect the console.")
            cache_id = response.instances[0].instance_id
        else:
            cache_id = found["dcs"].instance_id
        found["dcs"] = self.wait(NAMES["dcs"], lambda: self.dcs.show_instance(dcs.ShowInstanceRequest(instance_id=cache_id)),
                                  lambda obj: obj.status == "RUNNING")  # DCS's equivalent of ACTIVE.
        self.whitelist(found["dcs"], found["ecs"], apply=True)
        self.endpoints(found)

    @staticmethod
    def endpoints(found):
        database, cache, server = (found[key] for key in ("rds", "dcs", "ecs"))
        if database and database.private_ips:
            print(f"RDS private: {database.private_ips[0]}:{database.port or 5432}")
        if cache:
            print(f"DCS private: {cache.domain_name or cache.ip}:{cache.port or 6379}")
        if server:
            print("ECS public: " + (", ".join(Cloud.addresses(server, "floating")) or "none; attach an EIP manually"))

    def environment(self, found):
        database, cache = found["rds"], found["dcs"]
        ensure(database and cache and database.status == "ACTIVE" and cache.status == "RUNNING",
               "Both rds-kjb (ACTIVE) and dcs-kjb (RUNNING) are required; run apply first.")
        ensure(database.private_ips and (cache.domain_name or cache.ip), "Private endpoints are not ready.")
        # Validate both before emitting either line; percent encoding also prevents
        # dotenv interpolation of $, quotes, spaces, #, @, : and slash in passwords.
        pg, redis = quote(password("PG_PASSWORD"), safe=""), quote(password("REDIS_PASSWORD"), safe="")
        host = database.private_ips[0]
        cache_host = cache.domain_name or cache.ip
        scheme = "rediss" if cache.enable_ssl else "redis"
        print(f"DATABASE_URL=postgresql+psycopg://kjb:{pg}@{host}:{database.port or 5432}/kjb?sslmode=require")
        print(f"REDIS_URL={scheme}://:{redis}@{cache_host}:{cache.port or 6379}/0")

    def destroy(self, found):
        # Only exact-name, validated, enterprise-scoped database/cache instances.
        if found["dcs"]:
            cache_id = found["dcs"].instance_id
            self.dcs.delete_single_instance(dcs.DeleteSingleInstanceRequest(instance_id=cache_id))

            self.wait("dcs-kjb deletion", lambda: not (self.dcs.list_instances(
                dcs.ListInstancesRequest(instance_id=cache_id)).instances or []), bool)
        if found["rds"]:
            instance_id = found["rds"].id
            self.rds.delete_instance(rds.DeleteInstanceRequest(instance_id=instance_id))
            self.wait("rds-kjb deletion", lambda: not self.rds_by_id(instance_id), bool)
        log("Destroy complete: RDS/DCS only. ECS, EIP, disks, network and backups may still incur charges.")


def main():
    parser = argparse.ArgumentParser(description="Provision Kreng-jai Bridge on Huawei Cloud (pay-per-use only).",
                                     epilog="Credentials: HUAWEICLOUD_SDK_AK / HUAWEICLOUD_SDK_SK; see SKILL.md for prerequisites.")
    commands = parser.add_subparsers(dest="command", required=True)
    for command, help_text in [("plan", "Read-only discovery; show existing/missing resources"),
                               ("apply", "Create missing resources and wait for readiness"),
                               ("env", "Print DATABASE_URL/REDIS_URL only; contains secrets"),
                               ("destroy", "Delete rds-kjb/dcs-kjb only; data is lost")]:
        sub = commands.add_parser(command, help=help_text)
        sub.add_argument("--timeout", type=int, default=1800, help="Maximum wait seconds per resource (default: 1800)")
        if command == "destroy":
            sub.add_argument("--yes-delete", action="store_true", help="Explicitly confirm deleting RDS/DCS and their data")
    args = parser.parse_args()
    if args.command == "destroy" and not args.yes_delete:
        parser.error("destroy requires the typed confirmation flag --yes-delete (deletes rds-kjb/dcs-kjb data)")
    try:
        ensure(args.timeout > 0, "--timeout must be positive.")
        cloud = Cloud(args.timeout)
        log(ADMIN_GRANTS.rstrip())
        log(f"Region: {cloud.region}; enterprise project: {ENTERPRISE_PROJECT} ({cloud.ep})")
        found = cloud.inventory()
        if args.command == "env":
            cloud.environment(found)
        elif args.command == "destroy":
            cloud.destroy(found)
        else:
            for key, name in NAMES.items():
                obj = found[key]
                identifier = (getattr(obj, "id", None) or getattr(obj, "instance_id", None)) if obj else None
                log(f"{name}: existing {identifier}" if obj else f"{name}: would create")
            ssh_cidr = os.environ.get("HUAWEICLOUD_SSH_CIDR")
            if ssh_cidr:
                cidr = ipaddress.ip_network(ssh_cidr, strict=False)
                ensure(cidr.version == 4 and cidr.prefixlen > 0,
                       "HUAWEICLOUD_SSH_CIDR must restrict IPv4 SSH access (never 0.0.0.0/0).")
                ssh_cidr = str(cidr)
            cloud.rules(found["sg"].id if found["sg"] else None, ssh_cidr)
            selected = cloud.catalogs(found)
            if args.command == "apply":
                ensure(ssh_cidr, "Set HUAWEICLOUD_SSH_CIDR to your administrator IP/CIDR before apply.")
                cloud.apply(found, selected, ssh_cidr)
            else:
                if not ssh_cidr:
                    log("Before apply: set HUAWEICLOUD_SSH_CIDR to your administrator IP/CIDR.")
                if not found["ecs"]:
                    log("Before apply: HUAWEICLOUD_IMAGE_ID (Ubuntu 24.04 x86_64) and HUAWEICLOUD_KEY_NAME are required.")
                if found["rds"] and found["rds"].status == "ACTIVE":
                    cloud.database(found["rds"].id)
                else:
                    log("Would ensure PostgreSQL user kjb and database kjb (owner kjb) after RDS is ACTIVE.")
                if found["dcs"] and found["ecs"] and found["dcs"].status == "RUNNING":
                    cloud.whitelist(found["dcs"], found["ecs"])
                else:
                    log("Would enable DCS whitelist kjb-ecs for the ECS private IP after provisioning.")
                log("Read checks passed; create permissions/quotas cannot be proven by read-only plan.")
                cloud.endpoints(found)
        return 0
    except ProvisionError as exc:
        log(f"Error: {exc}")
    except exceptions.ClientRequestException as exc:
        # Error bodies can echo request fields/passwords. Show codes, not bodies.
        log(f"Huawei Cloud request failed: HTTP {exc.status_code}, code {exc.error_code}. Inspect the console.")
        if exc.status_code in (401, 403):
            log(ADMIN_GRANTS.rstrip())
    except (exceptions.SdkException, ValueError, KeyError, OSError):
        log("Cloud configuration/connection failed. Check region, project ID, credentials, network and SDK compatibility; no automatic create retry.")
    except KeyboardInterrupt:
        log("Interrupted. Resources may still be provisioning/billing; run plan before retrying.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
