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

import logging
import logging.handlers
import logging.config

import os
import sys

from StringIO import StringIO

# Logging levels for easy access
CRITICAL = logging.CRITICAL
FATAL = logging.FATAL
ERROR = logging.ERROR
WARNING = logging.WARNING
WARN = logging.WARN
INFO = logging.INFO
DEBUG = logging.DEBUG
NOTSET = logging.NOTSET

# Default basic format
DEF_CON_FORMAT = '%(asctime)s - %(filename)s[%(levelname)s]: %(message)s'


def setupBasicLogging():
    root = logging.getLogger()
    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(logging.Formatter(DEF_CON_FORMAT))
    console.setLevel(DEBUG)
    root.addHandler(console)
    root.setLevel(DEBUG)


def setupLogging(cfg=None):
    # See if the config provides any logging conf...
    if not cfg:
        cfg = {}

    log_cfgs = []
    log_cfg = cfg.get('logcfg')
    if log_cfg and isinstance(log_cfg, (str, basestring)):
        # If there is a 'logcfg' entry in the config,
        # respect it, it is the old keyname
        log_cfgs.append(str(log_cfg))
    elif "log_cfgs" in cfg and isinstance(cfg['log_cfgs'], (set, list)):
        for a_cfg in cfg['log_cfgs']:
            if isinstance(a_cfg, (list, set, dict)):
                cfg_str = [str(c) for c in a_cfg]
                log_cfgs.append('\n'.join(cfg_str))
            else:
                log_cfgs.append(str(a_cfg))

    # See if any of them actually load...
    am_tried = 0
    am_worked = 0
    for i, log_cfg in enumerate(log_cfgs):
        try:
            am_tried += 1
            # Assume its just a string if not a filename
            if log_cfg.startswith("/") and os.path.isfile(log_cfg):
                pass
            else:
                log_cfg = StringIO(log_cfg)
            # Attempt to load its config
            logging.config.fileConfig(log_cfg)
            am_worked += 1
        except Exception as e:
            sys.stderr.write(("WARN: Setup of logging config %s"
                              " failed due to: %s\n") % (i + 1, e))

    # If it didn't work, at least setup a basic logger (if desired)
    basic_enabled = cfg.get('log_basic', True)
    if not am_worked:
        sys.stderr.write(("WARN: no logging configured!"
                          " (tried %s configs)\n") % (am_tried))
        if basic_enabled:
            sys.stderr.write("Setting up basic logging...\n")
            setupBasicLogging()


def getLogger(name='cloudinit'):
    return logging.getLogger(name)


# Fixes this annoyance...
# No handlers could be found for logger XXX annoying output...
try:
    from logging import NullHandler
except ImportError:
    class NullHandler(logging.Handler):
        def emit(self, record):
            pass


def _resetLogger(log):
    if not log:
        return
    handlers = list(log.handlers)
    for h in handlers:
        h.flush()
        h.close()
        log.removeHandler(h)
    log.setLevel(NOTSET)
    log.addHandler(NullHandler())


def resetLogging():
    _resetLogger(logging.getLogger())
    _resetLogger(getLogger())


resetLogging()
