"""Strip personal data out of ESPN payloads before anything reaches a public repo.

ESPN identifies managers by SWID -- a GUID tied to their ESPN account -- and
ships their real first and last names alongside it. Neither belongs in a public
repo, but we still need stable identity linkage so a manager's 2018 season and
their 2025 season are recognizably the same person.

So: every SWID is replaced by a deterministic short id derived from it, and the
name fields are lifted out into a gitignored local file. The only names that
ever reach git are the ones written by hand into config/owners.ini.

    {A1B2C3D4-...}  ->  mgr_7f3a91c04e2b

The hash is unsalted on purpose. SWIDs are 128-bit random values, so the digest
cannot be reversed and cannot be brute-forced by enumeration; adding a salt would
buy nothing and would silently corrupt every id if the salt ever differed between
a laptop and CI.
"""

import configparser
import hashlib
import json
import os
import re

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
OWNERS_INI = os.path.join(ROOT, "config", "owners.ini")
LOCAL_IDENTITIES = os.path.join(ROOT, "config", "identities.local.json")

# ESPN SWIDs, with or without the surrounding braces.
GUID_RE = re.compile(
    r"^\{?[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
    r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}\}?$"
)

# Dropped from archived payloads wherever they appear.
PII_FIELDS = ("firstName", "lastName", "displayName")


def manager_id(swid):
    """Stable pseudonymous id for one ESPN account."""
    normalized = "{" + str(swid).strip().strip("{}").upper() + "}"
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return "mgr_" + digest[:12]


def is_guid(value):
    return isinstance(value, str) and bool(GUID_RE.match(value.strip()))


def sanitize(node, harvest):
    """Recursively replace SWIDs with manager ids and strip name fields.

    Walks the whole payload rather than targeting known fields, because ESPN
    puts SWIDs in several places (teams[].owners, teams[].primaryOwner,
    members[].id, transactions[].memberId) and has added more over the years.
    A generic walk cannot be silently outrun by a schema change.

    `harvest` accumulates {manager_id: {first, last, display}} for the local,
    gitignored name map.
    """
    if isinstance(node, dict):
        # Capture the real identity before discarding it.
        raw_id = node.get("id")
        if is_guid(raw_id) and any(node.get(f) for f in PII_FIELDS):
            record = harvest.setdefault(manager_id(raw_id), {})
            for field in PII_FIELDS:
                if node.get(field):
                    record[field] = node[field]

        clean = {}
        for key, value in node.items():
            if key in PII_FIELDS:
                continue
            clean[key] = sanitize(value, harvest)
        return clean

    if isinstance(node, list):
        return [sanitize(item, harvest) for item in node]

    if is_guid(node):
        return manager_id(node)

    return node


def suggest_display_name(record):
    """'Brendan Lenhard' -> 'Brendan L.' -- recognizable without being a full name."""
    first = (record.get("firstName") or "").strip()
    last = (record.get("lastName") or "").strip()
    if first and last:
        return "%s %s." % (first, last[0].upper())
    if first:
        return first
    # Fall back to the ESPN handle only as a last resort; it is often a real name.
    return (record.get("displayName") or "").strip() or "Unknown Manager"


def load_local_identities():
    if not os.path.exists(LOCAL_IDENTITIES):
        return {}
    with open(LOCAL_IDENTITIES) as fh:
        return json.load(fh)


def save_local_identities(identities):
    """Real names, kept on disk only. Gitignored -- never committed."""
    merged = load_local_identities()
    for mid, record in identities.items():
        merged.setdefault(mid, {}).update(record)
    os.makedirs(os.path.dirname(LOCAL_IDENTITIES), exist_ok=True)
    with open(LOCAL_IDENTITIES, "w") as fh:
        json.dump(merged, fh, indent=2, sort_keys=True)
    return merged


def load_owners():
    """Read the committed display-name config.

    Returns {manager_id: {"display": str, "merge_into": str or None}}.
    """
    parser = configparser.ConfigParser()
    parser.optionxform = str
    if os.path.exists(OWNERS_INI):
        parser.read(OWNERS_INI)

    owners = {}
    for section in parser.sections():
        owners[section] = {
            "display": parser.get(section, "display", fallback=section),
            "merge_into": parser.get(section, "merge_into", fallback=None) or None,
        }
    return owners


def scaffold_owners(identities):
    """Add a stub entry for every manager not yet in owners.ini.

    Never overwrites an entry that already exists -- hand-edited display names
    and merge_into links survive every refresh.
    """
    existing = load_owners()
    new_ids = [mid for mid in sorted(identities) if mid not in existing]
    if not new_ids:
        return []

    os.makedirs(os.path.dirname(OWNERS_INI), exist_ok=True)
    is_new_file = not os.path.exists(OWNERS_INI)

    with open(OWNERS_INI, "a") as fh:
        if is_new_file:
            fh.write(
                "# Public display names for the dashboard.\n"
                "#\n"
                "# Only the strings in this file are shown on the site or committed to\n"
                "# git -- real names from ESPN stay in config/identities.local.json,\n"
                "# which is gitignored. Suggested names below are first name + last\n"
                "# initial; edit them freely.\n"
                "#\n"
                "# If one person used two ESPN accounts over the years, point the older\n"
                "# one at the newer with merge_into so their career stats combine:\n"
                "#\n"
                "#   [mgr_oldaccount]\n"
                "#   display = Brendan L.\n"
                "#   merge_into = mgr_newaccount\n"
            )
        for mid in new_ids:
            fh.write(
                "\n[%s]\ndisplay = %s\n"
                % (mid, suggest_display_name(identities.get(mid, {})))
            )
    return new_ids


def resolve(manager, owners):
    """Follow merge_into links to the canonical manager id for one account."""
    seen = set()
    current = manager
    while current in owners and owners[current].get("merge_into"):
        if current in seen:  # a cycle in hand-edited config
            break
        seen.add(current)
        current = owners[current]["merge_into"]
    return current


def display_name(manager, owners):
    canonical = resolve(manager, owners)
    entry = owners.get(canonical)
    return entry["display"] if entry else canonical
