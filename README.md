# Conference Paper List

A browser for ML conference proceedings. Each conference is a single
self-contained HTML file with offline search, filter, and tag navigation
— no server, no JS framework, no install.

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

| Conference | Papers | Abstracts | Institutions | Tags | Tracks |
| ---------- | -----: | --------: | -----------: | ---: | ------ |
| AAAI 2026  | 4 955  | 98.4%     | 79.2%        | 76%  | 6 tabs (Main / Alignment / Social Impact / Journal / Demo / Senior) |
| CVPR 2026  | 4 069  | —         | —            | 100% | Spotlight / Regular |
| ICLR 2026  | 5 424  | ~99%      | ~99%         | 100% | Spotlight / Regular |
| ICML 2026  | 6 567  | ~99%      | 99.97%       | 100% | Spotlight / Regular |
| KDD 2026   | 256    | 100%      | 100%         | 100% | Jul / Feb cycle × Research / ADS |
| WWW 2026   | 954    | 90.8%     | 75.2%        | 100% | Research / Industry / Short / Web4Good |

Coverage gaps are mostly venues that haven't finished ACM/OJS ingestion
yet — they'll fill in closer to the conferences' final publication dates.

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
- **Favorites + Folders**: star papers across conferences, organize into
  named folders, filter by folder, export per-folder paper lists

### Favorites & Folders

Star any paper (click ★) to add it to your favorites. Right-click ★ to
assign the paper to one or more folders (e.g. "Thesis", "Baselines",
"Urban-ST").

| Action | How |
| ------ | --- |
| Create folder | Click `⚙ Folders` → type name → Add |
| Assign to folder | Right-click ★ on a card → pick folders |
| Filter by folder | Enable "★ Favorites only" → select folder from dropdown |
| Export one folder | `⚙ Folders` → "Export current folder" (downloads .md) |
| Export all folders | `⚙ Folders` → "Export all folders" |
| Rename / delete | `⚙ Folders` → ✎ / ✕ buttons |

All folder data lives in the browser's localStorage — no server required.
To sync across machines, use "★ Export" (downloads `favorites.js` which
includes folder assignments) and commit it to the repo.

> **When is `serve.py` needed?**
> Only for the "⤓ Save" button, which writes `favorites.js` directly to
> disk via a local POST endpoint. Everything else (folders, filtering,
> export downloads) works on GitHub Pages or `file://` with no server.

## Adding a new conference

### Project structure

```
conferences/<conf>.json   # Processed paper data (schema: shared/schema.md)
conferences/index.json    # Conference picker for index.html
shared/keyword_patterns.json  # 40 tag categories with regex patterns
templates/browser.html.tmpl   # Universal browser template (~1500 lines)
browsers/<conf>.html      # Generated self-contained HTML (what users see)
```

### Step-by-step

1. **Get paper data** into `conferences/<conf>.json` following the schema in
   `shared/schema.md`. Minimum fields: `i` (id), `t` (title), `u` (url).
   Sources: DBLP API, OpenReview API, miniconf, ACM proceedings PDF.

2. **Enrich** (optional but recommended):
   ```bash
   python scripts/fetch_abstracts.py     --conf <conf>   # OpenAlex + Semantic Scholar
   python scripts/fetch_authors_inst.py  --conf <conf>   # OpenAlex authorships
   ```

3. **Tag** papers by topic:
   ```bash
   # Option A: regex (free, instant, ~76% coverage)
   # Uses shared/keyword_patterns.json patterns on title + abstract
   # Option B: Claude API (better accuracy, requires ANTHROPIC_API_KEY)
   python scripts/tag_keywords_llm.py --conf <conf>
   ```

4. **Build** the browser:
   ```bash
   python scripts/build_index.py                   # update conferences/index.json
   python scripts/build_browser.py --conf <conf>   # generate browsers/<conf>.html
   ```

5. **Commit & push**:
   ```bash
   git add browsers/<conf>.html conferences/index.json
   git push
   ```

### Paper JSON schema (short keys for compactness)

| Key  | Meaning |
| ---- | ------- |
| `i`  | Paper ID |
| `t`  | Title |
| `a`  | Abstract |
| `u`  | Primary URL (DOI or OpenReview) |
| `au` | Authors — `[[name, inst_index], ...]` |
| `ins`| Institutions — `[name, ...]` (1-based via `au[i][1]`) |
| `g`  | Keyword tags (array of strings) |
| `o`  | Official topic / track name |
| `d`  | Designation key (for tab filtering) |
| `c`  | Cycle key (for multi-round venues like KDD) |

See `shared/schema.md` for the full specification.

## Data sources

- AAAI — DBLP API (4955 papers) + OpenAlex/Semantic Scholar abstracts +
  OJS article metadata for track classification
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
