"""The plain-language formula and worked examples every student can read.

Built from the current parameters and contains no one's hours.
"""

from app.commitments import PER_TYPE_MAX, STEP, TOTAL_MAX, adjust, factor_for
from app.models import Explainer, FactorRow, HourLimits, CommitmentType, WorkedExample
from app.store import COMMITMENT_TYPES, TYPE_KEYS, AdjustmentSettings

LABELS = dict(COMMITMENT_TYPES)


def _hours(hours: dict[str, float]) -> str:
    parts = [f"{value:g} {LABELS[key].lower()}" for key, value in hours.items() if value]
    return ", ".join(parts) if parts else "no commitments"


def _example(title: str, raw: float, hours: dict[str, float], params: AdjustmentSettings) -> WorkedExample:
    full = {key: hours.get(key, 0.0) for key in TYPE_KEYS}
    result = adjust(raw, full, params)
    steps = [
        f"Weighted hours: {result.weighted_total:g} ({_hours(hours)}, each type counted at its weight).",
        f"Factor: 1 + {params.rate:g} × {result.weighted_total:g}"
        f" = {1 + params.rate * result.weighted_total:.2f}"
        + (f", held at the cap of {params.cap:.2f}." if 1 + params.rate * result.weighted_total > params.cap else "."),
        f"Adjusted score: {raw:g} × {result.factor:.2f} = {raw * result.factor:.1f}"
        + (", shown as 100 because scores stop at 100." if result.capped else "."),
    ]
    return WorkedExample(
        title=title, raw_score=raw, hours=full, weighted_hours=result.weighted_total,
        factor=result.factor, adjusted_score=result.adjusted, capped=result.capped, steps=steps,
    )


def build_explainer(params: AdjustmentSettings) -> Explainer:
    cap_hours = (params.cap - 1) / params.rate if params.rate > 0 else 0.0
    table_hours = sorted({0.0, 10.0, 20.0, round(cap_hours, 1)})
    return Explainer(
        formula=[
            "Raw score = the sum, over criteria, of each criterion's weight × your percentage on it.",
            "Weighted hours = the sum, over work, child care and elder care, of the type's weight × your weekly hours.",
            "Factor = the smaller of 1 + rate × weighted hours, and the cap.",
            "Adjusted score = the smaller of 100 and raw score × factor.",
        ],
        types=[CommitmentType(key=key, label=label) for key, label in COMMITMENT_TYPES],
        type_weights={key: params.type_weights.get(key, 1.0) for key in TYPE_KEYS},
        rate=params.rate,
        cap=params.cap,
        limits=HourLimits(step=STEP, per_type_max=PER_TYPE_MAX, total_max=TOTAL_MAX),
        factor_table=[FactorRow(weighted_hours=h, factor=factor_for(h, params)) for h in table_hours],
        examples=[
            _example("A strong week with a job and child care", 80, {"work": 12, "childcare": 6}, params),
            _example("A score that reaches 100", 92, {"work": 20}, params),
            _example("Where the factor stops", 70, {"work": 40}, params),
        ],
        rules=[
            "Entering commitments is optional. Without an approved baseline the factor is 1.00.",
            "The factor never goes above the cap, whatever hours are entered.",
            "Scores stop at 100. A breakdown says when a score was capped.",
            "A criterion with no entry for a week is left out and the other weights are rescaled. It is not scored as zero.",
            "A window of several weeks averages the weekly adjusted scores, so each week's factor and cap apply to that week only.",
            "Students level on adjusted score are ordered by raw score, then by attendance, then homework. Any still level share a rank.",
            "Classmates see only your adjusted score and rank, never your hours, factor or raw score.",
        ],
    )
