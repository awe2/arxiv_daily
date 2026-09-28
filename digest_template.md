# arXiv Digest — {YYYY-MM-DD}

<!--
TEMPLATE NOTES (delete this comment block in the real digest):
- Structural reference for the daily digest. Follow it literally for
  ordering, headings, and per-paper fields. Fill every {placeholder}.
- The header fields are a markdown bullet list, one field per bullet.
- Skip any tier section that has no papers — omit the heading entirely.
- Per-paper figures are OPTIONAL: 0-1 is normal, 2 is the hard cap.
  Only reference figures actually extracted to disk for this paper, and
  never extract a figure you won't reference (see Step 5/7). If a paper
  warrants no figure, just omit the figure line — say nothing about it.
- Every figure gets an italic caption paragraph directly below it (blank
  line in between). With two figures, each has its own caption.
- Authors: list the first 3, then "et al." if there are more. Add a
  parenthetical to flag interest-file high-value co-authors when useful.
- Link the title to abs_url from metadata.json — do not fabricate IDs.
- No relevance/"Why Tier N" paragraph: the summary is the whole entry.
-->

- **Interest file used:** interests/{YYYY.MM}.md {(current month) | (fallback — no {YYYY.MM}.md exists yet)}
- **Categories pulled:** {comma-separated list: the six astro-ph sub-categories plus any extras from the interest file}
- **Papers scanned:** {N} ({breakdown, e.g. 88 astro-ph new/cross + 305 from extras})
- **After first filter:** {M} candidates reviewed with full text
- **Final selected:** {P} papers across {K} tiers

---

## Tier 1 — Highly relevant

### [{Paper Title}]({abs_url})

{Author 1}, {Author 2}, {Author 3} et al. {(optional: high-value co-author note)}
**Primary category:** {primary_category} {| also: secondary_category}

{3-4 sentence summary of the actual contribution: what they did, how, and
the headline result. Draw on the full-text reading from the second pass.}

![](figures/{arxiv_id}/{filename})

*{1-2 sentence caption: what this figure shows and the takeaway it is meant to deliver.}*

---

## Tier 2 — Adjacent / useful context

### [{Paper Title}]({abs_url})

{Author 1}, {Author 2}, {Author 3} et al.
**Primary category:** {primary_category} {| also: secondary_category}

{3-4 sentence summary of the actual contribution.}

![](figures/{arxiv_id}/{filename})

*{1-2 sentence caption: what this figure shows and the takeaway it is meant to deliver.}*

---

## Tier 3 — Outside my area but notable

### [{Paper Title}]({abs_url})

{Author 1}, {Author 2}, {Author 3} et al.
**Primary category:** {primary_category} {| also: secondary_category}

{3-4 sentence summary of the actual contribution. Hold a high bar for this
tier — the result has to be genuinely groundbreaking or surprising.}

![](figures/{arxiv_id}/{filename})

*{1-2 sentence caption: what this figure shows and the takeaway it is meant to deliver.}*

---

## Tier 4 — Meta-research about the field

### [{Paper Title}]({abs_url})

{Author 1}, {Author 2}, {Author 3} et al.
**Primary category:** {primary_category}

{3-4 sentence summary of the actual contribution — AI's effect on astronomy,
training/hiring, methodology critiques, sociology of science, publication and
funding shifts.}
