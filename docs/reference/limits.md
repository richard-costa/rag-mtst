# Formats and Limits

## Document Formats

| Format | Parser (default) | Explicit visual extraction |
| --- | --- | --- |
| TXT, `.md`, `.markdown` | UTF-8 text decoding | Not supported |
| PDF | Native AnyDoc text extraction; scans needing OCR are rejected | Poppler page rendering plus configured vision model |
| DOCX | Native AnyDoc; no Office service | unoserver conversion to PDF, then rendering/transcription |
| PPTX | Native AnyDoc; no Office service | unoserver conversion to PDF, then rendering/transcription |

Empty/nonsearchable documents are rejected. There is no URL acquisition,
automatic OCR, visual fallback, or provider fallback. Visual PPTX export includes
hidden slides and excludes notes pages to retain slide order. LibreOffice may
substitute fonts or change layout; pixel fidelity is not guaranteed.

Native parser output has no inferred page/slide provenance. Visual extraction
records ordered pages/slides and blanks. Known page numbers are one-based; chunk
indices are zero-based.

## Visual Extraction Bounds

These are internal processing limits, not a general HTTP upload policy or a
dollar ceiling. Provider/image input accounting can add costs beyond output tokens.

| Bound | Value |
| --- | --- |
| Original/converted PDF size | 20 MiB |
| Document pages | 50 |
| Requests in flight | One at a time per extraction |
| Maximum image dimension | 1600 pixels |
| Reserved output per request | 8192 tokens |
| Output budget per document | 65536 tokens |
| Model request timeout | 120 seconds |
| Poppler operation timeout | 60 seconds |
| Visual extraction deadline | 600 seconds |
| Office conversion timeout | 90 seconds |
| Adjacent-page context | 2000 characters; not page evidence |

Cancellation waits for Office conversion cleanup. Rendering, provider,
validation, timeout, or budget failures do not commit a partial document.

## Worker and Model Context

| Bound | Default / contract |
| --- | --- |
| Worker heartbeat | Every 5 seconds |
| Stale heartbeat | Failed after 60 seconds on a later worker poll; no automatic replay |
| Job execution | 15 minutes |
| Child shutdown grace | 5 seconds, then force-stop |
| Structural chunk target | 180 words; soft, not a token limit |
| Local embedding input | Selected tokenizer/model limit; oversized chunks are split losslessly |
| Answer input | 8000 locally estimated tokens by default; not exact provider accounting |
| Answer output | 4000 tokens by default, including reasoning |
| Answer timeout | 180 seconds by default; no automatic generation retries |
| Conversation generation history | At most 10 complete turns within one third of the prompt budget |
| Conversation history page | Default 50 messages; allowed 1 through 100 |

The answer input estimate uses `tiktoken`'s `cl100k_base` encoding and includes
system text, question, labels, JSON escaping, source text, history, response
schema, and a 64-token formatting reserve. Provider tokenizers and wire formats
can differ. A final source passage may be truncated. Model/server context must
fit the input and output allowances, including reasoning. See
[configuration](configuration.md) for internal settings and provider caveats.