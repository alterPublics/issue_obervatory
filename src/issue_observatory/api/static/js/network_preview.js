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

/** Node colour for actor-type nodes (blue-500). */
const COLOR_ACTOR = '#3b82f6';

/** Node colour for term-type nodes (amber-500). */
const COLOR_TERM  = '#f59e0b';

/** Default node colour when node_type is absent. */
const COLOR_DEFAULT = '#6b7280';

/** Edge colour (gray-400 at 60 % opacity). */
const COLOR_EDGE = 'rgba(156, 163, 175, 0.6)';

// ---------------------------------------------------------------------------
// Internal instance registry
// ---------------------------------------------------------------------------

/** @type {Map<string, import('sigma').Sigma>} */
const _instances = new Map();

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

/**
 * Trim a graph to the top-N nodes by degree and the top-M edges that
 * connect those nodes.  Returns a new object — does not mutate the input.
 *
 * @param {{ nodes: Array, edges: Array }} graphData
 * @returns {{ nodes: Array, edges: Array }}
 */
function _trimGraph(graphData) {
    const nodes = graphData.nodes || [];
    const edges = graphData.edges || [];

    if (nodes.length <= NETWORK_PREVIEW_MAX_NODES) {
        return {
            nodes,
            edges: edges.length > NETWORK_PREVIEW_MAX_EDGES
                ? edges.slice(0, NETWORK_PREVIEW_MAX_EDGES)
                : edges,
        };
    }

    const deg = _computeDegree(edges);

    // Sort descending by degree (fall back to node.weight for isolated nodes).
    const sorted = [...nodes].sort(
        (a, b) => (deg.get(b.id) || b.weight || 0) - (deg.get(a.id) || a.weight || 0)
    );
    const topNodes  = sorted.slice(0, NETWORK_PREVIEW_MAX_NODES);
    const nodeSet   = new Set(topNodes.map(n => n.id));

    const filteredEdges = edges
        .filter(e => nodeSet.has(e.source) && nodeSet.has(e.target))
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
        // Scale node size: min 5 px, proportional to degree (capped at 25 px).
        const size = Math.min(5 + deg * 1.5, 25);
        // Determine colour from node_type; fall back to default for unknown types.
        const color = node.node_type === 'actor' ? COLOR_ACTOR
                    : node.node_type === 'term'  ? COLOR_TERM
                    : COLOR_DEFAULT;
        // Truncate long labels to keep the graph readable.
        const label = node.label
            ? (node.label.length > 20 ? node.label.substring(0, 20) + '…' : node.label)
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
            // Edge thickness proportional to co-occurrence weight (capped at 4 px).
            size: Math.min(1 + weight * 0.2, 4),
            color: COLOR_EDGE,
        });
    });

    // Apply ForceAtlas2 layout synchronously for graphs below 500 nodes.
    // Larger graphs use random layout to avoid blocking the main thread.
    if (runLayout) {
        if (graph.order < 500 && typeof window.graphologyLayoutForceAtlas2 !== 'undefined') {
            try {
                window.graphologyLayoutForceAtlas2.assign(graph, {
                    iterations: layoutIterations,
                    settings: { gravity: 1, scalingRatio: 2, slowDown: 5 },
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
        // Show node labels only when zoomed in enough to keep the graph readable.
        labelRenderedSizeThreshold: 6,
        labelFont: 'system-ui, sans-serif',
        defaultEdgeColor: 'rgba(156, 163, 175, 0.5)',
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
            return { ...data, color: 'rgba(200,200,200,0.3)', label: '' };
        });
        sigma.setSetting('edgeReducer', (edge, data) => {
            if (graph.extremities(edge).includes(hoveredNode)) {
                return { ...data, color: '#6b7280', size: (data.size || 1) + 1 };
            }
            return { ...data, color: 'rgba(200,200,200,0.15)' };
        });
    });

    sigma.on('leaveNode', () => {
        hoveredNode = null;
        sigma.setSetting('nodeReducer', null);
        sigma.setSetting('edgeReducer', null);
    });

    // Store the instance for later retrieval by destroyNetworkPreview.
    _instances.set(containerId, sigma);
    return sigma;
};

/**
 * Kill and remove the sigma instance registered for a given container.
 * Safe to call even if no instance exists for the container.
 *
 * @param {string} containerId - The container element `id`.
 */
window.destroyNetworkPreview = function destroyNetworkPreview(containerId) {
    if (_instances.has(containerId)) {
        _instances.get(containerId).kill();
        _instances.delete(containerId);
    }
};
