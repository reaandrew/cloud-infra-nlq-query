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
            "strokeWidth=2",
            "fontSize=12",
            "fontColor=#232F3E",
            "endArrow=block",
            "endFill=1",
            "endSize=8",
            "labelBackgroundColor=#ffffff",
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

    Strict top-to-bottom layout in 5 rows. Single user on the left
    branches into the SPA path on the left half and the API path on
    the right half. Backend resources (Bedrock, S3 Vectors, Athena,
    Iceberg) sit on a shared bottom row reachable only from the API
    path. The ingest pipeline is a SINGLE labelled column on the
    far right so it stays out of the way of the runtime path edges.
    """
    W, H = 1800, 1100
    d = Diagram("01-system-overview", "System overview", W, H)

    # Column anchors
    SPA_X = 240
    AUTH_X = 600
    API_X = 880
    INGEST_X = 1380
    BACKEND_GAP = 240

    # Row anchors
    R_USER = 60
    R_EDGE = 240        # CloudFront / API GW
    R_LAMBDAS = 420     # SPA bucket / Auth / NLQ Lambda
    R_RESOURCES = 600   # Bedrock / S3 Vectors / Athena
    R_TABLE = 800       # Iceberg

    # ---- nodes ----
    d.nodes.append(Node("user", "End user", 60, R_USER, 80, 80, actor()))

    # SPA path (left)
    d.nodes.append(Node("cf", "CloudFront", SPA_X, R_EDGE, 160, 80,
                        aws_resource("cloudfront", "#8C4FFF")))
    d.nodes.append(Node("spa_s3", "SPA bucket\n(S3)", SPA_X, R_LAMBDAS, 160, 80,
                        aws_resource("simple_storage_service", "#7AA116")))

    # Auth column
    d.nodes.append(Node("apigw", "API Gateway v2\nHTTP API", API_X, R_EDGE, 200, 80,
                        aws_resource("api_gateway", "#FF4F8B")))
    d.nodes.append(Node("auth", "Authoriser\nLambda", AUTH_X, R_LAMBDAS, 160, 80,
                        aws_resource("lambda", AWS_ORANGE)))
    d.nodes.append(Node("secrets", "Secrets\nManager", AUTH_X, R_RESOURCES, 160, 80,
                        aws_resource("secrets_manager", "#DD344C")))

    # API + NLQ Lambda + Stats Lambda
    d.nodes.append(Node("nlq", "NLQ Lambda", API_X, R_LAMBDAS, 200, 80,
                        aws_resource("lambda", AWS_ORANGE)))

    # Backend row — Bedrock, S3 Vectors, Athena across the bottom
    d.nodes.append(Node("bedrock", "Amazon Bedrock\n(Titan + Claude)",
                        API_X - 80, R_RESOURCES, 200, 80,
                        aws_resource("sagemaker", "#01A88D")))
    d.nodes.append(Node("s3v", "S3 Vectors\n(417 schemas)",
                        API_X - 80 + BACKEND_GAP, R_RESOURCES, 200, 80,
                        aws_resource("simple_storage_service", "#01A88D")))
    d.nodes.append(Node("athena", "Athena",
                        API_X - 80 + BACKEND_GAP * 2, R_RESOURCES, 200, 80,
                        aws_resource("athena", "#8C4FFF")))

    # Iceberg single shared sink
    d.nodes.append(Node("iceberg", "Iceberg table\ncinq.operational",
                        API_X - 80 + BACKEND_GAP * 2, R_TABLE, 200, 80,
                        aws_resource("simple_storage_service", "#7AA116")))

    # Ingest column (far right)
    d.nodes.append(Node("mock", "cinq-config-mock\n(S3)", INGEST_X, R_EDGE, 220, 80,
                        aws_resource("simple_storage_service", "#7AA116")))
    d.nodes.append(Node("sqs", "cinq-extract\n(SQS, batched)", INGEST_X, R_LAMBDAS, 220, 80,
                        aws_resource("simple_queue_service", "#FF4F8B")))
    d.nodes.append(Node("extract", "Extract Lambda\n(append to Iceberg)", INGEST_X, R_RESOURCES, 220, 80,
                        aws_resource("lambda", AWS_ORANGE)))

    # ---- edges ----
    # User → CloudFront (down-and-right). Bus at Y=R_USER+30.
    d.edges.append(Edge(
        "e1", "user", "cf", "GET",
        exit=(1.0, 0.4), entry=TOP,
        waypoints=[(SPA_X + 80, R_USER + 32)],
    ))
    # User → API GW uses a DIFFERENT horizontal bus and exit Y so its
    # line never sits on top of e1's line.
    d.edges.append(Edge(
        "e2", "user", "apigw", "POST /nlq",
        exit=(1.0, 0.6), entry=TOP,
        waypoints=[(API_X + 100, R_USER + 60)],
    ))

    # SPA path top→bottom
    d.edges.append(Edge("e3", "cf", "spa_s3", "OAC",
                        exit=BOTTOM, entry=TOP))

    # API GW → Auth (left bend)
    d.edges.append(Edge("e4", "apigw", "auth", "x-api-key",
                        exit=BOTTOM, entry=TOP,
                        waypoints=[(AUTH_X + 80, R_EDGE + 130)]))
    # Auth → Secrets
    d.edges.append(Edge("e5", "auth", "secrets", "GetSecret",
                        exit=BOTTOM, entry=TOP))
    # API GW → NLQ Lambda (straight down)
    d.edges.append(Edge("e6", "apigw", "nlq",
                        exit=BOTTOM, entry=TOP))

    # NLQ Lambda fans down into Bedrock / S3 Vectors / Athena.
    # Each edge uses a DISTINCT exit-X on the NLQ Lambda and a DISTINCT
    # horizontal-bus Y so no two edges ever share a pixel.
    bedrock_cx = API_X - 80 + 100
    s3v_cx = API_X - 80 + BACKEND_GAP + 100
    athena_cx = API_X - 80 + BACKEND_GAP * 2 + 100
    # exit positions along the bottom of the NLQ Lambda (200px wide)
    d.edges.append(Edge("e7", "nlq", "bedrock", "embed + chat",
                        exit=(0.2, 1.0), entry=TOP,
                        waypoints=[(API_X + 40, R_LAMBDAS + 110),
                                   (bedrock_cx, R_LAMBDAS + 110)]))
    d.edges.append(Edge("e8", "nlq", "s3v", "query top-K",
                        exit=(0.5, 1.0), entry=TOP,
                        waypoints=[(API_X + 100, R_LAMBDAS + 140),
                                   (s3v_cx, R_LAMBDAS + 140)]))
    d.edges.append(Edge("e9", "nlq", "athena", "INSERT/SELECT",
                        exit=(0.8, 1.0), entry=TOP,
                        waypoints=[(API_X + 160, R_LAMBDAS + 170),
                                   (athena_cx, R_LAMBDAS + 170)]))

    # Athena → Iceberg
    d.edges.append(Edge("e10", "athena", "iceberg",
                        exit=BOTTOM, entry=TOP))

    # Ingest column top→bottom
    d.edges.append(Edge("e11", "mock", "sqs", "ObjectCreated",
                        exit=BOTTOM, entry=TOP))
    d.edges.append(Edge("e12", "sqs", "extract", "batch 25",
                        exit=BOTTOM, entry=TOP))
    # Extract Lambda → Iceberg (sweep across to the right of athena)
    d.edges.append(Edge("e13", "extract", "iceberg", "Athena INSERT",
                        exit=BOTTOM, entry=RIGHT,
                        waypoints=[(INGEST_X + 110, R_TABLE + 40),
                                   (API_X - 80 + BACKEND_GAP * 2 + 220, R_TABLE + 40)]))

    # ---- groupings ----
    d.groups.append(Group("g_browser", "Browser path",
                          SPA_X - 40, R_EDGE - 40, 240, 320))
    d.groups.append(Group("g_api", "API runtime path",
                          AUTH_X - 40, R_EDGE - 40, API_X - AUTH_X + 280, 320))
    d.groups.append(Group("g_data", "Backend resources (shared)",
                          API_X - 120, R_RESOURCES - 40, BACKEND_GAP * 2 + 320, 320))
    d.groups.append(Group("g_ingest", "Ingest pipeline (phase 1)",
                          INGEST_X - 30, R_EDGE - 40, 280, 320))

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
    """Phase 3 — strict top-down. NLQ Lambda fans down into 4 stages."""
    W, H = 1800, 1300
    d = Diagram("04-nlq-runtime", "NLQ runtime path", W, H)

    # Centre column for the user → API GW → Lambda chain
    CENTRE = 800

    d.nodes.append(Node("user", "End user", CENTRE - 40, 60, 80, 80, actor()))
    d.nodes.append(Node("r53", "Route 53\napi.nlq.demos.apps.equal.expert",
                        CENTRE - 160, 220, 320, 80,
                        aws_resource("route_53", "#8C4FFF")))
    d.nodes.append(Node("apigw", "API Gateway v2\nPOST /nlq",
                        CENTRE - 140, 380, 280, 80,
                        aws_resource("api_gateway", "#FF4F8B")))

    # Auth path branches LEFT
    d.nodes.append(Node("auth", "Authoriser\nLambda",
                        CENTRE - 480, 540, 200, 80,
                        aws_resource("lambda", AWS_ORANGE)))
    d.nodes.append(Node("secrets", "Secrets\nManager",
                        CENTRE - 480, 700, 200, 80,
                        aws_resource("secrets_manager", "#DD344C")))

    # NLQ Lambda continues straight down
    d.nodes.append(Node("nlq", "NLQ Lambda\n(handler.py)",
                        CENTRE - 140, 540, 280, 80,
                        aws_resource("lambda", AWS_ORANGE)))

    # Four stages spread across the bottom
    STAGE_Y = 740
    LABEL_Y = 940
    SPACING = 360
    LEFT_X = CENTRE - SPACING * 1.5
    stages = [
        ("titan", "Titan v2\nembed question",
         LEFT_X + 0 * SPACING),
        ("s3v", "S3 Vectors\nquery_vectors",
         LEFT_X + 1 * SPACING),
        ("claude", "Claude Sonnet 4.6\n(global profile)",
         LEFT_X + 2 * SPACING),
        ("athena", "Athena\nINSERT INTO",
         LEFT_X + 3 * SPACING),
    ]
    stage_styles = [
        aws_resource("sagemaker", "#01A88D"),
        aws_resource("simple_storage_service", "#01A88D"),
        aws_resource("sagemaker", "#01A88D"),
        aws_resource("athena", "#8C4FFF"),
    ]
    for (nid, label, x), style in zip(stages, stage_styles):
        d.nodes.append(Node(nid, label, int(x), STAGE_Y, 200, 80, style))

    # Iceberg sink
    d.nodes.append(Node("iceberg", "Iceberg table\ncinq.operational",
                        int(LEFT_X + 3 * SPACING), 1000, 200, 80,
                        aws_resource("simple_storage_service", "#7AA116")))

    # ---- edges ----
    d.edges.append(Edge("e1", "user", "r53", exit=BOTTOM, entry=TOP))
    d.edges.append(Edge("e2", "r53", "apigw", exit=BOTTOM, entry=TOP))

    # API GW → Auth (down then left)
    d.edges.append(Edge("e3", "apigw", "auth", "1. authorise",
                        exit=BOTTOM, entry=TOP,
                        waypoints=[(CENTRE - 380, 500)]))
    d.edges.append(Edge("e4", "auth", "secrets", "GetSecret",
                        exit=BOTTOM, entry=TOP))

    # API GW → NLQ Lambda
    d.edges.append(Edge("e5", "apigw", "nlq", "2. invoke",
                        exit=BOTTOM, entry=TOP))

    # NLQ Lambda → 4 stages. Each edge leaves the NLQ Lambda at a
    # distinct exit-X position and uses a distinct horizontal bus Y,
    # so no two edges ever overlap.
    # NLQ Lambda is 280px wide; exits at 0.1, 0.37, 0.63, 0.9 of width.
    exit_xs = [0.1, 0.37, 0.63, 0.9]
    bus_ys = [660, 680, 700, 720]
    for i, ((nid, _, x), ex, by) in enumerate(zip(stages, exit_xs, bus_ys)):
        sx = int(x) + 100  # centre of stage shape
        exit_abs_x = int(CENTRE - 140 + 280 * ex)
        d.edges.append(Edge(
            f"s{i}", "nlq", nid, f"{i + 3}.",
            exit=(ex, 1.0), entry=TOP,
            waypoints=[(exit_abs_x, by), (sx, by)],
        ))

    # Athena → Iceberg
    d.edges.append(Edge("ei", "athena", "iceberg",
                        exit=BOTTOM, entry=TOP))

    # Groupings
    d.groups.append(Group("g_auth", "Authoriser",
                          int(CENTRE - 520), 520, 280, 280))
    d.groups.append(Group("g_stages", "RAG + SQL execution",
                          int(LEFT_X - 40), 720, SPACING * 4 + 40, 380))

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
