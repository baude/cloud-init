# vi: ts=4 expandtab
#
#    Copyright (C) 2008-2010 Canonical Ltd.
#    Copyright (C) 2012 Hewlett-Packard Development Company, L.P.
#
#    Author: Chuck Short <chuck.short@canonical.com>
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
#

from cloudinit.settings import (PER_INSTANCE, FREQUENCIES)

from cloudinit import log as logging

LOG = logging.getLogger(__name__)

# TODO remove this from being a prefix??
TRANSFORM_PREFIX = ''  # "cc_"


def form_transform_name(name, mod=__name__):
    canon_name = name.replace("-", "_")
    if canon_name.lower().endswith(".py"):
        canon_name = canon_name[0:(len(canon_name) - 3)]
    canon_name = canon_name.strip()
    if not canon_name:
        return None
    if not canon_name.startswith(TRANSFORM_PREFIX):
        canon_name = '%s%s' % (TRANSFORM_PREFIX, canon_name)
    return ".".join([str(mod), str(canon_name)])


def fixup_transform(mod, def_freq=PER_INSTANCE):
    if not hasattr(mod, 'frequency'):
        setattr(mod, 'frequency', def_freq)
    else:
        freq = mod.frequency
        if freq and freq not in FREQUENCIES:
            LOG.warn("Transform %s has an unknown frequency %s", mod, freq)
    if not hasattr(mod, 'handle'):
        def empty_handle(_name, _cfg, _cloud, _log, _args):
            pass
        setattr(mod, 'handle', empty_handle)
    if not hasattr(mod, 'distros'):
        setattr(mod, 'distros', None)
    return mod
