You are running a daily arXiv recommendation routine in Anthropic's
cloud, against a clone of my arxiv-daily repo. Work in the cloned
repo's root; all paths below are relative to it unless absolute.

## CRITICAL: branch policy — read first

This routine uses ONE branch for everything: claude/digests

Do NOT create a new branch per run. Do NOT auto-generate a branch name.
Do NOT use a dated or random branch name. Every run commits to the
single persistent branch named exactly:

    claude/digests

The exact git commands to use are specified in Step 7. Follow them
literally. If you find yourself about to run `git checkout -b` with
any name other than `claude/digests`, stop — that is wrong.

## Environment

arxiv_pull.py uses only the Python standard library, so no installation
is needed. Invoke it as:

    python3 arxiv_pull.py [args]

## Files and directory layout

- arxiv_pull.py : my arXiv fetcher script (do not modify)
- instruction.md : instruction for Claude (do not modify)
- digest_template.md : the canonical format for the daily digest. Read
  it before writing the output in Step 6 and follow its structure
  literally. Do not modify it.
- interests/ : directory of interest files, named YYYY.MM.md
  (e.g., 2026.05.md). I maintain these manually — do not create,
  modify, or delete files in this directory. interests/TEMPLATE.md
  is a blank template, not an interest file — ignore it.
- YYYY-MM/ : monthly output directory at the repo root (e.g., 2026-05/).
  Contains the daily digest .md files and a figures/ subdirectory.
- YYYY-MM/figures/{arxiv_id}/ : extracted figures for each recommended
  paper, organized by arXiv ID
- .github/workflows/email-digest.yml : GitHub Actions workflow that
  emails the newest digest to me on every push to claude/digests.
  Repo infrastructure, NOT a routine output — do not modify or delete
  it.
- scratch/ : temporary working area for daily pulls. Everything in here
  is deleted at the end of each run.

The only persistent outputs of this routine are:
- the daily digest markdown files at YYYY-MM/YYYY-MM-DD.md
- the figures at YYYY-MM/figures/{arxiv_id}/...

Everything you CREATE beyond these gets cleaned up (scratch/ and any
temporary extraction directories). "Cleanup" means deleting your own
temporary working files only — never pre-existing repo files such as
.github/. Leave the email workflow untouched.

## How the fetcher works (read before running)

arxiv_pull.py is metadata-first. Useful flags:

- `--categories <cat1> <cat2> ...` : arXiv categories to search
- `--fields title authors abstract` : metadata fields in output JSON
- `--fields all` : every available metadata field
- `--fulltext tex` : also download .tar.gz LaTeX source for each paper
- `--fulltext none` : metadata only (default)
- `--ids <id1> <id2> ...` : fetch specific papers by arXiv ID; this mode
  ignores --days, --categories, --max-results
- `--out <dir>` : output directory (default ./arxiv_pull_<YYYY-MM-DD>)
- `--max-results N` : hard cap on number of papers
- `--page-size N` : results per API call

Output structure for any run:
  <out>/metadata.json           -- query info + paper list (selected fields)
  <out>/source/<id>.tar.gz      -- only when --fulltext tex was used

## Daily workflow

### Step 1: Read the current interest file

Determine the current month as YYYY.MM. Read interests/YYYY.MM.md.

If this month's file does not exist, fall back to the most recent
prior YYYY.MM.md in the interests/ directory and note the substitution
in the output summary. I maintain interest files manually, so a missing
file just means I haven't written one for this month yet — proceed
with the most recent prior file without complaint. Only files named
exactly YYYY.MM.md count; never use interests/TEMPLATE.md.

If there is no YYYY.MM.md file at all, stop: do not pull papers, do
not write a digest, do not commit or push. Print "No interest file
found — copy interests/TEMPLATE.md to interests/YYYY.MM.md and fill it
in" as the Step 8 summary and exit.

Parse the interest file to extract the arXiv categories I follow. The
interest file's categories section contains TWO groups:

  1. The full astro-ph family — I work in astronomy and want broad
     coverage across all astro-ph sub-categories, not just my
     specialty. These are:
       astro-ph.CO  (Cosmology and Nongalactic Astrophysics)
       astro-ph.EP  (Earth and Planetary Astrophysics)
       astro-ph.GA  (Astrophysics of Galaxies)
       astro-ph.HE  (High Energy Astrophysical Phenomena)
       astro-ph.IM  (Instrumentation and Methods for Astrophysics)
       astro-ph.SR  (Solar and Stellar Astrophysics)

  2. Additional non-astro-ph categories I've flagged in the interest
     file (e.g., cs.LG for ML-in-astronomy crossovers).
     The set varies depending on what I'm working on.

The first-pass pull (Step 2) uses the UNION of these two groups. The
tiered filtering in Step 4 — not the category list — is what narrows
the digest down to my actual specialty plus useful adjacent and
groundbreaking work.

### Step 2: First-pass pull (metadata only)

Create scratch/pass1/. Build the categories list by combining:
- all six astro-ph sub-categories (always), AND
- any additional categories listed in interests/YYYY.MM.md.

Run:

    python3 arxiv_pull.py \
        --categories astro-ph.CO astro-ph.EP astro-ph.GA astro-ph.HE \
                     astro-ph.IM astro-ph.SR <any extras from interest file> \
        --fields title authors abstract primary_category categories \
        --fulltext none \
        --out scratch/pass1 \
        --max-results 500

Note the higher --max-results: a one-day pull across all of astro-ph
plus extras typically returns several hundred papers, well above the
default cap. 500 is a reasonable ceiling; raise it if you ever see the
pull hit the cap.

If the total number of papers exceeds the arXiv API rate limit, fetch
multiple times to make sure you have all the papers. If the rate limit
problem persists, make sure that you AT LEAST have all the astro-ph
papers (typically <100).

Read scratch/pass1/metadata.json. For first-pass filtering:

- Read the FULL abstract for every paper. Do NOT truncate, summarize,
  or apply length cuts to abstracts. The full abstract is the cheapest
  reliable signal for filtering — truncation loses the result
  statement, which is usually at the end. Do NOT, however, fetch any
  additional information beyond title + authors + abstract +
  primary_category + categories. That is what scratch/pass1/metadata.json
  contains and it is sufficient.
- Filter against the interest file using these fields only.

Token-saving rule: do not re-fetch the same paper, do not load the
LaTeX source, and do not visit arxiv.org for any paper at this stage.
Full text is for the SECOND pass only (Step 3), after candidates are
selected.

The candidate count target is bigger because the input pool is larger:
aim for ~25-40 candidates for deeper review. Be generous — exclude
only papers clearly off-topic. The tiers below welcome breadth, and
an all-astro-ph pull is the right level of breadth for catching
cross-subfield surprises.

When filtering, remember that a paper's primary_category tells you
the author's framing, but the full categories list tells you where
it might also matter. A galaxies paper cross-listed to astro-ph.IM
is often interesting for methods reasons even if galaxies isn't my
focus.

If the pull genuinely returns zero papers, write a recommendation
file noting "no new papers in target categories", clean up scratch/,
commit and push per Step 7, and exit cleanly.

### Step 3: Second-pass pull (full text for survivors)

Create scratch/pass2/. Run:

    python3 arxiv_pull.py \
        --ids <id1> <id2> ... \
        --fields all \
        --fulltext tex \
        --out scratch/pass2

For each candidate:
- Extract the tarball into a temp directory (use `tar -xzf`).
- Find the main .tex file (the one with \documentclass and
  \begin{document}; prefer main.tex / ms.tex / paper.tex if multiple).
- Read the abstract, intro, method, results, and conclusion. Skim
  the rest.

If a paper's source isn't a tarball (some authors upload PDF only;
arxiv_pull.py saves these as .pdf or .bin), fall back to the PDF URL
in metadata.json. If unreadable entirely, drop it and note this.

### Step 4: Final filter with tiered selection

Re-filter using full-text understanding. The output should fall into
these tiers; papers within a tier are not ordered relative to each
other:

  Tier 1 — Highly relevant
    Direct hits on my main research focus per the interest file.

  Tier 2 — Adjacent / useful context
    Astronomy work outside my main focus that's still useful — methods
    I might borrow, related sub-fields, foundational results that
    affect how I interpret my own. Because the first-pass pulls all
    of astro-ph, expect this tier to surface inter-subfield work
    routinely; that's the point.

  Tier 3 — Outside my area but notable
    Off-topic (often non-astronomy or far astronomy sub-fields), but
    a genuinely groundbreaking or surprising result worth knowing
    about as a scientist. Hold a high bar here.

  Tier 4 — Meta-research about the field
    Papers about the practice of research itself in or near my field:
    how AI is changing astronomy, hiring/training of PhDs, replication
    or methodology critiques, sociology of science, publication
    patterns, funding shifts, etc.

Selection rules:
- Total papers per day: minimum 5, maximum 20.
- DO NOT pad to hit 5 with weak papers. If genuine quality only yields
  3, return 3 and say so in the summary — explicitly note that the
  minimum was relaxed because nothing else met the bar.
- DO NOT force coverage of every tier. If nothing in Tier 3 or Tier 4
  is interesting, omit those sections entirely. A digest of all Tier 1
  is fine. A digest that's only Tier 2 + Tier 4 is fine.
- Quality over quantity always wins. Be honest and direct — your job
  is to save me time, not to fill a quota.

This step produces the FINAL paper list for the digest. Step 5 (figure
extraction) operates only on this final list — not on the broader
candidate pool from Step 3.

### Step 5: Extract figures (only for papers in the final digest)

CRITICAL ORDERING: Step 4 already produced the final list of papers
that will appear in the digest. Figures are extracted ONLY for papers
on that final list, and ONLY if they will actually be referenced in
the markdown. No speculative extraction.

For each paper that WILL appear in the digest (and only those):

1. Decide first whether you want to include a figure for this paper
   at all. A figure is worth including only if it materially helps
   me understand the paper at a glance (a key result plot, an
   architecture diagram, a central concept illustration). If a paper
   is fully understandable from the text summary alone, include zero
   figures. Most papers should have 0-1 figures; 2 is the cap, not
   the target.

2. If you decide a figure is warranted, identify the specific figure
   from the LaTeX source. Look for \includegraphics references in
   Methods, Results, or central concept sections. Avoid title-page
   logos, decorative figures, and appendix-only figures.

3. ONLY THEN copy the figure file to YYYY-MM/figures/{arxiv_id}/.
   Copy as-is — figures may be .pdf, .png, .jpg, or .eps; do not
   convert.

4. Immediately record the markdown reference you will use for this
   figure (e.g., ![](figures/2605.23114/figure_results.png)), together
   with a note on what the figure is meant to show, taken from its
   \caption{} and the text that discusses it while the source is still
   open. You will turn this into the figure's caption in Step 6.

Forbidden patterns:
- Do NOT extract figures for papers that did not make the final cut
  in Step 4.
- Do NOT extract figures "just in case" you might use them later.
- Do NOT extract a figure and then decide not to reference it in
  the markdown. If you extracted it, it must appear in the digest.
- Do NOT leave orphaned figure files in YYYY-MM/figures/{arxiv_id}/
  that aren't referenced from the markdown.

Verification before moving to Step 6:
- List every file under YYYY-MM/figures/ that you created in this
  run. For each one, confirm it corresponds to a paper in the final
  selection AND will be referenced in the markdown you're about to
  write. Delete any that don't satisfy both conditions.

### Step 6: Write the recommendation file

Create YYYY-MM/YYYY-MM-DD.md (e.g., 2026-05/2026-05-25.md).

Read digest_template.md first and follow it EXACTLY — it is the
canonical format. Match its title line, header lines, tier headings,
and per-paper layout verbatim, substituting real values for every
{placeholder} and deleting the template's guidance comments. The notes
below summarize what the template requires; if anything here seems to
conflict with the template, the template wins.

Header section — `# arXiv Digest — YYYY-MM-DD`, then a markdown
bullet list (one `- **Field:** value` per line, per the template):
- Interest file used (note if it was a fallback from a prior month)
- Categories pulled
- Papers scanned (with the astro-ph vs. extras breakdown)
- After first filter (candidates reviewed with full text)
- Final selected (papers across N tiers)

Do not add a `*Note: ...*` caveat line or any other prose to the header.
Caveats about the run belong in the Step 8 stdout summary, not in the
digest file.

Body: one section per tier that has any papers, in this order:
- ## Tier 1 — Highly relevant
- ## Tier 2 — Adjacent / useful context
- ## Tier 3 — Outside my area but notable
- ## Tier 4 — Meta-research about the field

Skip a tier's section entirely if it has no papers.

For each paper (exactly the template's shape):
- ### Title (with arXiv link via abs_url from metadata.json)
- Authors (first 3, then "et al." if more); optionally flag an
  interest-file high-value co-author in a parenthetical
- `**Primary category:** <primary_category>` line, with `| also: <cat>`
  if there is a relevant cross-listing
- 3-4 sentence summary of the actual contribution. This is the whole
  entry: do NOT add a relevance paragraph, a "Why Tier N" line, or any
  other note on why the paper was selected — the tier already says it.
  Work anything essential about the connection into the summary itself.
- Within that summary, **bold** the few words that carry the paper, so
  I can get the gist by skimming only the bold text. Good targets:
  - the physical quantity or parameter the paper measures or
    constrains (e.g. **the IGM temperature at mean density T₀**)
  - the headline number, with its uncertainty or significance
    (e.g. **σ₈ = 0.79 ± 0.02**, **a 3.2σ detection**)
  - a short phrase naming the technical path (e.g. **simulation-based
    inference with a neural density estimator on the 1D flux power**)
  - occasionally, the single sentence stating the main conclusion
  Bold words that are already in the summary: do not add a new
  sentence, paragraph, or label (no "**Key result:**") just to hold the
  emphasis. Keep it sparing, about 2-4 bold spans per paper; if half
  the summary is bold, nothing stands out. Put the `**` outside any
  `$...$` math, never inside it (write **$T_0 = 10^4$ K**, not
  $**T_0**$).
- Inline references to extracted figures using relative paths:
  ![](figures/{arxiv_id}/<filename>)
- Directly below each figure (blank line in between), a brief italic
  caption, 1-2 sentences: `*<caption>*`. Say what the figure is meant to
  tell the reader, not just what is plotted. "Recovered T₀ tracks the
  input across z = 2-4, with bias under 2%" is useful; "T₀ versus
  redshift" is not. Name the axes or panels only where that is needed to
  read the takeaway. Base the caption on the paper's own \caption{} and
  the text discussing the figure, and don't describe features you
  haven't verified there. With two figures, each gets its own caption.
- If a paper warrants no figure, simply omit the figure line. Never add
  a note explaining that no figure was extracted.

### Step 7: Clean up, audit, then commit and push to claude/digests

First, delete the entire scratch/ directory and any temporary
extraction directories you created during Step 3. Cleanup removes ONLY
the temporary files you created this run — leave every pre-existing repo
file in place, including the workflow under .github/. After cleanup, the only NEW files from this run should be the
digest markdown and figures under YYYY-MM/.

Do NOT touch the interests/ directory under any circumstances. I
maintain those files manually.

Verify the cleanup with `ls scratch/` returning nothing.

Then run a figure audit before staging anything:

1. Grep the digest markdown for figure references:
       grep -oE 'figures/[^)]+' YYYY-MM/YYYY-MM-DD.md
2. List all figure files actually on disk under this month:
       find YYYY-MM/figures -type f
3. Every file in (2) must appear in (1). If a file is on disk but
   NOT referenced in the markdown, DELETE it before staging:
       rm <unreferenced-file>
4. Every reference in (1) must point to a file in (2). If a
   reference points to a missing file, fix the markdown (either
   remove the reference or restore the figure).

Only after this audit passes, run the git commands below.

Now commit and push. Use the SINGLE persistent branch claude/digests.
Run these commands EXACTLY, substituting the real date only in the
commit message:

    # Fetch the persistent branch if it already exists on the remote
    git fetch origin claude/digests 2>/dev/null || true

    # Check out claude/digests: track the remote version if it exists,
    # otherwise create it fresh from the current HEAD
    if git rev-parse --verify origin/claude/digests >/dev/null 2>&1; then
        git checkout -B claude/digests origin/claude/digests
    else
        git checkout -B claude/digests
    fi

    # Stage only the digest outputs (never scratch, never interests)
    git add YYYY-MM/*.md
    git add YYYY-MM/figures/

    # Commit and push to the same branch every time
    git commit -m "Daily digest <YYYY-MM-DD>"
    git push origin claude/digests

Rules for this step:
- The branch is ALWAYS claude/digests. Never any other name.
- Do NOT open a pull request. Commits accumulate on claude/digests and
  I review them there directly.
- If the push fails with a 403, the GitHub App lacks Contents: write
  permission — report this clearly in the summary and stop. Do not
  attempt to work around it by creating a differently-named branch.
- If the push fails because the remote branch advanced (non-fast-
  forward), run `git fetch origin claude/digests` then
  `git rebase origin/claude/digests` and push again. Do not force-push.
- The push to claude/digests automatically triggers the email workflow
  (.github/workflows/email-digest.yml), which emails the newest digest
  to me. No extra action is needed. Do not try to send email yourself.

### Step 8: Print a summary to stdout

- Branch pushed to (should always be claude/digests)
- Counts at each filter stage and tier breakdown
- Path to the recommendation file
- Interest file used, and whether it was a fallback from a prior month
- Number of figures extracted and number referenced (should be equal)
- Any errors, skipped papers, or quota deviations

## General guidelines

- The commit branch is ALWAYS claude/digests. This is not negotiable
  and overrides any instinct to create per-run branches.
- Quality over quantity, always. 10 honest picks beats 20 padded ones.
- Be direct in summaries. No hedging, no marketing language.
- Do not hallucinate paper IDs, authors, or summaries. metadata.json
  is the source of truth for what was actually fetched.
- Treat the interest file as authoritative for what I want; treat
  fetched papers as the input you're filtering with it.
- For tarball extraction use `tar -xzf`. If a "tarball" is actually a
  single gzipped file, use `gunzip` instead.
- The interests/ directory is read-only for this routine. Never create,
  edit, or delete files there.
- Figures are extracted ONLY for papers in the final digest, and ONLY
  if they will be referenced in the markdown. Extracted-but-unused
  figures are a bug. The audit in Step 7 enforces this — but the goal
  is to never extract unused figures in the first place, not to clean
  them up at the end.
- First-pass filtering uses the FULL abstract — never truncate. But
  do not fetch any additional context (full text, web pages) until
  candidates are selected for the second pass.
