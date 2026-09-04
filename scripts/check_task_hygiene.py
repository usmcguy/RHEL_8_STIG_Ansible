#!/usr/bin/env python3
"""Static checks for recurring bug patterns in this collection's roles.

Not a substitute for ansible-lint or a real test run — this targets the
specific mistake shapes that have actually caused live bugs in this repo
(see CLAUDE.md "Bug patterns that have recurred multiple times"):

  1. `notify:` pointing to a handler name that isn't defined anywhere in
     that role's handlers/main.yml (e.g. restart_aide, dconf_restart_button_lock).
  2. A variable used as `X.stdout` / `X.rc` / `X.changed` / `X.stat.*` /
     etc. that was never the target of a `register:` or `set_fact` anywhere
     in that role (e.g. dconf_db_check).
  3. Multiple tasks in rules.yml sharing the same literal `stigrule_<id>`
     name prefix where at least one of them is a read-only/fact-gathering
     "helper" task (stat/slurp/set_fact/find/debug, or a hardcoded
     changed_when: false). This is a reporting-hygiene smell for the
     stig_xml_custom callback's stigrule_<id> aggregation convention
     (see CLAUDE.md) — flagged as informational, not an error, since the
     callback's current OR-accumulate logic is no longer broken by it.

Exit code is 1 if any ERROR-severity finding exists, 0 otherwise (INFO
findings never fail the run). Run with no arguments from anywhere in the
repo; it locates roles/ relative to this script.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
ROLES_DIR = REPO_ROOT / "roles"

HELPER_MODULES = {
    "stat",
    "slurp",
    "set_fact",
    "find",
    "debug",
}

# Variable-shaped names that are always available and never come from a
# register/set_fact in the role itself.
KNOWN_MAGIC_PREFIXES = (
    "ansible_",
    "hostvars",
    "item",
    "inventory_hostname",
    "playbook_dir",
    "role_path",
    "lookup",
    "omit",
    "group_names",
    "groups",
)

ATTR_USAGE_RE = re.compile(
    r"\b([A-Za-z_][A-Za-z0-9_]*)\."
    r"(stdout|stderr|rc|changed|failed|stdout_lines|stderr_lines|stat)\b"
)
STIGRULE_NAME_RE = re.compile(r"stigrule_(\d+)", re.IGNORECASE)


def module_name(task: dict) -> str | None:
    """Return the short module name for a task dict (FQCN-tolerant)."""
    for key in task:
        if key in (
            "name",
            "when",
            "notify",
            "register",
            "changed_when",
            "failed_when",
            "loop",
            "loop_control",
            "vars",
            "tags",
            "with_items",
            "become",
            "become_user",
            "no_log",
            "ignore_errors",
            "block",
            "rescue",
            "always",
            "delegate_to",
            "async",
            "poll",
        ):
            continue
        # Treat the first remaining key as the module invocation.
        return key.rsplit(".", 1)[-1]
    return None


def flatten_tasks(tasks) -> list[dict]:
    """Recursively walk block/rescue/always and yield leaf task dicts."""
    out = []
    for task in tasks or []:
        if not isinstance(task, dict):
            continue
        out.append(task)
        for key in ("block", "rescue", "always"):
            if key in task and isinstance(task[key], list):
                out.extend(flatten_tasks(task[key]))
    return out


def load_tasks_file(path: Path) -> list[dict]:
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        print(f"WARN: could not parse {path}: {exc}", file=sys.stderr)
        return []
    if not isinstance(data, list):
        return []
    return flatten_tasks(data)


def collect_handler_names(role_dir: Path) -> set[str]:
    handlers_file = role_dir / "handlers" / "main.yml"
    if not handlers_file.exists():
        return set()
    names = set()
    for task in load_tasks_file(handlers_file):
        name = task.get("name")
        if isinstance(name, str):
            names.add(name)
        listen = task.get("listen")
        if isinstance(listen, str):
            names.add(listen)
        elif isinstance(listen, list):
            names.update(n for n in listen if isinstance(n, str))
    return names


def collect_defined_vars(all_tasks: list[dict]) -> set[str]:
    defined = set()
    for task in all_tasks:
        register = task.get("register")
        if isinstance(register, str):
            defined.add(register)
        mod = module_name(task)
        if mod == "set_fact":
            for key in task:
                if key.rsplit(".", 1)[-1] == "set_fact" and isinstance(task[key], dict):
                    defined.update(task[key].keys())
        vars_block = task.get("vars")
        if isinstance(vars_block, dict):
            defined.update(vars_block.keys())
    return defined


def is_known_magic(name: str) -> bool:
    return any(name == p or name.startswith(p) for p in KNOWN_MAGIC_PREFIXES)


def check_dangling_notify(role_name: str, all_tasks: list[dict], handler_names: set[str]) -> list[str]:
    errors = []
    for task in all_tasks:
        notify = task.get("notify")
        if notify is None:
            continue
        targets = [notify] if isinstance(notify, str) else list(notify)
        for target in targets:
            if not isinstance(target, str):
                continue
            if target not in handler_names:
                task_name = task.get("name", "<unnamed task>")
                errors.append(
                    f"ERROR [{role_name}] task '{task_name}' notifies undefined "
                    f"handler '{target}'"
                )
    return errors


def iter_string_values(node):
    """Yield every string leaf value in a nested dict/list (never dict keys),
    so we scan Jinja usage in task *content* without matching module names
    like 'ansible.builtin.stat' in the YAML keys themselves."""
    if isinstance(node, dict):
        for value in node.values():
            yield from iter_string_values(value)
    elif isinstance(node, list):
        for item in node:
            yield from iter_string_values(item)
    elif isinstance(node, str):
        yield node


def check_undefined_register_usage(role_name: str, all_tasks: list[dict], defined: set[str]) -> list[str]:
    errors = []
    seen = set()
    for task in all_tasks:
        blob = "\n".join(iter_string_values(task))
        for match in ATTR_USAGE_RE.finditer(blob):
            base = match.group(1)
            if base in defined or is_known_magic(base):
                continue
            key = (base, task.get("name", "<unnamed task>"))
            if key in seen:
                continue
            seen.add(key)
            errors.append(
                f"ERROR [{role_name}] task '{task.get('name', '<unnamed task>')}' "
                f"references '{base}.{match.group(2)}' but '{base}' is never "
                f"registered or set_fact'd in this role"
            )
    return errors


def check_stigrule_prefix_hygiene(role_name: str, rules_file: Path) -> list[str]:
    notes = []
    tasks = load_tasks_file(rules_file)
    groups: dict[str, list[dict]] = {}
    for task in tasks:
        name = task.get("name")
        if not isinstance(name, str):
            continue
        m = STIGRULE_NAME_RE.search(name)
        if not m:
            continue
        groups.setdefault(m.group(1), []).append(task)

    for rule_id, group in groups.items():
        if len(group) < 2:
            continue
        for task in group:
            mod = module_name(task)
            changed_when = task.get("changed_when")
            helper_shaped = mod in HELPER_MODULES or changed_when is False
            if helper_shaped:
                notes.append(
                    f"INFO  [{role_name}] rule {rule_id}: helper-shaped task "
                    f"'{task.get('name')}' (module={mod}) shares the "
                    f"stigrule_{rule_id} prefix with {len(group) - 1} other "
                    "task(s) - consider naming it without the prefix "
                    "(see CLAUDE.md)"
                )
    return notes


def main() -> int:
    if not ROLES_DIR.is_dir():
        print(f"ERROR: roles directory not found at {ROLES_DIR}", file=sys.stderr)
        return 1

    all_findings: list[str] = []
    error_count = 0

    for role_dir in sorted(ROLES_DIR.iterdir()):
        tasks_dir = role_dir / "tasks"
        if not tasks_dir.is_dir():
            continue
        role_name = role_dir.name

        all_tasks: list[dict] = []
        for tasks_file in sorted(tasks_dir.glob("*.yml")):
            all_tasks.extend(load_tasks_file(tasks_file))

        handler_names = collect_handler_names(role_dir)
        defined_vars = collect_defined_vars(all_tasks)

        findings = []
        findings.extend(check_dangling_notify(role_name, all_tasks, handler_names))
        findings.extend(check_undefined_register_usage(role_name, all_tasks, defined_vars))

        rules_file = tasks_dir / "rules.yml"
        if rules_file.exists():
            findings.extend(check_stigrule_prefix_hygiene(role_name, rules_file))

        all_findings.extend(findings)
        error_count += sum(1 for f in findings if f.startswith("ERROR"))

    if not all_findings:
        print("check_task_hygiene: no findings.")
        return 0

    for finding in all_findings:
        print(finding)

    print(
        f"\ncheck_task_hygiene: {error_count} error(s), "
        f"{len(all_findings) - error_count} info note(s)."
    )
    return 1 if error_count else 0


if __name__ == "__main__":
    sys.exit(main())
