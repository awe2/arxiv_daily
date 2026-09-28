# arxiv_daily

Weekday arXiv paper recommendations based on my research interests, curated by
Claude and delivered by email.

Each weekday morning a Claude Code routine pulls the latest arXiv listings
across the astro-ph family (plus any extra categories flagged in my interest
file), filters them against that file, reads the full text of the survivors,
and writes a tiered digest with short summaries and key figures. The digest is
committed to the `claude/digests` branch, and a GitHub Action emails it to me.

Forked from Anning Gao's [arxiv_daily](https://github.com/anninggao/arxiv_daily).

## How it works

The routine follows [`instruction.md`](instruction.md):

1. Read the current month's interest file in [`interests/`](interests/)
   (falls back to the most recent earlier month).
2. First pass: pull metadata for all of astro-ph (plus flagged extras) and
   filter on title/abstract.
3. Second pass: fetch full LaTeX source for the candidates and re-filter.
4. Select papers into four tiers (highly relevant → adjacent → notable →
   meta-research) and extract a figure or two where it helps.
5. Write `YYYY-MM/YYYY-MM-DD.md` and push it to the `claude/digests` branch.
6. The push triggers [`.github/workflows/email-digest.yml`](.github/workflows/email-digest.yml),
   which emails the digest as HTML. Figures are attached, and each figure in
   the body links to its file on GitHub. (LaTeX math appears as raw `$...$`
   in the email.)

The fetcher [`arxiv_pull.py`](arxiv_pull.py) uses only the standard library,
so the routine needs no dependencies.

## Writing your interest file

Copy [`interests/TEMPLATE.md`](interests/TEMPLATE.md) to
`interests/YYYY.MM.md` (e.g. `interests/2026.10.md`) and fill it in. Commit
it to `main`. Until at least one `YYYY.MM.md` exists, the routine stops
without sending anything.

- The six astro-ph sub-categories are always pulled. The **Extras** line under
  "arXiv categories to monitor" adds more (e.g. `cs.LG`, `stat.ML`).
- Everything else steers filtering and tiering. Specific topics, methods,
  surveys, and authors work better than broad field names.
- Write a new monthly file only when your interests change. Older files keep
  applying until then.

## One-time setup

1. **Gmail app password.** On the Google account that will send the mail,
   turn on 2-Step Verification, then create an App Password
   (Google Account → Security → App passwords).
2. **Repo secrets.** In **Settings → Secrets and variables → Actions**, add:
   - `MAIL_USERNAME`: the sending Gmail address
   - `MAIL_PASSWORD`: the app password from step 1
   - `MAIL_TO`: where the digest should go (comma-separate multiple addresses)
3. **GitHub access for Claude.** The Claude GitHub App needs access to this
   repo with **Contents: write** so the routine can push to `claude/digests`.
4. **Routine.** A scheduled Claude Code routine on this repo, running
   Mon–Fri, with the prompt "Follow instruction.md in the repo root exactly."

To test the email without waiting for a run: **Actions → Email daily digest →
Run workflow** on the `claude/digests` branch. This re-sends the newest digest.

The email workflow runs from the `claude/digests` branch. If you change
`email-digest.yml` on `main`, merge `main` into `claude/digests` to pick it
up.

## Repository layout

| Path | What it is |
|------|-----------|
| `YYYY-MM/YYYY-MM-DD.md` | Daily digest files (on `claude/digests`) |
| `YYYY-MM/figures/{arxiv_id}/` | Figures referenced by the digests (`.pdf`, `.png`, …; never converted) |
| `interests/YYYY.MM.md` | Monthly interest files (maintained by hand) |
| `interests/TEMPLATE.md` | Blank interest-file template |
| `arxiv_pull.py` | arXiv metadata + full-text fetcher |
| `digest_template.md` | Canonical format for a daily digest |
| `instruction.md` | The routine Claude follows each run |
| `.github/workflows/email-digest.yml` | Emails each new digest |
