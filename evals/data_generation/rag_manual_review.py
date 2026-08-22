"""Apply the human review decisions for the first frozen PDF candidate batch."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from evals.data_generation.rag_generator import write_cases, write_review_queue
from evals.data_generation.rag_validator import validate_candidates
from evals.rag.runner import _extract_pages


def evidence(page: int, *quotes: str) -> list[dict[str, Any]]:
    return [{"page": page, "quote": quote} for quote in quotes]


CORRECTIONS: dict[str, dict[str, Any]] = {
    "hello-agents-sample-paper-002": {
        "gold_evidence": evidence(1, "from 0.95006 to 0.97011"),
    },
    "hello-agents-sample-paper-005": {
        "gold_evidence": evidence(
            1,
            "the E-SEModule combines channel and spatial attention",
            "small",
            "low-contrast",
        ),
    },
    "hello-agents-sample-paper-006": {
        "gold_evidence": evidence(
            1,
            "recall by 19.1%",
            "from 0.7985 to 0.98964",
        ),
    },
    "hello-agents-sample-paper-008": {
        "answer_type": "fact",
        "should_abstain": False,
    },
    "hello-agents-2-1": {"answer_type": "fact"},
    "hello-agents-2-2": {
        "answer_type": "mechanism",
        "gold_evidence": evidence(
            2,
            "fixed receptive field",
            "adaptive sampling offsets",
            "weighted sampling mechanisms",
            "dynamically adjusting",
            "shape and size",
        ),
    },
    "hello-agents-2-3": {
        "answer_type": "mechanism",
        "expected_terms": [
            "dynamically modify",
            "receptive field",
            "overcoming the limitations",
            "fixed receptive fields",
        ],
        "gold_evidence": evidence(
            2,
            "dynamically modify the receptive field",
            "overcoming the limitations",
            "fixed receptive fields",
        ),
    },
    "hello-agents-2-4": {
        "gold_evidence": evidence(
            2,
            "Backbone, Neck, and Head. The Backbone employs the C2f",
        ),
    },
    "hello-agents-2-5": {
        "expected_terms": [
            "Neck",
            "PAFPN",
            "multi-level",
            "feature representation",
            "Head",
            "decoupled task optimization",
            "classification",
            "bounding box regression",
        ],
        "gold_evidence": evidence(
            2,
            "The Neck utilizes",
            "PAFPN, a fusion of FPN and PAN, to strengthen multi-level",
            "feature representation",
            "The Head adopts a decoupled task optimization strategy",
            "separately refining classification",
            "bounding box regression",
        ),
    },
    "hello-agents-2-6": {
        "gold_evidence": evidence(
            2,
            "Mosaic data",
            "augmentation further enhances small object detection",
        ),
    },
    "hello-agents-2-7": {
        "answer_type": "abstention",
        "answerable_from": "not_answerable",
    },
    "hello-agents-2-8": {
        "question": "What percentage improvements does YOLOv8-BFDS achieve over the original YOLOv8 in precision, recall, mAP50, and mAP50-95?",
        "answer_type": "comparison",
        "answerable_from": "single_page",
        "expected_terms": ["2.1%", "19.1%", "14.2%", "34.5%"],
        "should_abstain": False,
        "gold_evidence": evidence(
            1,
            "by 2.1%",
            "by 19.1%",
            "mAP50 by 14.2%",
            "mAP50-95 by 34.5%",
        ),
    },
    "hello-agents-sample-paper-3-1": {
        "answer_type": "mechanism",
        "expected_terms": [
            "DCNv2",
            "deformations",
            "occlusion",
            "complex backgrounds",
            "robustness",
            "detection accuracy",
        ],
        "gold_evidence": evidence(
            3,
            "DCNv2 module",
            "robustness and detection accuracy",
            "deformations",
            "object occlusions",
            "complex backgrounds",
        ),
    },
    "hello-agents-sample-paper-3-2": {
        "answer_type": "mechanism",
        "gold_evidence": evidence(
            3,
            "E-SEModule",
            "SE module",
            "fully connected layers",
            "convolutional layers",
            "dynamically adjust",
            "channel-wise weights",
        ),
    },
    "hello-agents-sample-paper-3-3": {
        "question": "What does Precision measure according to the paper?",
        "answer_type": "fact",
        "expected_terms": ["proportion", "predicted as positive"],
        "gold_evidence": evidence(
            3,
            "Precision measures the proportion",
            "predicted as positive",
        ),
    },
    "hello-agents-sample-paper-3-4": {
        "gold_evidence": evidence(3, "is an NVIDIA GeForce RTX 4060"),
    },
    "hello-agents-sample-paper-3-5": {
        "expected_terms": ["IoU=0.5", "0.5 to 0.95", "step size of 0.05"],
        "gold_evidence": evidence(
            3,
            "mAP50 (mean Average Precision at IoU=0.5)",
            "thresholds from 0.5 to 0.95",
            "step size of 0.05",
        ),
    },
    "hello-agents-sample-paper-3-6": {
        "answer_type": "mechanism",
        "expected_terms": ["top-down", "lower-level", "contextual information", "higher-level"],
        "gold_evidence": evidence(
            3,
            "top-down",
            "lower-level",
            "contextual information",
            "higher-level",
        ),
    },
    "hello-agents-sample-paper-3-7": {
        "gold_evidence": evidence(
            3,
            "The Python 3.10",
            "PyTorch 2.5.0 framework",
        ),
    },
    "hello-agents-sample-paper-3-8": {
        "gold_evidence": evidence(3, "Concat_BiFPN employs feature concatenation"),
    },
    "hello-agents-sample-paper-3-9": {
        "gold_evidence": evidence(
            3,
            "Intel(R) Core(TM) i7-13650HX 2.60 GHz",
            "24GB of",
        ),
    },
    "hello-agents-sample-paper-4-1": {"answer_type": "fact"},
    "hello-agents-sample-paper-4-2": {"answer_type": "fact"},
    "hello-agents-sample-paper-4-3": {
        "answer_type": "fact",
        "gold_evidence": evidence(4, "34.5%"),
    },
    "hello-agents-sample-paper-4-4": {"answer_type": "fact"},
    "hello-agents-sample-paper-4-5": {"answer_type": "fact"},
    "hello-agents-sample-paper-4-6": {
        "expected_terms": ["0.99149", "0.94707"],
    },
    "hello-agents-sample-paper-4-7": {
        "answer_type": "fact",
        "gold_evidence": evidence(4, "recall of 0.7985"),
    },
    "hello-agents-sample-paper-4-8": {
        "answer_type": "comparison",
        "gold_evidence": evidence(
            4,
            "YOLOv5",
            "YOLOv9",
            "balanced precision and recall",
        ),
    },
    "hello-agents-sample-paper-4-9": {"answer_type": "fact"},
    "hello-agents-sample-paper-4-10": {"answer_type": "fact"},
    "hello-agents-sample-paper-4-11": {"answer_type": "fact"},
    "hello-agents-sample-paper-4-12": {"answer_type": "fact"},
    "hello-agents-sample-paper-5-1": {"answer_type": "fact"},
    "hello-agents-sample-paper-5-2": {
        "expected_terms": ["0.98314", "0.98156"],
    },
    "hello-agents-sample-paper-5-3": {"answer_type": "fact"},
    "hello-agents-sample-paper-5-4": {
        "answer_type": "fact",
        "gold_evidence": evidence(5, "19.1% in recall"),
    },
    "hello-agents-sample-paper-5-5": {
        "answer_type": "fact",
        "gold_evidence": evidence(5, "BiFPN and DSConv"),
    },
    "hello-agents-sample-paper-5-6": {
        "answer_type": "fact",
        "gold_evidence": evidence(5, "0.83604"),
    },
    "hello-agents-sample-paper-5-7": {
        "answer_type": "fact",
        "gold_evidence": evidence(5, "2.1%"),
    },
    "hello-agents-sample-paper-5-9": {"answer_type": "fact"},
    "hello-agents-sample-paper-5-10": {"answer_type": "fact"},
}


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def apply_corrections(review_path: Path) -> list[dict[str, Any]]:
    corrected: list[dict[str, Any]] = []
    for row in load_jsonl(review_path):
        candidate = row["candidate"]
        if not isinstance(candidate, dict):
            raise ValueError(f"candidate {row['candidate_index']} is not an object")
        case_id = candidate["case_id"]
        if case_id not in CORRECTIONS:
            raise ValueError(f"missing manual correction for {case_id}")
        updated = dict(candidate)
        updated.update(CORRECTIONS[case_id])
        corrected.append(updated)
    return corrected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--accepted", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--review-output", type=Path, required=True)
    parser.add_argument("--source-id", required=True)
    args = parser.parse_args()

    candidates = load_jsonl(args.accepted) + apply_corrections(args.review)
    pages = _extract_pages(args.source, "pdf")
    report = validate_candidates(candidates, pages, source_id=args.source_id)
    write_cases(args.output, report.accepted)
    write_review_queue(args.review_output, report.review_queue)
    print(
        f"accepted={len(report.accepted)} review={len(report.review_queue)} "
        f"output={args.output}"
    )
    if report.review_queue:
        for item in report.review_queue:
            print(f"- {item.candidate_index}: {'; '.join(item.errors)}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
