/**
 * Issue Observatory — In-browser network preview using Sigma.js v3 + graphology.
 *
 * Provides a lightweight force-directed graph preview for the analysis dashboard's
 * network tabs (actor co-occurrence, term co-occurrence, bipartite actor-term).
 *
 * Requires (loaded via CDN in analysis/index.html extra_head block):
 *   - graphology UMD  → window.Graph
 *   - sigma UMD       → window.Sigma
 *   - graphology-layout         → window.graphologyLayout
 *   - graphology-layout-forceatlas2 → window.graphologyLayoutForceAtlas2
 *
 * This file exports two functions to the global scope:
 *   window.initNetworkPreview(containerId, graphData, options)
 *   window.destroyNetworkPreview(containerId)
 *
 * The primary network lifecycle (fetching data, managing Alpine state, zoom controls)
 * is handled by the networkPreview() Alpine component defined inline in
 * analysis/index.html.  This file provides the reusable rendering primitive that
 * the Alpine component calls via _renderSigma(), plus the documented API contract
 * for the expected JSON shape.
 *
 * ---- Expected JSON shape from the backend --------------------------------
 *
 *   GET /analysis/{run_id}/network/{network_type}
 *
 *   {
 *     "nodes": [
 *       {
 *         "id":        string,           // unique node identifier
 *         "label":     string,           // display label (truncated to 20 chars in preview)
 *         "node_type": "actor" | "term", // controls node colour
 *         "weight":    number            // optional; used as fallback degree
 *       },
 *       ...
 *     ],
 *     "edges": [
 *       {
 *         "source": string,  // node id
 *         "target": string,  // node id
 *         "weight": number   // co-occurrence count; controls edge thickness
 *       },
 *       ...
 *     ]
 *   }
 *
 * ---- Preview limits ------------------------------------------------------
 *
 *   Graphs with more than MAX_NODES nodes are trimmed to the top-N nodes by
 *   degree before rendering.  The caller (Alpine component) records the raw
 *   count from the API so a warning banner can be shown to the researcher.
 *
 *   MAX_NODES = 100
 *   MAX_EDGES = 200
 */

'use strict';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Maximum nodes to render in the browser preview. */
const NETWORK_PREVIEW_MAX_NODES = 100;

/** Maximum edges to render alongside the trimmed node set. */
const NETWORK_PREVIEW_MAX_EDGES = 200;

/** Node colour for sender/actor-type nodes (brand purple). */
const COLOR_ACTOR = '#7C3AED';

/** Node colour for keyword/term-type nodes (brand gold/amber). */
const COLOR_TERM  = '#D4C020';

/** Node colour for entity-type nodes (green/teal). */
const COLOR_ENTITY = '#16A34A';

/** Entity sub-type colours. */
const COLOR_ENTITY_PERSON = '#EA580C';  // orange
const COLOR_ENTITY_ORG    = '#DC2626';  // red
const COLOR_ENTITY_GPE    = '#16A34A';  // green
const COLOR_ENTITY_LOC    = '#16A34A';  // green

/** Node colour for platform-type nodes (blue). */
const COLOR_PLATFORM = '#2563EB';

/** Node colour for domain-type nodes (sky/cyan — distinct from the platform
 *  blue, the entity greens, and the keyword gold). */
const COLOR_DOMAIN = '#0EA5E9';

/** Default node colour when node_type is absent. */
const COLOR_DEFAULT = '#6B5F80';

/** Edge colour (purple-tinted at 25% opacity). */
const COLOR_EDGE = 'rgba(139, 92, 246, 0.5)';

// ---------------------------------------------------------------------------
// Internal instance registry
// ---------------------------------------------------------------------------

/** @type {Map<string, import('sigma').Sigma>} */
const _instances = new Map();

/** @type {Map<string, object>} graph instances for layout control */
const _graphs = new Map();

/** @type {Map<string, object>} FA2 layout supervisor instances */
const _fa2Supervisors = new Map();

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Compute the degree of each node from the edge list.
 *
 * @param {Array<{source: string, target: string}>} edges
 * @returns {Map<string, number>}
 */
function _computeDegree(edges) {
    const deg = new Map();
    edges.forEach(e => {
        deg.set(e.source, (deg.get(e.source) || 0) + 1);
        deg.set(e.target, (deg.get(e.target) || 0) + 1);
    });
    return deg;
}

/** Group-axis node types that must always survive preview trimming.
 *
 *  Bipartite networks have two kinds of nodes: the *grouping* axis
 *  (platforms / senders / actors) and the *item* axis (domains /
 *  keywords / entities).  When a graph has many items but only a
 *  handful of grouping nodes, a naive top-N-by-degree trim happily
 *  drops low-degree platforms (a platform linking to a single domain
 *  gets degree=1 and loses the budget contest to high-degree domains).
 *  Preserving every grouping node is almost always what the researcher
 *  wants, so we reserve their slots in the trim budget.
 */
const _GROUP_NODE_TYPES = new Set(['sender', 'platform', 'actor']);

/**
 * Trim a graph to the top-N nodes by degree and the top-M edges that
 * connect those nodes.  Returns a new object — does not mutate the input.
 *
 *  Strategy:
 *  1. Always keep every grouping-axis node (platform/sender/actor).
 *  2. Fill the remaining node budget with the highest-degree item nodes.
 *  3. Sort edges by weight descending before slicing to MAX_EDGES so
 *     the strongest connections survive (previously the slice was
 *     insertion-order which could drop all edges from a small platform).
 *
 * @param {{ nodes: Array, edges: Array }} graphData
 * @returns {{ nodes: Array, edges: Array }}
 */
function _trimGraph(graphData) {
    const nodes = graphData.nodes || [];
    const edges = graphData.edges || [];

    if (nodes.length <= NETWORK_PREVIEW_MAX_NODES) {
        if (edges.length <= NETWORK_PREVIEW_MAX_EDGES) {
            return { nodes, edges };
        }
        // Too many edges — keep strongest by weight.
        const sortedEdges = [...edges].sort(
            (a, b) => (b.weight || 0) - (a.weight || 0)
        ).slice(0, NETWORK_PREVIEW_MAX_EDGES);
        return { nodes, edges: sortedEdges };
    }

    const deg = _computeDegree(edges);

    // 1. Always keep group-axis nodes.
    const groupNodes = nodes.filter(n => _GROUP_NODE_TYPES.has(n.node_type));
    const itemNodes  = nodes.filter(n => !_GROUP_NODE_TYPES.has(n.node_type));

    // 2. Fill the remaining budget with the top-degree item nodes.
    const itemBudget = Math.max(0, NETWORK_PREVIEW_MAX_NODES - groupNodes.length);
    const topItems = [...itemNodes].sort(
        (a, b) => (deg.get(b.id) || b.weight || 0) - (deg.get(a.id) || a.weight || 0)
    ).slice(0, itemBudget);

    const topNodes = [...groupNodes, ...topItems];
    const nodeSet  = new Set(topNodes.map(n => n.id));

    // 3. Edge filter + weight-priority slice.  Previously this was
    // insertion-order, which meant small platforms could lose all their
    // edges when a few high-degree hubs consumed the 200-edge budget.
    const filteredEdges = edges
        .filter(e => nodeSet.has(e.source) && nodeSet.has(e.target))
        .sort((a, b) => (b.weight || 0) - (a.weight || 0))
        .slice(0, NETWORK_PREVIEW_MAX_EDGES);

    return { nodes: topNodes, edges: filteredEdges };
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Initialise a Sigma.js force-directed graph preview inside a container element.
 *
 * If a previous sigma instance exists for the same containerId it is killed
 * before creating the new one (prevents WebGL context leaks on re-render).
 *
 * @param {string} containerId
 *   The `id` attribute of the DOM element that will host the sigma canvas.
 *   The element must have explicit dimensions (height set via CSS or inline style).
 *
 * @param {{ nodes: Array, edges: Array }} graphData
 *   Graph data in the format returned by the backend JSON endpoints.
 *   See the file-level JSDoc for the full expected shape.
 *
 * @param {Object} [options]
 * @param {boolean} [options.trim=true]
 *   Whether to apply MAX_NODES/MAX_EDGES trimming before rendering.
 *   Set to false only when the caller has already trimmed the data.
 * @param {boolean} [options.runLayout=true]
 *   Whether to run the ForceAtlas2 layout algorithm.  Disable for very large
 *   graphs or when positions are already present in the node data.
 * @param {number}  [options.layoutIterations=150]
 *   Number of ForceAtlas2 iterations to run synchronously.
 * @param {number}  [options.gravity=1]
 *   ForceAtlas2 gravity setting — higher pulls nodes toward the center.
 * @param {number}  [options.scalingRatio=2]
 *   ForceAtlas2 scaling ratio — higher pushes nodes further apart.
 *
 * @returns {import('sigma').Sigma | null}
 *   The sigma instance, or null if the container is not found or the required
 *   libraries are not loaded.
 */
window.initNetworkPreview = function initNetworkPreview(containerId, graphData, options = {}) {
    const {
        trim            = true,
        runLayout       = true,
        layoutIterations = 150,
        gravity         = 1,
        scalingRatio    = 2,
    } = options;

    // Guard: required libraries must be loaded via CDN before calling this.
    if (typeof window.Sigma === 'undefined' || typeof window.Graph === 'undefined') {
        console.warn('[network_preview] sigma.js or graphology not loaded — skipping render.');
        return null;
    }

    const container = document.getElementById(containerId);
    if (!container) {
        console.warn(`[network_preview] Container #${containerId} not found.`);
        return null;
    }

    // Kill any previous instance on the same container.
    if (_instances.has(containerId)) {
        _instances.get(containerId).kill();
        _instances.delete(containerId);
    }

    // Handle empty data gracefully — caller should show a "No data" placeholder.
    const rawNodes = graphData.nodes || [];
    const rawEdges = graphData.edges || [];
    if (rawNodes.length === 0) {
        return null;
    }

    // Trim oversized graphs so the browser stays responsive.
    const data = trim ? _trimGraph({ nodes: rawNodes, edges: rawEdges }) : { nodes: rawNodes, edges: rawEdges };

    // Build the graphology graph object.
    const graph = new window.Graph({ type: 'undirected', multi: false });

    // Compute degree for node sizing.
    const degree = _computeDegree(data.edges);

    // Add nodes with visual attributes.
    data.nodes.forEach(node => {
        const deg  = degree.get(node.id) || node.weight || 1;
        // Scale node size: items cap at 6px; group-axis nodes (platforms,
        // senders, actors) start larger and cap at 10px so a 1-edge
        // platform is still clearly readable against the item nodes.
        const isGroup = _GROUP_NODE_TYPES.has(node.node_type);
        const size = isGroup
            ? Math.min(5 + deg * 0.35, 10)
            : Math.min(2 + deg * 0.5, 6);
        // Determine colour from node_type and entity_type.
        let color;
        if (node.node_type === 'actor' || node.node_type === 'sender') {
            color = COLOR_ACTOR;
        } else if (node.node_type === 'platform') {
            color = COLOR_PLATFORM;
        } else if (node.node_type === 'term' || node.node_type === 'keyword') {
            color = COLOR_TERM;
        } else if (node.node_type === 'entity') {
            const et = node.entity_type || '';
            color = et === 'PERSON' ? COLOR_ENTITY_PERSON
                  : et === 'ORG'    ? COLOR_ENTITY_ORG
                  : (et === 'GPE' || et === 'LOC') ? COLOR_ENTITY_GPE
                  : COLOR_ENTITY;
        } else if (node.node_type === 'domain') {
            color = COLOR_DOMAIN;
        } else {
            color = COLOR_DEFAULT;
        }
        // Truncate long labels to keep the graph readable.
        const maxLabelLen = 30;
        const label = node.label
            ? (node.label.length > maxLabelLen ? node.label.substring(0, maxLabelLen) + '...' : node.label)
            : node.id;

        graph.addNode(node.id, {
            label,
            size,
            color,
            // Initial random position — ForceAtlas2 will refine this.
            x: Math.random(),
            y: Math.random(),
        });
    });

    // Add edges, skipping any that reference nodes not in the trimmed set.
    data.edges.forEach(edge => {
        if (!graph.hasNode(edge.source) || !graph.hasNode(edge.target)) return;
        if (graph.hasEdge(edge.source, edge.target)) return;  // Skip duplicate edges.
        const weight = edge.weight || 1;
        graph.addEdge(edge.source, edge.target, {
            weight,
            // Edge thickness proportional to co-occurrence weight (min 1.5 px, capped at 5 px).
            size: Math.min(1.5 + weight * 0.3, 5),
            color: COLOR_EDGE,
        });
    });

    // Apply ForceAtlas2 layout synchronously for graphs up to 500 nodes
    // (the backend's MAX_NODES cap after reduction). Larger graphs use
    // random layout to avoid blocking the main thread.
    if (runLayout) {
        if (graph.order <= 500 && typeof window.graphologyLayoutForceAtlas2 !== 'undefined') {
            try {
                // Bulk iterations: fast structural layout
                window.graphologyLayoutForceAtlas2.assign(graph, {
                    iterations: layoutIterations,
                    settings: {
                        gravity,
                        scalingRatio,
                        slowDown: 5,
                        barnesHutOptimize: graph.order > 100,
                    },
                });
                // Short pass: resolve node overlaps
                window.graphologyLayoutForceAtlas2.assign(graph, {
                    iterations: 50,
                    settings: {
                        gravity,
                        scalingRatio,
                        adjustSizes: true,
                        slowDown: 10,
                        barnesHutOptimize: graph.order > 100,
                    },
                });
            } catch (layoutErr) {
                console.warn('[network_preview] ForceAtlas2 failed, using random layout:', layoutErr);
                if (typeof window.graphologyLayout !== 'undefined') {
                    window.graphologyLayout.random.assign(graph);
                }
            }
        } else if (typeof window.graphologyLayout !== 'undefined') {
            window.graphologyLayout.random.assign(graph);
        }
    }

    // Instantiate the sigma renderer.
    const sigma = new window.Sigma(graph, container, {
        renderEdgeLabels: false,
        // Lower threshold so labels are visible at default zoom.
        // A value of 1 renders labels for all nodes with a rendered size of ≥ 1px.
        labelRenderedSizeThreshold: 1,
        labelSize: 12,
        labelFont: 'Inter, system-ui, sans-serif',
        defaultEdgeColor: 'rgba(139, 92, 246, 0.5)',
        defaultEdgeType: 'line',
        // Prevents sigma from throwing when the container has no dimensions yet.
        allowInvalidContainer: true,
    });

    // Hover interactions: highlight hovered node and its neighbours.
    let hoveredNode = null;
    sigma.on('enterNode', ({ node }) => {
        hoveredNode = node;
        sigma.setSetting('nodeReducer', (n, data) => {
            if (n === hoveredNode || graph.neighbors(hoveredNode).includes(n)) {
                return { ...data, highlighted: true };
            }
            return { ...data, color: 'rgba(107, 95, 128, 0.25)', label: '' };
        });
        sigma.setSetting('edgeReducer', (edge, data) => {
            if (graph.extremities(edge).includes(hoveredNode)) {
                return { ...data, color: '#A855F7', size: (data.size || 1) + 1 };
            }
            return { ...data, color: 'rgba(139, 92, 246, 0.15)' };
        });
    });

    sigma.on('leaveNode', () => {
        hoveredNode = null;
        sigma.setSetting('nodeReducer', null);
        sigma.setSetting('edgeReducer', null);
    });

    // Store instances for later retrieval.
    _instances.set(containerId, sigma);
    _graphs.set(containerId, graph);
    return sigma;
};

/**
 * Kill and remove the sigma instance registered for a given container.
 * Safe to call even if no instance exists for the container.
 *
 * @param {string} containerId - The container element `id`.
 */
window.destroyNetworkPreview = function destroyNetworkPreview(containerId) {
    // Stop any running FA2 layout
    if (_fa2Supervisors.has(containerId)) {
        try { _fa2Supervisors.get(containerId).stop(); } catch (_e) { /* ignore */ }
        _fa2Supervisors.delete(containerId);
    }
    if (_instances.has(containerId)) {
        _instances.get(containerId).kill();
        _instances.delete(containerId);
    }
    _graphs.delete(containerId);
};

/**
 * Toggle ForceAtlas2 layout on/off for a given container.
 * Returns true if layout is now running, false if stopped.
 *
 * @param {string} containerId
 * @param {Object} [opts]
 * @param {number} [opts.gravity=1]
 * @param {number} [opts.scalingRatio=2]
 * @returns {boolean}
 */
window.toggleFA2Layout = function toggleFA2Layout(containerId, opts = {}) {
    const { gravity = 1, scalingRatio = 2 } = opts;

    // If FA2 is already running, stop it
    if (_fa2Supervisors.has(containerId)) {
        const supervisor = _fa2Supervisors.get(containerId);
        try { supervisor.stop(); } catch (_e) { /* ignore */ }
        _fa2Supervisors.delete(containerId);
        return false;
    }

    // Start FA2
    const graph = _graphs.get(containerId);
    if (!graph) {
        console.warn('[network_preview] No graph for', containerId);
        return false;
    }

    const FA2 = window.graphologyLayoutForceAtlas2;
    if (!FA2) {
        console.warn('[network_preview] ForceAtlas2 not available');
        return false;
    }

    const settings = { gravity, scalingRatio, slowDown: 5, barnesHutOptimize: graph.order > 100 };

    // Create a web worker supervisor for non-blocking layout
    // Fall back to a requestAnimationFrame loop if workers aren't available
    try {
        const layout = new FA2.ForceAtlas2Layout(graph, { settings });
        layout.start();
        _fa2Supervisors.set(containerId, layout);
        return true;
    } catch (_e) {
        // Fallback: run iterations in rAF loop
        let running = true;
        const controller = {
            stop() { running = false; },
        };
        function step() {
            if (!running) return;
            FA2.assign(graph, { iterations: 1, settings });
            requestAnimationFrame(step);
        }
        requestAnimationFrame(step);
        _fa2Supervisors.set(containerId, controller);
        return true;
    }
};

/**
 * Re-run ForceAtlas2 layout from random positions with new settings.
 * Stops any running live layout, randomises all node positions, then
 * runs a fixed number of synchronous FA2 iterations.
 *
 * @param {string} containerId
 * @param {Object} [opts]
 * @param {number} [opts.gravity=1]
 * @param {number} [opts.scalingRatio=2]
 * @param {number} [opts.iterations=200]
 */
window.rerunFA2Layout = function rerunFA2Layout(containerId, opts = {}) {
    const { gravity = 1, iterations = 500 } = opts;

    // Stop any running live layout first
    if (_fa2Supervisors.has(containerId)) {
        try { _fa2Supervisors.get(containerId).stop(); } catch (_e) { /* ignore */ }
        _fa2Supervisors.delete(containerId);
    }

    const graph = _graphs.get(containerId);
    if (!graph) return;

    const FA2 = window.graphologyLayoutForceAtlas2;
    if (!FA2) return;

    // Randomise all node positions so the layout starts fresh
    graph.forEachNode((node) => {
        graph.setNodeAttribute(node, 'x', Math.random());
        graph.setNodeAttribute(node, 'y', Math.random());
    });

    try {
        // Bulk: fast structural layout
        FA2.assign(graph, {
            iterations,
            settings: {
                gravity,
                scalingRatio: 2,
                slowDown: 1,
                barnesHutOptimize: graph.order > 100,
            },
        });
        // Short pass: resolve overlaps
        FA2.assign(graph, {
            iterations: 50,
            settings: {
                gravity,
                scalingRatio: 2,
                adjustSizes: true,
                slowDown: 10,
                barnesHutOptimize: graph.order > 100,
            },
        });
    } catch (err) {
        console.warn('[network_preview] FA2 rerun failed:', err);
    }
};

/**
 * Set the camera zoom level for a sigma instance.
 * Lower ratio = zoomed in = nodes appear further apart.
 *
 * @param {string} containerId
 * @param {number} spread — 1.0 = default, >1 = spread out, <1 = compact.
 */
window.setNetworkSpread = function setNetworkSpread(containerId, spread) {
    const sigma = _instances.get(containerId);
    if (!sigma) return;
    // Camera ratio is inverse of spread: higher spread = lower ratio = zoomed in
    sigma.getCamera().setState({ ratio: 1 / spread });
};

/**
 * Check if FA2 is currently running for a container.
 * @param {string} containerId
 * @returns {boolean}
 */
window.isFA2Running = function isFA2Running(containerId) {
    return _fa2Supervisors.has(containerId);
};
