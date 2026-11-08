"""roles.py — which schema and edge names the display methods mean by "a person", "a post", "a tenure".

The reader's sections (offices, holders, family, owners, deals...) are written against these roles, not
against the names of one archive's schema. The defaults are hydra's own; an archive that calls its edges
something else says so in wiki.yaml:

    roles:
      person: Human
      tenure: Appointment          # an edge from a person (source) to a post (target), dated
      kin: Kinship                 # an edge between relatives, parent -> child
      ownership: Holding           # owner (source) -> thing owned (target), with a share
      representation: Agency       # who acted for whom
      post: Office
      event: Transaction

`configure` sets them for the wiki being read; call sites read `roles.TENURE` at the time they run.
"""
from __future__ import annotations

DEFAULTS = {"PERSON": "Person", "POST": "Position", "EVENT": "Event", "TENURE": "Occupancy", "KIN": "Family",
            "OWNERSHIP": "Ownership", "REPRESENTATION": "Representation"}

PERSON = POST = EVENT = TENURE = KIN = OWNERSHIP = REPRESENTATION = ""


def configure(given: dict | None = None) -> None:
    """Set the roles from wiki.yaml `roles:` (keys in any case) over the defaults."""
    given = {str(k).upper(): str(v) for k, v in (given or {}).items() if v}
    unknown = set(given) - set(DEFAULTS)
    if unknown:
        raise ValueError(f"wiki.yaml roles: unknown {sorted(unknown)}; known: {sorted(k.lower() for k in DEFAULTS)}")
    globals().update({**DEFAULTS, **given})


configure()
