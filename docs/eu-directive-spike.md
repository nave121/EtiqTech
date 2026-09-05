# EU jurisdiction spike — Directive 2010/63/EU mapped to EtiqTech rules

**Status: research document for maintainer review (handoff decision #6). No EU rule is
implemented; nothing here changes behaviour.** Prepared 2026-09-05 from the consolidated
Directive text (EUR-Lex CELEX 02010L0063-20190626) and Annex VIII as published on
legislation.gov.uk. Regulatory interpretation below is a starting point, not legal advice.

## 1. Why a spike first

Israeli specifics are welded into the core (the Council request form, the Hebrew/English
form workflow, `writing_quality`, the guidance corpus). The rule registry (P3.1) gave every
rule a stable id and a first-pass `jurisdiction` tag (IL-form vs generic). Before building an
EU pack we need to know (a) which existing rules are already EU-relevant, (b) where the
Directive imposes something the linter does not check, and (c) how the Israeli 1–5 severity
scale relates to the Directive's four categories.

## 2. Directive requirements that a pre-submission linter can check

| Directive | Requirement (paraphrased) | Existing rule(s) | Gap / candidate |
|---|---|---|---|
| Art. 4 | Replacement, Reduction, Refinement must be applied | `alts:missing`, `alts:queries`, `alts:conclusion`, `N:justification-detail`, `N:power-analysis` | covered in substance; EU pack should keep `alts:engines` **out** (it is the Israeli form's "list the databases" field) |
| Art. 13(1) | Do not use animals where a Union-recognised non-animal method exists | `alts:*` | candidate **EU-ALT-VALIDATED**: alternatives search must state whether an EURL ECVAM-validated method exists for the purpose |
| Art. 13(2) | Prefer fewer animals, lowest pain capacity, least suffering | `N:*`, `sex:rationale` (partly) | candidate **EU-SPECIES-JUSTIFY**: explicit species-choice justification vs lower-sentience alternatives (the IL form asks "reasoning for choice of animal type" — same intent) |
| Art. 14 | Anaesthesia unless inappropriate; analgesia after; no severe pain without anaesthesia | `severity:analgesia`, `paralytic:without-anesthesia`, `surgery:*`, `postop:monitoring` | covered; EU wording differs (anaesthesia "unless inappropriate" needs a justification field) |
| Art. 15 + Annex VIII | Every procedure classified non-recovery / mild / moderate / severe; prohibition of long-lasting severe suffering that cannot be ameliorated | `pain:category-consistency`, `severity:monitoring` (IL 1–5 scale) | candidate **EU-SEVERITY-CLASS**: require one of the four categories per procedure; candidate **EU-SEVERE-PROHIBITED**: flag "long-lasting severe, cannot be ameliorated" |
| Art. 16 | Reuse only after mild/moderate, animal fully recovered, new procedure ≤ moderate | `reuse:justification`, `surgery:multiple-survival` | candidate **EU-REUSE-CONDITIONS**: reuse requires prior severity ≤ moderate + vet advice recorded |
| Art. 17 | Humane endpoint: kill when moderate/severe suffering likely to persist | `endpoints:20%-only`, `endpoints:death-only`, `endpoints:generic-consult` | covered |
| Art. 6 + Annex IV | Killing by a listed method, by competent person, with confirmation of death | `euthanasia:*` (AVMA matrix) | **conflict to resolve**: Annex IV differs from AVMA 2020 in places (e.g. CO2 conditions, decapitation/cervical dislocation weight limits); an EU pack needs an Annex IV matrix alongside `src/avma_matrix.py` |
| Art. 23–24 | Competence of staff; named persons | `pi:training`, `participant:training`, `participant:certified-without-training` | covered in substance; EU uses functions A–D (procedures / design / care / killing) — a pack could require the function letter |
| Art. 27 | Animal welfare body advised | — | out of scope for a protocol linter (institutional) |
| Art. 33 + Annex III | Care and accommodation standards | `housing:density`, `restraint:duration`, `deprivation:protocol` | partial; Annex III numeric minima (cage floor area per species/weight) are checkable — candidate **EU-HOUSING-ANNEX-III** |
| Art. 37 + Annex VI | Application content: objectives, 3Rs, severity, harm-benefit, numbers, endpoints | most of the linter | covered structurally |
| Art. 38 | Harm-benefit analysis explicit | Layer 2 theme `harm_benefit_analysis` | LLM only today; candidate structural check: a harm-benefit statement field present |
| Art. 39 | Retrospective assessment for severe / NHP projects | — | candidate **EU-RETRO-ASSESS**: severe or non-human-primate → flag that retrospective assessment applies |
| Art. 40 | Authorisation ≤ 5 years | `term:track` (IL: pilot 1y / regular ≤ 4y — verify in linter) | pack parameter: max term |
| Art. 43 | Non-technical summary (lay, anonymised) | `summaries:lay-length`, `summaries:scientific-length` | covered in substance; EU NTS has its own template (ALURES) — word limits are IL-form |

## 3. Severity scale mapping (Israel 1–5 → Directive categories)

The Israeli guidance (resources/law, "Severity level classification") uses five levels with
example procedures; Annex VIII uses four categories with example procedures. A defensible
first mapping, **to be confirmed by the maintainer with the Council's definitions**:

| IL level | Directive category | Annex VIII anchor examples |
|---|---|---|
| 1 | mild | injections, brief restraint, non-invasive imaging under sedation, superficial biopsy |
| 2 | mild / non-recovery | anaesthesia administration; terminal procedures under anaesthesia (non-recovery) |
| 3 | moderate | surgery with post-operative pain, >10% blood volume, acute toxicity, moderate tumour models, 48h food withdrawal |
| 4 | severe | lethal toxicity, progressive lethal tumours, severe post-operative impairment, inescapable shock, exhaustion endpoints |
| 5 | severe — and Art. 15(2) prohibition zone | long-lasting severe suffering that cannot be ameliorated → prohibited without the Art. 55(3) safeguard clause |

Note the Directive classifies by the **most severe effect on an individual animal after
refinement**, per procedure, while the IL form assigns a level per experiment — a pack needs
a per-procedure field or must treat the experiment's level as its maximum.

## 4. Proposed EU skeleton pack (≈5 seed rules) — for approval before implementation

1. `eu:severity-category` — each experiment declares one of non-recovery / mild / moderate / severe (Art. 15(1), Annex VIII).
2. `eu:severe-long-lasting` — flag when severity = severe and endpoints/analgesia text indicates long-lasting, non-ameliorable suffering (Art. 15(2)).
3. `eu:reuse-conditions` — reuse permitted only if prior severity ≤ moderate and general health restored, with veterinary advice (Art. 16).
4. `eu:killing-annex-iv` — euthanasia method listed in Annex IV for the species, with confirmation of death (Art. 6) — requires an Annex IV matrix; AVMA rules stay as advisory in the EU pack.
5. `eu:retrospective-assessment` — severe procedures or non-human primates → note that retrospective assessment applies (Art. 39).

Synthetic EU fixtures (canonical JSON via the adapter layer, no HTML) would prove the pack
abstraction; they must not be derived from the Israeli fixtures' protocol text.

## 5. What "pack" means mechanically (implemented as data, not behaviour)

A jurisdiction pack = rule set (registry ids) + guidance corpus (`doc_type`/`jurisdiction`
filter on `resources/corpus`) + theme configuration (e.g. `writing_quality` is IL-form). The
selection mechanism is `ETIQTECH_JURISDICTION` (see `src/rules.py: PACKS`); the Israel pack is
the current behaviour and the default. The EU pack above is not registered until the rules
exist and the maintainer has reviewed this document.

## Sources

- Directive 2010/63/EU, consolidated text: https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:02010L0063-20190626
- Annex VIII (severity classification) as published: https://www.legislation.gov.uk/eudr/2010/63/annex/VIII
- Original OJ publication: https://eur-lex.europa.eu/LexUriServ/LexUriServ.do?uri=OJ:L:2010:276:0033:0079:en:PDF
