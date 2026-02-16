/**
 * Issue Observatory — Chart.js rendering helpers.
 *
 * All exported functions guard against missing canvas elements so they
 * can be called unconditionally from template <script> blocks without
 * crashing on pages where the chart is conditionally absent.
 *
 * Requires: Chart.js 4.x loaded globally (via CDN in base.html).
 */

'use strict';

// ---------------------------------------------------------------------------
// Shared defaults applied to every chart instance.
// ---------------------------------------------------------------------------

const _CHART_DEFAULTS = {
  responsive: true,
  maintainAspectRatio: true,
  plugins: {
    legend: {
      labels: {
        font: { size: 12, family: 'system-ui, sans-serif' },
        color: '#374151',  // gray-700
      },
    },
    tooltip: {
      backgroundColor: '#1f2937',  // gray-800
      titleColor: '#f9fafb',
      bodyColor: '#d1d5db',
      padding: 10,
      cornerRadius: 6,
    },
  },
};

// ---------------------------------------------------------------------------
// Colour palette — consistent across all charts.
// ---------------------------------------------------------------------------

const _PALETTE = [
  '#2563eb', // blue-600
  '#16a34a', // green-600
  '#d97706', // amber-600
  '#9333ea', // purple-600
  '#dc2626', // red-600
  '#0891b2', // cyan-600
  '#ea580c', // orange-600
  '#4f46e5', // indigo-600
];

// ---------------------------------------------------------------------------
// Utility helpers
// ---------------------------------------------------------------------------

/**
 * Resolve a canvas element by ID.
 * Returns null (with a console warning) if the element does not exist.
 *
 * @param {string} canvasId - The `id` attribute of the <canvas> element.
 * @returns {HTMLCanvasElement|null}
 */
function _getCanvas(canvasId) {
  const el = document.getElementById(canvasId);
  if (!el) {
    console.warn(`[charts.js] Canvas element #${canvasId} not found — skipping chart init.`);
    return null;
  }
  return el;
}

/**
 * Destroy an existing Chart.js instance attached to a canvas, if any.
 * This prevents the "Canvas already in use" error when re-initialising.
 *
 * @param {HTMLCanvasElement} canvas
 */
function _destroyExisting(canvas) {
  const existing = Chart.getChart(canvas);
  if (existing) existing.destroy();
}

// ---------------------------------------------------------------------------
// 1. Volume over time — line or bar chart
// ---------------------------------------------------------------------------

/**
 * Render a content-volume-over-time chart.
 *
 * @param {string} canvasId - Target canvas element ID.
 * @param {Object} data - Chart data.
 * @param {string[]} data.labels     - Time labels (ISO dates or display strings).
 * @param {number[]} data.values     - Record counts per label.
 * @param {string}  [data.type]      - 'bar' (default) or 'line'.
 * @param {string}  [data.label]     - Dataset label (default: 'Records').
 * @param {Object}  [options]        - Additional Chart.js options (merged in).
 * @returns {Chart|null}
 */
window.initVolumeChart = function initVolumeChart(canvasId, data, options = {}) {
  const canvas = _getCanvas(canvasId);
  if (!canvas) return null;
  _destroyExisting(canvas);

  const chartType = data.type || 'bar';
  const isLine = chartType === 'line';

  return new Chart(canvas, {
    type: chartType,
    data: {
      labels: data.labels || [],
      datasets: [{
        label: data.label || 'Records',
        data: data.values || [],
        backgroundColor: isLine ? 'rgba(37, 99, 235, 0.15)' : 'rgba(37, 99, 235, 0.7)',
        borderColor: '#2563eb',
        borderWidth: isLine ? 2 : 0,
        fill: isLine,
        tension: isLine ? 0.3 : undefined,
        pointRadius: isLine ? 3 : undefined,
        borderRadius: isLine ? undefined : 3,
      }],
    },
    options: {
      ..._CHART_DEFAULTS,
      scales: {
        x: {
          ticks: { color: '#6b7280', font: { size: 11 }, maxRotation: 45 },
          grid: { display: false },
        },
        y: {
          beginAtZero: true,
          ticks: { color: '#6b7280', font: { size: 11 }, precision: 0 },
          grid: { color: 'rgba(0,0,0,0.05)' },
        },
      },
      ...options,
    },
  });
};

// ---------------------------------------------------------------------------
// 2. Engagement distribution — histogram / bar chart
// ---------------------------------------------------------------------------

/**
 * Render an engagement distribution chart (e.g. shares, likes, comments).
 *
 * @param {string} canvasId - Target canvas element ID.
 * @param {Object} data - Chart data.
 * @param {string[]} data.labels     - Bucket labels (e.g. ['0–10', '11–100', ...]).
 * @param {number[]} data.values     - Count per bucket.
 * @param {string}  [data.label]     - Dataset label (default: 'Engagement').
 * @param {Object}  [options]        - Additional Chart.js options (merged in).
 * @returns {Chart|null}
 */
window.initEngagementChart = function initEngagementChart(canvasId, data, options = {}) {
  const canvas = _getCanvas(canvasId);
  if (!canvas) return null;
  _destroyExisting(canvas);

  return new Chart(canvas, {
    type: 'bar',
    data: {
      labels: data.labels || [],
      datasets: [{
        label: data.label || 'Engagement',
        data: data.values || [],
        backgroundColor: 'rgba(22, 163, 74, 0.7)',  // green-600
        borderColor: '#16a34a',
        borderWidth: 0,
        borderRadius: 3,
      }],
    },
    options: {
      ..._CHART_DEFAULTS,
      scales: {
        x: {
          ticks: { color: '#6b7280', font: { size: 11 } },
          grid: { display: false },
        },
        y: {
          beginAtZero: true,
          ticks: { color: '#6b7280', font: { size: 11 }, precision: 0 },
          grid: { color: 'rgba(0,0,0,0.05)' },
        },
      },
      ...options,
    },
  });
};

// ---------------------------------------------------------------------------
// 3. Arena breakdown — doughnut chart
// ---------------------------------------------------------------------------

/**
 * Render a doughnut chart showing the content breakdown per arena / platform.
 *
 * @param {string} canvasId - Target canvas element ID.
 * @param {Object} data - Chart data.
 * @param {string[]} data.labels     - Arena or platform names.
 * @param {number[]} data.values     - Record counts per arena.
 * @param {Object}  [options]        - Additional Chart.js options (merged in).
 * @returns {Chart|null}
 */
window.initArenaBreakdownChart = function initArenaBreakdownChart(canvasId, data, options = {}) {
  const canvas = _getCanvas(canvasId);
  if (!canvas) return null;
  _destroyExisting(canvas);

  return new Chart(canvas, {
    type: 'doughnut',
    data: {
      labels: data.labels || [],
      datasets: [{
        data: data.values || [],
        backgroundColor: _PALETTE.slice(0, (data.labels || []).length),
        borderWidth: 2,
        borderColor: '#ffffff',
        hoverOffset: 6,
      }],
    },
    options: {
      ..._CHART_DEFAULTS,
      cutout: '60%',
      plugins: {
        ..._CHART_DEFAULTS.plugins,
        legend: {
          ..._CHART_DEFAULTS.plugins.legend,
          position: 'right',
        },
      },
      ...options,
    },
  });
};
