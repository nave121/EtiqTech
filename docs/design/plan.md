# Design task — make EtiqTech self-explanatory for non-technical people

**Status: plan for Razy's review (rule: plan before doing). Scheduled near the end of the sprint,
after the eval gate. Nothing below is built yet.**

## Who has to understand it without help

1. **The researcher** (primary user, brief §1): uploads a draft, reads findings, fixes the
   protocol, re-runs. Often not a native English speaker; works in the bilingual Council form.
2. **Committee staff / coordinators**: receive submissions "that passed EtiqTech"; need to know
   what that does and does not mean (the advisory framing exists for them).
3. **An institution evaluating adoption** (IT/compliance, not developers): needs to see in one
   page what the tool is, where data goes, and how to run it.

## What is developer-flavoured today (observed in the templates)

- Landing page copy is a terminal: `$ ethictech lint protocol.json`, `ethictech analyze`,
  "AI-Powered IACUC Review Tool". A researcher does not run commands.
- The app's first screen asks for a "Council HTML export" and offers "LLM Provider" / "Model"
  selects with model tags like `qwen3.5:35b`. A researcher needs "How do I get the file?" and
  should never have to pick a model.
- Findings are rule-id-first (`euthanasia:secondary-method`) with a message written for people
  who know the vocabulary; the "suggested fix" is good but buried behind a click.
- Status words are internal: "Layer 2", "Layer 3", "Human Eye", "reconcile", "theme".
- The report is a PDF export with rule ids and theme names; no plain-language summary on top.
- Everything is English-only UI (P4 i18n not done); the protocols are Hebrew/English.

## Proposed changes, smallest first (each is one commit + review)

1. **Plain-language first screen.** Replace the terminal-styled landing hero with three
   sentences and one button; a "Where do I get the file?" expander with the exact Council-system
   steps (maintainer to confirm the steps). Hide provider/model selects behind an "Advanced"
   toggle; default to the server's configured model.
2. **Findings in three lines.** Every finding renders as *what is wrong* → *why it matters
   (one line, with the guidance citation when grounded)* → *what to change*. Rule id and theme
   move to a small secondary line (still there for committees).
3. **Progress in human terms.** "Checking the form (instant)" → "Reading the protocol like a
   reviewer (a few minutes)" → "Second, deeper read (only when needed)" instead of Layer 1/2/3.
4. **One-page summary at the top of the report**: how many blocking issues, how many
   suggestions, the three most important fixes, and the advisory sentence. Print first.
5. **Hebrew/English UI toggle** (P4 i18n): extract strings to a dictionary, RTL preserved
   (the report body already is RTL). This is the largest item; it may not fit this sprint.
6. **A one-page `docs/START-HERE.md`** for the adopting institution: what it is, where data goes
   (links PRIVACY.md), what it costs to run (a laptop with Ollama or one GPU box), how to try it
   in linter-only mode in five minutes.

## What I will not do without a decision

- Change the wording of findings themselves (they are the linter's messages, tuned against the
  golden set) — I will add the plain-language framing *around* them.
- Remove rule ids or theme names from the UI (committees and the feedback loop need them).
- Touch the advisory wording (maintainer's, decision #2).

## Acceptance

A first-time researcher, given only the URL, uploads a protocol and can say what to fix first
without asking anyone. Test: five-minute walk-through script in `docs/START-HERE.md` followed
literally on a linter-only instance.
