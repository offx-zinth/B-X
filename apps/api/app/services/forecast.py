"""Forecast registry: predictive models as pluggable LLM tools.

A forecasting model estimates what may happen; simulation evaluates what
follows from stated conditions. Forecasts become *inputs* to simulation
(e.g. demand forecast -> arrival_rate), never replacements for it.

Registry entries: {name, version, inputs, outputs, metrics}. The LLM decides
when a forecaster is appropriate and calls it via the `forecast` AI tool;
results are recorded with model version + inputs for traceability.
"""
from __future__ import annotations
from datetime import datetime, timezone

_REGISTRY: dict[str, dict] = {}


def register(name: str, version: str = "1.0", inputs: list[str] | None = None,
             outputs: list[str] | None = None, metrics: dict | None = None,
             fn=None) -> dict:
    rec = {"name": name, "version": version, "inputs": inputs or [],
           "outputs": outputs or [], "metrics": metrics or {},
           "registered_at": datetime.now(timezone.utc).isoformat()}
    if fn is not None:
        rec["_fn"] = fn
    _REGISTRY[name] = rec
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def list_models() -> list[dict]:
    return [{k: v for k, v in r.items() if not k.startswith("_")}
            for r in _REGISTRY.values()]


def _moving_average(series: list[float], horizon: int) -> list[float]:
    if not series:
        return [0.0] * horizon
    window = series[-min(7, len(series)):]
    avg = sum(window) / len(window)
    return [round(avg, 2)] * horizon


def forecast_moving_average(series: list[float], horizon: int = 30) -> dict:
    horizon = max(1, min(int(horizon or 30), 365))
    vals = [float(v) for v in (series or []) if isinstance(v, (int, float))]
    preds = _moving_average(vals, horizon)
    return {"method": "moving_average", "horizon": horizon,
            "predictions": preds, "based_on_points": len(vals)}


def run(name: str, series: list[float] | None = None, horizon: int = 30,
        target: str = "") -> dict:
    """Run a registered forecaster. Unknown names fall back to moving_average
    so the tool stays usable before custom models are registered."""
    rec = _REGISTRY.get(name)
    version = rec["version"] if rec else "1.0-baseline"
    fn = rec.get("_fn") if rec and "_fn" in rec else None
    if fn is not None:
        try:
            out = fn(series or [], horizon)
            return {"model": name, "version": version, "target": target,
                    "horizon": horizon, **out}
        except Exception as e:
            return {"model": name, "version": version, "target": target,
                    "error": f"{type(e).__name__}: {e}"}
    out = forecast_moving_average(series or [], horizon)
    return {"model": name or "moving_average", "version": version,
            "target": target, **out}


# Baseline forecaster available without any training data or config.
register("moving_average", version="1.0-baseline",
         inputs=["series", "horizon"], outputs=["predictions"],
         metrics={"type": "baseline"})
register("demand_forecast", version="1.0-baseline",
         inputs=["series", "horizon"], outputs=["predictions"],
         metrics={"type": "baseline"})
register("duration_forecast", version="1.0-baseline",
         inputs=["series", "horizon"], outputs=["predictions"],
         metrics={"type": "baseline"})
