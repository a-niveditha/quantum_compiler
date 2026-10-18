"""
Live-compile service behind the dashboard's Compile button.

Loads the backend, the trained GNN and the two seed-42 RL agents once, then
compiles one benchmark with the five methods shown in the demo. Every method
reuses the exact code path that produced the published CSVs, so the live
metrics can be checked value-for-value against evaluation/results/.

    SABRE            Phase 1 baseline (layout + routing, O3)
    MQT_QMAP         Phase 1 baseline
    GNN+SABRE        Phase 2: GNN top-20 shortlist, SABRE routing, highest est. fidelity kept
    RL               Phase 3: RL agent (seed 42) routing from SABRE's layout
    GNN+RL           Phase 4: RL agent with GNN observation (seed 42) routing the GNN top-20
"""

from __future__ import annotations

import math
import threading
import time

import pandas as pd

from baseline.benchmark_sabre_qmap import run_qmap, run_sabre
from config import (BASELINE_CSV, GNN_RL_CHECKPOINT, RL_CHECKPOINT, RL_RESULTS_CSV, SEED,
                    get_backend, load_benchmark_circuits)
from evaluation.metrics import count_swaps
from gnn.evaluate_shared import GNN_RESULTS_CSV, TOP_K, sabre_candidates, select
from gnn.gnn_layout import GNNLayoutSelector
from gnn_rl.features import GNNObservation
from rl.circuit_utils import circuit_to_task, sabre_layout_and_swaps
from rl.env import RoutingEnv
from rl.evaluate import load_model, model_policy, post_routing_pm, route_candidates, score

CIRCUIT_INFO = {
    "ghz": "GHZ state: entangles all 5 qubits through a chain of CNOTs.",
    "dj": "Deutsch-Jozsa: decides whether an oracle function is constant or balanced.",
    "graphstate": "Graph state on a random 2-regular graph (seeded, identical in every phase).",
    "qft": "Quantum Fourier Transform: every qubit interacts with every other, the hardest to route.",
    "wstate": "W state: one excitation shared equally across 5 qubits.",
}

# id -> (label, description, CSV file, method name in that CSV)
METHODS = {
    "SABRE": ("SABRE", "Qiskit baseline: SABRE layout + routing, optimization level 3",
              BASELINE_CSV, "SABRE"),
    "MQT_QMAP": ("MQT QMAP", "MQT QMAP heuristic mapper baseline",
                 BASELINE_CSV, "MQT_QMAP"),
    "GNN+SABRE": ("GNN + SABRE", f"GNN shortlists its top {TOP_K} layouts, SABRE routes each, "
                  "highest estimated fidelity kept",
                  GNN_RESULTS_CSV, f"GNN_top{TOP_K}_fid+SABRE"),
    "RL": ("RL", "RL agent (seed 42) routes from SABRE's initial layout",
           RL_RESULTS_CSV, "RL_sb3_agent"),
    "GNN+RL": ("GNN + RL", f"RL agent with GNN embeddings in its observation (seed 42) routes "
               f"the GNN's top {TOP_K} layouts, fewest SWAPs kept",
               RL_RESULTS_CSV, f"RL_GNNobs_sb3_agent_gnn+GNN_top{TOP_K}_layout"),
}

# metric -> (tolerance for "matches published", higher is better?)
METRICS = {
    "swaps": (0, False),
    "depth": (0, False),
    "total_gates": (0, False),
    "estimated_fidelity": (1e-9, True),
    "state_fidelity": (1e-6, True),
    "compile_time_s": (None, False),   # measured live, never expected to match
}

# Physical positions of FakeJakartaV2's H-shaped coupling graph, for drawing.
JAKARTA_POSITIONS = {0: (0, 0), 1: (1, 0), 2: (2, 0), 3: (1, 1), 4: (0, 2), 5: (1, 2), 6: (2, 2)}


class CompileService:
    def __init__(self):
        t0 = time.perf_counter()
        self.lock = threading.Lock()
        self.backend = get_backend()
        self.circuits = load_benchmark_circuits()
        self.tasks = {n: circuit_to_task(qc, n, self.backend) for n, qc in self.circuits.items()}
        self.sabre_layouts = {n: sabre_layout_and_swaps(qc, self.backend, SEED)[0]
                              for n, qc in self.circuits.items()}
        self.pm = post_routing_pm(self.backend)
        self.selector = GNNLayoutSelector(self.backend)

        tasks = list(self.tasks.values())
        self.env = RoutingEnv(self.backend, tasks=tasks)
        feat = GNNObservation(self.backend)
        self.gnn_env = RoutingEnv(self.backend, tasks=tasks, extra_obs_dim=feat.dim, extra_obs_fn=feat)
        self.rl_policy = model_policy(*load_model(RL_CHECKPOINT))
        self.gnn_rl_policy = model_policy(*load_model(GNN_RL_CHECKPOINT))

        self.published = {path: pd.read_csv(path) for path in {m[2] for m in METHODS.values()}}
        self.compile("ghz")  # warm-up: first GNN / RL calls are slower
        self.startup_seconds = time.perf_counter() - t0

    # ------------------------------------------------------------------
    def options(self) -> dict:
        target = self.backend.target
        edges = sorted({tuple(sorted(e)) for e in self.backend.coupling_map.get_edges()})
        cx = "cx" if "cx" in target.operation_names else "ecr"

        def edge_error(a, b):
            errs = [target[cx][q].error for q in ((a, b), (b, a)) if q in target[cx]]
            return float(sum(errs) / len(errs))

        return {
            "device": {
                "name": "FakeJakartaV2",
                "qubits": [{"id": q, "x": x, "y": y,
                            "readout_error": float(target["measure"][(q,)].error)}
                           for q, (x, y) in JAKARTA_POSITIONS.items()],
                "edges": [{"a": a, "b": b, "cx_error": edge_error(a, b)} for a, b in edges],
            },
            "circuits": [{
                "id": n, "description": CIRCUIT_INFO.get(n, ""),
                "num_qubits": qc.num_qubits, "two_qubit_gates": self.tasks[n].num_2q,
                "drawing": str(qc.decompose().draw(output="text", fold=110)),
            } for n, qc in self.circuits.items()],
            "methods": [{"id": k, "label": v[0], "description": v[1]} for k, v in METHODS.items()],
            "metrics": list(METRICS),
            "top_k": TOP_K,
        }

    # ------------------------------------------------------------------
    def compile(self, name: str) -> dict:
        if name not in self.circuits:
            raise KeyError(name)
        with self.lock:
            qc, task, backend = self.circuits[name], self.tasks[name], self.backend
            t_start = time.perf_counter()
            raw = {}

            compiled, dt, swaps = run_sabre(qc, backend)
            raw["SABRE"] = (compiled, swaps, dt, _initial_layout(compiled, qc.num_qubits), {})

            compiled, dt, _, swaps = run_qmap(qc, backend)
            swaps = swaps if swaps is not None else count_swaps(compiled)
            raw["MQT_QMAP"] = (compiled, swaps, dt, _initial_layout(compiled, qc.num_qubits), {})

            shortlist, _, score_time = self.selector.top_k(qc, TOP_K)
            cands = sabre_candidates(qc, backend, shortlist)
            best, route_time = select(METHODS["GNN+SABRE"][3], cands)
            raw["GNN+SABRE"] = (best["compiled"], best["swaps"], score_time + route_time,
                                best["layout"], {"gnn_rank": best["rank"]})

            t0 = time.perf_counter()
            best = route_candidates(self.rl_policy, self.env, task, [self.sabre_layouts[name]], self.pm)
            raw["RL"] = (best["compiled"], best["swaps"], time.perf_counter() - t0, best["layout"],
                         {"fallback": best["fallback"]})

            t0 = time.perf_counter()
            best = route_candidates(self.gnn_rl_policy, self.gnn_env, task, shortlist, self.pm)
            raw["GNN+RL"] = (best["compiled"], best["swaps"], time.perf_counter() - t0 + score_time,
                             best["layout"], {"gnn_rank": best["rank"], "fallback": best["fallback"]})

            results = []
            for mid, (compiled, swaps, dt, layout, extra) in raw.items():
                row = score(name, mid, qc, compiled, swaps, dt, backend)
                results.append({
                    "method": mid, "label": METHODS[mid][0],
                    "layout": [int(p) for p in layout] if layout else None,
                    "metrics": self._compare(name, mid, row),
                    "extra": extra,
                    "drawing": str(compiled.draw(output="text", fold=110, idle_wires=False)),
                })
            return {"circuit": name, "results": results,
                    "total_seconds": time.perf_counter() - t_start}

    def _compare(self, circuit: str, method_id: str, row: dict) -> dict:
        _, _, path, csv_method = METHODS[method_id]
        df = self.published[path]
        match = df[(df["circuit"] == circuit) & (df["method"] == csv_method)]
        published = match.iloc[0] if len(match) else None
        out = {}
        for metric, (tol, _) in METRICS.items():
            live = _plain(row[metric])
            pub = _plain(published[metric]) if published is not None else None
            out[metric] = {
                "live": live, "published": pub,
                "matches": None if tol is None or pub is None else bool(abs(live - pub) <= tol),
            }
        return out


def _initial_layout(compiled, n_logical):
    """Physical qubit of each logical qubit, from Qiskit's layout metadata."""
    try:
        return list(compiled.layout.initial_index_layout(filter_ancillas=False))[:n_logical]
    except Exception:
        return None


def _plain(x):
    """numpy scalars -> JSON-safe Python numbers."""
    x = float(x)
    return int(x) if math.isfinite(x) and x.is_integer() else x
