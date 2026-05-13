# Conference Paper List

A personal browser for ML conference proceedings, focused on urban /
spatiotemporal / geospatial research directions. Each conference is a
single self-contained HTML file with offline search, filter, and tag
navigation — no server, no JS framework, no install.

## Usage

**Local (offline):**
```
git clone git@github.com:xxmy7/paper-list.git
cd paper-list
# Open index.html in any browser, or open browsers/*.html directly.
```

**Online (GitHub Pages):**
If Pages is enabled, the site is served at
`https://xxmy7.github.io/paper-list/`.

## What's inside

| Conference | Papers | Abstracts | Institutions | Multi-aff authors |
| ---------- | -----: | --------: | -----------: | ----------------: |
| ICML 2026  | 6 567  | ~99%      | 99.97%       | 4.8%              |
| KDD 2026   | 256    | 100%      | 100%         | 26.8%             |
| WWW 2026   | 954    | 90.8%     | 75.2%        | 7.5%              |

Coverage gaps are mostly tracks that ACM hasn't published yet — they'll
fill in closer to the conferences' final publication dates.

## Features

- **Per-conference tabs**: filter by track (Research / Industry / Short /
  Web4Good / Spotlight / etc.) and by official topic
- **Two-cycle support** (KDD): switch between February and July cycles
- **Tag navigation**: papers tagged by ML topic via Claude API
- **Full-text search** across titles, abstracts (when present), authors,
  and institutions; LaTeX math rendered with MathJax
- **Author institution superscripts**: single (`Name¹`) or multi-affiliation
  (`Name¹,³`) supported
- **Direct links**: per-paper ACM page, OpenReview / icml.cc page, DBLP record

## Data sources

- ICML — icml.cc miniconf API + OpenReview
- KDD — DBLP proceedings + the ACM v1 bundled PDF for abstracts + ins
- WWW — DBLP proceedings + ACM main proceedings PDF + Crossref / OpenAlex
  / Semantic Scholar fallbacks

All institution strings are author-declared (from OpenReview or ACM
camera-ready), preserved verbatim except for HTML entity decoding and
splitting of compound `&`-encoded strings.

## License

Personal-use research catalogue; the underlying paper metadata belongs to
the respective conference publishers (ACM / IMLS / IW3C2).
