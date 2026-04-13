import { type ReactNode } from "react";

/**
 * "How it works" — a documented walk-through of the Query view, with
 * cropped screenshots of every component. The screenshots are captured
 * by scripts/capture_anatomy.py against the live deployed SPA, so they
 * always match the current UI.
 */

const ANATOMY_BASE = "/docs/anatomy";

interface SectionProps {
  number: string;
  title: string;
  image: string;
  alt: string;
  children: ReactNode;
}

function Section({ number, title, image, alt, children }: SectionProps) {
  return (
    <section className="space-y-5">
      <div>
        <div className="text-[14px] uppercase tracking-wider font-bold text-[var(--color-text-secondary)]">
          Step {number}
        </div>
        <h2 className="gds-m mt-1 mb-0">{title}</h2>
      </div>
      <figure className="m-0">
        <img
          src={image}
          alt={alt}
          loading="lazy"
          className="w-full max-w-full h-auto border border-[var(--color-border)] bg-white"
        />
      </figure>
      <div className="space-y-4 text-[19px] leading-[1.47] text-[var(--color-text)]">
        {children}
      </div>
    </section>
  );
}

export function HowItWorksView() {
  return (
    <div className="max-w-[1100px] mx-auto px-4 md:px-8 py-16 space-y-16">
      {/* ---- intro ---- */}
      <div>
        <h1 className="gds-l mb-4">How it works</h1>
        <p className="text-[19px] leading-[1.47] text-[var(--color-text-secondary)] mb-0">
          A guided walk-through of the Query view. Every screenshot below was
          captured automatically against the live demo, so what you see here
          is exactly what you get when you load the page. The worked example
          is the Level&nbsp;3{" "}
          <strong className="font-bold text-[var(--color-text)]">
            Instance&nbsp;↔&nbsp;Volume
          </strong>{" "}
          quick-start, which shows off the cross-resource join pattern end to
          end.
        </p>
      </div>

      {/* ---- 1. header ---- */}
      <Section
        number="01"
        title="The page header"
        image={`${ANATOMY_BASE}/01-header.png`}
        alt="Black GOV.UK Design System header bar with a white DEMO chip, the words 'AWS Config NLQ', and an API key button on the right"
      >
        <p>
          A standard GOV.UK Design System header — black bar, blue
          underline, brand mark on the left. The top-right control opens a
          small dialog where you enter the API key the service needs before
          it&apos;ll run a query for you. There&apos;s nothing else to
          configure.
        </p>
      </Section>

      {/* ---- 2. question form ---- */}
      <Section
        number="02"
        title="Asking a question"
        image={`${ANATOMY_BASE}/03-question-form.png`}
        alt="A 'Your question' textarea with a placeholder example and an 'Ask the question' button"
      >
        <p>
          Type your question in plain English. There&apos;s no schema you
          have to learn first; the retrieval layer figures out which
          AWS&nbsp;Config resource type schemas are relevant from the
          question text alone, and passes those into the model as context.
          The placeholder shows a representative cross-resource join so you
          can see what level of complexity is supported.
        </p>
        <p>
          The textarea has the standard GOV.UK 2&nbsp;px black border with
          the unmistakable yellow focus state. <kbd>⌘</kbd>+<kbd>Enter</kbd>{" "}
          submits without a click. If no API key is set, the message{" "}
          <em>API key required</em> appears next to the keyboard hint and the
          API key modal opens on submit instead of firing the request.
        </p>
      </Section>

      {/* ---- 3. quick start tabs ---- */}
      <Section
        number="03"
        title="The quick-start library"
        image={`${ANATOMY_BASE}/04-quick-start-tabs.png`}
        alt="A tab strip with four tabs: 1 Basics, 2 JSON fields, 3 Cross-resource joins, 4 Advanced"
      >
        <p>
          The quick-start tabs are organised by{" "}
          <strong className="font-bold">complexity level</strong> rather than
          by topic. They run from one — a trivial single-table histogram —
          up to four, which is a four-way orphan-detection pivot. The numbered
          chip in each tab is the level marker; the active tab is filled
          blue.
        </p>
        <p>
          The grouping deliberately shows the range of what the system can
          do. A demo visitor walking left-to-right through the tabs sees the
          underlying engine getting progressively more impressive without
          needing to read any docs.
        </p>
      </Section>

      {/* ---- 4. example item ---- */}
      <Section
        number="04"
        title="A quick-start example"
        image={`${ANATOMY_BASE}/05-example-item.png`}
        alt="An example item showing the title 'Instance ↔ Volume', a one-line description and the literal natural-language question in italics"
      >
        <p>
          Each example is a short link-style block — a bold blue title (with
          the standard GOV.UK underline), a one-sentence description of what
          the example shows off, and the literal question that gets sent so
          you can see the input before you click.
        </p>
        <p>
          Clicking an example pastes its question straight into the textarea
          and immediately fires the API. There&apos;s no second click — by
          design, the friction between curiosity and result should be as low
          as possible.
        </p>
      </Section>

      {/* ---- 5. progress running ---- */}
      <Section
        number="05"
        title="Stage-by-stage progress"
        image={`${ANATOMY_BASE}/06-progress-running.png`}
        alt="A 'Running query' panel showing four stages: Embed question (complete), Retrieve schemas (complete), Generate SQL (in progress with a partial bar), Run Athena query (queued)"
      >
        <p>
          While the request is in flight the SPA shows a live progress
          panel. The four stages map directly to the steps the backend
          actually runs:
        </p>
        <ol className="list-decimal pl-6 space-y-1">
          <li>
            <strong className="font-bold">Embed question</strong> — Titan
            Text Embeddings v2 turns your question into a 1024-dimension
            vector
          </li>
          <li>
            <strong className="font-bold">Retrieve schemas</strong> — top-K
            most-similar resource types from the S3 Vectors index
          </li>
          <li>
            <strong className="font-bold">Generate SQL</strong> — Claude
            Sonnet writes a single Athena <code>SELECT</code> using the
            retrieved schemas as context
          </li>
          <li>
            <strong className="font-bold">Run Athena query</strong> —
            execute the SELECT against the Iceberg table and fetch rows
          </li>
        </ol>
        <p>
          Each row has its own progress bar, an active state, and a
          per-stage timing slot. The big <em>Total</em> figure on the right
          counts up in real time. Because the underlying API doesn&apos;t
          stream progress events, the timeline is animated against the
          observed median latencies and replaced with the real numbers the
          moment the response lands.
        </p>
      </Section>

      {/* ---- 6. progress complete ---- */}
      <Section
        number="06"
        title="The completed timings"
        image={`${ANATOMY_BASE}/07-progress-complete.png`}
        alt="The same progress panel after completion, every stage with a green check and a real elapsed time, the Total in the top-right showing the wall-clock"
      >
        <p>
          When the response comes back, every stage flips to green with its
          real elapsed time, and the heading changes from{" "}
          <em>Running query</em> to <em>Query complete</em>. The four
          numbers tell you exactly where the wall-clock went —{" "}
          <em>Generate SQL</em> is almost always the longest stage because
          it&apos;s the one waiting on a foundation model.
        </p>
        <p>
          On a failure, the active stage turns red and the heading flips to{" "}
          <em>Query failed</em>. No screenshot here because the demo is
          well-behaved most of the time.
        </p>
      </Section>

      {/* ---- 7. generated SQL ---- */}
      <Section
        number="07"
        title="The generated SQL"
        image={`${ANATOMY_BASE}/08-generated-sql.png`}
        alt="A code block showing a WITH-CTE Athena SQL query joining instances and volumes via json_extract_scalar"
      >
        <p>
          Claude returns a single fenced <code>SELECT</code>. The SPA
          extracts it from the response, validates that it&apos;s
          SELECT-only (no DDL or DML keywords allowed) and renders it in a
          GOV.UK <em>inset text</em> block — grey background, blue left
          border, monospace.
        </p>
        <p>
          For the showcase example you can see the cross-resource pattern in
          full: two CTEs (<code>instances</code> and <code>volumes</code>)
          one per resource type, each filtered by{" "}
          <code>resource_type = &apos;…&apos;</code>, joined on{" "}
          <code>attachments[0].instanceId</code> dug out of the volume&apos;s
          opaque <code>configuration</code> JSON. This is the canonical
          shape every cross-resource join generates — Claude doesn&apos;t
          need to be prompted for it, it falls out of the system prompt
          plus the retrieved schemas.
        </p>
      </Section>

      {/* ---- 8. retrieved schemas ---- */}
      <Section
        number="08"
        title="The retrieved schemas"
        image={`${ANATOMY_BASE}/09-retrieved-schemas.png`}
        alt="A list of five AWS Config resource types with their service, category, field count and similarity distance"
      >
        <p>
          These are the five resource type schemas the vector retriever
          picked from the S3 Vectors index for this question. Each row shows
          the resource type, its service group, its category, the number of
          AWS Config fields it has, and the cosine distance from the
          question vector — lower is closer.
        </p>
        <p>
          Both of the resource types the join needs (
          <code>AWS::EC2::Instance</code> and{" "}
          <code>AWS::EC2::Volume</code>) are present in the top five, which
          is what makes the join work — the model sees both schemas in its
          context and can cross-reference field paths between them. If a
          required schema misses the cut-off, the generated SQL becomes
          guesswork; bumping{" "}
          <code className="font-mono">top_k</code> in the request body is
          the workaround.
        </p>
      </Section>

      {/* ---- 9. results ---- */}
      <Section
        number="09"
        title="The results table"
        image={`${ANATOMY_BASE}/10-results-table.png`}
        alt="A wide tabular result with one row per attached EC2 volume — instance ID, name, type, volume ID, size, encryption status"
      >
        <p>
          The actual rows from Athena. The table is rendered straight from
          the columns the SQL projected, no schema tweaking, in a plain
          GOV.UK table — left-aligned, single grey border under the
          headings, monospace cell content for stable column widths.
        </p>
        <p>
          Above the table you&apos;ll see the row count from the API
          response. The first 100 rows are returned by default; the{" "}
          <code>top_k</code> field on the request body controls retrieval
          breadth, but result-row capping is enforced server-side at the
          system-prompt level.
        </p>
      </Section>
    </div>
  );
}
