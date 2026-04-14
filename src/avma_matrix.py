# src/avma_matrix.py

"""
AVMA 2020 Species-Euthanasia Acceptability Matrix.

Deterministic lookup table encoding the AVMA Guidelines for the Euthanasia
of Animals (2020 edition) for the 8 most common laboratory species.

Used by:
- Layer 1 linter (src/linter_renderer.py) — deterministic species×method checks
- Layer 2 LLM agent (src/llm_agent.py) — grounding data for euthanasia theme

References:
- AVMA Guidelines for the Euthanasia of Animals: 2020 Edition
- PHS Policy IV.C.1.i (euthanasia must be consistent with AVMA recommendations)
- Israeli Prevention of Cruelty to Animals Law (5754-1994) via NRC Guide
"""

from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Species name normalizer
# ---------------------------------------------------------------------------

SPECIES_ALIASES: Dict[str, str] = {
    # ---- Mouse ----
    "mouse": "mouse",
    "mice": "mouse",
    "mus musculus": "mouse",
    # Hebrew
    "עכבר": "mouse",
    "עכברים": "mouse",
    "עכברי מעבדה": "mouse",

    # ---- Rat ----
    "rat": "rat",
    "rats": "rat",
    "rattus norvegicus": "rat",
    # Hebrew
    "חולדה": "rat",
    "חולדות": "rat",
    "חולדת מעבדה": "rat",

    # ---- Guinea pig ----
    "guinea pig": "guinea_pig",
    "guinea_pig": "guinea_pig",
    "guinea pigs": "guinea_pig",
    "cavia porcellus": "guinea_pig",
    # Hebrew
    "שפן ים": "guinea_pig",
    "שפני ים": "guinea_pig",

    # ---- Rabbit ----
    "rabbit": "rabbit",
    "rabbits": "rabbit",
    "oryctolagus cuniculus": "rabbit",
    # Hebrew
    "ארנב": "rabbit",
    "ארנבות": "rabbit",
    "ארנבים": "rabbit",
    "ארנב מעבדה": "rabbit",

    # ---- Hamster ----
    "hamster": "hamster",
    "hamsters": "hamster",
    "mesocricetus auratus": "hamster",
    "golden hamster": "hamster",
    "syrian hamster": "hamster",
    # Hebrew
    "אוגר": "hamster",
    "אוגרים": "hamster",

    # ---- Gerbil ----
    "gerbil": "gerbil",
    "gerbils": "gerbil",
    "meriones unguiculatus": "gerbil",
    "mongolian gerbil": "gerbil",
    # Hebrew
    "ג'רביל": "gerbil",
    "גרביל": "gerbil",

    # ---- Zebrafish ----
    "zebrafish": "zebrafish",
    "zebra fish": "zebrafish",
    "danio rerio": "zebrafish",
    # Hebrew
    "דג זברה": "zebrafish",
    "דג-זברה": "zebrafish",
    "דגי זברה": "zebrafish",

    # ---- Pig ----
    "pig": "pig",
    "pigs": "pig",
    "swine": "pig",
    "sus scrofa": "pig",
    "minipig": "pig",
    "mini-pig": "pig",
    "mini pig": "pig",
    # Hebrew
    "חזיר": "pig",
    "חזירים": "pig",
    "חזיר מעבדה": "pig",
}


def normalize_species(raw: str) -> Optional[str]:
    """Return canonical species key or None if unknown.

    Case-insensitive, strips whitespace.
    """
    if not raw:
        return None
    key = raw.strip().lower()
    return SPECIES_ALIASES.get(key)


# ---------------------------------------------------------------------------
# Euthanasia method normalizer
# ---------------------------------------------------------------------------

METHOD_ALIASES: Dict[str, str] = {
    # CO2
    "co2": "CO2",
    "co₂": "CO2",
    "carbon dioxide": "CO2",

    # Inhalant overdose
    "inhalant_overdose": "inhalant_overdose",
    "inhalant overdose": "inhalant_overdose",
    "isoflurane overdose": "inhalant_overdose",
    "isoflurane": "inhalant_overdose",
    "sevoflurane": "inhalant_overdose",
    "sevoflurane overdose": "inhalant_overdose",

    # Barbiturate / injectable overdose
    "barbiturate": "barbiturate",
    "pentobarbital": "barbiturate",
    "pentobarbital overdose": "barbiturate",
    "sodium pentobarbital": "barbiturate",
    "pentobarbitone": "barbiturate",

    # Injectable overdose (non-barbiturate)
    "injectable_overdose": "injectable_overdose",
    "injectable overdose": "injectable_overdose",
    "ketamine overdose": "injectable_overdose",
    "ketamine/xylazine overdose": "injectable_overdose",

    # Cervical dislocation
    "cervical_dislocation": "cervical_dislocation",
    "cervical dislocation": "cervical_dislocation",

    # Decapitation
    "decapitation": "decapitation",

    # MS-222 (tricaine) — zebrafish-specific
    "ms-222": "MS-222",
    "ms-222 overdose": "MS-222",
    "ms222": "MS-222",
    "tricaine": "MS-222",
    "tricaine methanesulfonate": "MS-222",
    "tricaine overdose": "MS-222",

    # Exsanguination (under anesthesia)
    "exsanguination": "exsanguination",

    # Electrocution (under anesthesia) — pig-specific
    "electrocution": "electrocution",

    # Captive bolt — pig-specific
    "captive bolt": "captive_bolt",
    "captive_bolt": "captive_bolt",

    # Rapid chilling — zebrafish-specific
    "rapid chilling": "rapid_chilling",
    "rapid_chilling": "rapid_chilling",
    "hypothermia": "rapid_chilling",
}


def normalize_method(raw: str) -> Optional[str]:
    """Return canonical method key or None if unknown.

    Case-insensitive, strips whitespace.
    """
    if not raw:
        return None
    key = raw.strip().lower()
    return METHOD_ALIASES.get(key)


# ---------------------------------------------------------------------------
# AVMA 2020 Euthanasia Matrix
# ---------------------------------------------------------------------------
# Structure per species:
#   acceptable:                list[str]   — always acceptable methods
#   conditionally_acceptable:  dict        — method → {conditions, max_weight_g, ...}
#   unacceptable:              list[str]   — never acceptable for this species
#   neonatal:                  dict | None — special rules for neonates
#
# Notes:
# - CO2 is listed ONLY in "conditionally_acceptable" (not in "acceptable")
#   because it always requires mandatory conditions (displacement rate, secondary
#   physical method). The linter checks conditions via separate rules.
# - "pre-charged_CO2_chamber" is unacceptable for ALL species (AVMA 2020 M3.2).
# ---------------------------------------------------------------------------

AVMA_EUTHANASIA_MATRIX: Dict[str, Dict[str, Any]] = {
    # ================================================================
    # MOUSE
    # ================================================================
    "mouse": {
        "acceptable": [
            "barbiturate",
            "inhalant_overdose",
            "injectable_overdose",
        ],
        "conditionally_acceptable": {
            "cervical_dislocation": {
                "conditions": [
                    "Performed by trained personnel",
                    "Under anesthesia or scientifically justified without",
                ],
                "max_weight_g": None,  # No explicit weight limit for mice
            },
            "decapitation": {
                "conditions": [
                    "Scientifically justified",
                    "Performed by trained personnel",
                    "Under anesthesia or scientifically justified without",
                ],
            },
            "CO2": {
                "conditions": [
                    "Gradual displacement rate 30-70% chamber volume/min",
                    "Secondary physical method required after respiratory arrest",
                ],
                "displacement_rate_min": 30,
                "displacement_rate_max": 70,
                "requires_secondary_method": True,
            },
        },
        "unacceptable": [
            "pre-charged_CO2_chamber",
        ],
        "neonatal": {
            "age_cutoff_days": 10,
            "note": (
                "Neonates ≤10 days are resistant to CO2 hypoxia; requires "
                "extended exposure (≥50 min) plus mandatory physical secondary method"
            ),
            "CO2_requires_extended_exposure": True,
            "requires_physical_secondary": True,
        },
    },

    # ================================================================
    # RAT
    # ================================================================
    "rat": {
        "acceptable": [
            "barbiturate",
            "inhalant_overdose",
            "injectable_overdose",
        ],
        "conditionally_acceptable": {
            "cervical_dislocation": {
                "conditions": [
                    "Weight must be ≤200g",
                    "Performed by trained personnel",
                ],
                "max_weight_g": 200,
            },
            "decapitation": {
                "conditions": [
                    "Scientifically justified",
                    "Performed by trained personnel",
                ],
            },
            "CO2": {
                "conditions": [
                    "Gradual displacement rate 30-70% chamber volume/min",
                    "Secondary physical method required after respiratory arrest",
                ],
                "displacement_rate_min": 30,
                "displacement_rate_max": 70,
                "requires_secondary_method": True,
            },
        },
        "unacceptable": [
            "pre-charged_CO2_chamber",
        ],
        "neonatal": {
            "age_cutoff_days": 10,
            "note": (
                "Neonates ≤10 days are resistant to CO2 hypoxia; requires "
                "extended exposure (≥50 min) plus mandatory physical secondary method"
            ),
            "CO2_requires_extended_exposure": True,
            "requires_physical_secondary": True,
        },
    },

    # ================================================================
    # GUINEA PIG
    # ================================================================
    "guinea_pig": {
        "acceptable": [
            "barbiturate",
            "inhalant_overdose",
            "injectable_overdose",
        ],
        "conditionally_acceptable": {
            "decapitation": {
                "conditions": [
                    "Scientifically justified",
                    "Performed by trained personnel",
                ],
            },
            "CO2": {
                "conditions": [
                    "Gradual displacement rate 30-70% chamber volume/min",
                    "Secondary physical method required after respiratory arrest",
                ],
                "displacement_rate_min": 30,
                "displacement_rate_max": 70,
                "requires_secondary_method": True,
            },
        },
        "unacceptable": [
            "pre-charged_CO2_chamber",
            "cervical_dislocation",  # NOT acceptable for guinea pigs
        ],
        "neonatal": None,
    },

    # ================================================================
    # RABBIT
    # ================================================================
    "rabbit": {
        "acceptable": [
            "barbiturate",
            "inhalant_overdose",
            "injectable_overdose",
        ],
        "conditionally_acceptable": {
            "CO2": {
                "conditions": [
                    "Gradual displacement rate 50-60% chamber volume/min",
                    "Secondary physical method required after respiratory arrest",
                    "Animal must be sedated or anesthetized before CO2 exposure",
                ],
                "displacement_rate_min": 50,
                "displacement_rate_max": 60,
                "requires_secondary_method": True,
            },
            "cervical_dislocation": {
                "conditions": [
                    "Only for rabbits ≤1 kg",
                    "Under anesthesia",
                    "Performed by trained personnel",
                ],
                "max_weight_g": 1000,
            },
            "decapitation": {
                "conditions": [
                    "Scientifically justified",
                    "Performed by trained personnel",
                ],
            },
            "exsanguination": {
                "conditions": [
                    "Under deep general anesthesia only",
                ],
            },
        },
        "unacceptable": [
            "pre-charged_CO2_chamber",
        ],
        "neonatal": None,
    },

    # ================================================================
    # HAMSTER
    # ================================================================
    "hamster": {
        "acceptable": [
            "barbiturate",
            "inhalant_overdose",
            "injectable_overdose",
        ],
        "conditionally_acceptable": {
            "cervical_dislocation": {
                "conditions": [
                    "Performed by trained personnel",
                    "Under anesthesia or scientifically justified without",
                ],
                "max_weight_g": None,  # No explicit AVMA weight limit for hamsters
            },
            "decapitation": {
                "conditions": [
                    "Scientifically justified",
                    "Performed by trained personnel",
                ],
            },
            "CO2": {
                "conditions": [
                    "Gradual displacement rate 30-70% chamber volume/min",
                    "Secondary physical method required after respiratory arrest",
                ],
                "displacement_rate_min": 30,
                "displacement_rate_max": 70,
                "requires_secondary_method": True,
            },
        },
        "unacceptable": [
            "pre-charged_CO2_chamber",
        ],
        "neonatal": None,
    },

    # ================================================================
    # GERBIL
    # ================================================================
    "gerbil": {
        "acceptable": [
            "barbiturate",
            "inhalant_overdose",
            "injectable_overdose",
        ],
        "conditionally_acceptable": {
            "cervical_dislocation": {
                "conditions": [
                    "Performed by trained personnel",
                    "Under anesthesia or scientifically justified without",
                ],
                "max_weight_g": None,
            },
            "decapitation": {
                "conditions": [
                    "Scientifically justified",
                    "Performed by trained personnel",
                ],
            },
            "CO2": {
                "conditions": [
                    "Gradual displacement rate 30-70% chamber volume/min",
                    "Secondary physical method required after respiratory arrest",
                ],
                "displacement_rate_min": 30,
                "displacement_rate_max": 70,
                "requires_secondary_method": True,
            },
        },
        "unacceptable": [
            "pre-charged_CO2_chamber",
        ],
        "neonatal": None,
    },

    # ================================================================
    # ZEBRAFISH
    # ================================================================
    "zebrafish": {
        "acceptable": [
            "MS-222",           # Tricaine methanesulfonate — standard for zebrafish
            "barbiturate",
        ],
        "conditionally_acceptable": {
            "rapid_chilling": {
                "conditions": [
                    "Only for zebrafish ≤3.8 cm or larvae",
                    "Immersion in ice water (2-4°C) for ≥10 min after opercular movement ceases",
                ],
            },
            "decapitation": {
                "conditions": [
                    "Scientifically justified",
                    "Performed by trained personnel",
                ],
            },
        },
        "unacceptable": [
            "CO2",                      # CO2 is not recommended for zebrafish
            "pre-charged_CO2_chamber",
            "cervical_dislocation",     # Not applicable to fish
        ],
        "neonatal": None,
    },

    # ================================================================
    # PIG (Sus scrofa domesticus)
    # ================================================================
    "pig": {
        "acceptable": [
            "barbiturate",
            "injectable_overdose",
        ],
        "conditionally_acceptable": {
            "CO2": {
                "conditions": [
                    "Gradual displacement rate; animal may show aversion",
                    "Secondary physical method required after respiratory arrest",
                    "Preferable: animal sedated before CO2 exposure",
                ],
                "displacement_rate_min": 30,
                "displacement_rate_max": 70,
                "requires_secondary_method": True,
            },
            "electrocution": {
                "conditions": [
                    "Under general anesthesia only",
                    "Proper equipment and trained personnel required",
                ],
            },
            "captive_bolt": {
                "conditions": [
                    "Performed by trained personnel",
                    "Followed by secondary method (exsanguination)",
                ],
            },
            "exsanguination": {
                "conditions": [
                    "Under deep general anesthesia only",
                ],
            },
            "inhalant_overdose": {
                "conditions": [
                    "Practical only for smaller pigs or sedated animals",
                ],
            },
        },
        "unacceptable": [
            "pre-charged_CO2_chamber",
            "cervical_dislocation",  # Not acceptable for pigs
            "decapitation",          # Not standard for pigs in lab settings
        ],
        "neonatal": None,
    },
}


# ---------------------------------------------------------------------------
# Lookup helper functions
# ---------------------------------------------------------------------------

def check_method_for_species(species_key: str, method_key: str) -> Dict[str, Any]:
    """Check AVMA acceptability of a euthanasia method for a given species.

    Parameters
    ----------
    species_key : str
        Canonical species key (output of normalize_species()).
    method_key : str
        Canonical method key (output of normalize_method()).

    Returns
    -------
    dict with keys:
        status : str
            "acceptable", "conditionally_acceptable", "unacceptable", or "unknown"
        conditions : list[str] | None
            Required conditions if conditionally_acceptable.
        max_weight_g : int | None
            Weight limit in grams if applicable.
        displacement_rate_min : int | None
        displacement_rate_max : int | None
        requires_secondary_method : bool
    """
    entry = AVMA_EUTHANASIA_MATRIX.get(species_key)
    if entry is None:
        return {"status": "unknown", "conditions": None, "max_weight_g": None,
                "requires_secondary_method": False}

    # Check unacceptable first (highest priority)
    if method_key in entry.get("unacceptable", []):
        return {"status": "unacceptable", "conditions": None, "max_weight_g": None,
                "requires_secondary_method": False}

    # Check conditionally acceptable
    cond = entry.get("conditionally_acceptable", {})
    if method_key in cond:
        info = cond[method_key]
        return {
            "status": "conditionally_acceptable",
            "conditions": info.get("conditions"),
            "max_weight_g": info.get("max_weight_g"),
            "displacement_rate_min": info.get("displacement_rate_min"),
            "displacement_rate_max": info.get("displacement_rate_max"),
            "requires_secondary_method": info.get("requires_secondary_method", False),
        }

    # Check acceptable
    if method_key in entry.get("acceptable", []):
        return {"status": "acceptable", "conditions": None, "max_weight_g": None,
                "requires_secondary_method": False}

    # Method not in any list for this species — treat as unacceptable
    # (AVMA principle: only listed methods are acceptable)
    return {"status": "unacceptable", "conditions": None, "max_weight_g": None,
            "requires_secondary_method": False}


def is_neonatal(species_key: str, age_days: Optional[float]) -> bool:
    """Check if an animal qualifies as neonatal for AVMA euthanasia purposes.

    Returns True if the species has a neonatal cutoff and the age is at or
    below it. Returns False if age is unknown or species has no neonatal rules.
    """
    entry = AVMA_EUTHANASIA_MATRIX.get(species_key)
    if entry is None:
        return False
    neo = entry.get("neonatal")
    if neo is None:
        return False
    if age_days is None:
        return False
    cutoff = neo.get("age_cutoff_days")
    if cutoff is None:
        return False
    return age_days <= cutoff


def get_displacement_rate_range(species_key: str) -> Optional[Tuple[int, int]]:
    """Return (min, max) CO2 displacement rate for a species, or None.

    Reads from the CO2 entry in conditionally_acceptable for the species.
    """
    entry = AVMA_EUTHANASIA_MATRIX.get(species_key)
    if entry is None:
        return None
    co2_info = entry.get("conditionally_acceptable", {}).get("CO2")
    if co2_info is None:
        return None
    lo = co2_info.get("displacement_rate_min")
    hi = co2_info.get("displacement_rate_max")
    if lo is not None and hi is not None:
        return (lo, hi)
    return None


def get_neonatal_info(species_key: str) -> Optional[Dict[str, Any]]:
    """Return neonatal handling info for a species, or None."""
    entry = AVMA_EUTHANASIA_MATRIX.get(species_key)
    if entry is None:
        return None
    return entry.get("neonatal")


def format_avma_summary_for_species(species_key: str) -> str:
    """Return a human-readable summary of AVMA rules for a species.

    Used for LLM grounding prompts.
    """
    entry = AVMA_EUTHANASIA_MATRIX.get(species_key)
    if entry is None:
        return f"No AVMA data available for species: {species_key}"

    lines = [f"### {species_key}"]
    lines.append(f"- Acceptable: {', '.join(entry.get('acceptable', []))}")

    cond_methods = list(entry.get("conditionally_acceptable", {}).keys())
    if cond_methods:
        lines.append(f"- Conditionally acceptable: {', '.join(cond_methods)}")

    unacc = entry.get("unacceptable", [])
    if unacc:
        lines.append(f"- Unacceptable: {', '.join(unacc)}")

    neo = entry.get("neonatal")
    if neo:
        lines.append(
            f"- Neonatal (≤{neo['age_cutoff_days']} days): "
            f"CO2 requires extended exposure + physical secondary method"
        )

    return "\n".join(lines)
