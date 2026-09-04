# Testing scaffold status (Layer 1 + Layer 2)

Status as of 2026-08-23. Picks up from the "would molecule/unit testing be a
good idea" discussion — see git history around this date for the full
reasoning. Three-tier plan: Layer 1 (static checks) done and working; Layer 2
(Molecule + container) scaffolded and proven functional up to a real,
expected container/VM boundary; Layer 3 (existing live-VM run) unchanged.

## Layer 1 — `scripts/check_task_hygiene.py` (done)

A standalone Python script (stdlib + PyYAML only, no other deps) that parses
both roles' task/handler files with real YAML and checks for the specific
recurring bug shapes documented in `CLAUDE.md`:

1. `notify:` targeting a handler name not defined in that role's
   `handlers/main.yml`.
2. A variable used as `X.stdout`/`X.rc`/`X.changed`/`X.stat.*`/etc. that was
   never the target of a `register:` or `set_fact` anywhere in that role.
3. Multiple tasks in `rules.yml` sharing a literal `stigrule_<id>` name
   prefix where at least one is a read-only/fact-gathering "helper" task
   (stat/slurp/set_fact/find/debug, or hardcoded `changed_when: false`) —
   flagged as INFO/hygiene, not an error, since the callback's current
   OR-accumulate logic (see `CLAUDE.md`) is no longer broken by this, it's
   just noise reduction.

Run: `python3 scripts/check_task_hygiene.py` from repo root. Exit code 1 if
any ERROR-severity finding exists, 0 otherwise (INFO findings never fail).

**Current state**: 0 errors, 102 info notes (expected — matches the known
R-258131/R-230229-etc. "worst offenders" from the earlier callback
investigation). Two real bugs were found and fixed via this script this
session: `rhel8stig_supp`'s `stigrule_230332__enable_authselect_with_features`
notified a nonexistent `auth_select_apply` handler (should have been
`apply_authselect_changes` — it was accidentally the *variable name* the
real handler registers internally, not the handler's own name).

**Known limitation**: check #2 (undefined register usage) is a heuristic,
not a real Jinja/AST analysis — it can't detect *ordering* bugs (a var
referenced before it's registered, when both exist in the file), only
completely-undefined ones. That was sufficient to catch every real bug found
this session, but isn't exhaustive.

**Not yet done for Layer 1**: `ansible-lint` / `yamllint` aren't configured
in this repo at all (checked — no `.ansible-lint`, no `.yamllint*`). Adding
them would be free additional coverage on top of the custom script, but
wasn't done yet.

## Layer 2 — Molecule (scaffolded, proven functional, hit expected boundary)

Location: `roles/rhel9stig_supp/molecule/default/` (per-role scenario,
chosen since `rhel8stig_supp` and `rhel9stig_supp` are independently
testable and shouldn't share one scenario).

Files: `molecule.yml`, `prepare.yml`, `converge.yml`, `verify.yml`.

- **Driver**: `podman` (installed this session via
  `pip install --user "molecule-plugins[podman]"` — wasn't present before).
- **Platform**: `registry.access.redhat.com/ubi9/ubi-init:latest`, `systemd:
  always`, `command: /usr/sbin/init`, cgroup volume mount, `SYS_ADMIN`
  capability — the standard recipe for a systemd-capable podman container.
- **`ANSIBLE_COLLECTIONS_PATH`** is set explicitly in `provisioner.env` to
  match `ansible.cfg`'s `collections_path` exactly (hardcoded
  `/home/dave/gitCode:...` — same non-portability tradeoff `ansible.cfg`
  already makes). **Keep these two in sync if either ever changes.**
- `rhel9stig_allow_system_reboot: false` and
  `rhel9stig_stigrule_258230_Manage: false` (FIPS) are set via
  `provisioner.inventory.host_vars` — no real reboot/bootloader capability
  in a container, so these are disabled up front rather than left to fail.

### Three real bugs found and fixed while getting this far

1. **`tmpfs` schema/runtime mismatch**: the installed `molecule-plugins`
   version's own JSON schema for `platforms[].tmpfs` wants an array of
   strings, but the underlying `containers.podman.podman_container` module
   it calls wants a dict. Neither format satisfies both layers
   simultaneously. Fix: removed the explicit `tmpfs:` key entirely — podman's
   own `systemd: always` handling manages the needed tmpfs mounts for an
   init container automatically.
2. **`become: true` in `converge.yml`/`verify.yml` failed** — the podman
   connection is already root by default in this minimal image, and `sudo`
   isn't installed on it at all. Fixed by setting `become: false` in both
   playbooks (with a comment explaining why).
3. **`authselect` package missing** — the minimal UBI init image doesn't
   ship it, so `/usr/share/authselect/default/sssd` didn't exist yet and an
   early role task (`Deploy updated authselect profile templates`) failed.
   Fixed by adding an explicit install step to `prepare.yml`.
   **Gotcha hit while debugging this**: `molecule converge` reuses an
   existing container silently ("create: Skipped, instances already
   created") on repeat runs, and *may not actually re-execute `prepare.yml`
   meaningfully against it* even though it reports "prepare: Executed:
   Successful" — confirmed the fix by `podman exec`-ing into the running
   container directly rather than trusting molecule's step log. **If a fix
   to `prepare.yml` doesn't seem to take effect, run `molecule destroy`
   first to force a truly fresh container**, or `podman exec` in to verify
   directly.

### Where it currently stops (expected, not a bug)

After the above three fixes, `molecule converge` got through dozens of real
role tasks successfully (system-account/group discovery and filtering,
authselect profile deployment, etc.), then failed at
`stigrule_257787__grub2-setpassword_BIOS` — a GRUB bootloader password task.
This is exactly the category of task flagged in the original Layer 2
proposal as fundamentally untestable in a container (no real bootloader
exists). **This is proof the scaffold works, not a scaffold defect.**

The container from this last run (`rhel9stig-molecule`) was left running
(not destroyed) in case it's useful to poke at directly before the next
session. Destroy it with `cd roles/rhel9stig_supp && molecule destroy` when
done with it, or just let the next `molecule converge` reuse it (see the
gotcha above about that not always doing what you'd expect).

## What's left (not started)

1. **The `container_unsafe` tagging project** — the actual next step to make
   `converge.yml` cover the whole role. Go through `rules.yml` and tag every
   task in the categories that can't mean anything in a container:
   - GRUB/bootloader/kernel-cmdline changes (`grub2-setpassword`,
     `grubby --update-kernel`, `/etc/default/grub` edits, etc.)
   - Disk partition/mount checks (`partition_option.yml`-driven rules)
   - FIPS mode + reboot (already disabled via host_vars, but the tasks
     themselves aren't tagged — currently only skipped because their `when:`
     happens to be false, not because of an explicit tag)
   - Real auditd/kernel-audit-dependent behavior (containers generally can't
     run auditd meaningfully — kernel audit subsystem is host-level)
   - SELinux enforcement-dependent checks (enforcement mode inside a
     container depends on and often differs from the host)

   Then wire `--skip-tags container_unsafe` into the molecule scenario
   (likely `provisioner.options: skip-tags: container_unsafe` in
   `molecule.yml`, or an explicit `ansible.builtin.include_role: ... apply:
   {tags: [...]}` structure in `converge.yml` — needs a bit of
   experimentation to see which molecule actually respects cleanly).

   This is a large, mechanical, easy-to-get-subtly-wrong task across ~150
   rules — worth doing carefully and incrementally rather than in one pass,
   and it's the same tagging effort that would *also* need to happen for a
   `rhel8stig_supp` scenario (see below), so consider whether a shared
   tagging convention/list should be designed once and applied to both.

2. **A `rhel8stig_supp` molecule scenario** doesn't exist yet. Once the
   rhel9 scenario's container_unsafe tagging approach is proven out, copy
   the pattern — the same `tmpfs`/`become`/`authselect`-class gotchas will
   very likely resurface there too (worth checking rhel8's task list for
   similar minimal-image package gaps before assuming otherwise).

3. **`verify.yml` is deliberately minimal** (3 representative checks:
   dnf.conf gpgcheck, aide package, usbguard package). Expand it
   opportunistically whenever a rule gets touched for a bug fix anyway,
   rather than trying to write assertions for all ~150 rules up front.

4. **`ansible-lint`/`yamllint`** aren't configured (Layer 1 gap, noted
   above) — cheap to add, wasn't done this session.

5. Confirm what `molecule idempotence` actually reports once a full
   container-safe converge is achievable — this was the main motivating
   payoff for Layer 2 (catching non-idempotent tasks like the AIDE bug
   found earlier this session), but hasn't been exercised yet since
   converge itself hasn't completed end-to-end.

## Commands to resume

```bash
cd roles/rhel9stig_supp
molecule converge         # run through create+prepare+converge
molecule destroy          # tear down (do this if a prepare.yml fix isn't taking effect)
molecule test             # full sequence: create, prepare, converge, idempotence, verify, destroy
podman exec -it rhel9stig-molecule bash   # poke around directly while it's up
```

`scripts/check_task_hygiene.py` has no external state — just re-run it after
any `rules.yml`/`handlers/main.yml` edit in either role.
