#!/usr/bin/python
# vi: ts=4 expandtab
#
#    Copyright (C) 2012 Canonical Ltd.
#    Copyright (C) 2012 Hewlett-Packard Development Company, L.P.
#
#    Author: Scott Moser <scott.moser@canonical.com>
#    Author: Juerg Hafliger <juerg.haefliger@hp.com>
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

from StringIO import StringIO

import csv
import os
import pwd

from cloudinit import log as logging
from cloudinit import util

LOG = logging.getLogger(__name__)
DEF_SSHD_CFG = "/etc/ssh/sshd_config"


class AuthKeyLine(object):
    def __init__(self, source, keytype=None, base64=None,
                 comment=None, options=None):
        self.base64 = base64
        self.comment = comment
        self.options = options
        self.keytype = keytype
        self.source = source

    def empty(self):
        if (not self.base64 and
            not self.comment and not self.keytype and not self.options):
            return True
        return False

    def __str__(self):
        toks = []
        if self.options:
            toks.append(self.options)
        if self.keytype:
            toks.append(self.keytype)
        if self.base64:
            toks.append(self.base64)
        if self.comment:
            toks.append(self.comment)
        if not toks:
            return self.source
        else:
            return ' '.join(toks)


class AuthKeyLineParser(object):
    """
    AUTHORIZED_KEYS FILE FORMAT
     AuthorizedKeysFile specifies the file containing public keys for public
     key authentication; if none is specified, the default is
     ~/.ssh/authorized_keys.  Each line of the file contains one key (empty
     (because of the size of the public key encoding) up to a limit of 8 kilo-
     bytes, which permits DSA keys up to 8 kilobits and RSA keys up to 16
     kilobits.  You don't want to type them in; instead, copy the
     identity.pub, id_dsa.pub, or the id_rsa.pub file and edit it.

     sshd enforces a minimum RSA key modulus size for protocol 1 and protocol
     2 keys of 768 bits.

     The options (if present) consist of comma-separated option specifica-
     tions.  No spaces are permitted, except within double quotes.  The fol-
     lowing option specifications are supported (note that option keywords are
     case-insensitive):
    """

    def _extract_options(self, ent):
        """
        The options (if present) consist of comma-separated option specifica-
         tions.  No spaces are permitted, except within double quotes.
         Note that option keywords are case-insensitive.
        """
        quoted = False
        i = 0
        while (i < len(ent) and
               ((quoted) or (ent[i] not in (" ", "\t")))):
            curc = ent[i]
            if i + 1 >= len(ent):
                i = i + 1
                break
            nextc = ent[i + 1]
            if curc == "\\" and nextc == '"':
                i = i + 1
            elif curc == '"':
                quoted = not quoted
            i = i + 1

        options = ent[0:i]
        options_lst = []

        # Now use a csv parser to pull the options
        # out of the above string that we just found an endpoint for.
        #
        # No quoting so we don't mess up any of the quoting that
        # is already there.
        reader = csv.reader(StringIO(options), quoting=csv.QUOTE_NONE)
        for row in reader:
            for e in row:
                # Only keep non-empty csv options
                e = e.strip()
                if e:
                    options_lst.append(e)

        # Now take the rest of the items before the string
        # as long as there is room to do this...
        toks = []
        if i + 1 < len(ent):
            rest = ent[i + 1:]
            toks = rest.split(None, 2)
        return (options_lst, toks)

    def _form_components(self, src_line, toks, options=None):
        components = {}
        if len(toks) == 1:
            components['base64'] = toks[0]
        elif len(toks) == 2:
            components['base64'] = toks[0]
            components['comment'] = toks[1]
        elif len(toks) == 3:
            components['keytype'] = toks[0]
            components['base64'] = toks[1]
            components['comment'] = toks[2]
        components['options'] = options
        if not components:
            return AuthKeyLine(src_line)
        else:
            return AuthKeyLine(src_line, **components)

    def parse(self, src_line, def_opt=None):
        line = src_line.rstrip("\r\n")
        if line.startswith("#") or line.strip() == '':
            return AuthKeyLine(src_line)
        else:
            ent = line.strip()
            toks = ent.split(None, 3)
            if len(toks) < 4:
                return self._form_components(src_line, toks, def_opt)
            else:
                (options, toks) = self._extract_options(ent)
                if options:
                    options = ",".join(options)
                else:
                    options = def_opt
                return self._form_components(src_line, toks, options)


def parse_authorized_keys(fname):
    lines = []
    try:
        if os.path.isfile(fname):
            lines = util.load_file(fname).splitlines()
    except (IOError, OSError):
        util.logexc(LOG, "Error reading lines from %s", fname)
        lines = []

    parser = AuthKeyLineParser()
    contents = []
    for line in lines:
        contents.append(parser.parse(line))
    return contents


def update_authorized_keys(fname, keys):
    entries = parse_authorized_keys(fname)
    to_add = list(keys)

    for i in range(0, len(entries)):
        ent = entries[i]
        if ent.empty() or not ent.base64:
            continue
        # Replace those with the same base64
        for k in keys:
            if k.empty() or not k.base64:
                continue
            if k.base64 == ent.base64:
                # Replace it with our better one
                ent = k
                # Don't add it later
                to_add.remove(k)
        entries[i] = ent

    # Now append any entries we did not match above
    for key in to_add:
        entries.append(key)

    # Now format them back to strings...
    lines = [str(b) for b in entries]

    # Ensure it ends with a newline
    lines.append('')
    return '\n'.join(lines)


def setup_user_keys(keys, user, key_prefix, paths):
    # Make sure the users .ssh dir is setup accordingly
    pwent = pwd.getpwnam(user)
    ssh_dir = os.path.join(pwent.pw_dir, '.ssh')
    ssh_dir = paths.join(False, ssh_dir)
    if not os.path.exists(ssh_dir):
        util.ensure_dir(ssh_dir, mode=0700)
        util.chownbyid(ssh_dir, pwent.pw_uid, pwent.pw_gid)

    # Turn the keys given into actual entries
    parser = AuthKeyLineParser()
    key_entries = []
    for k in keys:
        key_entries.append(parser.parse(str(k), def_opt=key_prefix))

    sshd_conf_fn = paths.join(True, DEF_SSHD_CFG)
    with util.SeLinuxGuard(ssh_dir, recursive=True):
        try:
            # AuthorizedKeysFile may contain tokens
            # of the form %T which are substituted during connection set-up.
            # The following tokens are defined: %% is replaced by a literal
            # '%', %h is replaced by the home directory of the user being
            # authenticated and %u is replaced by the username of that user.
            ssh_cfg = parse_ssh_config(sshd_conf_fn)
            akeys = ssh_cfg.get("authorizedkeysfile", '')
            akeys = akeys.strip()
            if not akeys:
                akeys = "%h/.ssh/authorized_keys"
            akeys = akeys.replace("%h", pwent.pw_dir)
            akeys = akeys.replace("%u", user)
            akeys = akeys.replace("%%", '%')
            if not akeys.startswith('/'):
                akeys = os.path.join(pwent.pw_dir, akeys)
            authorized_keys = paths.join(False, akeys)
        except (IOError, OSError):
            authorized_keys = os.path.join(ssh_dir, 'authorized_keys')
            util.logexc(LOG, ("Failed extracting 'AuthorizedKeysFile'"
                              " in ssh config"
                              " from %s, using 'AuthorizedKeysFile' file"
                              " %s instead"),
                        sshd_conf_fn, authorized_keys)

        content = update_authorized_keys(authorized_keys, key_entries)
        util.ensure_dir(os.path.dirname(authorized_keys), mode=0700)
        util.write_file(authorized_keys, content, mode=0600)
        util.chownbyid(authorized_keys, pwent.pw_uid, pwent.pw_gid)


def parse_ssh_config(fname):
    # The file contains keyword-argument pairs, one per line.
    # Lines starting with '#' and empty lines are interpreted as comments.
    # Note: key-words are case-insensitive and arguments are case-sensitive
    ret = {}
    if not os.path.isfile(fname):
        return ret
    for line in util.load_file(fname).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        (key, val) = line.split(None, 1)
        key = key.strip().lower()
        if key:
            ret[key] = val
    return ret
