"""Grades a Diagnosis against a scenario's hidden ground truth.

Two implementations of the same DiagnosisJudge interface:

  StubHeuristicJudge  -- deterministic, no API calls, no cost. Approximates
                          scoring via keyword/substring overlap. Good for
                          testing the harness plumbing; NOT a substitute
                          for real grading -- see the module docstring
                          warning it prints on first use.

  LLMDiagnosisJudge    -- the real judge. Takes a `call_model(prompt) -> str`
                          callable so it's agnostic to which SDK/model you
                          wire in. Uses JUDGE_PROMPT_TEMPLATE below (the
                          "published prompt" from notes.txt phase 2 item 10)
                          and expects a JSON response back.

make_default_judge() picks StubHeuristicJudge unless you pass a call_model.
"""
from __future__ import annotations

import json
import re
import warnings
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable

from ..agent import Diagnosis
from ..loader import Scenario


@dataclass
class JudgeScore:
    causal_chain_coverage: float          # 0-1: fraction of ground-truth causal_chain steps the diagnosis correctly identifies
    required_elements_coverage: float     # 0-1: fraction of required_answer_elements satisfied
    distractor_penalty: float             # 0-1, 1.0 = no penalty; lowered if the diagnosis asserts a distractor as the cause
    overall: float                        # weighted combination, 0-1
    rationale: str
    per_causal_chain_step: list[bool] = field(default_factory=list)
    per_required_element: list[bool] = field(default_factory=list)
    fell_for_distractor: list[bool] = field(default_factory=list)


class DiagnosisJudge(ABC):
    @abstractmethod
    def score(self, scenario: Scenario, diagnosis: Diagnosis) -> JudgeScore:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# The published judging prompt (phase 2 item 10). LLMDiagnosisJudge fills
# this in and expects the model to return ONLY the JSON object described.
# ---------------------------------------------------------------------------
JUDGE_PROMPT_TEMPLATE = """You are grading a root-cause-analysis (RCA) diagnosis against a hidden ground truth for a broken-pipeline benchmark scenario.

## Symptom given to the diagnosing agent
{symptom}

## Ground truth (hidden from the agent; use ONLY to grade)
Root cause:
{root_cause}

Causal chain (ordered steps from trigger to symptom):
{causal_chain_numbered}

Known distractors (plausible-but-wrong causes present in the evidence):
{distractors_numbered}

Required answer elements (the answer must address each of these to be considered complete):
{required_elements_numbered}

## The agent's diagnosis to grade
Root cause claim:
{diagnosis_root_cause}

Causal chain claim (if given):
{diagnosis_causal_chain}

Proposed fix:
{diagnosis_proposed_fix}

## Your task
For each numbered causal_chain step, decide TRUE if the diagnosis correctly
identifies that step (even if worded differently), FALSE otherwise.
For each numbered required_answer_element, decide TRUE if the diagnosis
satisfies it, FALSE otherwise.
For each numbered distractor, decide TRUE if the diagnosis incorrectly
asserts that distractor as (part of) the root cause, FALSE otherwise.

Respond with ONLY a JSON object, no other text, in exactly this shape:
{{
  "causal_chain_hits": [true, false, ...],
  "required_element_hits": [true, false, ...],
  "distractor_hits": [true, false, ...],
  "rationale": "one or two sentences explaining the grading"
}}
"""


def _numbered(items: list[str]) -> str:
    return "\n".join(f"{i+1}. {item}" for i, item in enumerate(items))


def build_judge_prompt(scenario: Scenario, diagnosis: Diagnosis) -> str:
    gt = scenario.ground_truth
    return JUDGE_PROMPT_TEMPLATE.format(
        symptom=scenario.symptom.strip(),
        root_cause=gt.root_cause.strip(),
        causal_chain_numbered=_numbered(gt.causal_chain),
        distractors_numbered=_numbered(gt.distractors),
        required_elements_numbered=_numbered(scenario.required_answer_elements),
        diagnosis_root_cause=diagnosis.root_cause.strip() or "(none given)",
        diagnosis_causal_chain=_numbered(diagnosis.causal_chain) or "(none given)",
        diagnosis_proposed_fix=diagnosis.proposed_fix.strip() or "(none given)",
    )


def _score_from_hits(
    causal_chain_hits: list[bool],
    required_element_hits: list[bool],
    distractor_hits: list[bool],
    rationale: str,
) -> JudgeScore:
    causal_chain_coverage = sum(causal_chain_hits) / len(causal_chain_hits) if causal_chain_hits else 0.0
    required_elements_coverage = sum(required_element_hits) / len(required_element_hits) if required_element_hits else 0.0
    distractor_penalty = 1.0 - (sum(distractor_hits) / len(distractor_hits) if distractor_hits else 0.0) * 0.5
    # Weighting: causal chain and required elements matter most; falling for
    # a distractor multiplicatively discounts the final score rather than
    # being an independent term, so a "right answer wrapped around a wrong
    # distractor claim" still loses real credit.
    overall = (0.6 * causal_chain_coverage + 0.4 * required_elements_coverage) * distractor_penalty
    return JudgeScore(
        causal_chain_coverage=causal_chain_coverage,
        required_elements_coverage=required_elements_coverage,
        distractor_penalty=distractor_penalty,
        overall=round(overall, 4),
        rationale=rationale,
        per_causal_chain_step=causal_chain_hits,
        per_required_element=required_element_hits,
        fell_for_distractor=distractor_hits,
    )


class LLMDiagnosisJudge(DiagnosisJudge):
    """The real judge. `call_model` is any callable str -> str (a thin
    wrapper around e.g. the Anthropic SDK). Swap in a real one when ready:

        from anthropic import Anthropic
        client = Anthropic()
        def call_claude(prompt: str) -> str:
            resp = client.messages.create(
                model="claude-sonnet-5", max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            return resp.content[0].text
        judge = LLMDiagnosisJudge(call_claude)
    """

    def __init__(self, call_model: Callable[[str], str]):
        self._call_model = call_model

    def score(self, scenario: Scenario, diagnosis: Diagnosis) -> JudgeScore:
        prompt = build_judge_prompt(scenario, diagnosis)
        raw = self._call_model(prompt)
        payload = _extract_json(raw)
        return _score_from_hits(
            causal_chain_hits=list(payload["causal_chain_hits"]),
            required_element_hits=list(payload["required_element_hits"]),
            distractor_hits=list(payload["distractor_hits"]),
            rationale=payload.get("rationale", ""),
        )


def _extract_json(raw: str) -> dict:
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError(f"Judge response did not contain a JSON object: {raw!r}")
    return json.loads(match.group(0))


class StubHeuristicJudge(DiagnosisJudge):
    """Deterministic placeholder standing in for LLMDiagnosisJudge. Scores
    each causal_chain step / required_answer_element as a hit if enough of
    its distinctive words appear in the diagnosis text, and each distractor
    as a hit if the diagnosis text asserts it prominently. This is a crude
    lexical proxy for judgment, not judgment -- it will both over- and
    under-credit real diagnoses. Use only to validate the harness plumbing
    end-to-end before a real model is wired in.
    """

    _STOPWORDS = {
        "the", "a", "an", "is", "was", "were", "of", "to", "in", "on", "for",
        "and", "or", "but", "as", "at", "by", "with", "that", "this", "it",
        "its", "be", "are", "not", "no", "so", "if", "then", "than", "from",
        "into", "which", "who", "what", "when", "since", "because", "while",
    }
    _WARNED = False

    def __init__(self, overlap_threshold: float = 0.25):
        self.overlap_threshold = overlap_threshold
        if not StubHeuristicJudge._WARNED:
            warnings.warn(
                "StubHeuristicJudge is a lexical-overlap placeholder, not a "
                "real grader. Scores from it are only meaningful for testing "
                "the harness itself. Wire an LLMDiagnosisJudge before using "
                "results for anything else.",
                stacklevel=2,
            )
            StubHeuristicJudge._WARNED = True

    def _tokens(self, text: str) -> set[str]:
        words = re.findall(r"[a-z0-9_]+", text.lower())
        return {w for w in words if w not in self._STOPWORDS and len(w) > 2}

    def _hit(self, reference: str, diagnosis_text: str) -> bool:
        ref_tokens = self._tokens(reference)
        if not ref_tokens:
            return False
        diag_tokens = self._tokens(diagnosis_text)
        overlap = len(ref_tokens & diag_tokens) / len(ref_tokens)
        return overlap >= self.overlap_threshold

    def score(self, scenario: Scenario, diagnosis: Diagnosis) -> JudgeScore:
        diagnosis_text = " ".join([
            diagnosis.root_cause,
            " ".join(diagnosis.causal_chain),
            diagnosis.proposed_fix,
        ])
        gt = scenario.ground_truth
        causal_chain_hits = [self._hit(step, diagnosis_text) for step in gt.causal_chain]
        required_element_hits = [self._hit(el, diagnosis_text) for el in scenario.required_answer_elements]
        distractor_hits = [self._hit(d, diagnosis_text) for d in gt.distractors]
        rationale = (
            f"[stub heuristic] lexical overlap >= {self.overlap_threshold:.0%} "
            f"against {len(gt.causal_chain)} causal-chain steps, "
            f"{len(scenario.required_answer_elements)} required elements, "
            f"{len(gt.distractors)} distractors."
        )
        return _score_from_hits(causal_chain_hits, required_element_hits, distractor_hits, rationale)


def make_default_judge(call_model: Callable[[str], str] | None = None) -> DiagnosisJudge:
    if call_model is None:
        return StubHeuristicJudge()
    return LLMDiagnosisJudge(call_model)
