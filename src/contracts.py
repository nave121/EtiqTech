"""
Inter-stage data contracts for the EthicChecker pipeline.

These Pydantic models describe the shape of data passed between pipeline stages:

  parse_html() → ParserOutput (validated via IACUC_SCHEMA_V2 JSONSchema)
  lint()       → LinterResult
  run_verification() → VerifierResult

Use these models for:
  - Pytest contract tests (validate real outputs conform to shape)
  - Runtime validation at stage boundaries
  - Documentation of expected fields and types
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Linter output
# ---------------------------------------------------------------------------

class ChecklistItem(BaseModel):
    status: Literal["pass", "fail"]
    message: str
    suggested_fix: Optional[str] = None
    severity: Literal["error", "warning", "advisory"]
    reference: str
    rule_id: Optional[str] = None  # canonical registry id (src/rules.py); None only for unregistered refs


class LintAnalysisSummary(BaseModel):
    N_total_all_experiments: int
    num_experiments: int
    sexes_seen: list[str]
    single_sex_design: bool
    is_colony: bool


class LintAnalysisAlternatives(BaseModel):
    present: bool
    engines_count: int
    queries_count: int
    conclusion_length: int


class LintAnalysis(BaseModel):
    summary: LintAnalysisSummary
    alternatives: LintAnalysisAlternatives
    experiments: list[dict[str, Any]]


class LinterResult(BaseModel):
    status: Literal["pass", "fail"]
    profile: str
    errors: int
    warnings: int
    structural_errors: int
    law_critical_errors: int
    advisory_warnings: int
    analysis: LintAnalysis
    generated_at: str
    checklist: list[ChecklistItem]
    ruleset_version: Optional[str] = None
    jurisdiction: Optional[str] = None
    rules_outside_pack: Optional[int] = None


# ---------------------------------------------------------------------------
# LLM verifier output
# ---------------------------------------------------------------------------

class ThemeSubQuestionResult(BaseModel):
    question: str = Field(min_length=1)
    score: Literal[0, 1, 2, 3]
    label: Literal["not_addressed", "inadequate", "partially_adequate", "adequate"]
    rationale: str = Field(min_length=1)


class GroundingRef(BaseModel):
    """A retrieved source injected into the theme prompt (Phase 2); surfaced for CC BY attribution."""
    ref: str = Field(pattern=r"^G\d+$")
    id: str
    title: str
    url: str
    doc_type: Optional[str] = None
    license: Optional[str] = None
    method: Optional[str] = None


class ThemeVerdict(BaseModel):
    score: Literal[0, 1, 2, 3]
    label: Literal["not_addressed", "inadequate", "partially_adequate", "adequate"]
    rationale: str = Field(min_length=1)
    sub_questions: list[ThemeSubQuestionResult] = Field(default_factory=list)
    grounding: list[GroundingRef] = Field(default_factory=list)


class ThemeMetadata(BaseModel):
    pass1_changed: bool
    pass1_score: Literal[0, 1, 2, 3]
    final_score: Literal[0, 1, 2, 3]
    pass1_label: Literal["not_addressed", "inadequate", "partially_adequate", "adequate"]
    final_label: Literal["not_addressed", "inadequate", "partially_adequate", "adequate"]
    new_questions_added: bool


class Layer2DisagreementSummary(BaseModel):
    themes_with_disagreement: int
    total_themes: int
    theme_keys: list[str] = Field(default_factory=list)


class VerifierResult(BaseModel):
    themes: dict[str, ThemeVerdict]
    pass1_themes: dict[str, ThemeVerdict] = Field(default_factory=dict)
    theme_metadata: dict[str, ThemeMetadata] = Field(default_factory=dict)
    disagreement_summary: Layer2DisagreementSummary = Field(
        default_factory=lambda: Layer2DisagreementSummary(
            themes_with_disagreement=0,
            total_themes=0,
            theme_keys=[],
        )
    )
    questions: list[dict[str, Any]]
    checklist_items: list[dict[str, Any]] = Field(default_factory=list)
    grounding_notice: Optional[str] = None  # set when retrieval degraded (lexical) or was unavailable


# ---------------------------------------------------------------------------
# Layer 3 "Human Eye" holistic review output
# ---------------------------------------------------------------------------

class HumanEyeSection(BaseModel):
    section: str
    status: Literal["Compliant", "Deficiency", "Information Missing"]
    severity: Literal["Critical", "Major", "Minor", "Recommendation"]
    finding: str
    regulatory_basis: str
    explanation: str
    action_required: str


class CrossRefIssue(BaseModel):
    fields: list[str]
    issue: str
    severity: Literal["Critical", "Major", "Minor", "Recommendation"]


class Layer3DisagreementSummary(BaseModel):
    verdict_changed: bool = False
    risk_changed: bool = False
    new_cross_reference_issues: int = 0


class HumanEyeResult(BaseModel):
    sections: list[HumanEyeSection]
    pass1_sections: list[HumanEyeSection] = Field(default_factory=list)
    cross_reference_issues: list[CrossRefIssue] = Field(default_factory=list)
    overall_verdict: Literal["approve", "revise_minor", "revise_major", "reject"]
    risk_profile: Literal["low", "medium", "high", "critical"]
    summary: str
    disagreement_summary: Layer3DisagreementSummary = Field(
        default_factory=Layer3DisagreementSummary
    )
    triggered_by: str = ""   # reason string from should_trigger_layer3
    skipped: bool = False
