const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {metricKey, buildTraces, escapeText} = require('../dashboard_metrology/static/dashboard_metrology/history.js');

test('separates distinct units and categories and groups lenses', () => {
  const rows = [
    {category: 'PSF', measurement_type: 'X', unit: 'µm', lens_id: 1, magnification: '40x', value: 1, measured_at: '2025-01-01', has_acquisition_time: true},
    {category: 'PSF', measurement_type: 'X', unit: 'µm', lens_id: 2, magnification: '63x', value: 2, measured_at: '2025-01-02'},
    {category: 'PSF', measurement_type: 'X', unit: 'nm', lens_id: 1, value: 1000, measured_at: '2025-01-01'},
    {category: 'Other', measurement_type: 'X', unit: 'µm', lens_id: 1, value: 4, measured_at: '2025-01-01'}
  ];
  const traces = buildTraces(rows, metricKey(rows[0]));
  assert.equal(traces.length, 2);
  assert.deepEqual(traces.flatMap(trace => trace.y), [1, 2]);
  assert.match(traces[0].text[0], /acquisition/);
  assert.match(traces[1].text[0], /import/);
});

test('escapes text placed in Plotly labels and hover content', () => {
  assert.equal(escapeText('<script>&'), '&lt;script&gt;&amp;');
  const row = {category: 'X', measurement_type: 'Y', unit: '', lens_id: 1, magnification: '<b>x</b>', status: '<script>', value: 2, measured_at: '2025-01-01'};
  const trace = buildTraces([row], metricKey(row))[0];
  assert.equal(trace.name, '&lt;b&gt;x&lt;/b&gt;');
  assert.match(trace.text[0], /&lt;script&gt;/);
});

test('renders a chart and lets the user switch metrics', async () => {
  const elements = {
    'metrology-history': {dataset: {url: '/metrology/microscopes/1/history/'}},
    'history-metric': {
      options: [], disabled: true, listeners: {},
      replaceChildren() { this.options = []; },
      append(option) { this.options.push(option); if (this.options.length === 1) this.value = option.value; },
      addEventListener(type, callback) { this.listeners[type] = callback; }
    },
    'history-status': {textContent: ''}, 'history-chart': {},
    'history-mode': {value: 'value', listeners: {}, addEventListener(type, callback) { this.listeners[type] = callback; }}
  };
  const plots = [];
  const rows = [
    {category: 'PSF', measurement_type: 'X', unit: 'µm', lens_id: 1, value: 1, measured_at: '2025-01-01'},
    {category: 'PSF', measurement_type: 'Y', unit: 'µm', lens_id: 1, value: 2, score: 0.8, measured_at: '2025-01-01'}
  ];
  const plotly = {react: (element, traces) => plots.push(traces)};
  const context = {
    document: {getElementById: id => elements[id], createElement: () => ({}), documentElement: {getAttribute: () => 'light'}},
    window: {Plotly: plotly}, Plotly: plotly,
    fetch: async () => ({ok: true, json: async () => ({measurements: rows, truncated: false})}),
    Map, JSON, Number, String, Array
  };
  vm.runInNewContext(fs.readFileSync(require.resolve('../dashboard_metrology/static/dashboard_metrology/history.js'), 'utf8'), context);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(elements['history-metric'].options.length, 2);
  assert.equal(elements['history-metric'].disabled, false);
  assert.equal(plots.length, 1);
  elements['history-metric'].value = elements['history-metric'].options[1].value;
  elements['history-metric'].listeners.change();
  assert.equal(plots.length, 2);
  assert.equal(plots[1][0].y[0], 2);
  elements['history-mode'].value = 'score';
  elements['history-mode'].listeners.change();
  assert.equal(plots[2][0].y[0], 0.8);
});
