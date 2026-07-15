"""
Golden corpus for venvy.audit.matcher.

This is the single most important test file in the project: it is the difference
between a trustworthy scanner and one that gets yanked. Every real-world false
positive/negative we ever find becomes a permanent case here. The suite only grows.

Cases are grouped by the failure class they defend against.
"""
import pytest

from venvy.audit.matcher import (
    AffectedPackage,
    AffectedRange,
    MatchStatus,
    RangeEvent,
    canonicalize_name,
    parse_osv_affected,
    version_status,
)


# ---------------------------------------------------------------------------
# Helpers to build advisory shapes concisely.
# ---------------------------------------------------------------------------
def _range(*events):
    """events: sequence of (kind, value) tuples."""
    return AffectedRange(events=tuple(RangeEvent(k, v) for k, v in events))


def _pkg(name="demo", ranges=(), versions=()):
    return AffectedPackage(name=name, ranges=tuple(ranges), versions=tuple(versions))


# ---------------------------------------------------------------------------
# Name canonicalization (PEP 503).
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Flask", "flask"),
        ("Flask_SQLAlchemy", "flask-sqlalchemy"),
        ("Flask-SQLAlchemy", "flask-sqlalchemy"),
        ("Flask.SQLAlchemy", "flask-sqlalchemy"),
        ("zope.interface", "zope-interface"),
        ("A__B--C..D", "a-b-c-d"),
        ("  Requests  ", "requests"),
        ("oslo.config", "oslo-config"),
    ],
)
def test_canonicalize_name(raw, expected):
    assert canonicalize_name(raw) == expected


# ---------------------------------------------------------------------------
# Basic [introduced, fixed) intervals.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "version,expected",
    [
        ("0.1", MatchStatus.AFFECTED),
        ("1.5", MatchStatus.AFFECTED),
        ("1.9.9", MatchStatus.AFFECTED),
        ("2.0", MatchStatus.NOT_AFFECTED),      # fixed is exclusive
        ("2.0.1", MatchStatus.NOT_AFFECTED),
    ],
)
def test_introduced_zero_fixed(version, expected):
    pkg = _pkg(ranges=[_range(("introduced", "0"), ("fixed", "2.0"))])
    assert version_status(version, pkg) == expected


@pytest.mark.parametrize(
    "version,expected",
    [
        ("0.9", MatchStatus.NOT_AFFECTED),      # below introduced
        ("1.0", MatchStatus.AFFECTED),          # introduced is inclusive
        ("1.9.9", MatchStatus.AFFECTED),
        ("2.0", MatchStatus.NOT_AFFECTED),
    ],
)
def test_introduced_nonzero_fixed(version, expected):
    pkg = _pkg(ranges=[_range(("introduced", "1.0"), ("fixed", "2.0"))])
    assert version_status(version, pkg) == expected


# ---------------------------------------------------------------------------
# last_affected is INCLUSIVE (distinct from fixed).
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "version,expected",
    [
        ("1.0", MatchStatus.AFFECTED),
        ("1.5", MatchStatus.AFFECTED),          # inclusive upper bound
        ("1.5.1", MatchStatus.NOT_AFFECTED),
        ("2.0", MatchStatus.NOT_AFFECTED),
    ],
)
def test_last_affected_inclusive(version, expected):
    pkg = _pkg(ranges=[_range(("introduced", "1.0"), ("last_affected", "1.5"))])
    assert version_status(version, pkg) == expected


# ---------------------------------------------------------------------------
# Open-ended range (introduced, no upper bound) — affected forever after.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "version,expected",
    [
        ("0.9", MatchStatus.NOT_AFFECTED),
        ("1.0", MatchStatus.AFFECTED),
        ("99.0", MatchStatus.AFFECTED),
    ],
)
def test_open_ended_range(version, expected):
    pkg = _pkg(ranges=[_range(("introduced", "1.0"))])
    assert version_status(version, pkg) == expected


# ---------------------------------------------------------------------------
# Multiple intervals within one range (introduced/fixed pairs).
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "version,expected",
    [
        ("0.5", MatchStatus.AFFECTED),          # in [0, 1.0)
        ("1.0", MatchStatus.NOT_AFFECTED),      # patched gap
        ("1.5", MatchStatus.NOT_AFFECTED),      # in the gap [1.0, 2.0)
        ("2.5", MatchStatus.AFFECTED),          # in [2.0, 3.0)
        ("3.0", MatchStatus.NOT_AFFECTED),
    ],
)
def test_multi_interval_range(version, expected):
    pkg = _pkg(
        ranges=[
            _range(
                ("introduced", "0"),
                ("fixed", "1.0"),
                ("introduced", "2.0"),
                ("fixed", "3.0"),
            )
        ]
    )
    assert version_status(version, pkg) == expected


def test_events_out_of_order_are_sorted():
    # Same as multi-interval but events supplied in scrambled order.
    pkg = _pkg(
        ranges=[
            _range(
                ("fixed", "3.0"),
                ("introduced", "0"),
                ("fixed", "1.0"),
                ("introduced", "2.0"),
            )
        ]
    )
    assert version_status("2.5", pkg) == MatchStatus.AFFECTED
    assert version_status("1.5", pkg) == MatchStatus.NOT_AFFECTED


# ---------------------------------------------------------------------------
# Pre-release handling — the classic silent-miss.
# ---------------------------------------------------------------------------
def test_prerelease_below_fixed_is_affected():
    # 2.0.0rc1 < 2.0.0, so it is still in [0, 2.0.0).
    pkg = _pkg(ranges=[_range(("introduced", "0"), ("fixed", "2.0.0"))])
    assert version_status("2.0.0rc1", pkg) == MatchStatus.AFFECTED
    assert version_status("2.0.0", pkg) == MatchStatus.NOT_AFFECTED


def test_prerelease_with_introduced_zero_sentinel():
    # 0.0.0a1 sorts BELOW Version("0"); with a naive Version("0") bound it would be
    # wrongly cleared. The NEG_INF sentinel keeps it affected.
    pkg = _pkg(ranges=[_range(("introduced", "0"), ("fixed", "1.0"))])
    assert version_status("0.0.0a1", pkg) == MatchStatus.AFFECTED


# ---------------------------------------------------------------------------
# Epochs — an epoch bumps a version above all lower-epoch versions.
# ---------------------------------------------------------------------------
def test_epoch_escapes_range():
    # 1!1.0 (epoch 1) is greater than any epoch-0 version, so it is >= fixed 2.0.
    pkg = _pkg(ranges=[_range(("introduced", "0"), ("fixed", "2.0"))])
    assert version_status("1!1.0", pkg) == MatchStatus.NOT_AFFECTED


# ---------------------------------------------------------------------------
# Explicit versions list — OR-combined with ranges, normalization-aware.
# ---------------------------------------------------------------------------
def test_explicit_versions_exact():
    pkg = _pkg(versions=["1.2.3", "1.2.5"])
    assert version_status("1.2.3", pkg) == MatchStatus.AFFECTED
    assert version_status("1.2.4", pkg) == MatchStatus.NOT_AFFECTED


def test_explicit_versions_normalized_equivalence():
    # "1.0" and "1.0.0" are the same release under PEP 440.
    pkg = _pkg(versions=["1.0"])
    assert version_status("1.0.0", pkg) == MatchStatus.AFFECTED


def test_explicit_versions_or_with_range():
    pkg = _pkg(
        ranges=[_range(("introduced", "5.0"), ("fixed", "6.0"))],
        versions=["1.2.3"],
    )
    assert version_status("1.2.3", pkg) == MatchStatus.AFFECTED   # via explicit list
    assert version_status("5.5", pkg) == MatchStatus.AFFECTED     # via range
    assert version_status("2.0", pkg) == MatchStatus.NOT_AFFECTED


# ---------------------------------------------------------------------------
# FAIL-CLOSED behavior — the invariant that prevents false all-clears.
# ---------------------------------------------------------------------------
def test_unparseable_installed_version_is_unknown():
    pkg = _pkg(ranges=[_range(("introduced", "0"), ("fixed", "2.0"))])
    assert version_status("not-a-version", pkg) == MatchStatus.UNKNOWN


def test_unparseable_range_boundary_is_unknown_not_clear():
    # A garbage boundary must NOT be silently treated as "not affected".
    pkg = _pkg(ranges=[_range(("introduced", "0"), ("fixed", "garbage"))])
    assert version_status("1.0", pkg) == MatchStatus.UNKNOWN


def test_affected_range_wins_over_unknown_range():
    # If one range proves AFFECTED, an unrelated unknown range must not downgrade it.
    pkg = _pkg(
        ranges=[
            _range(("introduced", "0"), ("fixed", "2.0")),      # 1.0 -> affected
            _range(("introduced", "x"), ("fixed", "y")),        # unparseable
        ]
    )
    assert version_status("1.0", pkg) == MatchStatus.AFFECTED


def test_no_signal_is_not_affected():
    pkg = _pkg(ranges=[_range(("introduced", "10.0"), ("fixed", "11.0"))])
    assert version_status("1.0", pkg) == MatchStatus.NOT_AFFECTED


# ---------------------------------------------------------------------------
# OSV JSON parsing -> AffectedPackage, end-to-end on a realistic record.
# ---------------------------------------------------------------------------
def test_parse_osv_affected_realistic():
    entry = {
        "package": {"ecosystem": "PyPI", "name": "Django"},
        "ranges": [
            {
                "type": "ECOSYSTEM",
                "events": [
                    {"introduced": "0"},
                    {"fixed": "3.2.14"},
                    {"introduced": "4.0"},
                    {"fixed": "4.0.6"},
                ],
            }
        ],
        "versions": ["3.2.13", "4.0.5"],
    }
    pkg = parse_osv_affected(entry)
    assert pkg.name == "django"  # canonicalized
    assert version_status("3.2.0", pkg) == MatchStatus.AFFECTED
    assert version_status("3.2.14", pkg) == MatchStatus.NOT_AFFECTED
    assert version_status("4.0.5", pkg) == MatchStatus.AFFECTED
    assert version_status("4.0.6", pkg) == MatchStatus.NOT_AFFECTED
    assert version_status("5.0", pkg) == MatchStatus.NOT_AFFECTED


def test_git_range_is_ignored_ecosystem_range_decides():
    # Real-world shape (cryptography/pip/pyjwt): a GIT range with commit-hash bounds
    # sits alongside an ECOSYSTEM range. The commit hashes must NOT poison the result
    # to UNKNOWN; the ECOSYSTEM range is authoritative.
    entry = {
        "package": {"ecosystem": "PyPI", "name": "cryptography"},
        "ranges": [
            {
                "type": "GIT",
                "repo": "https://github.com/pyca/cryptography",
                "events": [
                    {"introduced": "0"},
                    {"fixed": "94a50a9731f35405f0357fa5f3b177d46a726ab3"},
                ],
            },
            {
                "type": "ECOSYSTEM",
                "events": [{"introduced": "1.8"}, {"fixed": "39.0.1"}],
            },
        ],
    }
    pkg = parse_osv_affected(entry)
    assert version_status("48.0.1", pkg) == MatchStatus.NOT_AFFECTED   # was UNKNOWN
    assert version_status("2.0", pkg) == MatchStatus.AFFECTED
    assert version_status("39.0.1", pkg) == MatchStatus.NOT_AFFECTED


def test_git_only_range_is_unscoped_unknown():
    # If the ONLY range is GIT (no ecosystem range, no versions), we genuinely cannot
    # version-scope it -> fail closed to UNKNOWN, never NOT_AFFECTED.
    entry = {
        "package": {"ecosystem": "PyPI", "name": "demo"},
        "ranges": [
            {"type": "GIT", "events": [{"introduced": "0"}, {"fixed": "abc123def"}]}
        ],
    }
    pkg = parse_osv_affected(entry)
    assert pkg.unscoped is True
    assert version_status("1.0", pkg) == MatchStatus.UNKNOWN


def test_semver_range_skipped_for_pypi():
    entry = {
        "package": {"ecosystem": "PyPI", "name": "demo"},
        "ranges": [
            {"type": "SEMVER", "events": [{"introduced": "0"}, {"fixed": "2.0.0"}]},
            {"type": "ECOSYSTEM", "events": [{"introduced": "0"}, {"fixed": "1.0"}]},
        ],
    }
    pkg = parse_osv_affected(entry)
    # Only the ECOSYSTEM range counts: affected below 1.0, not at 1.5.
    assert version_status("0.5", pkg) == MatchStatus.AFFECTED
    assert version_status("1.5", pkg) == MatchStatus.NOT_AFFECTED


def test_parse_osv_ignores_unknown_event_kinds():
    entry = {
        "package": {"ecosystem": "PyPI", "name": "demo"},
        "ranges": [
            {
                "type": "ECOSYSTEM",
                "events": [
                    {"introduced": "0"},
                    {"limit": "9.9.9"},     # unknown kind, must be ignored
                    {"fixed": "2.0"},
                ],
            }
        ],
    }
    pkg = parse_osv_affected(entry)
    assert version_status("1.0", pkg) == MatchStatus.AFFECTED
    assert version_status("2.0", pkg) == MatchStatus.NOT_AFFECTED


def test_parse_osv_unscoped_is_unknown_not_clear():
    # An advisory that names a package but gives NO version scope must never clear a
    # version (that would be a false all-clear). It fails closed to UNKNOWN.
    pkg = parse_osv_affected({"package": {"name": "demo"}})
    assert pkg.unscoped is True
    assert version_status("1.0", pkg) == MatchStatus.UNKNOWN


def test_unscoped_flag_does_not_suppress_a_real_range():
    # A concrete AFFECTED must win even when the unscoped flag is set; outside the
    # range, the unscoped flag forces UNKNOWN rather than a false NOT_AFFECTED.
    pkg = AffectedPackage(
        name="demo",
        ranges=(_range(("introduced", "0"), ("fixed", "2.0")),),
        unscoped=True,
    )
    assert version_status("1.0", pkg) == MatchStatus.AFFECTED
    assert version_status("3.0", pkg) == MatchStatus.UNKNOWN


# ---------------------------------------------------------------------------
# Determinism — same inputs, same answer, regardless of evaluation order.
# ---------------------------------------------------------------------------
def test_determinism_repeated_calls():
    pkg = _pkg(
        ranges=[
            _range(("introduced", "1.0"), ("fixed", "2.0")),
            _range(("introduced", "3.0"), ("last_affected", "3.5")),
        ]
    )
    for _ in range(5):
        assert version_status("3.5", pkg) == MatchStatus.AFFECTED
        assert version_status("2.5", pkg) == MatchStatus.NOT_AFFECTED
