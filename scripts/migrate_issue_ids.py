#!/usr/bin/env python3
"""Migration script: Convert issue IDs from string to int.

This script:
1. Renames issue directories from "042-slug/" to "042/"
2. Updates issue.yaml files to have `id: 42` (int) instead of `id: '042'` (string)

Run from repo root:
    python scripts/migrate_issue_ids.py

Or with dry-run to preview changes:
    python scripts/migrate_issue_ids.py --dry-run
"""

import argparse
import re
import shutil
from pathlib import Path

import yaml


def migrate_issues(issues_dir: Path, dry_run: bool = False) -> None:
    """Migrate all issues to int IDs and simplified directory names."""
    if not issues_dir.exists():
        print(f"Issues directory not found: {issues_dir}")
        return

    # Collect directories to rename (do renames after iteration)
    renames: list[tuple[Path, Path]] = []

    for issue_dir in sorted(issues_dir.iterdir()):
        if not issue_dir.is_dir():
            continue
        if issue_dir.name == "archive":
            continue

        # Parse current directory name (e.g., "042-fix-login")
        match = re.match(r"^(\d+)-(.*)$", issue_dir.name)
        if not match:
            # Already just a number? Check if it's a valid ID
            if re.match(r"^\d+$", issue_dir.name):
                print(f"  [skip] {issue_dir.name}/ - already migrated")
                # Still update YAML if needed
                update_yaml(issue_dir / "issue.yaml", dry_run)
                continue
            print(f"  [warn] {issue_dir.name}/ - unexpected format, skipping")
            continue

        issue_id_str = match.group(1)
        issue_id_int = int(issue_id_str.lstrip("0") or "0")
        new_dir_name = f"{issue_id_int:03d}"

        # Update YAML first (while directory still exists)
        yaml_path = issue_dir / "issue.yaml"
        update_yaml(yaml_path, dry_run)

        # Plan directory rename
        if issue_dir.name != new_dir_name:
            new_dir = issues_dir / new_dir_name
            renames.append((issue_dir, new_dir))
            print(f"  [rename] {issue_dir.name}/ -> {new_dir_name}/")
        else:
            print(f"  [ok] {issue_dir.name}/ - name already correct")

    # Perform renames
    for old_dir, new_dir in renames:
        if dry_run:
            print(f"  [dry-run] Would rename {old_dir} -> {new_dir}")
        else:
            if new_dir.exists():
                print(f"  [error] Target exists: {new_dir}")
                continue
            old_dir.rename(new_dir)


def update_yaml(yaml_path: Path, dry_run: bool = False) -> None:
    """Update issue.yaml to use int ID."""
    if not yaml_path.exists():
        return

    with open(yaml_path) as f:
        content = f.read()

    # Parse YAML
    data = yaml.safe_load(content)
    if not data:
        return

    # Check if ID needs updating
    current_id = data.get("id")
    if current_id is None:
        return

    # Convert to int
    if isinstance(current_id, str):
        new_id = int(current_id.lstrip("0") or "0")
        data["id"] = new_id
        print(f"    [yaml] id: '{current_id}' -> {new_id}")

        if not dry_run:
            with open(yaml_path, "w") as f:
                yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)
    elif isinstance(current_id, int):
        print(f"    [yaml] id: {current_id} - already int")


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate issue IDs to integers")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without making them",
    )
    parser.add_argument(
        "--issues-dir",
        type=Path,
        default=Path("_agenttree/issues"),
        help="Path to issues directory",
    )
    args = parser.parse_args()

    print(f"Migrating issues in: {args.issues_dir}")
    if args.dry_run:
        print("DRY RUN - no changes will be made\n")
    else:
        print()

    migrate_issues(args.issues_dir, args.dry_run)

    print("\nDone!")
    if args.dry_run:
        print("Run without --dry-run to apply changes.")


if __name__ == "__main__":
    main()
