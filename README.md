# Ansible STIG Playbook

This repository contains an Ansible STIG playbook intended to supplement DISA STIG content and help automate system hardening tasks.

> [!WARNING]
> This playbook can make significant system changes and may have unintended consequences if applied without review or testing.
>
> Always back up the target system before running this playbook.
>
> Always review any code downloaded from the internet before executing it in your environment.

> [!CAUTION]
> Use this content at your own risk. No responsibility is accepted for any damage, outage, data loss, or other harm caused by execution of this playbook.

## Purpose

- Provide an Ansible-based STIG remediation playbook to supplement official DISA guidance.
- Help users adapt and automate portions of their hardening workflow in their own environments.
- Serve as a starting point for review, testing, and customization rather than a drop-in guarantee of compliance.

## Before You Run It

- Review the playbook and every change it makes before execution.
- Test in a non-production environment first.
- Create a verified backup or snapshot of the target system before use.
- Confirm the settings match your platform, mission, and local security requirements.

## Disclaimer

- This project is provided for educational and operational use as-is, without warranty.
- The playbook is intended to supplement DISA content, not replace official DISA STIG documentation or validation procedures.
- The operator is solely responsible for validating all changes before deployment.
- By using this repository, users accept full responsibility for reviewing, testing, and safely executing the content.

## Contributors

- Dave King [usmcguy](https://github.com/usmcguy)
- Glenn Mora Rangel [glennmora ](https://github.com/glennmora)
