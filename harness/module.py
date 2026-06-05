from __future__ import annotations

import hashlib
import importlib.util
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType


@dataclass(frozen=True)
class Candidate:
    problem_id: str
    source: str
    normalized_source: str
    candidate_hash: str
    instruction_count: int
    metadata: dict[str, object] = field(default_factory=dict)


class ResearchProblem(ABC):
    problem_id: str
    root: Path

    @abstractmethod
    def baseline(self) -> tuple[int, str]:
        """Return the canonical reference instruction count and assembly."""

    @abstractmethod
    def load(self, submission_blob: str) -> Candidate:
        """Materialize a submission into a candidate artifact."""

    @abstractmethod
    def verify(self, candidate: Candidate) -> bool:
        """Return True when a candidate passes deterministic checks."""

    @abstractmethod
    def score(self, candidate: Candidate) -> int:
        """Return the leaderboard score for a candidate."""


def normalize_assembly(source: str) -> str:
    lines: list[str] = []
    for raw in source.splitlines():
        line = raw.split("//", 1)[0].split(";", 1)[0].strip()
        if not line or line.endswith(":") or line.startswith("."):
            continue
        line = " ".join(line.replace(",", " , ").split()).replace(" ,", ",")
        lines.append(line)
    return "\n".join(lines) + ("\n" if lines else "")


def count_instructions(source: str) -> int:
    return len([line for line in normalize_assembly(source).splitlines() if line])


def hash_normalized_source(normalized_source: str) -> str:
    return hashlib.sha256(normalized_source.encode("utf-8")).hexdigest()


def load_problem_module(path: Path) -> ModuleType:
    module_path = path / "module.py"
    if not module_path.exists():
        raise FileNotFoundError(module_path)
    spec = importlib.util.spec_from_file_location(f"arm64golf_problem_{path.name}", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load problem module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
