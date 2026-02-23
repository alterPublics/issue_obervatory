"""Diagnostic script to test RSS feeds matching logic with Danish content."""

import re
from arenas.query_builder import match_groups_in_text, term_in_text

# Test data simulating Danish news headlines about Greenland
test_headlines = [
    "Grønland øger investeringer i grøn energi",
    "Ny aftale mellem Danmark og Grønland",
    "USA's interesse i Grønlands mineraler vokser",
    "Klimaforandringer påvirker Grønlands gletsjere",
    "greenland ice sheet melting faster",
    "Grønlandspolitik: Folketing diskuterer fremtiden",
    "The future of Greenland in Arctic geopolitics",
]

# Search terms to test
search_terms_da = ["grønland", "greenland"]  # Danish and English
search_term_en_only = ["greenland"]

print("=" * 70)
print("Testing RSS Feeds Matching Logic")
print("=" * 70)
print()

# Test 1: Basic term_in_text function
print("TEST 1: Basic term_in_text() function")
print("-" * 70)
for term in search_terms_da:
    print(f"\nTesting term: '{term}'")
    for headline in test_headlines:
        lower_headline = headline.lower()
        matches = term_in_text(term, lower_headline)
        print(f"  {'✓' if matches else '✗'} {headline}")

print()
print("=" * 70)

# Test 2: match_groups_in_text (simulating collect_by_terms logic)
print("TEST 2: match_groups_in_text() with lowercase groups")
print("-" * 70)

# Each term becomes its own group (OR logic)
lower_groups = [[term.lower()] for term in search_terms_da]
print(f"\nLower groups: {lower_groups}")
print()

for headline in test_headlines:
    searchable = headline.lower()
    matched_terms = match_groups_in_text(lower_groups, searchable)
    print(f"  {'✓' if matched_terms else '✗'} {headline}")
    if matched_terms:
        print(f"      Matched: {matched_terms}")

print()
print("=" * 70)

# Test 3: Check for case sensitivity issues
print("TEST 3: Case sensitivity check")
print("-" * 70)
test_term = "grønland"
test_texts = [
    "Grønland",  # Capital G
    "grønland",  # lowercase
    "GRØNLAND",  # all caps
]

for text in test_texts:
    matches = term_in_text(test_term, text)
    print(f"  Term '{test_term}' in '{text}': {'✓' if matches else '✗'}")

print()
print("=" * 70)

# Test 4: Check for compound word matching
print("TEST 4: Compound word matching (word boundary check)")
print("-" * 70)
test_term = "grønland"
compound_words = [
    "Grønlandspolitik",  # Greenland politics (compound)
    "Grønlands",  # Greenland's (possessive)
    "mellem Grønland og",  # Greenland with spaces
]

for text in compound_words:
    matches = term_in_text(test_term, text.lower())
    print(f"  Term '{test_term}' in '{text}': {'✓' if matches else '✗'}")

print()
print("=" * 70)

# Test 5: Simulate the actual RSS collector flow
print("TEST 5: Simulated RSS collector flow")
print("-" * 70)

# This is what collect_by_terms does:
terms = ["Grønland", "Greenland"]  # Mixed case input
term_groups = None  # No boolean groups

# Build lowercase group structure (from collect_by_terms line 182-190)
if term_groups is not None:
    lower_groups = [[t.lower() for t in grp] for grp in term_groups if grp]
    lower_terms = [t for grp in lower_groups for t in grp]
else:
    lower_terms = [t.lower() for t in terms]
    lower_groups = [[t] for t in lower_terms]  # each term = own OR group

print(f"Input terms: {terms}")
print(f"Lower terms: {lower_terms}")
print(f"Lower groups: {lower_groups}")
print()

# For each headline, simulate the matching (lines 210-216)
matches_found = 0
for headline in test_headlines:
    # Simulate _build_searchable_text (lines 739-755)
    searchable = headline.lower()

    # Match groups (line 214)
    matched_terms = match_groups_in_text(lower_groups, searchable)

    if matched_terms:
        matches_found += 1
        print(f"  ✓ MATCH: {headline}")
        print(f"      Terms: {matched_terms}")
    else:
        print(f"  ✗ NO MATCH: {headline}")

print()
print(f"Total matches: {matches_found}/{len(test_headlines)}")
print()
