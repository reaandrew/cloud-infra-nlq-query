#!/usr/bin/env python3
"""
Generates mock AWS Config snapshot data in the same JSON format that Config
delivers to S3. Uses the authoritative property schemas from
awslabs/aws-config-resource-schema (fetched via fetch_config_resource_schemas.sh)
to ensure field names, casing, and structure match real Config items.

Two output modes:

  Single file:
    ./generate_config_snapshot.py data/snap.json --count 100

  AWS Config S3 layout (gzipped, written under
  AWSLogs/{account}/Config/{region}/{Y}/{M}/{D}/ConfigSnapshot/...):
    ./generate_config_snapshot.py --s3-root data/s3 --count 100
"""

import argparse
import gzip
import io
import json
import random
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Top-level ConfigurationItem envelope fields. Everything else in the schema
# (configuration.*, supplementaryConfiguration.*) goes into the nested payload.
ENVELOPE_KEYS = {
    "accountId", "arn", "availabilityZone", "awsRegion",
    "configurationItemCaptureTime", "configurationItemDeliveryTime",
    "configurationItemStatus", "configurationStateId",
    "resourceCreationTime", "resourceId", "resourceName", "resourceType",
    "tags", "version", "relationships",
}

SINGULAR_EXCEPTIONS = {
    "status", "address", "access", "class", "analysis", "tenancy",
    "dns", "sse", "kms", "tls", "ipv6", "https",
    "ebs",  # singular block device sub-object
}

# Resource ID prefix conventions. Missing types fall back to rand_hex without
# a prefix (correct for name-based IDs like S3 buckets, IAM roles, KMS keys).
RESOURCE_ID_PREFIXES = {
    "AWS::EC2::Instance": "i",
    "AWS::EC2::Volume": "vol",
    "AWS::EC2::VPC": "vpc",
    "AWS::EC2::Subnet": "subnet",
    "AWS::EC2::SecurityGroup": "sg",
    "AWS::EC2::NetworkInterface": "eni",
    "AWS::EC2::NatGateway": "nat",
    "AWS::EC2::InternetGateway": "igw",
    "AWS::EC2::RouteTable": "rtb",
    "AWS::EC2::NetworkAcl": "acl",
    "AWS::EC2::VPCEndpoint": "vpce",
    "AWS::EC2::EIP": "eipalloc",
    "AWS::EC2::TransitGateway": "tgw",
}

# Resource types that live inside a VPC and should reference one consistently.
VPC_RESIDENT_TYPES = {
    "AWS::EC2::Instance", "AWS::EC2::Volume", "AWS::EC2::NetworkInterface",
    "AWS::EC2::NatGateway", "AWS::EC2::VPCEndpoint",
    "AWS::RDS::DBInstance", "AWS::RDS::DBCluster",
    "AWS::ElasticLoadBalancingV2::LoadBalancer",
    "AWS::ElasticLoadBalancing::LoadBalancer",
    "AWS::Lambda::Function",  # if VPC-attached
    "AWS::ECS::Service",
    "AWS::EKS::Cluster",
    "AWS::ElastiCache::CacheCluster",
    "AWS::Redshift::Cluster",
    "AWS::OpenSearch::Domain",
    "AWS::Elasticsearch::Domain",
}


def _iso(dt):
    """ISO-8601 with millisecond precision (matches AWS Config)."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    return _iso(datetime.now(timezone.utc))


def past_iso(max_days=180):
    delta = timedelta(days=random.randint(1, max_days),
                      hours=random.randint(0, 23),
                      minutes=random.randint(0, 59))
    return _iso(datetime.now(timezone.utc) - delta)


def rand_hex(n):
    return "".join(random.choices("0123456789abcdef", k=n))


def is_array_segment(name):
    lower = name.lower()
    if lower in SINGULAR_EXCEPTIONS:
        return False
    if lower.endswith("ss") or lower.endswith("us") or lower.endswith("is"):
        return False
    return lower.endswith("s")


# --- Value generators driven by field-name heuristics ----------------------

def gen_value(field_name, type_str, ctx):
    lower = field_name.lower()
    if type_str == "boolean":
        return _gen_bool(lower)
    if type_str == "integer":
        return _gen_int(lower)
    if type_str in ("double", "float"):
        return round(random.uniform(0, 100), 2)
    if type_str == "date":
        return past_iso()
    return _gen_string(lower, field_name, ctx)


def _gen_bool(lower):
    if "enabled" in lower or "encrypted" in lower or "active" in lower:
        return random.choices([True, False], weights=[0.8, 0.2])[0]
    if "delete" in lower or "public" in lower:
        return random.choices([True, False], weights=[0.2, 0.8])[0]
    return random.choice([True, False])


def _gen_int(lower):
    if "port" in lower:
        return random.choice([22, 80, 443, 3306, 5432, 6379, 8080, 9200, 27017])
    if "timeout" in lower:
        return random.choice([30, 60, 120, 300, 900])
    if "memory" in lower or "size" in lower:
        return random.choice([128, 256, 512, 1024, 2048, 4096])
    if "count" in lower:
        return random.randint(1, 10)
    if "percent" in lower:
        return random.randint(0, 100)
    if "retention" in lower or "period" in lower or "days" in lower:
        return random.choice([1, 7, 14, 30, 90])
    if "version" in lower:
        return random.randint(1, 10)
    return random.randint(0, 1000)


def _gen_string(lower, original, ctx):
    region = ctx["region"]
    account = ctx["account"]
    rtype = ctx["resource_type"]
    rid = ctx["resource_id"]
    env = ctx["env"]
    app = ctx["app"]

    # Pool-backed identifiers (consistency across the snapshot)
    if lower in ("vpcid",) and ctx.get("vpc_id"):
        return ctx["vpc_id"]
    if lower in ("subnetid",) and ctx.get("subnet_id"):
        return ctx["subnet_id"]
    if lower in ("groupid", "securitygroupid", "vpcsecuritygroupid") and ctx.get("sg_ids"):
        return random.choice(ctx["sg_ids"])
    if lower in ("kmskeyid", "kmsmasterkeyid", "masterkeyid") and ctx.get("kms_key_ids"):
        return random.choice(ctx["kms_key_ids"])
    if lower in ("kmskeyarn", "encryptionkeyarn") and ctx.get("kms_key_arns"):
        return random.choice(ctx["kms_key_arns"])

    if lower == "arn" or lower.endswith("arn"):
        service = rtype.split("::")[1].lower()
        return f"arn:aws:{service}:{region}:{account}:{rtype.split('::')[-1].lower()}/{rid}"

    if lower.endswith("id"):
        prefix = _id_prefix_for(lower)
        return f"{prefix}-{rand_hex(17)}" if prefix else rand_hex(20)

    if lower in ("name", "groupname", "rolename", "functionname",
                 "dbinstanceidentifier", "dbclusteridentifier"):
        return f"{env}-{app}-{original.replace('Name', '').lower() or 'resource'}"

    if "region" in lower:
        return region
    if "account" in lower:
        return account
    if "zone" in lower or "az" == lower:
        return ctx["az"]
    if "cidr" in lower:
        return f"10.{random.randint(0,255)}.{random.randint(0,255)}.0/{random.choice([16,24,28])}"
    if "ip" in lower and "address" in lower:
        return f"10.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}"
    if "url" in lower or "endpoint" in lower or "address" in lower:
        return f"{env}-{app}.{region}.amazonaws.com"
    if "email" in lower:
        return f"{app}@{env}.example.com"
    if "engine" in lower and "version" not in lower:
        return random.choice(["postgres", "mysql", "aurora-postgresql", "aurora-mysql"])
    if "runtime" in lower:
        return random.choice(["nodejs18.x", "nodejs20.x", "python3.11", "python3.12", "java17", "go1.x"])
    if "instancetype" in lower or "instanceclass" in lower:
        return random.choice(["t3.micro", "t3.small", "t3.medium", "m5.large", "m5.xlarge", "c5.large"])
    if "state" in lower or "status" in lower:
        return random.choice(["available", "active", "running", "OK"])
    if "protocol" in lower:
        return random.choice(["tcp", "udp", "https", "http"])
    if "key" in lower:
        return f"AKIA{rand_hex(16).upper()}"
    if "tag" in lower or "label" in lower:
        return env

    return f"{env}-{app}-{lower}"


def _id_prefix_for(lower):
    mapping = {
        "vpcid": "vpc", "subnetid": "subnet", "instanceid": "i",
        "imageid": "ami", "volumeid": "vol", "snapshotid": "snap",
        "groupid": "sg", "securitygroupid": "sg", "vpcsecuritygroupid": "sg",
        "routetableid": "rtb", "internetgatewayid": "igw",
        "natgatewayid": "nat", "networkinterfaceid": "eni",
        "networkaclid": "acl", "dhcpoptionsid": "dopt",
        "elasticipid": "eipalloc", "allocationid": "eipalloc",
        "keypairid": "key", "placementgroupid": "pg",
        "transitgatewayid": "tgw", "customergatewayid": "cgw",
        "vpngatewayid": "vgw", "vpnconnectionid": "vpn",
        "kmskeyid": "key", "certificateid": "cert",
    }
    return mapping.get(lower, "")


# --- Schema → nested object construction -----------------------------------

def insert_path(tree, parts, value):
    cur = tree
    for p in parts[:-1]:
        if p not in cur or not isinstance(cur[p], dict):
            cur[p] = {}
        cur = cur[p]
    cur[parts[-1]] = value


def arrayify(node):
    if not isinstance(node, dict):
        return node
    for k in list(node.keys()):
        v = node[k]
        if isinstance(v, dict):
            arrayify(v)
            if is_array_segment(k):
                node[k] = [v]
    return node


def build_item(resource_type, schema, ctx, relationships):
    nested = {}
    for path, type_str in schema.items():
        parts = path.split(".")
        if parts[0] in ENVELOPE_KEYS and parts[0] != "relationships":
            continue
        # We construct relationships ourselves below
        if parts[0] == "relationships":
            continue
        leaf_name = parts[-1]
        value = gen_value(leaf_name, type_str, ctx)
        insert_path(nested, parts, value)

    arrayify(nested)

    configuration = nested.pop("configuration", {})
    supplementary = nested.pop("supplementaryConfiguration", {})

    return {
        "relatedEvents": [],
        "relationships": relationships,
        "configuration": configuration,
        "supplementaryConfiguration": supplementary,
        "tags": ctx["tags"],
        "configurationItemVersion": "1.3",
        "configurationItemCaptureTime": now_iso(),
        "configurationStateId": random.randint(1_700_000_000_000, 1_900_000_000_000),
        "awsAccountId": ctx["account"],
        "configurationItemStatus": "OK",
        "resourceType": resource_type,
        "resourceId": ctx["resource_id"],
        "resourceName": ctx["resource_name"],
        "ARN": ctx["arn"],
        "awsRegion": ctx["region"],
        "availabilityZone": ctx["az"],
        "configurationStateMd5Hash": "",
        "resourceCreationTime": past_iso(),
    }


# --- Infrastructure pool ---------------------------------------------------

ENVS = ["production", "staging", "development", "test"]
TEAMS = ["platform", "backend", "frontend", "data", "security", "devops"]
APPS = ["web-app", "api-service", "worker", "scheduler", "gateway",
        "auth-service", "data-pipeline", "monitoring"]


def build_infra_pool(region, account, num_vpcs=2, subnets_per_vpc=3,
                     sgs_per_vpc=3, num_kms_keys=3):
    """Pre-allocate VPCs, subnets, SGs, and KMS keys that resources reference."""
    azs = [f"{region}{c}" for c in "abc"]
    vpcs = []
    for i in range(num_vpcs):
        env = ENVS[i % len(ENVS)]
        vpc_id = f"vpc-{rand_hex(17)}"
        cidr = f"10.{i*16}.0.0/16"
        subnets = []
        for j in range(subnets_per_vpc):
            subnets.append({
                "id": f"subnet-{rand_hex(17)}",
                "vpc_id": vpc_id,
                "az": azs[j % len(azs)],
                "cidr": f"10.{i*16}.{j}.0/24",
                "env": env,
            })
        sgs = []
        for j in range(sgs_per_vpc):
            sgs.append({
                "id": f"sg-{rand_hex(17)}",
                "vpc_id": vpc_id,
                "name": f"{env}-sg-{j}",
                "env": env,
            })
        vpcs.append({"id": vpc_id, "cidr": cidr, "env": env,
                     "subnets": subnets, "sgs": sgs})

    kms_keys = []
    for i in range(num_kms_keys):
        key_uuid = str(uuid.uuid4())
        kms_keys.append({
            "id": key_uuid,
            "arn": f"arn:aws:kms:{region}:{account}:key/{key_uuid}",
            "env": ENVS[i % len(ENVS)],
        })

    return {"vpcs": vpcs, "kms_keys": kms_keys}


def _build_arn(resource_type, region, account, resource_id):
    service = resource_type.split("::")[1].lower()
    short = resource_type.split("::")[-1].lower()
    # S3 ARNs have no region, no account, and no resource-type prefix
    if resource_type == "AWS::S3::Bucket":
        return f"arn:aws:s3:::{resource_id}"
    # IAM is global (no region) but still includes account
    if service == "iam":
        return f"arn:aws:iam::{account}:{short}/{resource_id}"
    return f"arn:aws:{service}:{region}:{account}:{short}/{resource_id}"


def _build_resource_id(resource_type):
    prefix = RESOURCE_ID_PREFIXES.get(resource_type)
    if prefix:
        return f"{prefix}-{rand_hex(17)}"
    return rand_hex(20)


def make_context(resource_type, region, account, vpc_assignment=None,
                 kms_pool=None):
    env = random.choice(ENVS)
    app = random.choice(APPS)
    team = random.choice(TEAMS)
    az = f"{region}{random.choice('abc')}"
    rid = _build_resource_id(resource_type)
    name = f"{env}-{app}-{resource_type.split('::')[-1].lower()}"
    arn = _build_arn(resource_type, region, account, rid)

    ctx = {
        "region": region, "account": account, "az": az,
        "env": env, "app": app, "team": team,
        "resource_type": resource_type, "resource_id": rid,
        "resource_name": name, "arn": arn,
        "tags": {"Name": name, "Environment": env,
                 "Team": team, "Application": app},
    }

    if vpc_assignment:
        vpc, subnet, sg_ids = vpc_assignment
        ctx["vpc_id"] = vpc["id"]
        ctx["subnet_id"] = subnet["id"]
        ctx["sg_ids"] = sg_ids
        ctx["az"] = subnet["az"]
        ctx["env"] = vpc["env"]
        ctx["tags"]["Environment"] = vpc["env"]

    if kms_pool:
        ctx["kms_key_ids"] = [k["id"] for k in kms_pool]
        ctx["kms_key_arns"] = [k["arn"] for k in kms_pool]

    return ctx


def assign_vpc(pool):
    vpc = random.choice(pool["vpcs"])
    subnet = random.choice(vpc["subnets"])
    sg_ids = [sg["id"] for sg in random.sample(vpc["sgs"], k=min(2, len(vpc["sgs"])))]
    return vpc, subnet, sg_ids


def vpc_relationships(vpc, subnet, sg_ids, account):
    rels = [
        {"resourceId": vpc["id"], "resourceType": "AWS::EC2::VPC",
         "name": "Is contained in Vpc"},
        {"resourceId": subnet["id"], "resourceType": "AWS::EC2::Subnet",
         "name": "Is contained in Subnet"},
    ]
    for sg_id in sg_ids:
        rels.append({"resourceId": sg_id, "resourceType": "AWS::EC2::SecurityGroup",
                     "name": "Is associated with SecurityGroup"})
    return rels


def _rebind_resource(ctx, resource_type, resource_id, region, account):
    """Reassign a pre-allocated resource ID to a context and refresh the ARN."""
    ctx["resource_type"] = resource_type
    ctx["resource_id"] = resource_id
    ctx["arn"] = _build_arn(resource_type, region, account, resource_id)


def _set_nested(obj, path, value):
    """Walk a nested structure of dicts and 1-element lists; set a leaf value.
    No-op if the path doesn't already exist."""
    cur = obj
    for i, key in enumerate(path):
        is_last = i == len(path) - 1
        if isinstance(cur, list):
            if not cur:
                return
            cur = cur[0]
        if not isinstance(cur, dict):
            return
        if is_last:
            cur[key] = value
            return
        if key not in cur:
            return
        cur = cur[key]


def link_items(items, account):
    """Post-generation pass that stitches cross-references by resource ID.

    Wires:
      - EC2 Instance <-> EBS Volume (attachments)
      - EC2 Instance <-> ENI (attachment)
      - Lambda Function  -> IAM Role
      - RDS DBInstance   -> RDS DBSubnetGroup
    """
    by_type = {}
    for it in items:
        by_type.setdefault(it["resourceType"], []).append(it)

    stats = {"volume_attachments": 0, "eni_attachments": 0,
             "lambda_role_links": 0, "rds_subnetgroup_links": 0}

    instances = by_type.get("AWS::EC2::Instance", [])
    volumes = list(by_type.get("AWS::EC2::Volume", []))
    enis = list(by_type.get("AWS::EC2::NetworkInterface", []))

    vol_i = 0
    eni_i = 0
    for inst in instances:
        instance_id = inst["resourceId"]

        attached_volume_ids = []
        for _ in range(min(2, len(volumes) - vol_i)):
            vol = volumes[vol_i]
            vol_i += 1
            vol_id = vol["resourceId"]

            _set_nested(vol, ["configuration", "attachments", "instanceId"], instance_id)
            _set_nested(vol, ["configuration", "attachments", "volumeId"], vol_id)
            _set_nested(vol, ["configuration", "attachments", "state"], "attached")
            _set_nested(vol, ["configuration", "attachments", "deleteOnTermination"], True)

            vol["relationships"].append({
                "resourceId": instance_id,
                "resourceType": "AWS::EC2::Instance",
                "name": "Is attached to Instance",
            })
            inst["relationships"].append({
                "resourceId": vol_id,
                "resourceType": "AWS::EC2::Volume",
                "name": "Is attached to Volume",
            })
            attached_volume_ids.append(vol_id)
            stats["volume_attachments"] += 1

        if attached_volume_ids:
            _set_nested(inst,
                        ["configuration", "blockDeviceMappings", "ebs", "volumeId"],
                        attached_volume_ids[0])

        if eni_i < len(enis):
            eni = enis[eni_i]
            eni_i += 1
            eni_id = eni["resourceId"]

            _set_nested(eni, ["configuration", "attachment", "instanceId"], instance_id)
            _set_nested(eni, ["configuration", "attachment", "status"], "attached")

            eni["relationships"].append({
                "resourceId": instance_id,
                "resourceType": "AWS::EC2::Instance",
                "name": "Is attached to Instance",
            })
            inst["relationships"].append({
                "resourceId": eni_id,
                "resourceType": "AWS::EC2::NetworkInterface",
                "name": "Contains NetworkInterface",
            })
            _set_nested(inst,
                        ["configuration", "networkInterfaces", "networkInterfaceId"],
                        eni_id)
            stats["eni_attachments"] += 1

    lambdas = by_type.get("AWS::Lambda::Function", [])
    roles = by_type.get("AWS::IAM::Role", [])
    for lam in lambdas:
        if not roles:
            break
        role = random.choice(roles)
        role_arn = role.get("ARN") or f"arn:aws:iam::{account}:role/{role['resourceName']}"
        _set_nested(lam, ["configuration", "role"], role_arn)
        lam["relationships"].append({
            "resourceId": role["resourceId"],
            "resourceType": "AWS::IAM::Role",
            "name": "Is associated with IAM Role",
        })
        stats["lambda_role_links"] += 1

    rds_instances = by_type.get("AWS::RDS::DBInstance", [])
    subnet_groups = by_type.get("AWS::RDS::DBSubnetGroup", [])
    for rds in rds_instances:
        if not subnet_groups:
            break
        sg = random.choice(subnet_groups)
        sg_name = sg.get("resourceName") or sg["resourceId"]
        _set_nested(rds,
                    ["configuration", "dBSubnetGroup", "dBSubnetGroupName"],
                    sg_name)
        rds["relationships"].append({
            "resourceId": sg["resourceId"],
            "resourceType": "AWS::RDS::DBSubnetGroup",
            "name": "Is associated with DBSubnetGroup",
        })
        stats["rds_subnetgroup_links"] += 1

    # S3 Bucket → KMS Key (when encrypted with a pool key)
    buckets = by_type.get("AWS::S3::Bucket", [])
    kms_items = by_type.get("AWS::KMS::Key", [])
    stats["s3_kms_links"] = 0
    for bucket in buckets:
        if not kms_items:
            break
        key = random.choice(kms_items)
        bucket["relationships"].append({
            "resourceId": key["resourceId"],
            "resourceType": "AWS::KMS::Key",
            "name": "Is encrypted by KMS Key",
        })
        stats["s3_kms_links"] += 1

    return stats


def emit_pool_items(pool, region, account, schemas):
    """Emit VPC/Subnet/SG/KMS items so they appear in the snapshot."""
    items = []
    for vpc in pool["vpcs"]:
        ctx = make_context("AWS::EC2::VPC", region, account)
        _rebind_resource(ctx, "AWS::EC2::VPC", vpc["id"], region, account)
        ctx["vpc_id"] = vpc["id"]
        ctx["env"] = vpc["env"]
        ctx["tags"]["Environment"] = vpc["env"]
        ctx["az"] = "Multiple Availability Zones"
        items.append(build_item("AWS::EC2::VPC",
                                schemas.get("AWS::EC2::VPC", {}), ctx, []))

        for subnet in vpc["subnets"]:
            ctx = make_context("AWS::EC2::Subnet", region, account)
            _rebind_resource(ctx, "AWS::EC2::Subnet", subnet["id"], region, account)
            ctx["vpc_id"] = vpc["id"]
            ctx["env"] = vpc["env"]
            ctx["az"] = subnet["az"]
            ctx["tags"]["Environment"] = vpc["env"]
            rels = [{"resourceId": vpc["id"], "resourceType": "AWS::EC2::VPC",
                     "name": "Is contained in Vpc"}]
            items.append(build_item("AWS::EC2::Subnet",
                                    schemas.get("AWS::EC2::Subnet", {}), ctx, rels))

        for sg in vpc["sgs"]:
            ctx = make_context("AWS::EC2::SecurityGroup", region, account)
            _rebind_resource(ctx, "AWS::EC2::SecurityGroup", sg["id"], region, account)
            ctx["vpc_id"] = vpc["id"]
            ctx["env"] = vpc["env"]
            ctx["tags"]["Environment"] = vpc["env"]
            rels = [{"resourceId": vpc["id"], "resourceType": "AWS::EC2::VPC",
                     "name": "Is contained in Vpc"}]
            items.append(build_item("AWS::EC2::SecurityGroup",
                                    schemas.get("AWS::EC2::SecurityGroup", {}), ctx, rels))

    for key in pool["kms_keys"]:
        ctx = make_context("AWS::KMS::Key", region, account, kms_pool=pool["kms_keys"])
        ctx["resource_id"] = key["id"]
        ctx["resource_name"] = key["id"]
        ctx["arn"] = key["arn"]
        ctx["env"] = key["env"]
        ctx["tags"]["Environment"] = key["env"]
        items.append(build_item("AWS::KMS::Key",
                                schemas.get("AWS::KMS::Key", {}), ctx, []))

    return items


# --- I/O -------------------------------------------------------------------

def load_schemas(schemas_dir):
    schemas = {}
    for path in sorted(Path(schemas_dir).glob("*.properties.json")):
        rtype = path.name.removesuffix(".properties.json")
        with open(path) as f:
            schemas[rtype] = json.load(f)
    return schemas


def write_single_file(snapshot, output_path):
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        json.dump(snapshot, f, indent=2)
    return out


def s3_key_for(snapshot, account, region, when=None):
    """
    Build the AWS Config S3 key for a snapshot:

      AWSLogs/{accountId}/Config/{region}/{Y}/{M}/{D}/ConfigSnapshot/
        {accountId}_Config_{region}_ConfigSnapshot_{YYYYMMDDTHHMMSSZ}_{uuid}.json.gz

    Real Config does NOT zero-pad month/day path segments.
    """
    when = when or datetime.now(timezone.utc)
    ts = when.strftime("%Y%m%dT%H%M%SZ")
    snap_id = snapshot["configSnapshotId"]
    filename = f"{account}_Config_{region}_ConfigSnapshot_{ts}_{snap_id}.json.gz"
    return (f"AWSLogs/{account}/Config/{region}/"
            f"{when.year}/{when.month}/{when.day}/ConfigSnapshot/{filename}")


def gzip_snapshot(snapshot):
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
        gz.write(json.dumps(snapshot).encode("utf-8"))
    return buf.getvalue()


def write_s3_layout(snapshot, root, account, region, when=None):
    """Write snapshot to a local directory tree mirroring the Config S3 layout."""
    key = s3_key_for(snapshot, account, region, when)
    path = Path(root) / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip_snapshot(snapshot))
    return path


def upload_s3(s3_client, snapshot, bucket, prefix, account, region, when=None):
    """Upload snapshot directly to S3 under the Config delivery layout."""
    key = s3_key_for(snapshot, account, region, when)
    if prefix:
        key = f"{prefix.rstrip('/')}/{key}"
    body = gzip_snapshot(snapshot)
    s3_client.put_object(Bucket=bucket, Key=key, Body=body,
                         ContentType="application/json", ContentEncoding="gzip")
    return f"s3://{bucket}/{key}"


# --- Top-level orchestration -----------------------------------------------

def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("output_file", nargs="?",
                   help="Single-file output path (omit when --s3-root is used)")
    p.add_argument("--s3-root", default=None,
                   help="Write under AWS Config S3 layout rooted at this local directory")
    p.add_argument("--s3-bucket", default=None,
                   help="Upload directly to this S3 bucket (uses ambient AWS credentials)")
    p.add_argument("--s3-prefix", default="",
                   help="Optional key prefix inside --s3-bucket (e.g. 'mock/')")
    p.add_argument("--upload-workers", type=int, default=16,
                   help="Parallel S3 upload workers (default: 16)")
    p.add_argument("--count", type=int, default=30,
                   help="Number of non-infrastructure items to generate (default: 30)")
    p.add_argument("--vpcs", type=int, default=2,
                   help="Number of VPCs in the infra pool (default: 2)")
    p.add_argument("--schemas-dir", default="data/config_resource_schemas")
    p.add_argument("--region", default="eu-west-2")
    p.add_argument("--account", default="123456789012",
                   help="Single account ID (ignored if --accounts or --num-accounts is set)")
    p.add_argument("--accounts", default=None,
                   help="Comma-separated list of account IDs to generate snapshots for")
    p.add_argument("--num-accounts", type=int, default=None,
                   help="Number of fake account IDs to auto-generate")
    p.add_argument("--types", default=None,
                   help="Comma-separated resource types (default: random mix). "
                        "Overridden by --profile if both given.")
    p.add_argument("--profile", default=None,
                   help="Named profile from --profiles-file (e.g. compute, data, security, networking)")
    p.add_argument("--profiles-file", default="scripts/config_profiles.json",
                   help="Path to the profiles JSON file")
    p.add_argument("--list-profiles", action="store_true",
                   help="List available profiles and exit")
    p.add_argument("--seed", type=int, default=None)
    args = p.parse_args()

    # --list-profiles is informational — handle before output validation
    if args.list_profiles:
        profiles_path = Path(args.profiles_file)
        if not profiles_path.is_file():
            sys.exit(f"Profiles file not found: {profiles_path}")
        with open(profiles_path) as f:
            profiles_doc = json.load(f)
        for name, p_def in profiles_doc.get("profiles", {}).items():
            print(f"{name}: {p_def.get('description', '')}")
            for rtype, weight in p_def.get("types", {}).items():
                print(f"    {rtype}: {weight}")
        return

    if not args.output_file and not args.s3_root and not args.s3_bucket:
        p.error("provide an output_file, --s3-root, or --s3-bucket")

    output_modes = sum(bool(x) for x in (args.output_file, args.s3_root, args.s3_bucket))
    if output_modes > 1:
        p.error("use only one of: output_file, --s3-root, --s3-bucket")

    if args.seed is not None:
        random.seed(args.seed)

    # Resolve account list
    if args.accounts:
        accounts = [a.strip() for a in args.accounts.split(",") if a.strip()]
    elif args.num_accounts:
        accounts = [str(random.randint(100_000_000_000, 999_999_999_999))
                    for _ in range(args.num_accounts)]
    else:
        accounts = [args.account]

    if len(accounts) > 1 and args.output_file:
        p.error("multiple accounts require --s3-root or --s3-bucket")

    schemas_dir = Path(args.schemas_dir)
    if not schemas_dir.is_dir():
        sys.exit(f"Schemas dir not found: {schemas_dir}\n"
                 f"Run scripts/fetch_config_resource_schemas.sh first.")

    schemas = load_schemas(schemas_dir)
    if not schemas:
        sys.exit(f"No schemas found in {schemas_dir}")

    # Resolve resource type pool from profile, --types, or default mix
    # Pool-managed types (VPC/Subnet/SG/KMS) come from the infra pool and are
    # excluded from the draw pool to avoid duplicating them.
    pool_managed = {"AWS::EC2::VPC", "AWS::EC2::Subnet",
                    "AWS::EC2::SecurityGroup", "AWS::KMS::Key"}

    def expand_weighted(types_dict):
        pool = []
        for rtype, weight in types_dict.items():
            if rtype in pool_managed:
                print(f"  note: {rtype} is pool-managed, skipping from draw pool",
                      file=sys.stderr)
                continue
            if rtype not in schemas:
                sys.exit(f"Unknown resource type in profile: {rtype}")
            pool.extend([rtype] * int(weight))
        if not pool:
            sys.exit("Profile resolved to an empty draw pool")
        return pool

    if args.profile:
        profiles_path = Path(args.profiles_file)
        if not profiles_path.is_file():
            sys.exit(f"Profiles file not found: {profiles_path}")
        with open(profiles_path) as f:
            profiles_doc = json.load(f)
        profiles = profiles_doc.get("profiles", {})
        if args.profile not in profiles:
            sys.exit(f"Profile '{args.profile}' not found. "
                     f"Available: {', '.join(profiles)}")
        type_pool = expand_weighted(profiles[args.profile]["types"])
        print(f"Using profile '{args.profile}': "
              f"{profiles[args.profile].get('description', '')}", file=sys.stderr)
    elif args.types:
        wanted = [t.strip() for t in args.types.split(",")]
        missing = [t for t in wanted if t not in schemas]
        if missing:
            sys.exit(f"Unknown resource type(s): {missing}")
        type_pool = wanted
    else:
        common = [
            "AWS::EC2::Instance", "AWS::EC2::Volume", "AWS::S3::Bucket",
            "AWS::Lambda::Function", "AWS::RDS::DBInstance", "AWS::IAM::Role",
            "AWS::IAM::Policy", "AWS::DynamoDB::Table", "AWS::ECS::Service",
            "AWS::ElasticLoadBalancingV2::LoadBalancer", "AWS::SQS::Queue",
            "AWS::SNS::Topic", "AWS::CloudWatch::Alarm",
            "AWS::SecretsManager::Secret",
        ]
        common = [t for t in common if t in schemas]
        rest = [t for t in schemas if t not in common and t not in pool_managed]
        type_pool = common * 7 + rest

    s3_client = None
    if args.s3_bucket:
        import boto3
        s3_client = boto3.client("s3", region_name=args.region)

    print(f"Generating snapshots for {len(accounts)} account(s) in {args.region}",
          file=sys.stderr)

    def build_account_snapshot(account):
        # Each account gets its own infra pool — IDs don't collide across accounts.
        pool = build_infra_pool(args.region, account, num_vpcs=args.vpcs)
        items = emit_pool_items(pool, args.region, account, schemas)
        for _ in range(args.count):
            rtype = random.choice(type_pool)
            assignment = assign_vpc(pool) if rtype in VPC_RESIDENT_TYPES else None
            ctx = make_context(rtype, args.region, account,
                               vpc_assignment=assignment,
                               kms_pool=pool["kms_keys"])
            rels = []
            if assignment:
                vpc, subnet, sg_ids = assignment
                rels = vpc_relationships(vpc, subnet, sg_ids, account)
            items.append(build_item(rtype, schemas[rtype], ctx, rels))

        link_items(items, account)

        snapshot = {
            "fileVersion": "1.0",
            "configSnapshotId": str(uuid.uuid4()),
            "configurationItems": items,
        }
        return account, snapshot, items

    # Single-file output: just one account
    if args.output_file:
        account, snapshot, items = build_account_snapshot(accounts[0])
        path = write_single_file(snapshot, args.output_file)
        print(f"Wrote {len(items)} items to {path}")
        return

    # Local S3-layout dir
    if args.s3_root:
        for account in accounts:
            _, snapshot, items = build_account_snapshot(account)
            path = write_s3_layout(snapshot, args.s3_root, account, args.region)
            print(f"  {account}: {len(items)} items -> {path}", file=sys.stderr)
        return

    # Direct S3 upload, parallelized
    completed = 0
    total_items = 0
    failures = []

    def upload_one(account):
        _, snapshot, items = build_account_snapshot(account)
        url = upload_s3(s3_client, snapshot, args.s3_bucket, args.s3_prefix,
                        account, args.region)
        return account, url, len(items)

    with ThreadPoolExecutor(max_workers=args.upload_workers) as ex:
        futures = {ex.submit(upload_one, a): a for a in accounts}
        for fut in as_completed(futures):
            account = futures[fut]
            try:
                _, url, n = fut.result()
                completed += 1
                total_items += n
                if completed % 25 == 0 or completed == len(accounts):
                    print(f"  [{completed}/{len(accounts)}] uploaded "
                          f"({total_items} items so far)", file=sys.stderr)
            except Exception as e:
                failures.append((account, str(e)))
                print(f"  FAILED account {account}: {e}", file=sys.stderr)

    print(f"\nDone. {completed}/{len(accounts)} accounts uploaded, "
          f"{total_items} items total to s3://{args.s3_bucket}/{args.s3_prefix}",
          file=sys.stderr)
    if failures:
        print(f"{len(failures)} failures", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
