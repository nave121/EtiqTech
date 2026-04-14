# src/schema.py

"""
IACUC / Technion-style animal experiment request schema (V2).

This is shaped like a JSON Schema (draft-07-ish) but stored as a Python dict
for easier maintenance. It includes an `x_meta` block per major field with
natural-language expectations and rules for later LLM-based checking.
"""

IACUC_SCHEMA_V2 = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "$id": "https://navina.dev/iacuc.schema.v2.json",
    "title": "IACUC / Animal Experiment Request - Template V2 (Technion-style)",
    "type": "object",
    "required": [
        "header",
        "research",
        "pi",
        "participants",
        "summaries",
        "alternatives_search",
        "animals_total",
        "n_justification",
        "experiments",
        "pi_declaration",
    ],
    "properties": {
        "header": {
            "type": "object",
            "required": ["protocol_id", "institution"],
            "properties": {
                "protocol_id": {
                    "type": "string",
                    "x_meta": {
                        "title": "Protocol ID",
                        "description": "Council-generated request number.",
                        "expected": "Digits only as issued by the Council export, e.g. '26855'.",
                        "rules": [
                            "Must not be edited by the PI.",
                        ],
                        "source_of_truth": [
                            "Technion council system export header",
                        ],
                        "examples": ["26638", "26855", "26871"],
                    },
                },
                "institution": {
                    "type": "string",
                    "x_meta": {
                        "title": "Institution",
                        "description": "Submitting institution label as printed in header.",
                        "expected": "Hebrew RTL label, typically 'הטכניון'.",
                        "rules": [
                            "Must match institutional header.",
                        ],
                        "examples": ["הטכניון"],
                    },
                },
                "subcommittee": {
                    "type": "string",
                    "x_meta": {
                        "title": "Subcommittee",
                        "description": "Optional sub-committee name/number.",
                        "expected": "Free text or empty.",
                        "rules": [
                            "Optional; render if present.",
                        ],
                    },
                },
                "export_version": {
                    "type": "string",
                    "x_meta": {
                        "title": "Export version",
                        "description": "Renderer/format version for auditability.",
                        "expected": "Semver string, e.g. '2.0.0'.",
                        "rules": [],
                    },
                },
            },
        },

        "research": {
            "type": "object",
            "required": [
                "title_he",
                "title_en",
                "request_type",
                "is_continuation",
                "third_party_service",
                "approval_term_years",
                "sites",
            ],
            "properties": {
                "title_he": {
                    "type": "string",
                    "x_meta": {
                        "title": "Hebrew title",
                        "description": "נושא המחקר בעברית",
                        "expected": "Concrete description of disease/model/method; avoid generic text.",
                        "rules": [
                            "If request_type='regular', title SHOULD NOT contain 'פיילוט'.",
                            "If request_type='pilot', title SHOULD contain 'פיילוט'.",
                        ],
                        "examples": [
                            "שימוש בתקשורת סינתטית בין חיידקים מהונדסים ותאי מערכת חיסון למיקוד טיפולים בסרטן",
                            "מחקר פיילוט - מיקרו-מחטים פונקציונליים להסרת אנדוטוקסינים ישירות מזיהום עורי.",
                        ],
                    },
                },
                "title_en": {
                    "type": "string",
                    "x_meta": {
                        "title": "English title",
                        "description": "Project title in English.",
                        "expected": "Semantically aligned with Hebrew title.",
                        "rules": [
                            "If request_type='regular', avoid 'Pilot' in title.",
                            "If request_type='pilot', include 'Pilot' in title.",
                        ],
                        "examples": [
                            "Optimizing reovirus treatment against tumors",
                            "Pilot study to investigate the mechanism of a-synuclein aggregation in a new mouse model",
                        ],
                    },
                },
                "request_type": {
                    "type": "string",
                    "enum": [
                        "regular",
                        "pilot",
                        "teaching",
                        "colony",
                        "amendment",
                        "continuation",
                    ],
                    "x_meta": {
                        "title": "Request type",
                        "description": "Type/track of request (regular, pilot, teaching, colony, etc.).",
                        "expected": "Most protocols are 'regular' or 'colony'; 'pilot' is short and small N.",
                        "rules": [
                            "Pilot → approval_term_years MUST be 1.",
                            "Colony → invasive experiments are NOT allowed (breeding/ID/genotyping only).",
                            "Pilot requests should keep experiments and total N modest; large, multi-branch designs belong in 'regular' or 'continuation' tracks.",
                        ],
                        "examples": ["regular", "pilot", "colony"],
                    },
                },
                "is_continuation": {
                    "type": "boolean",
                    "x_meta": {
                        "title": "Is continuation",
                        "description": "Whether this request is a continuation.",
                        "expected": "true for continuation, false for new.",
                        "rules": [
                            "If true, require prior_protocol_id and continuation_reason.",
                        ],
                    },
                },
                "continuation_reason": {
                    "type": "string",
                    "x_meta": {
                        "title": "Continuation reason",
                        "description": "Short explanation why a continuation is needed.",
                        "expected": "Specific, not boilerplate.",
                        "rules": [
                            "Required if is_continuation=true.",
                        ],
                        "examples": [
                            "סיום ניסויים קודמים והעמקה",
                            "Continuation of the pilot protocol",
                        ],
                    },
                },
                "prior_protocol_id": {
                    "type": "string",
                    "x_meta": {
                        "title": "Previous protocol ID",
                        "description": "Council ID of the previous related protocol.",
                        "expected": "Digits; existing protocol number.",
                        "rules": [
                            "Required if is_continuation=true.",
                        ],
                        "examples": ["25645", "240", "26453"],
                    },
                },
                "third_party_service": {
                    "type": "boolean",
                    "x_meta": {
                        "title": "Third-party service?",
                        "description": "Is this a service project for another institution/company?",
                        "expected": "true only if sponsored by a third party.",
                        "rules": [
                            "If true, require 'third_party' block.",
                        ],
                    },
                },
                "approval_term_years": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 4,
                    "x_meta": {
                        "title": "Approval term (years)",
                        "description": "Requested term for approval.",
                        "expected": "1–4; pilot usually 1 year; regular often 4.",
                        "rules": [
                            "Pilot → MUST be 1 year.",
                        ],
                        "examples": [1, 3, 4],
                    },
                },
                "sites": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "required": ["name"],
                        "properties": {
                            "name": {"type": "string"},
                            "steps": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                    "x_meta": {
                        "title": "Sites of performance",
                        "description": "List of sites and which steps are carried out at each.",
                        "expected": "At least 'במוסד עצמו'; more if multi-center.",
                        "rules": [],
                    },
                },
            },
        },

        "pi": {
            "type": "object",
            "required": [
                "id_type",
                "id_number",
                "last_name_he",
                "first_name_he",
                "last_name_en",
                "first_name_en",
                "email",
                "phone_primary",
                "institutional_cert_no",
            ],
            "properties": {
                "id_type": {
                    "type": "string",
                    "enum": ["TZ", "passport"],
                    "x_meta": {
                        "title": "ID type",
                        "description": "National ID (TZ) or passport.",
                        "expected": "Typically 'TZ'.",
                        "rules": [],
                    },
                },
                "id_number": {
                    "type": "string",
                    "x_meta": {
                        "title": "ID number",
                        "description": "National ID / passport number.",
                        "expected": "String; no formatting logic enforced here.",
                        "rules": [],
                    },
                },
                "last_name_he": {"type": "string"},
                "first_name_he": {"type": "string"},
                "last_name_en": {"type": "string"},
                "first_name_en": {"type": "string"},
                "faculty": {"type": "string"},
                "department": {"type": "string"},
                "email": {"type": "string"},
                "phone_primary": {"type": "string"},
                "phone_secondary": {"type": "string"},
                "institutional_cert_no": {
                    "type": "string",
                    "x_meta": {
                        "title": "Institutional certification number",
                        "description": "PI's animal work certification number in the institution.",
                        "expected": "String like '61-2020', '21-2006', etc.",
                        "rules": [],
                    },
                },
                "training": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["cert_no", "issuer", "animal_scope"],
                        "properties": {
                            "cert_no": {"type": "string"},
                            "issuer": {"type": "string"},
                            "animal_scope": {"type": "string"},
                            "date": {"type": "string"},
                        },
                    },
                    "x_meta": {
                        "title": "PI training certificates",
                        "description": "Training table matching the council export.",
                        "expected": "At least one certificate covering the species used.",
                        "rules": [
                            "PI MUST have at least one training certificate.",
                        ],
                    },
                },
            },
        },

        "participants": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "family_name",
                    "given_name",
                    "national_id_or_passport",
                    "role",
                    "certified",
                ],
                "properties": {
                    "family_name": {"type": "string"},
                    "given_name": {"type": "string"},
                    "national_id_or_passport": {"type": "string"},
                    "role": {
                        "type": "string",
                        "enum": ["PI", "performs_procedures", "participant", "collaborator"],
                    },
                    "certified": {"type": "boolean"},
                    "training": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["cert_no", "issuer", "animal_scope"],
                            "properties": {
                                "cert_no": {"type": "string"},
                                "issuer": {"type": "string"},
                                "animal_scope": {"type": "string"},
                                "date": {"type": "string"},
                            },
                        },
                    },
                },
            },
            "x_meta": {
                "title": "Participants & training",
                "description": "All people involved in the protocol and their training.",
                "rules": [
                    "Any participant with role='performs_procedures' MUST have at least one training cert.",
                    "If certified=true, training[] MUST NOT be empty.",
                ],
            },
        },

        "third_party": {
            "type": "object",
            "properties": {
                "sponsor_org": {"type": "string"},
                "ordering_investigator_name": {"type": "string"},
                "sponsor_approver_name": {"type": "string"},
                "declaration_url": {"type": "string"},
                "contract_number": {"type": "string"},
                "data_rights_note": {"type": "string"},
            },
            "x_meta": {
                "title": "Third-party details",
                "description": "Details of sponsor institution/company if this is a service study.",
                "rules": [
                    "Required if research.third_party_service = true.",
                ],
            },
        },

        "summaries": {
            "type": "object",
            "required": ["scientific_en_≤300w", "lay_he_≤150w"],
            "properties": {
                "scientific_en_≤300w": {
                    "type": "string",
                    "x_meta": {
                        "title": "Scientific abstract (English, ≤300 words)",
                        "description": "Structured scientific summary in English (Council fields 3.1–3.5).",
                        "expected": (
                            "Cover, in order: (A) scientific subject; (B) relevant background "
                            "and previous results (for continuation); (C) specific question and "
                            "scientific rationale; (D) proposed animal use and model justification; "
                            "(E) predicted outcome."
                        ),
                        "rules": [
                            "Internal helper field aggregating Council items 3.1–3.5 (total upper bound ≈450 words).",
                        ],
                    },
                },
                "lay_he_≤150w": {
                    "type": "string",
                    "x_meta": {
                        "title": "Lay summary (Hebrew, ≤150 words)",
                        "description": "Plain-language justification of the study and animal use.",
                        "expected": "Written for non-expert; avoid jargon; must justify animal use.",
                        "rules": [
                            "Length must be ≤150 words.",
                        ],
                    },
                },
            },
        },

        "alternatives_search": {
            "type": "object",
            "required": ["engines", "date", "queries", "conclusion"],
            "properties": {
                "engines": {"type": "array", "items": {"type": "string"}},
                "date": {"type": "string"},
                "queries": {"type": "array", "items": {"type": "string"}},
                "conclusion": {"type": "string"},
            },
            "x_meta": {
                "title": "3Rs alternatives search",
                "description": "Document search for replacement/reduction/refinement alternatives.",
                "expected": (
                    "List search engines/methods (e.g. Good Search Practice on Animal Alternative – EU), "
                    "search date, main queries used, and a short conclusion on the absence of reasonable alternatives."
                ),
                "rules": [
                    "engines[] MUST NOT be empty.",
                    "queries[] MUST NOT be empty; each query should reflect an actual alternatives search.",
                    "conclusion MUST briefly state the outcome of the alternatives search (why no reasonable alternative exists).",
                ],
            },
        },

        "animals_total": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["species", "strain", "sex", "genetic_status", "source", "n_total"],
                "properties": {
                    "species": {"type": "string"},
                    "species_standard": {
                        "type": "string",
                        "enum": [
                            "mouse",
                            "rat",
                            "guinea_pig",
                            "rabbit",
                            "hamster",
                            "gerbil",
                            "zebrafish",
                            "pig",
                        ],
                    },
                    "strain": {"type": "string"},
                    "sex": {"type": "string", "enum": ["M", "F", "both", "unknown"]},
                    "genetic_status": {"type": "string"},
                    "source": {
                        "type": "string",
                        "enum": ["vendor", "in-house", "collaboration", "other"],
                    },
                    "n_total": {"type": "integer", "minimum": 0},
                },
            },
            "x_meta": {
                "title": "Animals required – totals",
                "description": "Total animal numbers per species/strain/sex/genotype.",
                "rules": [
                    "Totals must equal the sum over all experiments for the same key.",
                    "Duplicate rows should be merged.",
                    "If extra animals are requested as reserve for failures/mortality, the reserve fraction should be modest (≈10%) and explicitly justified in n_justification.details.",
                ],
            },
        },

        "n_justification": {
            "type": "object",
            "required": ["method", "details"],
            "properties": {
                "method": {
                    "type": "string",
                    "enum": ["power", "literature", "EDA"],
                },
                "details": {"type": "string"},
                "attachments": {"type": "array", "items": {"type": "string"}},
            },
            "x_meta": {
                "title": "Justification of animal numbers",
                "description": "Power calculation / literature / EDA explanation.",
                "expected": "Concrete numeric reasoning or literature-based justification.",
                "rules": [
                    "For method='power', details should mention effect size, alpha, power, and variability (SD/variance) assumptions.",
                    "For large total N (e.g. >~200 animals), details should break down numbers per group and endpoint, not only give a global count.",
                    "Reserve animals for attrition (typically ≤10%) should be described explicitly (what failures or losses they cover).",
                ],
            },
        },

        "is_colony": {
            "type": "boolean",
            "x_meta": {
                "title": "Is breeding/colony-only protocol",
                "description": "True if the protocol is only for maintaining a colony.",
                "rules": [
                    "If true, invasive experiments must not be present.",
                ],
            },
        },

        "colony_block": {
            "type": "object",
            "properties": {
                "purpose": {"type": "string"},
                "severity_level": {"type": "integer"},
                "genotyping": {
                    "type": "object",
                    "properties": {
                        "method": {"type": "string"},
                        "age_days": {"type": "string"},
                        "notes": {"type": "string"},
                    },
                },
                "production_model": {
                    "type": "object",
                    "properties": {
                        "females": {"type": "integer", "minimum": 0},
                        "litters_per_female_per_year": {"type": "number", "minimum": 0},
                        "avg_litter_size": {"type": "number", "minimum": 0},
                        "genotype_fraction": {"type": "number", "minimum": 0},
                        "attrition_fraction": {"type": "number", "minimum": 0},
                        "term_years": {"type": "integer", "minimum": 1, "maximum": 4},
                        "target_animals": {"type": "integer", "minimum": 0},
                    },
                },
            },
            "x_meta": {
                "title": "Colony / breeding block",
                "description": "Details specific to breeding-only protocols.",
                "rules": [
                    "Required when is_colony=true or request_type='colony'.",
                ],
            },
        },

        "experiments": {
            "type": "array",
            "minItems": 0,
            "items": {
                "type": "object",
                "required": [
                    "label",
                    "animals",
                    "housing",
                    "rationale_species_strain_sex",
                    "procedure_timeline",
                    "severity_level_1_to_5",
                    "monitoring",
                    "humane_endpoints",
                    "euthanasia",
                    "fate",
                ],
                "properties": {
                    "label": {"type": "string"},
                    "question": {"type": "string"},
                    "animals": {
                        "type": "object",
                        "required": ["species", "strain", "genetic_status", "sex", "n", "age", "source"],
                        "properties": {
                            "species": {"type": "string"},
                            "species_standard": {
                                "type": "string",
                                "enum": [
                                    "mouse",
                                    "rat",
                                    "guinea_pig",
                                    "rabbit",
                                    "hamster",
                                    "gerbil",
                                    "zebrafish",
                                    "pig",
                                ],
                            },
                            "strain": {"type": "string"},
                            "genetic_status": {"type": "string"},
                            "sex": {"type": "string", "enum": ["M", "F", "both"]},
                            "n": {"type": "integer", "minimum": 0},
                            "age": {
                                "type": "object",
                                "required": ["value", "unit"],
                                "properties": {
                                    "value": {"type": "number"},
                                    "unit": {
                                        "type": "string",
                                        "enum": ["days", "weeks", "months"],
                                    },
                                },
                            },
                            "weight": {
                                "type": "object",
                                "properties": {
                                    "value": {"type": "number"},
                                    "unit": {"type": "string", "enum": ["g", "kg"]},
                                },
                            },
                            "source": {"type": "string"},
                        },
                    },
                    "housing": {
                        "type": "object",
                        "required": ["group_housed", "enrichment"],
                        "properties": {
                            "group_housed": {"type": "boolean"},
                            "single_housing_reason": {"type": "string"},
                            "single_housing_duration_days": {"type": "number"},
                            "enrichment": {"type": "string", "enum": ["standard", "custom"]},
                            "enrichment_custom": {"type": "string"},
                        },
                    },
                    "housing_density": {
                        "type": "object",
                        "properties": {
                            "cage_floor_area_cm2": {"type": "number", "minimum": 0},
                            "animals_per_enclosure": {"type": "integer", "minimum": 1},
                            "breeding_with_litter": {"type": "boolean"},
                        },
                        "x_meta": {
                            "title": "Housing density",
                            "description": "Structured inputs for Guide-based floor-area checks.",
                            "rules": [
                                "Populate when cage-level housing density is part of the protocol record.",
                                "Use cage_floor_area_cm2 and animals_per_enclosure so deterministic Guide thresholds can be checked.",
                            ],
                        },
                    },
                    "rationale_species_strain_sex": {"type": "string"},
                    "procedure_timeline": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["day_or_timepoint", "step"],
                            "properties": {
                                "day_or_timepoint": {"type": "string"},
                                "step": {"type": "string"},
                                "route_or_site": {"type": "string"},
                                "volume_or_dose": {"type": "string"},
                                "device_or_material": {"type": "string"},
                            },
                        },
                    },
                    "restraint": {
                        "type": "object",
                        "properties": {
                            "used": {"type": "boolean"},
                            "method": {"type": "string"},
                            "max_duration_minutes": {"type": "number", "minimum": 0},
                            "sessions_per_animal": {"type": "integer", "minimum": 0},
                            "acclimation": {"type": "string"},
                            "monitoring": {"type": "string"},
                            "humane_removal_criteria": {"type": "string"},
                            "food_water_plan": {"type": "string"},
                            "justification": {"type": "string"},
                        },
                        "x_meta": {
                            "title": "Restraint details",
                            "description": "Use only when physical restraint or immobilization is part of the experiment.",
                            "rules": [
                                "Document the maximum duration, acclimation procedure, and criteria for removing distressed animals.",
                                "If restraint is prolonged, state how access to food/water is managed.",
                            ],
                        },
                    },
                    "analgesia": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["phase", "agent", "dose", "route", "frequency"],
                            "properties": {
                                "phase": {
                                    "type": "string",
                                    "enum": ["pre", "intra", "post"],
                                },
                                "agent": {"type": "string"},
                                "dose": {"type": "string"},
                                "route": {"type": "string"},
                                "frequency": {"type": "string"},
                            },
                        },
                    },
                    "anesthesia": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["agent", "route"],
                            "properties": {
                                "agent": {"type": "string"},
                                "rationale": {"type": "string"},
                                "dose": {"type": "string"},
                                "frequency": {"type": "string"},
                                "induction": {"type": "string"},
                                "maintenance": {"type": "string"},
                                "route": {"type": "string"},
                                "monitoring": {"type": "string"},
                            },
                        },
                    },
                    "anesthesia_drugs": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["agent", "dose", "route", "frequency"],
                            "properties": {
                                "agent": {"type": "string"},
                                "dose": {"type": "string"},
                                "route": {"type": "string"},
                                "frequency": {"type": "string"},
                                "rationale": {"type": "string"},
                                "induction": {"type": "string"},
                                "maintenance": {"type": "string"},
                                "monitoring": {"type": "string"},
                                "source_text": {"type": "string"},
                            },
                        },
                    },
                    "severity_level_1_to_5": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 5,
                    },
                    "pain_category": {
                        "type": "string",
                        "enum": ["B", "C", "D", "E"],
                    },
                    "pain_category_structured": {
                        "type": "object",
                        "required": ["raw", "parsed"],
                        "properties": {
                            "raw": {"type": "string"},
                            "parsed": {
                                "type": ["string", "null"],
                                "enum": ["B", "C", "D", "E", None],
                            },
                        },
                        "x_meta": {
                            "title": "Structured pain category",
                            "description": "Raw pain-category text plus optional USDA B/C/D/E normalization.",
                            "rules": [
                                "Preserve the source text in raw.",
                                "Set parsed only when a USDA B/C/D/E category is explicitly detectable; otherwise use null.",
                            ],
                        },
                    },
                    "monitoring": {
                        "type": "object",
                        "required": ["initial_72h_daily", "ongoing_per_week", "parameters", "documentation"],
                        "properties": {
                            "initial_72h_daily": {"type": "boolean"},
                            "ongoing_per_week": {"type": "integer", "minimum": 0},
                            "parameters": {"type": "array", "items": {"type": "string"}},
                            "documentation": {"type": "string"},
                        },
                        "x_meta": {
                            "title": "Monitoring",
                            "description": "Clinical monitoring schedule and what is documented.",
                            "rules": [
                                "For severity grades 4–5, monitoring conditions should be explicit (frequency, parameters, and documentation; score tables where appropriate).",
                            ],
                        },
                    },
                    "humane_endpoints": {
                        "type": "object",
                        "required": ["general"],
                        "properties": {
                            "general": {"type": "array", "items": {"type": "string"}},
                            "specific": {"type": "array", "items": {"type": "string"}},
                        },
                        "x_meta": {
                            "title": "Humane endpoints",
                            "description": "Criteria for stopping or euthanizing animals general to all arms and specific to this experiment.",
                            "rules": [
                                "For severity ≥3, general[] should include at least one concrete clinical criterion (e.g. weight loss threshold, behavior change, wound/tumor complications).",
                                "Where possible, specific[] should mention model-specific endpoints (e.g. tumor size/ulceration, flap necrosis, ocular damage) instead of only generic text.",
                            ],
                        },
                    },
                    "euthanasia": {
                        "type": "object",
                        "required": ["primary", "parameters", "confirmation"],
                        "properties": {
                            "primary": {"type": "string"},
                            "method_standard": {
                                "type": "string",
                                "enum": [
                                    "CO2",
                                    "inhalant_overdose",
                                    "barbiturate",
                                    "injectable_overdose",
                                    "cervical_dislocation",
                                    "decapitation",
                                    "MS-222",
                                    "exsanguination",
                                    "electrocution",
                                    "captive_bolt",
                                    "rapid_chilling",
                                ],
                            },
                            "parameters": {"type": "string"},
                            "conditions_text": {"type": "string"},
                            "confirmation": {"type": "string"},
                            "confirmation_details": {"type": "string"},
                        },
                        "x_meta": {
                            "title": "Euthanasia",
                            "description": "Primary method of euthanasia and how death is confirmed.",
                            "rules": [
                                "CO2 as a primary method should be accompanied by a confirmation step (e.g. cervical dislocation, thoracotomy, exsanguination, decapitation, ECG).",
                                "Methods such as cervical dislocation or decapitation should be performed under deep anesthesia or only where age-specific guidelines permit.",
                            ],
                        },
                    },
                    "reuse_or_prior_procedures": {
                        "type": "object",
                        "properties": {
                            "has_prior": {"type": "boolean"},
                            "prior_protocol_ids": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "x_meta": {
                            "title": "Reuse or prior procedures",
                            "description": "Indicates whether animals in this experiment have participated in previous experiments.",
                            "rules": [
                                "Default is no reuse; has_prior should normally be false.",
                                "If has_prior=true, prior_protocol_ids MUST list the previous permit IDs and reuse must be explicitly justified elsewhere.",
                            ],
                        },
                    },
                    "reuse_review": {
                        "type": "object",
                        "properties": {
                            "prior_severity": {
                                "type": "string",
                                "enum": ["mild", "moderate", "severe", "non_recovery"],
                            },
                            "fully_recovered": {"type": "boolean"},
                            "new_procedure_severity": {
                                "type": "string",
                                "enum": ["mild", "moderate", "severe", "non_recovery"],
                            },
                            "vet_consulted": {"type": "boolean"},
                        },
                        "x_meta": {
                            "title": "Reuse review",
                            "description": "Structured gate for protocols that reuse animals after prior procedures.",
                            "rules": [
                                "Reuse requires prior severity to have been mild or moderate.",
                                "Reuse requires full recovery, veterinarian consultation, and the new procedure to be mild, moderate, or non-recovery.",
                            ],
                        },
                    },
                    "field_study_permits": {
                        "type": "object",
                        "properties": {
                            "field_study": {"type": "boolean"},
                            "wildlife": {"type": "boolean"},
                            "collection_permit_ids": {"type": "string"},
                            "protected_species": {"type": "boolean"},
                            "cites_documentation": {"type": "string"},
                            "wildlife_pathogen_handling": {"type": "boolean"},
                            "biosafety_approval_id": {"type": "string"},
                            "field_euthanasia_method": {"type": "string"},
                            "field_euthanasia_details": {"type": "string"},
                        },
                        "x_meta": {
                            "title": "Field-study permits",
                            "description": "Regulatory documentation for field capture, wildlife work, and field euthanasia.",
                            "rules": [
                                "Field or wildlife work should list the relevant collection permit identifiers.",
                                "Protected-species work should include CITES or equivalent documentation where applicable.",
                                "Wildlife pathogen work should include biosafety approval details.",
                            ],
                        },
                    },
                    "fate": {
                        "type": "string",
                        "enum": ["euthanasia", "return_to_colony", "rehoming", "other"],
                    },

                    # Specialty sub-blocks
                    "stereotaxic_implant": {
                        "type": "object",
                        "properties": {
                            "used": {"type": "boolean"},
                            "craniotomy": {"type": "boolean"},
                            "implant_type": {"type": "string"},
                            "periop_antibiotics": {"type": "string"},
                            "warming_and_support": {"type": "string"},
                            "end_of_study_removal": {"type": "string"},
                        },
                    },
                    "oncology": {
                        "type": "object",
                        "properties": {
                            "tumor_induction_method": {"type": "string"},
                            "measurement_method": {"type": "string"},
                            "measurement_frequency": {"type": "string"},
                            "tumor_burden_cap": {"type": "string"},
                            "ulceration_policy": {"type": "string"},
                        },
                    },
                    "diabetes": {
                        "type": "object",
                        "properties": {
                            "measurement": {
                                "type": "string",
                                "enum": ["fasted", "non_fasted"],
                            },
                            "bg_threshold_mg_dl": {"type": "integer"},
                            "frequency": {"type": "string"},
                            "ketone_or_urine_checks": {"type": "string"},
                        },
                    },
                    "biosafety_infectious_agents": {
                        "type": "object",
                        "properties": {
                            "used": {"type": "boolean"},
                            "agent_name": {"type": "string"},
                            "BSL_level": {
                                "type": "string",
                                "enum": ["1", "2", "2+", "3", "4"],
                            },
                            "shedding_risk": {"type": "string"},
                            "PPE": {"type": "string"},
                            "decontamination_SOP": {"type": "string"},
                            "waste_handling": {"type": "string"},
                            "facility_biosafety_approval_id": {"type": "string"},
                        },
                    },
                    "nanomaterials": {
                        "type": "object",
                        "properties": {
                            "particle_type": {"type": "string"},
                            "size_distribution_nm": {"type": "string"},
                            "zeta_potential_mV": {"type": "string"},
                            "vehicle": {"type": "string"},
                            "exposure_route": {"type": "string"},
                            "aerosol_controls": {"type": "string"},
                        },
                    },
                    "ocular_procedures": {
                        "type": "object",
                        "properties": {
                            "topical_anesthesia": {"type": "string"},
                            "mydriatic": {"type": "string"},
                            "ocular_lubrication": {"type": "string"},
                            "postop_analgesia_specifics": {"type": "string"},
                            "vision_function_tests": {"type": "string"},
                        },
                    },
                },
            },
            "x_meta": {
                "title": "Experiments (1..N)",
                "description": "Per-experiment definitions, matching the Technion export pages.",
                "rules": [
                    "If surgery or invasive procedures are present, analgesia/anesthesia must be described.",
                    "Severity >=4 requires daily monitoring in the first 72h and at least weekly afterward.",
                    "CO2 euthanasia requires flow rate (30–70% chamber volume/min) and a confirmation step.",
                    "If text mentions tumor/graft → oncology sub-block required (tumor_burden_cap, ulceration_policy).",
                    "If diabetes model → diabetes block required (fasted/non_fasted, BG threshold).",
                    "If virus/oncolytic agent → biosafety block required.",
                    "If nanoparticle/VOC → nanomaterials block required.",
                    "If optic nerve/eye → ocular_procedures block required.",
                    "For severity ≥3 with surgery/trauma, peri- and post-operative analgesia should be present unless strongly justified.",
                    "If all experiments use a single sex, rationale_species_strain_sex should explicitly justify sex choice to avoid later duplicate male/female studies.",
                ],
            },
        },

        "postmortem_processing": {
            "type": "object",
            "properties": {
                "used": {"type": "boolean"},
                "perfusion": {"type": "string"},
                "fixation": {"type": "string"},
                "clearing_or_special_technique": {"type": "string"},
                "chemical_safety_notes": {"type": "string"},
            },
            "x_meta": {
                "title": "Post-mortem processing",
                "description": "Perfusion/fixation/clearing steps, especially for CNS work.",
                "rules": [],
            },
        },

        "pi_declaration": {
            "type": "object",
            "required": ["name", "date"],
            "properties": {
                "name": {"type": "string"},
                "date": {"type": "string"},
                "affirmations": {"type": "array", "items": {"type": "string"}},
            },
            "x_meta": {
                "title": "PI declaration",
                "description": "PI declaration matching the council export page.",
                "rules": [],
            },
        },

        "chair_statement": {
            "type": "object",
            "properties": {
                "decision": {
                    "type": "string",
                    "enum": ["Approved", "Not approved", "Revisions required", ""],
                },
                "comments": {"type": "string"},
            },
            "x_meta": {
                "title": "Chair statement",
                "description": "Optional; holds committee decision and comments.",
                "rules": [],
            },
        },
    },
}
