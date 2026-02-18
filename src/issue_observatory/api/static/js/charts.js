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
          title: data.xLabel
            ? { display: true, text: data.xLabel, color: '#6b7280', font: { size: 11 } }
            : { display: false },
        },
        y: {
          beginAtZero: true,
          ticks: { color: '#6b7280', font: { size: 11 }, precision: 0 },
          grid: { color: 'rgba(0,0,0,0.05)' },
          title: data.yLabel
            ? { display: true, text: data.yLabel, color: '#6b7280', font: { size: 11 } }
            : { display: false },
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
// ---------------------------------------------------------------------------
// 4. Top actors — horizontal bar chart
// ---------------------------------------------------------------------------

/**
 * Render a horizontal bar chart of top actors by post count.
 *
 * IP2-061: callers should prefer resolved_name over display_name before building
 * the labels array.  The canonical label-resolution pattern used in the
 * actorsChart Alpine component is:
 *   const label = actor.resolved_name
 *       || actor.author_display_name
 *       || (actor.pseudonymized_author_id?.substring(0, 8) + '...')
 *       || '?';
 * A confirmed identity (resolved_name present) should be visually flagged by
 * appending a Unicode check character (\u2713) to the label.
 *
 * @param {string} canvasId - Target canvas element ID.
 * @param {Object} data - Chart data.
 * @param {string[]} data.labels  - Actor display names (pre-resolved by the caller).
 * @param {number[]} data.values  - Post counts per actor.
 * @param {Object}  [options]     - Additional Chart.js options (merged in).
 * @returns {Chart|null}
 */
window.initActorsChart = function initActorsChart(canvasId, data, options = {}) {
  const canvas = _getCanvas(canvasId);
  if (!canvas) return null;
  _destroyExisting(canvas);

  return new Chart(canvas, {
    type: 'bar',
    data: {
      labels: data.labels || [],
      datasets: [{
        label: 'Posts',
        data: data.values || [],
        backgroundColor: 'rgba(37, 99, 235, 0.7)',
        borderColor: '#2563eb',
        borderWidth: 0,
        borderRadius: 3,
      }],
    },
    options: {
      ..._CHART_DEFAULTS,
      indexAxis: 'y',
      scales: {
        x: {
          beginAtZero: true,
          ticks: { color: '#6b7280', font: { size: 11 }, precision: 0 },
          grid: { color: 'rgba(0,0,0,0.05)' },
          title: data.xLabel
            ? { display: true, text: data.xLabel, color: '#6b7280', font: { size: 11 } }
            : { display: false },
        },
        y: {
          ticks: { color: '#374151', font: { size: 11 } },
          grid: { display: false },
          title: data.yLabel
            ? { display: true, text: data.yLabel, color: '#6b7280', font: { size: 11 } }
            : { display: false },
        },
      },
      ...options,
    },
  });
};

// ---------------------------------------------------------------------------
// 5. Top terms — horizontal bar chart
// ---------------------------------------------------------------------------

/**
 * Render a horizontal bar chart of top search terms by frequency.
 *
 * @param {string} canvasId - Target canvas element ID.
 * @param {Object} data - Chart data.
 * @param {string[]} data.labels  - Term strings.
 * @param {number[]} data.values  - Match counts per term.
 * @param {Object}  [options]     - Additional Chart.js options (merged in).
 * @returns {Chart|null}
 */
window.initTermsChart = function initTermsChart(canvasId, data, options = {}) {
  const canvas = _getCanvas(canvasId);
  if (!canvas) return null;
  _destroyExisting(canvas);

  return new Chart(canvas, {
    type: 'bar',
    data: {
      labels: data.labels || [],
      datasets: [{
        label: 'Matches',
        data: data.values || [],
        backgroundColor: 'rgba(217, 119, 6, 0.7)',  // amber-600
        borderColor: '#d97706',
        borderWidth: 0,
        borderRadius: 3,
      }],
    },
    options: {
      ..._CHART_DEFAULTS,
      indexAxis: 'y',
      scales: {
        x: {
          beginAtZero: true,
          ticks: { color: '#6b7280', font: { size: 11 }, precision: 0 },
          grid: { color: 'rgba(0,0,0,0.05)' },
          title: data.xLabel
            ? { display: true, text: data.xLabel, color: '#6b7280', font: { size: 11 } }
            : { display: false },
        },
        y: {
          ticks: { color: '#374151', font: { size: 11 } },
          grid: { display: false },
          title: data.yLabel
            ? { display: true, text: data.yLabel, color: '#6b7280', font: { size: 11 } }
            : { display: false },
        },
      },
      ...options,
    },
  });
};

// ---------------------------------------------------------------------------
// 6. Engagement statistics — grouped bar chart (mean / median / p95)
// ---------------------------------------------------------------------------

/**
 * Render a grouped bar chart showing engagement statistics per metric.
 *
 * Expects the shape returned by GET /analysis/{run_id}/engagement:
 *   { likes: {mean, median, p95, max}, shares: {...}, comments: {...}, views: {...} }
 *
 * Renders three datasets: mean, median, p95.
 *
 * @param {string} canvasId - Target canvas element ID.
 * @param {Object} data - Engagement distribution dict from the API.
 * @param {Object} [options] - Additional Chart.js options (merged in).
 * @returns {Chart|null}
 */
window.initEngagementStatsChart = function initEngagementStatsChart(canvasId, data, options = {}) {
  const canvas = _getCanvas(canvasId);
  if (!canvas) return null;
  _destroyExisting(canvas);

  const metrics = Object.keys(data);
  if (metrics.length === 0) return null;

  // Extract axis label strings from the options object before spreading it into
  // Chart.js options (xLabel/yLabel are not native Chart.js keys).
  const { xLabel, yLabel, ...remainingOptions } = options;

  return new Chart(canvas, {
    type: 'bar',
    data: {
      labels: metrics,
      datasets: [
        {
          label: 'Mean',
          data: metrics.map(m => data[m] ? (data[m].mean ?? 0) : 0),
          backgroundColor: 'rgba(37, 99, 235, 0.7)',
          borderColor: '#2563eb',
          borderWidth: 0,
          borderRadius: 3,
        },
        {
          label: 'Median',
          data: metrics.map(m => data[m] ? (data[m].median ?? 0) : 0),
          backgroundColor: 'rgba(22, 163, 74, 0.7)',
          borderColor: '#16a34a',
          borderWidth: 0,
          borderRadius: 3,
        },
        {
          label: 'p95',
          data: metrics.map(m => data[m] ? (data[m].p95 ?? 0) : 0),
          backgroundColor: 'rgba(217, 119, 6, 0.7)',
          borderColor: '#d97706',
          borderWidth: 0,
          borderRadius: 3,
        },
      ],
    },
    options: {
      ..._CHART_DEFAULTS,
      scales: {
        x: {
          ticks: { color: '#374151', font: { size: 12 } },
          grid: { display: false },
          title: xLabel
            ? { display: true, text: xLabel, color: '#6b7280', font: { size: 11 } }
            : { display: false },
        },
        y: {
          beginAtZero: true,
          ticks: { color: '#6b7280', font: { size: 11 }, precision: 1 },
          grid: { color: 'rgba(0,0,0,0.05)' },
          title: yLabel
            ? { display: true, text: yLabel, color: '#6b7280', font: { size: 11 } }
            : { display: false },
        },
      },
      ...remainingOptions,
    },
  });
};

// ---------------------------------------------------------------------------
// 7. Multi-arena volume chart — line chart with one dataset per arena
// ---------------------------------------------------------------------------

/**
 * Render a multi-arena volume-over-time line chart.
 *
 * @param {string} canvasId - Target canvas element ID.
 * @param {Object} data - Processed data from the volume endpoint.
 * @param {string[]} data.labels     - Period labels (ISO date strings, sliced to 10 chars).
 * @param {Object[]} data.rows       - Raw API rows [{period, count, arenas: {...}}].
 * @param {string[]} data.arenaNames - Sorted list of arena names.
 * @param {Object}  [options]        - Additional Chart.js options (merged in).
 * @returns {Chart|null}
 */
window.initMultiArenaVolumeChart = function initMultiArenaVolumeChart(canvasId, data, options = {}) {
  const canvas = _getCanvas(canvasId);
  if (!canvas) return null;
  _destroyExisting(canvas);

  const { labels, rows, arenaNames, xLabel, yLabel } = data;

  const datasets = arenaNames.length > 0
    ? arenaNames.map((arena, i) => ({
        label: arena,
        data: rows.map(r => (r.arenas && r.arenas[arena]) ? r.arenas[arena] : 0),
        borderColor: _PALETTE[i % _PALETTE.length],
        backgroundColor: _PALETTE[i % _PALETTE.length] + '26',  // 15% opacity
        borderWidth: 2,
        fill: false,
        tension: 0.3,
        pointRadius: 3,
      }))
    : [{
        label: 'Total records',
        data: rows.map(r => r.count),
        borderColor: '#2563eb',
        backgroundColor: 'rgba(37,99,235,0.1)',
        borderWidth: 2,
        fill: true,
        tension: 0.3,
        pointRadius: 3,
      }];

  return new Chart(canvas, {
    type: 'line',
    data: { labels: labels || [], datasets },
    options: {
      ..._CHART_DEFAULTS,
      scales: {
        x: {
          ticks: { color: '#6b7280', font: { size: 11 }, maxRotation: 45 },
          grid: { display: false },
          title: xLabel
            ? { display: true, text: xLabel, color: '#6b7280', font: { size: 11 } }
            : { display: false },
        },
        y: {
          beginAtZero: true,
          ticks: { color: '#6b7280', font: { size: 11 }, precision: 0 },
          grid: { color: 'rgba(0,0,0,0.05)' },
          title: yLabel
            ? { display: true, text: yLabel, color: '#6b7280', font: { size: 11 } }
            : { display: false },
        },
      },
      ...options,
    },
  });
};

// ---------------------------------------------------------------------------
// 8. Arena breakdown — doughnut chart
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// 9. Emergent terms — horizontal bar chart (green palette, high-precision x axis)
// ---------------------------------------------------------------------------

/**
 * Render a horizontal bar chart of emergent terms by emergence score.
 *
 * Data comes from GET /analysis/{run_id}/emergent-terms:
 *   [{ term: string, score: number, document_frequency: number, is_search_term: boolean }]
 *
 * The inline Alpine fallback in the template also renders this chart directly
 * via Chart.js when this helper is not yet present.  Both paths produce the
 * same visual output — this helper is the canonical implementation.
 *
 * @param {string} canvasId - Target canvas element ID.
 * @param {Object} data - Chart data.
 * @param {string[]} data.labels  - Term strings.
 * @param {number[]} data.values  - Emergence scores per term.
 * @param {string}  [data.xLabel] - X-axis label (default: 'Emergence score').
 * @param {Object}  [options]     - Additional Chart.js options (merged in).
 * @returns {Chart|null}
 */
window.initEmergentTermsChart = function initEmergentTermsChart(canvasId, data, options = {}) {
  const canvas = _getCanvas(canvasId);
  if (!canvas) return null;
  _destroyExisting(canvas);

  return new Chart(canvas, {
    type: 'bar',
    data: {
      labels: data.labels || [],
      datasets: [{
        label: 'Emergence score',
        data: data.values || [],
        // Green-600 distinguishes this chart from the regular terms chart (amber).
        backgroundColor: 'rgba(22, 163, 74, 0.7)',
        borderColor: '#16a34a',
        borderWidth: 0,
        borderRadius: 3,
      }],
    },
    options: {
      ..._CHART_DEFAULTS,
      indexAxis: 'y',
      plugins: {
        ..._CHART_DEFAULTS.plugins,
        legend: { display: false },
      },
      scales: {
        x: {
          beginAtZero: true,
          // Four decimal places for small TF-IDF / BM25-style scores.
          ticks: { color: '#6b7280', font: { size: 11 }, precision: 4 },
          grid: { color: 'rgba(0,0,0,0.05)' },
          title: data.xLabel
            ? { display: true, text: data.xLabel, color: '#6b7280', font: { size: 11 } }
            : { display: true, text: 'Emergence score', color: '#6b7280', font: { size: 11 } },
        },
        y: {
          ticks: { color: '#374151', font: { size: 11 } },
          grid: { display: false },
          title: data.yLabel
            ? { display: true, text: data.yLabel, color: '#6b7280', font: { size: 11 } }
            : { display: false },
        },
      },
      ...options,
    },
  });
};

// ---------------------------------------------------------------------------
// 10. Arena breakdown — doughnut chart
// ---------------------------------------------------------------------------

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
