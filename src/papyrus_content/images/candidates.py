"""Where rounds of generated pictures and their private files are kept.

``CandidateStore`` is the interface the generation handlers use; ``InMemoryCandidateStore`` is the one the tests and specs use. The backend's own store (the
ImageCandidate rows and the private newsroom/image-candidates/ files, design section 7) implements the same calls.
"""
from __future__ import annotations

import copy
from typing import Protocol

TERMINAL = ("ready", "failed", "rejected", "applied", "unapplied", "expired")
CLOSED = ("rejected", "applied", "expired")


class CandidateStore(Protocol):
    def save_round(self, round_record: dict) -> None: ...
    def get_round(self, round_id: str) -> dict | None: ...
    def round_for_request(self, request_id: str, subject: str) -> dict | None: ...
    def save_candidate(self, candidate: dict) -> None: ...
    def get_candidate(self, candidate_id: str) -> dict | None: ...
    def candidates_of(self, round_id: str) -> list[dict]: ...
    def put_file(self, path: str, data: bytes) -> None: ...
    def read_file(self, path: str) -> bytes | None: ...
    def delete_file(self, path: str) -> None: ...
    def spent_on(self, day: str) -> float: ...


class InMemoryCandidateStore:
    def __init__(self) -> None:
        self.rounds: dict[str, dict] = {}
        self.candidates: dict[str, dict] = {}
        self.files: dict[str, bytes] = {}

    def save_round(self, round_record: dict) -> None:
        self.rounds[round_record["roundId"]] = copy.deepcopy(round_record)

    def get_round(self, round_id: str) -> dict | None:
        return copy.deepcopy(self.rounds.get(round_id))

    def round_for_request(self, request_id: str, subject: str) -> dict | None:
        return next((copy.deepcopy(row) for row in self.rounds.values() if row.get("requestId") == request_id and row.get("createdBy") == subject), None)

    def save_candidate(self, candidate: dict) -> None:
        self.candidates[candidate["id"]] = copy.deepcopy(candidate)

    def get_candidate(self, candidate_id: str) -> dict | None:
        return copy.deepcopy(self.candidates.get(candidate_id))

    def candidates_of(self, round_id: str) -> list[dict]:
        return sorted((copy.deepcopy(row) for row in self.candidates.values() if row["roundId"] == round_id), key=lambda row: row["position"])

    def put_file(self, path: str, data: bytes) -> None:
        self.files[path] = data

    def read_file(self, path: str) -> bytes | None:
        return self.files.get(path)

    def delete_file(self, path: str) -> None:
        self.files.pop(path, None)

    def spent_on(self, day: str) -> float:
        return round(sum(row.get("costUsd") or 0 for row in self.candidates.values() if str(row.get("createdAt", "")).startswith(day)), 6)
