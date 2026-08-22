# usmcguy.stigs.rhel9stig_supp
===============

A supplemental Ansible role for applying selected RHEL 9 STIG rules and configurations.

Requirements
------------

- Ansible 2.16 or later.
- Target hosts must be Red Hat Enterprise Linux 9.
- Privileged escalation must be available for tasks that modify system security settings.
- Requires the following Ansible collections beyond the built-in core modules:
  - `ansible.posix`
  - `community.general`
  - `community.crypto`

Role Variables
--------------

The role exposes configuration through variables defined in `defaults/main.yml`. Common variables to review or override include:

|Variable Name|Default Value|Required|Description|
|:---:|:---:|:---:|:---:|
|rhel9stig_allow_system_reboot|true|false|reboot the system when required|
|rhel9stig_stigrule_authselect_profile| sssd|false|authselect profile to enforce|
|rhel9stig_stigrule_authselect_features |with-faillock<br>with-files-access-provider<br>with-files-domain<br>with-mkhomedir<br>with-smartcard<br>with-smartcard-lock-on-removal<br>with-sudo<br>without-nullok|false|authselect feature list used when enforcing authselect|
|rhel9stig_stigrule_logon_DenyAttempts|3|false|maximum failed login attempts before lockout|
|rhel9stig_stigrule_login_FailInterval|900|false|login fail interval in seconds|

For a complete list of variables and their defaults, see `roles/rhel9stig_supp/defaults/main.yml`.

Dependencies
------------

This role has no required Galaxy role dependencies. It is a self-contained supplemental STIG role for RHEL 9.

It does require the following collections to be available in your Ansible environment:

- `ansible.posix`
- `community.general`
- `community.crypto`

Example Playbook
----------------

    - hosts: rhel9_servers
      become: true
      roles:
        - role: usmcguy.stigs.rhel9stig_supp
          vars:
            rhel9stig_allow_system_reboot: false
            rhel9stig_stigrule_authselect_profile: "sssd"
            rhel9stig_stigrule_230234_grub_password: "ChangeMe_!@12#$34"

License
-------

Apache-2.0

Author Information
------------------

- Dave K [usmcguy](https://github.com/usmcguy) <br>
  [![usmcguy](https://avatars.githubusercontent.com/u/761929?v=4&s=48)](https://github.com/usmcguy)
