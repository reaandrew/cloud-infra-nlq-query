/**
 * Hand-curated example questions for the Query view.
 *
 * Organised by category so the SPA can group them in cards. Each entry
 * is meant to demonstrate a distinct query pattern: simple aggregation,
 * JSON column probe, single-resource filter, two-resource join, n-way
 * join, etc.
 */

export interface ExampleCategory {
  id: string;
  title: string;
  description: string;
}

export interface Example {
  id: string;
  category: string;
  title: string;
  question: string;
  description: string;
}

export const EXAMPLE_CATEGORIES: ExampleCategory[] = [
  {
    id: "inventory",
    title: "Inventory",
    description: "What's in the estate, broken down by account, type or region.",
  },
  {
    id: "compute",
    title: "Compute",
    description: "EC2 instances, EBS volumes, Lambda functions and how they relate.",
  },
  {
    id: "security",
    title: "Security",
    description: "IAM, KMS, encryption posture, public exposure.",
  },
  {
    id: "networking",
    title: "Networking",
    description: "VPCs, subnets, ENIs and what's living inside them.",
  },
];

export const EXAMPLES: Example[] = [
  // ---- inventory ----
  {
    id: "inv-types",
    category: "inventory",
    title: "Resource type histogram",
    question: "how many resources of each type are there in the account, top 15",
    description: "Single-table aggregation. The fastest end-to-end query in the catalogue.",
  },
  {
    id: "inv-by-account",
    category: "inventory",
    title: "Top accounts by resource count",
    question: "show me the top 10 accounts by total resource count, including how many distinct resource types they have",
    description: "Account-level inventory with a secondary aggregation.",
  },
  {
    id: "inv-tag-environment",
    category: "inventory",
    title: "EC2 instances by Environment tag",
    question: "show me a count of EC2 instances broken down by their Environment tag value, top 10",
    description: "Tag-based aggregation via json_extract_scalar on the opaque tags column.",
  },

  // ---- compute ----
  {
    id: "compute-largest-volumes",
    category: "compute",
    title: "Largest EBS volumes",
    question: "list the largest 10 EBS volumes by size showing volume ID, size, type, encryption status and account",
    description: "Single-resource JSON probe with CAST. Common SRE question.",
  },
  {
    id: "compute-instances-per-account",
    category: "compute",
    title: "EC2 instances per account",
    question: "how many EC2 instances are there per account, top 10",
    description: "Cheap aggregation, no JSON digging.",
  },
  {
    id: "compute-instance-volume-join",
    category: "compute",
    title: "Instance ↔ volume join",
    question: "for each EC2 instance show the volumes attached to it. join EC2::Instance with EC2::Volume on the attachment instance ID. limit to 25 rows",
    description: "Two-resource WITH-CTE join across the configuration JSON.",
  },
  {
    id: "compute-lambda-runtimes",
    category: "compute",
    title: "Lambda runtimes histogram",
    question: "count Lambda functions by runtime, ordered by count descending",
    description: "Pulls runtime out of the configuration column and groups.",
  },

  // ---- security ----
  {
    id: "sec-iam-roles",
    category: "security",
    title: "IAM roles per account",
    question: "show me the count of IAM roles per account, top 15",
    description: "Single-resource aggregation; useful baseline for IAM growth.",
  },
  {
    id: "sec-kms-key-states",
    category: "security",
    title: "KMS keys by state",
    question: "count KMS keys grouped by their key state across the whole estate",
    description: "Touches the configuration JSON, useful for spotting pending-deletion keys.",
  },
  {
    id: "sec-volumes-encryption",
    category: "security",
    title: "Unencrypted EBS volumes",
    question: "find EBS volumes where encryption is false, show account, volume ID, size and AZ",
    description: "Single-resource boolean filter on the configuration column.",
  },

  // ---- networking ----
  {
    id: "net-subnet-occupancy",
    category: "networking",
    title: "Subnet occupancy",
    question: "for each subnet count how many EC2 instances and network interfaces are inside it. join EC2::Subnet with EC2::Instance and EC2::NetworkInterface on subnetId. show top 15",
    description: "Three-resource join with LEFT JOIN + COALESCE — the canonical orphan-detection shape.",
  },
  {
    id: "net-vpc-inventory",
    category: "networking",
    title: "VPC inventory",
    question: "for each VPC count how many EC2 instances, RDS instances, lambda functions and network interfaces are inside it. group by vpc and account, top 20",
    description: "Four-resource pivot via COUNT(*) FILTER (WHERE …).",
  },
  {
    id: "net-eni-without-instance",
    category: "networking",
    title: "ENIs not attached to an instance",
    question: "find network interfaces whose attachment instance ID is null or empty. show account, region, ENI ID and description",
    description: "Single-resource filter for orphan ENIs, common cleanup query.",
  },
];
