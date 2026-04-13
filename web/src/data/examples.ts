/**
 * Hand-curated example questions for the Query view.
 *
 * Organised into four **complexity levels** so the UI can show off the
 * range of queries the system supports, from trivial aggregations up to
 * multi-resource orphan detection with 3+ CTE joins.
 *
 * Each level deliberately uses patterns the natural-language layer
 * handles well:
 *   1. Basics           — single resource type, GROUP BY, no JSON
 *   2. JSON fields      — reaches into the opaque configuration / tags
 *                         columns via json_extract_scalar
 *   3. Cross-resource   — two resource types joined via a JSON-extracted
 *                         ID, producing a WITH-CTE join
 *   4. Advanced         — three or more resource types; orphan detection
 *                         and inventory pivots
 */

export interface ExampleCategory {
  id: string;
  level: number;
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
    id: "basic",
    level: 1,
    title: "Basics",
    description:
      "Single-table aggregations. One GROUP BY, no JSON digging. The fastest queries in the catalogue — typically back in 5 seconds.",
  },
  {
    id: "json",
    level: 2,
    title: "JSON fields",
    description:
      "Reaches into the opaque configuration and tags JSON columns via json_extract_scalar. A filter or projection on a nested field turns into a useful SQL expression without you naming it.",
  },
  {
    id: "cross",
    level: 3,
    title: "Cross-resource joins",
    description:
      "Combines two resource types by joining on IDs extracted from JSON. Claude writes the full WITH-CTE join — instance-to-volume, lambda-to-role, volume-to-KMS-key.",
  },
  {
    id: "advanced",
    level: 4,
    title: "Advanced",
    description:
      "Three or more resource types, orphan detection, inventory pivots. 4-way joins via COUNT(*) FILTER (WHERE ...) and the LEFT JOIN ... WHERE IS NULL anti-join pattern for unreferenced resources.",
  },
];

export const EXAMPLES: Example[] = [
  // ---- level 1: basics ----
  {
    id: "basic-types-histogram",
    category: "basic",
    title: "Resource type histogram",
    question:
      "how many resources of each type are there in the account, top 15",
    description:
      "Single-table aggregation. The fastest end-to-end query in the catalogue.",
  },
  {
    id: "basic-instances-per-account",
    category: "basic",
    title: "EC2 instances per account",
    question: "how many EC2 instances are there per account, top 10",
    description: "Same pattern, filtered to a specific resource type.",
  },
  {
    id: "basic-top-accounts",
    category: "basic",
    title: "Top accounts by resource count",
    question:
      "show me the top 10 accounts by total resource count, including how many distinct resource types they have",
    description:
      "Account-level aggregation with a secondary count(distinct). Still no JSON probe.",
  },

  // ---- level 2: JSON fields ----
  {
    id: "json-largest-volumes",
    category: "json",
    title: "Largest EBS volumes",
    question:
      "list the largest 10 EBS volumes by size showing volume ID, size, type, encryption status and account",
    description:
      "Projects configuration.size, configuration.volumeType and configuration.encrypted with a cast for sorting.",
  },
  {
    id: "json-tag-environment",
    category: "json",
    title: "EC2 by Environment tag",
    question:
      "show me a count of EC2 instances broken down by their Environment tag value, top 10",
    description:
      "Pulls the Environment key out of the opaque tags JSON object and groups on it.",
  },
  {
    id: "json-lambda-runtimes",
    category: "json",
    title: "Lambda runtimes",
    question:
      "count Lambda functions grouped by their runtime, ordered by count descending",
    description:
      "A single field probe — configuration.runtime — with a straightforward histogram.",
  },

  // ---- level 3: cross-resource ----
  {
    id: "cross-instance-volume",
    category: "cross",
    title: "Instance ↔ Volume",
    question:
      "for each EC2 instance show the volumes attached to it. join EC2::Instance with EC2::Volume on the attachment instance ID. limit to 25 rows",
    description:
      "Two CTEs, one per resource type, joined on attachments[0].instanceId.",
  },
  {
    id: "cross-lambda-role",
    category: "cross",
    title: "Lambda ↔ IAM role",
    question:
      "show me Lambda functions and the IAM roles they assume, joining Lambda::Function with IAM::Role on the role ARN. limit 25",
    description:
      "Joins compute workloads to their identity — the bridge between Lambda.configuration.role and IAM Role.arn.",
  },
  {
    id: "cross-volume-kms",
    category: "cross",
    title: "EBS volume ↔ KMS key",
    question:
      "for each EBS volume that is encrypted, show which KMS key encrypts it by joining EC2::Volume with KMS::Key on the KMS key ID. limit 25",
    description:
      "Shows which customer-managed key is protecting each volume, a common compliance question.",
  },

  // ---- level 4: advanced ----
  {
    id: "advanced-subnet-occupancy",
    category: "advanced",
    title: "Subnet occupancy (3-way)",
    question:
      "for each subnet count how many EC2 instances and network interfaces are inside it. join EC2::Subnet with EC2::Instance and EC2::NetworkInterface on subnetId. show top 15",
    description:
      "Three resource types, LEFT JOIN + COALESCE for subnets with no matching children — the canonical orphan-detection shape.",
  },
  {
    id: "advanced-vpc-inventory",
    category: "advanced",
    title: "VPC inventory (4-way pivot)",
    question:
      "for each VPC count how many EC2 instances, RDS instances, lambda functions and network interfaces are inside it. group by vpc and account, top 20",
    description:
      "COUNT(*) FILTER (WHERE ...) pivot across four resource types. Tells you which VPCs are actually in use and which are empty.",
  },
  {
    id: "advanced-orphan-kms",
    category: "advanced",
    title: "Orphan KMS keys",
    question:
      "find KMS keys that are not referenced by any EBS volume, RDS instance, or S3 bucket. show the orphan keys with account and state",
    description:
      "The classic anti-join: union all the consumers, LEFT JOIN, filter where the consumer side is NULL.",
  },
];
