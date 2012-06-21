# vi: ts=4 expandtab
#
#    Copyright (C) 2011 Canonical Ltd.
#    Copyright (C) 2012 Hewlett-Packard Development Company, L.P.
#
#    Author: Scott Moser <scott.moser@canonical.com>
#    Author: Juerg Haefliger <juerg.haefliger@hp.com>
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License version 3, as
#    published by the Free Software Foundation.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.

import sys

from cloudinit import templater
from cloudinit import util
from cloudinit import version

from cloudinit.settings import PER_ALWAYS

frequency = PER_ALWAYS

FINAL_MESSAGE_DEF = ("Cloud-init v. {{version}} finished at {{timestamp}}."
                     " Up {{uptime}} seconds.")


def handle(_name, cfg, cloud, log, args):

    msg_in = None
    if len(args) != 0:
        msg_in = args[0]
    else:
        msg_in = util.get_cfg_option_str(cfg, "final_message")

    if not msg_in:
        template_fn = cloud.get_template_filename('final_message')
        if template_fn:
            msg_in = util.load_file(template_fn)

    if not msg_in:
        msg_in = FINAL_MESSAGE_DEF

    uptime = util.uptime()
    ts = util.time_rfc2822()
    cver = version.version_string()
    try:
        subs = {
            'uptime': uptime,
            'timestamp': ts,
            'version': cver,
        }
        # Use stdout, stderr or the logger??
        content = templater.render_string(msg_in, subs)
        sys.stderr.write("%s\n" % (content))
    except Exception:
        util.logexc(log, "Failed to render final message template")

    boot_fin_fn = cloud.paths.boot_finished
    try:
        contents = "%s - %s - v. %s\n" % (uptime, ts, cver)
        util.write_file(boot_fin_fn, contents)
    except:
        util.logexc(log, "Failed to write boot finished file %s", boot_fin_fn)
