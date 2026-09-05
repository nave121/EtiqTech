# PREPARE guidelines → EtiqTech coverage

The [PREPARE guidelines](https://norecopa.no/PREPARE) (Planning Research and Experimental
Procedures on Animals: Recommendations for Excellence; Smith AJ, Clutton RE, Lilley E,
Hansen KEA, Brattelid T. *Laboratory Animals* 2018, 52(2):135-141, doi:10.1177/0023677217724823)
are Norecopa's 15-topic checklist for planning animal studies, published under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). This page maps each topic to what
EtiqTech checks today — deterministic rule ids (Layer 1, see `docs/rules.md`) and LLM themes
(Layer 2) — so 3R practitioners can see the coverage and the gaps at a glance. Coverage
judgements are ours, not Norecopa's; topic titles are quoted from the checklist.

Legend: **L1** = deterministic rule id · **L2** = LLM theme (advisory) · **—** = not covered.

## A. Formulation of the study

| # | PREPARE topic | L1 rules | L2 themes | Coverage |
|---|---|---|---|---|
| 1 | Literature searches | `alts:missing`, `alts:engines`, `alts:queries`, `alts:conclusion` | `three_Rs_alternatives` | good — search presence, databases, queries and conclusion are checked; the *quality* of the search is L2 only (retrieval grounding, Phase 2, targets exactly this) |
| 2 | Legal issues | `title:track`, `term:track`, `permits:field-study`, `cosmetics:ban`, `gma:ibc` | — | partial — Israeli Council requirements and CITES/IBC hooks; no general legal checklist |
| 3 | Ethical issues, harm-benefit assessment and humane endpoints | `endpoints:20%-only`, `endpoints:death-only`, `endpoints:generic-consult`, `pain:category-consistency`, `severity:monitoring` | `harm_benefit_analysis`, `euthanasia_and_endpoints`, `severity_monitoring_analgesia` | good on endpoints; harm-benefit is L2 only (no structural field) |
| 4 | Experimental design and statistical analysis | `N:justification-detail`, `N:power-analysis`, `animals:totals-vs-exps`, `sex:rationale`, `sex:sabv` | `N_and_justification`, `sex_and_reuse`, `scientific_coherence` | good on numbers; randomisation/blinding are not checked (gap) |
| 5 | Objectives and timescale, funding and division of labour | `summaries:scientific-length`, `summaries:lay-length`, `pi`, `participant:*` | `scientific_coherence`, `personnel_and_training` | partial — objectives via summaries; funding/timescale are outside the request form |

## B. Dialogue between scientists and the animal facility

| # | PREPARE topic | L1 rules | L2 themes | Coverage |
|---|---|---|---|---|
| 6 | Facility evaluation | `permits:field-study`, `colony:*` | `housing_and_husbandry` | weak — facility approval is asserted by the form, not evaluated |
| 7 | Education and training | `pi:training`, `participant:training`, `participant:certified-without-training`, `vet:consultation` | `personnel_and_training` | good |
| 8 | Health risks, waste disposal and decontamination | `special:biosafety`, `special:nanomaterials`, `gma:ibc` | `hazardous_agents` | partial — biosafety/hazard metadata; waste and decontamination not checked (gap) |

## C. Quality control of the components in the study

| # | PREPARE topic | L1 rules | L2 themes | Coverage |
|---|---|---|---|---|
| 9 | Test substances and procedures | `special:*` (stereotaxic, oncology, diabetes, ocular, ascites) | `scientific_coherence` | partial — context-specific blocks only |
| 10 | Experimental animals | `animals:totals-vs-exps`, `sex:*`, `colony:breeding-plan`, `reuse:justification` | `sex_and_reuse` | good |
| 11 | Quarantine and health monitoring | — | `housing_and_husbandry` (indirectly) | gap |
| 12 | Housing and husbandry | `housing:density`, `restraint:duration`, `deprivation:protocol` | `housing_and_husbandry` | partial |
| 13 | Experimental procedures | `severity:analgesia`, `severity:monitoring`, `postop:monitoring`, `paralytic:without-anesthesia`, `surgery:multiple-survival`, `restraint:duration` | `severity_monitoring_analgesia`, `surgical_standards` | good |
| 14 | Humane killing, release, re-use or re-homing | `euthanasia:*` (AVMA 2020 matrix: species-method, CO2 rate, secondary method, pre-charged chamber, cervical weight, neonatal), `reuse:justification` | `euthanasia_and_endpoints`, `sex_and_reuse` | good — the strongest area of the linter |
| 15 | Necropsy | — | — | gap (the form's post-mortem block is parsed but not checked) |

## Summary

- Well covered: 1, 3 (endpoints), 4 (numbers), 7, 10, 13, 14.
- Partial: 2, 5, 8, 9, 12.
- Gaps: 11 (quarantine/health monitoring), 15 (necropsy), randomisation/blinding within 4,
  waste/decontamination within 8, harm-benefit as a structural field within 3.

Gaps are candidates for new rules; each would need fixtures (27 of 59 rules already have no
fixture coverage — see `docs/rules.md`) before it can be tuned with the feedback loop.
