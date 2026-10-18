"""
Phase 2 evaluation in the shared framework: GNN-selected initial layout +
SABRE routing, scored exactly like the Phase 1 baseline (SABRE at
optimization_level=3, true inserted-SWAP count, evaluation/metrics.py incl.
estimated and state fidelity).

qubit_allocation.evaluate (the GNN project's own evaluator) stays as is: it
measures prediction quality and compares layouts at optimization_level=0.
This script produces the numbers that go next to SABRE / QMAP / RL:
  GNN_layout+SABRE        route the GNN's single best-predicted layout
  GNN_top20+SABRE         route its TOP_K best-predicted layouts and keep the
                          one with the fewest SWAPs (ties: lower depth);
                          compile time includes every candidate routing
  GNN_top20_fid+SABRE     same 20 routed candidates, keep the one with the
                          highest estimated fidelity (noise-aware selection
                          from the backend's calibration data; no retraining)

RUN (from backend/, after the GNN is trained):
    python -m gnn.evaluate_shared
"""

from __future__ import annotations

import os

import pandas as pd

from baseline.benchmark_sabre_qmap import run_sabre
from config import BASELINE_CSV, RESULTS_DIR, get_backend, load_benchmark_circuits
from evaluation.metrics import estimated_fidelity, state_fidelity_vs_ideal, total_gate_count
from gnn.gnn_layout import GNNLayoutSelector

GNN_RESULTS_CSV = f"{RESULTS_DIR}/gnn_results.csv"
TOP_K = 20


# How each reported method picks among the routed shortlist.
SELECTIONS = {
    "GNN_layout+SABRE": (1, lambda c: (c["swaps"], c["depth"])),
    f"GNN_top{TOP_K}+SABRE": (TOP_K, lambda c: (c["swaps"], c["depth"])),
    f"GNN_top{TOP_K}_fid+SABRE": (TOP_K, lambda c: -c["estimated_fidelity"]),
}


def sabre_candidates(qc, backend, layouts) -> list[dict]:
    """Route qc with SABRE (O3) from each fixed initial layout, in order."""
    out = []
    for rank, layout in enumerate(layouts, start=1):
        compiled, route_time, swaps = run_sabre(qc, backend, initial_layout=layout)
        out.append({"rank": rank, "layout": list(layout), "compiled": compiled, "swaps": swaps,
                    "depth": compiled.depth(), "route_time": route_time,
                    "estimated_fidelity": estimated_fidelity(compiled, backend)})
    return out


def select(method, candidates) -> tuple[dict, float]:
    """(chosen candidate, routing seconds spent on the pool it was chosen from)."""
    k, key = SELECTIONS[method]
    pool = candidates[:k]
    return min(pool, key=key), sum(c["route_time"] for c in pool)


def main():
    backend = get_backend()
    selector = GNNLayoutSelector(backend)
    rows = []
    for name, qc in load_benchmark_circuits().items():
        layouts, predicted, score_time = selector.top_k(qc, TOP_K)
        candidates = sabre_candidates(qc, backend, layouts)
        for method in SELECTIONS:
            best, route_time = select(method, candidates)
            sf, leak = state_fidelity_vs_ideal(qc, best["compiled"])
            rows.append({
                "circuit": name, "method": method,
                "depth": best["depth"], "swaps": best["swaps"],
                "total_gates": total_gate_count(best["compiled"]),
                "compile_time_s": score_time + route_time,
                "estimated_fidelity": best["estimated_fidelity"],
                "state_fidelity": sf, "leakage": leak,
                "notes": f"layout={best['layout']} gnn_rank={best['rank']} "
                         f"predicted_swaps={predicted[best['rank'] - 1]:.2f} scoring_s={score_time:.3f}",
            })
        print(f"{name:<11} top1: {rows[-3]['swaps']} swaps | top{TOP_K}: {rows[-2]['swaps']} swaps | "
              f"top{TOP_K} by fidelity: {rows[-1]['swaps']} swaps, est. fidelity {rows[-1]['estimated_fidelity']:.4f}")

    df = pd.DataFrame(rows)
    os.makedirs(RESULTS_DIR, exist_ok=True)
    df.to_csv(GNN_RESULTS_CSV, index=False)

    full = pd.concat([pd.read_csv(BASELINE_CSV), df], ignore_index=True) if os.path.exists(BASELINE_CSV) else df
    full = full[full["method"].isin(["SABRE", "MQT_QMAP", *SELECTIONS])]
    pd.set_option("display.width", 160)
    print("\n=== swaps per circuit ===")
    print(full.pivot(index="circuit", columns="method", values="swaps").to_string())
    print("\n=== totals over 5 circuits ===")
    print(full.groupby("method", sort=False).agg(
        depth=("depth", "sum"), swaps=("swaps", "sum"), total_gates=("total_gates", "sum"),
        compile_time_s=("compile_time_s", "sum"), estimated_fidelity=("estimated_fidelity", "mean"),
        state_fidelity=("state_fidelity", "min")).to_string())
    print(f"\nSaved {GNN_RESULTS_CSV}")


if __name__ == "__main__":
    main()
