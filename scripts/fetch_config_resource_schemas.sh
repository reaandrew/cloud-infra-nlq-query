#! /usr/bin/env bash
#
# Fetches AWS Config resource property schemas from the awslabs repo:
#   https://github.com/awslabs/aws-config-resource-schema
#
# Each schema is a flat JSON object mapping dotted property paths to primitive
# types (string, integer, boolean, date). These are the authoritative field
# names/casing used by AWS Config.
#
# Usage:
#   ./fetch_config_resource_schemas.sh <output_dir>

set -euo pipefail

output_dir="${1:?Usage: $0 <output_dir>}"
mkdir -p "$output_dir"

repo="awslabs/aws-config-resource-schema"
branch="master"
prefix="config/properties/resource-types/"

echo "Listing schema files from $repo..."
paths=$(curl -sf "https://api.github.com/repos/$repo/git/trees/$branch?recursive=1" \
  | jq -r --arg prefix "$prefix" '.tree[] | select(.path | startswith($prefix) and endswith(".properties.json")) | .path')

total=$(echo "$paths" | wc -l)
echo "Downloading $total schemas into $output_dir..."

count=0
echo "$paths" | while read -r path; do
  count=$((count + 1))
  name=$(basename "$path")
  curl -sf "https://raw.githubusercontent.com/$repo/$branch/$path" > "$output_dir/$name"
  printf '\r  [%d/%d] %s' "$count" "$total" "$name"
done
echo ""
echo "Done."
