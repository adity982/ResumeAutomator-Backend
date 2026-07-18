# Resume Automator product and engineering roadmap

This roadmap was created from a cross-repository audit of
[`ResumeAutomator-Frontend`](https://github.com/adity982/ResumeAutomator-Frontend)
and [`ResumeAutomator-Backend`](https://github.com/adity982/ResumeAutomator-Backend)
on 18 July 2026. The individual issues are the implementation source of truth.

## Current product baseline

The product already supports Google sign-in, PDF parsing, URL or pasted job
descriptions, ATS matching, streamed resume tailoring, cover letters, cold
emails, interview questions, career suggestions, PDF templates, and saved
resume history.

The audit found that the production build succeeds, but the frontend is one
466-line component, lint reports eight errors, the API URL is repeated in the
UI, the bundle is about 638 KB before gzip, and several radar values are
synthetic. The backend compiles, but user identity is trusted from request
data, CORS is unrestricted, uploads and a SQLite database are committed,
scraping permits arbitrary URLs, request validation is limited, and there are
no automated tests or CI workflows.

## Delivery order

| Phase | Goal | Planned work | Exit gate |
| --- | --- | --- | --- |
| 0 | Protect users and the service | Backend improvements I05-I07 | Verified identity and ownership; private files removed from the current tree; uploads and scraping pass security tests |
| 1 | Establish a maintainable platform | Improvements I01-I04 and I08-I10 | Typed contracts, migrations, API client, accessible errors, CI, observability, and no synthetic scores |
| 2 | Make the core workflow trustworthy | Features F02, F04, F06, and F08 | Versioned jobs and documents, evidence-backed suggestions, reviewable AI changes, and reliable PDF/DOCX exports |
| 3 | Expand the application workflow | Features F01, F03, F07, F09, and F10 | Pipeline, comparison, coaching, outreach, and personalized discovery work end to end with ownership tests |
| 4 | Turn usage into insight | Feature F05 | Analytics use persisted, defined metrics and support drill-down, export, and deletion |

Phase numbers express dependency order, not fixed dates. A small team should
finish Phase 0 before building additional features and should ship Phase 1 in
vertical slices rather than as a long rewrite.

## Ten new features

| ID | Primary repository | Feature | Outcome |
| --- | --- | --- | --- |
| F01 | Frontend [#3](https://github.com/adity982/ResumeAutomator-Frontend/issues/3) | Application workspace and pipeline board | Track saved roles through application, interview, offer, and closure |
| F02 | Frontend [#1](https://github.com/adity982/ResumeAutomator-Frontend/issues/1) | Evidence-preserving resume editor with AI diff | Review and approve AI edits without introducing unverified facts |
| F03 | Frontend [#2](https://github.com/adity982/ResumeAutomator-Frontend/issues/2) | Multi-job comparison and best-fit ranking | Prioritize up to five target roles using verified scoring dimensions |
| F04 | Frontend [#4](https://github.com/adity982/ResumeAutomator-Frontend/issues/4) | Live document preview with PDF and DOCX exports | See pagination and formatting before exporting usable documents |
| F05 | Frontend [#5](https://github.com/adity982/ResumeAutomator-Frontend/issues/5) | Career analytics and progress dashboard | Understand match trends, keyword gaps, and application conversion |
| F06 | Backend [#1](https://github.com/adity982/ResumeAutomator-Backend/issues/1) | Saved job library with normalized snapshots | Preserve versioned job data even when source pages change |
| F07 | Backend [#2](https://github.com/adity982/ResumeAutomator-Backend/issues/2) | Interactive interview coaching sessions | Capture answers, score them with rubrics, and measure practice over time |
| F08 | Backend [#3](https://github.com/adity982/ResumeAutomator-Backend/issues/3) | Keyword-gap action plans with evidence | Turn gaps into safe, evidence-backed actions instead of keyword stuffing |
| F09 | Backend [#4](https://github.com/adity982/ResumeAutomator-Backend/issues/4) | Networking outreach campaign kit | Create channel-specific, user-approved outreach and follow-ups |
| F10 | Backend [#5](https://github.com/adity982/ResumeAutomator-Backend/issues/5) | Personalized discovery preferences and saved searches | Recommend roles and search links that respect user constraints |

## Ten improvements

| ID | Primary repository | Improvement | Reason |
| --- | --- | --- | --- |
| I01 | Frontend [#7](https://github.com/adity982/ResumeAutomator-Frontend/issues/7) | Central API configuration and component decomposition | Remove hard-coded endpoints and reduce the single-component change risk |
| I02 | Frontend [#9](https://github.com/adity982/ResumeAutomator-Frontend/issues/9) | Accessible, responsive feedback and recovery | Replace blocking alerts with usable, resilient interaction states |
| I03 | Frontend [#6](https://github.com/adity982/ResumeAutomator-Frontend/issues/6) | Explainable ATS metrics | Stop presenting fabricated chart values as measured results |
| I04 | Frontend [#8](https://github.com/adity982/ResumeAutomator-Frontend/issues/8) | Tests, CI gates, and bundle budgets | Fix current lint failures and catch functional/performance regressions |
| I05 | Backend [#6](https://github.com/adity982/ResumeAutomator-Backend/issues/6) | Verified Firebase identity and ownership | Prevent callers from reading or writing another user's data |
| I06 | Backend [#7](https://github.com/adity982/ResumeAutomator-Backend/issues/7) | Secure uploads and resume privacy controls | Remove sensitive tracked artifacts and enforce safe file handling |
| I07 | Backend [#8](https://github.com/adity982/ResumeAutomator-Backend/issues/8) | SSRF-resistant async scraping and bounded caching | Protect internal networks and prevent event-loop/cache exhaustion |
| I08 | Backend [#9](https://github.com/adity982/ResumeAutomator-Backend/issues/9) | Validated contracts and modular services | Replace untyped dictionaries and route-level business logic |
| I09 | Backend [#10](https://github.com/adity982/ResumeAutomator-Backend/issues/10) | Production database configuration and migrations | Move safely beyond import-time SQLite table creation |
| I10 | Backend [#11](https://github.com/adity982/ResumeAutomator-Backend/issues/11) | Operational hardening for AI/API workloads | Add limits, health checks, redacted telemetry, and reliable streaming failure semantics |

## Cross-repository implementation sequence

1. Complete I05-I07 before exposing more stored data or network operations.
2. Define the versioned schemas in I08, then build I09 and the frontend API
   client in I01 against those contracts.
3. Make I03 and F08 one vertical slice: the backend supplies evidence and the
   frontend renders only verified dimensions.
4. Build F06 before features that reuse a stable job target (F02, F03, F07,
   F09, and F10).
5. Add application/document version models while delivering F01, F02, and
   F04; analytics F05 consumes those records last.

## Definition of done

Every roadmap item must include ownership checks where user data is involved,
bounded and validated inputs, tests at the appropriate layer, accessible
loading/error/empty states, documentation of contract or migration changes,
redacted observability, and successful lint/test/build checks in both affected
repositories. AI-generated claims must remain reviewable and traceable to user
or job-description evidence.
