# Start here (for institutions)

One page for the people who decide whether to run EtiqTech: IT, compliance, committee
coordinators. Developers should read [README.md](../README.md) instead.

## What it is

EtiqTech is a pre-submission check for animal-research protocols. A researcher uploads the
file the Council system produces, and the tool checks it against the Council form and
Israeli animal-welfare rules, then says what to fix, in order.

- 59 deterministic rules (the list is in [rules.md](rules.md)). Every finding names its rule
  id and quotes the linter's message and suggested fix word for word.
- 12 review topics read by a language model, when one is configured. This layer is advisory
  and never changes a rule finding.
- It approves nothing. The ethics committee still reviews every protocol.

## Who it is for

- The researcher, before submitting: fix the obvious things without waiting for the committee.
- Committee staff: fewer protocols come back for the same missing block.
- The institution: a self-hosted tool that holds a draft for as short a time as possible.

## Where the data goes

From [PRIVACY.md](../PRIVACY.md), guarantees 1 to 4:

- Protocols are never written to disk. Parsed, linted and (optionally) sent to the model from
  memory. No database, no upload folder, no cache file.
- Protocols live in process memory for about one hour, at most. Restarting the process erases
  everything.
- No protocol text ever appears in logs, at any log level.
- The language model runs locally by default. The app refuses to send anything to a host that is
  not loopback, private-network or cluster-internal unless the operator sets
  `ETIQTECH_ALLOW_REMOTE_LLM=1`.

Verify it yourself, from a clone of the repo:

```bash
python -m pytest tests/test_privacy_canary.py tests/test_local_first.py -q
curl -s localhost:4242/api/health      # llm_local: true, law_loaded: true
```

The one thing that is stored is thumbs up/down on a finding: rule id or topic, verdict, ruleset
version, profile, timestamp. No protocol text. `ETIQTECH_FEEDBACK=0` turns it off.

## What it costs to run

- Linter-only (`ETIQTECH_LLM_DISABLED=1`): any container runtime. No GPU, no model. The image
  is `python:3.13-slim` plus the app.
- With the AI layers: one machine running Ollama that the container can reach
  (`OLLAMA_BASE_URL`). The reference Kubernetes manifests in `k8s/` run Ollama in-cluster.
- One gunicorn worker per container, always. Review sessions live in that process, so scale by
  running more containers, never more workers (`gunicorn.conf.py` explains why).

## What "checked with EtiqTech" means for committee staff

Every report carries a provenance line as the last line of the summary block at the top, on screen and on page 1 of the PDF:

```
Checked with EtiqTech · ruleset 1.0.0 · profile default · 3 findings on <file> · AI review: not run
```

- `ruleset` is the version of the 59 rules the check ran under.
- `profile` is the strictness. The web UI always runs `default`: a finding tied to a legal
  requirement is reported as LEGAL REQUIREMENT but does not fail the check, so a report can say
  PASSED and still list things the committee will send back. The stricter `strict_law` profile,
  which turns those into failures, is available from the command line only
  (`--profile strict_law`, see the README).
- "AI review: not run" appears on linter-only instances. Without it, the AI section is marked
  advisory in the report itself.

A protocol that "passed EtiqTech" passed the 59 rules under the named profile. Nothing more.

## What it is not

- Not an approval, and not legal or veterinary advice (see the disclaimer in the README).
- No login. The app has no authentication layer; put a reverse proxy with access control in
  front of it before anyone outside the machine can reach it (the reference deployment uses
  Cloudflare Access). Do not expose it to the public internet bare.

## Five-minute walk-through (linter-only)

Numbers below were observed on a linter-only instance built from this repo, ruleset 1.0.0.

1. Build and run, no GPU:

   ```bash
   docker build -t etiqtech .
   docker run -p 4242:4242 -e ETIQTECH_LLM_DISABLED=1 etiqtech
   ```

   `curl -s localhost:4242/api/health` answers
   `{"law_loaded":true,"llm_enabled":false,"llm_local":true,"llm_remote_allowed":false,"status":"ok"}`.

2. Open <http://localhost:4242/app>. The page shows a drop zone and the privacy line. No
   model picker appears in this mode.

3. Drop `examples/known-bad/bad_IL-001-01-2000.html` from your clone onto the page. After a
   few seconds the report opens with this first line:

   > Nothing fails the automated check, but 1 finding is tied to a legal requirement.
   > Committees send protocols back for these. 2 more are worth fixing.

   The cards below it read Automated check PASSED, Fail the check 0, Other findings 3.

4. "Start with these" lists three entries. The first is
   LEGAL REQUIREMENT, "Requirement not met: Humane endpoints beyond 20% weight loss",
   rule id `endpoints:20%-only`. The other two are WORTH FIXING: `term:track` and
   `special:nanomaterials`.

5. Press **Show me where** on the first entry. The protocol scrolls to Experiment 1 and the
   detail panel opens with the findings for that experiment; each shows what the check found, why
   it matters, what to change, and the grey line `endpoints:20%-only · warning · ruleset 1.0.0 ·
   profile default (endpoints:20%-only:exp-1)`.

6. Press **Export PDF**. The report prints from your browser with the summary as page 1 and the
   provenance line at the end of the summary block:
   `Checked with EtiqTech · ruleset 1.0.0 · profile default · 3 findings on bad_IL-001-01-2000.html · AI review: not run`.

For the failing case, repeat with `examples/known-bad/bad.html`. The first line becomes:

> 1 finding fails the automated check. Fix it before you submit. 16 more are tied to a legal
> requirement. 1 more is worth fixing.

The cards read Automated check FAILED, Fail the check 1, Other findings 17, and the first entry
under "Start with these" is FAILS THE CHECK, "Requirement not met: Animal totals match the sum
over experiments", rule id `animals:totals-vs-exps`.

Both files are synthetic fixtures. Never upload a real protocol to a demo instance.
