# DRAAD synthetic scenarios

This directory contains the versioned, synthetic lookup data used by the DRAAD
reference application:

- [`crew.json`](./crew.json): six crew records and their raamopdracht mappings.
- [`raamopdrachten.json`](./raamopdrachten.json): six authorization scopes.
- [`incidents.json`](./incidents.json): ten repeatable example inputs.

The application reads these JSON files locally so every run uses the same
deterministic crew and authorization data. The Blob upload is an ingestion
exercise; it is not used by the runtime lookup path.

## Procedure corpus

`app/docs/VWI` contains 40 PDFs with 40 distinct, canonical VWI identifiers.
The document indexer also includes the BEI-BLS and raamopdracht-format PDFs, for
42 source PDFs in total. Each non-empty PDF page becomes a Search document.

Work-mode suffixes are safety-significant. Identifiers such as
`E-22-onder-sp` and `E-22-sp-loos` are different procedures. The application
accepts an exact match. A bare base may expand to a suffixed identifier only
when the indexed catalogue contains exactly one variant for that base. Because
E-22 and E-40 each have multiple variants, their bare base codes never count as
covered.

## Crew and authorization map

| Crew | Raamopdracht | Region | Covered VWIs | Live work | Valid through |
|---|---|---|---|---|---|
| crew-001 K. de Vries | RA-NHN-0101 | 1700–1709 | E-22-sp-loos, E-67, E-85 | no | 2026-12-31 |
| crew-002 M. Janssen | RA-NHN-0102 | 1810–1825 | E-22-onder-sp, E-66, E-67, E-85 | yes | 2026-12-31 |
| crew-003 T. Smit | RA-NHN-0103 | 1620s, 1700s, 1810–1825 | E-48 | no | 2026-12-31 |
| crew-004 R. Bakker | RA-NHN-0104 | 1620–1629 | E-04, E-22-sp-loos, E-67, E-85 | no | 2026-05-20 |
| crew-005 J. de Boer | RA-NHN-0105 | 1620–1629 | E-04, E-22-sp-loos, E-40-sp-loos, E-67, E-85 | no | 2026-12-31 |
| crew-006 S. van Dijk | RA-NHN-0106 | 1810–1825 | E-11, E-22-sp-loos, E-40-sp-loos, E-67, E-85 | no | 2026-12-31 |

## Deterministic selection behavior

Before the matcher runs, Python removes raamopdrachten that fail the incident
date, postcode, or explicit available-crew filter. The matcher selects only
VWIs. Python then chooses the surviving raamopdracht with the greatest exact,
safe VWI overlap and maps it to an available crew.

Consequences for the example set:

- Incident 6 never sends expired RA-NHN-0104 to the matcher; valid
  RA-NHN-0105 is the eligible Hoorn authorization.
- Incident 7 has no geographically eligible raamopdracht and escalates without
  trying an out-of-region assignment.
- The reviewer revision loop can request a corrected VWI selection or
  confidence. It cannot restore a raamopdracht removed by a hard prefilter.
- Empty, malformed, ambiguous, or uncovered VWI selections fail closed and
  require human review.

## Scenario expectations

| Case | Primary behavior | Expected outcome |
|---|---|---|
| 1 | Burning smell; E-67 plus uncovered E-60 candidate | partial coverage; escalate |
| 2 | Suspected fuse issue in 1704 | RA-NHN-0101; covered |
| 3 | E-22-onder-sp in 1815 | RA-NHN-0102; live-work scope required |
| 4 | Candidate E-40-sp-loos in 1622 | RA-NHN-0105; covered |
| 5 | E-66 in 1815 | RA-NHN-0102; live-work scope required |
| 6 | E-04 in 1622 after date prefilter | RA-NHN-0105; covered |
| 7 | E-67 in uncovered postcode 1781 | no raamopdracht; escalate |
| 8 | E-11 plus E-22-sp-loos in 1815 | RA-NHN-0106; covered |
| 9 | E-48 supervisory work in 1705 | RA-NHN-0103; covered |
| 10 | MS incident outside the BLS corpus | no VWI/raamopdracht; escalate |

These outcomes are teaching fixtures, not operational work authorizations.
