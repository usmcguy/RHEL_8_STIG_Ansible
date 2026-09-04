# Copyright (c) 2026 Dave King
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import absolute_import, division, print_function

DOCUMENTATION = r"""
name: stig_xml_custom
type: aggregate
short_description: Generate STIG results xml
extends_documentation_fragment:
  - ansible.builtin.default_callback
description:
  - When play completes, a xccdf-results.xml is created in a sub-folder under /tmp
"""

__metaclass__ = type

import os
import re
import tempfile
import xml.dom.minidom
import xml.etree.ElementTree as ET
from time import gmtime, strftime

from ansible.plugins.callback import CallbackBase

class CallbackModule(CallbackBase):
    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = "xml"
    CALLBACK_NAME = "usmcguy.stigs.stig_xml_custom"

    CALLBACK_NEEDS_WHITELIST = True

    def _get_role_files_dir(self, task):
        if task is None or not hasattr(task, 'get_path'):
            self._display.warning("no task / no get_path")
            return None

        task_path = task.get_path()
        self._display.warning("raw get_path: {!r}".format(task_path))
        if task_path is None:
            return None

        task_path = task_path.split(':')[0]
        task_path = os.path.abspath(task_path)
        parts = task_path.split(os.sep)
        self._display.warning("parts: {}".format(parts))
        if 'roles' not in parts:
            self._display.warning("'roles' not in path")
            return None

        roles_index = parts.index('roles')
        if roles_index + 1 >= len(parts):
            return None

        role_path = os.path.join(os.sep, *parts[: roles_index + 2])
        files_dir = os.path.join(role_path, 'files')
        self._display.warning("checking files_dir: {} exists={}".format(
            files_dir, os.path.isdir(files_dir)))
        return files_dir if os.path.isdir(files_dir) else None

    def _get_STIG_path(self, task=None):
        if task is not None:
            files_dir = self._get_role_files_dir(task)
            if files_dir:
                candidates = [
                    os.path.join(files_dir, fname)
                    for fname in os.listdir(files_dir)
                    if fname.lower().endswith('.xml') and 'xccdf' in fname.lower()
                ]
                if candidates:
                    return sorted(candidates)[0]

        cwd = os.path.abspath('.')
        for dirpath, dirs, files in os.walk(cwd):
            if os.path.basename(dirpath) == 'files':
                for fname in files:
                    if fname.lower().endswith('.xml') and 'xccdf' in fname.lower():
                        return os.path.join(dirpath, fname)

        return None

    def __init__(self):
        super(CallbackModule, self).__init__()
        # Per-host state. XCCDF's <TestResult> represents one test event
        # against one target, so each managed host gets its own rule dict
        # and its own <TestResult> tree; multi-host runs get one output
        # file per host rather than mixing hosts into a single document.
        self.rules = {}  # hostname -> {rule_key: bool}
        self.trees = {}  # hostname -> ET.Element (TestResult)
        self.stig_path = os.environ.get('STIG_PATH')
        self.XML_path = os.environ.get('XML_PATH')
        if self.XML_path is None:
            self.XML_path = os.path.join(tempfile.mkdtemp(), 'xccdf-results.xml')
        self._display.display("Using XML_PATH: {}".format(self.XML_path))

    def _ensure_stig_path(self, task=None):
        if self.stig_path is None:
            self.stig_path = self._get_STIG_path(task)
            if self.stig_path:
                self._display.display("Using STIG_PATH: {}".format(self.stig_path))
        return self.stig_path

    def _get_tree(self, hostname):
        if hostname in self.trees:
            return self.trees[hostname]
        if not self.stig_path:
            return None
        STIG_name = os.path.basename(self.stig_path)
        ET.register_namespace('', 'http://checklists.nist.gov/xccdf/1.2')
        tr = ET.Element('{http://checklists.nist.gov/xccdf/1.2}TestResult')
        tr.set(
            'id',
            'xccdf_mil.disa.stig_testresult_scap_mil.disa_comp_{}'.format(STIG_name),
        )
        endtime = strftime('%Y-%m-%dT%H:%M:%S', gmtime())
        tr.set('end-time', endtime)
        bm = ET.SubElement(tr, '{http://checklists.nist.gov/xccdf/1.2}benchmark')
        bm.set('href', 'xccdf_mil.disa.stig_testresult_scap_mil.disa_comp_{}'.format(STIG_name))
        tg = ET.SubElement(tr, '{http://checklists.nist.gov/xccdf/1.2}target')
        tg.text = hostname
        self.trees[hostname] = tr
        return tr

    def _host_xml_path(self, hostname):
        base, ext = os.path.splitext(self.XML_path)
        safe_host = re.sub(r'[^A-Za-z0-9._-]', '_', hostname)
        return '{}-{}{}'.format(base, safe_host, ext or '.xml')

    def _get_rev(self, nid, task=None):
        stig_path = self.stig_path or self._get_STIG_path(task)
        if not stig_path:
            raise RuntimeError('Unable to resolve STIG_PATH for task {}'.format(task))

        with open(stig_path, 'r') as f:
            r = r'SV-{}r(?P<rev>\d+)_rule'.format(nid)
            m = re.search(r, f.read())
        if m:
            rev = m.group('rev')
        else:
            rev = '0'
        return rev

    def _rule_key(self, task, hostname):
        name = task.get_name()
        m = re.search(r'stigrule_(?P<id>\d+)', name, re.IGNORECASE)
        if not m:
            return None
        self._ensure_stig_path(task)
        if self._get_tree(hostname) is None:
            return None
        nid = m.group('id')
        rev = self._get_rev(nid, task)
        return '{}r{}'.format(nid, rev)

    def v2_runner_on_ok(self, result):
        hostname = result._host.get_name()
        key = self._rule_key(result._task, hostname)
        if key is None:
            return
        # Sticky-fail: once any task for this rule reports a real change (a
        # violation was found and fixed), the rule stays "fail" no matter
        # what later helper/read-only tasks under the same id report. This
        # avoids an early fact-gathering task (stat/slurp/set_fact, always
        # changed:false) permanently locking the rule to a false "pass"
        # before the real check/remediation task ever runs.
        host_rules = self.rules.setdefault(hostname, {})
        host_rules[key] = host_rules.get(key, False) or result.is_changed()

    def _mark_rule_failed(self, task, hostname):
        key = self._rule_key(task, hostname)
        if key is None:
            return
        self.rules.setdefault(hostname, {})[key] = True

    def v2_runner_on_failed(self, result, ignore_errors=False):
        # A task with ignore_errors: true is expected/handled elsewhere in
        # the rule's own logic (e.g. a probe used to decide what to fix
        # next) and shouldn't itself mark the rule non-compliant.
        if ignore_errors:
            return
        self._mark_rule_failed(result._task, result._host.get_name())

    def v2_runner_on_unreachable(self, result):
        self._mark_rule_failed(result._task, result._host.get_name())

    def v2_playbook_on_stats(self, stats):
        hostnames = list(self.rules.keys())
        single_host = len(hostnames) == 1
        for hostname in hostnames:
            tr = self.trees.get(hostname)
            if tr is None:
                continue
            host_rules = self.rules[hostname]
            for rule, changed in host_rules.items():
                state = 'fail' if changed else 'pass'
                rr = ET.SubElement(
                    tr, '{http://checklists.nist.gov/xccdf/1.2}rule-result'
                )
                rr.set('idref', 'xccdf_mil.disa.stig_rule_SV-{}_rule'.format(rule))
                rs = ET.SubElement(rr, '{http://checklists.nist.gov/xccdf/1.2}result')
                rs.text = state
            passing = len(host_rules) - sum(host_rules.values())
            sc = ET.SubElement(tr, '{http://checklists.nist.gov/xccdf/1.2}score')
            sc.set('maximum', str(len(host_rules)))
            sc.set('system', 'urn:xccdf:scoring:flat-unweighted')
            sc.text = str(passing)

            out_path = self.XML_path if single_host else self._host_xml_path(hostname)
            with open(out_path, 'wb') as f:
                out = ET.tostring(tr)
                pretty = xml.dom.minidom.parseString(out).toprettyxml(encoding='utf-8')
                f.write(pretty)
            if not single_host:
                self._display.display("Writing: {}".format(out_path))
