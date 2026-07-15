"""
matcher.py — the correctness core of ``venvy audit``.

This module decides, for a single installed ``(name, version)``, whether it is affected
by an advisory. A bug here is a *false all-clear*, which is the single worst failure a
security tool can have. Therefore:

  * We evaluate OSV affected-ranges with the documented event-sweep algorithm, using
    ``packaging.version`` for a correct total ordering (pre-releases, epochs, post-
    releases all handled by the library, never by string comparison).
  * We FAIL CLOSED: any version or range boundary we cannot parse yields ``UNKNOWN``,
    never ``NOT_AFFECTED``. Unknown is surfaced to the user; it is never treated as safe.

The matcher does no I/O, no network, and no name lookup — callers select candidate
advisories by canonical name (see :func:`canonicalize_name`) and hand them here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Sequence, Tuple

from packaging.version import InvalidVersion, Version


class MatchStatus(str, Enum):
    """Outcome of evaluating one installed version against one advisory.

    UNKNOWN is a first-class result, not an error: it means "this could not be
    evaluated with confidence" and must be reported, never silently dropped.
    """

    AFFECTED = "affected"
    NOT_AFFECTED = "not_affected"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Name canonicalization (PEP 503).
# A mismatch here = a missed advisory = a false all-clear, so both the installed
# name and the advisory name MUST be canonicalized the same way before comparison.
# ---------------------------------------------------------------------------
_CANONICALIZE_RE = re.compile(r"[-_.]+")


def canonicalize_name(name: str) -> str:
    """Return the PEP 503 normalized project name (lowercase, runs of -_. -> -)."""
    return _CANONICALIZE_RE.sub("-", name).strip().lower()


# ---------------------------------------------------------------------------
# Negative-infinity sentinel for ``introduced: "0"``.
#
# OSV uses the literal string "0" to mean "from the beginning of time". We must NOT
# parse it as Version("0"): a pre-release such as 0.0.0a1 sorts *below* Version("0"),
# so ``target >= Version("0")`` would be False and we'd wrongly clear an affected
# pre-release. A true -inf sentinel avoids that entire class of bug.
# ---------------------------------------------------------------------------
class _NegativeInfinity:
    __slots__ = ()

    def __lt__(self, other: object) -> bool:  # noqa: D105
        return not isinstance(other, _NegativeInfinity)

    def __le__(self, other: object) -> bool:  # noqa: D105
        return True

    def __gt__(self, other: object) -> bool:  # noqa: D105
        return False

    def __ge__(self, other: object) -> bool:  # noqa: D105
        return isinstance(other, _NegativeInfinity)

    def __eq__(self, other: object) -> bool:  # noqa: D105
        return isinstance(other, _NegativeInfinity)

    def __hash__(self) -> int:  # noqa: D105
        return hash("-inf")


NEG_INF = _NegativeInfinity()


# ---------------------------------------------------------------------------
# Advisory data model (the minimal shape the matcher needs).
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RangeEvent:
    """A single OSV range event: exactly one of introduced/fixed/last_affected."""

    kind: str  # "introduced" | "fixed" | "last_affected"
    value: str


@dataclass(frozen=True)
class AffectedRange:
    """One OSV ``ranges`` entry, an ordered set of events forming affected intervals."""

    events: Tuple[RangeEvent, ...]


@dataclass(frozen=True)
class AffectedPackage:
    """The affected-version definition for one package within one advisory.

    ``ranges`` and ``versions`` are OR-combined, exactly per the OSV spec: a version is
    affected if it falls in any range OR is listed explicitly.
    """

    name: str  # canonical (PEP 503) name
    ranges: Tuple[AffectedRange, ...] = field(default_factory=tuple)
    versions: Tuple[str, ...] = field(default_factory=tuple)
    # True when the advisory names this package but gives NO version scope at all
    # (neither ranges nor versions). Per fail-closed policy we cannot prove any
    # installed version safe, so such an advisory forces UNKNOWN, never NOT_AFFECTED.
    unscoped: bool = False


_VALID_EVENT_KINDS = ("introduced", "fixed", "last_affected")


def parse_osv_affected(entry: dict) -> AffectedPackage:
    """Build an :class:`AffectedPackage` from a raw OSV ``affected`` object.

    Tolerant by design: unrecognized event kinds are dropped (they cannot make a
    version *more* affected than the recognized events, and the range evaluation below
    already fails closed on anything it can't interpret). Never raises on well-formed
    OSV; malformed structure surfaces later as UNKNOWN, not as a crash.
    """
    name = canonicalize_name((entry.get("package") or {}).get("name", ""))

    ranges: List[AffectedRange] = []
    for rng in entry.get("ranges", []) or []:
        # Only version-based ranges are matchable against an installed PyPI version.
        # OSV advisories routinely ALSO carry a GIT range whose introduced/fixed values
        # are commit hashes, not versions. Evaluating those would fail to parse and
        # poison the result to UNKNOWN even when a valid ECOSYSTEM range exists. SEMVER
        # ranges belong to other ecosystems. So we keep ECOSYSTEM (and untyped, treated
        # as ECOSYSTEM) and skip the rest.
        rtype = rng.get("type")
        if rtype not in (None, "ECOSYSTEM"):
            continue
        events: List[RangeEvent] = []
        for ev in rng.get("events", []) or []:
            for kind in _VALID_EVENT_KINDS:
                if kind in ev:
                    events.append(RangeEvent(kind=kind, value=str(ev[kind])))
                    break
        if events:
            ranges.append(AffectedRange(events=tuple(events)))

    versions = tuple(str(v) for v in (entry.get("versions") or []))
    # OSV: an affected entry with neither ranges nor versions cannot be version-scoped.
    # We refuse to guess "all affected" (false positives) or "none affected" (false
    # all-clear); such an entry is flagged unscoped -> UNKNOWN at match time.
    unscoped = not ranges and not versions
    return AffectedPackage(
        name=name, ranges=tuple(ranges), versions=versions, unscoped=unscoped
    )


# ---------------------------------------------------------------------------
# Core evaluation.
# ---------------------------------------------------------------------------
def _parse_bound(value: str):
    """Parse a range-boundary string to a comparable, or None if it cannot be parsed.

    ``"0"`` maps to the negative-infinity sentinel (start-of-time). Any other
    unparseable boundary returns None, which forces the range to UNKNOWN (fail closed).
    """
    if value == "0":
        return NEG_INF
    try:
        return Version(value)
    except InvalidVersion:
        return None


def _range_affects(events: Sequence[RangeEvent], target: Version) -> Optional[bool]:
    """Evaluate one range against ``target``.

    Returns True/False, or None when the range cannot be evaluated (unparseable
    boundary) — the caller escalates None to UNKNOWN.

    Algorithm: sort events ascending by version, then sweep. ``introduced`` turns the
    affected flag on once we've passed it; ``fixed`` (exclusive) and ``last_affected``
    (inclusive) turn it back off. The final flag reflects the interval containing
    ``target``.
    """
    parsed: List[Tuple[object, str]] = []
    for ev in events:
        bound = _parse_bound(ev.value)
        if bound is None:
            return None  # cannot evaluate this range -> UNKNOWN
        parsed.append((bound, ev.kind))

    # Stable sort by version; NEG_INF sorts first via its comparison methods.
    parsed.sort(key=lambda pair: pair[0])

    affected = False
    for bound, kind in parsed:
        if kind == "introduced":
            if target >= bound:
                affected = True
        elif kind == "fixed":
            if target >= bound:  # fixed is exclusive: >= fixed is NOT affected
                affected = False
        elif kind == "last_affected":
            if target > bound:  # last_affected is inclusive: only > it clears
                affected = False
    return affected


def version_status(version: str, pkg: AffectedPackage) -> MatchStatus:
    """Return whether ``version`` is affected by ``pkg``.

    Fail-closed contract:
      * Unparseable installed version                -> UNKNOWN
      * A range with an unparseable boundary, and no
        other signal proving AFFECTED                -> UNKNOWN
      * Otherwise NOT_AFFECTED only when every range
        and explicit-version check is conclusive.
    """
    try:
        target = Version(version)
    except InvalidVersion:
        return MatchStatus.UNKNOWN

    # Explicit affected-versions list (OR-combined with ranges).
    for raw in pkg.versions:
        try:
            if Version(raw) == target:
                return MatchStatus.AFFECTED
        except InvalidVersion:
            # A single unparseable entry in the list can't match; skip it. It does not
            # taint the result because an explicit list is a positive signal only.
            continue

    # An unscoped advisory (package named, no version info) cannot clear this version.
    saw_unknown = pkg.unscoped
    for rng in pkg.ranges:
        result = _range_affects(rng.events, target)
        if result is True:
            return MatchStatus.AFFECTED
        if result is None:
            saw_unknown = True

    if saw_unknown:
        return MatchStatus.UNKNOWN
    return MatchStatus.NOT_AFFECTED


def fixed_versions(pkg: AffectedPackage) -> Tuple[str, ...]:
    """Return the parseable ``fixed`` versions across a package's ranges, in order.

    Best-effort, display-only guidance ("upgrade to X"). Never affects a match verdict.
    Deduplicated, original order preserved.
    """
    seen = set()
    out: List[str] = []
    for rng in pkg.ranges:
        for ev in rng.events:
            if ev.kind != "fixed" or ev.value in seen:
                continue
            try:
                Version(ev.value)
            except InvalidVersion:
                continue
            seen.add(ev.value)
            out.append(ev.value)
    return tuple(out)
