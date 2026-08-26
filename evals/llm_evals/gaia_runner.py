"""Run the local GAIA 2023 benchmark with a tool-using Hi-Agent.

This follows the three-layer design from Chapter 12:

* :class:`GAIADataset` loads the current Parquet-backed dataset and resolves
  attachments without allowing paths to escape the GAIA directory.
* :class:`GAIAEvaluator` calls an agent, extracts ``FINAL ANSWER`` and applies
  the chapter's quasi-exact normalization.
* The CLI writes a GAIA JSONL artifact and a local diagnostic report.

The runner is intentionally validation-first.  It can read ``test`` files,
but it never claims accuracy for rows without a public final answer.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from tools.base import MyTool, ToolParameter


SUPPORTED_SPLITS = ("validation", "test")
SUPPORTED_LEVELS = (1, 2, 3)
DEFAULT_SYSTEM_PROMPT = """你是一个能够使用工具解决真实世界问题的通用 AI 助手。

请先理解问题，再决定是否需要工具。需要时可以使用计算器、互联网搜索和
read_attachment 工具。对于附件问题，必须先读取附件再作答；不要凭文件名猜答案。
可以进行多轮工具调用，并核对工具返回结果。

最终必须在单独一行输出：FINAL ANSWER: <最终答案>
FINAL ANSWER 后只放答案，不要追加解释。答案要尽量短，并严格满足题目要求的格式。
"""


@dataclass(frozen=True)
class GAIAItem:
    task_id: str
    question: str
    level: int
    final_answer: str | None
    file_name: str | None
    file_path: str | None
    attachment_path: Path | None


class GAIADataset:
    """Load the local 2023 GAIA split from Parquet metadata."""

    def __init__(
        self,
        root: str | Path,
        *,
        split: str = "validation",
        level: int | None = None,
    ) -> None:
        if split not in SUPPORTED_SPLITS:
            raise ValueError(f"split must be one of {SUPPORTED_SPLITS}, got {split!r}")
        if level is not None and level not in SUPPORTED_LEVELS:
            raise ValueError(f"level must be one of {SUPPORTED_LEVELS}, got {level!r}")
        self.root = Path(root).expanduser().resolve()
        self.split = split
        self.level = level
        self.split_root = (self.root / "2023" / split).resolve()

    @property
    def metadata_path(self) -> Path:
        return self.split_root / "metadata.parquet"

    def load(self) -> list[GAIAItem]:
        if not self.metadata_path.is_file():
            raise FileNotFoundError(f"GAIA metadata not found: {self.metadata_path}")

        try:
            import pyarrow.parquet as parquet
        except ImportError as exc:
            raise ImportError(
                "读取当前 GAIA Parquet 数据需要 pyarrow；请在 hi-agent 环境执行 "
                "uv sync 或 uv add pyarrow。"
            ) from exc

        rows = parquet.read_table(self.metadata_path).to_pylist()
        items = [self._standardize(row) for row in rows]
        if self.level is not None:
            items = [item for item in items if item.level == self.level]
        return items

    def _standardize(self, row: dict[str, Any]) -> GAIAItem:
        task_id = str(row.get("task_id") or "").strip()
        question = str(row.get("Question") or row.get("question") or "").strip()
        if not task_id or not question:
            raise ValueError(f"GAIA row is missing task_id or Question: {row!r}")

        raw_level = row.get("Level", row.get("level", 0))
        try:
            level = int(raw_level)
        except (TypeError, ValueError):
            level = 0

        raw_answer = row.get("Final answer", row.get("final_answer"))
        # Keep the official boundary: test answers are not used for local scoring
        # or copied into diagnostic artifacts, even if a local snapshot contains
        # an answer column.
        final_answer = (
            None
            if self.split == "test" or raw_answer is None
            else str(raw_answer)
        )
        file_name = self._optional_text(row.get("file_name"))
        file_path = self._optional_text(row.get("file_path"))
        attachment_path = self.resolve_attachment(file_path or file_name)

        return GAIAItem(
            task_id=task_id,
            question=question,
            level=level,
            final_answer=final_answer,
            file_name=file_name,
            file_path=file_path,
            attachment_path=attachment_path,
        )

    @staticmethod
    def _optional_text(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def resolve_attachment(self, value: str | None) -> Path | None:
        """Resolve a metadata attachment while enforcing the dataset boundary."""
        if not value:
            return None

        candidate = Path(value)
        if candidate.is_absolute():
            resolved = candidate.resolve()
        elif str(value).replace("\\", "/").startswith("2023/"):
            resolved = (self.root / candidate).resolve()
        else:
            resolved = (self.split_root / candidate).resolve()

        if self.split_root != resolved and self.split_root not in resolved.parents:
            raise ValueError(f"GAIA attachment escapes split root: {value!r}")
        if not resolved.is_file():
            raise FileNotFoundError(f"GAIA attachment not found: {resolved}")
        return resolved


class GAIAAttachmentTool(MyTool):
    """Adapter that exposes one safe attachment reader to MyFunctionCallAgent."""

    name = "read_attachment"
    description = (
        "读取当前 GAIA 题目附带的文件并转换为可阅读文本；支持 PDF、DOCX、PPTX、"
        "XLSX、CSV、JSON、XML、TXT、代码和常见图片。参数 file_name 使用题目提供的文件名。"
    )

    def __init__(self, dataset: GAIADataset, *, max_chars: int = 30000) -> None:
        super().__init__(self.name, self.description)
        self.dataset = dataset
        self.max_chars = max_chars

    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="file_name",
                type="string",
                description="题目提供的附件文件名或相对路径",
                required=True,
            )
        ]

    def run(self, parameters: dict[str, Any]) -> str:
        from retrieval.loaders.markitdown import MarkitdownLoader

        value = parameters.get("file_name") or parameters.get("file_path")
        path = self.dataset.resolve_attachment(str(value) if value else None)
        if path is None:
            return "错误：当前题目没有可读取的附件。"

        try:
            document = MarkitdownLoader().load(
                path,
                user_id="gaia-eval",
                namespace=f"{self.dataset.split}-{self.dataset.level or 'all'}",
            )
        except Exception as exc:
            return f"附件读取失败（{path.name}）：{exc}"

        text = document.text.strip()
        if len(text) > self.max_chars:
            text = text[: self.max_chars] + "\n[附件内容已截断]"
        return f"附件：{path.name}\n格式：{path.suffix.lower()}\n内容：\n{text}"


def build_prompt(item: GAIAItem) -> str:
    attachment = ""
    if item.attachment_path:
        attachment = (
            "\n\n本题有附件："
            f"{item.file_name or item.attachment_path.name}。"
            "如果问题需要附件中的信息，请调用 read_attachment(file_name=...) 读取它。"
        )
    return f"GAIA 任务 ID：{item.task_id}\n\n问题：\n{item.question}{attachment}"


def normalize_answer(answer: str | None) -> str:
    """Apply the normalization described in Chapter 12's GAIA section."""
    if not answer:
        return ""
    answer = answer.strip().strip("[]").strip().lower()
    answer = answer.replace("$", "").replace("%", "")
    answer = answer.replace("€", "").replace("£", "")
    answer = re.sub(r"(?<=\d),(?=\d)", "", answer)
    if "," in answer:
        parts = [normalize_answer(part) for part in answer.split(",")]
        return ",".join(sorted(parts))
    answer = " ".join(answer.split())
    words = answer.split()
    if words and words[0] in {"the", "a", "an"}:
        answer = " ".join(words[1:])
    return answer.rstrip(".,;:!?")


def extract_answer(response: str) -> str:
    """Extract the final answer marker, with a conservative fallback."""
    marker = re.search(r"FINAL ANSWER\s*:\s*(.+?)(?:\r?\n|$)", response, re.I)
    if marker:
        return marker.group(1).strip().strip("[]").strip()

    for pattern in (r"答案\s*[：:]\s*(.+)", r"最终答案\s*[：:]\s*(.+)", r"Answer\s*[：:]\s*(.+)"):
        match = re.search(pattern, response, re.I)
        if match:
            return match.group(1).strip()

    lines = [line.strip() for line in response.splitlines() if line.strip()]
    return lines[-1] if lines else response.strip()


class GAIAEvaluator:
    """Evaluate agent answers and retain per-case evidence."""

    def __init__(
        self,
        items: Iterable[GAIAItem],
        agent_factory: Callable[[], Any],
        *,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        samples: int = 5,
    ) -> None:
        self.items = list(items)
        self.agent_factory = agent_factory
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.samples = samples

    def evaluate(self) -> dict[str, Any]:
        items = self.items if self.samples == 0 else self.items[: self.samples]
        cases: list[dict[str, Any]] = []
        for index, item in enumerate(items, 1):
            started = time.perf_counter()
            response = ""
            error = None
            try:
                agent = self.agent_factory()
                response = str(
                    agent.run(
                        build_prompt(item),
                        temperature=self.temperature,
                        max_tokens=self.max_tokens,
                    )
                )
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"

            predicted = extract_answer(response) if response else ""
            has_answer = item.final_answer is not None and item.final_answer != ""
            valid = (
                has_answer
                and error is None
                and normalize_answer(predicted) == normalize_answer(item.final_answer)
            )
            cases.append(
                {
                    "task_id": item.task_id,
                    "index": index,
                    "level": item.level,
                    "file_name": item.file_name,
                    "predicted": predicted,
                    "expected": item.final_answer if has_answer else None,
                    "normalized_predicted": normalize_answer(predicted),
                    "normalized_expected": normalize_answer(item.final_answer) if has_answer else None,
                    "valid": valid,
                    "scorable": has_answer,
                    "error": error,
                    "response": response,
                    "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                }
            )
            print(f"[{index}/{len(items)}] {item.task_id}: {'PASS' if valid else 'FAIL'}")

        scorable = [case for case in cases if case["scorable"]]
        correct = sum(case["valid"] for case in scorable)
        by_level: dict[str, dict[str, int | float]] = {}
        for level in sorted({case["level"] for case in cases}):
            level_cases = [case for case in scorable if case["level"] == level]
            level_correct = sum(case["valid"] for case in level_cases)
            by_level[str(level)] = {
                "correct": level_correct,
                "total": len(level_cases),
                "accuracy": level_correct / len(level_cases) if level_cases else None,
            }
        return {
            "benchmark": "GAIA 2023",
            "total_samples": len(cases),
            "scorable_samples": len(scorable),
            "correct_samples": correct,
            "accuracy": correct / len(scorable) if scorable else None,
            "by_level": by_level,
            "cases": cases,
        }


def export_jsonl(results: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for case in results["cases"]:
            handle.write(
                json.dumps(
                    {
                        "task_id": case["task_id"],
                        "model_answer": case["predicted"],
                        "reasoning_trace": case["response"],
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a local GAIA 2023 evaluation")
    parser.add_argument("--gaia-root", default=os.getenv("GAIA_PROJECT_ROOT"))
    parser.add_argument("--split", choices=SUPPORTED_SPLITS, default="validation")
    parser.add_argument("--level", type=int, choices=SUPPORTED_LEVELS)
    parser.add_argument("--samples", type=int, default=5, help="0 means all samples")
    parser.add_argument("--model", default=os.getenv("LLM_MODEL_ID"))
    parser.add_argument("--model-label", default="hi-agent-baseline")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--report", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.gaia_root:
        raise SystemExit("请提供 --gaia-root 或设置 GAIA_PROJECT_ROOT")
    if args.samples < 0:
        raise SystemExit("--samples must be >= 0")

    root = Path(args.gaia_root).expanduser().resolve()
    dataset = GAIADataset(root, split=args.split, level=args.level)
    items = dataset.load()

    from agents.functioncall_agent import MyFunctionCallAgent
    from core.llm_client import MyLLMClient
    from tools.builtin.calculator import CalculatorTool
    from tools.builtin.search import SearchTool
    from tools.registry import MyToolRegistry

    llm = MyLLMClient(model=args.model)

    def agent_factory() -> MyFunctionCallAgent:
        registry = MyToolRegistry()
        registry.register_tool(CalculatorTool())
        registry.register_tool(SearchTool())
        registry.register_tool(GAIAAttachmentTool(dataset))
        return MyFunctionCallAgent(
            name="gaia-eval-agent",
            llm=llm,
            tool_registry=registry,
            system_prompt=DEFAULT_SYSTEM_PROMPT,
            max_iterations=8,
        )

    evaluator = GAIAEvaluator(
        items,
        agent_factory,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        samples=args.samples,
    )
    results = evaluator.evaluate()
    label = args.model_label
    level_label = f"level{args.level}" if args.level else "all"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = args.output or root.parent.parent.parent / "artifacts" / f"gaia-{args.split}-{level_label}-{stamp}.jsonl"
    report = args.report or root.parent.parent.parent / "artifacts" / f"gaia-{args.split}-{level_label}-{stamp}.json"
    results.update(
        {
            "model": llm.model,
            "model_label": label,
            "split": args.split,
            "level": args.level,
            "temperature": args.temperature,
            "max_tokens": args.max_tokens,
            "data_root": str(root),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "output_path": str(output),
        }
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    report.parent.mkdir(parents=True, exist_ok=True)
    export_jsonl(results, output)
    report.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    accuracy = results["accuracy"]
    accuracy_text = "N/A" if accuracy is None else f"{accuracy:.2%}"
    print(f"Accuracy: {results['correct_samples']}/{results['scorable_samples']} = {accuracy_text}")
    print(f"GAIA JSONL: {output}")
    print(f"Eval report: {report}")
    return 0 if results["scorable_samples"] == 0 or results["correct_samples"] == results["scorable_samples"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
