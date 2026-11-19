(function () {
  'use strict';
  const chart = document.getElementById('score-chart');
  if (!chart) return;
  const points = JSON.parse(document.getElementById('metrology-score-history').textContent);
  const microscopes = JSON.parse(document.getElementById('metrology-microscope-data').textContent);
  const status = document.getElementById('score-chart-status');
  if (!points.length) {
    status.textContent = 'Not enough comparable measurements to calculate scores yet.';
    return;
  }
  if (!window.Plotly) {
    status.textContent = 'The score graph could not be loaded. Microscope cards remain available above.';
    return;
  }
  function escapeText(value) { return String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c]); }
  const traces = microscopes.map(microscope => {
    const rows = points.filter(point => point.microscope_id === microscope.id).sort((a, b) => a.day.localeCompare(b.day));
    return {name: escapeText(microscope.name), x: rows.map(row => row.day), y: rows.map(row => row.score),
      customdata: rows.map(() => microscope.url), type: 'scatter', mode: 'lines+markers',
      hovertemplate: '%{x}<br>Score: %{y:.2f}<extra>%{fullData.name}</extra>'};
  }).filter(trace => trace.x.length);
  const theme = window.dashboardTheme?.plotlyLayout?.() || {};
  Plotly.newPlot(chart, traces, {...theme, margin: {l: 55, r: 20, t: 15, b: 55},
    xaxis: {...theme.xaxis, title: {text: 'Date'}, type: 'date'},
    yaxis: {...theme.yaxis, title: {text: 'Score'}, range: [0, 1.05]},
    legend: {orientation: 'h'}, clickmode: 'event+select',
    shapes: [0.7, 0.4].map((value, index) => ({type: 'line', xref: 'paper', x0: 0, x1: 1, y0: value, y1: value, line: {color: index ? '#cf4d4d' : '#d89a20', dash: 'dash', width: 1}}))
  }, {responsive: true, displaylogo: false}).then(() => {
    chart.on('plotly_click', event => {
      const url = event.points?.[0]?.customdata;
      if (typeof url === 'string' && /^\/metrology\/microscopes\/\d+\/$/.test(url)) window.location.assign(url);
    });
  });
}());
