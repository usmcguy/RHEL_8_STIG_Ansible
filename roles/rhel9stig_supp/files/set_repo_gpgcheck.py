#!/usr/bin/env python3
"""Ensure gpgcheck is set to a fixed value under every section of every
/etc/yum.repos.d/*.repo file. Edits only the gpgcheck line (inserting one
right after the section header if missing); every other line is copied
through unchanged, to mirror community.general.ini_file's surgical
single-option edit behavior instead of doing a full-file rewrite (which
would risk reformatting comments/ordering in a file subscription-manager
also manages)."""
import glob
import re
import sys

SECTION_RE = re.compile(r'^\[(?P<name>[^\]]+)\]\s*$')
GPGCHECK_RE = re.compile(r'^[ \t]*gpgcheck[ \t]*=[ \t]*(?P<value>.*?)[ \t]*$')


def process_file(path, target):
    with open(path, 'r') as fh:
        lines = fh.readlines()

    out = []
    section_header = None
    section_body = []
    section_has_gpgcheck = False
    file_changed = False

    def flush_section():
        nonlocal file_changed, section_header, section_body, section_has_gpgcheck
        if section_header is not None:
            if not section_has_gpgcheck:
                section_body.insert(0, 'gpgcheck = {}\n'.format(target))
                file_changed = True
            out.append(section_header)
            out.extend(section_body)
        section_header = None
        section_body = []
        section_has_gpgcheck = False

    for line in lines:
        if SECTION_RE.match(line):
            flush_section()
            section_header = line
            continue

        if section_header is None:
            # Lines before any section header (rare) — pass through untouched.
            out.append(line)
            continue

        gpgcheck_match = GPGCHECK_RE.match(line)
        if gpgcheck_match:
            section_has_gpgcheck = True
            if gpgcheck_match.group('value') != str(target):
                section_body.append('gpgcheck = {}\n'.format(target))
                file_changed = True
            else:
                section_body.append(line)
            continue

        section_body.append(line)

    flush_section()

    if file_changed:
        with open(path, 'w') as fh:
            fh.writelines(out)

    return file_changed


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else '1'
    changed_files = [
        path for path in sorted(glob.glob('/etc/yum.repos.d/*.repo'))
        if process_file(path, target)
    ]
    print('CHANGED:' + ','.join(changed_files) if changed_files else 'OK')


if __name__ == '__main__':
    main()
