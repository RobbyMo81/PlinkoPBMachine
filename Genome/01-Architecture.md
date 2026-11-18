# 01 — Architecture

**PlinkoBPMachine Cold-Start MVP · Pass-3 handoff**

Companions are [02 — Build Instructions & Testing](02-Build-Instructions.md) and [03 — Loop Workflow Instructions & Independent AI Reviewer](03-Loop-Workflow.md). This document defines the MVP contracts and authority. Document 02 defines implementation and check criteria. Document 03 defines their sequence. Report any conflict before acting on the affected step.

## Purpose and scope

Demonstrate that an isolated laboratory can execute two mathematical seeds and one non-evolving random control, produce valid rankings and draws, and complete one independently verified mutation and one independently verified crossover. The seed-only historical evaluation describes fixed-ranking performance. Testing predictive advantage, the Plinko sum-bin hypothesis, or multi-generation evolution is outside the MVP.

Build approval covers implementation. The project owner authorizes preflight and the experimental run separately through an authenticated, human-controlled channel outside the AI workflow. Only the owner’s trusted authorization record grants stage authorization. AI participants and the controller have no permission to create or modify it.

| Stage | Owner authorization binds |
|---|---|
| Preflight | Stage and exact sandbox profile, including runtime image identity. The same owner authorization explicitly scopes pre-run snapshot preparation to the absolute canonical database path and approved development window. |
| Experiment | Run ID, exact sandbox profile, passing preflight record, and exactly the five single-use launch slots below. |

| Launch slot ID | Purpose |
|---|---|
| `SEED-G1` | G1 mathematical seed |
| `SEED-G2` | G2 mathematical seed |
| `SEED-G3` | G3 random control |
| `MUTATION-G2` | Offspring from the approved G2 mutation |
| `CROSSOVER-G1-G2` | Offspring from either approved G1/G2 crossover orientation |

The authenticated experiment authorization delegates to the rule-based gate the authority to derive one launch approval per named slot. The gate binds that slot to the exact executable-artifact fingerprint once the artifact exists and records the parent authorization. It verifies the applicable deterministic checks, independent approval, and matching image, profile, and preflight before issuance. The gate durably consumes each approval before requesting launch. Skipped or blocked slots cannot be reassigned. A reproductive proposal request consumes the branch’s Discovery opportunity. Its launch slot remains unused if the candidate is rejected before launch.

## Responsibilities and boundaries

| Component | Responsibility |
|---|---|
| Deterministic controller | Schedules sequential work and opens at most one proposal opportunity per reproductive branch |
| Discovery AI | Proposes the bounded mutation and the crossover independently from verified seeds |
| Deterministic Validator | Runs controlled preflight fixtures and checks artifacts, outputs, and lineage |
| Critical Verifier | Independently reviews preflight and candidates, tallies the limited evaluator fixture, and verifies the closed evidence bundle |
| Trusted snapshot preparer | Uses a dedicated authenticated identity to prepare the development export and limited fixture before the timed run. Retains custody of the staging copy and publishes the `DATA-01` count and digest evidence. |
| Rule-based gate | Verifies owner authorization and evidence, issues and consumes single-use launch approvals under delegation, and governs admission |
| Independent Resource Controller (IRC) | Owns the run, AI-interaction, and container deadlines, checks effective runtime and output limits, and confirms containment after a stop |
| Journal writer | Owns the append-only journal and accepts authenticated event submissions |

Genome code runs in sequential, nonprivileged, network-isolated containers with read-only code and inputs, no writable workspace, and no access to production data, control interfaces, or the authoritative journal. Among laboratory consumers, the evaluator alone receives the full immutable development export. The trusted snapshot preparer provides the Critical Verifier with a small read-only fixture of development draws for the known-answer check. Discovery AI receives the approved operation rules and authorized parent IDs, DNA, and structural records. Its input excludes player cards, historical draws, fitness, and novelty records. Changing live ranking rules requires separate, explicit project-owner approval identifying the exact change and evidence.

## Genome contracts

| Seed | Contract |
|---|---|
| G1 | Modular scoring, `(5x + 7) mod 29` in both pools |
| G2 | Quadratic scoring, `-2x² + 37x + 11` in both pools |
| G3 | Uniform sample of five distinct white balls, a uniform draw Powerball, and an independent uniform PB permutation. Uses separate reproducible streams from one recorded seed. Excluded from reproduction and selection. |

Each mathematical module takes a candidate in its assigned pool and returns an integer. Rank by descending score and then ascending ball number. Every genome returns a permutation of PB 1–26 and a draw of five distinct white balls 1–69 plus one PB 1–26. Mathematical draws use the first-ranked PB and the five highest-ranked whites.

- **Mutation:** G2 is the verified parent. Discovery AI chooses a shared linear coefficient of 36 or 38. The quadratic coefficient and constant stay fixed. The change applies to both pools. Both choices preserve the unordered Top-3 PB set and complete draw. Pass the branch on verified DNA change, parentage, and correct outputs.
- **Crossover:** Discovery AI chooses either G1 PB with G2 whites or G2 PB with G1 whites and names both donors in its single proposal. Inherit each complete module from its verified seed parent. Both reproductive branches originate from the initial seeds.

For mathematical genomes, use version 1 DNA records with `pb` and `white_balls` slots. Each slot holds a family and its exact integer parameters. The full-DNA fingerprint covers the versioned record. The module fingerprint covers one complete slot value. The structural fingerprint covers the versioned slots with each slot reduced to its family. Follow the canonical encoding and hash fixture in Document 02. At a launch or admission gate, **candidate fingerprint means the executable-artifact fingerprint**. DNA, module, and structural fingerprints identify genetic content and lineage.

## Evidence and history

Give every seed and offspring a permanent individual ID. The G-018 player card presents 12 fields: genome ID, taxonomy, structural fingerprint, full DNA fingerprint, parentage, method, fitness, novelty, verification, lifecycle, evidence references, and record version. Record G3’s control method and link the seed and generator version as run provenance. Use explicit unavailable or unassessed values where a field does not apply.

Count distinct complete draws once across the experiment, treating white-ball order as immaterial. Report distinct sets and duplicate events descriptively. **G-017** requires independent certification of structural or behavioral novelty against versioned comparison records and calibrated criteria, with functional validity and reproducibility verified. Algorithmic novelty remains unverified in this MVP. Verified DNA changes and draw uniqueness have their own evidence.

The development window is October 7, 2015 through December 31, 2025 inclusive. Only G1, G2, and G3 receive historical scores. The 2026 window stays outside the MVP. Its later use requires owner authorization and advance registration of candidate fingerprints, window, metric, and decision rule. Record possible exposure from the live experiment’s published outcomes or other sources. If exposure that could influence candidate design cannot be ruled out, report that evaluation as exploratory and use fresh prospective draws for confirmation.

## MVP governance references

| Decision | Rule used in this handoff |
|---|---|
| G-000 | Discovery, deterministic validation, independent review, and authorization are distinct. Unresolved critical objections block progression. |
| G-001 | Recombination uses compatible modules with verified lineage. Admitted outputs satisfy the complete PB ranking and candidate-draw contracts. |
| G-017 / G-018 | Algorithmic novelty requires independent certification. Player cards present identity, lineage, and verification from authoritative evidence as defined above. |
| G-019 | Approve one architectural decision at a time. Implementation, preflight, and the run follow the project owner’s approved authorization sequence. |
| G-022 | The deterministic IRC has independent enforcement authority. The scheduler and AI cannot override the fixed run limits. |
| P-03.01 | The evaluator must match an independently tallied fixture of actual development draws using G1’s pinned PB permutation before scoring. See `EVAL-01` in Document 02. |
