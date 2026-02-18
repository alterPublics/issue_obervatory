# Scenario 11 — Credit Awareness

**Created:** 2026-02-17

## Research question
A researcher has 50 credits remaining and wants to run a medium-tier Google Search collection that will cost 80 credits. Does the system stop them, and do they understand why?

## Expected workflow
1. Open the collection launcher.
2. Select a query design with Google Search enabled at medium tier.
3. Observe the credit estimate panel on the right side.
4. The estimate shows 80 credits required vs. 50 available.
5. The researcher sees the insufficient credit warning.
6. The Launch button is disabled.
7. The researcher understands they need to contact an administrator for more credits.

## Success criteria
- Credit estimate loads automatically after query design and tier selection without the researcher having to click anything.
- The estimate breaks down credits by arena, showing why Google Search costs credits.
- The insufficient credit warning is visually prominent (red, not easily missed).
- The Launch button is visibly disabled (greyed out) with a tooltip explaining why.
- The researcher understands what to do next (contact admin for credits, or switch to free tier).

## Known edge cases
- The credit badge in the header polls every 30 seconds — if credits change during the session, the launcher's Alpine state may be stale until the next poll.
- The estimate panel says "Contact an administrator" but does not provide a mechanism (no email link, no admin contact field).
- Free tier has 0 credit cost but the credit estimate still requires selecting a query design before the estimate renders.
