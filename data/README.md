# DRAAD demo scenarios

The 10 cases that drive Lab 5 evaluation, grounded in the synthetic data in [`data`](./data).

---

## 1. Synthetic data summary

Three pool files under [`data`](./data):

- [`crew.json`](./datacrew.json) — 6 crew members, all `WV-BLS`.
- [`raamopdrachten.json`](./dataraamopdrachten.json) — 6 ROs.
- [`incidents.json`](./dataincidents.json) — 10 incidents. Every incident has the full 6-crew shortlist in `available_crew[]`.

### Crew → RO map

| Crew | Home | RO | RO scope (covered VWIs) | Region | Live work | Status |
|---|---|---|---|---|---|---|
| crew-001 K. de Vries | Heerhugowaard | RA-NHN-0101 | E-22-sp-loos, E-67, E-85 | 1700s (Heerhugowaard) | no | valid |
| crew-002 M. Janssen | Alkmaar | RA-NHN-0102 | E-22-onder-sp, E-66, E-67, E-85 | 1810–1825 (Alkmaar) | **yes** | valid |
| crew-003 T. Smit | Heerhugowaard | RA-NHN-0103 | E-48 | full NHN (1620s + 1700s + 1810–1825) | no | valid |
| crew-004 R. Bakker | Hoorn | RA-NHN-0104 | E-04, E-22-sp-loos, E-67, E-85 | 1620s (Hoorn) | no | **EXPIRED 2026-05-20** |
| crew-005 J. de Boer | Hoorn | RA-NHN-0105 | E-04, E-22-sp-loos, E-40-sp-loos, E-67, E-85 | 1620s (Hoorn) | no | valid |
| crew-006 S. van Dijk | Alkmaar | RA-NHN-0106 | E-11, E-22-sp-loos, E-40-sp-loos, E-67, E-85 | 1810–1825 (Alkmaar) | no | valid |

### Indexed VWI catalogue (10 entries)

| VWI | Dutch name (official) |
|---|---|
| E-04 | Het in en uit bedrijf nemen en veiligstellen van een LS-netdeel |
| E-11 | Een LS-kabel selecteren |
| E-22-onder-sp | Een LS-groep plaatsen/verwijderen op een LS-rek (onder spanning) |
| E-22-sp-loos | Een LS-groep plaatsen/verwijderen op een LS-rek (spanningsloos) |
| E-40-sp-loos | Een verbindingsmof monteren (spanningsloos) |
| E-48 | Toezicht bij het uitvoeren van civiele werkzaamheden in de grond |
| E-60 | Een (mogelijk) gevaarlijke situatie bij een aansluiting opheffen |
| E-66 | Een zekeringhouder of installatieautomaat onder spanning verwisselen |
| E-67 | Storingen in aansluitkasten kleiner of gelijk aan 3x80 A verhelpen |
| E-85 | Zekeringen vervangen |

**E-60 is deliberately not in any RO's `covered_vwi_ids`** — drives the partial-coverage path in case 1.

### Hackathon simplifications (read once)

- All crew hold `WV-BLS`, the highest field-crew aanwijzing. Rule 6 (aanwijzing sufficiency) is wired in the rule_checker but trivially passes everywhere. Post-hackathon: replace with verified per-VWI map.
- RO prose enumerates covered E-numbers verbatim (real ROs sometimes describe scope operationally). Lets the matcher cite cleanly.
- `confidence` is 2-value enum (`confirmed` | `candidate`). Required prerequisites → `confirmed`. *Possible* prerequisites mentioned in rationale prose only, not added to `vwis[]`.
- Scope is BLS only. BHS out.

---

## 2. The 10 demo cases

Each case lists the incident shape, the matched crew/RO/VWIs, and what the case tests.

---

### Case 1 — Aansluitkast brandlucht (lead demo, partial coverage)

**Incident** ([INC-2026-05-21-001](./dataincidents.json)): Klant in Heerhugowaard (postcode 1701) meldt brandlucht uit de meterkast, hoofdschakelaar uit, geen rookontwikkeling.

**Expected match**: **crew-001 K. de Vries / RA-NHN-0101** (correct region 1700s; standard storingen-RO).

**Expected `vwis[]`**: `E-67` (candidate), `E-60` (candidate). Both candidate because cause is unconfirmed — brandlucht is a symptom.

**Why**: RA-NHN-0101 covers E-67 (aansluitkast storing) but **not** E-60 (gevaarlijke situatie) — no RO covers E-60. So:

- `coverage_status = partial`
- `operational_action = wv_escalation_needed` (dangerous-situation soft rule fires in `dispatch_reviewer` because of "brandlucht" + partial coverage)

**Tests**: dangerous-situation soft rule; symptom-vs-cause discipline (both VWIs `candidate`); partial-coverage path.

---

### Case 2 — Klant zonder stroom, vermoedelijk zekering (happy path)

**Incident** ([INC-2026-05-21-002](./dataincidents.json)): Single klant in Heerhugowaard (1704) zonder stroom op één groep, vermoedt zekering, geen brandlucht.

**Expected match**: **crew-001 K. de Vries / RA-NHN-0101** (region match, RA covers E-85).

**Expected `vwis[]`**: `E-85` (confirmed).

**Why**: cause is concrete (zekering), single VWI, region+scope match cleanly.

- `coverage_status = covered`
- `operational_action = dispatch_ok`

**Tests**: clean happy-path control. Lab 5 needs at least one full green pass.

---

### Case 3 — LS-groep plaatsen/verwijderen op LS-rek onder spanning

**Incident** ([INC-2026-05-21-003](./dataincidents.json)): Geplande herconfiguratie LS-rek in Alkmaar (1815). Eén LS-groep moet onder spanning verwijderd/herplaatst worden. Rek blijft onder spanning.

**Expected match**: **crew-002 M. Janssen / RA-NHN-0102** — the only RO with `permits_live_work: true` AND that covers E-22-onder-sp.

**Expected `vwis[]`**: `E-22-onder-sp` (confirmed) — incident text explicitly names "LS-groep onder spanning verwijderd/herplaatst", grounded in the official VWI title.

- `coverage_status = covered`
- `operational_action = dispatch_ok`

**What would fail**: crew-006 (S. van Dijk) is also in Alkmaar region but RA-NHN-0106 has `permits_live_work: false`. If the matcher picks 006, rule 5 (live-work permission) fails → revise loop forces 002.

**Tests**: live-work permission rule on `-onder-sp` variant; matcher picking the live-variant; revise loop on rule 5.

---

### Case 4 — Verbindingsmof storing, oorzaak onduidelijk

**Incident** ([INC-2026-05-21-004](./dataincidents.json)): SCADA-alarm, storing op LS-kabel in Hoorn (1622), vermoedelijk moffail, oorzaak (water, mechanisch, degradatie) niet bevestigd. Flikkerend licht, afwijkende stroommeting, geen volledige uitval.

**Expected match**: **crew-005 J. de Boer / RA-NHN-0105** — region 1620s, RA covers E-40-sp-loos. (crew-004 also in Hoorn but RA expired; crew-006 covers E-40-sp-loos but wrong region.)

**Expected `vwis[]`**: `E-40-sp-loos` (candidate) — final scope (variant + whether moef actually needs replacing) only resolved on-site by LMRA.

- `coverage_status = covered`
- `operational_action = dispatch_ok`

Rationale prose may mention E-04 (isolation) or E-11 (cable selection) as *possible* prerequisites — **prose only, not in `vwis[]`**, because the incident doesn't actually require them.

**Tests**: variant uncertainty is **not** an escalation trigger; `candidate` confidence is an honest stance, doesn't force escalation; discipline of keeping speculative prerequisites in prose only.

---

### Case 5 — Onder-spanning zekeringhouder vervangen

**Incident** ([INC-2026-05-21-005](./dataincidents.json)): Geplande vervanging zekeringhouder in aansluitkast Alkmaar (1815), onder spanning omdat twee zorgklanten gevoed worden.

**Expected match**: **crew-002 M. Janssen / RA-NHN-0102** — only live-work RO in Alkmaar region, RA covers E-66.

**Expected `vwis[]`**: `E-66` (confirmed).

- `coverage_status = covered`
- `operational_action = dispatch_ok`

**Tests**: live-work permission rule must be **VWI-agnostic** (E-66 is a standalone live VWI, not a `-onder-sp` suffix). The rule has to look up `is_live_work` from the VWI catalogue, not pattern-match on the suffix. Crew-006 in same region would fail rule 5.

---

### Case 6 — LS-netdeel uit bedrijf nemen, eerstgekozen RO verlopen (revise loop)

**Incident** ([INC-2026-05-21-006](./dataincidents.json)): Gepland: LS-netdeel uitbedrijfneming en veiligstellen voor onderhoud trafostation Hoorn-West (1622).

**First match attempt**: **crew-004 R. Bakker / RA-NHN-0104** — Hoorn region, RA covers E-04. But `geldigheidsduur_end = 2026-05-20` (yesterday). Rule 3 (temporal validity) **fails**.

**After revise**: **crew-005 J. de Boer / RA-NHN-0105** — same region, also covers E-04, still valid.

**Expected `vwis[]`**: `E-04` (confirmed).

- `coverage_status = covered` (after revise)
- `operational_action = dispatch_ok`

**Tests**: revise loop end-to-end. Only case where two crew/RO combos are exercised in one run.

---

### Case 7 — Postcode buiten geldigheidsgebied (geographic fail, no recovery)

**Incident** ([INC-2026-05-21-007](./dataincidents.json)): Storing aansluitkast ≤3×80A in **Den Helder (1781)**, 24 huishoudens zonder stroom.

**Expected match**: **none**. Postcode 1781 is in NHN but not in any RO's `geldigheidsgebied_postcodes[]` (all ROs cover 1620s, 1700s, or 1810–1825 only).

**Expected `vwis[]`**: `E-67` (confirmed) — incident explicitly names "aansluitkast ≤3×80A", grounded in the official VWI title.

For every crew/RO combo the matcher tries, rule 4 (geographic validity) fails. After retries exhausted:

- `coverage_status = not_covered`
- `operational_action = wv_escalation_needed`
- `review_status = flagged_for_human_review`

**Tests**: rule 4 (geographic validity); revise-loop termination at max retries; escalation on hard-rule failures with no recoverable alternative.

---

### Case 8 — Kabelfout op LS-groep, kabel onbekend (multi-VWI, mixed confidence)

**Incident** ([INC-2026-05-21-008](./dataincidents.json)): Veldcrew radio: kabelfout op LS-groep aan LS-rek in Alkmaar (1815), meerdere parallelle kabels in bundel — voedingskabel moet eerst geselecteerd en geïdentificeerd worden, daarna LS-groep spanningsloos verwijderd/herplaatst.

**Expected match**: **crew-006 S. van Dijk / RA-NHN-0106** — only RO with E-11 (cable selection), region match, also covers E-22-sp-loos.

**Expected `vwis[]`**:
- `E-11` (**confirmed**) — required prerequisite explicitly named in incident.
- `E-22-sp-loos` (**candidate**) — subsequent action named, but final scope contingent on cable-ID result + on-site LMRA.

- `coverage_status = covered` (both in RA's `covered_vwi_ids`)
- `operational_action = dispatch_ok`

**Tests**: multi-VWI sequencing with mixed confidence within one `vwis[]` array. Only case exercising mixed confidence.

---

### Case 9 — Toezicht bij graafwerk derden

**Incident** ([INC-2026-05-21-009](./dataincidents.json)): Aannemer Van der Velde Infra start graafwerk Heerhugowaard (1705) voor glasvezeluitrol nabij LS-kabel; Liander toezicht gevraagd.

**Expected match**: **crew-003 T. Smit / RA-NHN-0103** — the only RO with E-48 in scope. Region check passes (1700s covered).

**Expected `vwis[]`**: `E-48` (confirmed).

- `coverage_status = covered`
- `operational_action = dispatch_ok`

**Tests**: supervisory VWI (different class from hands-on work). Forces the matcher to pick the supervisor, not a hands-on monteur. Region overlap with crew-001 doesn't matter — RA-NHN-0101 doesn't cover E-48.

---

### Case 10 — MS-asset gemeld op LS-storingslijn (no-fit refusal)

**Incident** ([INC-2026-05-21-010](./dataincidents.json)): Melding via LS-storingslijn betreft kennelijk een **MS-ringstoring** (middenspanning kring 13 stedelijk Alkmaar). Misroutering door KCC. Postcode 1701 is van de beller, niet van de storing.

**Expected match**: **none** — no indexed BLS VWI matches an MS-asset incident.

**Expected `vwis[]`**: `[]` (empty).

- `coverage_status = unknown`
- `operational_action = wv_escalation_needed`
- `review_status = flagged_for_human_review`

**Tests**: matcher must refuse to invent a fit; reviewer must escalate cleanly when no candidate VWI exists in the indexed corpus. Hard rule against hallucination.

---

## 3. Coverage matrix

### VWI → case(s)

| VWI | Case(s) |
|---|---|
| E-04 | 6 |
| E-11 | 8 |
| E-22-onder-sp | 3 |
| E-22-sp-loos | 8 |
| E-40-sp-loos | 4 |
| E-48 | 9 |
| E-60 | 1 |
| E-66 | 5 |
| E-67 | 1, 7 |
| E-85 | 2 |

Every indexed VWI exercised by ≥1 case.

### Crew → case(s)

| Crew | Case(s) | Role in case |
|---|---|---|
| crew-001 K. de Vries | 1, 2 | match (1700s, sp-loos scope) |
| crew-002 M. Janssen | 3, 5 | match (Alkmaar, live work) |
| crew-003 T. Smit | 9 | match (toezicht E-48) |
| crew-004 R. Bakker | 6 | first pick → temporal fail → revise |
| crew-005 J. de Boer | 4, 6 | match (Hoorn) |
| crew-006 S. van Dijk | 8 | match (Alkmaar, E-11 only here) |

### Failure-mode coverage (Lab 5 planted failures)

| Failure mode | Case |
|---|---|
| Partial coverage (VWI missing from any RO) | 1 |
| Temporal fail → revise recovers | 6 |
| Geographic fail → revise exhausts → escalate | 7 |
| No-fit refusal → empty `vwis[]` + escalate | 10 |

### Lab 5 exact-match targets

Per case: `confirmed` VWI set + `coverage_status` + `operational_action` (+ `review_status` where flagged).

---

## 4. Coverage-status logic (recap)

| coverage_status | When |
|---|---|
| `covered` | Every selected VWI appears in matched RO's `covered_vwi_ids[]`. |
| `partial` | Some but not all selected VWIs appear. |
| `not_covered` | None of the selected VWIs appear in any candidate RO. |
| `unknown` | Retrieval returned no usable ROs (incl. case 10's no-VWI case). |

Full rule split (deterministic vs LLM) in [briefing §6 (3)](./briefing-shenglin-evi-2026-05-20.md).
