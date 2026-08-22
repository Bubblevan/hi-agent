"""Offline runner for validating the grounded RAG mini-benchmark."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from evals.rag.scorer import validate_evidence_quotes
from evals.rag.schema import RAGEvalCase
from retrieval.datasets import load_rag_manifest, resolve_source_path, sha256_file


class RAGDatasetError(ValueError):
    """Raised when a RAG benchmark cannot be loaded or validated."""


def load_cases(path: str | Path) -> list[RAGEvalCase]:
    """Load and schema-validate every non-empty JSONL row."""

    dataset_path = Path(path)
    cases: list[RAGEvalCase] = []
    seen_case_ids: set[str] = set()
    with dataset_path.open(encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            try:
                case = RAGEvalCase.model_validate(json.loads(line))
            except (json.JSONDecodeError, ValidationError) as error:
                raise RAGDatasetError(
                    f"{dataset_path}:{line_number}: invalid case: {error}"
                ) from error
            if case.case_id in seen_case_ids:
                raise RAGDatasetError(
                    f"{dataset_path}:{line_number}: duplicate case_id {case.case_id}"
                )
            seen_case_ids.add(case.case_id)
            cases.append(case)
    return cases


def _extract_pages(path: Path, kind: str) -> list[str]:
    if kind == "markdown":
        return [path.read_text(encoding="utf-8")]

    try:
        import pypdf

        reader = pypdf.PdfReader(str(path))
        return [page.extract_text() or "" for page in reader.pages]
    except ImportError:
        try:
            import pdfplumber
        except ImportError as error:  # pragma: no cover - environment failure
            raise RAGDatasetError(
                "PDF validation requires pypdf or pdfplumber"
            ) from error
        with pdfplumber.open(path) as pdf:
            return [page.extract_text() or "" for page in pdf.pages]


def _source_map(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    sources = manifest["sources"]
    return {source["id"]: source for source in sources}


def validate_dataset(
    cases_path: str | Path,
    manifest_path: str | Path,
    *,
    project_root: str | Path,
) -> list[str]:
    """Return all source, page, quote, and evidence-term violations."""

    cases = load_cases(cases_path)
    manifest = load_rag_manifest(manifest_path)
    sources = _source_map(manifest)
    pages_by_source: dict[str, list[str]] = {}
    errors: list[str] = []

    for case in cases:
        source = sources.get(case.source_id)
        if source is None:
            errors.append(f"{case.case_id}: unknown source_id {case.source_id}")
            continue

        source_path = resolve_source_path(source, project_root=project_root)
        if not source_path.is_file():
            errors.append(f"{case.case_id}: source does not exist: {source_path}")
            continue
        if source_path.stat().st_size != source["bytes"]:
            errors.append(f"{case.case_id}: source byte count does not match manifest")
            continue
        if sha256_file(source_path) != source["sha256"]:
            errors.append(f"{case.case_id}: source sha256 does not match manifest")
            continue

        if case.source_id not in pages_by_source:
            pages_by_source[case.source_id] = _extract_pages(
                source_path,
                source["kind"],
            )
        errors.extend(
            validate_evidence_quotes(case, pages_by_source[case.source_id])
        )

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cases", type=Path)
    parser.add_argument("manifest", type=Path)
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
    )
    args = parser.parse_args()

    try:
        errors = validate_dataset(
            args.cases,
            args.manifest,
            project_root=args.project_root,
        )
    except (RAGDatasetError, ValueError) as error:
        print(f"INVALID: {error}")
        return 1

    if errors:
        print("INVALID")
        print("\n".join(f"- {error}" for error in errors))
        return 1

    print(f"VALID: grounded RAG dataset at {args.cases}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
