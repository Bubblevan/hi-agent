from pathlib import Path

from evals.data_generation.context_generator import (
    FAMILIES,
    generate_cases,
    serialize_cases,
    write_cases,
)
from evals.data_generation.context_validator import (
    load_cases,
    validate_cases,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_generator_creates_eight_families_and_four_variants():
    cases = generate_cases()

    assert len(cases) == 32
    generated_families = {
        next(
            family
            for family in FAMILIES
            if case.case_id.removeprefix("ctx-generated-").startswith(family + "-")
        )
        for case in cases
    }
    assert generated_families == set(FAMILIES)
    assert len({case.case_id for case in cases}) == 32


def test_generated_cases_are_validated_against_selector_oracle():
    cases = generate_cases()

    assert validate_cases(cases) == []
    assert any(case.expected.outcome == "error" for case in cases)
    assert any(case.expected.dropped_item_ids for case in cases)


def test_generated_cases_round_trip_as_jsonl(tmp_path):
    path = tmp_path / "generated.jsonl"
    cases = generate_cases(variants=1)

    write_cases(path, cases)

    rows = [line for line in path.read_text(encoding="utf-8").splitlines() if line]
    assert len(rows) == len(cases)
    assert serialize_cases(cases).splitlines() == rows


def test_checked_in_generated_fixture_is_valid():
    path = PROJECT_ROOT / "tests" / "fixtures" / "context_contract_cases.generated.jsonl"

    cases = load_cases(path)

    assert len(cases) == 32
    assert validate_cases(cases) == []
