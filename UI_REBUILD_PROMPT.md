# DocVerify Web UI — Rebuild Prompt

> Use this prompt to rebuild the DocVerify web UI to reflect all bug hunt changes.
> The backend API is already updated. This prompt covers the frontend (index.html,
> app.js, style.css) and any new API endpoints needed.

---

## Context

DocVerify is a shipping document cross-reference verification engine. A 27-agent bug
hunt found and fixed 40 bugs. The web UI needs to reflect all these improvements.

**Current state:** 3 files in `docverify/web/static/` — `index.html`, `app.js`, `style.css`.
FastAPI backend at `docverify/web/app.py` + `docverify/web/api.py`.

**Stack:** Vanilla HTML/CSS/JS, no framework. Dark theme. FastAPI backend.

---

## What to Build

### 1. DASHBOARD PAGE — Update

**Current:** Shows 4 stat cards (groups, passed, failed, feedback accuracy) + quick actions + log.

**Changes needed:**

- Add a **"System Health" banner** below the stats grid showing:
  - Test suite: 382/382 passing
  - Bug hunt: 40 bugs found & fixed, 0 regressions
  - Feedback tuner: active/inactive status
  - Last pipeline run timestamp

- Add a **`--clean` toggle** to Quick Actions:
  ```html
  <label class="toggle-label">
    <input type="checkbox" id="opt-clean">
    <span>Clean output before run</span>
  </label>
  ```
  Wire it into `runPipeline()`:
  ```js
  const body = JSON.stringify({
      numeric_tolerance: parseFloat(document.getElementById('cfg-tolerance')?.value) || 0.0,
      use_llm: document.getElementById('cfg-use-llm')?.value === 'true',
      clean: document.getElementById('opt-clean')?.checked || false,
  });
  ```

- Update the **log output** to highlight severity-separated reporting:
  - Lines with "Findings" → red
  - Lines with "Minor Observations" → blue
  - Lines with "All critical fields agree" → green

### 2. RESULTS PAGE — Major Update

**Current:** Shows scorecard + shipment list with findings. Detail view shows all findings in one flat list.

**Changes needed:**

#### 2a. Severity-Separated Detail View

When showing group detail (`showDetail()`), separate findings by severity:

```js
// In showDetail(), after getting findings:
const actionable = findings.filter(f => f.severity === 'HIGH' || f.severity === 'MEDIUM');
const minor = findings.filter(f => f.severity === 'LOW');

let html = '';

// Documents section (unchanged)
html += `<h3>Documents (${docs.length})</h3>`;
// ... existing doc table ...

// Actionable findings
if (actionable.length > 0) {
    html += `<h3 style="color:var(--red)">Findings (${actionable.length})</h3>`;
    html += actionable.map(f => findingCard(f)).join('');
}

// Minor observations
if (minor.length > 0) {
    html += `<h3 style="color:var(--blue)">Minor Observations (${minor.length})</h3>`;
    html += `<div style="font-size:13px;color:var(--text-dim);margin-bottom:12px">
        These are informational only and do not affect the PASS/FAIL verdict.
    </div>`;
    html += minor.map(f => findingCard(f)).join('');
}

// Clean verdict message
if (findings.length === 0) {
    html += '<div style="color:var(--green);padding:12px">✓ All critical fields agree across documents</div>';
}
```

#### 2b. PASS Verdict Display

For PASS verdicts with LOW findings, show:
```
✓ All critical fields agree across 4 documents
[Minor Observations section below]
```

For PASS verdicts with no findings:
```
✓ All shared fields agree across 4 documents
```

For single-doc groups:
```
⚠ Insufficient documents for cross-reference (1 document in group)
No comparison performed.
```

#### 2c. Correction Draft Preview

Add a "Correction Draft" button/card in the detail view for FAIL verdicts:

```js
// After findings section, for FAIL verdicts:
if (data.verdict === 'FAIL' && actionable.length > 0) {
    html += `<h3>Correction Draft</h3>`;
    html += `<div class="log-output" style="max-height:300px">`;
    html += `Dear Partner,\n\n`;
    html += `We have identified the following discrepancies in shipment ${groupId}:\n\n`;
    actionable.forEach((f, i) => {
        html += `${i + 1}. ${f.field}: expected "${f.value_a}", found "${f.value_b}" (${f.severity})\n`;
    });
    html += `\nPlease review and provide corrected documents.\n\nBest regards`;
    html += `</div>`;
}
```

#### 2d. Dashboard Link

Add a button to open the auto-generated dashboard.html:

```html
<button class="btn" onclick="window.open('/data/out/dashboard.html', '_blank')">
    📊 Open Dashboard
</button>
```

This requires a new API endpoint to serve the file (see Section 6).

#### 2e. Shipment List Cards

Update the shipment list to show severity breakdown:

```js
// In the shipment card rendering:
const highCount = s.findings?.filter(f => f.severity === 'HIGH').length || 0;
const medCount = s.findings?.filter(f => f.severity === 'MEDIUM').length || 0;
const lowCount = s.findings?.filter(f => f.severity === 'LOW').length || 0;

// Show: "2 HIGH · 1 MEDIUM · 3 LOW" instead of just "6 finding(s)"
```

### 3. CONFIG PAGE — Updates

**Changes needed:**

- **Ollama URL placeholder**: Change from `http://192.168.1.142:11434` to `http://localhost:11434`

- **Add `--clean` toggle** in Pipeline Settings section:
  ```html
  <div class="form-group">
      <label class="form-label">Clean Output Before Run</label>
      <select class="form-select" id="cfg-clean">
          <option value="false">No (keep previous output)</option>
          <option value="true">Yes (wipe output directory first)</option>
      </select>
  </div>
  ```

- **Add validation feedback** — show inline errors when config values are invalid:
  ```js
  async function saveConfig() {
      const tolerance = parseFloat(document.getElementById('cfg-tolerance').value);
      if (isNaN(tolerance) || tolerance < 0) {
          toast('Numeric tolerance must be a non-negative number', 'error');
          return;
      }
      // ... rest of save logic
  }
  ```

- **Show feedback tuner status** — add a card showing whether tuning overrides are loaded:
  ```html
  <div class="card">
      <div class="card-header">
          <div class="card-title">🔧 Feedback Tuner</div>
      </div>
      <div id="tuner-status">Loading...</div>
  </div>
  ```
  Wire to a new `/api/tuner/status` endpoint (see Section 6).

### 4. DOCUMENTS PAGE — Minor Update

No major changes needed. The path traversal protection is in the backend. Just ensure
error responses are shown gracefully:

```js
// In viewDocument():
if (data.error === 'Access denied') {
    toast('Access denied — invalid file path', 'error');
    return;
}
```

### 5. STYLE UPDATES

Add these CSS utilities:

```css
/* Severity section headers */
.section-findings { color: var(--red); border-left: 3px solid var(--red); padding-left: 12px; }
.section-minor { color: var(--blue); border-left: 3px solid var(--blue); padding-left: 12px; }
.section-clean { color: var(--green); border-left: 3px solid var(--green); padding-left: 12px; }

/* Toggle switch */
.toggle-label {
    display: flex; align-items: center; gap: 8px;
    font-size: 13px; color: var(--text-dim); cursor: pointer;
}
.toggle-label input[type="checkbox"] {
    width: 16px; height: 16px; accent-color: var(--accent);
}

/* Correction draft */
.correction-draft {
    background: var(--bg-input);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 16px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px;
    white-space: pre-wrap;
    max-height: 300px;
    overflow-y: auto;
}

/* System health banner */
.health-banner {
    display: flex; gap: 24px; align-items: center;
    padding: 12px 16px; margin-bottom: 16px;
    background: var(--bg-card); border: 1px solid var(--border);
    border-radius: var(--radius); font-size: 13px;
}
.health-item { display: flex; align-items: center; gap: 6px; }
.health-dot { width: 8px; height: 8px; border-radius: 50%; }
.health-dot.green { background: var(--green); }
.health-dot.yellow { background: var(--yellow); }
.health-dot.red { background: var(--red); }
```

### 6. NEW API ENDPOINTS NEEDED

#### 6a. Serve Dashboard HTML

```python
# In app.py:
@app.get("/api/dashboard")
def api_dashboard():
    """Serve the auto-generated dashboard.html."""
    dashboard_path = OUT_DIR / "dashboard.html"
    if not dashboard_path.exists():
        return {"error": "Dashboard not generated yet. Run the pipeline first."}
    return FileResponse(dashboard_path, media_type="text/html")
```

#### 6b. Tuner Status

```python
# In api.py:
def get_tuner_status() -> dict:
    """Check if feedback tuner overrides are loaded."""
    try:
        from docverify.feedback.tuner import FeedbackTuner
        tuner = FeedbackTuner()
        overrides = tuner.load_overrides()
        return {
            "active": overrides is not None,
            "synonym_boosts": len(overrides.synonym_boosts) if overrides else 0,
            "tolerance_adjustment": overrides.tolerance_adjustment if overrides else None,
        }
    except Exception:
        return {"active": False, "synonym_boosts": 0, "tolerance_adjustment": None}
```

#### 6c. Pipeline Run with Clean Flag

Already supported in backend — just pass `clean=True` in the request body:
```python
# In trigger_pipeline(), add:
if kwargs.get("clean"):
    cmd.append("--clean")
```

And in `app.py`:
```python
@app.post("/api/pipeline/run")
def api_pipeline_run(body: dict = None):
    body = body or {}
    return trigger_pipeline(
        "corpus",
        corpus_dir=body.get("corpus_dir"),
        use_llm=body.get("use_llm", False),
        numeric_tolerance=body.get("numeric_tolerance", 0.0),
        clean=body.get("clean", False),
    )
```

---

## Implementation Order

1. **Style updates** — add CSS utilities (5 min)
2. **Config page** — Ollama URL placeholder, clean toggle, validation (10 min)
3. **Dashboard page** — health banner, clean toggle in quick actions (10 min)
4. **Results page** — severity separation, correction draft, dashboard link (20 min)
5. **New API endpoints** — dashboard serve, tuner status (10 min)
6. **Wire everything** — connect frontend to new endpoints (10 min)

**Total estimated effort: ~60 minutes**

---

## Testing Checklist

- [ ] Dashboard shows 382 tests, not 346
- [ ] "Clean output before run" toggle works
- [ ] Results detail separates HIGH/MEDIUM from LOW findings
- [ ] PASS verdicts show "All critical fields agree" when LOW findings exist
- [ ] Single-doc groups show "Insufficient documents" message
- [ ] Correction draft shows ALL findings, not just the first
- [ ] Dashboard.html link opens the auto-generated dashboard
- [ ] Config page Ollama URL shows localhost, not 192.168.1.142
- [ ] Config validation rejects NaN/negative tolerance
- [ ] Unknown config keys show clear error message
- [ ] Path traversal attempts show "Access denied" gracefully
- [ ] Feedback tuner status displays correctly
