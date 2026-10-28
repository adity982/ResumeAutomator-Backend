# Delivery status

The former July audit is historical. The current implementation is documented in README.md and docs/ARCHITECTURE.md.

| Stage | Implemented software | External release gate |
| --- | --- | --- |
| 1. Trustworthy core | Honest coverage/checklist labels; no fixed confidence percentages; input invalidation; revision-safe account recovery; immutable document families and approval; Unicode exports and actual PDF preview; event-based conversion metrics. | Verify Firebase, production database backups/restores and real deployment configuration. |
| 2. Portfolio evidence | Bounded public GitHub previews; commit/file/line provenance; durable worker; explicit contribution review; source deletion and invalidation; unchanged-content reuse. | Private GitHub App access is a separate future integration. |
| 3. Retrieval and selection | Learned FastEmbed vectors, PostgreSQL/pgvector path, lexical/dense/hybrid retrieval, requirement coverage, complementary project sets, cited extractive bullets, missing-evidence behavior and a 60-case synthetic benchmark. | Run PostgreSQL CI, staging workload checks and broader human-labeled evaluations before production claims. |
| 4. Pilot and launch | Job-centered navigation, illustrative sample, account controls, contacts/hiring signals, editable outreach/status tracking, application timeline, feedback capture and pilot guide. | Recruit real participants, obtain publishing consent, observe usage and complete production rollout. |

No merge or production deployment is implied by implementation. Do not mark the real-user pilot complete until participants have actually used the software.
