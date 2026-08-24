# CLAUDE.md

Working notes for this repo, gathered from hands-on debugging sessions. This is
not a code-structure overview (read the code for that) — it's the stuff that
isn't obvious from reading the code once, and has already caused real time loss.

## Collection resolution (`ansible.cfg`)

- `collections_path` **must** list the repo's parent dir *alongside* the normal
  defaults, not instead of them:
  `collections_path = /home/dave/gitCode:/home/dave/.ansible/collections:/usr/share/ansible/collections`
  Setting it to just the repo's parent dir breaks resolution of dependency
  collections like `community.general` (`ini_file`, `firewalld`, etc.) — the
  playbook will die immediately with `couldn't resolve module/action`.
- If you edit `plugins/callback/stig_xml_custom.py` (or anything else resolved
  via the `usmcguy.stigs` FQCN) and your changes don't seem to take effect,
  **check for a stale/duplicate collection install** shadowing this checkout —
  e.g. `find ~/.ansible/collections -iname "stig_xml_custom.py"`. One such
  stale, disconnected clone (a different git branch, months old) silently
  shadowed this repo's callback plugin for an entire session before it was
  caught. `ansible-playbook --syntax-check` does not catch this; only a real
  run (or explicitly diffing the resolved file) does.
- Plain `roles: - rhel9stig_supp` references in a playbook resolve via
  `roles_path`/relative `./roles/`, independent of collection FQCN resolution
  — so role-file edits (`tasks/`, `defaults/`, `handlers/`) are not affected by
  the above; only collection-level plugins (callback, filter, modules) are.

## Testing against a real host

- `ansible-playbook -i inventory.ini test_enforce.yml --ask-become-pass` is
  the real end-to-end test, run against `rhel9.edentree.home` for RHEL 9 STIGs
  and `rhel-8.edentree.home` for RHEL 8 STIGS (see `inventory.ini`). There is no 
  molecule/unit test harness in this repo — verification is always live-host.
- **`--ask-become-pass` isn't actually required** if your local `ssh-agent` has
  the right key loaded (check with `ssh-add -l`). The target host has
  `pam_ssh_agent_auth` configured so `sudo` authenticates against a forwarded
  agent key instead of a Unix password — that's what `inventory.ini`'s
  `ansible_ssh_extra_args="-o ForwardAgent=yes"` and
  `ansible_become_flags="... --preserve-env=SSH_AUTH_SOCK"` are for. `test.sh`
  relies on exactly this (it has no `--ask-become-pass` and isn't run with a
  password prompt). A plain `ssh dave@rhel9.edentree.home` without `-A` will
  make `sudo` demand a password and fail non-interactively (`sudo: a password
  is required`) — the agent forwarding is the part that's easy to forget when
  testing `sudo`/`become` manually outside of Ansible, e.g.:
  `ssh -A dave@rhel9.edentree.home "sudo --preserve-env=SSH_AUTH_SOCK <cmd>"`.
  Running `ansible-playbook` directly (no wrapper) picks this up automatically
  from `inventory.ini` as long as the invoking shell's own `ssh-agent` holds
  the key — no password needs to be typed or stored anywhere.
- Always run `--syntax-check` before a live run. It catches YAML/module
  resolution issues but **not**: undefined Jinja vars evaluated only under a
  specific `when:`, handler-name typos (`notify:` to a nonexistent handler
  only errors at actual notify-time), or `changed_when` logic bugs.
- Full runs are slow — expect 30-90+ minutes on a fresh host. Known slow
  points: `stigrule_257822_set_gpgcheck` (a 645-section loop on this host's
  `redhat.repo`, one `ini_file` call per section — a faster opt-in single-script
  replacement is staged commented-out right after it in `rules.yml`), AIDE
  `--init` (full filesystem scan, wrapped in `async: 1800/poll: 30`), and
  `dnf_update` on a fresh box. Run long jobs backgrounded with a `Monitor`
  watching for `fatal|FAILED|PLAY RECAP`, don't poll synchronously.
- The test host gets restored from a hypervisor snapshot between major test
  cycles (this is done manually, outside Ansible). **After every snapshot
  restore, the SSH host key must be re-trusted**:
  `ssh-keygen -R rhel9.edentree.home && ssh-keyscan -H rhel9.edentree.home >> ~/.ssh/known_hosts`
  — a restore reverts the host key and Ansible/SSH will refuse to connect
  otherwise.
- Enabling FIPS mode (R-258230) triggers both a real reboot *and* an SSH host
  key rotation (RHEL drops the Ed25519 host key under the FIPS crypto policy,
  falling back to RSA/ECDSA). The role has self-healing tasks around this
  specific transition (`rules.yml`, search `FIPS-mode reboot`) that
  temporarily relax `StrictHostKeyChecking` and auto-trust the new key, then
  restore strict checking — this only fires once per FIPS-not-yet-enabled →
  enabled transition, not on every run.

## The `stigrule_<id>` naming convention (critical, easy to violate silently)

The custom callback plugin `plugins/callback/stig_xml_custom.py` decides each
STIG rule's pass/fail by regex-matching `stigrule_(\d+)` **anywhere in a
task's name** — it does not care about anything after the id. This has a real
consequence for how tasks must be named:

- **Only the task(s) that actually determine compliance for a rule should be
  named `stigrule_<id>__...`.** Any helper/fact-gathering task (`stat`,
  `slurp`, `set_fact`, a `shell`/`command` with `changed_when: false` used
  just to gather data) that shares that same numeric id prefix will also feed
  into that rule's reported result — since the callback folds every
  same-prefixed task's outcome into one running rule state.
- Current logic (fixed this session — previously it was "first `changed:false`
  locks the rule to pass forever," a real bug): any task under a rule id that
  reports `changed:true`, or fails without `ignore_errors: true`, permanently
  marks that rule "fail." Only if nothing ever does is it "pass." A task with
  `ignore_errors: true` never marks a rule failed (matches this repo's
  existing pattern of "probe" tasks whose failure is expected/handled).
  `v2_runner_on_unreachable` is also handled.
  Each managed host gets its own `<TestResult>` output file (XCCDF requires
  one `<TestResult>` per target); single-host runs keep the exact `XML_PATH`
  filename, multi-host runs get `<XML_PATH-base>-<hostname>.xml` per host.
- **When adding a new helper task to an existing rule, name it plainly**
  (e.g. `"Stat X for Y check"`), *without* the `stigrule_<id>__` prefix, so it
  can't pollute that rule's compliance signal. Two examples already fixed
  this way: the two new `stat` tasks in `partition_option.yml`, and "Stat
  newly (re)initialized AIDE database" in `rules.yml` (R-258134).
- `roles/rhel8stig_supp` shares this exact callback and has the **same**
  latent bug pattern in more rules than rhel9 (22 affected vs. 7, per an
  investigation this session) — it has not been audited/fixed yet.

## Bug patterns that have recurred multiple times in this codebase

Watch for these specifically when reviewing or writing new rule tasks —
each of these has been found more than once, independently, in
`roles/rhel9stig_supp/tasks/rules.yml`:

- **Missing `register:`** on a task whose result is referenced by a later
  task's `when:` (e.g. `dconf_db_check`, `dconf_restart_button_lock`) — the
  reference silently resolves to an `Undefined`/error, or a nonexistent
  handler-name gets mistaken for a registered variable.
- **`notify:` pointing to a handler name that was never defined** in
  `handlers/main.yml` (`restart_aide` referenced a systemd service that
  doesn't exist for AIDE at all — AIDE is cron-driven, not a daemon;
  `dconf_restart_button_lock` was `notify:`'d but never defined as a handler).
  Cross-check with:
  `comm -23 <(grep -oP 'notify:\s*\K\S+' roles/*/tasks/rules.yml | sort -u) <(grep -oP '^- name: \K.*' roles/*/handlers/main.yml | sort -u)`
- **RHEL 8 → RHEL 9 copy-paste package/name drift**: package and variable
  names copied from the sibling `rhel8stig_supp` role without checking RHEL 9
  equivalents (`mailx` → `s-nail`, a missing `usbguard` package-install step,
  `_bin_paths` vs `_library_paths` variable-name typos between adjacent
  rules).
- **`ansible_facts.mounts` silently drops tmpfs-backed mounts.** Ansible's own
  fact-gathering (`module_utils/facts/hardware/linux.py`) skips any
  `/proc/mounts` entry whose device field doesn't start with `/` or `\` —
  this includes `/tmp` and `/dev/shm` when tmpfs-backed. Don't use
  `ansible_facts.mounts | selectattr(...)` to check "is this path a separate
  filesystem" — use a `stat`-based `st_dev` comparison between the path and
  its parent instead (see `partition_option.yml`).
- **`changed_when` string-matching a command's exact stdout wording is
  fragile** across tool versions (AIDE's real completion message didn't match
  the word order the original `changed_when` expected, silently breaking
  idempotency for R-258134). Prefer checking the actual filesystem
  side-effect (does the expected output file now exist?) over pattern-
  matching human-readable tool output.

## Misc

- This environment the user commits edits individually with descriptive messages
  as work happens — you generally don't need to worry about losing work
  mid-session, and the git history will be granular. Still, only create
  commits yourself when explicitly asked.
- SSH pipelining is enabled (`ssh_connection.pipelining = True`) — confirmed
  safe here (no `requiretty` in sudoers on the test host).
