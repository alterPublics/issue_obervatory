# Data Quality Finding: Ritzau Via Returns Unfiltered Press Releases

**Date**: 2026-02-23
**Severity**: CRITICAL
**Arena**: ritzau_via (news_media)
**Responsible agent**: [data]

## Observation

When a batch collection is launched with search terms "Gronland", "Greenland", "gronlandsk selvstaendighed", "Gronlands selvstyre" against the Ritzau Via arena, the collector returns 80 press releases that have no relationship to any of these search terms.

## Evidence

### Sample records returned (first 5 of 80)

1. **Guldborgsund Kommune**: Local culture prize ceremony in Nykobing F. Teater -- about gymnastics, archery, motocross.
2. **Globenewswire**: Equinox Gold Corp. financial statements filing (Canadian mining company).
3. **Business Wire**: Andersen Consulting partnership with Grinity (Czech/Slovak construction consultancy).
4. **Globenewswire**: Jay Walker Podcast distribution deal with Tubi.
5. **Danmarks Idraetsforbund**: Danish sports federation press release.

### Key data points

- `search_terms_matched` field: EMPTY for all 80 records
- Search terms used: "Gronland", "Greenland", "gronlandsk selvstaendighed", "Gronlands selvstyre"
- Language distribution: Mix of Danish ("da") and English ("en") despite language="da" setting
- Published timestamps: All within seconds of each other (02:24:05 to 02:24:13), suggesting bulk import of latest press releases

## Probable cause

The Ritzau Via collector appears to fetch the latest N press releases from the `/api/press-releases` endpoint without passing any search term filter. The `collect_by_terms()` method either:
(a) Does not incorporate the search terms into the API query parameters, or
(b) The Ritzau Via API does not support keyword search and the collector lacks client-side filtering.

## Research impact

This finding completely undermines the data trust dimension of the Issue Observatory for the Ritzau Via arena. If a researcher collected data about Greenland independence discourse and received press releases about local gymnastics clubs, they would:

1. Lose trust in the entire data collection pipeline
2. Be unable to distinguish relevant from irrelevant content without manual review of every record
3. Produce misleading analysis results (actor rankings, term frequencies, engagement metrics would all reflect random press releases, not Greenland discourse)
4. Risk publishing incorrect findings if they relied on aggregate statistics without manual verification

## Recommended fix

1. Verify whether the Ritzau Via JSON API supports keyword search parameters
2. If yes: pass search terms as query parameters in the API call
3. If no: implement client-side filtering -- iterate through returned records and only persist those where `text_content` contains at least one search term (case-insensitive match)
4. Always populate `search_terms_matched` with the specific terms that matched each record
5. Add a warning in the arena metadata if Ritzau Via only supports "latest press releases" mode without keyword filtering

## Reproduction steps

1. Create a query design with search terms "Gronland", "Greenland"
2. Enable ritzau_via arena at FREE tier
3. Launch a batch collection
4. Wait for ritzau_via task to complete
5. Export content as CSV
6. Observe that no records contain the search terms in their text content
