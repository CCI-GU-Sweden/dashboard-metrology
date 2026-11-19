/* Interactive, unit-safe measurement history. */
(function () {
  'use strict';

  function escapeText(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, character => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    })[character]);
  }

  function metricKey(row) {
    return JSON.stringify([row.category, row.measurement_type, row.unit || '']);
  }

  function buildTraces(rows, selected) {
    const groups = new Map();
    rows.filter(row => metricKey(row) === selected).forEach(row => {
      const key = row.lens_id == null ? 'unknown' : String(row.lens_id);
      if (!groups.has(key)) {
        const lens = row.magnification || 'No lens';
        const na = row.numerical_aperture == null ? '' : `, NA ${row.numerical_aperture}`;
        groups.set(key, {name: escapeText(lens + na), x: [], y: [], text: [], mode: 'lines+markers', type: 'scatter'});
      }
      const trace = groups.get(key);
      trace.x.push(row.measured_at);
      trace.y.push(row.value);
      trace.text.push(escapeText(`${row.status || ''} · ${row.has_acquisition_time ? 'acquisition' : 'import'} time`));
    });
    return Array.from(groups.values()).map(trace => ({
      ...trace, hovertemplate: '%{x}<br>%{y}<br>%{text}<extra>%{fullData.name}</extra>'
    }));
  }

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = {metricKey, buildTraces, escapeText};
  }
  if (typeof document === 'undefined') return;

  const container = document.getElementById('metrology-history');
  if (!container) return;
  const selector = document.getElementById('history-metric');
  const status = document.getElementById('history-status');
  const chart = document.getElementById('history-chart');

  fetch(container.dataset.url, {credentials: 'same-origin', headers: {'Accept': 'application/json'}})
    .then(response => {
      if (!response.ok) throw new Error('Unable to load measurement history.');
      return response.json();
    })
    .then(data => {
      const rows = data.measurements.filter(row => row.measured_at && Number.isFinite(row.value));
      const metrics = new Map();
      rows.forEach(row => {
        const key = metricKey(row);
        if (!metrics.has(key)) metrics.set(key, `${row.category} · ${row.measurement_type}${row.unit ? ` (${row.unit})` : ''}`);
      });
      selector.replaceChildren();
      if (!metrics.size) {
        const option = document.createElement('option');
        option.textContent = 'No measurements available';
        selector.append(option);
        status.textContent = 'No dated measurements available for this selection.';
        return;
      }
      Array.from(metrics.entries()).sort((a, b) => a[1].localeCompare(b[1])).forEach(([key, label]) => {
        const option = document.createElement('option');
        option.value = key;
        option.textContent = label;
        selector.append(option);
      });
      selector.disabled = false;
      status.textContent = data.truncated
        ? 'Showing the most recent 5,000 dated measurements. Zoom and hover for details.'
        : 'Zoom, pan, and hover for details. Unspecified acquisition dates use import time.';
      function draw() {
        if (!window.Plotly) {
          status.textContent = 'The chart could not be loaded. Measurements remain available in the table below.';
          return;
        }
        const [, name, unit] = JSON.parse(selector.value);
        const dark = document.documentElement.getAttribute('data-theme') === 'dark';
        Plotly.react(chart, buildTraces(rows, selector.value), {
          xaxis: {title: {text: 'Date'}, type: 'date'},
          yaxis: {title: {text: escapeText(name + (unit ? ` (${unit})` : ''))}, automargin: true},
          margin: {l: 70, r: 20, t: 20, b: 65},
          paper_bgcolor: 'transparent', plot_bgcolor: 'transparent',
          font: {color: dark ? '#e5e7eb' : '#243247'},
          legend: {orientation: 'h'}, uirevision: selector.value
        }, {responsive: true, displaylogo: false});
      }
      selector.addEventListener('change', draw);
      draw();
    })
    .catch(() => { status.textContent = 'Unable to load measurement history. The table below remains available.'; });
}());
