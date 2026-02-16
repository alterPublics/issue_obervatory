"""Content export utilities for the Issue Observatory.

Exports ``content_records`` data to CSV, XLSX, JSON (NDJSON), Parquet, and
GEXF formats.  All format methods are async and return raw bytes ready to be
streamed as an HTTP response or uploaded to object storage.

The ``ContentExporter`` class is format-agnostic: callers pass in a list of
plain dicts (typically produced by a SQLAlchemy ``mappings()`` query result or
a list comprehension over ORM rows).  The exporter does NOT perform database
queries itself — that responsibility stays with the route handler or Celery
task.

Optional dependencies:
    openpyxl  — required for ``export_xlsx``; raises ImportError if missing.
    pyarrow   — required for ``export_parquet``; raises ImportError if missing.

Both are listed as main project dependencies in pyproject.toml (Phase 3 core
feature), so ImportError should never occur in production.  The guard exists
for environments that install a minimal subset of dependencies.

Owned by the DB Engineer.
"""

from __future__ import annotations

import io
import json
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Column definitions
# ---------------------------------------------------------------------------

#: Ordered list of flat columns written by CSV and XLSX exporters.
_FLAT_COLUMNS: list[str] = [
    "platform",
    "arena",
    "content_type",
    "title",
    "text_content",
    "url",
    "author_display_name",
    "published_at",
    "views_count",
    "likes_count",
    "shares_count",
    "comments_count",
    "language",
    "collection_tier",
    "search_terms_matched",
]


def _safe_str(value: Any) -> str:  # noqa: ANN401
    """Coerce a record value to a safe UTF-8 string for CSV/XLSX output.

    Lists (e.g. ``search_terms_matched``) are joined with ``|`` so that each
    row stays a single cell.  None becomes an empty string.

    Args:
        value: Any Python value from a deserialized content record dict.

    Returns:
        A string representation safe for inclusion in a spreadsheet cell.
    """
    if value is None:
        return ""
    if isinstance(value, list):
        return " | ".join(str(v) for v in value)
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


class ContentExporter:
    """Export content records to various file formats.

    All public methods are ``async`` for consistency with the FastAPI/Celery
    calling context, even though the work is CPU-bound (I/O happens via in-memory
    buffers).  If profiling shows that large exports block the event loop, the
    CPU-intensive sections should be wrapped in ``asyncio.to_thread``.

    Typical usage in a route handler::

        exporter = ContentExporter()
        data = await exporter.export_csv(records, include_metadata=True)
        return Response(content=data, media_type="text/csv; charset=utf-8")
    """

    # ------------------------------------------------------------------
    # CSV
    # ------------------------------------------------------------------

    async def export_csv(
        self,
        records: list[dict[str, Any]],
        include_metadata: bool = False,
    ) -> bytes:
        """Export records as a UTF-8 CSV file.

        Columns written in order: platform, arena, content_type, title,
        text_content, url, author_display_name, published_at, views_count,
        likes_count, shares_count, comments_count, language, collection_tier,
        search_terms_matched.  If ``include_metadata`` is True, a final column
        ``raw_metadata`` contains the JSONB payload serialized as a JSON string.

        Args:
            records: List of content record dicts (keys match ORM column names).
            include_metadata: Whether to include the ``raw_metadata`` JSONB
                column as a trailing JSON string column.

        Returns:
            Raw UTF-8 encoded CSV bytes including the BOM marker so that
            Microsoft Excel opens it correctly without charset configuration.
        """
        import csv  # stdlib — always available

        columns = list(_FLAT_COLUMNS)
        if include_metadata:
            columns.append("raw_metadata")

        buf = io.StringIO()
        writer = csv.DictWriter(
            buf,
            fieldnames=columns,
            extrasaction="ignore",
            lineterminator="\r\n",
        )
        writer.writeheader()

        for rec in records:
            row: dict[str, str] = {col: _safe_str(rec.get(col)) for col in columns}
            if include_metadata and "raw_metadata" in columns:
                meta = rec.get("raw_metadata")
                row["raw_metadata"] = json.dumps(meta, ensure_ascii=False) if meta else ""
            writer.writerow(row)

        # UTF-8 BOM so Excel auto-detects encoding for Danish characters (æøå).
        return "\ufeff".encode("utf-8") + buf.getvalue().encode("utf-8")

    # ------------------------------------------------------------------
    # XLSX
    # ------------------------------------------------------------------

    async def export_xlsx(
        self,
        records: list[dict[str, Any]],
        sheet_name: str = "Content",
    ) -> bytes:
        """Export records as an XLSX workbook (UTF-8 safe for Danish æøå).

        The header row is bold and frozen; columns are auto-sized to the
        wider of the header or the longest value in the first 100 rows.

        Args:
            records: List of content record dicts.
            sheet_name: Name of the worksheet tab (max 31 chars, enforced by
                openpyxl automatically).

        Returns:
            Raw XLSX bytes.

        Raises:
            ImportError: If ``openpyxl`` is not installed.
        """
        try:
            import openpyxl
            from openpyxl.styles import Font
        except ImportError as exc:
            raise ImportError(
                "openpyxl is required for XLSX export. "
                "Install it with: pip install 'openpyxl>=3.1,<4.0'"
            ) from exc

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = sheet_name[:31]  # Excel limit

        columns = list(_FLAT_COLUMNS)

        # Write header
        ws.append(columns)
        for cell in ws[1]:
            cell.font = Font(bold=True)
        ws.freeze_panes = "A2"

        # Write data rows
        for rec in records:
            row_values = []
            for col in columns:
                val = rec.get(col)
                if val is None:
                    row_values.append("")
                elif isinstance(val, list):
                    row_values.append(" | ".join(str(v) for v in val))
                elif isinstance(val, datetime):
                    # Keep as datetime so Excel formats it as a date cell.
                    row_values.append(val.replace(tzinfo=None))
                else:
                    row_values.append(val)
            ws.append(row_values)

        # Auto-size columns based on header + first 100 data rows
        for col_idx, col_name in enumerate(columns, start=1):
            col_letter = openpyxl.utils.get_column_letter(col_idx)
            max_len = len(col_name)
            for row_idx in range(2, min(102, ws.max_row + 1)):
                cell_val = ws.cell(row=row_idx, column=col_idx).value
                if cell_val is not None:
                    max_len = max(max_len, len(str(cell_val)))
            ws.column_dimensions[col_letter].width = min(max_len + 2, 80)

        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    # ------------------------------------------------------------------
    # JSON / NDJSON
    # ------------------------------------------------------------------

    async def export_json(self, records: list[dict[str, Any]]) -> bytes:
        """Export records as newline-delimited JSON (NDJSON).

        NDJSON is preferred over a single JSON array for large datasets because
        it can be streamed line-by-line without loading the full payload into
        memory.  Each line is a complete JSON object terminated by ``\\n``.

        Datetime objects are serialized to ISO 8601 strings.  UUID objects are
        serialized to their string representation.

        Args:
            records: List of content record dicts.

        Returns:
            UTF-8 encoded NDJSON bytes.
        """
        import uuid

        def _default(obj: Any) -> str:  # noqa: ANN401
            if isinstance(obj, datetime):
                return obj.isoformat()
            if isinstance(obj, uuid.UUID):
                return str(obj)
            raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

        lines = [
            json.dumps(rec, ensure_ascii=False, default=_default) for rec in records
        ]
        return "\n".join(lines).encode("utf-8")

    # ------------------------------------------------------------------
    # Parquet
    # ------------------------------------------------------------------

    async def export_parquet(self, records: list[dict[str, Any]]) -> bytes:
        """Export records as a Parquet file using pyarrow.

        Schema is inferred from the ``_FLAT_COLUMNS`` list.  Columns are
        typed as ``string`` for text fields; ``int64`` for count fields;
        ``timestamp[us, tz=UTC]`` for temporal fields.  The ``raw_metadata``
        column is omitted from Parquet output because nested JSONB does not
        map cleanly to a columnar schema — callers who need it should use the
        JSON or CSV exporter.

        Args:
            records: List of content record dicts.

        Returns:
            Raw Parquet bytes.

        Raises:
            ImportError: If ``pyarrow`` is not installed.
        """
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
        except ImportError as exc:
            raise ImportError(
                "pyarrow is required for Parquet export. "
                "Install it with: pip install 'pyarrow>=15.0,<16.0'"
            ) from exc

        import uuid

        string_cols = [
            "platform", "arena", "content_type", "title", "text_content",
            "url", "author_display_name", "language", "collection_tier",
        ]
        int_cols = ["views_count", "likes_count", "shares_count", "comments_count"]
        ts_cols = ["published_at"]

        column_data: dict[str, list[Any]] = {col: [] for col in _FLAT_COLUMNS}

        for rec in records:
            for col in _FLAT_COLUMNS:
                val = rec.get(col)
                if col in int_cols:
                    column_data[col].append(int(val) if val is not None else None)
                elif col in ts_cols:
                    if isinstance(val, datetime):
                        # Convert to UTC-aware, then to microseconds timestamp
                        if val.tzinfo is None:
                            val = val.replace(tzinfo=timezone.utc)
                        column_data[col].append(val)
                    else:
                        column_data[col].append(None)
                elif col == "search_terms_matched":
                    if isinstance(val, list):
                        column_data[col].append(val)
                    else:
                        column_data[col].append([])
                elif isinstance(val, uuid.UUID):
                    column_data[col].append(str(val))
                else:
                    column_data[col].append(str(val) if val is not None else None)

        schema_fields = []
        for col in _FLAT_COLUMNS:
            if col in int_cols:
                schema_fields.append(pa.field(col, pa.int64()))
            elif col in ts_cols:
                schema_fields.append(pa.field(col, pa.timestamp("us", tz="UTC")))
            elif col == "search_terms_matched":
                schema_fields.append(pa.field(col, pa.list_(pa.string())))
            else:
                schema_fields.append(pa.field(col, pa.string()))

        schema = pa.schema(schema_fields)
        arrays = []
        for col in _FLAT_COLUMNS:
            if col in int_cols:
                arrays.append(pa.array(column_data[col], type=pa.int64()))
            elif col in ts_cols:
                arrays.append(pa.array(column_data[col], type=pa.timestamp("us", tz="UTC")))
            elif col == "search_terms_matched":
                arrays.append(pa.array(column_data[col], type=pa.list_(pa.string())))
            else:
                arrays.append(pa.array(column_data[col], type=pa.string()))

        table = pa.table(dict(zip(_FLAT_COLUMNS, arrays, strict=True)), schema=schema)
        buf = io.BytesIO()
        pq.write_table(table, buf)
        return buf.getvalue()

    # ------------------------------------------------------------------
    # GEXF (actor co-occurrence network)
    # ------------------------------------------------------------------

    async def export_gexf(self, records: list[dict[str, Any]]) -> bytes:
        """Export an actor co-occurrence network as GEXF for Gephi.

        Graph construction rules:
        - **Nodes**: one per unique ``pseudonymized_author_id``.  Node
          attributes: ``display_name`` (author_display_name), ``platform``,
          ``total_posts`` (record count for that author).
        - **Edges**: two authors are connected if they both appear in records
          linked to the same ``collection_run_id``.  Edge weight = number of
          shared collection runs.  Edge attribute ``shared_terms``: pipe-joined
          union of ``search_terms_matched`` across shared runs.
        - Records where ``pseudonymized_author_id`` is None are skipped.

        The GEXF format targets Gephi 0.9+ (schema version 1.2).

        Args:
            records: List of content record dicts.

        Returns:
            UTF-8 encoded GEXF XML bytes.
        """
        # Build per-author node data and per-run author sets
        author_info: dict[str, dict[str, Any]] = {}
        run_authors: dict[str, set[str]] = defaultdict(set)
        run_terms: dict[str, set[str]] = defaultdict(set)

        for rec in records:
            author_id = rec.get("pseudonymized_author_id")
            if not author_id:
                continue

            if author_id not in author_info:
                author_info[author_id] = {
                    "display_name": rec.get("author_display_name") or "",
                    "platform": rec.get("platform") or "",
                    "total_posts": 0,
                }
            author_info[author_id]["total_posts"] += 1

            run_id = str(rec.get("collection_run_id") or "unknown")
            run_authors[run_id].add(author_id)
            terms = rec.get("search_terms_matched") or []
            run_terms[run_id].update(terms)

        # Build edge co-occurrence map: (author_a, author_b) -> {weight, shared_terms}
        edge_map: dict[tuple[str, str], dict[str, Any]] = defaultdict(
            lambda: {"weight": 0, "shared_terms": set()}
        )

        for run_id, authors in run_authors.items():
            author_list = sorted(authors)
            terms = run_terms.get(run_id, set())
            for i, a in enumerate(author_list):
                for b in author_list[i + 1:]:
                    key = (a, b)
                    edge_map[key]["weight"] += 1
                    edge_map[key]["shared_terms"].update(terms)

        # Build GEXF XML
        gexf = ET.Element(
            "gexf",
            {
                "xmlns": "http://gexf.net/1.3",
                "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
                "xsi:schemaLocation": (
                    "http://gexf.net/1.3 http://gexf.net/1.3/gexf.xsd"
                ),
                "version": "1.3",
            },
        )
        meta = ET.SubElement(gexf, "meta", {"lastmodifieddate": datetime.now(timezone.utc).strftime("%Y-%m-%d")})
        ET.SubElement(meta, "creator").text = "Issue Observatory"
        ET.SubElement(meta, "description").text = "Actor co-occurrence network"

        graph = ET.SubElement(gexf, "graph", {"mode": "static", "defaultedgetype": "undirected"})

        # Node attribute declarations
        node_attrs = ET.SubElement(graph, "attributes", {"class": "node"})
        ET.SubElement(node_attrs, "attribute", {"id": "0", "title": "display_name", "type": "string"})
        ET.SubElement(node_attrs, "attribute", {"id": "1", "title": "platform", "type": "string"})
        ET.SubElement(node_attrs, "attribute", {"id": "2", "title": "total_posts", "type": "integer"})

        # Edge attribute declarations
        edge_attrs = ET.SubElement(graph, "attributes", {"class": "edge"})
        ET.SubElement(edge_attrs, "attribute", {"id": "0", "title": "weight", "type": "float"})
        ET.SubElement(edge_attrs, "attribute", {"id": "1", "title": "shared_terms", "type": "string"})

        # Nodes
        nodes_el = ET.SubElement(graph, "nodes")
        for author_id, info in author_info.items():
            node = ET.SubElement(nodes_el, "node", {"id": author_id, "label": info["display_name"]})
            attvals = ET.SubElement(node, "attvalues")
            ET.SubElement(attvals, "attvalue", {"for": "0", "value": info["display_name"]})
            ET.SubElement(attvals, "attvalue", {"for": "1", "value": info["platform"]})
            ET.SubElement(attvals, "attvalue", {"for": "2", "value": str(info["total_posts"])})

        # Edges
        edges_el = ET.SubElement(graph, "edges")
        for edge_idx, ((a, b), edata) in enumerate(edge_map.items()):
            edge = ET.SubElement(
                edges_el,
                "edge",
                {"id": str(edge_idx), "source": a, "target": b, "weight": str(edata["weight"])},
            )
            attvals = ET.SubElement(edge, "attvalues")
            ET.SubElement(attvals, "attvalue", {"for": "0", "value": str(edata["weight"])})
            ET.SubElement(attvals, "attvalue", {
                "for": "1",
                "value": " | ".join(sorted(edata["shared_terms"])),
            })

        tree = ET.ElementTree(gexf)
        ET.indent(tree, space="  ")
        buf = io.BytesIO()
        buf.write(b'<?xml version="1.0" encoding="UTF-8"?>\n')
        tree.write(buf, encoding="unicode", xml_declaration=False)
        return buf.getvalue()
