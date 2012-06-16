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

from cloudinit import util
from cloudinit.settings import PER_ALWAYS

frequency = PER_ALWAYS


def handle(name, cfg, cloud, log, _args):
    if util.get_cfg_option_bool(cfg, "preserve_hostname", False):
        log.debug(("Configuration option 'preserve_hostname' is set,"
                    " not updating the hostname in %s"), name)
        return

    (hostname, _fqdn) = util.get_hostname_fqdn(cfg, cloud)
    try:
        prev_fn = os.path.join(cloud.get_cpath('data'), "previous-hostname")
        cloud.distro.update_hostname(hostname, prev_fn)
    except Exception:
        util.logexc(log, "Failed to set the hostname to %s", hostname)
        raise
