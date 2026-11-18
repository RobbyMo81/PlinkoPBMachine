"""Genome contracts (Document 01): scoring, ranking, draws, G3, offspring.

Rank by descending score, then ascending ball number. Every genome returns a
complete PB permutation of 1-26 and a draw of five distinct white balls 1-69
plus one PB 1-26. Mathematical draws use the first-ranked PB and the five
highest-ranked whites; G3 uses its own uniform draw PB plus an independent
uniform permutation.
"""

from collections.abc import Mapping
from hashlib import sha256

from genome_lab.config import HIT_SET_SIZE
from genome_lab.dna import MODULAR, QUADRATIC, DNARecord, Slot

WHITE_LO, WHITE_HI = 1, 69
PB_LO, PB_HI = 1, 26
DRAW_WHITES = 5

MUTATION_B_CHOICES = (36, 38)
G3_GENERATOR_VERSION = "g3-stream-v1"

G1 = DNARecord(
    pb=Slot(MODULAR, {"a": 5, "b": 7, "m": 29}),
    white_balls=Slot(MODULAR, {"a": 5, "b": 7, "m": 29}),
)
G2 = DNARecord(
    pb=Slot(QUADRATIC, {"a": -2, "b": 37, "c": 11}),
    white_balls=Slot(QUADRATIC, {"a": -2, "b": 37, "c": 11}),
)
SEEDS = {"G1": G1, "G2": G2}

# EVAL-01 pinned input (Document 02): G1's complete PB ranking.
G1_PINNED_PB_RANKING = (
    10,
    4,
    21,
    15,
    9,
    3,
    26,
    20,
    14,
    8,
    2,
    25,
    19,
    13,
    7,
    1,
    24,
    18,
    12,
    6,
    23,
    17,
    11,
    5,
    22,
    16,
)


def score(slot: Slot, x: int) -> int:
    params = slot.parameters
    if slot.family == MODULAR:
        return (params["a"] * x + params["b"]) % params["m"]
    return params["a"] * x * x + params["b"] * x + params["c"]


def rank_pool(slot: Slot, lo: int, hi: int) -> list[int]:
    """Rank pool values lo..hi by descending score, then ascending ball number."""
    return sorted(range(lo, hi + 1), key=lambda x: (-score(slot, x), x))


def pb_permutation(dna: DNARecord) -> list[int]:
    return rank_pool(dna.pb, PB_LO, PB_HI)


def draw_from(dna: DNARecord) -> dict:
    whites = rank_pool(dna.white_balls, WHITE_LO, WHITE_HI)[:DRAW_WHITES]
    return {"whites": sorted(whites), "pb": pb_permutation(dna)[0]}


def evaluate_genome(dna: DNARecord) -> dict:
    """Complete genome output: PB permutation, draw, and identity fingerprint."""
    return {
        "pb_ranking": pb_permutation(dna),
        "draw": draw_from(dna),
        "full_dna_fingerprint": dna.full_fingerprint(),
    }


def pinned_ranking_matches() -> bool:
    return tuple(pb_permutation(G1)) == G1_PINNED_PB_RANKING


class _Stream:
    """Deterministic SHA-256 counter-mode stream: separate reproducible streams
    from one recorded seed (G3 contract)."""

    def __init__(self, seed: str, stream_id: str) -> None:
        self._prefix = f"{seed}|{stream_id}|".encode()
        self._counter = 0
        self._buffer = b""

    def _take(self, n: int) -> bytes:
        while len(self._buffer) < n:
            block = sha256(self._prefix + str(self._counter).encode("ascii")).digest()
            self._buffer += block
            self._counter += 1
        taken, self._buffer = self._buffer[:n], self._buffer[n:]
        return taken

    def below(self, n: int) -> int:
        """Uniform integer in [0, n) via rejection sampling."""
        if n <= 0:
            raise ValueError("n must be positive")
        nbytes = (n - 1).bit_length() // 8 + 1
        limit = (256**nbytes // n) * n
        while True:
            value = int.from_bytes(self._take(nbytes), "big")
            if value < limit:
                return value % n


def g3_outputs(seed: str) -> dict:
    """G3 random control: uniform distinct white sample, uniform draw PB, and an
    independent uniform PB permutation, from three streams of one recorded seed."""
    sample = _Stream(seed, "white_sample")
    draw_pb = _Stream(seed, "draw_powerball")
    permutation = _Stream(seed, "pb_permutation")

    pool = list(range(WHITE_LO, WHITE_HI + 1))
    for i in range(DRAW_WHITES):
        j = i + sample.below(len(pool) - i)
        pool[i], pool[j] = pool[j], pool[i]
    whites = sorted(pool[:DRAW_WHITES])

    pb = PB_LO + draw_pb.below(PB_HI - PB_LO + 1)

    perm = list(range(PB_LO, PB_HI + 1))
    for i in range(len(perm) - 1, 0, -1):
        j = permutation.below(i + 1)
        perm[i], perm[j] = perm[j], perm[i]

    return {
        "pb_ranking": perm,
        "draw": {"whites": whites, "pb": pb},
        "generator_version": G3_GENERATOR_VERSION,
        "seed": seed,
    }


def mutation_offspring(b: int) -> DNARecord:
    if b not in MUTATION_B_CHOICES:
        raise ValueError(f"mutation linear coefficient must be one of {MUTATION_B_CHOICES}")
    slot = Slot(QUADRATIC, {"a": -2, "b": b, "c": 11})
    return DNARecord(pb=slot, white_balls=slot)


def crossover_offspring(pb_donor: DNARecord, whites_donor: DNARecord) -> DNARecord:
    """Inherit each complete module from its verified seed parent."""
    return DNARecord(pb=pb_donor.pb, white_balls=whites_donor.white_balls)


def validate_mutation(offspring: DNARecord, parent: DNARecord = G2) -> list[str]:
    """Enforce the approved G2 change: only the shared linear coefficient moves."""
    errors = []
    if offspring.pb.record() != offspring.white_balls.record():
        errors.append("mutation must apply to both pools identically")
    for slot_name in ("pb", "white_balls"):
        child = getattr(offspring, slot_name)
        grown = getattr(parent, slot_name)
        if child.family != grown.family:
            errors.append(f"{slot_name}: family changed")
            continue
        changed = {k for k in grown.parameters if grown.parameters[k] != child.parameters.get(k)}
        if grown.family == QUADRATIC:
            if changed - {"b"}:
                errors.append(f"{slot_name}: only b may change, changed {sorted(changed)}")
            if child.parameters.get("b") not in MUTATION_B_CHOICES:
                errors.append(f"{slot_name}: b must be one of {MUTATION_B_CHOICES}")
        elif changed:
            errors.append(f"{slot_name}: parameters changed {sorted(changed)}")
    return errors


def validate_crossover(
    offspring: DNARecord, pb_parent: DNARecord, whites_parent: DNARecord
) -> list[str]:
    """Compare both inherited module fingerprints with the declared donor slots."""
    errors = []
    if offspring.module_fingerprint("pb") != pb_parent.module_fingerprint("pb"):
        errors.append("pb module fingerprint does not match its donor parent")
    if offspring.module_fingerprint("white_balls") != whites_parent.module_fingerprint(
        "white_balls"
    ):
        errors.append("white_balls module fingerprint does not match its donor parent")
    return errors


def validate_output(output: Mapping) -> list[str]:
    """Validate the complete ranking and draw contracts (G-001)."""
    errors = []
    ranking = output.get("pb_ranking")
    if not isinstance(ranking, list) or sorted(ranking) != list(range(PB_LO, PB_HI + 1)):
        errors.append("pb_ranking must be a permutation of 1..26")
    draw = output.get("draw")
    if not isinstance(draw, Mapping):
        errors.append("draw must be an object")
        return errors
    whites = draw.get("whites")
    pb = draw.get("pb")
    if (
        not isinstance(whites, list)
        or len(whites) != DRAW_WHITES
        or len(set(whites)) != DRAW_WHITES
        or any(not isinstance(w, int) or not WHITE_LO <= w <= WHITE_HI for w in whites)
    ):
        errors.append("draw whites must be five distinct integers in 1..69")
    if not isinstance(pb, int) or not PB_LO <= pb <= PB_HI:
        errors.append("draw pb must be an integer in 1..26")
    return errors


def recompute_expected(dna: DNARecord) -> dict:
    """Independently recompute a mathematical genome's outputs."""
    return evaluate_genome(dna)


def verify_candidate_output(dna: DNARecord, output: Mapping) -> list[str]:
    """RUN-OUTPUT: validate and independently recompute both outputs."""
    errors = validate_output(output)
    expected = recompute_expected(dna)
    if list(output.get("pb_ranking") or []) != expected["pb_ranking"]:
        errors.append("pb_ranking does not match independent recomputation")
    if dict(output.get("draw") or {}) != expected["draw"]:
        errors.append("draw does not match independent recomputation")
    return errors


def g3_input_record(seed: str) -> dict:
    """The G3 candidate input record: random control, excluded from
    reproduction and selection; the seed and generator version are recorded
    as run provenance before launch."""
    return {"g3": {"seed": seed, "generator_version": G3_GENERATOR_VERSION}}


def expected_output_for_input(record) -> dict:
    """Independently recompute the expected engine output for a candidate
    input record (DNA record or G3 control record)."""
    from genome_lab.dna import canonical_bytes, dna_from_record, sha256_hex

    data = dict(record)
    if "g3" in data:
        output = dict(g3_outputs(data["g3"]["seed"]))
    else:
        output = evaluate_genome(dna_from_record(data))
    output["input_fingerprint"] = sha256_hex(canonical_bytes(data))
    return output


def is_hit(actual_pb: int, ranking: list[int]) -> bool:
    """Build decision B1: a hit is actual PB within the top-ranked PB values."""
    return actual_pb in ranking[:HIT_SET_SIZE]
