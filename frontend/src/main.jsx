import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './styles.css';

// metric id -> [label, better direction, formatter]
const METRICS = {
  swaps: ['SWAP gates', 'low', v => v],
  depth: ['Circuit depth', 'low', v => v],
  total_gates: ['Total gates', 'low', v => v],
  estimated_fidelity: ['Estimated fidelity', 'high', v => v.toFixed(4)],
  state_fidelity: ['State fidelity', 'high', v => v.toFixed(4)],
  compile_time_s: ['Compile time', 'low', v => `${v < 0.1 ? v.toFixed(3) : v.toFixed(2)} s`],
};

const GOOD = [78, 155, 101];   // low error: green
const BAD = [214, 69, 69];     // high error: red
const mix = t => `rgb(${GOOD.map((g, i) => Math.round(g + (BAD[i] - g) * t)).join(',')})`;

async function api(path, body) {
  const res = await fetch(`/api/${path}`, body ? {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  } : undefined);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

function App() {
  const [options, setOptions] = useState(null);
  const [circuit, setCircuit] = useState('dj');
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const loadOptions = () => {
    setError(null);
    api('options').then(setOptions).catch(() => setError('offline'));
  };
  useEffect(loadOptions, []);

  const compile = async () => {
    setLoading(true); setError(null);
    try { setResult(await api('compile', { circuit })); }
    catch (e) { setError(e.message === 'Failed to fetch' ? 'offline' : e.message); }
    finally { setLoading(false); }
  };

  const info = options?.circuits.find(c => c.id === circuit);
  const shown = result && result.circuit === circuit ? result : null;

  return <div className="page">
    <header className="topbar">
      <div className="brand"><span className="orb">⚛</span><div>
        <div className="title">QUANTUM COMPILER</div>
        <div className="subtitle">GNN + RL qubit allocation and routing · FakeJakartaV2</div>
      </div></div>
      <div className={`status ${options ? '' : 'off'}`}><span></span>{options ? 'API CONNECTED' : 'API OFFLINE'}</div>
    </header>

    <main>
      <section className="hero">
        <div>
          <p className="eyebrow">LIVE COMPILATION</p>
          <h1>Compile a benchmark <em>live</em> and compare against SABRE.</h1>
          <p className="muted">Pick one of the five MQT Bench circuits. The backend compiles it with all five
            methods on the 7-qubit FakeJakartaV2 and checks every number against the published results.</p>
        </div>
        <div className="controls">
          <label>CIRCUIT
            <select value={circuit} onChange={e => setCircuit(e.target.value)} disabled={!options || loading}>
              {(options?.circuits ?? []).map(c => <option key={c.id} value={c.id}>{c.id} · {c.num_qubits} qubits</option>)}
            </select>
          </label>
          <button onClick={compile} disabled={!options || loading}>{loading ? 'COMPILING…' : 'COMPILE CIRCUIT'}</button>
        </div>
      </section>

      {error === 'offline' && <section className="card notice">
        <h2>Backend API not reachable</h2>
        <p className="muted">From <code>backend/</code> with the venv active, run
          <code>python -m uvicorn api.server:app --port 8000</code>, wait for "API ready", then
          <button className="link" onClick={loadOptions}>retry</button>.</p>
      </section>}
      {error && error !== 'offline' && <section className="card notice"><h2>Compile failed</h2><p className="muted">{error}</p></section>}

      {info && <section className="card circuitinfo">
        <div className="cardhead"><div><p className="eyebrow">CIRCUIT</p><h2>{info.id}</h2></div>
          <div className="badge">{info.num_qubits} logical qubits · {info.two_qubit_gates} two-qubit gates</div></div>
        <p className="muted">{info.description}</p>
        <details><summary>Logical circuit</summary><pre className="drawing">{info.drawing}</pre></details>
      </section>}

      {loading && <section className="card loadingcard"><div className="spinner"></div>
        <p className="muted">Running SABRE, QMAP, GNN scoring of 2,520 layouts, and both RL agents…</p></section>}

      {shown && !loading && <Results result={shown} options={options} />}
    </main>
    <footer>QUANTUM COMPILER · RESULTS FROM backend/evaluation/results · RL AGENTS: SEED 42</footer>
  </div>;
}

function Results({ result, options }) {
  const rows = result.results;
  const checks = rows.flatMap(r => Object.values(r.metrics)).filter(m => m.matches !== null);
  const matched = checks.filter(m => m.matches).length;

  const best = {};
  for (const [key, [, dir]] of Object.entries(METRICS)) {
    const vals = rows.map(r => r.metrics[key].live);
    const target = dir === 'low' ? Math.min(...vals) : Math.max(...vals);
    best[key] = vals.every(v => Math.abs(v - vals[0]) < 1e-12) ? null : target;
  }

  return <>
    <section className="summary">
      <div className={`pill ${matched === checks.length ? 'ok' : 'warn'}`}>
        {matched === checks.length ? '✓' : '!'} {matched}/{checks.length} values match the published results
      </div>
      <div className="pill">compiled in {result.total_seconds.toFixed(2)} s</div>
    </section>

    <section className="comparison card">
      <div className="cardhead"><div><p className="eyebrow">RESULTS</p><h2>{result.circuit} <span>on</span> FakeJakartaV2</h2></div>
        <div className="badge">best value per row highlighted</div></div>
      <div className="table" style={{ '--cols': rows.length }}>
        <div className="row head"><div></div>{rows.map(r => <div key={r.method} title={options.methods.find(m => m.id === r.method)?.description}>{r.label}</div>)}</div>
        {Object.entries(METRICS).map(([key, [label, , fmt]]) => <div className="row" key={key}>
          <div className="metric">{label}</div>
          {rows.map(r => {
            const m = r.metrics[key];
            const isBest = best[key] !== null && Math.abs(m.live - best[key]) < 1e-12 && key !== 'compile_time_s';
            return <div key={r.method} className={isBest ? 'best' : ''}>
              {fmt(m.live)}
              {m.matches !== null && <span className={`check ${m.matches ? 'yes' : 'no'}`}
                title={m.matches ? `matches published value ${fmt(m.published)}` : `published: ${fmt(m.published)}`}>
                {m.matches ? '✓' : '✗'}</span>}
            </div>;
          })}
        </div>)}
      </div>
      <p className="footnote">✓ = identical to the CSV in evaluation/results (fidelity within 1e-9). Compile time is measured live and not compared.
        GNN-based methods include scoring all 2,520 candidate layouts.</p>
    </section>

    <section className="card chips">
      <div className="cardhead"><div><p className="eyebrow">QUBIT PLACEMENT</p><h2>Where each method put the circuit</h2></div>
        <div className="legend"><span className="sw good"></span>low error <span className="sw bad"></span>high error</div></div>
      <div className="chipgrid">{rows.map(r => <Chip key={r.method} row={r} device={options.device} />)}</div>
      <p className="footnote">Coupler colour = two-qubit gate error (0.61%–1.34%); ring colour = readout error (1.6%–5.5%).
        Filled qubits hold logical qubits q0–q4 at the start of the circuit.</p>
    </section>

    <section className="card drawings">
      <div className="cardhead"><div><p className="eyebrow">OUTPUT</p><h2>Compiled circuits</h2></div></div>
      {rows.map(r => <details key={r.method}><summary>{r.label} · {r.metrics.depth.live} depth · {r.metrics.total_gates.live} gates</summary>
        <pre className="drawing">{r.drawing}</pre></details>)}
    </section>
  </>;
}

function Chip({ row, device }) {
  const pos = q => [30 + q.x * 80, 30 + q.y * 80];
  const byId = Object.fromEntries(device.qubits.map(q => [q.id, q]));
  const cx = device.edges.map(e => e.cx_error), ro = device.qubits.map(q => q.readout_error);
  const norm = (v, arr) => (v - Math.min(...arr)) / (Math.max(...arr) - Math.min(...arr));
  const logicalAt = Object.fromEntries((row.layout ?? []).map((p, l) => [p, l]));
  const used = row.layout ?? [];
  const avgRO = used.length ? used.reduce((s, p) => s + byId[p].readout_error, 0) / used.length : null;

  return <div className="chip">
    <div className="chiphead"><b>{row.label}</b><span>{row.metrics.swaps.live} SWAP{row.metrics.swaps.live === 1 ? '' : 's'}</span></div>
    <svg viewBox="0 0 220 220" role="img" aria-label={`${row.label} layout ${used.join(',')}`}>
      {device.edges.map(e => {
        const [x1, y1] = pos(byId[e.a]), [x2, y2] = pos(byId[e.b]);
        return <line key={`${e.a}-${e.b}`} x1={x1} y1={y1} x2={x2} y2={y2} stroke={mix(norm(e.cx_error, cx))} strokeWidth="5" strokeLinecap="round" opacity="0.85">
          <title>{`coupler ${e.a}-${e.b}: CX error ${(e.cx_error * 100).toFixed(2)}%`}</title></line>;
      })}
      {device.qubits.map(q => {
        const [x, y] = pos(q), l = logicalAt[q.id];
        return <g key={q.id}>
          <circle cx={x} cy={y} r="19" className={l !== undefined ? 'node occupied' : 'node free'} stroke={mix(norm(q.readout_error, ro))} strokeWidth="4">
            <title>{`physical Q${q.id}: readout error ${(q.readout_error * 100).toFixed(1)}%`}</title></circle>
          <text x={x} y={y + 4} textAnchor="middle" className={l !== undefined ? 'logical' : 'phys'}>{l !== undefined ? `q${l}` : `Q${q.id}`}</text>
        </g>;
      })}
    </svg>
    <div className="chipfoot">{used.length ? <>layout [{used.join(', ')}] · avg readout {(avgRO * 100).toFixed(1)}%</> : 'layout unavailable'}
      {row.extra?.gnn_rank && <> · GNN rank {row.extra.gnn_rank}</>}</div>
  </div>;
}

createRoot(document.getElementById('root')).render(<App />);
