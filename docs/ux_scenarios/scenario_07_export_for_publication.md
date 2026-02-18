# Scenario 07 — Export for Publication

**Created:** 2026-02-17

## Research question
A researcher has collected 45,000 records and wants to export them as XLSX for Excel-based analysis and as GEXF for Gephi network visualization. Do the files work correctly for Danish content?

## Expected workflow
1. Navigate to the Analysis Dashboard for the completed run.
2. Select XLSX format in the Export section.
3. Click "Export (up to 10k records)" — download the file.
4. Open in Excel and verify: Danish characters (æøå) render correctly, column headers are clear, no broken encoding.
5. Return to the dashboard, click "Export async (large dataset)" for the full 45,000 records.
6. Monitor the async job status (pending → running → complete).
7. Download the completed file.
8. Select GEXF format and download the actor network.
9. Open the GEXF file in Gephi.

## Success criteria
- XLSX file encodes Danish characters correctly (BOM header applied).
- XLSX column headers are meaningful to a researcher (not internal field names like "text_content").
- The distinction between sync export (10k limit) and async export (full dataset) is clearly communicated.
- Async job shows progress percentage during generation.
- GEXF file opens in Gephi with labelled nodes and weighted edges.

## Known edge cases
- Column headers in XLSX use internal snake_case names like "text_content", "views_count", "search_terms_matched" — these are developer names, not researcher-friendly labels.
- The 10,000-record limit on sync export is mentioned on the button but not explained (why the limit exists, or how to know if the dataset exceeds it).
- The JSON export produces NDJSON format, which many researchers will not recognize as valid JSON (they expect a JSON array).
- Parquet export omits raw_metadata, which is the only place full content from Event Registry is stored.
