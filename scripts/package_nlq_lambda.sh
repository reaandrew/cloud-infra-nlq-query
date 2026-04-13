#!/usr/bin/env bash
# Package the NLQ HTTP API Lambda. The function needs:
#   - a recent boto3 (the runtime's bundled boto3 is too old to know about the
#     s3vectors service)
#   - the enriched schema markdown docs from data/enriched_schemas/
# Both are staged into build/nlq/ alongside handler.py, and terraform's
# archive_file resource zips the directory.
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
src="$repo_root/lambda/nlq"
build="$repo_root/build/nlq"
enriched="$repo_root/data/enriched_schemas"

if [ ! -d "$enriched" ] || [ -z "$(ls -A "$enriched"/*.md 2>/dev/null || true)" ]; then
  echo "ERROR: $enriched is empty. Run 'make enrich-schemas' first." >&2
  exit 1
fi

echo "package-nlq: cleaning $build"
rm -rf "$build"
mkdir -p "$build"

echo "package-nlq: copying handler"
cp "$src/handler.py" "$build/handler.py"

echo "package-nlq: copying $(ls "$enriched"/*.md | wc -l) enriched schema docs"
mkdir -p "$build/enriched_schemas"
cp "$enriched"/*.md "$build/enriched_schemas/"

echo "package-nlq: pip installing boto3>=1.42 into the package"
pip install \
  --target "$build" \
  --quiet \
  --upgrade \
  --no-cache-dir \
  --no-compile \
  'boto3>=1.42.88' 'botocore>=1.42.88'

echo "package-nlq: trimming pip metadata to keep the zip small"
find "$build" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
find "$build" -name "*.dist-info" -type d -exec rm -rf {} + 2>/dev/null || true
find "$build" -name "*.pyc" -delete 2>/dev/null || true

echo "package-nlq: package size"
du -sh "$build"
echo "package-nlq: ready at $build"
