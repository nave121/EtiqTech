"""
Tests for the AVMA 2020 Species-Euthanasia Matrix module.

Covers:
- Data structure integrity
- Species name normalizer (English, Hebrew, Latin, plurals)
- Euthanasia method normalizer
- Lookup helper functions
"""

import pytest
from src.avma_matrix import (
    AVMA_EUTHANASIA_MATRIX,
    normalize_species,
    normalize_method,
    check_method_for_species,
    is_neonatal,
    get_displacement_rate_range,
    get_neonatal_info,
    format_avma_summary_for_species,
)

# ---------------------------------------------------------------------------
# Data structure integrity
# ---------------------------------------------------------------------------

EXPECTED_SPECIES = ["mouse", "rat", "guinea_pig", "rabbit", "hamster", "gerbil", "zebrafish", "pig"]


def test_all_eight_species_present():
    for sp in EXPECTED_SPECIES:
        assert sp in AVMA_EUTHANASIA_MATRIX, f"Missing species: {sp}"


def test_all_species_have_three_categories():
    for species, entry in AVMA_EUTHANASIA_MATRIX.items():
        assert "acceptable" in entry, f"{species} missing 'acceptable'"
        assert "conditionally_acceptable" in entry, f"{species} missing 'conditionally_acceptable'"
        assert "unacceptable" in entry, f"{species} missing 'unacceptable'"
        assert isinstance(entry["acceptable"], list)
        assert isinstance(entry["conditionally_acceptable"], dict)
        assert isinstance(entry["unacceptable"], list)


def test_pre_charged_unacceptable_all_species():
    """AVMA M3.2: pre-charged CO₂ chambers are unacceptable for ALL species."""
    for species, entry in AVMA_EUTHANASIA_MATRIX.items():
        assert "pre-charged_CO2_chamber" in entry["unacceptable"], (
            f"{species}: pre-charged_CO2_chamber must be unacceptable"
        )


def test_acceptable_lists_not_empty():
    for species, entry in AVMA_EUTHANASIA_MATRIX.items():
        assert len(entry["acceptable"]) > 0, f"{species} has empty acceptable list"


def test_conditionally_acceptable_have_conditions():
    """Every conditionally acceptable method must list at least one condition."""
    for species, entry in AVMA_EUTHANASIA_MATRIX.items():
        for method, info in entry["conditionally_acceptable"].items():
            assert "conditions" in info, (
                f"{species}/{method}: missing 'conditions' key"
            )
            assert len(info["conditions"]) > 0, (
                f"{species}/{method}: conditions list is empty"
            )


# ---------------------------------------------------------------------------
# Species-specific data correctness
# ---------------------------------------------------------------------------

def test_rat_cervical_dislocation_weight_limit():
    """Rats: cervical dislocation max weight = 200g."""
    rat = AVMA_EUTHANASIA_MATRIX["rat"]
    cd = rat["conditionally_acceptable"]["cervical_dislocation"]
    assert cd["max_weight_g"] == 200


def test_rabbit_co2_displacement_rate():
    """Rabbits: CO₂ displacement rate 50-60% (different from rodents)."""
    rabbit = AVMA_EUTHANASIA_MATRIX["rabbit"]
    co2 = rabbit["conditionally_acceptable"]["CO2"]
    assert co2["displacement_rate_min"] == 50
    assert co2["displacement_rate_max"] == 60


def test_zebrafish_co2_unacceptable():
    """Zebrafish: CO₂ is not recommended."""
    zf = AVMA_EUTHANASIA_MATRIX["zebrafish"]
    assert "CO2" in zf["unacceptable"]


def test_zebrafish_ms222_acceptable():
    """Zebrafish: MS-222 (tricaine) is the standard method."""
    zf = AVMA_EUTHANASIA_MATRIX["zebrafish"]
    assert "MS-222" in zf["acceptable"]


def test_guinea_pig_cervical_dislocation_unacceptable():
    """Guinea pigs: cervical dislocation is NOT acceptable."""
    gp = AVMA_EUTHANASIA_MATRIX["guinea_pig"]
    assert "cervical_dislocation" in gp["unacceptable"]


def test_pig_cervical_dislocation_unacceptable():
    """Pigs: cervical dislocation is NOT acceptable."""
    pig = AVMA_EUTHANASIA_MATRIX["pig"]
    assert "cervical_dislocation" in pig["unacceptable"]


def test_mouse_neonatal_cutoff():
    """Mice: neonatal cutoff is 10 days."""
    mouse = AVMA_EUTHANASIA_MATRIX["mouse"]
    assert mouse["neonatal"] is not None
    assert mouse["neonatal"]["age_cutoff_days"] == 10


def test_rat_neonatal_cutoff():
    """Rats: neonatal cutoff is 10 days."""
    rat = AVMA_EUTHANASIA_MATRIX["rat"]
    assert rat["neonatal"] is not None
    assert rat["neonatal"]["age_cutoff_days"] == 10


def test_species_without_neonatal_rules():
    """Guinea pig, rabbit, hamster, gerbil, zebrafish, pig have no neonatal rules."""
    for sp in ["guinea_pig", "rabbit", "hamster", "gerbil", "zebrafish", "pig"]:
        assert AVMA_EUTHANASIA_MATRIX[sp]["neonatal"] is None, (
            f"{sp} should have neonatal=None"
        )


# ---------------------------------------------------------------------------
# Species normalizer
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    # English canonical
    ("mouse", "mouse"),
    ("Mouse", "mouse"),
    ("MOUSE", "mouse"),  # Lowercased to "mouse" → matches
    ("mice", "mouse"),
    ("rat", "rat"),
    ("rats", "rat"),
    ("guinea pig", "guinea_pig"),
    ("guinea_pig", "guinea_pig"),
    ("rabbit", "rabbit"),
    ("rabbits", "rabbit"),
    ("hamster", "hamster"),
    ("gerbil", "gerbil"),
    ("zebrafish", "zebrafish"),
    ("pig", "pig"),
    ("pigs", "pig"),
    ("swine", "pig"),
    # Latin names
    ("mus musculus", "mouse"),
    ("rattus norvegicus", "rat"),
    ("cavia porcellus", "guinea_pig"),
    ("oryctolagus cuniculus", "rabbit"),
    ("danio rerio", "zebrafish"),
    # Hebrew
    ("עכבר", "mouse"),
    ("עכברים", "mouse"),
    ("חולדה", "rat"),
    ("חולדות", "rat"),
    ("שפן ים", "guinea_pig"),
    ("ארנב", "rabbit"),
    ("ארנבות", "rabbit"),
    ("אוגר", "hamster"),
    ("ג'רביל", "gerbil"),
    ("גרביל", "gerbil"),
    ("דג זברה", "zebrafish"),
    ("דג-זברה", "zebrafish"),
    ("חזיר", "pig"),
    # Unknown / empty
    ("unknown species", None),
    ("dog", None),
    ("cat", None),
    ("", None),
    ("  ", None),
])
def test_normalize_species(raw, expected):
    result = normalize_species(raw)
    assert result == expected


def test_normalize_species_strips_whitespace():
    assert normalize_species("  mouse  ") == "mouse"
    assert normalize_species(" חולדה ") == "rat"


# ---------------------------------------------------------------------------
# Method normalizer
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("CO2", "CO2"),
    ("co2", "CO2"),
    ("co₂", "CO2"),
    ("carbon dioxide", "CO2"),
    ("inhalant_overdose", "inhalant_overdose"),
    ("inhalant overdose", "inhalant_overdose"),
    ("isoflurane overdose", "inhalant_overdose"),
    ("barbiturate", "barbiturate"),
    ("pentobarbital", "barbiturate"),
    ("pentobarbital overdose", "barbiturate"),
    ("cervical_dislocation", "cervical_dislocation"),
    ("cervical dislocation", "cervical_dislocation"),
    ("decapitation", "decapitation"),
    ("MS-222", "MS-222"),
    ("ms-222", "MS-222"),
    ("ms-222 overdose", "MS-222"),
    ("tricaine", "MS-222"),
    ("exsanguination", "exsanguination"),
    ("electrocution", "electrocution"),
    ("captive bolt", "captive_bolt"),
    ("rapid chilling", "rapid_chilling"),
    ("hypothermia", "rapid_chilling"),
    # Unknown
    ("unknown method", None),
    ("", None),
])
def test_normalize_method(raw, expected):
    assert normalize_method(raw) == expected


# ---------------------------------------------------------------------------
# check_method_for_species
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("species,method,expected_status", [
    # Mouse — acceptable methods
    ("mouse", "CO2", "conditionally_acceptable"),
    ("mouse", "barbiturate", "acceptable"),
    ("mouse", "inhalant_overdose", "acceptable"),
    # Mouse — conditionally acceptable
    ("mouse", "cervical_dislocation", "conditionally_acceptable"),
    ("mouse", "decapitation", "conditionally_acceptable"),
    # Mouse — unacceptable
    ("mouse", "pre-charged_CO2_chamber", "unacceptable"),
    # Rat
    ("rat", "CO2", "conditionally_acceptable"),
    ("rat", "cervical_dislocation", "conditionally_acceptable"),
    # Guinea pig — cervical dislocation is unacceptable
    ("guinea_pig", "cervical_dislocation", "unacceptable"),
    ("guinea_pig", "CO2", "conditionally_acceptable"),
    # Rabbit
    ("rabbit", "barbiturate", "acceptable"),
    ("rabbit", "CO2", "conditionally_acceptable"),
    # Zebrafish
    ("zebrafish", "MS-222", "acceptable"),
    ("zebrafish", "CO2", "unacceptable"),
    ("zebrafish", "cervical_dislocation", "unacceptable"),
    # Pig
    ("pig", "barbiturate", "acceptable"),
    ("pig", "cervical_dislocation", "unacceptable"),
    ("pig", "decapitation", "unacceptable"),
    # Unknown species
    ("unknown", "CO2", "unknown"),
    # Method not listed for species (should be unacceptable)
    ("mouse", "electrocution", "unacceptable"),
    ("zebrafish", "barbiturate", "acceptable"),
])
def test_check_method_for_species(species, method, expected_status):
    result = check_method_for_species(species, method)
    assert result["status"] == expected_status


def test_check_method_returns_conditions():
    result = check_method_for_species("rat", "cervical_dislocation")
    assert result["status"] == "conditionally_acceptable"
    assert result["conditions"] is not None
    assert result["max_weight_g"] == 200


def test_check_method_returns_displacement_rate():
    result = check_method_for_species("rabbit", "CO2")
    assert result["status"] == "conditionally_acceptable"
    assert result.get("displacement_rate_min") == 50
    assert result.get("displacement_rate_max") == 60


# ---------------------------------------------------------------------------
# is_neonatal
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("species,age_days,expected", [
    ("mouse", 5, True),
    ("mouse", 10, True),
    ("mouse", 11, False),
    ("mouse", 0.5, True),
    ("rat", 10, True),
    ("rat", 15, False),
    ("mouse", None, False),   # Unknown age
    ("rabbit", 5, False),     # No neonatal rules for rabbit
    ("zebrafish", 3, False),  # No neonatal rules
    ("unknown", 5, False),    # Unknown species
])
def test_is_neonatal(species, age_days, expected):
    assert is_neonatal(species, age_days) == expected


# ---------------------------------------------------------------------------
# get_displacement_rate_range
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("species,expected", [
    ("mouse", (30, 70)),
    ("rat", (30, 70)),
    ("guinea_pig", (30, 70)),
    ("rabbit", (50, 60)),
    ("hamster", (30, 70)),
    ("gerbil", (30, 70)),
    ("zebrafish", None),  # No CO₂ entry
    ("pig", (30, 70)),
    ("unknown", None),
])
def test_get_displacement_rate_range(species, expected):
    assert get_displacement_rate_range(species) == expected


# ---------------------------------------------------------------------------
# get_neonatal_info
# ---------------------------------------------------------------------------

def test_get_neonatal_info_mouse():
    info = get_neonatal_info("mouse")
    assert info is not None
    assert info["age_cutoff_days"] == 10
    assert info["CO2_requires_extended_exposure"] is True


def test_get_neonatal_info_none_for_rabbit():
    assert get_neonatal_info("rabbit") is None


def test_get_neonatal_info_none_for_unknown():
    assert get_neonatal_info("unknown") is None


# ---------------------------------------------------------------------------
# format_avma_summary_for_species
# ---------------------------------------------------------------------------

def test_format_avma_summary_contains_key_info():
    summary = format_avma_summary_for_species("mouse")
    assert "mouse" in summary
    assert "Acceptable" in summary
    assert "Conditionally acceptable" in summary
    assert "Unacceptable" in summary
    assert "Neonatal" in summary


def test_format_avma_summary_unknown_species():
    summary = format_avma_summary_for_species("unknown_species")
    assert "No AVMA data" in summary


def test_format_avma_summary_zebrafish():
    summary = format_avma_summary_for_species("zebrafish")
    assert "MS-222" in summary
    assert "Neonatal" not in summary  # zebrafish has no neonatal rules
