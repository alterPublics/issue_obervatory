"""VKontakte (VK) arena package for Issue Observatory.

DEFERRED ARENA -- Phase 4 / Future
====================================

This arena is NOT yet implemented. The stub files in this package exist to
reserve the module namespace, document the intended architecture, and make
the deferred status visible in the API specification (all endpoints return
HTTP 501 Not Implemented).

Status
------
- Implementation phase: Phase 4 / Future (not in current roadmap)
- Blocked on: University legal review (see below)
- Do NOT activate or enable collection without completing the legal review
  process first.

Legal Considerations
--------------------
Before any code in this arena is connected to live collection, the following
legal and compliance questions MUST be resolved by university legal counsel
and the Data Protection Officer:

1. EU Sanctions context: EU sanctions against Russia (post-2022) do not
   explicitly prohibit academic research use of VK, but the sanctions
   landscape is complex and evolving. VK Company (formerly Mail.ru Group)
   must be individually checked against current EU sanctions lists before
   any interaction.

2. Cross-border data transfer: Russia has no adequacy decision under GDPR
   (Schrems II considerations apply). Any transfer of personal data collected
   from VK to EU servers requires a valid legal basis and appropriate
   safeguards (e.g. Standard Contractual Clauses).

3. Russian jurisdiction: VK is subject to Russian Federal Law No. 152-FZ on
   Personal Data. The interaction between Russian data law and GDPR for EU-
   based researchers requires specific legal guidance.

4. Geo-restrictions: VK may block API access from certain EU IP ranges.
   API reachability from the deployment location must be verified before
   any development investment begins.

5. Ethical framing: Research involving Russian social media in the current
   geopolitical context requires explicit ethical justification and DPIA
   documentation.

Research Value Justification
-----------------------------
VK has essentially zero Danish-language user presence. Its value for this
project is limited to specific future research scenarios:
- Studying Russian-language influence operations targeting Danish/European
  discourse.
- Comparative CIS media ecosystem analysis.
- Tracking Russian-language reactions to Danish policy decisions (NATO,
  Arctic policy, energy policy).

Until a specific research question requiring VK data is identified AND legal
review is complete, this arena must remain deferred.

References
----------
- Arena brief: docs/arenas/vkontakte.md
- Implementation plan: docs/arenas/new_arenas_implementation_plan.md (section 6)
- VK API documentation: https://dev.vk.com/en/reference
"""
