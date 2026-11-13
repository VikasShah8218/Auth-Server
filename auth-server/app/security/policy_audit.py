"""Print the effective access rule for every route.

    python -m app.security.policy_audit
    python -m app.security.policy_audit --json

Exits with 1 if the policy doesn't match the routes, or if any route is on the default rule, so it also
works as a CI gate.
"""

import json
import sys


def main() -> int:
    from app.security.enforcement import apply_security_policy
    from main import create_app

    try:
        rows = apply_security_policy(create_app())
    except RuntimeError as exc:
        print(f"POLICY ERROR: {exc}", file=sys.stderr)
        return 1

    rows.sort(key=lambda row: (row[1], row[0]))
    on_default = [row for row in rows if row[3] == "default"]

    if "--json" in sys.argv:
        keys = ("method", "path", "rule", "source")
        print(json.dumps([dict(zip(keys, row)) for row in rows], indent=2))
    else:
        widths = [max(len(row[i]) for row in rows) for i in range(3)]
        for method, path, rule, source in rows:
            print(f"{method:<{widths[0]}}  {path:<{widths[1]}}  {rule:<{widths[2]}}  {source}")
        print(f"\n{len(rows)} routes, {len(on_default)} on the default rule")

    return 1 if on_default else 0


if __name__ == "__main__":
    sys.exit(main())
