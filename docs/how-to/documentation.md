# Maintain the Documentation

Edit English Markdown files under `docs/`. Navigation lives in `mkdocs.yml`.
The root README is a short project entry point; detailed material belongs here.

## Place Content by Reader Need

| Type | Purpose | Write as |
| --- | --- | --- |
| Tutorial | Learn a skill with a predictable result | One guided exercise, with prerequisites, observations, and safe cleanup |
| How-to guide | Complete a specific task | Direct steps, assumptions, and relevant alternatives |
| Reference | Look up an exact contract | Settings, fields, commands, defaults, limits, and errors |
| Explanation | Understand behavior and tradeoffs | Design rationale, relationships, and boundaries |

Follow the [Diataxis map](https://diataxis.fr/map/). Link to the other kinds of
content rather than repeating them. Check examples against current source and
use synthetic data; never include real credentials or private documents.

## Preview and Build

Install Python 3.14+ and [uv](run.md#install-uv) first. A documentation preview
does not need Docker, a database, or model credentials.

```bash
uv sync --locked --group docs
uv run --group docs mkdocs serve --dev-addr 127.0.0.1:8002
```

Use another port if occupied. For publication verification:

```bash
uv run --group docs mkdocs build --strict
```

MkDocs validates navigation, local links, and anchors. It writes disposable HTML
to the ignored `site/` directory. The docs require only MkDocs and its Material
theme: no application imports, database, model calls, translation service, hooks,
custom scripts, Node packages, or diagram export step.

Use standard Markdown headings, lists, tables, links, and fenced code blocks.
The running API's `/docs` and `/openapi.json` provide exact machine-generated
HTTP schemas; do not copy generated schema dumps into the site.

## Maintain Diagrams

Keep Mermaid source in fenced `mermaid` blocks beside the behavior it explains.
The `pymdownx.superfences` configuration in `mkdocs.yml` enables Material's
built-in renderer. No image exports or separate diagram toolchain are needed.

Set the diagram type's `useMaxWidth: false` in its Mermaid front matter, as in
the explanation pages. The shared diagram stylesheet then allows horizontal
scrolling on narrow screens instead of shrinking labels to an unreadable size.

Use flowcharts for data paths and decisions, state diagrams for durable job
statuses, and sequence diagrams when transaction or request ordering matters.
Keep labels short and explain failure boundaries in the surrounding prose so
the page remains useful without a rendered diagram.

Material loads Mermaid from a CDN in the reader's browser, so diagram rendering
requires network access. A strict build validates navigation and Markdown, but
does not execute Mermaid. Preview changed diagrams in the browser to check for
syntax errors, readable labels, and usable narrow-screen layouts.

Verify changed documentation when a documentation pass is requested. A code-only
change does not require a site build or automatic documentation rewrite.