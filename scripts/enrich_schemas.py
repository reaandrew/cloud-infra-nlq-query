#!/usr/bin/env python3
"""
Enriches each AWS Config resource property schema in
data/config_resource_schemas/ into a semantic Markdown document under
data/enriched_schemas/. The Markdown is what gets embedded and stored in
S3 Vectors for natural-language schema retrieval.

For each schema we ask Claude (Bedrock) to produce a short JSON object
describing the resource type, its category, what it's typically queried
for, and which fields are most useful. We then render that as Markdown
and append the mechanical "all field paths" listing so the embedding sees
both the human language and the raw structure.

Idempotent: skips schemas whose enriched .md already exists unless
--force is passed. Run cost is printed up-front so you can abort.

Usage:
    aws-vault exec ee-sandbox -- ./scripts/enrich_schemas.py
    aws-vault exec ee-sandbox -- ./scripts/enrich_schemas.py --limit 5     # smoke test
    aws-vault exec ee-sandbox -- ./scripts/enrich_schemas.py --force       # re-enrich all
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import boto3
from botocore.config import Config

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / "data" / "config_resource_schemas"
OUT_DIR = REPO_ROOT / "data" / "enriched_schemas"

DEFAULT_MODEL = os.environ.get("CHAT_MODEL_ID", "anthropic.claude-sonnet-4-6")
DEFAULT_REGION = os.environ.get("AWS_REGION", "eu-west-2")
DEFAULT_WORKERS = int(os.environ.get("ENRICH_WORKERS", "8"))

SYSTEM_PROMPT = """\
You are a senior cloud architect documenting AWS Config resource types so
they can be retrieved via semantic search and used by a SQL-generating
assistant.

Given a resource type and its full list of property paths and types from
AWS Config, return a SINGLE compact JSON object (no surrounding prose, no
markdown fences) with exactly these keys:

{
  "service": "<short canonical service name, e.g. EC2, S3, IAM, Lambda>",
  "category": "<one of: compute, storage, networking, security, identity, database, analytics, observability, management, serverless, ml, messaging, integration, media, iot, edge, dev_tools, content_delivery, other>",
  "description": "<1-3 sentences describing what this resource is and what it represents in AWS>",
  "common_queries": [
    "<3 to 5 example natural language questions someone might ask about this resource type>",
    "..."
  ],
  "notable_fields": [
    {"path": "<full property path from the schema>", "description": "<what this field tells you in plain English>"},
    "...up to 10 entries..."
  ],
  "relationships_to": [
    "<other AWS::Service::Type values this resource is typically related to, best-effort>",
    "..."
  ]
}

Constraints:
- notable_fields paths MUST be exact strings copied from the input field list.
- Output JSON only, no prose, no fences, no commentary. Start with { and end with }.
- Be specific. Avoid generic descriptions like "an AWS resource".
"""

USER_TEMPLATE = """\
Resource type: {resource_type}

Property paths and types (full list):
{field_list}
"""


def list_raw_schemas() -> list[Path]:
    return sorted(RAW_DIR.glob("*.properties.json"))


def resource_type_from_path(p: Path) -> str:
    return p.name.removesuffix(".properties.json")


def out_path(resource_type: str) -> Path:
    return OUT_DIR / f"{resource_type}.md"


def render_markdown(resource_type: str, enriched: dict, raw: dict) -> str:
    field_count = len(raw)
    paths = sorted(raw.items())

    common_queries = enriched.get("common_queries") or []
    notable_fields = enriched.get("notable_fields") or []
    relationships_to = enriched.get("relationships_to") or []

    lines: list[str] = []
    lines.append(f"# {resource_type}")
    lines.append("")
    lines.append(f"- **Service**: {enriched.get('service', '')}")
    lines.append(f"- **Category**: {enriched.get('category', '')}")
    lines.append(f"- **Field count**: {field_count}")
    lines.append("")
    lines.append("## Description")
    lines.append("")
    lines.append(enriched.get("description", "").strip() or "_(no description)_")
    lines.append("")
    if common_queries:
        lines.append("## Common queries")
        lines.append("")
        for q in common_queries:
            lines.append(f"- {q}")
        lines.append("")
    if notable_fields:
        lines.append("## Notable fields")
        lines.append("")
        for f in notable_fields:
            if isinstance(f, dict):
                path = f.get("path", "")
                desc = f.get("description", "")
                lines.append(f"- `{path}` — {desc}")
        lines.append("")
    if relationships_to:
        lines.append("## Related resource types")
        lines.append("")
        for r in relationships_to:
            lines.append(f"- {r}")
        lines.append("")
    lines.append("## All field paths")
    lines.append("")
    for path, ftype in paths:
        lines.append(f"- `{path}`: {ftype}")
    lines.append("")
    return "\n".join(lines)


def call_claude(client, model_id: str, resource_type: str, raw: dict) -> dict:
    field_list = "\n".join(f"- {p}: {t}" for p, t in sorted(raw.items()))
    user = USER_TEMPLATE.format(resource_type=resource_type, field_list=field_list)

    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 1500,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user}],
    }
    resp = client.invoke_model(
        modelId=model_id,
        body=json.dumps(body),
        contentType="application/json",
    )
    payload = json.loads(resp["body"].read())
    text = "".join(
        block["text"] for block in payload["content"] if block["type"] == "text"
    ).strip()
    if text.startswith("```"):
        # strip optional fences just in case
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    return json.loads(text)


def enrich_one(client, model_id: str, raw_path: Path, force: bool) -> tuple[str, str, int, int]:
    resource_type = resource_type_from_path(raw_path)
    target = out_path(resource_type)
    if target.exists() and not force:
        return resource_type, "skip", 0, 0

    with raw_path.open() as fh:
        raw = json.load(fh)

    t0 = time.time()
    enriched = call_claude(client, model_id, resource_type, raw)
    elapsed_ms = int((time.time() - t0) * 1000)

    md = render_markdown(resource_type, enriched, raw)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(md)
    tmp.rename(target)

    return resource_type, "ok", elapsed_ms, len(md)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--region", default=DEFAULT_REGION)
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    p.add_argument("--limit", type=int, default=0,
                   help="If >0, only enrich the first N schemas (smoke test)")
    p.add_argument("--force", action="store_true",
                   help="Re-enrich even if the output file already exists")
    p.add_argument("--only", help="Comma-separated list of resource types to enrich")
    args = p.parse_args()

    raws = list_raw_schemas()
    if args.only:
        wanted = set(args.only.split(","))
        raws = [r for r in raws if resource_type_from_path(r) in wanted]
    if args.limit:
        raws = raws[: args.limit]

    if not raws:
        print("no schemas to process", file=sys.stderr)
        sys.exit(1)

    pending = [
        r for r in raws
        if args.force or not out_path(resource_type_from_path(r)).exists()
    ]
    skipped = len(raws) - len(pending)

    print(f"raw schemas:        {len(raws)}")
    print(f"already enriched:   {skipped}")
    print(f"to enrich now:      {len(pending)}")
    if pending:
        # rough cost estimate: per call ~3K input + ~1K output
        approx_input_tokens = len(pending) * 3000
        approx_output_tokens = len(pending) * 1000
        approx_cost = (approx_input_tokens / 1_000_000) * 3.0 + (approx_output_tokens / 1_000_000) * 15.0
        print(f"approx Bedrock cost (Claude Sonnet 4.6): ~${approx_cost:.2f}")
        print(f"model:              {args.model}")
        print(f"workers:            {args.workers}")
        print()

    if not pending:
        print("nothing to do.")
        return

    client = boto3.client(
        "bedrock-runtime",
        region_name=args.region,
        config=Config(retries={"max_attempts": 5, "mode": "adaptive"},
                      read_timeout=120),
    )

    ok = 0
    failed: list[tuple[str, str]] = []
    started = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(enrich_one, client, args.model, r, args.force): r
            for r in pending
        }
        for fut in as_completed(futures):
            raw_path = futures[fut]
            rt = resource_type_from_path(raw_path)
            try:
                _, status, ms, nbytes = fut.result()
                if status == "ok":
                    ok += 1
                    print(f"  [{ok}/{len(pending)}] {rt} ({ms} ms, {nbytes} B)")
            except Exception as exc:
                failed.append((rt, str(exc)))
                print(f"  ERROR  {rt}: {exc}", file=sys.stderr)

    elapsed = time.time() - started
    print()
    print(f"done in {elapsed:.1f}s — {ok} ok, {len(failed)} failed, {skipped} skipped")
    if failed:
        print("failures:")
        for rt, err in failed:
            print(f"  {rt}: {err}")
        sys.exit(1)


if __name__ == "__main__":
    main()
