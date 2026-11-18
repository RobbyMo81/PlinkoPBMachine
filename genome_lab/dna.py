"""DNA records, canonical serialization, and fingerprints (Document 02).

Serialize DNA as compact UTF-8 JSON with object keys sorted lexicographically
at every level, integer parameters in base 10, and no optional whitespace,
BOM, or trailing newline. The full-DNA fingerprint covers the versioned
record; the module fingerprint covers one complete slot value; the structural
fingerprint covers the versioned slots reduced to families.

Build decision (red-team B2): the executable artifact is a generic genome
engine and the DNA record is a declared read-only input, so no per-candidate
artifact build is needed inside the run clock. The ten canonical fixture
digestes below are the PF-DNA known-answer set.
"""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass

DNA_VERSION = 1
MODULAR = "modular"
QUADRATIC = "quadratic"

SLOT_KEYS = ("family", "parameters")
PARAM_KEYS = {MODULAR: ("a", "b", "m"), QUADRATIC: ("a", "b", "c")}


def canonical_bytes(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _validate_slot(name: str, slot: Mapping) -> None:
    if set(slot) != set(SLOT_KEYS):
        raise ValueError(f"{name}: slot keys must be {SLOT_KEYS}, got {sorted(slot)}")
    family = slot["family"]
    if family not in PARAM_KEYS:
        raise ValueError(f"{name}: unknown family {family!r}")
    params = slot["parameters"]
    expected = PARAM_KEYS[family]
    if set(params) != set(expected):
        raise ValueError(f"{name}: {family} parameters must be {expected}")
    for key, value in params.items():
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError(f"{name}: parameter {key} must be an integer")


@dataclass(frozen=True)
class Slot:
    family: str
    parameters: Mapping[str, int]

    def record(self) -> dict:
        return {"family": self.family, "parameters": dict(self.parameters)}

    def structural(self) -> dict:
        return {"family": self.family}


@dataclass(frozen=True)
class DNARecord:
    pb: Slot
    white_balls: Slot
    version: int = DNA_VERSION

    def record(self) -> dict:
        return {
            "pb": self.pb.record(),
            "version": self.version,
            "white_balls": self.white_balls.record(),
        }

    def canonical(self) -> bytes:
        return canonical_bytes(self.record())

    def full_fingerprint(self) -> str:
        return sha256_hex(self.canonical())

    def module_fingerprint(self, slot_name: str) -> str:
        if slot_name not in ("pb", "white_balls"):
            raise ValueError(f"unknown slot {slot_name!r}")
        return sha256_hex(canonical_bytes(getattr(self, slot_name).record()))

    def structural_fingerprint(self) -> str:
        return sha256_hex(
            canonical_bytes(
                {
                    "pb": self.pb.structural(),
                    "version": self.version,
                    "white_balls": self.white_balls.structural(),
                }
            )
        )


def dna_from_record(record: Mapping) -> DNARecord:
    if not isinstance(record, Mapping):
        raise TypeError("DNA record must be a JSON object")
    if set(record) != {"pb", "version", "white_balls"}:
        raise ValueError(f"DNA keys must be ['pb', 'version', 'white_balls'], got {sorted(record)}")
    if record["version"] != DNA_VERSION:
        raise ValueError(f"unsupported DNA version {record['version']!r}")
    for slot_name in ("pb", "white_balls"):
        _validate_slot(slot_name, record[slot_name])
    return DNARecord(
        pb=Slot(record["pb"]["family"], dict(record["pb"]["parameters"])),
        white_balls=Slot(
            record["white_balls"]["family"], dict(record["white_balls"]["parameters"])
        ),
    )


def load_dna(path) -> DNARecord:
    with open(path, "rb") as handle:
        return dna_from_record(json.loads(handle.read().decode("utf-8")))


# Canonical known-answer fixtures (Document 02, PF-DNA): name -> (content, digest).
CANONICAL_FIXTURES: dict[str, tuple[str, str]] = {
    "G1 module": (
        '{"family":"modular","parameters":{"a":5,"b":7,"m":29}}',
        "28e89e68cf94eb68a1ae0b76c3902896f465002133ae47b43e343bd95e160304",
    ),
    "G1 full DNA": (
        (
            '{"pb":{"family":"modular","parameters":{"a":5,"b":7,"m":29}},'
            '"version":1,"white_balls":{"family":"modular","parameters":{"a":5,"b":7,"m":29}}}'
        ),
        "4c7a907d6274c9e8c5cda398e7a9c9faf99edc98a01fa7bcc31a555a73e2328f",
    ),
    "G1 structural": (
        '{"pb":{"family":"modular"},"version":1,"white_balls":{"family":"modular"}}',
        "47ad724100ae543359e4fb9bb9693d4bf0be34add8eebdfe07f0bcc54983d0fa",
    ),
    "G2 module": (
        '{"family":"quadratic","parameters":{"a":-2,"b":37,"c":11}}',
        "7d7655262fc5e4b30d34a30619b3135c93ba9a30534d5867d64aed9692335329",
    ),
    "G2 full DNA": (
        (
            '{"pb":{"family":"quadratic","parameters":{"a":-2,"b":37,"c":11}},'
            '"version":1,"white_balls":{"family":"quadratic","parameters":{"a":-2,"b":37,"c":11}}}'
        ),
        "98d95c34cee3014a7d16732a34c38d0bebc21c007f477fae6a75fd2f50308942",
    ),
    "G2 structural": (
        '{"pb":{"family":"quadratic"},"version":1,"white_balls":{"family":"quadratic"}}',
        "fb3b43de3b2d77af2c77f78fe648c5c941d6d3a40e7fb8fedfd329a34523b8fd",
    ),
    "Mutation 36 module": (
        '{"family":"quadratic","parameters":{"a":-2,"b":36,"c":11}}',
        "ffa7428e5312503d0276f51158b45dbb02899e8e8cf1b4068674b6cb0d52646a",
    ),
    "Mutation 38 module": (
        '{"family":"quadratic","parameters":{"a":-2,"b":38,"c":11}}',
        "79e664ba36b4107abb9b6feda26b3aa317346dfed07429025cbcd22ce5e7c62e",
    ),
    "Crossover G1 PB + G2 whites": (
        (
            '{"pb":{"family":"modular","parameters":{"a":5,"b":7,"m":29}},'
            '"version":1,"white_balls":{"family":"quadratic","parameters":{"a":-2,"b":37,"c":11}}}'
        ),
        "3e09d28c62106c0a7e045d7ed3c02c0afad298818e87fdc42c27dadc2017c8a5",
    ),
    "Crossover G2 PB + G1 whites": (
        (
            '{"pb":{"family":"quadratic","parameters":{"a":-2,"b":37,"c":11}},'
            '"version":1,"white_balls":{"family":"modular","parameters":{"a":5,"b":7,"m":29}}}'
        ),
        "9a9ebfbe3477d0b6756b627a52d38661d88dccee033d83a8513b206447d112ad",
    ),
}


def verify_canonical_fixtures() -> list[str]:
    """PF-DNA: verify all ten canonical fixture hashes. Returns failures."""
    failures = []
    for name, (content, expected) in CANONICAL_FIXTURES.items():
        actual = sha256_hex(content.encode("utf-8"))
        if actual != expected:
            failures.append(f"{name}: expected {expected}, computed {actual}")
    return failures
