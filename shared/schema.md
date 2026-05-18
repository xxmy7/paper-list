# Conference data schema

Each file in `conferences/<id>.json` follows this shape. The generic browser
template reads it and adapts the UI based on `fields_present`, `designations`,
`links`, etc.

```jsonc
{
  "id": "icml2026",            // unique short id; matches filename and browser HTML name
  "name": "ICML 2026",         // display name shown in header and switcher
  "venue": "ICML",             // venue acronym (used for sorting/grouping)
  "year": 2026,
  "source": "openreview",      // "openreview" | "dblp" | "manual" (informational)

  // Which short keys are present on the paper records. Drives UI show/hide:
  //   "a"  → enables "Search abstracts" checkbox and abstract toggle
  //   "au" → enables author rendering and the "Search authors/inst." checkbox
  //   "ins" → enables institution list rendering
  //   "g"  → enables keyword-tag dropdown (when keyword_field === "g")
  //   "o"  → enables official-topic dropdown (when topic_field === "o")
  // For DBLP-only conferences, fields_present is typically ["i","t","au","u","dblp"].
  "fields_present": ["i","t","d","u","v","a","g","o","au","ins"],

  // External links to render in each paper card. Each link is shown only when
  // the referenced field exists and is non-empty on that paper.
  // `url_template` uses `{field}` placeholders that resolve against the paper.
  "links": [
    { "label": "ICML page",  "field": "v", "url_template": "https://icml.cc{v}" },
    { "label": "OpenReview", "field": "u", "url_template": "{u}" }
  ],

  // Optional. Drives the top-of-page tabs (All / <tab1> / <tab2> / ...).
  // Set to null for conferences where you don't categorize papers.
  "designations": {
    "field": "d",                          // field on each paper that holds the designation key
    "tabs": [
      { "key": "spotlight", "label": "Spotlight",
        "badge_class": "spotlight", "badge_text": "SPOTLIGHT",
        "card_class": "spotlight-card" },
      { "key": "regular",   "label": "Regular",
        "badge_class": "regular",   "badge_text": "POSTER",
        "card_class": "" }
    ]
  },

  "topic_field":   "o",        // field that holds an "official topic" string (or null)
  "keyword_field": "g",        // field that holds an array of free-form tags (or null)

  "papers": [
    {
      "i":  64822,                                  // id (string or int)
      "t":  "Paper title",                          // required
      "d":  "regular",                              // designation key (see tabs above)
      "u":  "https://openreview.net/forum?id=...",  // primary paper URL
      "v":  "/virtual/2026/poster/64822",           // partial URL plugged into link templates
      "a":  "Abstract text...",                     // abstract
      "g":  ["Other", "Multimodal/VLM"],            // keyword tags
      "o":  "ML Theory->Optimization",              // official topic; "primary->sub" form is split into optgroups
      "au": [["Author Name", 0], ["Co-Author", 1]], // [name, institution_index] tuples (idx into "ins")
      "ins": ["Univ A", "Univ B"]                   // canonical institution names
    }
  ]
}
```

## DBLP-only conferences (KDD / WWW / ...)

DBLP HTML carries only titles, authors, and links — no abstracts or
decisions. A typical DBLP-derived record looks like:

```jsonc
{
  "i":  "conf/kdd/AhnSS26",
  "t":  "Enriching Semantic Profiles into Knowledge Graph...",
  "au": [["Seokho Ahn", null], ["Sungbok Shin", null], ["Young-Duk Seo", null]],
  "u":  "https://doi.org/10.1145/3770854.3780324",
  "dblp": "https://dblp.org/rec/conf/kdd/AhnSS26.html"
}
```

The institution slot is `null` because DBLP doesn't carry affiliations.
The browser hides the abstract / topic / keyword controls automatically.

## Adding a new field

1. Decide on a short key (e.g., `pdf` for a PDF URL).
2. Have your build script emit it on the paper records.
3. Add it to `fields_present`.
4. To surface it as a card link, add an entry to `links`:
   ```json
   { "label": "PDF", "field": "pdf", "url_template": "{pdf}" }
   ```
5. Re-run `scripts/build_browser.py --conf <id>`.

If you want a *filterable* dropdown for a new field, the browser template
would need a small addition. Until then, keep new fields cosmetic
(links / badges) rather than filterable.
