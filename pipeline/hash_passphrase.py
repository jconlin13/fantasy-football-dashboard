"""Print the SHA-256 of a passphrase, for config/draft.ini.

Run this yourself and paste the hash. The passphrase is typed into a hidden
prompt, is never written to disk, and never appears in your shell history.

    python3 pipeline/hash_passphrase.py

Worth knowing what this does and does not do. The site is static, so the check
happens in the visitor's browser: the hash is public and someone determined
could guess the word offline. It is a speed bump that keeps the Launch Draft
button out of the way of people who are not in the league -- ESPN's own login is
what actually stops a stranger from entering the draft room.
"""

import getpass
import hashlib
import sys


def main():
    first = getpass.getpass("Passphrase: ")
    if not first.strip():
        print("empty -- nothing to hash", file=sys.stderr)
        return 1
    if first != getpass.getpass("Again: "):
        print("they do not match", file=sys.stderr)
        return 1

    print("\npassphrase_sha256 = %s" % hashlib.sha256(first.encode("utf-8")).hexdigest())
    print("\nPaste that line into the [draft] section of config/draft.ini.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
