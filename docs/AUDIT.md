# Verification corrections, 2026-10-19

The first published version passed its original 13 tests, but those tests did not cover mixed currencies, sub-micro costs, missing fees or nested metadata. Version 0.2.0 adds six regression scenarios and changes the summary format to `RUN_SUMMARY_V2`.

- Store raw Decimal amounts. Round the currency subtotal after summation, using six decimal places and half-up rounding.
- Keep currencies separate. Never convert or add USD and EUR implicitly.
- Represent unknown model prices and `fee.amount: null` explicitly. A currency total remains null while any component is unknown. Known subtotals remain available.
- Require a human actor for an explicit `human_time` event. Record decimal minutes without estimating effort from timestamps.
- Require an actor for diary entries. Show the redacted diary and review text in the offline timeline.
- Redact nested metadata, secret-valued fields and actor names before storage. Pattern-based redaction still requires manual review before sharing.
- Commit each input file atomically. Invalid later lines roll the whole file back.
- Hash the event envelope as well as its payload in new rows. Existing version-1 rows remain readable, but protect only the original payload. A hash chain is not a signature or trusted external timestamp. Full rewriting, tail truncation and fabricated events cannot be excluded without a separately retained trusted checkpoint.

No private chat, billing record or real provider price was imported during verification. Fixtures remain synthetic. Existing ledgers retain their historical stored amounts; the tool does not invent precision lost by older rounding.
