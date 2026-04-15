#!/usr/bin/env python3
"""
Generate the architecture diagrams for the "How this was made" page.

Design rules — the bits that keep the diagrams clean and readable:

  1. Each diagram has ONE dominant flow direction (left→right OR top→bottom).
     No diagram mixes the two.
  2. Every edge specifies its source exit point and target entry point
     explicitly via exitX/exitY/entryX/entryY. Auto-routing is never
     trusted to pick a clean path.
  3. Boxes are laid out on a strict grid with generous gaps so edges
     have room to route without crossing other shapes.
  4. Where an edge has to bend non-trivially, explicit waypoints are
     used (Edge.waypoints).
  5. Invisible anchor cells at the page corners force drawio's PNG
     auto-crop to use the full page bounds.

Outputs land in:
    docs/architecture/                       (.drawio sources, committed)
    web/public/docs/architecture/<name>.png  (bundled into the SPA)
    /media/psf/Home/Downloads/architecture/  (your local copies)
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Tuple, List

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
    w: int = 160
    h: int = 80
    style: str = ""

    def cx(self) -> int:
        return self.x + self.w // 2

    def cy(self) -> int:
        return self.y + self.h // 2

    def to_xml(self) -> str:
        return (
            f'<mxCell id="{self.id}" value="{self.label}" '
            f'style="{self.style}" vertex="1" parent="1">'
            f'<mxGeometry x="{self.x}" y="{self.y}" width="{self.w}" height="{self.h}" as="geometry"/>'
            f"</mxCell>"
        )


# Side codes for connection points
RIGHT = (1.0, 0.5)
LEFT = (0.0, 0.5)
TOP = (0.5, 0.0)
BOTTOM = (0.5, 1.0)
TOP_LEFT = (0.0, 0.0)
TOP_RIGHT = (1.0, 0.0)
BOTTOM_LEFT = (0.0, 1.0)
BOTTOM_RIGHT = (1.0, 1.0)


@dataclass
class Edge:
    id: str
    src: str
    tgt: str
    label: str = ""
    exit: Optional[Tuple[float, float]] = None
    entry: Optional[Tuple[float, float]] = None
    waypoints: List[Tuple[int, int]] = field(default_factory=list)
    label_x: Optional[float] = None  # -1..1 along the edge path
    label_y: Optional[float] = None  # perpendicular offset

    def _style(self) -> str:
        parts = [
            "edgeStyle=orthogonalEdgeStyle",
            "rounded=0",
            "orthogonalLoop=1",
            "jettySize=auto",
            "html=1",
            "strokeColor=#232F3E",
            "strokeWidth=3",
            "fontSize=14",
            "fontStyle=1",
            "fontColor=#232F3E",
            "endArrow=block",
            "endFill=1",
            "endSize=12",
            "startSize=12",
            "labelBackgroundColor=#ffffff",
            "labelBorderColor=none",
            "spacingLeft=4",
            "spacingRight=4",
        ]
        if self.exit is not None:
            ex, ey = self.exit
            parts += [f"exitX={ex}", f"exitY={ey}", "exitDx=0", "exitDy=0"]
        if self.entry is not None:
            nx, ny = self.entry
            parts += [f"entryX={nx}", f"entryY={ny}", "entryDx=0", "entryDy=0"]
        return ";".join(parts) + ";"

    def to_xml(self) -> str:
        points_xml = ""
        if self.waypoints:
            inner = "".join(f'<mxPoint x="{x}" y="{y}"/>' for x, y in self.waypoints)
            points_xml = f'<Array as="points">{inner}</Array>'

        geom_attrs = 'relative="1" as="geometry"'
        # Optional label position (x in [-1,1] along the edge, y is perpendicular pixels)
        label_attrs = ""
        if self.label_x is not None:
            label_attrs += f' x="{self.label_x}"'
        if self.label_y is not None:
            label_attrs += f' y="{self.label_y}"'

        return (
            f'<mxCell id="{self.id}" value="{self.label}" style="{self._style()}" '
            f'edge="1" parent="1" source="{self.src}" target="{self.tgt}">'
            f"<mxGeometry{label_attrs} {geom_attrs}>{points_xml}</mxGeometry>"
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

    def to_xml(self) -> str:
        style = (
            f"rounded=0;whiteSpace=wrap;html=1;fillColor={self.fill};"
            f"strokeColor={self.stroke};dashed=1;dashPattern=4 4;"
            f"verticalAlign=top;align=left;fontSize=12;fontStyle=2;"
            f"fontColor=#666666;spacingLeft=10;spacingTop=8;"
        )
        return (
            f'<mxCell id="{self.id}" value="{self.label}" style="{style}" '
            f'vertex="1" parent="1">'
            f'<mxGeometry x="{self.x}" y="{self.y}" width="{self.w}" height="{self.h}" as="geometry"/>'
            f"</mxCell>"
        )


@dataclass
class Diagram:
    name: str
    title: str
    width: int
    height: int
    nodes: List[Node] = field(default_factory=list)
    edges: List[Edge] = field(default_factory=list)
    groups: List[Group] = field(default_factory=list)

    def _anchor_cells(self) -> List[Node]:
        invisible = (
            "rounded=0;whiteSpace=wrap;html=1;"
            "fillColor=none;strokeColor=none;fontSize=1;fontColor=none;"
        )
        return [
            Node("__a_tl", " ", 0, 0, 1, 1, invisible),
            Node("__a_br", " ", self.width - 1, self.height - 1, 1, 1, invisible),
        ]

    def to_xml(self) -> str:
        body = ""
        for n in self._anchor_cells():
            body += n.to_xml()
        # groups first so nodes paint on top
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
    """AWS resource icon with the standard label-below layout."""
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
        "verticalAlign=top;align=center;html=1;fontSize=13;fontStyle=1;"
        "aspect=fixed;shape=mxgraph.aws4.users;"
    )


def plain_box(fill: str = "#FFFFFF", stroke: str = AWS_DARK) -> str:
    return (
        f"rounded=0;whiteSpace=wrap;html=1;fillColor={fill};strokeColor={stroke};"
        "fontColor=#232F3E;fontSize=13;fontStyle=1;align=center;verticalAlign=middle;"
        "strokeWidth=2;"
    )


# ---------- diagrams ----------

def diagram_overview() -> Diagram:
    """High-level system overview.

    Strict three-column layout so every arrow stays within its own
    swim-lane. The SPA path, the runtime API path, and the ingest
    pipeline each occupy a distinct column with their own top-down
    flow. The only cross-column edges are:

      * User → CloudFront and User → API Gateway (the two public entry
        points) at the very top, with separated buses so they cannot
        sit on top of each other.
      * Extract Lambda → shared Iceberg table, routed through the far
        RIGHT gutter (empty reserved column) so it never crosses the
        backend resources or the runtime API column.

    The 3-way fan-out from the NLQ Lambdas into Bedrock / S3 Vectors /
    Athena is represented by a SINGLE arrow into a labelled backends
    group (detail lives in diagram 04).
    """
    W, H = 2200, 1200
    d = Diagram("01-system-overview", "System overview", W, H)

    # ---- reserved gutters (no nodes placed here) ----
    RIGHT_GUTTER_X = W - 40

    # ---- column anchors (well-spaced, no overlaps) ----
    USER_X = 60
    SPA_X = 260       # CloudFront + SPA bucket column
    API_X = 740       # API Gateway + NLQ Lambdas column
    AUTH_X = 470      # Authoriser + Secrets column (between SPA and API)
    BACKENDS_X = 1080 # Bedrock + S3 Vectors + Athena container
    INGEST_X = 1800   # Ingest pipeline column (far right, clear of backends)

    # ---- row anchors ----
    R_USER = 60
    R_EDGE = 240        # CloudFront / API GW / Mock bucket
    R_LAMBDAS = 440     # SPA bucket / Auth / NLQ / SQS
    R_RESOURCES = 640   # Secrets / (Backends container top) / Extract
    R_TABLE = 920       # Iceberg (shared)

    # ---- nodes ----
    d.nodes.append(Node("user", "End user", USER_X, R_USER, 100, 90, actor()))

    # ---- SPA (browser) column ----
    d.nodes.append(Node("cf", "CloudFront",
                        SPA_X, R_EDGE, 180, 90,
                        aws_resource("cloudfront", "#8C4FFF")))
    d.nodes.append(Node("spa_s3", "SPA bucket\ncinq-nlq-spa",
                        SPA_X, R_LAMBDAS, 180, 90,
                        aws_resource("simple_storage_service", "#7AA116")))

    # ---- API runtime column ----
    d.nodes.append(Node("apigw", "API Gateway v2\nHTTP API",
                        API_X, R_EDGE, 220, 90,
                        aws_resource("api_gateway", "#FF4F8B")))
    d.nodes.append(Node("nlq", "NLQ Lambdas\nsubmit + worker",
                        API_X, R_LAMBDAS, 220, 90,
                        aws_resource("lambda", AWS_ORANGE)))
    d.nodes.append(Node("jobs", "Jobs bucket\n(S3)",
                        API_X, R_RESOURCES, 220, 90,
                        aws_resource("simple_storage_service", "#7AA116")))

    # ---- Auth column (between SPA and API) ----
    d.nodes.append(Node("auth", "Authoriser\nLambda",
                        AUTH_X, R_LAMBDAS, 200, 90,
                        aws_resource("lambda", AWS_ORANGE)))
    d.nodes.append(Node("secrets", "Secrets\nManager",
                        AUTH_X, R_RESOURCES, 200, 90,
                        aws_resource("secrets_manager", "#DD344C")))

    # ---- Backends container (Bedrock + S3 Vectors + Athena, horizontally) ----
    # These are laid out inside a group to make clear they're one
    # logical "shared backends" boundary — edges into the group come
    # from the NLQ Lambda, edges out go to Iceberg.
    backend_w = 200
    backend_gap = 30
    backend_h = 110
    BE_ROW_Y = R_RESOURCES
    d.nodes.append(Node("bedrock", "Amazon Bedrock\n(Titan + Claude)",
                        BACKENDS_X, BE_ROW_Y, backend_w, backend_h,
                        aws_resource("sagemaker", "#01A88D")))
    d.nodes.append(Node("s3v", "S3 Vectors\n(417 schemas)",
                        BACKENDS_X + (backend_w + backend_gap), BE_ROW_Y,
                        backend_w, backend_h,
                        aws_resource("simple_storage_service", "#01A88D")))
    d.nodes.append(Node("athena", "Athena",
                        BACKENDS_X + 2 * (backend_w + backend_gap), BE_ROW_Y,
                        backend_w, backend_h,
                        aws_resource("athena", "#8C4FFF")))

    # ---- Ingest pipeline column (far right) ----
    d.nodes.append(Node("mock", "cinq-config-mock\n(S3)",
                        INGEST_X, R_EDGE, 220, 90,
                        aws_resource("simple_storage_service", "#7AA116")))
    d.nodes.append(Node("sqs", "cinq-extract\n(SQS, batched)",
                        INGEST_X, R_LAMBDAS, 220, 90,
                        aws_resource("simple_queue_service", "#FF4F8B")))
    d.nodes.append(Node("extract", "Extract Lambda\n(append to Iceberg)",
                        INGEST_X, R_RESOURCES, 220, 90,
                        aws_resource("lambda", AWS_ORANGE)))

    # ---- Shared Iceberg table ----
    iceberg_x = BACKENDS_X + (backend_w + backend_gap)  # under the middle backend (S3 Vectors)
    d.nodes.append(Node("iceberg", "Iceberg table\ncinq.operational",
                        iceberg_x, R_TABLE, backend_w, 90,
                        aws_resource("simple_storage_service", "#7AA116")))

    # ---- edges ----

    # User has TWO outgoing arrows. Use two different horizontal buses
    # anchored to different exit Ys on the user actor so they cannot
    # overlap.
    d.edges.append(Edge(
        "u_cf", "user", "cf", "HTTPS",
        exit=(1.0, 0.35), entry=TOP,
        waypoints=[(SPA_X + 90, R_USER + 30)],
    ))
    d.edges.append(Edge(
        "u_api", "user", "apigw", "POST /nlq",
        exit=(1.0, 0.65), entry=TOP,
        waypoints=[(API_X + 110, R_USER + 60)],
    ))

    # SPA path
    d.edges.append(Edge("cf_s3", "cf", "spa_s3", "OAC",
                        exit=BOTTOM, entry=TOP))

    # API runtime column — straight down
    d.edges.append(Edge("api_nlq", "apigw", "nlq", "invoke",
                        exit=BOTTOM, entry=TOP))
    d.edges.append(Edge("nlq_jobs", "nlq", "jobs", "write progress",
                        exit=BOTTOM, entry=TOP))

    # API GW → Authoriser (down-left, through the clear gap at y=R_EDGE+120)
    d.edges.append(Edge(
        "api_auth", "apigw", "auth", "x-api-key",
        exit=(0.1, 1.0), entry=TOP,
        waypoints=[
            (API_X + int(220 * 0.1), R_EDGE + 130),
            (AUTH_X + 100, R_EDGE + 130),
        ],
    ))
    d.edges.append(Edge("auth_secrets", "auth", "secrets", "GetSecret",
                        exit=BOTTOM, entry=TOP))

    # NLQ → Backends container (ONE arrow, right into the group)
    d.edges.append(Edge(
        "nlq_backends", "nlq", "bedrock", "embed / retrieve / generate / query",
        exit=RIGHT, entry=LEFT,
        waypoints=[(BACKENDS_X - 40, R_LAMBDAS + 45),
                   (BACKENDS_X - 40, BE_ROW_Y + backend_h // 2)],
    ))

    # Athena → Iceberg (straight down from the right-most backend)
    d.edges.append(Edge(
        "athena_iceberg", "athena", "iceberg",
        exit=(0.1, 1.0), entry=(0.9, 0.0),
        waypoints=[
            (BACKENDS_X + 2 * (backend_w + backend_gap) + int(backend_w * 0.1),
             R_TABLE - 40),
            (iceberg_x + int(backend_w * 0.9), R_TABLE - 40),
        ],
    ))

    # Ingest column — straight down
    d.edges.append(Edge("mock_sqs", "mock", "sqs", "ObjectCreated",
                        exit=BOTTOM, entry=TOP))
    d.edges.append(Edge("sqs_extract", "sqs", "extract", "batch 25",
                        exit=BOTTOM, entry=TOP))

    # Extract → Iceberg — routed via RIGHT gutter so it never crosses
    # any other node. Exit extract RIGHT → far right gutter → drop to
    # iceberg row → approach iceberg from its RIGHT side.
    d.edges.append(Edge(
        "extract_iceberg", "extract", "iceberg", "Athena INSERT",
        exit=RIGHT, entry=RIGHT,
        waypoints=[
            (RIGHT_GUTTER_X, R_RESOURCES + 45),   # into the right gutter
            (RIGHT_GUTTER_X, R_TABLE + 45),       # down to iceberg row
        ],
    ))

    # ---- groupings ----
    d.groups.append(Group(
        "g_browser", "Browser path",
        SPA_X - 40, R_EDGE - 50, 260, R_LAMBDAS + 130 - (R_EDGE - 50),
    ))
    d.groups.append(Group(
        "g_auth", "Authoriser",
        AUTH_X - 30, R_LAMBDAS - 40, 260, R_RESOURCES + 120 - (R_LAMBDAS - 40),
    ))
    d.groups.append(Group(
        "g_api", "Runtime API",
        API_X - 40, R_EDGE - 50, 300, R_RESOURCES + 130 - (R_EDGE - 50),
    ))
    d.groups.append(Group(
        "g_backends", "Shared backends",
        BACKENDS_X - 30, BE_ROW_Y - 40,
        3 * backend_w + 2 * backend_gap + 60, backend_h + 60,
    ))
    d.groups.append(Group(
        "g_ingest", "Ingest pipeline (phase 1)",
        INGEST_X - 30, R_EDGE - 50, 280, R_RESOURCES + 130 - (R_EDGE - 50),
    ))

    return d


def diagram_ingest() -> Diagram:
    """Phase 1 — single horizontal flow with two upstream branches."""
    W, H = 1900, 720
    d = Diagram("02-ingest-pipeline", "Ingest pipeline", W, H)

    # Single horizontal row at y=300
    Y = 300
    GAP = 280

    nodes_def = [
        ("gen", "Mock generator\n(scripts/generate_…)", 60, plain_box("#FFE7B3", AWS_ORANGE), 220),
        ("mock", "cinq-config-mock\n(S3)", 60 + GAP, aws_resource("simple_storage_service", "#7AA116"), 200),
        ("sqs", "cinq-extract-queue\n(SQS, batch 25, 60s)", 60 + GAP * 2 + 20, aws_resource("simple_queue_service", "#FF4F8B"), 220),
        ("extract", "Extract Lambda\nreserved concurrency 5", 60 + GAP * 3 + 40, aws_resource("lambda", AWS_ORANGE), 220),
        ("athena_in", "Athena\nINSERT INTO", 60 + GAP * 4 + 60, aws_resource("athena", "#8C4FFF"), 200),
        ("iceberg", "Iceberg table\ncinq.operational", 60 + GAP * 5 + 60, aws_resource("simple_storage_service", "#7AA116"), 220),
    ]
    for nid, label, x, style, w in nodes_def:
        d.nodes.append(Node(nid, label, x, Y, w, 80, style))

    # DLQ (above sqs)
    d.nodes.append(Node("dlq", "DLQ\n(after 3 retries)",
                        60 + GAP * 2 + 30, 80, 200, 80,
                        aws_resource("simple_queue_service", "#DD344C")))

    # Compact path — single row at y=540
    d.nodes.append(Node("compact", "Compact Lambda\n(nightly)",
                        60 + GAP * 3 + 40, 540, 220, 80,
                        aws_resource("lambda", AWS_ORANGE)))
    d.nodes.append(Node("athena_c", "Athena\nMERGE / OPTIMIZE / VACUUM",
                        60 + GAP * 4 + 60, 540, 200, 80,
                        aws_resource("athena", "#8C4FFF")))

    # Hot path edges — strict L→R, all entering left, exiting right
    chain = ["gen", "mock", "sqs", "extract", "athena_in", "iceberg"]
    chain_labels = ["upload .json.gz", "ObjectCreated", "trigger",
                    "wr.athena.to_iceberg", "Parquet append"]
    for i, (a, b, label) in enumerate(zip(chain, chain[1:], chain_labels)):
        d.edges.append(Edge(f"hot{i}", a, b, label,
                            exit=RIGHT, entry=LEFT))

    # SQS → DLQ (up)
    d.edges.append(Edge("e_dlq", "sqs", "dlq", "max receives",
                        exit=TOP, entry=BOTTOM))

    # Compact → Athena_c → Iceberg (loops up)
    d.edges.append(Edge("c1", "compact", "athena_c", "SQL",
                        exit=RIGHT, entry=LEFT))
    d.edges.append(Edge("c2", "athena_c", "iceberg", "rewrite",
                        exit=TOP, entry=BOTTOM,
                        waypoints=[(60 + GAP * 4 + 60 + 100, 460)]))

    # Groupings
    d.groups.append(Group("g_hot", "Hot path — runs on every snapshot, ~30s end to end",
                          40, 240, W - 80, 200))
    d.groups.append(Group("g_cold", "Cold path — nightly compaction",
                          60 + GAP * 3 + 20, 480, GAP * 2 + 60, 180))

    return d


def diagram_rag_indexing() -> Diagram:
    """Phase 2 — strict L→R single-row chain."""
    W, H = 2000, 600
    d = Diagram("03-rag-indexing", "Schema RAG indexing (one-off)", W, H)

    Y = 240
    GAP = 280
    items = [
        ("schemas", "awslabs/aws-config-\nresource-schema\n(417 .properties.json)",
         60, plain_box("#E0F0FF", AWS_BLUE), 240),
        ("enrich", "scripts/\nenrich_schemas.py",
         60 + GAP, plain_box("#FFE7B3", AWS_ORANGE), 220),
        ("claude", "Claude Sonnet 4.6\n(Bedrock)",
         60 + GAP * 2, aws_resource("sagemaker", "#01A88D"), 200),
        ("md", "data/enriched_schemas/\n(417 markdown docs)",
         60 + GAP * 3, plain_box("#E8F5E9", "#388E3C"), 240),
        ("indexer", "scripts/\nindex_schemas.py",
         60 + GAP * 4, plain_box("#FFE7B3", AWS_ORANGE), 220),
        ("titan", "Titan Text\nEmbeddings v2",
         60 + GAP * 5, aws_resource("sagemaker", "#01A88D"), 200),
        ("s3v", "S3 Vectors\ncinq-schemas-index\n(417 × 1024-dim)",
         60 + GAP * 6, aws_resource("simple_storage_service", "#01A88D"), 240),
    ]
    for nid, label, x, style, w in items:
        d.nodes.append(Node(nid, label, x, Y, w, 90, style))

    chain = [i[0] for i in items]
    labels = ["per file", "JSON\nrequest", "rendered\nmarkdown",
              "load", "InvokeModel", "PutVectors"]
    for i, (a, b, label) in enumerate(zip(chain, chain[1:], labels)):
        d.edges.append(Edge(f"e{i}", a, b, label,
                            exit=RIGHT, entry=LEFT))

    d.groups.append(Group("g", "One-off pipeline — re-run when awslabs publishes new resource types",
                          40, 200, W - 80, 220))
    return d


def diagram_nlq_runtime() -> Diagram:
    """Phase 3 — async NLQ runtime, AWS-style layout.

    Design rules enforced below:
      * Strict hierarchical top-down flow. User at top, worker pipeline
        at the bottom, intermediate Lambdas + storage in between.
      * Two empty "gutters" (LEFT_GUTTER_X and RIGHT_GUTTER_X) reserved
        for back-edges. Any edge that needs to route around the main
        content uses one of these gutters — and no node ever sits inside
        a gutter, so the back-edges are physically incapable of
        overlapping any box.
      * The two cross-cluster back-edges (Submit→Worker async invoke,
        Worker→Jobs progress write) use DIFFERENT gutters so they can't
        touch each other either.
      * L→R pipeline flow at the bottom is a single row: worker + four
        stages in sequence, with athena → iceberg as the only downward
        arrow.
    """
    W, H = 2200, 1400
    d = Diagram("04-nlq-runtime", "NLQ runtime path (async)", W, H)

    # ---- gutters (empty columns reserved for back-edges) ----
    # Nothing is ever placed in x=0..GUTTER_L or x=W-GUTTER_R..W so the
    # back-edge arrows can run through them without colliding with any box.
    LEFT_GUTTER_X = 30
    RIGHT_GUTTER_X = W - 30

    # ---- row anchors (top-down) ----
    R_USER = 60
    R_ROUTE = 220
    R_APIGW = 380
    R_LAMBDAS = 560    # auth + submit
    R_STORE = 740      # secrets + jobs bucket
    R_WORKER = 980     # worker + stages in one horizontal row
    R_ICEBERG = 1180

    # ---- column anchors ----
    C_AUTH = 200
    AUTH_W = 240
    C_SUBMIT = 760
    SUBMIT_W = 380
    C_STAGE_START = 100  # worker + stages start here

    # ---- top cluster nodes ----
    # User — centred above apigw
    d.nodes.append(Node("user", "End user",
                        C_SUBMIT + SUBMIT_W // 2 - 50, R_USER, 100, 90, actor()))

    # Route 53
    d.nodes.append(Node(
        "r53", "Route 53\napi.nlq.demos.apps.equal.expert",
        C_SUBMIT + SUBMIT_W // 2 - 180, R_ROUTE, 360, 90,
        aws_resource("route_53", "#8C4FFF"),
    ))

    # API Gateway
    d.nodes.append(Node(
        "apigw",
        "API Gateway v2 HTTP API\nPOST /nlq      GET /nlq/jobs/{id}",
        C_SUBMIT + SUBMIT_W // 2 - 220, R_APIGW, 440, 100,
        aws_resource("api_gateway", "#FF4F8B"),
    ))

    # Authoriser + Secrets — left column
    d.nodes.append(Node(
        "auth", "Authoriser Lambda",
        C_AUTH, R_LAMBDAS, AUTH_W, 100,
        aws_resource("lambda", AWS_ORANGE),
    ))
    d.nodes.append(Node(
        "secrets", "Secrets Manager",
        C_AUTH, R_STORE, AUTH_W, 100,
        aws_resource("secrets_manager", "#DD344C"),
    ))

    # Submit/Status Lambda + Jobs bucket — centre column
    d.nodes.append(Node(
        "submit", "Submit / Status Lambda\n(handler.py)",
        C_SUBMIT, R_LAMBDAS, SUBMIT_W, 100,
        aws_resource("lambda", AWS_ORANGE),
    ))
    d.nodes.append(Node(
        "jobs", "Jobs Bucket  (S3)\ncinq-nlq-jobs   |   TTL 1 day",
        C_SUBMIT, R_STORE, SUBMIT_W, 110,
        aws_resource("simple_storage_service", "#7AA116"),
    ))

    # ---- bottom cluster: worker pipeline as a single L→R row ----
    worker_w = 280
    stage_w = 240
    stage_gap = 50
    stage_h = 120
    stage_positions = [
        ("worker",
         "NLQ Worker Lambda\n(worker.py)\ntimeout 5 min",
         worker_w, aws_resource("lambda", AWS_ORANGE)),
        ("titan",
         "Titan v2\nembed question",
         stage_w, aws_resource("sagemaker", "#01A88D")),
        ("s3v",
         "S3 Vectors\nretrieve schemas",
         stage_w, aws_resource("simple_storage_service", "#01A88D")),
        ("claude",
         "Claude Sonnet 4.6\ngenerate SQL",
         stage_w, aws_resource("sagemaker", "#01A88D")),
        ("athena",
         "Athena\nrun SELECT",
         stage_w, aws_resource("athena", "#8C4FFF")),
    ]
    x_cursor = C_STAGE_START
    stage_x: dict[str, int] = {}
    stage_w_map: dict[str, int] = {}
    for nid, label, w, style in stage_positions:
        stage_x[nid] = x_cursor
        stage_w_map[nid] = w
        d.nodes.append(Node(nid, label, x_cursor, R_WORKER, w, stage_h, style))
        x_cursor += w + stage_gap

    # Iceberg — directly below athena
    athena_x = stage_x["athena"]
    d.nodes.append(Node(
        "iceberg", "Iceberg table\ncinq.operational",
        athena_x, R_ICEBERG, stage_w, 100,
        aws_resource("simple_storage_service", "#7AA116"),
    ))

    # ---- edges: top cluster (all strictly downward) ----
    d.edges.append(Edge("e1", "user", "r53", "HTTPS",
                        exit=BOTTOM, entry=TOP))
    d.edges.append(Edge("e2", "r53", "apigw", "alias",
                        exit=BOTTOM, entry=TOP))

    # API Gateway → Authoriser (every request). Exit far-left of apigw,
    # route down-left via a dedicated waypoint at y=R_APIGW+140 (above
    # the Lambda row).
    d.edges.append(Edge(
        "e3", "apigw", "auth", "x-api-key",
        exit=(0.15, 1.0), entry=TOP,
        waypoints=[(C_AUTH + AUTH_W // 2, R_LAMBDAS - 40)],
    ))
    # Authoriser → Secrets
    d.edges.append(Edge("e4", "auth", "secrets", "GetSecret",
                        exit=BOTTOM, entry=TOP))
    # API Gateway → Submit (straight down)
    d.edges.append(Edge(
        "e5", "apigw", "submit", "invoke",
        exit=(0.75, 1.0), entry=(0.75, 0.0),
    ))
    # Submit → Jobs (straight down, left half)
    d.edges.append(Edge(
        "e6", "submit", "jobs", "write progress",
        exit=(0.25, 1.0), entry=(0.25, 0.0),
    ))
    # Jobs → Submit (poll read, right half — far from the write arrow)
    d.edges.append(Edge(
        "e7", "jobs", "submit", "poll read",
        exit=(0.75, 0.0), entry=(0.75, 1.0),
    ))

    # ---- bottom cluster: L→R pipeline ----
    chain = ["worker", "titan", "s3v", "claude", "athena"]
    labels = ["1. embed", "2. retrieve", "3. generate", "4. query"]
    for i, (a, b, label) in enumerate(zip(chain, chain[1:], labels)):
        d.edges.append(Edge(f"p{i}", a, b, label,
                            exit=RIGHT, entry=LEFT))

    # Athena → Iceberg (straight down)
    d.edges.append(Edge("e_iceberg", "athena", "iceberg", "SELECT",
                        exit=BOTTOM, entry=TOP))

    # ---- cross-cluster back-edges, routed through the GUTTERS ----
    # Rule: any edge that has to travel between the top cluster and the
    # bottom cluster exits its source node, walks into a clear horizontal
    # "gap row" (either above-auth or between-auth-and-secrets), then
    # travels down through a column that contains NO nodes, and enters
    # the target from the same clear side. The two back-edges use
    # opposite gutters so they can't touch each other either.

    # Clear Y gaps in the top cluster (any bus travelling horizontally
    # across the top cluster must use one of these Ys):
    BUS_Y_BETWEEN_LAMBDAS = R_LAMBDAS + 100 + 40   # between auth/submit bottom and secrets/jobs top
    BUS_Y_MIDGAP = R_STORE + 110 + 65              # between jobs bottom and worker top

    worker_left_x = stage_x["worker"]
    worker_right_x = worker_left_x + worker_w

    # (A) Submit → Worker async invoke — exits submit LEFT at its
    # bottom-left corner, turns down into the gap Y between the lambdas
    # and the stores, then tracks left along that gap past the
    # authoriser, down the left gutter, and into the worker's LEFT edge.
    d.edges.append(Edge(
        "async_invoke", "submit", "worker", "async invoke",
        exit=(0.0, 1.0), entry=(0.0, 0.5),
        waypoints=[
            (C_SUBMIT - 1, BUS_Y_BETWEEN_LAMBDAS),       # step into the gap row
            (LEFT_GUTTER_X, BUS_Y_BETWEEN_LAMBDAS),       # travel left into the gutter
            (LEFT_GUTTER_X, R_WORKER + stage_h // 2),     # drop down the left gutter
        ],
    ))

    # (B) Worker → Jobs progress writes — exits worker TOP-RIGHT,
    # steps up into the mid-gap row above the worker row, travels right
    # into the right gutter, climbs the right gutter, then slides left
    # along the between-lambdas gap row and into the jobs bucket's RIGHT
    # edge. Uses OPPOSITE Xs from the async-invoke edge throughout.
    jobs_right_x = C_SUBMIT + SUBMIT_W
    d.edges.append(Edge(
        "progress_write", "worker", "jobs",
        "writes progress after every stage",
        exit=(0.95, 0.0), entry=(1.0, 0.5),
        waypoints=[
            (worker_left_x + int(worker_w * 0.95), BUS_Y_MIDGAP),
            (RIGHT_GUTTER_X, BUS_Y_MIDGAP),
            (RIGHT_GUTTER_X, BUS_Y_BETWEEN_LAMBDAS),
            (jobs_right_x + 20, BUS_Y_BETWEEN_LAMBDAS),
        ],
    ))

    # ---- groupings ----
    d.groups.append(Group(
        "g_submit", "Submit + Status  —  API Gateway-bound, sub-second",
        70, R_APIGW - 40, W - 140, R_STORE + 140 - (R_APIGW - 40),
    ))
    d.groups.append(Group(
        "g_worker", "Async Worker Pipeline  —  no 30s cap, runs up to 5 min",
        70, R_WORKER - 40, W - 140, R_ICEBERG + 120 - (R_WORKER - 40),
    ))

    return d


def diagram_spa_hosting() -> Diagram:
    """Phase 4 — strict L→R serving path with build path below."""
    W, H = 2000, 720
    d = Diagram("05-spa-hosting", "SPA front-end hosting", W, H)

    # Top: serving path
    Y_TOP = 280
    d.nodes.append(Node("user", "End user", 60, Y_TOP, 100, 80, actor()))
    d.nodes.append(Node("r53", "Route 53\nnlq.demos.apps.equal.expert",
                        220, Y_TOP, 280, 80,
                        aws_resource("route_53", "#8C4FFF")))
    d.nodes.append(Node("cf", "CloudFront\nsecurity headers + SPA fallback",
                        560, Y_TOP, 280, 80,
                        aws_resource("cloudfront", "#8C4FFF")))
    d.nodes.append(Node("oac", "Origin Access\nControl", 900, Y_TOP, 200, 80,
                        plain_box("#E0F0FF", AWS_BLUE)))
    d.nodes.append(Node("s3", "Private S3 bucket\ncinq-nlq-spa",
                        1160, Y_TOP, 240, 80,
                        aws_resource("simple_storage_service", "#7AA116")))

    # ACM cert above CloudFront
    d.nodes.append(Node("acm", "ACM cert\n(us-east-1)",
                        560, 80, 280, 80,
                        aws_resource("certificate_manager", "#DD344C")))

    # Bottom: build pipeline ending at S3
    Y_BOT = 540
    d.nodes.append(Node("vite", "Vite + React + TS\nweb/dist/",
                        220, Y_BOT, 280, 80,
                        plain_box("#FFE7B3", AWS_ORANGE)))
    d.nodes.append(Node("makefile", "make spa-deploy",
                        560, Y_BOT, 280, 80,
                        plain_box("#FFE7B3", AWS_ORANGE)))
    d.nodes.append(Node("sync", "aws s3 sync +\nCloudFront invalidation",
                        900, Y_BOT, 280, 80,
                        plain_box("#FFE7B3", AWS_ORANGE)))

    # Top row L→R
    chain = ["user", "r53", "cf", "oac", "s3"]
    labels = ["DNS", "alias A", "OAC", "signed GET"]
    for i, (a, b, label) in enumerate(zip(chain, chain[1:], labels)):
        d.edges.append(Edge(f"top{i}", a, b, label,
                            exit=RIGHT, entry=LEFT))

    # ACM → CloudFront (down)
    d.edges.append(Edge("acm_cf", "acm", "cf", "TLS",
                        exit=BOTTOM, entry=TOP))

    # Build path L→R
    d.edges.append(Edge("b1", "vite", "makefile", "build",
                        exit=RIGHT, entry=LEFT))
    d.edges.append(Edge("b2", "makefile", "sync",
                        exit=RIGHT, entry=LEFT))
    # Sync → S3 (up)
    d.edges.append(Edge("b3", "sync", "s3", "deploy",
                        exit=TOP, entry=BOTTOM,
                        waypoints=[(1040, 480), (1280, 480)]))

    d.groups.append(Group("g_serving", "Serving path", 40, 240, W - 80, 200))
    d.groups.append(Group("g_build", "Build & deploy", 200, 500, 1000, 160))

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
