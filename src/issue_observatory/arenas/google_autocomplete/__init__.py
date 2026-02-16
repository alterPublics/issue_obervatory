"""Google Autocomplete arena package.

Collects autocomplete suggestions from Google via three tiers:

- **FREE** — Undocumented Google endpoint (``suggestqueries.google.com``).
  No authentication required. Unreliable for sustained production use.
- **MEDIUM** — Serper.dev autocomplete endpoint (``POST google.serper.dev/autocomplete``).
  Uses shared ``platform="serper"`` credentials.
- **PREMIUM** — SerpAPI autocomplete endpoint (``GET serpapi.com/search?engine=google_autocomplete``).
  Uses shared ``platform="serpapi"`` credentials.

Danish locale parameters (``hl=da``, ``gl=dk``) are applied on all requests.
Content type is ``"autocomplete_suggestion"`` with arena ``"google_autocomplete"``.
"""
