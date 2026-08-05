"""
app/services/metrics_analyzer_service.py

Same statistical engine as Backend/API/testing_folder/metrics_analyzer.py
— bootstrap_ci, cohen_d, wilcoxon_srtest, spearman_rho, describe, and the
BenchmarkAnalyzer report generator are all unchanged pure-Python logic.

The only structural change: the old BenchmarkStore exposed everything as
@staticmethod (`BenchmarkStore.load_run(run_id)`), which meant this file
called it without ever knowing where `BENCHMARK_RESULTS_DIR` was actually
configured. Now `BenchmarkAnalyzer` takes a `BenchmarkStore` *instance*
(constructed from Settings in dependencies.py) as a constructor argument.
"""
from __future__ import annotations

import math
import random
import time
from typing import Any, Dict, List, Tuple

from app.services.benchmark_service import BenchmarkStore

try:
    from scipy import stats as _scipy_stats
    _SCIPY = True
except ImportError:
    _SCIPY = False


def _mean(v: List[float]) -> float:
    return sum(v) / len(v) if v else 0.0


def _variance(v: List[float], ddof: int = 1) -> float:
    if len(v) < 2:
        return 0.0
    m = _mean(v)
    return sum((x - m) ** 2 for x in v) / (len(v) - ddof)


def _std(v: List[float], ddof: int = 1) -> float:
    return math.sqrt(_variance(v, ddof))


def _median(v: List[float]) -> float:
    s = sorted(v)
    n = len(s)
    return (s[n // 2 - 1] + s[n // 2]) / 2 if n % 2 == 0 else s[n // 2]


def _percentile(v: List[float], p: float) -> float:
    s = sorted(v)
    idx = (len(s) - 1) * p / 100
    lo, hi = int(idx), math.ceil(idx)
    return s[lo] + (s[hi] - s[lo]) * (idx - lo) if lo != hi else s[lo]


def describe(v: List[float]) -> Dict[str, float]:
    if not v:
        return {k: 0.0 for k in ("n", "mean", "std", "median", "iqr", "min", "max")}
    return {
        "n": float(len(v)), "mean": round(_mean(v), 4), "std": round(_std(v), 4),
        "median": round(_median(v), 4), "iqr": round(_percentile(v, 75) - _percentile(v, 25), 4),
        "min": round(min(v), 4), "max": round(max(v), 4),
    }


def bootstrap_ci(v: List[float], n_boot: int = 1_000, ci: float = 0.95, seed: int = 42) -> Tuple[float, float]:
    rng = random.Random(seed)
    n = len(v)
    means = sorted(_mean([rng.choice(v) for _ in range(n)]) for _ in range(n_boot))
    alpha = (1 - ci) / 2
    return (round(means[int(alpha * n_boot)], 4), round(means[int((1 - alpha) * n_boot)], 4))


def cohen_d(x: List[float], y: List[float]) -> float:
    n1, n2 = len(x), len(y)
    if n1 < 2 or n2 < 2:
        return 0.0
    pooled_var = ((_variance(x) * (n1 - 1) + _variance(y) * (n2 - 1)) / (n1 + n2 - 2))
    pooled_std = math.sqrt(pooled_var) if pooled_var > 0 else 1e-9
    return round((_mean(y) - _mean(x)) / pooled_std, 4)


def wilcoxon_srtest(x: List[float], y: List[float]) -> Dict[str, Any]:
    if len(x) != len(y):
        return {"p_value": None, "error": "Unequal sample lengths"}
    diffs = [yi - xi for xi, yi in zip(x, y)]
    diffs = [d for d in diffs if d != 0]
    if not diffs:
        return {"statistic": 0.0, "p_value": 1.0, "method": "sign_test", "significant": False}

    if _SCIPY:
        stat, p = _scipy_stats.wilcoxon(
            [yi - xi for xi, yi in zip(x, y)], alternative="greater", zero_method="zsplit",
        )
        return {"statistic": round(float(stat), 4), "p_value": round(float(p), 6), "method": "wilcoxon_scipy", "significant": float(p) < 0.05}

    pos = sum(1 for d in diffs if d > 0)
    n = len(diffs)
    from math import comb
    p_sign = sum(comb(n, k) * (0.5 ** n) for k in range(pos, n + 1))
    return {"statistic": float(pos), "p_value": round(p_sign, 6), "method": "sign_test_fallback", "significant": p_sign < 0.05}


def spearman_rho(x: List[float], y: List[float]) -> float:
    n = len(x)
    if n < 2:
        return 0.0

    def _ranks(v):
        sv = sorted(range(n), key=lambda i: v[i])
        rank = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j < n and v[sv[j]] == v[sv[i]]:
                j += 1
            avg = (i + j - 1) / 2 + 1
            for k in range(i, j):
                rank[sv[k]] = avg
            i = j
        return rank

    rx, ry = _ranks(x), _ranks(y)
    xm, ym = _mean(rx), _mean(ry)
    num = sum((rx[i] - xm) * (ry[i] - ym) for i in range(n))
    den = math.sqrt(sum((rx[i] - xm) ** 2 for i in range(n)) * sum((ry[i] - ym) ** 2 for i in range(n)))
    return round(num / den, 4) if den > 0 else 0.0


class BenchmarkAnalyzer:
    """
    Loads a completed benchmark run and computes all statistical metrics.

    `store` is an injected BenchmarkStore instance (see
    dependencies.get_benchmark_store) instead of the old static-method
    calls, so results_dir is resolved from Settings exactly once.
    """

    def __init__(self, run_id: str, store: BenchmarkStore):
        self.run_id = run_id
        self.store = store
        data = store.load_run(run_id)
        if data is None:
            raise FileNotFoundError(f"No benchmark run found: '{run_id}'")
        self._data = data
        self._qr = data.get("query_results", [])
        self._cr = data.get("code_results", [])
        self._scenarios: List[str] = data.get("scenarios_enabled", [])

    def _scores_for(self, scenario: str, metric: str = "overall_score") -> List[float]:
        out = []
        for qr in self._qr:
            sr = qr.get("scenario_results", {}).get(scenario, {})
            if sr.get("error"):
                continue
            val = sr.get("quality", {}).get(metric)
            if val is not None:
                out.append(float(val))
        return out

    def _timing_for(self, scenario: str, phase: str) -> List[float]:
        out = []
        for qr in self._qr:
            sr = qr.get("scenario_results", {}).get(scenario, {})
            if sr.get("error"):
                continue
            val = sr.get("timing", {}).get(phase)
            if val is not None:
                out.append(float(val))
        return out

    def _keyword_recalls(self, scenario: str) -> List[float]:
        return [
            float(qr.get("scenario_results", {}).get(scenario, {}).get("keyword_recall", 0))
            for qr in self._qr
            if not qr.get("scenario_results", {}).get(scenario, {}).get("error")
        ]

    def compute_scenario_stats(self) -> Dict[str, Any]:
        out = {}
        for s in self._scenarios:
            scores = self._scores_for(s, "overall_score")
            recalls = self._keyword_recalls(s)
            tot_ms = self._timing_for(s, "total_ms")
            gen_ms = self._timing_for(s, "generation_ms")
            eval_ms = self._timing_for(s, "evaluation_ms")
            heal_ms = self._timing_for(s, "healing_ms")

            heal_cnt = sum(1 for qr in self._qr if qr.get("scenario_results", {}).get(s, {}).get("healing_triggered", False))
            n_valid = sum(1 for qr in self._qr if not qr.get("scenario_results", {}).get(s, {}).get("error"))

            ci_low, ci_hi = bootstrap_ci(scores) if scores else (0.0, 0.0)
            out[s] = {
                "n_valid": n_valid,
                "quality_score": {**describe(scores), "ci_95_low": ci_low, "ci_95_high": ci_hi},
                "keyword_recall": describe(recalls),
                "latency_ms": {
                    "total": describe(tot_ms), "generation": describe(gen_ms),
                    "evaluation": describe(eval_ms), "healing": describe(heal_ms),
                },
                "healing_trigger_rate": round(heal_cnt / n_valid, 3) if n_valid else 0.0,
            }
        return out

    def compute_pairwise_comparisons(self) -> Dict[str, Any]:
        out = {}
        for i, s_a in enumerate(self._scenarios):
            for s_b in self._scenarios[i + 1:]:
                qa = self._scores_for(s_a)
                qb = self._scores_for(s_b)
                n = min(len(qa), len(qb))
                if n < 2:
                    continue
                qa, qb = qa[:n], qb[:n]

                ta = self._timing_for(s_a, "total_ms")[:n]
                tb = self._timing_for(s_b, "total_ms")[:n]
                dq = [b - a for a, b in zip(qa, qb)]
                dt = [b - a for a, b in zip(ta, tb)]

                key = f"{s_a}__vs__{s_b}"
                out[key] = {
                    "quality_delta": {**describe(dq)},
                    "time_overhead_ms": {**describe(dt)},
                    "cohen_d": cohen_d(qa, qb),
                    "wilcoxon": wilcoxon_srtest(qa, qb),
                    "spearman_rho_quality_vs_time": spearman_rho(dq, dt),
                    "healing_roi": (
                        round(_mean(dq) / (_mean([max(h, 0.001) for h in self._timing_for(s_b, "healing_ms")[:n]]) / 1_000), 4)
                        if "heal" in s_b else None
                    ),
                }
        return out

    def compute_category_breakdown(self) -> Dict[str, Any]:
        from collections import defaultdict
        cat_data: Dict[str, Dict[str, List[float]]] = defaultdict(lambda: defaultdict(list))

        for qr in self._qr:
            cat = qr.get("category", "unknown")
            for s in self._scenarios:
                sr = qr.get("scenario_results", {}).get(s, {})
                if sr.get("error"):
                    continue
                q = sr.get("quality", {}).get("overall_score")
                r = sr.get("keyword_recall")
                if q is not None:
                    cat_data[cat][f"{s}__quality"].append(float(q))
                if r is not None:
                    cat_data[cat][f"{s}__recall"].append(float(r))

        out = {}
        for cat, metrics in cat_data.items():
            out[cat] = {mkey: describe(vals) for mkey, vals in metrics.items()}
        return out

    def compute_code_analysis_metrics(self) -> Dict[str, Any]:
        if not self._cr:
            return {"message": "No code benchmark results in this run."}

        detection_rates = [r.get("detection_rate", 0) for r in self._cr]
        severity_acc = [1.0 if r.get("severity_correct") else 0.0 for r in self._cr]
        fp_rates = [r.get("false_positive_count", 0) / max(r.get("total_findings", 1), 1) for r in self._cr]
        latencies = [r.get("analysis_ms", 0) for r in self._cr]

        by_lang: Dict[str, List] = {}
        by_cwe: Dict[str, int] = {}
        for r in self._cr:
            lang = r.get("language", "unknown")
            by_lang.setdefault(lang, []).append(r.get("detection_rate", 0))
            for cwe in r.get("known_cwes", []):
                by_cwe[cwe] = by_cwe.get(cwe, 0) + (1 if cwe in r.get("detected_cwes", []) else 0)

        return {
            "overall": {
                "detection_rate": describe(detection_rates), "severity_accuracy": describe(severity_acc),
                "false_positive_rate": describe(fp_rates), "analysis_latency_ms": describe(latencies),
            },
            "per_language": {lang: {"mean_detection_rate": round(_mean(vals), 3)} for lang, vals in by_lang.items()},
            "per_cwe_detection": by_cwe,
        }

    def compute_latency_analysis(self) -> Dict[str, Any]:
        out = {}
        for s in self._scenarios:
            tot = self._timing_for(s, "total_ms")
            gen = self._timing_for(s, "generation_ms")
            evl = self._timing_for(s, "evaluation_ms")
            heal = self._timing_for(s, "healing_ms")
            # Not gated into `n` below — older run files saved before this
            # field existed simply won't have it, and that shouldn't zero
            # out the rest of the latency table for those runs.
            rl = self._timing_for(s, "rate_limited_ms")
            n = min(len(tot), len(gen), len(evl), len(heal))
            if n == 0:
                continue

            tot, gen, evl, heal = tot[:n], gen[:n], evl[:n], heal[:n]
            heal_pct = [round(h / max(t, 1) * 100, 1) for h, t in zip(heal, tot)]
            eval_pct = [round(e / max(t, 1) * 100, 1) for e, t in zip(evl, tot)]
            out[s] = {
                "total_ms": describe(tot),
                "generation_pct_of_total": round(_mean([g / max(t, 1) * 100 for g, t in zip(gen, tot)]), 1),
                "evaluation_pct_of_total": round(_mean(eval_pct), 1),
                "healing_pct_of_total": round(_mean(heal_pct), 1),
                "p95_total_ms": round(_percentile(tot, 95), 1),
                "p99_total_ms": round(_percentile(tot, 99), 1),
                "rate_limited_ms_mean": round(_mean(rl), 1) if rl else 0.0,
            }
        return out

    def compute_healing_roi_summary(self) -> Dict[str, Any]:
        # Any scenario ending in "_heal" (but not "_no_heal") pairs with the
        # "<same provider>_no_heal" scenario, whatever the provider is —
        # replaces the old fixed {"gemini_heal": ..., "ollama_heal": ...}
        # map, which silently dropped any provider besides those two.
        heal_scenarios = [s for s in self._scenarios if s.endswith("_heal") and not s.endswith("_no_heal")]
        out = {}
        for s_heal in heal_scenarios:
            s_base = s_heal[: -len("_heal")] + "_no_heal"
            if s_base not in self._scenarios:
                continue

            q_base = self._scores_for(s_base)
            q_heal = self._scores_for(s_heal)
            h_ms = self._timing_for(s_heal, "healing_ms")
            n = min(len(q_base), len(q_heal), len(h_ms))
            if n == 0:
                continue

            deltas = [q_heal[i] - q_base[i] for i in range(n)]
            rois = [d / max(h / 1_000, 0.001) for d, h in zip(deltas, h_ms[:n])]
            triggered = [
                qr.get("scenario_results", {}).get(s_heal, {}).get("healing_triggered", False) for qr in self._qr
            ][:n]
            triggered_indices = [i for i, t in enumerate(triggered) if t]

            out[f"{s_base}_vs_{s_heal}"] = {
                "quality_delta": describe(deltas),
                "healing_roi_quality_per_sec": describe(rois),
                "healing_triggered_n": len(triggered_indices),
                "healing_trigger_rate": round(len(triggered_indices) / n, 3),
                "mean_delta_when_triggered": (round(_mean([deltas[i] for i in triggered_indices]), 4) if triggered_indices else 0.0),
                "mean_delta_when_not_triggered": (
                    round(_mean([deltas[i] for i in range(n) if i not in triggered_indices]), 4) if len(triggered_indices) < n else 0.0
                ),
            }
        return out

    def generate_research_report(self) -> Dict[str, Any]:
        cfg = self._data.get("config", {})
        return {
            "metadata": {
                "run_id": self.run_id, "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "total_queries": self._data.get("total_queries"), "scenarios": self._scenarios,
                "evaluator_provider": cfg.get("evaluator_provider"), "evaluator_model": cfg.get("evaluator_model"),
                "generation_models": cfg.get("generation_models", {}),
                "providers_available": cfg.get("providers_available", []),
                "providers_unavailable": cfg.get("providers_unavailable", {}),
                "scipy_available": _SCIPY,
            },
            "scenario_stats": self.compute_scenario_stats(),
            "pairwise_comparisons": self.compute_pairwise_comparisons(),
            "category_breakdown": self.compute_category_breakdown(),
            "latency_analysis": self.compute_latency_analysis(),
            "healing_roi": self.compute_healing_roi_summary(),
            "code_analysis": self.compute_code_analysis_metrics(),
        }

    def generate_markdown_report(self) -> str:
        report = self.generate_research_report()
        meta = report["metadata"]
        ss = report["scenario_stats"]
        pw = report["pairwise_comparisons"]
        cat = report["category_breakdown"]
        lat = report["latency_analysis"]
        roi = report["healing_roi"]
        code = report["code_analysis"]

        lines = [
            "# DATIN RAG Pipeline — Benchmark Report", "",
            f"**Run ID**: `{meta['run_id']}`  ", f"**Generated**: {meta['generated_at']}  ",
            f"**Queries**: {meta['total_queries']}  ", f"**Scenarios**: {', '.join(meta['scenarios'])}  ",
            f"**Generation models**: {', '.join(f'{p}={m}' for p, m in meta.get('generation_models', {}).items())}  ",
            f"**Evaluator**: {meta.get('evaluator_provider', '')}={meta['evaluator_model']}  ",
            f"**Statistical test**: {'Wilcoxon signed-rank (scipy)' if meta['scipy_available'] else 'Sign test (scipy absent)'}",
            "", "---", "", "## 1. Scenario Quality Scores", "",
            "| Scenario | N | Mean ± SD | Median | 95% CI | Heal Rate |", "|---|---|---|---|---|---|",
        ]
        for s, d in ss.items():
            q = d["quality_score"]
            ci = f"[{q['ci_95_low']}, {q['ci_95_high']}]"
            lines.append(f"| {s} | {int(q['n'])} | {q['mean']:.3f} ± {q['std']:.3f} | {q['median']:.3f} | {ci} | {d['healing_trigger_rate']*100:.0f}% |")

        lines += ["", "## 2. Keyword Recall (Deterministic Proxy)", "", "| Scenario | Mean | SD | Median |", "|---|---|---|---|"]
        for s, d in ss.items():
            kr = d["keyword_recall"]
            lines.append(f"| {s} | {kr['mean']:.3f} | {kr['std']:.3f} | {kr['median']:.3f} |")

        lines += ["", "## 3. Pairwise Comparisons", "", "| Pair | Δ Quality (mean) | Cohen's d | Wilcoxon p | Significant | Heal ROI |", "|---|---|---|---|---|---|"]
        for pair, d in pw.items():
            w = d["wilcoxon"]
            delta = d["quality_delta"]["mean"]
            cd = d["cohen_d"]
            p_val = w.get("p_value", "N/A")
            sig = "✓" if w.get("significant") else "✗"
            h_roi = f"{d['healing_roi']:.3f}" if d.get("healing_roi") is not None else "N/A"
            lines.append(f"| {pair.replace('__vs__', ' vs ')} | {delta:+.4f} | {cd:+.4f} | {p_val} | {sig} | {h_roi} |")

        lines += ["", "## 4. Per-Category Quality (Mean overall_score)", "", "| Category |" + "".join(f" {s} |" for s in self._scenarios), "|---|" + "---|" * len(self._scenarios)]
        for c, metrics in sorted(cat.items()):
            row = f"| {c} |"
            for s in self._scenarios:
                key = f"{s}__quality"
                val = metrics.get(key, {}).get("mean", "—")
                row += f" {val:.3f} |" if isinstance(val, float) else " — |"
            lines.append(row)

        lines += [
            "", "## 5. Latency Budget", "",
            "| Scenario | Mean Total (ms) | Gen % | Eval % | Heal % | p95 (ms) | Rate-Limit Wait (ms) |",
            "|---|---|---|---|---|---|---|",
        ]
        for s, d in lat.items():
            tot = d["total_ms"]
            rl = d.get("rate_limited_ms_mean", 0.0)
            lines.append(
                f"| {s} | {tot['mean']:.0f} ± {tot['std']:.0f} | {d['generation_pct_of_total']}% | "
                f"{d['evaluation_pct_of_total']}% | {d['healing_pct_of_total']}% | {d['p95_total_ms']:.0f} | "
                f"{rl:.0f} |"
            )

        lines += ["", "## 6. Self-Healing ROI", ""]
        for pair, d in roi.items():
            dq = d["quality_delta"]
            r = d["healing_roi_quality_per_sec"]
            lines += [
                f"**{pair}**",
                f"- Quality Δ mean ± SD: {dq['mean']:+.4f} ± {dq['std']:.4f}",
                f"- Healing trigger rate: {d['healing_trigger_rate']*100:.1f}%",
                f"- ROI (quality pts/sec): {r['mean']:+.4f} ± {r['std']:.4f}",
                f"- Δ when triggered: {d['mean_delta_when_triggered']:+.4f}",
                f"- Δ when not triggered: {d['mean_delta_when_not_triggered']:+.4f}",
                "",
            ]

        if "overall" in code:
            ov = code["overall"]
            lines += ["## 7. Code Analysis Benchmark", "", "| Metric | Mean | SD | Min | Max |", "|---|---|---|---|---|"]
            for metric_key, label in [("detection_rate", "CWE Detection Rate"), ("severity_accuracy", "Severity Accuracy"), ("false_positive_rate", "False Positive Rate")]:
                d = ov.get(metric_key, {})
                lines.append(f"| {label} | {d.get('mean',0):.3f} | {d.get('std',0):.3f} | {d.get('min',0):.3f} | {d.get('max',0):.3f} |")
            lines.append("")
            if "per_language" in code:
                lines += ["**Detection rate per language:**", ""]
                for lang, d in code["per_language"].items():
                    lines.append(f"- `{lang}`: {d.get('mean_detection_rate', 0):.3f}")

        lines += ["", "---", "", "## 8. Conclusions", "", self._auto_conclusions(report), "", "_Report generated by DATIN BenchmarkAnalyzer_"]
        return "\n".join(lines)

    def _auto_conclusions(self, report: Dict[str, Any]) -> str:
        ss = report["scenario_stats"]
        pw = report["pairwise_comparisons"]
        roi = report["healing_roi"]
        conclusions = []

        best = max(ss.items(), key=lambda kv: kv[1]["quality_score"]["mean"])
        worst = min(ss.items(), key=lambda kv: kv[1]["quality_score"]["mean"])
        conclusions.append(
            f"**Best scenario**: `{best[0]}` (mean quality {best[1]['quality_score']['mean']:.3f}); "
            f"**worst**: `{worst[0]}` ({worst[1]['quality_score']['mean']:.3f})."
        )

        sig_pairs = [(k, v) for k, v in pw.items() if v.get("wilcoxon", {}).get("significant")]
        if sig_pairs:
            pair_str = ", ".join(k.replace("__vs__", " vs ") for k, _ in sig_pairs)
            conclusions.append(f"Statistically significant quality differences (α=0.05) found for: {pair_str}.")
        else:
            conclusions.append("No statistically significant quality differences detected across scenarios — a larger query corpus may be required for reliable inference.")

        for pair_key, d in roi.items():
            r = d["healing_roi_quality_per_sec"]["mean"]
            tr = d["healing_trigger_rate"]
            if r > 0:
                conclusions.append(f"Self-healing ROI for `{pair_key}`: **{r:.3f} quality pts/sec** (trigger rate {tr*100:.1f}%) — healing improves output quality.")
            elif r < 0:
                conclusions.append(f"Self-healing ROI for `{pair_key}` is **negative ({r:.3f})** — healing introduced regressions for this provider; investigate healing prompt calibration.")
            else:
                conclusions.append(f"Self-healing for `{pair_key}` had **zero net effect** on quality despite {tr*100:.1f}% trigger rate.")

        return "\n\n".join(conclusions)