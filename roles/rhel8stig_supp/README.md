# usmcguy.stigs.rhel8stig_supp
===============

A supplemental Ansible role for applying selected RHEL 8 STIG rules and configurations.

Requirements
------------

- Ansible 2.16 or later.
- Target hosts must be Red Hat Enterprise Linux 8.
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
|rhel8STIG_allow_system_reboot|true|false|reboot the system when required|
|rhel8STIG_stigrule_authselect_profile| sssd|false|authselect profile to enforce|
|rhel8STIG_stigrule_authselect_features |with-faillock<br>with-files-access-provider<br>with-files-domain<br>with-mkhomedir<br>with-smartcard<br>with-smartcard-lock-on-removal<br>with-sudo<br>without-nullok|false|authselect feature list used when enforcing authselect|
|rhel8STIG_stigrule_logon_DenyAttempts|3|false|maximum failed login attempts before lockout|
|rhel8STIG_stigrule_login_FailInterval|900|false|login fail interval in seconds|
|rhel8STIG_stigrule_230234_grub_password|ChangeMe_!@12#$34|true|GRUB password used by supplemental STIG rules|
|rhel8STIG_stigrule_230301_exclude_mounts|<none>|false|mount exclusions for file system checks|
|rhel8STIG_stigrule_230316_nameservers|<none>|true|DNS servers|
|rhel8STIG_stigrule_230316_cloud|false|false|If true, allows use of 1 DNS Server that is highly-available|
|rhel8STIG_stigrule_230316_dns_interface|<none>|false|Interface to assign DNS Servers|
|rhel8STIG_stigrule_230317_dot_bashrc||false|`.bashrc` content for shell environment remediation|

For a complete list of variables and their defaults, see `roles/rhel8stig_supp/defaults/main.yml`.

Dependencies
------------

This role has no required Galaxy role dependencies. It is a self-contained supplemental STIG role for RHEL 8.

It does require the following collections to be available in your Ansible environment:

- `ansible.posix`
- `community.general`
- `community.crypto`

Example Playbook
----------------

    - hosts: rhel8_servers
      become: true
      roles:
        - role: usmcguy.stigs.rhel8stig_supp
          vars:
            rhel8STIG_allow_system_reboot: false
            rhel8STIG_stigrule_authselect_profile: "sssd"
            rhel8STIG_stigrule_230234_grub_password: "ChangeMe_!@12#$34"

License
-------

Apache-2.0

Author Information
------------------

- Dave K [usmcguy](https://github.com/usmcguy) <br>
  [![usmcguy](https://avatars.githubusercontent.com/u/761929?v=4&s=48)](https://github.com/usmcguy)
- Glenn Mora Rangel [glennmora](https://github.com/glennmora) <br>
  [![glennmora](https://avatars.githubusercontent.com/u/108555140?v=4&s=48)](https://github.com/glennmora)
