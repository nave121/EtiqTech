# EtiqTech UI spec: plain words, one fix list, same screens

Status: implementation spec, synthesised from three scored designs and nine judge reviews
(2026-09-05). Supersedes the proposal list in `plan.md`. Every number below was re-run against
the repo on the day of writing; where a judge showed a design contradicting itself or a
constraint, that idea is dropped and named in section 7.

Facts this spec is built on (verified, not quoted from the designs):

- The web UI lints with `profile='default'` only (`server/app.py:245`, `:427`). Under that profile,
  across all 94 example HTML files, failing findings split as: law_critical/warning 253,
  advisory/warning 219, structural/warning 9, structural/error 3, law_critical/error 1. So a
  rule can be a legal requirement and still be a `warning`, and 90 of 94 fixtures have zero errors.
- `examples/known-bad/bad_IL-001-01-2000.html` lints to status `pass`, 0 errors, 3 warnings:
  `term:track` (structural), `endpoints:20%-only` (law_critical), `special:nanomaterials`
  (advisory). `examples/known-bad/bad.html` lints to `fail`, 1 error, 17 warnings.
- `src/rules.py` carries a `title` and a `kind` for all 59 rules; the UI never sees either.
  Titles are written as satisfied conditions ("Alternatives search present").
- `tests/test_advisory_banner.py` asserts exactly 4 server-rendered copies of the advisory
  notice and that the string `'Advisory only` does not appear in `app.js`.
- `ChecklistItem` in `src/contracts.py` is a default pydantic model; extra keys are ignored, so
  adding fields to checklist items is additive.
- `mapReferenceToDataRef` returns `null` for `cosmetics:ban` and `surgery:multiple-survival`
  (22 of 485 failing findings across `examples/`), so those never render on screen today.
- The landing page's EN/HE toggle works (`landing.js:28-53`); `/app` has no i18n mechanism.

## 1. Principles

- The researcher lands on an answer, not a document: one sentence, then the first three things
  to fix, in order. Everything else is behind that.
- Priority is derived from the (severity, kind) pair, never severity alone and never kind alone.
  A law-critical warning is neither "blocking" nor "optional"; the UI says exactly what it is.
- Framing goes around the linter's strings. `message` and `suggested_fix` render verbatim and
  escaped. Rule ids, theme keys, profile and ruleset version stay visible on every finding and
  in print.
- One wording per fact. The advisory notice comes from the template via `advisoryNotice()`;
  the new Layer 1 scope sentence lives once, in the template. Counts on the landing page are
  59 rules and 12 topics or they are removed.
- Smallest diff that holds: native `<details>`, one new DOM node rendered once for screen and
  print, three lines of Python, no dependency, no build step, no inline handlers.

## 2. The researcher journey, screen by screen

All copy is English. `[HE]` marks a string that needs a Hebrew twin in a later i18n commit
(`/app`) or a reviewed `data-he` attribute now (landing). Nothing in `/app` gets Hebrew in
this pass; see section 7.

### 2.1 Landing (`/`)

Same layout, same sections, same animations. Strings only, plus one card change.

- Brand: `EthicTech` becomes `EtiqTech` everywhere in the UI (templates, JS headers, print
  header in `updatePrintSummary`). The repo, docs, env vars and the page's own roadmap copy
  (landing.html:570) already say EtiqTech.
- Tag: "Pre-submission check for animal-research protocols" [HE draft: "בדיקה מקדימה לבקשות
  מחקר בבעלי חיים"]
- H1: "Check your protocol before the committee does" [HE draft: "בדקו את הבקשה לפני שהוועדה
  בודקת"]
- Body: "Upload the file the Council system produces. EtiqTech checks it against the Council
  form and Israeli animal-welfare rules and tells you what to fix, in a few minutes, before you
  submit. It does not approve anything. The ethics committee still reviews every protocol."
  [HE draft: "העלו את הקובץ שמערכת המועצה מייצרת. EtiqTech בודק אותו מול טופס המועצה ומול כללי
  רווחת בעלי החיים בישראל ואומר מה לתקן, תוך כמה דקות, לפני ההגשה. הכלי לא מאשר דבר. ועדת
  האתיקה עדיין בודקת כל בקשה."]
- Buttons: "Check my protocol" / "How it works" [HE drafts: "בדקו את הבקשה שלי" / "איך זה עובד"]
- Hero terminal (`#terminal-animation`): keep the card, drop the shell prompt row
  `ethictech analyze protocol.html` and every number in `terminalLines` (42, 38, 11, 12
  sections, 0.12s). Lines become: "Reading the Council export", "Checking 59 rules",
  "2 findings tied to a legal requirement", "Reading 12 topics the way a reviewer would",
  "Report ready". Card title: "What a check looks like" [HE].
- Layer 1 sample card (landing.html:329-340): drop `$ ethictech lint protocol.json` and the
  `0.12s` footer. Replace the two rule ids that do not exist in the registry:
  `euthanasia:method` becomes `euthanasia:species-method`, `severity:classification` becomes
  `pain:category-consistency`. Keep the six-row shape and the ids visible. Footer: "59 rules
  checked".
- Every count: "40+", "42", "11" become "59" and "12" or are deleted from the sentence. The
  "11 AI Review Themes" trust card becomes "12 review topics". The `data-he` twins of every
  touched string are corrected in the same edit (the current Hebrew also says 11).
- Footer: add a link "Start here (for institutions)" to `/docs/START-HERE.md` on GitHub, next
  to the existing tagline. [HE]
- The 5 How-It-Works steps keep their structure; only the strings that name a command, a
  layer number or a count change, in the three-step language of 2.4.

### 2.2 Upload (`/app`)

Header subtitle: "Check your protocol before you submit it" [HE]

Drop zone, top to bottom:

- "Drop your protocol file here" [HE]
- "or click to choose a file. The .html file from the Council system, or a .json export." [HE]
  (`handleFile` currently rejects `.json` with `alert('Please upload an HTML file.')` while
  `ALLOWED_EXTENSIONS` at `server/app.py:69` and this very line accept it. Regex becomes
  `/\.(html?|json)$/i`.)
- Inline error line `.upload-error` (replaces both `alert()` calls; hidden until needed):
  - wrong type: "That file type is not supported. Upload the .html file you exported from the
    Council system, or a .json protocol file." [HE]
  - server failure: "Something went wrong reading that file. Try exporting it again from the
    Council system. If it keeps failing, the file may not be a Council export." [HE]
- Always-visible privacy line, true in every mode, sourced from PRIVACY.md guarantees 1 to 3:
  "Your protocol is checked in memory. It is never written to disk or into a log, and it is
  dropped after about an hour." [HE]
- `<details>` "Where do I get this file?" [HE]. Body: "It is the file the Council system
  produces when you save your request as a web page. Save it, then drop it here. Not sure? Ask
  your committee coordinator for the HTML export of your request." [HE] Plus a Jinja comment
  `{# TODO(maintainer): exact menu path in the Council system, see docs/design/spec.md 8.2 #}`.
  No click-by-click steps are invented.
- `<details id="model-selection">` "Advanced: choose the AI model" [HE], collapsed, wrapping the
  existing provider/model selects and `#model-status` unchanged. The `id` moves from the inner
  div to the `<details>` so `fetchProviders()`'s existing `sel.hidden = true` hides the whole
  disclosure in linter-only mode (a judge caught the empty-disclosure leak). Inside, the Ollama
  branch of `fetchModels()` sets `#model-status` to "This model runs on this server. Your
  protocol is not sent anywhere else." when `providerInfo[provider].local` is true; the existing
  remote warning string stays.

### 2.3 Checking (spinner)

- `.loading-text`: "Checking your protocol" [HE]
- `.loading-subtext`: "Step 1 of 3: checking the form against the rules. A few seconds." [HE]
  In linter-only mode: "Checking the form against the rules. A few seconds." [HE]

### 2.4 Results

Top of `#results-section`, above the four cards: the new `#report-summary` node (section 4).
Then the four cards, relabelled, values unchanged:

- Status card: label "Automated check" [HE], value "PASSED" / "FAILED" (was PASS/FAIL). This is
  exactly what `status` means and nothing more.
- Errors card: label "Fail the check" [HE]
- Warnings card: label "Other findings" [HE]
- LLM card: label "AI review (advisory)" [HE]

Then the RTL protocol with its badges, untouched. Badge text stays "2 Errors" / "1 Warning";
the raw severity word is what committees see in print today and the chip vocabulary in the
detail panel carries the plain reading.

Layer 2 floating card (`setLLMStatus`, `handleThemeStart`, `handleComplete`):

- start: "Step 2 of 3: reading your protocol the way a reviewer would. Usually a few minutes."
  [HE] (no minutes figure; `docs/benchmarks.md` has no timing that supports one)
- per theme: `Reading: ${label}`; progress text `${progress} of ${total} topics` [HE]
- `.thinking-label`: "Draft notes from the model (not the result)" [HE]
- complete, all adequate: `All ${total} topics look adequate.` [HE]
- complete, otherwise: `${acceptable} of ${total} topics look adequate. ${total - acceptable} need
  work.` [HE]
- error: `The AI review could not finish (${message}). The rule checks are unaffected and your
  report is ready to export.` [HE]
- connection lost: "Lost the connection to the AI reviewer. The rule checks are complete and
  your report is ready to export." [HE]

Layer 3 card and panel (`startLayer3Review`, `handleLayer3Event`, `showLayer3Results`):

- start: "Step 3 of 3: a second, deeper read of the whole protocol. Runs only when something
  needs it." [HE]
- `layer3_trigger`: `Second read, because: ${reason}` [HE]
- `layer3_skip`: "Second read not needed. Nothing serious came up." [HE]
- `pass_start`: `Second read, part ${pass}: ${label}` [HE]
- done, ok: "Second read: nothing serious." [HE]; done, issues: "Second read: found things to
  fix. They are in the panel below." [HE]
- panel header "Human Eye Review" becomes "Second read (deeper review)" [HE]; "Section
  Findings" becomes "What the deeper read found" [HE]; "Action:" becomes "What to change:" [HE];
  "Cross-Reference Issues" becomes "Things that contradict each other" [HE]. The printed block
  keeps "Human Eye Review (Layer 3)" for committee continuity.
- The never-shown `#layer3-btn` and `showLayer3Button()` are deleted.

Export button (`setExportReady`): disabled label "Export PDF (ready when the review finishes)"
[HE], enabled label "Export PDF". The tooltip goes.

Reviewer notes: unchanged.

## 3. The finding card

One template string in `showLintIssueDetails`, same `detail-issue` div, same panel. Order and
source of every line:

```
[LEGAL REQUIREMENT]                                    <- tier chip, section 3.1
Requirement not met: Humane endpoints beyond 20% weight loss   <- "Requirement not met:" label + RULES[rule_id].title
What the check found
  Experiment 1: humane endpoints mention only 20% weight loss without model-specific criteria.
                                                       <- item.message, verbatim
Why it matters
  Tied to a legal requirement. It does not fail the automated check under this profile,
  but committees send protocols back for it.           <- one of four fixed strings, 3.2
What to change
  Weight loss of 20% alone is not a sufficient humane endpoint. Add earlier and ...
                                                       <- item.suggested_fix, verbatim
Where: Experiment 1                                    <- formatRefName(dataRef)
endpoints:20%-only · warning · ruleset 1.0.0 · profile default   <- grey mono line
Was this finding useful?  [thumbs]                     <- feedbackHtml(), last
```

Rules:

- The headline is `"Requirement not met: " + rule_title`. Every registry title is a satisfied
  condition, so this label makes all 59 read correctly on a failure without rewriting them
  (judges on all three designs flagged bare titles reading backwards). For `rule_id ===
  'required'` the title is generic ("Required fields present at a given path"); skip the
  headline and let the message lead, since it already reads "Missing required fields at ...".
- Labels "What the check found", "Why it matters", "What to change", "Where" are UI chrome.
  [HE] on all four.
- `message` and `suggested_fix` are never edited, truncated or merged. Both get
  `unicode-bidi: plaintext` in CSS so a Hebrew species name inside an English sentence keeps its
  brackets and punctuation in place inside the LTR panel (`.detail-content` is already
  `direction: ltr`).
- The grey line keeps the `title="rule id · ruleset x"` tooltip, adds `severity` and `profile`,
  and shows the raw `reference` in parentheses when it differs from `rule_id`. This is the
  line committees and the feedback loop key on.
- Feedback thumbs stay in the detail panel only, bound to the one existing listener in
  `setupFeedback()`. They are not duplicated into the summary list (a judge showed that
  duplicating `feedbackHtml()` lets one person submit two rows for one rule id).
- Everything passes through `escapeHtml` / `escapeAttr`. No inline handlers.

### 3.1 Tiers (the one rule the whole spec depends on)

Tier is a pure function of `(severity, rule_kind)`:

| tier | condition | chip | colour |
|---|---|---|---|
| 1 | `severity === 'error'` (any kind) | FAILS THE CHECK | red (`--status-fail`) |
| 2 | `severity === 'warning' && rule_kind === 'law_critical'` | LEGAL REQUIREMENT | amber-red |
| 3 | everything else that failed | WORTH FIXING | amber (`--status-warning`) |

Tier 1 is exactly what makes `status` = `fail`. Tier 2 is the class the default profile
demotes to a warning and `strict_law` would promote to an error. Tier 3 is advisory plus
structural warnings. The raw `severity` word is still printed on the grey line.

### 3.2 Why-it-matters strings (four, fixed, keyed on tier and kind)

- tier 1: "This fails the automated check. Fix it before you submit." [HE]
- tier 2: "Tied to a legal requirement. It does not fail the automated check under this
  profile, but committees send protocols back for it." [HE]
- tier 3, kind structural or required: "The Council form is incomplete or inconsistent here."
  [HE]
- tier 3, kind advisory: "Not required. Fixing it makes the committee's review faster." [HE]

### 3.3 LLM finding (`showLLMDetails`)

Smaller change; the constraints are tightest here.

- Title stays the theme name; the theme key is added to the grey line:
  `euthanasia_and_endpoints · advisory · 12 topics`.
- Score badge gains its label: "2 of 3: Partially Adequate" (already computed by
  `formatGradeLabel`). "Overall score: 2/3" line stays.
- "Sub-Questions" becomes "What the model looked at" [HE]. All sub-questions stay listed.
- `groundingHtml(result.grounding)` renders exactly as today ("Sources used for grounding",
  `[G1] title`, URL, licence).
- The advisory banner stays last, read via `advisoryNotice()`, word for word.
- `formatThemeName` gains `writing_quality: 'Writing Quality'`; today the twelfth theme renders
  as its raw key on badges and in print.

## 4. The one-page summary (screen and print)

One node, `#report-summary`, first child of `#results-section`, built by one function
`renderReportSummary()` called from `showResults`, `handleThemeDone`, `handleComplete`,
`handleLayer3Event('complete' | 'skip')` and `resetToUpload` (clears it). It is visible on
screen and is the first thing printed; it is outside `.document-container`, so the existing
`#print-summary-block` (File / Ruleset / Status / Errors / Warnings, theme list, Layer 3
verdict) prints directly after it, unchanged. Print CSS: `#report-summary { page-break-after:
avoid; direction: ltr; text-align: left; }`, nothing else.

Content, in order. Counts `b`, `l`, `o` are the tier 1, 2, 3 totals over failing checklist
items (built from `lintReport.checklist`, not `lintIssuesMap`, so the 22 findings the data-ref
map drops are counted and listed).

1. Verdict sentence (JS fills numbers into template spans; `n === 1 ? 'finding' : 'findings'`):
   - `b > 0`: "{b} finding(s) fail the automated check. Fix them before you submit."
     then, if `l > 0`, " {l} more are tied to a legal requirement." then, if `o > 0`,
     " {o} more are worth fixing." [HE]
   - `b === 0 && l > 0`: "Nothing fails the automated check, but {l} finding(s) are tied to a
     legal requirement. Committees send protocols back for these." then the `o` clause. [HE]
   - `b === 0 && l === 0 && o > 0`: "Nothing fails the automated check. {o} finding(s) are worth
     fixing before you submit." [HE]
   - all zero: "The automated check found nothing to fix." [HE]
   The word "blocking" does not appear anywhere. On `bad_IL-001-01-2000.html` this renders:
   "Nothing fails the automated check, but 1 finding is tied to a legal requirement. Committees
   send protocols back for these. 2 more are worth fixing."
2. Scope sentence, static text in `app.html`, printed with the node: "This is a pre-submission
   check against the Council form and Israeli animal-welfare rules. It is not an approval. The
   ethics committee reviews every protocol." [HE] New outbound wording; maintainer sign-off
   (8.1). It lives in the template so exactly one copy exists, the same discipline as the
   advisory notice.
3. "Start with these" [HE]: up to three entries, ranked tier 1, then tier 2, then tier 3,
   ties broken by checklist order, one entry per distinct `rule_id`. Each entry:
   - tier chip + "Requirement not met: {rule_title}" (message leads for `required`)
   - one instance: the `message` verbatim; several instances: "{n} places: Experiments 1, 2, 3"
     from the `:exp-N` suffixes (no message shown, so no two messages are ever collapsed into
     one)
   - `rule_id` in mono
   - button "Show me where" [HE]: `dataRef = mapReferenceToDataRef(reference)`; if
     `lintIssuesMap[dataRef]` exists, call the existing `showLintIssueDetails(lintIssuesMap[dataRef],
     dataRef)` and `highlightSection(dataRef)`; otherwise open the detail panel with just this
     rule's failing items and title "Finding" (no highlight). No button dead-ends.
4. AI section, present only when `Object.keys(llmResults).length > 0`, appended by JS:
   - "AI review (advisory): {k} of {n} topics look adequate." then the list of themes scoring
     below 2 as `theme name (score of 3)`, each a button opening `showLLMDetails`. [HE]
   - Layer 3 line when `layer3Results && !layer3Results.skipped`: "Second read: {verdict},
     risk {risk_profile}." [HE]
   - `advisoryNotice()` text as a `<p class="advisory-banner">`, inserted by JS the same way
     `showLLMDetails` does today. Not server-rendered, so the `count == 4` test holds.
5. Provenance line, always: "Checked with EtiqTech · ruleset {ruleset_version} · profile
   {profile} · {n} findings on {file}" [HE]. `profile` is shown because default and strict_law
   disagree about what counts as an error, and a coordinator receiving two PDFs needs to see why.

Print order becomes: this node (page 1), the existing machine-readable block, the RTL protocol
with its inline `print-issue-box` / `print-llm-box` entries (unchanged, rule ids intact), the
Layer 3 block, reviewer notes, the advisory footer verbatim.

## 5. Linter-only mode (`ETIQTECH_LLM_DISABLED=1`)

- `fetchProviders()` hides the whole `<details id="model-selection">`; nothing of the Advanced
  disclosure is visible.
- Spinner subtext drops the step counter (2.3).
- `#report-summary` renders items 1, 2, 3 and 5; item 4 is absent, so no advisory notice appears
  in the summary (the notice is scoped by its own words to Layers 2 and 3). The provenance line
  ends with "AI review: not run". [HE]
- LLM card hidden and export enabled immediately, as today.
- The privacy line under the drop zone is unchanged and true.
- Acceptance: the START-HERE walk-through (commit 9) is executed literally in this mode.

## 6. Commit plan

Order is small and safe first. Effort includes the acceptance check. Total: 21.75 h.

1. **Name, counts, twelfth theme, .json.** `EthicTech` becomes `EtiqTech` in
   `server/templates/landing.html`, `server/templates/app.html`, `server/static/js/app.js`
   (file header and `updatePrintSummary`), `server/static/js/landing.js`. `formatThemeName`
   gains `writing_quality`. `handleFile` regex becomes `/\.(html?|json)$/i`. Landing counts
   become 59 / 12 or are removed (including `terminalLines` and every `data-he` twin);
   `euthanasia:method` and `severity:classification` are replaced with registered ids.
   Acceptance: `grep -rn "EthicTech\|40+\|42 rules\|11 ethical\|11 themes\|11 AI" server/` returns
   nothing; dropping `examples/adapters` JSON output uploads without a dialog. 0.75 h.
2. **Inline upload errors.** Add `<p class="upload-error" id="upload-error" hidden>` inside
   `.upload-card`; both `alert()` calls in `handleFile` set its text and unhide it; a new
   `handleFile` call clears it. Files: `app.js`, `app.html`, `main.css`.
   Acceptance: uploading a `.txt` shows the inline sentence and leaves the drop zone usable; no
   `alert(` remains in `app.js`. 1 h.
3. **Expose title and kind.** In `annotate_report()` (`src/rules.py:118`), after `rule_id`:
   `rule = RULES.get(item["rule_id"]) if item["rule_id"] else None`,
   `item["rule_title"] = rule.title if rule else None`, `item["rule_kind"] = rule.kind if rule
   else None`. Add `rule_title: Optional[str] = None` and `rule_kind: Optional[str] = None` to
   `ChecklistItem` in `src/contracts.py`. Add one assertion to
   `tests/test_rules_registry.py::test_every_emitted_check_maps_to_a_registered_rule`: every
   item with a `rule_id` has a non-empty `rule_title` and a `rule_kind` in the four known values.
   One line in `docs/schema.md` or `docs/rules.md` naming the two new keys.
   Acceptance: `PYTHONPATH=. pytest tests/test_rules_registry.py tests/test_privacy_canary.py -q`
   green. 0.5 h.
4. **Upload screen.** Copy from 2.2; `<details>` for "Where do I get this file?" with the Jinja
   TODO; `<details id="model-selection">` wrapping the selects (id moved off the inner div);
   privacy line; local-model line in `fetchModels()`. Files: `app.html`, `app.js`, `main.css`.
   Acceptance: with `ETIQTECH_LLM_DISABLED=1` the page shows no "Advanced" text at all; without
   it the disclosure is collapsed and opens on click and on Enter. 2 h.
5. **Progress and status strings.** All strings in 2.3 and 2.4 (spinner, `setLLMStatus` call
   sites, `handleThemeStart`, `handleComplete`, `handleLLMError`, SSE `onerror`, Layer 3 status
   text, Layer 3 panel labels, `setExportReady` label). Delete `#layer3-btn` and
   `showLayer3Button()`. Strings only; no SSE or control-flow change.
   Acceptance: `grep -n "Layer 2\|Human Eye\|themes scored\|Triggered:\|Pass \${" app.js`
   matches only the two print-block strings; `pytest tests/test_advisory_banner.py -q` green.
   1.5 h.
6. **Finding card.** Rebuild the template string in `showLintIssueDetails` to section 3, add
   `tierOf(item)` and the four why-strings, add `unicode-bidi: plaintext` on `.detail-message`
   and `.detail-fix-text`, update `showLLMDetails` per 3.3. Files: `app.js`, `main.css`.
   Acceptance: on `bad_IL-001-01-2000.html`, clicking the Experiment 1 badge shows LEGAL
   REQUIREMENT, "Requirement not met: Humane endpoints beyond 20% weight loss", the verbatim
   message, the tier 2 why-line, the verbatim fix, and `endpoints:20%-only · warning · ruleset
   1.0.0 · profile default`; thumbs still post to `/api/feedback` once. 3.5 h.
7. **Report summary node.** `#report-summary` markup in `app.html` (scope sentence static,
   spans for numbers), `renderReportSummary()` in `app.js` per section 4, the four card
   relabels, `resetToUpload` clears the node, print CSS. Files: `app.html`, `app.js`,
   `main.css`.
   Acceptance: on `bad_IL-001-01-2000.html` the first line on screen and on page 1 of the print
   preview is the tier 2 verdict sentence from 4.1, "Start with these" lists `endpoints:20%-only`
   first, and every "Show me where" button opens a panel; on
   `examples/head-to-head/IL-015-06-2000, 90015/bad_IL-015-06-2000.html` the list contains
   `cosmetics:ban`, which no badge shows today. 6 h.
8. **Landing copy.** Section 2.1 strings with the Hebrew drafts as `data-he`, terminal card and
   Layer 1 sample card changes, footer link. Files: `landing.html`, `landing.js`.
   Acceptance: toggle EN/HE and confirm every touched element swaps (no element shows
   `undefined`); the IntersectionObserver still reveals every `[data-animate]` block; blocked
   on 8.3 Hebrew review before merge. 3 h.
9. **`docs/START-HERE.md`.** One page: what it is (59 rules, 12 topics, approves nothing), who it
   is for, where the data goes (four bullets from PRIVACY.md plus its two verify commands), what
   it costs to run (linter-only: any container; AI layers: one Ollama machine; one gunicorn
   worker per container), what "checked with EtiqTech" means for committee staff (ruleset and
   profile named in the footer, default profile only in the web UI), what it is not (no auth;
   reverse proxy). Then the five-minute walk-through: `docker run -p 4242:4242 -e
   ETIQTECH_LLM_DISABLED=1 etiqtech`, open `/app`, upload
   `examples/known-bad/bad_IL-001-01-2000.html`, expect "Nothing fails the automated check, but
   1 finding is tied to a legal requirement ... 2 more are worth fixing", first fix "Humane
   endpoints beyond 20% weight loss", press Show me where, press Export PDF. Second fixture for
   the failing case: `examples/known-bad/bad.html` (1 fails the check, 17 others). Link from
   the top of `README.md` and the landing footer.
   Acceptance: the walk-through is run literally on a linter-only container before the commit
   lands and the quoted numbers are the ones observed. 1.5 h.

Every commit: `PYTHONPATH=. pytest tests/test_advisory_banner.py tests/test_privacy_canary.py
tests/test_rules_registry.py -q` green, and no `innerHTML` assignment without `escapeHtml` /
`escapeAttr` on every interpolation.

## 7. Explicitly out of scope, and why

- **Hebrew UI for `/app`.** About 180 JS-built strings and no `t()` mechanism; the landing
  walker (`el.textContent = el.dataset[lang]`) cannot translate anything JavaScript renders,
  and flipping `dir` on a page whose document is already RTL is a layout job across ~90
  direction-dependent selectors. Every new string is marked `[HE]` above so the extraction is
  mechanical next sprint. Design 2's 4 h estimate was judged at 6 to 8 h with RTL unresolved.
- **Rewriting the 59 rule titles.** Allowed (they are registry metadata, not golden-set
  strings) but a domain-reviewed 59-string pass does not fit the sprint. The "Requirement not
  met:" label makes the existing satisfied-condition titles read correctly; the rewrite is
  listed as a follow-up in 8.4.
- **Grouping identical findings across experiments into one card.** The biggest readability
  win in design 2 and the biggest correctness risk: it needs message-equality logic and a JS
  test, and `tests/` is pytest-only with no JS runner allowed. The summary list groups by
  `rule_id` only and never shows a merged message; full cards stay one per finding.
- **Re-check diff between uploads** (design 3, commit 6). Nobody asked for it, it matches on
  `:exp-N` suffixes that shift when experiments are reordered, and a judge named it the first
  cut. `resetToUpload` must clear `#report-summary`; that is the whole second-upload story.
- **Enabling export after Layer 1** (design 2). Changes what committees receive; maintainer
  decision (8.5), not a copy pass.
- **A profile switch in the UI, or lint under `strict_law` on the web path.** One route and a
  policy decision about which profile is an institution's bar. The UI names the profile instead
  (8.6).
- **A second advisory-flavoured sentence in JS** (design 3, commit 5). Violates the
  single-wording discipline the advisory test enforces. The Layer 1 scope sentence is template
  text, and the LLM notice is `advisoryNotice()`.
- **Rewording any linter `message` or `suggested_fix`, touching a rule id or theme name, or
  one word of the advisory notice.** All framing sits around them.
- **Removing the raw token stream, the floating cards, the detail panel, the annotated document
  view or the reviewer notes.** They work; relabelling the stream costs one string.
- **Server-side PDF.** A renderer means a temp file, which PRIVACY.md guarantee 1 forbids.
- **Deleting `server/templates/index.html`** (dead, no route renders it, still says EthicTech).
  Deletion is the maintainer's call.
- **Any new JS dependency, build step, framework, inline script or handler.** Both disclosures
  are `<details>`; the summary is a template string through `escapeHtml`.
- **Anything in the session cache, feedback store, rate limiter or canary path.** The privacy
  canary must pass unmodified after all nine commits.

## 8. Open questions for the maintainer

1. **Scope sentence wording** (4.2): "This is a pre-submission check against the Council form
   and Israeli animal-welfare rules. It is not an approval. The ethics committee reviews every
   protocol." It will be quoted by committees. Approve, edit, or drop. Default if silent: ship
   as written; it is template text and a one-line change.
2. **Council file-export steps.** The exact menu path in the Council system for producing the
   HTML file. The `<details>` ships with the repo-true wording ("the file the Council system
   produces when you save your request as a web page") plus "ask your committee coordinator"
   and a Jinja TODO. Nobody fills it in from memory.
3. **Hebrew review** of the landing drafts in 2.1 (tag, H1, body, two buttons, card title,
   footer link) by a native speaker before commit 8 merges. The `/app` strings marked `[HE]` are
   a list for the next sprint, not a request now.
4. **Rule titles as headlines.** With the "Requirement not met:" label all 59 read correctly.
   If you would rather have problem-phrased titles ("Humane endpoints stop at 20% weight
   loss"), that is a 59-string edit in `src/rules.py` plus `scripts/gen_rules_doc.py --check`;
   say so and it becomes a tenth commit with a domain reviewer named.
5. **Export timing.** Keep export gated on Layer 3 (today), or enable it when Layer 1 finishes
   with a visible "AI review still in progress" line on the summary. This spec keeps today's
   gate.
6. **Profile.** The web UI lints under `default` only, so law-critical findings arrive as
   warnings and the report says `pass`. The summary names the profile and the tier 2 wording
   explains it. Do you want `strict_law` selectable per instance (an env var and one line at
   `server/app.py:245` and `:427`), or is naming the profile enough for now?
7. **Card relabels.** "Automated check: PASSED / FAILED", "Fail the check", "Other findings",
   "AI review (advisory)". Confirm no committee process keys on the on-screen words ERROR /
   WARNING / PASS; the raw words stay in the print block and the grey line either way.
8. **Brand.** The UI is renamed to EtiqTech in commit 1 because the repo, docs, env vars and
   the landing roadmap copy already use it. Say stop if EthicTech was intentional.
