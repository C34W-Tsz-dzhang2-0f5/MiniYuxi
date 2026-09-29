# Issue tracker: Local Markdown

Issues and specs for this repo live as markdown files in `.scratch/`.

## Conventions

- One feature per directory: `.scratch/<feature-slug>/`
- The spec is `.scratch/<feature-slug>/spec.md`
- Implementation issues are one file per ticket at `.scratch/<feature-slug>/issues/<NN>-<slug>.md`, numbered from `01`, never a single combined tickets file
- Status is recorded as a `Status:` line near the top of each issue file. **Note:** the `triage` skill is **not installed** in this repo, so the five canonical triage roles (`needs-triage` / `needs-info` / `ready-for-agent` / `ready-for-human` / `wontfix`) are **not used** here. Use simple states instead: `open` / `claimed` / `done`.
- Comments and conversation history append to the bottom of the file under a `## Comments` heading

## When a skill says "publish to the issue tracker"

Create a new file under `.scratch/<feature-slug>/` (creating the directory if needed).

## When a skill says "fetch the relevant ticket"

Read the file at the referenced path. The user will normally pass the path or the issue number directly.

## Mapping for engineering skills

- `to-spec`: writes `.scratch/<feature-slug>/spec.md`
- `to-tickets`: writes `.scratch/<feature-slug>/issues/NN-<slug>.md` (one per tracer-bullet vertical slice, with a `Blocked by:` line for dependency edges)
- `wayfinder`: not installed; if adopted later, the map lives at `.scratch/<effort>/map.md`

## Notes

This repo's `origin` is a `ghfast.top` proxy to `github.com/C34W-Tsz-dzhang2-0f5/MiniYuxi` and local `main` is currently unpushed (`origin/main [gone]`), so a local-markdown tracker is the reliable choice. To switch to GitHub Issues later, re-run `setup-matt-pocock-skills` and update this file.
