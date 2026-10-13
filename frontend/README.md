# Dashboard (live compile demo)

Pick one of the 5 benchmarks, click **Compile circuit**, and the backend compiles it
live with SABRE, MQT QMAP, GNN + SABRE, RL and GNN + RL on FakeJakartaV2. Every
metric is checked against the published CSVs in `backend/evaluation/results/`
(✓ = identical; compile time is measured live and not compared).

## Run (two terminals)

**1. API**, from `backend/` with the venv active. Wait for `API ready`:

```bash
python -m uvicorn api.server:app --port 8000
```

**2. Dashboard**, from `frontend/` (first time: `npm install`):

```bash
npm run dev
```

Open http://localhost:5173. The dev server forwards `/api` to port 8000
(`vite.config.js`).

## What is shown

| Section | Content |
|---|---|
| Results table | 6 metrics × 5 methods, best value per row highlighted, ✓/✗ against the CSVs |
| Qubit placement | Each method's initial layout on Jakarta's chip; coupler colour = CX error, ring colour = readout error |
| Compiled circuits | Text drawing of each compiled circuit |

The methods map to these published rows:

| Dashboard | CSV | Method |
|---|---|---|
| SABRE | `sabre_vs_qmap_results.csv` | `SABRE` |
| MQT QMAP | `sabre_vs_qmap_results.csv` | `MQT_QMAP` |
| GNN + SABRE | `gnn_results.csv` | `GNN_top20_fid+SABRE` |
| RL | `rl_results.csv` | `RL_sb3_agent` (seed 42) |
| GNN + RL | `rl_results.csv` | `RL_GNNobs_sb3_agent_gnn+GNN_top20_layout` (seed 42) |

RL rows use the seed-42 agents; mean ± std over 3 seeds is in the CSVs and
`backend/gnn_rl/README.md`.
