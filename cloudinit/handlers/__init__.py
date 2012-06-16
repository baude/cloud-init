# vi: ts=4 expandtab
#
#    Copyright (C) 2012 Canonical Ltd.
#    Copyright (C) 2012 Hewlett-Packard Development Company, L.P.
#    Copyright (C) 2012 Yahoo! Inc.
#
#    Author: Scott Moser <scott.moser@canonical.com>
#    Author: Juerg Haefliger <juerg.haefliger@hp.com>
#    Author: Joshua Harlow <harlowja@yahoo-inc.com>
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

import abc
import os

from cloudinit.settings import (PER_ALWAYS, PER_INSTANCE, FREQUENCIES)

from cloudinit import importer
from cloudinit import log as logging
from cloudinit import url_helper
from cloudinit import util

LOG = logging.getLogger(__name__)

# Used as the content type when a message is not multipart
# and it doesn't contain its own content-type
NOT_MULTIPART_TYPE = "text/x-not-multipart"

# When none is assigned this gets used
OCTET_TYPE = 'application/octet-stream'

# Special content types that signal the start and end of processing
CONTENT_END = "__end__"
CONTENT_START = "__begin__"
CONTENT_SIGNALS = [CONTENT_START, CONTENT_END]

# Used when a part-handler type is encountered
# to allow for registration of new types.
PART_CONTENT_TYPES = ["text/part-handler"]
PART_HANDLER_FN_TMPL = 'part-handler-%03d'

# For parts without filenames
PART_FN_TPL = 'part-%03d'

# Different file beginnings to there content type
INCLUSION_TYPES_MAP = {
    '#include': 'text/x-include-url',
    '#include-once': 'text/x-include-once-url',
    '#!': 'text/x-shellscript',
    '#cloud-config': 'text/cloud-config',
    '#upstart-job': 'text/upstart-job',
    '#part-handler': 'text/part-handler',
    '#cloud-boothook': 'text/cloud-boothook',
    '#cloud-config-archive': 'text/cloud-config-archive',
}

# Sorted longest first
INCLUSION_SRCH = sorted(list(INCLUSION_TYPES_MAP.keys()),
                        key=(lambda e: 0 - len(e)))


class Handler(object):

    __metaclass__ = abc.ABCMeta

    def __init__(self, frequency, version=2):
        self.handler_version = version
        self.frequency = frequency

    def __repr__(self):
        return "%s: [%s]" % (util.obj_name(self), self.list_types())

    @abc.abstractmethod
    def list_types(self):
        raise NotImplementedError()

    def handle_part(self, data, ctype, filename, payload, frequency):
        return self._handle_part(data, ctype, filename, payload, frequency)

    @abc.abstractmethod
    def _handle_part(self, data, ctype, filename, payload, frequency):
        raise NotImplementedError()


def run_part(mod, data, ctype, filename, payload, frequency):
    mod_freq = mod.frequency
    if not (mod_freq == PER_ALWAYS or
            (frequency == PER_INSTANCE and mod_freq == PER_INSTANCE)):
        return
    mod_ver = mod.handler_version
    # Sanity checks on version (should be an int convertable)
    try:
        mod_ver = int(mod_ver)
    except:
        mod_ver = None
    try:
        if mod_ver and mod_ver >= 2:
            # Treat as v. 2 which does get a frequency
            mod.handle_part(data, ctype, filename, payload, frequency)
        else:
            # Treat as v. 1 which gets no frequency
            mod.handle_part(data, ctype, filename, payload)
    except:
        util.logexc(LOG, ("Failed calling handler %s (%s, %s, %s)"
                         " with frequency %s"), 
                    mod, ctype, filename,
                    mod_ver, frequency)


def call_begin(mod, data, frequency):
    run_part(mod, data, CONTENT_START, None, None, frequency)


def call_end(mod, data, frequency):
    run_part(mod, data, CONTENT_END, None, None, frequency)


def walker_handle_handler(pdata, _ctype, _filename, payload):
    curcount = pdata['handlercount']
    modname = PART_HANDLER_FN_TMPL % (curcount)
    frequency = pdata['frequency']
    modfname = os.path.join(pdata['handlerdir'], "%s" % (modname))
    if not modfname.endswith(".py"):
        modfname = "%s.py" % (modfname)
    # TODO: Check if path exists??
    util.write_file(modfname, payload, 0600)
    handlers = pdata['handlers']
    try:
        mod = fixup_handler(importer.import_module(modname))
        handlers.register(mod)
        call_begin(mod, pdata['data'], frequency)
        pdata['handlercount'] = curcount + 1
    except:
        util.logexc(LOG, "Failed at registered python file: %s", modfname)


def _extract_first_or_bytes(blob, size):
    # Extract the first line upto X bytes or X bytes from more than the
    # first line if the first line does not contain enough bytes
    first_line = blob.split("\n", 1)[0]
    if len(first_line) >= size:
        start = first_line[:size]
    else:
        start = blob[0:size]
    return start


def walker_callback(pdata, ctype, filename, payload):
    if ctype in PART_CONTENT_TYPES:
        walker_handle_handler(pdata, ctype, filename, payload)
        return
    handlers = pdata['handlers']
    if ctype not in handlers:
        # Extract the first line or 24 bytes for displaying in the log
        start = _extract_first_or_bytes(payload, 24)
        details = "'%s...'" % (start.encode("string-escape"))
        if ctype == NOT_MULTIPART_TYPE:
            LOG.warning("Unhandled non-multipart (%s) userdata: %s",
                        ctype, details)
        else:
            LOG.warning("Unhandled unknown content-type (%s) userdata: %s",
                        ctype, details)
    else:
        run_part(handlers[ctype], pdata['data'], ctype, filename,
                 payload, pdata['frequency'])


# Callback is a function that will be called with 
# (data, content_type, filename, payload)
def walk(msg, callback, data):
    partnum = 0
    for part in msg.walk():
        # multipart/* are just containers
        if part.get_content_maintype() == 'multipart':
            continue

        ctype = part.get_content_type()
        if ctype is None:
            ctype = OCTET_TYPE

        filename = part.get_filename()
        if not filename:
            filename = PART_FN_TPL % (partnum)

        callback(data, ctype, filename, part.get_payload(decode=True))
        partnum = partnum + 1


def fixup_handler(mod, def_freq=PER_INSTANCE):
    if not hasattr(mod, "handler_version"):
        setattr(mod, "handler_version", 1)
    if not hasattr(mod, 'list_types'):
        def empty_types():
            return []
        setattr(mod, 'list_types', empty_types)
    if not hasattr(mod, 'frequency'):
        setattr(mod, 'frequency', def_freq)
    else:
        freq = mod.frequency
        if freq and freq not in FREQUENCIES:
            LOG.warn("Handler %s has an unknown frequency %s", mod, freq)
    if not hasattr(mod, 'handle_part'):
        def empty_handler(_data, _ctype, _filename, _payload):
            pass
        setattr(mod, 'handle_part', empty_handler)
    return mod


def type_from_starts_with(payload, default=None):
    for text in INCLUSION_SRCH:
        if payload.startswith(text):
            return INCLUSION_TYPES_MAP[text]
    return default


