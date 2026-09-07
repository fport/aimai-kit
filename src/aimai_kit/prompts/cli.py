"""prompt-lab — run / extract / eval.

`eval` is the command this package earns its keep with: it runs one prompt
version and one schema against the golden set and produces four numbers. The
figures in the docs come from this output, not from hand-editing a table.

Field accuracy is printed in ASCENDING order, weakest field first. The reason
is practical — the first thing you see when you open the table should be what
to work on next. An average would mislead: nine fields at 98% and one at 20%
average out to 90%, and that one field produces wrong data every day in
production.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from ..provider.client import LLMClient
from ..provider.counting import TokenCounter
from ..provider.pricing import ModelPricing, load_pricing
from ..provider.telemetry import UsageCollector, UsageRecord
from ..provider.types import ChatResult, JsonSchemaSpec
from .grounding import verify_citations
from .pipeline import build_request
from .registry import PromptRegistry
from .schemas import ContractSummary, ContractSummaryV1, strict_json_schema
from .structured import SchemaBindingFailed, generate_structured
from .stub import StubExtractor

__all__ = ["main", "run_eval", "EvalResult", "make_client"]

SCHEMAS = {"v1": ContractSummaryV1, "v2": ContractSummary}

# Fields compared against the golden set. `risk_rationale` is free text, so it
# is scored as present/absent rather than exact-match: expecting the model to
# reproduce our sentence would measure memorization, not accuracy.
COMPARED_FIELDS = (
    "parties",
    "start_date",
    "end_date",
    "amount_minor",
    "currency",
    "termination_notice_days",
    "auto_renewal",
    "jurisdiction",
    "risk_level",
    "risk_rationale",
)


def make_client(spec: str) -> LLMClient:
    """'stub' or 'provider:model'."""
    if spec == "stub":
        return StubExtractor()
    from ..provider.adapters import make_adapter

    return make_adapter(spec)


def _matches(name: str, expected: Any, actual: Any) -> bool:
    if name == "parties":
        return {p.strip().casefold() for p in (expected or [])} == {
            p.strip().casefold() for p in (actual or [])
        }
    if name == "risk_rationale":
        return bool((expected or "").strip()) == bool((actual or "").strip())
    return expected == actual


@dataclass
class EvalResult:
    prompt_ref: str = ""
    schema: str = "v2"
    schema_fingerprint: str = ""
    model: str = ""
    provider: str = ""
    document_count: int = 0
    first_try_pass_rate: float = 0.0
    mean_attempts: float = 0.0
    invalid_count: int = 0
    grounding_ratio: float = 0.0
    grounding_drop: bool = True
    input_tokens_p50: int = 0
    cost_per_doc_usd: str = "0"
    prefix_signature: str = ""
    pricing_model: str = ""
    field_accuracy: dict[str, float] = field(default_factory=dict)
    weakest_field: str = ""
    edge_case_failures: dict[str, list[str]] = field(default_factory=dict)


def _usage_record(
    result: ChatResult,
    price: ModelPricing | None,
    attempt: int,
    prompt_ref: str,
    schema_fingerprint: str = "",
) -> UsageRecord:
    return UsageRecord(
        provider=result.provider,
        model=result.model,
        operation="eval",
        input_tokens=result.usage.input_tokens,
        output_tokens=result.usage.output_tokens,
        cost_usd=(
            price.cost(result.usage.input_tokens, result.usage.output_tokens)
            if price
            else Decimal(0)
        ),
        prompt_ref=prompt_ref,
        schema_fingerprint=schema_fingerprint or None,
        attempt=attempt,
    )


def run_eval(
    client: LLMClient,
    dataset_path: Path,
    *,
    prompt_key: str,
    schema_name: str = "v2",
    registry: PromptRegistry | None = None,
    catalog: dict[str, ModelPricing] | None = None,
    max_attempts: int = 3,
    window: int = 200_000,
    limit: int | None = None,
    grounding_drop: bool = True,
    pricing_model: str | None = None,
) -> EvalResult:
    """Measure against the golden set.

    `pricing_model` multiplies the token profile by ANOTHER model's prices.
    Running with the stub, it answers "what would this prompt cost per
    document on claude-opus-5?" — useful for budgeting before a real run. The
    token counts are the stub's, the prices are the model's; say so in the
    table.
    """
    registry = registry or PromptRegistry("prompts")
    catalog = catalog or {}
    schema = SCHEMAS[schema_name]
    schema_fingerprint = JsonSchemaSpec(
        schema.__name__, strict_json_schema(schema)
    ).fingerprint

    raw = json.loads(dataset_path.read_text(encoding="utf-8"))
    records = raw["records"][:limit] if limit else raw["records"]

    collector = UsageCollector()
    counter = TokenCounter(getattr(client, "model", "gpt-4o"))
    price = catalog.get(pricing_model or getattr(client, "model", ""))

    attempts: list[int] = []
    input_tokens: list[int] = []
    grounding_ratios: list[float] = []
    correct: dict[str, int] = dict.fromkeys(COMPARED_FIELDS, 0)
    measured: dict[str, int] = dict.fromkeys(COMPARED_FIELDS, 0)
    invalid = 0
    edge_failures: dict[str, list[str]] = {}
    prompt_ref = ""
    signature = ""

    for record in records:
        built = build_request(
            registry,
            prompt_key,
            record["document"],
            doc_id=record["id"],
            schema=schema,
            window=window,
            operation="eval",
        )
        prompt_ref, signature = str(built.ref), built.prefix_signature
        input_tokens.append(counter.count_messages(built.req.message_dicts()))

        try:
            repaired = generate_structured(
                client, built.req, schema, max_attempts=max_attempts
            )
        except SchemaBindingFailed:
            invalid += 1
            attempts.append(max_attempts)
            continue

        attempts.append(repaired.attempts)
        for result in repaired.results:
            collector(
                _usage_record(
                    result, price, repaired.attempts, prompt_ref, schema_fingerprint
                )
            )

        value, grounding = verify_citations(
            repaired.value, record["document"], drop=grounding_drop
        )
        grounding_ratios.append(grounding.ratio)

        actual = value.model_dump(mode="json")
        failed_fields: list[str] = []
        for name in COMPARED_FIELDS:
            if name not in record["expected"]:
                continue
            measured[name] += 1
            if _matches(name, record["expected"][name], actual.get(name)):
                correct[name] += 1
            else:
                failed_fields.append(name)

        if record.get("edge_case") and failed_fields:
            edge_failures[record["edge_case"]] = failed_fields

    accuracy = {
        name: round(correct[name] / measured[name], 3)
        for name in COMPARED_FIELDS
        if measured[name]
    }
    ordered = dict(sorted(accuracy.items(), key=lambda kv: kv[1]))

    return EvalResult(
        prompt_ref=prompt_ref,
        schema=schema_name,
        schema_fingerprint=schema_fingerprint,
        model=getattr(client, "model", "?"),
        provider=getattr(client, "provider", "?"),
        document_count=len(records),
        first_try_pass_rate=(
            round(sum(a == 1 for a in attempts) / len(attempts), 3) if attempts else 0.0
        ),
        mean_attempts=round(statistics.fmean(attempts), 2) if attempts else 0.0,
        invalid_count=invalid,
        grounding_ratio=(
            round(statistics.fmean(grounding_ratios), 3) if grounding_ratios else 0.0
        ),
        grounding_drop=grounding_drop,
        input_tokens_p50=int(statistics.median(input_tokens)) if input_tokens else 0,
        cost_per_doc_usd=(
            f"{collector.total_cost / len(records):.6f}" if records else "0"
        ),
        prefix_signature=signature,
        pricing_model=pricing_model or "",
        field_accuracy=ordered,
        weakest_field=next(iter(ordered), ""),
        edge_case_failures=edge_failures,
    )


# --- commands -----------------------------------------------------------


def _read_document(path: str) -> str:
    target = Path(path)
    if not target.is_file():
        raise SystemExit(f"Input file not found: {path}")
    return target.read_text(encoding="utf-8")


def cmd_run(args) -> int:
    registry = PromptRegistry(args.prompts)
    document = _read_document(args.input)
    built = build_request(
        registry,
        args.prompt,
        document,
        window=args.window,
        max_output_tokens=args.max_output,
        operation="run",
        max_words=args.max_words,
    )
    client = make_client(args.model)
    result = client.complete(built.req)

    print(f"prompt_ref  : {built.ref}")
    print(f"prefix sig  : {built.prefix_signature}")
    print(f"model       : {result.provider}:{result.model}")
    print(
        f"tokens      : in {result.usage.input_tokens} / "
        f"out {result.usage.output_tokens} / "
        f"cached {result.usage.cached_input_tokens}"
    )
    print(f"budget      : {built.report.summary()}")
    for line in built.report.lines():
        print(f"  {line}")
    print("\n--- answer ---")
    print(result.text)
    return 0


def cmd_extract(args) -> int:
    registry = PromptRegistry(args.prompts)
    document = _read_document(args.input)
    schema = SCHEMAS[args.schema]
    built = build_request(
        registry,
        args.prompt,
        document,
        schema=schema,
        window=args.window,
        max_output_tokens=args.max_output,
        operation="extract",
    )
    client = make_client(args.model)
    repaired = generate_structured(
        client, built.req, schema, max_attempts=args.max_attempts
    )
    value, grounding = verify_citations(repaired.value, document)

    print(f"prompt_ref  : {built.ref}")
    print(f"attempts    : {repaired.attempts}")
    print(f"grounding   : {grounding.ratio:.0%}")
    for line in grounding.lines():
        print(f"  {line}")
    if grounding.dropped:
        print(f"  DROPPED   : {', '.join(grounding.dropped)}")
    print("\n--- output ---")
    print(json.dumps(value.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0


def cmd_eval(args) -> int:
    result = run_eval(
        make_client(args.model),
        Path(args.dataset),
        prompt_key=args.prompt,
        schema_name=args.schema,
        registry=PromptRegistry(args.prompts),
        catalog=load_pricing(args.pricing) if args.pricing else {},
        max_attempts=args.max_attempts,
        window=args.window,
        limit=args.limit,
        grounding_drop=not args.no_grounding_drop,
        pricing_model=args.pricing_model,
    )

    print(
        f"prompt_ref            : {result.prompt_ref}  "
        f"(schema {result.schema}+{result.schema_fingerprint})"
    )
    print(f"model                 : {result.provider}:{result.model}")
    print(f"documents             : {result.document_count}")
    print(f"first-try pass rate   : {result.first_try_pass_rate:.1%}")
    print(f"mean attempts         : {result.mean_attempts}")
    print(f"never valid           : {result.invalid_count}")
    print(f"grounding ratio       : {result.grounding_ratio:.1%}")
    print(f"input tokens (p50)    : {result.input_tokens_p50}")
    suffix = f" (at {result.pricing_model} prices)" if result.pricing_model else ""
    print(f"cost / document (USD) : {result.cost_per_doc_usd}{suffix}")
    print("\nfield accuracy (weakest first):")
    for name, ratio in result.field_accuracy.items():
        bar = "#" * int(ratio * 20)
        print(f"  {name:<26} {ratio:>6.1%}  {bar}")
    if result.edge_case_failures:
        print("\nfields that failed on edge cases:")
        for case, fields in sorted(result.edge_case_failures.items()):
            print(f"  {case:<22} -> {', '.join(fields)}")

    if args.json_path:
        target = Path(args.json_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(
                {"ran_at": datetime.now(UTC).isoformat(), **asdict(result)},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\nJSON written: {target}", file=sys.stderr)

    # CI gate: the threshold comes from your own data. If the weakest field
    # falls below it the run fails, so a prompt or schema change cannot break
    # the most fragile field silently.
    if args.min_field_accuracy is not None and result.field_accuracy:
        lowest = min(result.field_accuracy.values())
        if lowest < args.min_field_accuracy:
            print(
                f"\nTHRESHOLD FAILED: weakest field '{result.weakest_field}' "
                f"{lowest:.1%} < {args.min_field_accuracy:.1%}",
                file=sys.stderr,
            )
            return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(prog="prompt-lab")
    parser.add_argument("--prompts", default="prompts", help="Prompt directory")
    parser.add_argument("--model", default="stub", help="stub | provider:model")
    parser.add_argument("--window", type=int, default=200_000)
    parser.add_argument("--max-output", type=int, default=2048)
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="Run a prompt and report the budget")
    p_run.add_argument("--prompt", default="summarize@v2")
    p_run.add_argument("--input", required=True)
    p_run.add_argument("--max-words", type=int, default=180)
    p_run.set_defaults(fn=cmd_run)

    p_extract = sub.add_parser("extract", help="Extract a ContractSummary")
    p_extract.add_argument("--prompt", default="extract_contract@v2")
    p_extract.add_argument("--input", required=True)
    p_extract.add_argument("--schema", choices=list(SCHEMAS), default="v2")
    p_extract.add_argument("--max-attempts", type=int, default=3)
    p_extract.set_defaults(fn=cmd_extract)

    p_eval = sub.add_parser("eval", help="Measure against the golden set")
    p_eval.add_argument("--prompt", default="extract_contract@v2")
    p_eval.add_argument("--dataset", default="evals/golden_set/contracts.json")
    p_eval.add_argument("--schema", choices=list(SCHEMAS), default="v2")
    p_eval.add_argument("--max-attempts", type=int, default=3)
    p_eval.add_argument("--limit", type=int, default=None)
    p_eval.add_argument("--pricing", default=None)
    p_eval.add_argument("--json", dest="json_path", default=None)
    p_eval.add_argument("--min-field-accuracy", type=float, default=None)
    p_eval.add_argument(
        "--no-grounding-drop",
        action="store_true",
        help=(
            "Report ungrounded fields instead of nulling them. Used to "
            "separate 'how much of the drop came from the schema' from 'how "
            "much came from grounding' when comparing schema versions."
        ),
    )
    p_eval.add_argument(
        "--pricing-model",
        default=None,
        help=(
            "Multiply the token profile by this model's prices (cost "
            "projection for a stub run). Example: claude-opus-5"
        ),
    )
    p_eval.set_defaults(fn=cmd_eval)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
