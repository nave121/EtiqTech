from collections import Counter

import pytest

from src.golden_dataset import (
    case_variant_path,
    lint_base_refs,
    load_case_instance,
    load_golden_dataset,
    validate_case,
)

TIERS = ("obvious", "moderate", "subtle", "hidden")


def _new_adversarial_cases():
    dataset = load_golden_dataset()
    cases = [
        case
        for case in dataset["cases"]
        if case.get("case_type") == "adversarial"
        and "examples/golden-dataset/adversarial/" in case["_case_json_path"].as_posix()
    ]
    return sorted(cases, key=lambda case: case["case_id"])


def _case_id(case):
    return case["case_id"]


def _case_tier(case):
    path_text = case["_case_json_path"].parent.name
    for tier in TIERS:
        if f"-{tier}-" in path_text:
            return tier
    raise AssertionError(f"Could not infer adversarial tier from {path_text}")


ADVERSARIAL_CASES = _new_adversarial_cases()
OBVIOUS_CASES = [case for case in ADVERSARIAL_CASES if _case_tier(case) == "obvious"]
MODERATE_AND_SUBTLE_CASES = [
    case for case in ADVERSARIAL_CASES if _case_tier(case) in {"moderate", "subtle"}
]
HIDDEN_CASES = [case for case in ADVERSARIAL_CASES if _case_tier(case) == "hidden"]


def test_new_adversarial_case_count_and_tiers():
    assert len(ADVERSARIAL_CASES) == 8

    counts = Counter(_case_tier(case) for case in ADVERSARIAL_CASES)
    for tier in TIERS:
        assert counts[tier] == 2, f"Expected 2 adversarial cases for tier {tier}, got {counts[tier]}"


@pytest.mark.parametrize("case", ADVERSARIAL_CASES, ids=_case_id)
def test_new_adversarial_cases_validate(case):
    errors = validate_case(case)
    assert not errors, "Case validation errors:\n" + "\n".join(errors)


@pytest.mark.parametrize("case", ADVERSARIAL_CASES, ids=_case_id)
def test_new_adversarial_good_variants_are_clean(case):
    good_refs = lint_base_refs(load_case_instance(case_variant_path(case, "good")))
    expected_good_refs = sorted(case["ground_truth"]["good_expected_l1_refs"])
    assert good_refs == expected_good_refs


@pytest.mark.parametrize("case", OBVIOUS_CASES, ids=_case_id)
def test_obvious_cases_fire_expected_layer1_refs(case):
    bad_refs = lint_base_refs(load_case_instance(case_variant_path(case, "bad")))
    expected_bad_refs = sorted(case["ground_truth"]["bad_expected_l1_refs"])

    assert expected_bad_refs, "Obvious adversarial cases must have deterministic Layer 1 expectations."
    assert bad_refs == expected_bad_refs


@pytest.mark.parametrize("case", MODERATE_AND_SUBTLE_CASES, ids=_case_id)
def test_moderate_and_subtle_cases_have_layer1_or_layer2_targets(case):
    bad_refs = lint_base_refs(load_case_instance(case_variant_path(case, "bad")))
    expected_bad_refs = sorted(case["ground_truth"]["bad_expected_l1_refs"])

    assert bad_refs == expected_bad_refs
    if expected_bad_refs:
        assert expected_bad_refs
    else:
        assert case["ground_truth"]["target_l2_themes"], (
            f"{case['case_id']} should document Layer 2 targets when Layer 1 is not expected to fire."
        )


@pytest.mark.parametrize("case", HIDDEN_CASES, ids=_case_id)
def test_hidden_cases_are_documented_for_layer2_and_layer3(case):
    bad_refs = lint_base_refs(load_case_instance(case_variant_path(case, "bad")))
    expected_bad_refs = sorted(case["ground_truth"]["bad_expected_l1_refs"])

    assert bad_refs == expected_bad_refs
    assert case["ground_truth"]["target_l2_themes"]
    assert case["ground_truth"]["target_l3_sections"]


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            case,
            marks=pytest.mark.xfail(
                reason="Layer 1 is not currently expected to catch this hidden semantic-only adversarial case."
            ),
        )
        for case in HIDDEN_CASES
        if not case["ground_truth"]["bad_expected_l1_refs"]
    ],
    ids=_case_id,
)
def test_hidden_cases_not_yet_expected_to_fire_layer1(case):
    bad_refs = lint_base_refs(load_case_instance(case_variant_path(case, "bad")))
    assert bad_refs, "Remove xfail and tighten expectations if Layer 1 starts catching this case."
