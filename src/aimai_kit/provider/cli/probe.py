"""model-probe — measure the same prompt N times across several models.

Why the measurement is shaped this way:

TTFT cannot be measured with `complete`; a single-shot call carries no
information about when the first token arrived. So the N runs go through
STREAMING: the moment the first chunk lands is TTFT, the end of the stream is
total duration. But a provider may not send `usage` on a stream. The fix: one
extra `complete` call AFTER the N streaming runs, and the REAL usage comes
from there.

The price is N+1 calls; the payoff is this column pair — the local tiktoken
estimate next to the provider's reported token count. On Anthropic and Gemini
that drift reaches 10-20% and affects every budget calculation downstream.

The pre-flight budget check runs for every model: a request that exceeds the
window never reaches the provider.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from ..adapters import make_adapter
from ..counting import ContextBudgetExceeded, TokenCounter, budget_guard
from ..determinism import stats_from_outputs
from ..errors import LLMError
from ..pricing import ModelPricing, load_pricing
from ..telemetry import percentiles
from ..types import ChatRequest, Message, Role

__all__ = ["main", "ModelMeasurement", "probe_model", "print_table"]


@dataclass
class ModelMeasurement:
    """Measurement result for a single model. Serializes 1:1 to JSON."""

    spec: str
    provider: str
    model: str
    n: int
    ok: bool = True
    error: str | None = None

    input_tokens_est: int = 0
    input_tokens_actual: int = 0
    output_tokens_actual: int = 0
    cached_tokens: int = 0
    estimate_drift_pct: float | None = None

    cost_usd: str = "0"
    cost_per_1k_usd: str = "0"

    ttft_ms: dict[str, float] = field(default_factory=dict)
    total_ms: dict[str, float] = field(default_factory=dict)

    distinct_outputs: int = 0
    modal_share: float = 0.0
    sample_output: str = ""


def _percentile_dict(values: list[float]) -> dict[str, float]:
    return {f"p{p}": round(v, 1) for p, v in percentiles(values).items()}


def probe_model(
    spec: str,
    prompt: str,
    *,
    n: int,
    max_output_tokens: int,
    system: str | None,
    catalog: dict[str, ModelPricing],
    temperature: float | None = None,
    dry_run: bool = False,
) -> ModelMeasurement:
    """Measure one model. Never raises; failures are written into the result.

    Reason: when two of three models work and the third returns a 401, we do
    not want to lose the whole table. A comparison tool should show as much
    as it can compare.
    """
    client = None
    try:
        client = make_adapter(spec) if not dry_run else None
    except Exception as error:  # noqa: BLE001 - broad catch at the CLI edge
        provider, _, model = spec.partition(":")
        return ModelMeasurement(
            spec=spec,
            provider=provider,
            model=model,
            n=n,
            ok=False,
            error=str(error),
        )

    provider, _, model = spec.partition(":")
    measurement = ModelMeasurement(
        spec=spec,
        provider=client.provider if client else provider,
        model=client.model if client else model,
        n=n,
    )

    req = ChatRequest(
        messages=[Message(role=Role.USER, content=prompt)],
        system=system,
        max_output_tokens=max_output_tokens,
        temperature=temperature,
        operation="probe",
    )

    counter = TokenCounter(measurement.model)
    price = catalog.get(measurement.model)

    # 1) Pre-flight budget check. The window comes from the catalog; when
    #    it is missing the check is not skipped silently, it is reported.
    if price is not None and price.context_window > 0:
        try:
            measurement.input_tokens_est = budget_guard(
                counter,
                req.message_dicts(),
                max_output_tokens,
                price.context_window,
                measurement.model,
            )
        except ContextBudgetExceeded as error:
            measurement.ok = False
            measurement.error = str(error)
            return measurement
    else:
        measurement.input_tokens_est = counter.count_messages(req.message_dicts())
        measurement.error = "window not in catalog; budget check skipped"

    if dry_run:
        return measurement

    # 2) N streaming runs: TTFT and total duration come from here.
    ttfts: list[float] = []
    durations: list[float] = []
    outputs: list[str] = []
    try:
        for _ in range(n):
            t0 = time.monotonic()
            first: float | None = None
            chunks: list[str] = []
            for chunk in client.stream(req):
                if first is None:
                    first = (time.monotonic() - t0) * 1000
                chunks.append(chunk)
            durations.append((time.monotonic() - t0) * 1000)
            if first is not None:
                ttfts.append(first)
            outputs.append("".join(chunks).strip())

        # 3) One `complete` run: the REAL usage comes from here.
        result = client.complete(req)
    except LLMError as error:
        measurement.ok = False
        measurement.error = str(error)
        return measurement

    measurement.ttft_ms = _percentile_dict(ttfts)
    measurement.total_ms = _percentile_dict(durations)

    stability = stats_from_outputs(outputs)
    measurement.distinct_outputs = stability.distinct_outputs
    measurement.modal_share = round(stability.modal_share, 3)
    measurement.sample_output = stability.modal_output[:280]

    measurement.input_tokens_actual = result.usage.input_tokens
    measurement.output_tokens_actual = result.usage.output_tokens
    measurement.cached_tokens = result.usage.cached_input_tokens
    if result.usage.input_tokens:
        drift = (
            (measurement.input_tokens_est - result.usage.input_tokens)
            / result.usage.input_tokens
            * 100
        )
        measurement.estimate_drift_pct = round(drift, 1)

    if price is not None:
        unit = price.cost(
            result.usage.input_tokens,
            result.usage.output_tokens,
            result.usage.cached_input_tokens,
        )
        measurement.cost_usd = f"{unit:.6f}"
        measurement.cost_per_1k_usd = f"{unit * 1000:.2f}"

    return measurement


# --- table output -------------------------------------------------------


def _or_dash(value: Any) -> str:
    return "-" if value is None else f"{value:g}"


COLUMNS = [
    ("model", 28, lambda m: m.model),
    ("in~", 7, lambda m: str(m.input_tokens_est)),
    ("in", 6, lambda m: str(m.input_tokens_actual)),
    ("drift%", 7, lambda m: _or_dash(m.estimate_drift_pct)),
    ("out", 6, lambda m: str(m.output_tokens_actual)),
    ("USD/1k", 8, lambda m: m.cost_per_1k_usd),
    ("TTFT p50", 9, lambda m: _or_dash(m.ttft_ms.get("p50"))),
    ("TTFT p95", 9, lambda m: _or_dash(m.ttft_ms.get("p95"))),
    ("total p50", 9, lambda m: _or_dash(m.total_ms.get("p50"))),
    ("total p95", 9, lambda m: _or_dash(m.total_ms.get("p95"))),
    ("distinct", 8, lambda m: str(m.distinct_outputs)),
    ("modal", 6, lambda m: f"{m.modal_share:.2f}"),
]


def print_table(measurements: list[ModelMeasurement], stream=sys.stdout) -> None:
    header = " ".join(name.ljust(width) for name, width, _ in COLUMNS)
    print(header, file=stream)
    print("-" * len(header), file=stream)
    for m in measurements:
        if not m.ok:
            print(f"{m.model.ljust(28)} ERROR: {m.error}", file=stream)
            continue
        print(
            " ".join(get(m).ljust(width)[:width] for _, width, get in COLUMNS),
            file=stream,
        )
    for m in [x for x in measurements if x.ok and x.error]:
        print(f"  ! {m.model}: {m.error}", file=stream)


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(
        prog="model-probe",
        description="Measure the same prompt N times across several models.",
    )
    parser.add_argument(
        "--prompt", required=True, help="Prompt file path or literal text"
    )
    parser.add_argument(
        "--models",
        nargs="+",
        required=True,
        help="provider:model list (anthropic:claude-opus-5 openai:gpt-5.5)",
    )
    parser.add_argument("-n", type=int, default=5, help="Runs per model")
    parser.add_argument("--max-output", type=int, default=512)
    parser.add_argument("--system", default=None)
    parser.add_argument("--temperature", type=float, default=None)
    parser.add_argument("--pricing", default=None, help="Pricing catalog path")
    parser.add_argument(
        "--json", dest="json_path", default=None, help="JSON output path"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not call the API; only estimate tokens and check the budget",
    )
    args = parser.parse_args(argv)

    path = Path(args.prompt)
    prompt = path.read_text(encoding="utf-8") if path.is_file() else args.prompt
    catalog = load_pricing(args.pricing)

    measurements = [
        probe_model(
            spec,
            prompt,
            n=args.n,
            max_output_tokens=args.max_output,
            system=args.system,
            catalog=catalog,
            temperature=args.temperature,
            dry_run=args.dry_run,
        )
        for spec in args.models
    ]

    print_table(measurements)

    if args.json_path:
        payload = {
            "measured_at": datetime.now(UTC).isoformat(),
            "n": args.n,
            "prompt_excerpt": prompt[:200],
            "dry_run": args.dry_run,
            "measurements": [asdict(m) for m in measurements],
        }
        target = Path(args.json_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        print(f"\nJSON written: {target}", file=sys.stderr)

    return 0 if all(m.ok for m in measurements) else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
