#!/usr/bin/env python3
"""
Generate the architecture diagrams for the "How this was made" page.

Each diagram is defined declaratively (nodes + edges) in a small Python
DSL and rendered as a .drawio XML file. The drawio CLI then exports
each .drawio to a high-resolution PNG.

Outputs land in:
    docs/architecture/                       (.drawio sources, committed)
    web/public/docs/architecture/<name>.png  (bundled into the SPA)
    /media/psf/Home/Downloads/architecture/  (your local copies)

We use the official AWS shape library (mxgraph.aws4.*) so the diagrams
look like a real AWS architecture deck rather than coloured boxes.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent

SRC_DIR = REPO_ROOT / "docs" / "architecture"
SPA_DIR = REPO_ROOT / "web" / "public" / "docs" / "architecture"
USER_DIR = Path("/media/psf/Home/Downloads/architecture")

DRAWIO_BIN = os.environ.get("DRAWIO_BIN", "drawio")

# AWS palette
AWS_ORANGE = "#FF9900"
AWS_DARK = "#232F3E"
AWS_BLUE = "#1A476F"
AWS_TEAL = "#00A4A6"
AWS_RED = "#E7157B"
AWS_PURPLE = "#7AA116"

GROUP_FILL = "#fafafa"
GROUP_STROKE = "#cccccc"


# ---------- DSL ----------

@dataclass
class Node:
    id: str
    label: str
    x: int
    y: int
    w: int = 140
    h: int = 80
    style: str = ""

    def to_xml(self) -> str:
        return (
            f'<mxCell id="{self.id}" value="{self.label}" '
            f'style="{self.style}" vertex="1" parent="1">'
            f'<mxGeometry x="{self.x}" y="{self.y}" width="{self.w}" height="{self.h}" as="geometry"/>'
            f"</mxCell>"
        )


@dataclass
class Edge:
    id: str
    src: str
    tgt: str
    label: str = ""
    style: str = (
        "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;"
        "html=1;exitDx=0;exitDy=0;strokeColor=#232F3E;strokeWidth=2;"
        "fontSize=12;fontColor=#232F3E;endArrow=block;endFill=1;"
    )

    def to_xml(self) -> str:
        return (
            f'<mxCell id="{self.id}" value="{self.label}" style="{self.style}" '
            f'edge="1" parent="1" source="{self.src}" target="{self.tgt}">'
            f'<mxGeometry relative="1" as="geometry"/>'
            f"</mxCell>"
        )


@dataclass
class Group:
    id: str
    label: str
    x: int
    y: int
    w: int
    h: int
    fill: str = GROUP_FILL
    stroke: str = GROUP_STROKE
    dashed: int = 1

    def to_xml(self) -> str:
        style = (
            f"rounded=0;whiteSpace=wrap;html=1;fillColor={self.fill};"
            f"strokeColor={self.stroke};dashed={self.dashed};"
            f"verticalAlign=top;align=left;fontSize=11;fontStyle=2;"
            f"fontColor=#666666;spacingLeft=8;spacingTop=4;"
        )
        return (
            f'<mxCell id="{self.id}" value="{self.label}" style="{style}" '
            f'vertex="1" parent="1">'
            f'<mxGeometry x="{self.x}" y="{self.y}" width="{self.w}" height="{self.h}" as="geometry"/>'
            f"</mxCell>"
        )


@dataclass
class Diagram:
    name: str          # filename slug
    title: str
    width: int
    height: int
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    groups: list[Group] = field(default_factory=list)

    def _anchor_cells(self) -> list[Node]:
        """drawio's PNG export auto-crops to the diagram bounding box, and
        the bbox computation can be wrong when AWS resource icons are mixed
        with plain shapes at varying heights. Invisible anchor cells at
        (0,0) and (width, height) force the bbox to match the page."""
        invisible_style = (
            "rounded=0;whiteSpace=wrap;html=1;"
            "fillColor=none;strokeColor=none;fontSize=1;fontColor=none;"
        )
        return [
            Node("__anchor_tl", " ", 0, 0, 1, 1, invisible_style),
            Node("__anchor_br", " ", self.width - 1, self.height - 1, 1, 1, invisible_style),
        ]

    def to_xml(self) -> str:
        body = ""
        for n in self._anchor_cells():
            body += n.to_xml()
        # groups first (so nodes render above them)
        for g in self.groups:
            body += g.to_xml()
        for n in self.nodes:
            body += n.to_xml()
        for e in self.edges:
            body += e.to_xml()
        return textwrap.dedent(
            f"""\
            <mxfile host="cli">
              <diagram id="d1" name="{self.title}">
                <mxGraphModel dx="{self.width}" dy="{self.height}" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="{self.width}" pageHeight="{self.height}" math="0" shadow="0">
                  <root>
                    <mxCell id="0"/>
                    <mxCell id="1" parent="0"/>
                    {body}
                  </root>
                </mxGraphModel>
              </diagram>
            </mxfile>
            """
        )


# ---------- shape helpers ----------

def aws_resource(res_icon: str, fill: str = AWS_ORANGE) -> str:
    """Style for an AWS service icon with the standard label-below layout."""
    return (
        "sketch=0;points=[[0,0,0],[0.25,0,0],[0.5,0,0],[0.75,0,0],[1,0,0],[0,1,0],"
        "[0.25,1,0],[0.5,1,0],[0.75,1,0],[1,1,0],[0,0.25,0],[0,0.5,0],[0,0.75,0],"
        "[1,0.25,0],[1,0.5,0],[1,0.75,0]];outlineConnect=0;fontColor=#232F3E;"
        f"gradientColor=none;fillColor={fill};strokeColor=#ffffff;dashed=0;"
        "verticalLabelPosition=bottom;verticalAlign=top;align=center;html=1;"
        "fontSize=12;fontStyle=0;aspect=fixed;"
        f"shape=mxgraph.aws4.resourceIcon;resIcon=mxgraph.aws4.{res_icon};"
    )


def actor() -> str:
    return (
        "sketch=0;outlineConnect=0;fontColor=#232F3E;gradientColor=none;"
        "fillColor=#232F3E;strokeColor=#ffffff;dashed=0;verticalLabelPosition=bottom;"
        "verticalAlign=top;align=center;html=1;fontSize=12;fontStyle=1;"
        "aspect=fixed;shape=mxgraph.aws4.users;"
    )


def plain_box(fill: str = "#FFFFFF", stroke: str = AWS_DARK) -> str:
    return (
        f"rounded=0;whiteSpace=wrap;html=1;fillColor={fill};strokeColor={stroke};"
        "fontColor=#232F3E;fontSize=12;fontStyle=1;align=center;verticalAlign=middle;"
        "strokeWidth=2;"
    )


def note_box() -> str:
    return (
        "shape=note;whiteSpace=wrap;html=1;backgroundOutline=1;darkOpacity=0.05;"
        "fillColor=#FFF8DC;strokeColor=#999999;fontSize=11;fontColor=#444444;"
        "align=left;verticalAlign=top;spacingLeft=8;spacingTop=4;"
    )


# ---------- diagrams ----------

def diagram_overview() -> Diagram:
    """High-level system overview — the whole stack on one page."""
    d = Diagram("01-system-overview", "System overview", 1400, 900)

    # Top row: user → CDN → SPA bucket
    d.nodes.append(Node("user", "End user", 80, 380, 80, 80, actor()))
    d.nodes.append(Node("r53", "Route 53", 220, 380, 80, 80, aws_resource("route_53", "#8C4FFF")))
    d.nodes.append(Node("cf", "CloudFront", 360, 380, 80, 80, aws_resource("cloudfront", "#8C4FFF")))
    d.nodes.append(Node("spa_bucket", "SPA assets\n(S3)", 500, 380, 80, 80, aws_resource("simple_storage_service", "#7AA116")))

    # Middle column: API GW + auth
    d.nodes.append(Node("apigw", "API Gateway v2\n(HTTP API)", 360, 580, 80, 80, aws_resource("api_gateway", "#FF4F8B")))
    d.nodes.append(Node("auth", "Authoriser\nLambda", 220, 720, 80, 80, aws_resource("lambda", AWS_ORANGE)))
    d.nodes.append(Node("secrets", "Secrets\nManager", 80, 720, 80, 80, aws_resource("secrets_manager", "#DD344C")))

    # Right of API GW: NLQ Lambda and Stats Lambda
    d.nodes.append(Node("nlq", "NLQ Lambda\n(extract+RAG+SQL)", 540, 580, 100, 80, aws_resource("lambda", AWS_ORANGE)))
    d.nodes.append(Node("stats", "Stats Lambda", 700, 580, 100, 80, aws_resource("lambda", AWS_ORANGE)))

    # Bedrock + S3 Vectors
    d.nodes.append(Node("bedrock", "Amazon Bedrock\n(Titan + Claude 4.6)", 800, 380, 100, 80, aws_resource("sagemaker", "#01A88D")))
    d.nodes.append(Node("s3v", "S3 Vectors\n(417 schemas)", 940, 380, 100, 80, aws_resource("simple_storage_service", "#01A88D")))

    # Athena + Iceberg + Glue
    d.nodes.append(Node("athena", "Athena", 940, 580, 100, 80, aws_resource("athena", "#8C4FFF")))
    d.nodes.append(Node("glue", "Glue Catalog\n(cinq.operational)", 1080, 580, 100, 80, aws_resource("glue", "#8C4FFF")))
    d.nodes.append(Node("iceberg", "Iceberg table\n(S3 cinq-config)", 1220, 580, 100, 80, aws_resource("simple_storage_service", "#7AA116")))

    # Ingest pipeline tail
    d.nodes.append(Node("mock", "cinq-config-mock\n(S3)", 1220, 80, 100, 80, aws_resource("simple_storage_service", "#7AA116")))
    d.nodes.append(Node("sqs", "cinq-extract\n(SQS)", 1060, 80, 100, 80, aws_resource("simple_queue_service", "#FF4F8B")))
    d.nodes.append(Node("extract", "Extract\nLambda", 900, 80, 100, 80, aws_resource("lambda", AWS_ORANGE)))
    d.nodes.append(Node("compact", "Compact\nLambda (nightly)", 740, 80, 100, 80, aws_resource("lambda", AWS_ORANGE)))

    # Edges: SPA path
    d.edges.append(Edge("e1", "user", "r53", "DNS"))
    d.edges.append(Edge("e2", "r53", "cf"))
    d.edges.append(Edge("e3", "cf", "spa_bucket", "OAC"))
    d.edges.append(Edge("e4", "user", "apigw", "/stats, /nlq"))

    # API GW fans out
    d.edges.append(Edge("e5", "apigw", "auth", "x-api-key"))
    d.edges.append(Edge("e6", "auth", "secrets", "GetSecret"))
    d.edges.append(Edge("e7", "apigw", "nlq", "POST /nlq"))
    d.edges.append(Edge("e8", "apigw", "stats", "GET /stats/*"))

    # NLQ Lambda
    d.edges.append(Edge("e9", "nlq", "bedrock", "embed + chat"))
    d.edges.append(Edge("e10", "nlq", "s3v", "query"))
    d.edges.append(Edge("e11", "nlq", "athena", "INSERT INTO"))
    d.edges.append(Edge("e12", "stats", "athena", "GROUP BY"))
    d.edges.append(Edge("e13", "athena", "glue"))
    d.edges.append(Edge("e14", "glue", "iceberg"))

    # Ingest path
    d.edges.append(Edge("e15", "mock", "sqs", "ObjectCreated"))
    d.edges.append(Edge("e16", "sqs", "extract", "batch 25"))
    d.edges.append(Edge("e17", "extract", "athena", "INSERT INTO\nIceberg"))
    d.edges.append(Edge("e18", "compact", "athena", "MERGE/OPTIMIZE/VACUUM"))

    # Groupings
    d.groups.append(Group("g_browser", "Browser path", 60, 360, 540, 120))
    d.groups.append(Group("g_api", "API layer", 200, 560, 600, 260))
    d.groups.append(Group("g_data", "Data layer", 820, 360, 520, 320))
    d.groups.append(Group("g_ingest", "Ingest pipeline (phase 1)", 720, 60, 620, 140))

    return d


def diagram_ingest() -> Diagram:
    """Phase 1 ingest pipeline."""
    d = Diagram("02-ingest-pipeline", "Ingest pipeline", 1400, 600)

    d.nodes.append(Node("gen", "Mock generator\n(scripts/generate_config_snapshot.py)",
                        60, 240, 200, 80, plain_box("#FFE7B3", AWS_ORANGE)))
    d.nodes.append(Node("mock", "cinq-config-mock\n(gzipped JSON)", 320, 240, 120, 80,
                        aws_resource("simple_storage_service", "#7AA116")))
    d.nodes.append(Node("sqs", "cinq-extract-queue\n(SQS, batch 25, 60s)",
                        500, 240, 140, 80, aws_resource("simple_queue_service", "#FF4F8B")))
    d.nodes.append(Node("extract", "Extract Lambda\n(reserved concurrency 5)",
                        700, 240, 140, 80, aws_resource("lambda", AWS_ORANGE)))
    d.nodes.append(Node("athena_in", "Athena\nINSERT INTO",
                        900, 240, 120, 80, aws_resource("athena", "#8C4FFF")))
    d.nodes.append(Node("iceberg", "Iceberg table\ncinq.operational",
                        1080, 240, 140, 80, aws_resource("simple_storage_service", "#7AA116")))

    d.nodes.append(Node("compact", "Compact Lambda\n(nightly EventBridge)",
                        700, 460, 140, 80, aws_resource("lambda", AWS_ORANGE)))
    d.nodes.append(Node("athena_c", "Athena\nMERGE / OPTIMIZE / VACUUM",
                        900, 460, 180, 80, aws_resource("athena", "#8C4FFF")))

    d.nodes.append(Node("dlq", "DLQ\n(after 3 retries)",
                        500, 60, 140, 80, aws_resource("simple_queue_service", "#DD344C")))

    d.edges.append(Edge("e1", "gen", "mock", "uploads .json.gz"))
    d.edges.append(Edge("e2", "mock", "sqs", "S3:ObjectCreated"))
    d.edges.append(Edge("e3", "sqs", "extract", "trigger"))
    d.edges.append(Edge("e4", "extract", "athena_in", "wr.athena.to_iceberg"))
    d.edges.append(Edge("e5", "athena_in", "iceberg", "Parquet append"))

    d.edges.append(Edge("e6", "compact", "athena_c", "SQL"))
    d.edges.append(Edge("e7", "athena_c", "iceberg", "rewrite"))

    d.edges.append(Edge("e8", "sqs", "dlq", "max receives"))

    d.groups.append(Group("g_pipe", "Hot path — every snapshot, ~30s end to end", 40, 220, 1200, 120))
    d.groups.append(Group("g_compact", "Cold path — nightly compaction", 680, 440, 560, 120))

    return d


def diagram_rag_indexing() -> Diagram:
    """Phase 2 — one-off schema enrichment + embedding into S3 Vectors."""
    d = Diagram("03-rag-indexing", "Schema RAG indexing (one-off)", 1400, 500)

    d.nodes.append(Node("awslabs", "awslabs/aws-config-resource-schema\n(417 .properties.json files)",
                        60, 200, 220, 80, plain_box("#E0F0FF", AWS_BLUE)))
    d.nodes.append(Node("enrich", "scripts/enrich_schemas.py\n(threaded, idempotent)",
                        320, 200, 200, 80, plain_box("#FFE7B3", AWS_ORANGE)))
    d.nodes.append(Node("claude", "Claude Sonnet 4.6\n(via Bedrock)",
                        560, 200, 140, 80, aws_resource("sagemaker", "#01A88D")))
    d.nodes.append(Node("md", "data/enriched_schemas/\n(417 markdown docs)",
                        740, 200, 180, 80, plain_box("#E8F5E9", "#388E3C")))
    d.nodes.append(Node("indexer", "scripts/index_schemas.py",
                        960, 200, 180, 80, plain_box("#FFE7B3", AWS_ORANGE)))
    d.nodes.append(Node("titan", "Titan Embeddings v2\n(via Bedrock)",
                        1180, 80, 180, 80, aws_resource("sagemaker", "#01A88D")))
    d.nodes.append(Node("s3v", "S3 Vectors\ncinq-schemas-index\n(417 × 1024-dim)",
                        1180, 320, 180, 80, aws_resource("simple_storage_service", "#01A88D")))

    d.edges.append(Edge("e1", "awslabs", "enrich", "for each schema"))
    d.edges.append(Edge("e2", "enrich", "claude", "JSON request"))
    d.edges.append(Edge("e3", "claude", "md", "rendered .md"))
    d.edges.append(Edge("e4", "md", "indexer", "load"))
    d.edges.append(Edge("e5", "indexer", "titan", "InvokeModel"))
    d.edges.append(Edge("e6", "indexer", "s3v", "PutVectors"))

    d.groups.append(Group("g", "One-off pipeline — re-run when awslabs publishes new resource types", 40, 180, 1340, 240))

    return d


def diagram_nlq_runtime() -> Diagram:
    """Runtime path of a single NL question."""
    d = Diagram("04-nlq-runtime", "NLQ runtime path", 1400, 700)

    d.nodes.append(Node("user", "End user", 60, 320, 80, 80, actor()))
    d.nodes.append(Node("r53", "Route 53\napi.nlq.demos…", 200, 320, 100, 80,
                        aws_resource("route_53", "#8C4FFF")))
    d.nodes.append(Node("apigw", "API Gateway v2\nPOST /nlq",
                        360, 320, 120, 80, aws_resource("api_gateway", "#FF4F8B")))

    d.nodes.append(Node("auth", "Authoriser Lambda\nx-api-key check",
                        360, 480, 140, 80, aws_resource("lambda", AWS_ORANGE)))
    d.nodes.append(Node("secrets", "Secrets Manager\n(API key)",
                        540, 480, 120, 80, aws_resource("secrets_manager", "#DD344C")))

    d.nodes.append(Node("nlq", "NLQ Lambda\n(handler.py)",
                        540, 320, 120, 80, aws_resource("lambda", AWS_ORANGE)))

    # Stages
    d.nodes.append(Node("titan", "Titan v2\nembed question",
                        720, 60, 140, 80, aws_resource("sagemaker", "#01A88D")))
    d.nodes.append(Node("s3v", "S3 Vectors\nquery_vectors top-K",
                        900, 60, 140, 80, aws_resource("simple_storage_service", "#01A88D")))
    d.nodes.append(Node("md", "Bundled enriched\nmarkdown (417 docs)",
                        1080, 60, 160, 80, plain_box("#E8F5E9", "#388E3C")))
    d.nodes.append(Node("claude", "Claude Sonnet 4.6\nglobal inference profile",
                        720, 320, 180, 80, aws_resource("sagemaker", "#01A88D")))

    d.nodes.append(Node("athena", "Athena",
                        940, 320, 100, 80, aws_resource("athena", "#8C4FFF")))
    d.nodes.append(Node("glue", "Glue Catalog",
                        1080, 320, 120, 80, aws_resource("glue", "#8C4FFF")))
    d.nodes.append(Node("iceberg", "Iceberg table",
                        1240, 320, 120, 80, aws_resource("simple_storage_service", "#7AA116")))

    # Edges
    d.edges.append(Edge("e1", "user", "r53"))
    d.edges.append(Edge("e2", "r53", "apigw"))
    d.edges.append(Edge("e3", "apigw", "auth", "1. authorise"))
    d.edges.append(Edge("e4", "auth", "secrets", "GetSecretValue"))
    d.edges.append(Edge("e5", "apigw", "nlq", "2. invoke"))
    d.edges.append(Edge("e6", "nlq", "titan", "3. embed"))
    d.edges.append(Edge("e7", "nlq", "s3v", "4. retrieve top-K"))
    d.edges.append(Edge("e8", "nlq", "md", "5. read schema docs"))
    d.edges.append(Edge("e9", "nlq", "claude", "6. generate SQL"))
    d.edges.append(Edge("e10", "nlq", "athena", "7. start_query"))
    d.edges.append(Edge("e11", "athena", "glue", "schema lookup"))
    d.edges.append(Edge("e12", "athena", "iceberg", "scan"))

    d.groups.append(Group("g_auth", "Auth", 340, 460, 340, 140))
    d.groups.append(Group("g_rag", "Retrieval-augmented generation", 700, 40, 560, 140))
    d.groups.append(Group("g_query", "Query execution", 920, 300, 460, 140))

    return d


def diagram_spa_hosting() -> Diagram:
    """SPA front-end hosting (phase 4) — all on one row to avoid drawio
    auto-crop weirdness when there's a vertical gap between groups."""
    d = Diagram("05-spa-hosting", "SPA front-end hosting", 1400, 460)

    # Top row: serving path
    d.nodes.append(Node("user", "End user", 40, 200, 80, 80, actor()))
    d.nodes.append(Node("r53", "Route 53\nnlq.demos.apps.equal.expert", 160, 200, 200, 80,
                        aws_resource("route_53", "#8C4FFF")))
    d.nodes.append(Node("cf", "CloudFront\nsecurity headers + SPA fallback",
                        400, 200, 220, 80, aws_resource("cloudfront", "#8C4FFF")))
    d.nodes.append(Node("oac", "Origin Access\nControl", 660, 200, 140, 80,
                        plain_box("#E0F0FF", AWS_BLUE)))
    d.nodes.append(Node("s3", "Private S3\ncinq-nlq-spa", 840, 200, 160, 80,
                        aws_resource("simple_storage_service", "#7AA116")))

    # ACM cert sits above CloudFront
    d.nodes.append(Node("acm", "ACM cert\n(us-east-1)", 400, 60, 140, 80,
                        aws_resource("certificate_manager", "#DD344C")))

    # Build path runs along the BOTTOM but inside the same outer group
    d.nodes.append(Node("vite", "Vite + React + TS\nweb/dist/", 1060, 60, 180, 80,
                        plain_box("#FFE7B3", AWS_ORANGE)))
    d.nodes.append(Node("sync", "make spa-deploy\naws s3 sync + invalidation",
                        1060, 200, 200, 80, plain_box("#FFE7B3", AWS_ORANGE)))

    d.edges.append(Edge("e1", "user", "r53", "DNS"))
    d.edges.append(Edge("e2", "r53", "cf", "alias A"))
    d.edges.append(Edge("e3", "cf", "oac"))
    d.edges.append(Edge("e4", "oac", "s3", "signed GET"))
    d.edges.append(Edge("e5", "acm", "cf", "TLS"))

    d.edges.append(Edge("e6", "vite", "sync", "build"))
    d.edges.append(Edge("e7", "sync", "s3", "deploy"))

    d.groups.append(Group("g_serving", "Browser → CloudFront → S3", 20, 180, 1010, 130))
    d.groups.append(Group("g_build", "Build & deploy", 1040, 40, 240, 270))

    return d


# ---------- driver ----------

def render(diagram: Diagram) -> Path:
    SRC_DIR.mkdir(parents=True, exist_ok=True)
    SPA_DIR.mkdir(parents=True, exist_ok=True)
    USER_DIR.mkdir(parents=True, exist_ok=True)

    drawio_path = SRC_DIR / f"{diagram.name}.drawio"
    drawio_path.write_text(diagram.to_xml())

    png_src = SRC_DIR / f"{diagram.name}.png"
    print(f"==> rendering {diagram.name}")
    res = subprocess.run(
        [DRAWIO_BIN, "-x", "-f", "png", "-t", "-b", "20", "-s", "2",
         "-o", str(png_src), str(drawio_path)],
        check=False, capture_output=True, text=True,
    )
    if res.returncode != 0 or not png_src.exists():
        print(res.stdout)
        print(res.stderr, file=sys.stderr)
        raise RuntimeError(f"drawio export failed for {diagram.name}")

    # Copy to SPA + user dirs
    spa_path = SPA_DIR / f"{diagram.name}.png"
    user_path = USER_DIR / f"{diagram.name}.png"
    shutil.copy2(png_src, spa_path)
    shutil.copy2(png_src, user_path)
    size_kb = png_src.stat().st_size // 1024
    print(f"    wrote {png_src.name} ({size_kb} KB) → SPA + Downloads")
    return png_src


def main() -> int:
    diagrams: list[Diagram] = [
        diagram_overview(),
        diagram_ingest(),
        diagram_rag_indexing(),
        diagram_nlq_runtime(),
        diagram_spa_hosting(),
    ]
    for d in diagrams:
        render(d)
    print("\n==> done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
