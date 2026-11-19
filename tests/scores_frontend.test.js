const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

test('plots per-microscope scores and allows only local microscope navigation', async () => {
  const listeners = {};
  const chart = {on: (name, callback) => { listeners[name] = callback; }};
  const elements = {
    'score-chart': chart,
    'score-chart-status': {textContent: ''},
    'metrology-score-history': {textContent: JSON.stringify([{microscope_id: 1, day: '2026-01-01', score: 0.8}])},
    'metrology-microscope-data': {textContent: JSON.stringify([{id: 1, name: '<scope>', url: '/metrology/microscopes/1/'}])}
  };
  let traces, destination;
  const plotly = {newPlot: (node, data) => { traces = data; return Promise.resolve(); }};
  const context = {document: {getElementById: id => elements[id]},
    window: {Plotly: plotly, location: {assign: value => { destination = value; }}},
    Plotly: plotly, JSON, String};
  vm.runInNewContext(fs.readFileSync(require.resolve('../dashboard_metrology/static/dashboard_metrology/scores.js'), 'utf8'), context);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(traces[0].name, '&lt;scope&gt;');
  assert.equal(traces[0].y[0], 0.8);
  listeners.plotly_click({points: [{customdata: '/metrology/microscopes/1/'}]});
  assert.equal(destination, '/metrology/microscopes/1/');
  listeners.plotly_click({points: [{customdata: 'https://evil.example/'}]});
  assert.equal(destination, '/metrology/microscopes/1/');
});
