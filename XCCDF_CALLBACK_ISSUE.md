# Known issue: `stig_xml_custom` callback pass/fail aggregation is unreliable

Status: **not yet fixed** — documented here for follow-up.

## Where

`plugins/callback/stig_xml_custom.py`, primarily `v2_runner_on_ok` (~line 135-148) and `v2_playbook_on_stats` (~line 150-167).

## The problem

The callback decides pass/fail per STIG rule like this:

```python
def v2_runner_on_ok(self, result):
    name = result._task.get_name()
    m = re.search(r'stigrule_(?P<id>\d+)', name, re.IGNORECASE)
    if not m:
        return
    nid = m.group('id')
    rev = ...  # SV revision looked up from the XCCDF source
    key = '{}r{}'.format(nid, rev)
    if self.rules.get(key, 'Unknown') is not False:
        self.rules[key] = result.is_changed()
```

Issues, in order of severity:

1. **Sticky false-pass lock-in.** It matches *any* task whose name contains `stigrule_<digits>` — not just the "real" compliance-determining task, but every helper task (`stat`, `slurp`, `set_fact`, `command`/`shell` with `changed_when: false`) that happens to share the same numeric prefix. The **first** such task to report `ok` with `changed: false` permanently locks that rule to "pass" (`self.rules[key] = False`), because the `is not False` guard prevents any later task from ever overwriting a `False` (pass) value — even if a later task for the same rule ID genuinely fails or makes a real remediation change.

   Concretely: many rules are written as *[gather facts] → [decide] → [remediate]*, and all three steps share the same `stigrule_<id>__...` name prefix. The fact-gathering steps (stat/slurp/set_fact) are essentially always `changed: false`, so they win the lock before the real check ever runs.

2. **Failures are invisible.** There is no `v2_runner_on_failed` or `v2_runner_on_skipped` handler in this file at all — only `v2_runner_on_ok` touches `self.rules`. So even without issue #1, a task that genuinely *fails* never gets recorded as a failure in the XCCDF report.

3. **No per-host keying.** `self.rules` is a single dict on the callback instance; the key is just `{numeric_id}r{revision}` with no host component. On a multi-host run, all hosts' results for a given rule ID collapse into one shared pass/fail value.

4. `v2_playbook_on_stats` does no reconciliation — it just serializes `self.rules` as-is into the XCCDF XML (`'fail' if changed else 'pass'`).

## Why it matters

The report can show a rule as compliant ("pass") when the real remediation task never ran, was skipped, or failed outright — the failure/skip is simply never seen by the callback. This has likely been silently happening for a while; it isn't something introduced by recent changes.

## Scope (as of 2026-08-23)

An investigation agent scanned both `roles/rhel9stig_supp/tasks/rules.yml` and `roles/rhel8stig_supp/tasks/rules.yml` (both use this same callback, per each role's `ansible.cfg`):

| Role | Distinct `stigrule_<id>` groups | Single-task (safe) | Affected (helper locks in before real check) |
|---|---|---|---|
| rhel9stig_supp | 121 | 74 | **7** |
| rhel8stig_supp | 150 | 94 | **22** |

**Affected rule IDs — rhel9stig_supp**: 257822, 257950, 258131, 258134, 258135, 258231, 272496

**Affected rule IDs — rhel8stig_supp**: 230229, 230243, 230259, 230263, 230264, 230271, 230274, 230484, 230554, 244521, 244522, 244531, 244532, 244546, 250316, 250317, 251708, 251709, 251710, 251711, 254520, 272484

Representative examples (file:line):
- `roles/rhel9stig_supp/tasks/rules.yml:3964` — `stigrule_258134__read_aide.conf` (slurp) locks "pass" before the real AIDE check/init/rename tasks around lines 4031-4070.
- `roles/rhel9stig_supp/tasks/rules.yml:742` — `stigrule_257822__stat_conf_files` (stat) locks "pass" before the real `ini_file` remediation at line 814.
- `roles/rhel8stig_supp/tasks/rules.yml:4813` — a `changed_when: false` check task locks "pass" before the actual `fail`-based gate at line 4841, so that gate's fail can never surface.
- `roles/rhel8stig_supp/tasks/rules.yml:4935` — R-250316 has three helper tasks before the real fix at line 4987.
- `roles/rhel8stig_supp/tasks/rules.yml:2973` — `stigrule_230484__check_server_line` (`changed_when: false`) locks "pass" before the actual NTP config fixes at lines 2983-3008.

Worst case: **R-258131** (CA cert bundle rebuild, both roles) — roughly 19 of 28 tasks are fact-gathering helpers, any one of which can lock the rule long before the real `copy` that writes the updated bundle.

Not affected: single-task rules (no collision possible — 74/121 rhel9, 94/150 rhel8), and rules where the only prefixed task *is* the real check.

Severity: concentrated, not universal (~6-15% of multi-task rules), but it lands squarely on the hardest-to-manually-verify rules — multi-step fact-gathering rules like AIDE integrity, cert/CA bundle management, SELinux context/user mapping, and file-permission sweeps — exactly where a false "pass" is least likely to be noticed.

## Already-applied partial mitigation

This session, two new helper tasks were deliberately named *without* the `stigrule_<id>` prefix specifically to dodge this bug:
- `roles/rhel9stig_supp/tasks/partition_option.yml` — the two new `Stat ... for separate-partition check` tasks.
- `roles/rhel9stig_supp/tasks/rules.yml` — `Stat newly (re)initialized AIDE database` (R-258134).

This is a valid pattern (and worth continuing opportunistically) but is not a fix for the ~29 already-affected rules, and is easy to forget on future rules.

## Proposed fix (recommended)

**Rewrite the callback to track the *last*-registered task result per rule ID within a play, instead of "first `ok`+`changed:false` wins forever."** This matches the actual intent (the final task in a rule's sequence is the one that determines compliance) and requires no mass rename across ~29 rules — it fixes all current and future rules automatically, including ones not yet identified.

Combine with:
- Add `v2_runner_on_failed` and `v2_runner_on_unreachable` handlers so a genuine failure is recorded as "fail" (currently invisible).
- Consider adding a host component to the `self.rules` key to fix the multi-host collapsing issue (separate from the main bug, but same file/area).

**Alternative / defense-in-depth (not a full fix on its own)**: keep renaming helper tasks to drop the `stigrule_<id>` prefix, rule by rule, as they're touched for other reasons (as already done twice). Useful for the worst offenders (e.g., R-258131) even after the callback fix, since it also makes task output clearer for humans. Doing this alone, across all ~29 rules, is a large, error-prone, manually-verified effort — not recommended as the primary fix.

**Anchoring the regex** (`^stigrule_` instead of unanchored `search`) closes a separate, minor, unrelated risk (accidental substring matches in unrelated task names) but does **not** fix the actual multi-task collision bug, since the affected task names already start with `stigrule_`.

## Next steps when picking this up

1. Decide whether to fix host-keying at the same time (small addition, same file) or track separately.
2. Rewrite `v2_runner_on_ok` to overwrite unconditionally (last-write-wins) rather than the `is not False` sticky guard.
3. Add `v2_runner_on_failed` / `v2_runner_on_unreachable`, deciding what "fail" should mean when a task legitimately uses `ignore_errors: true` (several existing tasks in `rules.yml` do this deliberately, e.g. the RPM GPG fingerprint checks) — failed-but-ignored tasks probably should *not* auto-fail the rule the way a real fatal failure should.
4. Re-run both roles' full playbooks against real hosts and confirm the XCCDF output changes in the expected direction (rules that were falsely "pass" should now correctly reflect their real task's outcome) without introducing new false negatives.
5. No molecule/unit tests exist for this callback — verification will be manual/live-host based, same as the rest of this collection.
