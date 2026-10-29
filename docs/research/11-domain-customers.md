# 11 — Domain and customer research: medication reconciliation
_Drafted 2026-10-29 by a research agent as a scaffold; each section's owner reviews and finalizes it._

Conventions: `[R1]`, `[V1]`, `[S1]`, `[D1]` cite the Sources list of that owner's section. `UNVERIFIED` = not confirmed from a page that was successfully fetched. `INFERENCE` = reasoning by the drafter, not a statement from a source. Several primary sites (jointcommission.org pages, ahrq.gov, hhs.gov, ihi.org, cmaj.ca, pubmed HTML) blocked or failed; see each Sources list. Where a PDF could not be summarized by the fetch tool, the fetched file's text was extracted locally and read directly.

## Recommendation
- **Scope stays V1 = duplicates, omissions, dose mismatches.** Omission of a regularly used drug is the most common unintended discrepancy in the original admission study (46.4%) [S3]; frequency and brand/generic normalization stay V2.
- **UX: spell everything out and stay neutral.** Show "once daily", "mcg", "0.5 mg" (never QD, µg, .5 mg, 1.0 mg) [R4]; call findings "discrepancies", not "errors", because intent cannot be judged from the data [S5]; group by type, do not rank by harm (clinical judgement; literature range is wide, 11-59% clinically important) [S4].
- **Trust = durable, atomic history.** Joint Commission NPSG.03.06.01 requires documented medication information [V1]; save run + snapshot + findings in one transaction so a failed save never looks like "no discrepancies" [V5].
- **Report-only, synthetic-only.** FDA's CDS guidance lets decision-support software fall outside the device definition only if it meets four criteria, including no specific treatment directive and a basis the clinician can review [D6]; Synthea data carries no real-patient exposure [D4]. Disclaimer states intended user (clinician) and purpose.

## Rachit Shah: users and medication terminology
OWNER: Rachit Shah, to review and finalize

**Who performs reconciliation, and when**
- It is a multidisciplinary task shared by physicians, nurses, pharmacists and other clinicians; WHO says a pharmacist ideally gathers or validates the home-medication list and compares it with orders, otherwise a trained physician, nurse, therapist or technologist/technician does it [R1]. Joint Commission (ambulatory chapter, eff. Jan 2026): the comparison is done by a qualified individual whom the organization identifies [R3].
- Transitions: admission, transfer within the hospital, discharge [R1][R2]. WHO's High 5s project evaluated admission only; transfer and discharge were not evaluated [R1].
- Per medication they record name (generic and brand), dose, frequency, route [R1]; Joint Commission examples: name, dose, route, frequency, purpose; current meds include scheduled and as-needed ones [R3]. WHO also lists OTC, herbal, recreational and prn drugs [R1].
- WHO: the history should live in "a purpose designed form or computer tab" available whenever medicines are prescribed [R1].
- INFERENCE, what a tool must give them: both lists side by side with the source labelled; findings they can work through by type; unambiguous display (below); brand/generic tolerance (fewer false "missing" alerts); a documented output (history, PDF); a clear statement that the clinician decides.

**Terminology**
- **Generic vs brand (RxNorm):** NLM RxNorm gives normalized names and IDs for generic and branded drugs. Term types: IN (ingredient, e.g. fluoxetine), BN (brand, e.g. Prozac), SCD (ingredient + strength + dose form), SBD (SCD plus brand in brackets). An RXCUI is the concept ID shared by synonymous names from different sources [R5]. See `07-rxnorm.md` for the integration.
- **Dose units (ISMP, 2021 edition) [R4]:** write `mcg`, not `µg` (µg is mistaken as mg, a 1000-fold difference, since 1 mg = 1000 mcg); spell out `nanogram` (ng mistaken as mg or nasogastric); use `mL` not `cc` (cc mistaken as "u"/units); `L` uppercase; no terminal period after mg/mL; leave a space between drug name, dose and unit (`10mg` risks being read as 100); use a leading zero (`0.5 mg`, not `.5 mg`) and no trailing zero (`1 mg`, not `1.0 mg`, which is mistaken as 10 mg).
- **Frequency / sig abbreviations.** Expansions below are standard convention and UNVERIFIED (not fetched); the ISMP column is read from [R4]; BID/TID/QID entries were not confirmed in the extracted text.

| Abbrev. | Usual meaning (UNVERIFIED) | ISMP handling [R4] | Plain-language display (proposal) |
|---|---|---|---|
| QD, q.d. | once daily | mistaken as QID; use "daily" | once daily |
| QOD | every other day | mistaken as QD or QID; write it out | every other day |
| BID / TID / QID | twice / three times / four times daily | not confirmed | twice daily / three times daily / four times daily |
| QHS, HS | at bedtime | QHS mistaken as qhr (every hour); HS also reads as half-strength; ISMP's own advice differs between entries, so spell out | at bedtime |
| PRN | as needed | as-needed meds must still be on the list [R1][R3] | as needed |

- **Joint Commission "Do Not Use" list:** it sits under the Information Management standard (IM.02.02.01; the number is partly garbled in the extracted text, verify); ISMP marks the entries that are on it with a double asterisk and says they must be on an organization's list [R4]. The primary JC list PDF returned HTTP 403, so the nine items are UNVERIFIED here. Search-engine excerpts (not fetched, not cited) agree on: U/u, IU, Q.D./QD, Q.O.D./QOD, trailing zero, lack of leading zero, MS, MSO4, MgSO4. Owner: confirm at jointcommission.org in a browser before slides.
- **Implication:** the UI never prints raw QD/BID/µg, trailing zeros or missing leading zeros; incoming FHIR and pharmacy strings are normalized for compare and for display. INFERENCE: normalize unit synonyms (µg, ug, mcg) before comparing doses, or 0.5 mg vs 500 mcg would show a false dose mismatch.

### Sources
- [R1] WHO High 5s, Standard Operating Protocol for Medication Reconciliation, v3 Sept 2014 (PDF, locally extracted): https://cdn.who.int/media/docs/default-source/patient-safety/high5s/h5s-sop.pdf?sfvrsn=594d8e49_4
- [R2] WHO High 5s medication reconciliation fact sheet (PDF, locally extracted): https://cdn.who.int/media/docs/default-source/patient-safety/high5s/ps-med-rec-fs-mar-2011.pdf?sfvrsn=b43b8d82_2
- [R3] Joint Commission, National Patient Safety Goals, Ambulatory Health Care, effective January 2026 (PDF, locally extracted; hospital chapter not obtained): https://digitalassets.jointcommission.org/api/public/content/92c95c4e94304b2084e7e039d916719b
- [R4] ISMP List of Error-Prone Abbreviations, Symbols, and Dose Designations, 2021 edition (PDF, locally extracted; some characters including the µ symbol and digits were lost in extraction, entries read for meaning; ISMP has since updated the list, check the current edition): https://www.ismp.org/system/files/resources/2021-02/Error%20Prone%20Abbreviations%202021_0.pdf
- [R5] NLM, RxNorm overview: https://www.nlm.nih.gov/research/umls/rxnorm/overview.html
- Blocked or failed: Joint Commission Do Not Use PDF and standards pages (403); ISMP HTML list (redirects to ECRI, HTTP 429); AHRQ MATCH (403).

## Vedant Misra: history, auditability, transaction integrity
OWNER: Vedant Misra, to review and finalize

- **NPSG.03.06.01, "Maintain and communicate accurate patient medication information" [V1].** Rationale text: there is evidence that medication discrepancies can affect patient outcomes; reconciliation compares what the patient is taking (or should be taking) with newly ordered medications, addressing duplications, omissions, interactions and the need to continue current medications. EP 1: obtain and/or update current-medication information and document it in a list useful to those who manage medications ("Documentation is required"); obtained at the start of an episode of care and updated when medications change. EP 3 (prescribing organizations): compare and identify/resolve discrepancies. EP 4: give the patient written medication information at the end of the episode, also with required documentation.
- Scope caveat: the fetched text is the Ambulatory Health Care chapter (Jan 2026). The hospital chapter was not obtained (JC site 403), so hospital EP wording is UNVERIFIED.
- **Why a durable record matters (INFERENCE tied to [V1]):** the standard requires documented medication information; a stored run answers "which lists were compared, what was found, when, by which app version". A screen-only result cannot. The history is an aid, not the legal medical record (the EHR remains that).
- **HIPAA Security Rule, 45 CFR 164.312 (technical safeguards) [V2]:** (b) audit controls: hardware, software or procedural mechanisms that record and examine activity in systems containing ePHI. (c)(1) integrity: policies to protect ePHI from improper alteration or destruction; (c)(2) mechanism to authenticate ePHI (addressable): electronic means to confirm it was not altered or destroyed in an unauthorized manner. Neighbours: (a) access control, (d) person/entity authentication.
- Related: 164.308(a)(1)(ii)(D) requires regular review of system activity records such as audit logs [V3]; 164.316(b) requires written/electronic documentation of required security actions, kept six years [V4] (a security-documentation rule, not a clinical-record retention rule).
- Applicability (general knowledge, not fetched): these duties bind covered entities and business associates handling real ePHI. Our demo uses synthetic data, so treat 164.312 as a design checklist, not a compliance claim.
- **Atomic saves [V5].** PostgreSQL transactions make a group of statements all-or-nothing: others never see a partial result, and `ROLLBACK` before `COMMIT` cancels everything. Without an explicit `BEGIN`, each statement is its own implicit transaction, so the app must wrap the whole save explicitly.
- **Why it matters here (INFERENCE):** if the run row commits but the findings insert fails, history shows a finished run with zero findings, which reads as "no discrepancies found": a false all-clear in a safety tool. Run, medication snapshot and findings go in one transaction; `05-postgres-persistence.md` already specifies one `SessionLocal.begin()` block. Suggested test: force a failure mid-save, assert no run row persisted.
- **Design suggestions for the owner to decide:** history append-only (no UPDATE/DELETE of findings); store per run who/when/app version/source snapshot; if V1 has no login, record an explicit "demo user" (audit needs an actor); unknown finding types render as "Other (<value>)" (`10-release-rollback.md`).

### Sources
- [V1] Joint Commission NPSG, Ambulatory Health Care, eff. Jan 2026 (PDF, locally extracted): https://digitalassets.jointcommission.org/api/public/content/92c95c4e94304b2084e7e039d916719b
- [V2] 45 CFR 164.312 (Cornell LII): https://www.law.cornell.edu/cfr/text/45/164.312
- [V3] 45 CFR 164.308 (Cornell LII): https://www.law.cornell.edu/cfr/text/45/164.308
- [V4] 45 CFR 164.316 (Cornell LII): https://www.law.cornell.edu/cfr/text/45/164.316
- [V5] PostgreSQL docs, Transactions tutorial: https://www.postgresql.org/docs/current/tutorial-transactions.html
- Blocked or failed: ecfr.gov (redirected to a bot-check page, not followed); hhs.gov Security Rule pages (403); Joint Commission hospital NPSG chapter (403).

## Sarthak Kakkar: workflows, discrepancy types, consequences
OWNER: Sarthak Kakkar, to review and finalize

**Standard manual steps (WHO High 5s SOP [S1][S2])**
1. **Collect the Best Possible Medication History (BPMH):** systematic interview of patient/family where possible, covering all prescribed and non-prescribed drugs (OTC, herbal, recreational, prn); a BPMH uses several information sources [S1].
2. **Verify and document:** check more than one source (community pharmacy, physicians/home care, medication containers, patient lists, government medication database, prior records); record generic and brand name, dose, frequency, route [S1].
3. **Compare and resolve:** compare the BPMH with admission orders, identify discrepancies, bring them to the prescriber, change orders if appropriate; goal is to reconcile within 24 hours [S1][S2].
4. **Communicate:** at discharge, give a Best Possible Medication Discharge Plan to the patient, community pharmacy, primary care physician or next facility [S1].
- Our tool covers step 3's comparison only (FHIR list vs pharmacy records mirrors step 2's multi-source idea). It does not do the interview, resolution or communication.
- AHRQ MATCH: an AHRQ newsletter item confirms the toolkit supports reconciliation at transitions and handoffs (May 2013) [S7]; its process map and role tables could not be read (ahrq.gov 403/empty), so those details are UNVERIFIED. IHI how-to guide: not fetched (connection refused, 404, redirect), UNVERIFIED.

**Discrepancy taxonomy (no single standard)**
| Type | Source of definition | In our product |
|---|---|---|
| Omission: pre-admission drug missing from the history/orders | Tam [S4] | V1 "missing/omitted" |
| Commission: drug added that was not used before | Tam [S4] | team to decide if V1 flags both directions |
| Dose | field named in JC and WHO lists [S1][S6] | V1 |
| Frequency | same | V2 |
| Route | same | not planned: gap to state explicitly |
| Duplication | JC note: discrepancies include omissions, duplications, contraindications, unclear information, changes [S6] | V1 |
| Intentional (documented) vs undocumented intentional vs unintentional | WHO SOP [S1] | tool cannot judge intent; clinician does |
- Almanasreh 2016 systematic review (95 studies): no agreed definition of "discrepancy"; intent is hard for an outside observer to judge; only 11 studies used one of three standardized taxonomies (MDT 2004, 19 items; APS-Doc 2012, 48 items; Claeys 2012, 11 items) [S5].

**Consequences (original studies; figures read from abstracts via a fetch summarizer, owner to re-check on PubMed before slides)**
- **Cornish et al., Arch Intern Med 2005;165(4):424-9 [S3]:** prospective study, 151 patients taking at least 4 regular prescription drugs on general internal medicine teaching units. 81 patients (53.6%, 95% CI 45.7-61.6) had at least one unintended discrepancy between admission orders and a comprehensive interview-based history. 38.6% of the discrepancies were rated as having potential for moderate to severe discomfort or clinical deterioration. Most common type: omission of a regularly used drug (46.4%).
- **Tam et al., CMAJ 2005;173(5):510-5 [S4]:** systematic review of 22 studies. Up to 67% of patients had at least one medication history error; 27-54% in the 5 studies that separated unintentional discrepancies from intentional changes; in 6 studies, 11-59% of errors were judged clinically important. Definitions differ by study, so ranges are wide.
- WHO SOP restates, citing other work (secondary, original citations not fetched): about half of in-hospital medication errors arise at admission or discharge, about 30% of those with potential for harm [S1].
- Limits: admission-focused, hospital-based, small samples; do not quote one "% harmful" without its range and setting.

### Sources
- [S1] WHO High 5s SOP v3, 2014 (PDF, locally extracted): https://cdn.who.int/media/docs/default-source/patient-safety/high5s/h5s-sop.pdf?sfvrsn=594d8e49_4
- [S2] WHO High 5s fact sheet (PDF, locally extracted): https://cdn.who.int/media/docs/default-source/patient-safety/high5s/ps-med-rec-fs-mar-2011.pdf?sfvrsn=b43b8d82_2
- [S3] Cornish 2005, PMID 15738372 (abstract via NCBI E-utilities): https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id=15738372&retmode=text&rettype=abstract
- [S4] Tam 2005, PMID 16129874 (abstract via NCBI E-utilities): https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id=16129874&retmode=text&rettype=abstract
- [S5] Almanasreh, Moles, Chen, Br J Clin Pharmacol 2016;82(3):645-658: https://pmc.ncbi.nlm.nih.gov/articles/PMC5338112/ (first 100,000 of 146,265 characters read)
- [S6] Joint Commission NPSG, Ambulatory Health Care, eff. Jan 2026 (PDF, locally extracted): https://digitalassets.jointcommission.org/api/public/content/92c95c4e94304b2084e7e039d916719b
- [S7] AHRQ PSNet, "Medication reconciliation meets its MATCH" (May 2013 newsletter item): https://psnet.ahrq.gov/issue/medication-reconciliation-meets-its-match
- Blocked or failed: AHRQ MATCH toolkit PDF and chapters (403/empty); IHI how-to guide (connection refused, 404); PubMed HTML (cookie wall); CMAJ site (403); PSNet primer (404).

## Devang Borkar: privacy and release safety
OWNER: Devang Borkar, to review and finalize

- **PHI basics (45 CFR 160.103) [D1]:** protected health information is individually identifiable health information (health data created or received by a provider, plan, employer or clearinghouse, tied to past, present or future health, care or payment, that identifies or could reasonably identify a person), in any form. Excluded: FERPA education records, employment records held as employer, data on people deceased over 50 years.
- **Safe Harbor, 45 CFR 164.514(b)(2) [D2]:** remove 18 identifiers: names; geographic units smaller than a state (first three ZIP digits allowed only if the area exceeds 20,000 people); all date elements except year (ages over 89 grouped as 90+); phone; fax; email; SSN; medical record numbers; health plan beneficiary numbers; account numbers; certificate/license numbers; vehicle IDs and plates; device IDs and serial numbers; URLs; IP addresses; biometric identifiers; full-face photos; any other unique identifying number or code. Plus no actual knowledge that the rest could identify someone. Alternative: Expert Determination (qualified expert documents very small re-identification risk) [D2].
- **Why Synthea:** it simulates synthetic patients and exports HL7 FHIR (R4, STU3, DSTU2), C-CDA, CSV; its README calls the output "realistic (but not real)" [D3]. The JAMIA paper says real records are hard to share because of legal, privacy and security limits and that synthetic records carry no risk of exposing real patients [D4]. Caveat: that holds only while no real data is mixed in; the team's pharmacy records are also synthetic, so label both as synthetic in the UI, PDF and slides (Safe Harbor lists names and full dates as identifiers, and synthetic records contain them).
- **Secrets out of git [D7]:** a committed secret persists in clones, forks and cached views; revoke or rotate first, then rewrite history only if needed. Prevent: environment variables or a secrets manager, pre-commit scanners (gitleaks, git-secrets), GitHub push protection, stage files individually instead of `git add .`. Repo check: `.gitignore` already lists `.env` and `.envrc`.
- **FDA Clinical Decision Support Software guidance [D5][D6]:** final guidance issued 29 Jan 2026 (supersedes the 6 Jan 2026 version). Non-device CDS must meet four criteria from section 520(o)(1)(E): (1) no processing of medical images, IVD signals or signal-acquisition patterns; (2) displays, analyzes or prints medical information; (3) supports or provides recommendations to a health care professional (HCP) about prevention, diagnosis or treatment; (4) lets the HCP independently review the basis so they do not rely primarily on it. For criterion 3, FDA reads the software as one that does not provide a specific preventive, diagnostic or treatment output or directive and does not replace or direct HCP judgment. Its example list of non-device CDS includes duplicate-prescription notifications "(e.g., medication reconciliations)". For criterion 4, labeling should state intended use, intended HCP user and patient population, required inputs, and a plain-language basis; time-critical tasks do not qualify, and FDA discusses automation bias (over-reliance on an automated suggestion).
- **Reading for us:** "reports discrepancies, no treatment recommendation" keeps us on the safe side of criterion 3 (INFERENCE: stricter than FDA requires, since FDA's examples allow some advice, but simpler to defend). Criterion 4 supports showing both source values for every finding and putting intended use in the disclaimer. This is a class project; the guidance is cited as a design aid, not a regulatory determination or legal advice.
- **Release safety:** HIPAA requires a data backup plan (retrievable exact copies of ePHI) and a disaster recovery plan (restore lost data) [D8]; used here as an analogy for "backup before upgrade, tested restore, rollback path". Implemented in `10-release-rollback.md` (verified dumps, rollback by swapping the app image, expand-only schema).

### Sources
- [D1] 45 CFR 160.103 (Cornell LII): https://www.law.cornell.edu/cfr/text/45/160.103
- [D2] 45 CFR 164.514 (Cornell LII): https://www.law.cornell.edu/cfr/text/45/164.514
- [D3] Synthea README (GitHub): https://github.com/synthetichealth/synthea
- [D4] Walonoski et al., JAMIA 2018;25(3):230-238, PMID 29025144 (abstract via NCBI E-utilities): https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id=29025144&retmode=text&rettype=abstract
- [D5] FDA guidance page, Clinical Decision Support Software: https://www.fda.gov/regulatory-information/search-fda-guidance-documents/clinical-decision-support-software
- [D6] FDA guidance PDF, issued 29 Jan 2026 (locally extracted): https://www.fda.gov/media/109618/download
- [D7] GitHub Docs, Removing sensitive data from a repository: https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository
- [D8] 45 CFR 164.308(a)(7) (Cornell LII): https://www.law.cornell.edu/cfr/text/45/164.308
- Blocked or failed: HHS de-identification and Security Rule pages (403); synthea.mitre.org (TLS certificate error).

## Implications for our product
1. **Compare the fields clinicians reconcile.** Name, dose, route, frequency, purpose are the Joint Commission examples [R3]; WHO's history records generic and brand name [R1]. V1 compares name and dose; V2 adds frequency and RxNorm (brand/generic) to cut false "missing" findings [R5].
2. **Put omissions first in the UI.** Omission was the most common unintended discrepancy (46.4%) [S3].
3. **No harm ranking, no advice.** Clinically important share ranges 11-59% across studies [S4] and rating it is clinical judgement; FDA criterion 3 favors no directive [D6].
4. **Say "discrepancy", never "error"; leave intent to the clinician.** Intent is hard to judge from outside, and definitions vary [S5]; WHO separates intentional from unintentional [S1].
5. **Display plain language only.** ISMP flags QD, QOD, µg, trailing zeros, missing leading zeros [R4]; show "once daily", "mcg", "0.5 mg" and normalize units before comparing doses (INFERENCE).
6. **As-needed meds are in scope.** JC and WHO both require prn/as-needed drugs on the list [R3][R1]; the data model needs an as-needed flag and the V2 frequency rule must handle it.
7. **History is a documented record, saved atomically.** NPSG.03.06.01 EP 1 and 4 require documentation [V1]; HIPAA 164.312(b),(c) frame audit and integrity [V2]; one transaction for run + snapshot + findings prevents a false all-clear [V5].
8. **Disclaimer carries intended use.** FDA criterion 4 expects labeling with intended use, HCP user and population [D6]; add "not for time-critical decisions" and "synthetic data".
9. **Show the basis of each finding.** Both source values side by side with source labels (FDA criterion 4 [D6]; WHO multi-source verification [S1]).
10. **Synthetic only, secrets out, backups tested.** Synthea carries no real-patient exposure [D4]; Safe Harbor identifiers (names, dates) are why real data is excluded [D2]; `.env` ignored, rotate if leaked [D7]; backup and restore path per HIPAA 164.308(a)(7) analogy [D8].

## Customer questions
Five drafted questions for a clinical customer (nurse, pharmacist or physician):
1. (Suggested owner: Rachit Shah) How do your clinicians write and read drug names and frequencies today (brand vs generic, "BID" vs "twice daily"), and would side-by-side brand and generic display help or add noise?
2. (Suggested owner: Sarthak Kakkar) Which discrepancy types do you see most and care about most (omission, duplication, dose, frequency, route), and how do you tell an intentional difference from an unintended one at the point of review?
3. (Suggested owner: Vedant Misra) After a reconciliation, what do you need on record (who reviewed, when, which source lists, which findings) and for how long, and would a PDF filed to the chart meet that?
4. (Suggested owner: Devang Borkar) Would a tool that only reports discrepancies and never suggests an action fit your workflow, and what disclaimer wording and export restrictions (PDF, email, printing) would your organization expect?
5. (Suggested owner: Sarthak Kakkar) When the EHR list and pharmacy fill data disagree, which do you trust more, and how should the tool treat OTC, herbal and as-needed drugs that fill data may not capture?

Open slots (one per teammate):
- Q (OWNER: Rachit Shah, to author): ______
- Q (OWNER: Vedant Misra, to author): ______
- Q (OWNER: Sarthak Kakkar, to author): ______
- Q (OWNER: Devang Borkar, to author): ______

## Rejected alternatives
- **Real or de-identified real patient data:** needs PHI handling (Safe Harbor removes 18 identifier types [D2]); Synthea chosen [D3][D4].
- **Recommending dose changes or discontinuation:** outside scope, raises FDA criterion 3 and automation-bias concerns [D6].
- **Harm or severity scoring of findings:** clinical judgement; literature ranges too wide to automate [S4].
- **Showing raw abbreviations (QD, BID, µg) as received:** ISMP/JC error-prone list [R4].
- **Overwriting a "latest result" per patient instead of keeping history:** loses the documented record and weakens integrity and audit [V1][V2].
- **Non-atomic multi-step save (run first, findings later):** a partial failure looks like "no discrepancies" [V5].
- **Citing blocked primary pages or secondary summaries as verified:** the Joint Commission Do Not Use list, AHRQ MATCH and IHI guide stay UNVERIFIED until a teammate reads them in a browser.
