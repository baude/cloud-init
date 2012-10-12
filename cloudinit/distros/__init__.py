# vi: ts=4 expandtab
#
#    Copyright (C) 2012 Canonical Ltd.
#    Copyright (C) 2012 Hewlett-Packard Development Company, L.P.
#    Copyright (C) 2012 Yahoo! Inc.
#
#    Author: Scott Moser <scott.moser@canonical.com>
#    Author: Juerg Haefliger <juerg.haefliger@hp.com>
#    Author: Joshua Harlow <harlowja@yahoo-inc.com>
#    Author: Ben Howard <ben.howard@canonical.com>
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

import abc
import itertools
import os
import re

from cloudinit import importer
from cloudinit import log as logging
from cloudinit import ssh_util
from cloudinit import util

from cloudinit.distros.parsers import hosts

LOG = logging.getLogger(__name__)


class Distro(object):

    __metaclass__ = abc.ABCMeta
    default_user = None
    default_user_groups = None
    hosts_fn = "/etc/hosts"
    ci_sudoers_fn = "/etc/sudoers.d/90-cloud-init-users"

    def __init__(self, name, cfg, paths):
        self._paths = paths
        self._cfg = cfg
        self.name = name

    @abc.abstractmethod
    def install_packages(self, pkglist):
        raise NotImplementedError()

    @abc.abstractmethod
    def _write_network(self, settings):
        # In the future use the http://fedorahosted.org/netcf/
        # to write this blob out in a distro format
        raise NotImplementedError()

    def get_option(self, opt_name, default=None):
        return self._cfg.get(opt_name, default)

    @abc.abstractmethod
    def set_hostname(self, hostname):
        raise NotImplementedError()

    @abc.abstractmethod
    def package_command(self, cmd, args=None):
        raise NotImplementedError()

    @abc.abstractmethod
    def update_package_sources(self):
        raise NotImplementedError()

    def get_primary_arch(self):
        arch = os.uname[4]
        if arch in ("i386", "i486", "i586", "i686"):
            return "i386"
        return arch

    def _get_arch_package_mirror_info(self, arch=None):
        mirror_info = self.get_option("package_mirrors", [])
        if arch == None:
            arch = self.get_primary_arch()
        return _get_arch_package_mirror_info(mirror_info, arch)

    def get_package_mirror_info(self, arch=None,
                                availability_zone=None):
        # this resolves the package_mirrors config option
        # down to a single dict of {mirror_name: mirror_url}
        arch_info = self._get_arch_package_mirror_info(arch)
        return _get_package_mirror_info(availability_zone=availability_zone,
                                        mirror_info=arch_info)

    def apply_network(self, settings, bring_up=True):
        # Write it out
        dev_names = self._write_network(settings)
        # Now try to bring them up
        if bring_up:
            return self._bring_up_interfaces(dev_names)
        return False

    @abc.abstractmethod
    def apply_locale(self, locale, out_fn=None):
        raise NotImplementedError()

    @abc.abstractmethod
    def set_timezone(self, tz):
        raise NotImplementedError()

    def _get_localhost_ip(self):
        return "127.0.0.1"

    @abc.abstractmethod
    def _read_hostname(self, filename, default=None):
        raise NotImplementedError()

    @abc.abstractmethod
    def _write_hostname(self, hostname, filename):
        raise NotImplementedError()

    @abc.abstractmethod
    def _read_system_hostname(self):
        raise NotImplementedError()

    def _apply_hostname(self, hostname):
        # This really only sets the hostname
        # temporarily (until reboot so it should
        # not be depended on). Use the write
        # hostname functions for 'permanent' adjustments.
        LOG.debug("Non-persistently setting the system hostname to %s",
                  hostname)
        try:
            util.subp(['hostname', hostname])
        except util.ProcessExecutionError:
            util.logexc(LOG, ("Failed to non-persistently adjust"
                              " the system hostname to %s"), hostname)

    def update_hostname(self, hostname, prev_hostname_fn):
        if not hostname:
            return

        prev_hostname = self._read_hostname(prev_hostname_fn)
        (sys_fn, sys_hostname) = self._read_system_hostname()
        update_files = []
        if not prev_hostname or prev_hostname != hostname:
            update_files.append(prev_hostname_fn)

        if (not sys_hostname) or (sys_hostname == prev_hostname
                                  and sys_hostname != hostname):
            update_files.append(sys_fn)

        update_files = set([f for f in update_files if f])
        LOG.debug("Attempting to update hostname to %s in %s files",
                  hostname, len(update_files))

        for fn in update_files:
            try:
                self._write_hostname(hostname, fn)
            except IOError:
                util.logexc(LOG, "Failed to write hostname %s to %s",
                            hostname, fn)

        if (sys_hostname and prev_hostname and
            sys_hostname != prev_hostname):
            LOG.debug("%s differs from %s, assuming user maintained hostname.",
                       prev_hostname_fn, sys_fn)

        if sys_fn in update_files:
            self._apply_hostname(hostname)

    def update_etc_hosts(self, hostname, fqdn):
        header = ''
        if os.path.exists(self.hosts_fn):
            eh = hosts.HostsConf(util.load_file(self.hosts_fn))
        else:
            eh = hosts.HostsConf('')
            header = util.make_header(base="added")
        local_ip = self._get_localhost_ip()
        prev_info = eh.get_entry(local_ip)
        need_change = False
        if not prev_info:
            eh.add_entry(local_ip, fqdn, hostname)
            need_change = True
        else:
            need_change = True
            for entry in prev_info:
                if sorted(entry) == sorted([fqdn, hostname]):
                    # Exists already, leave it be
                    need_change = False
                    break
            if need_change:
                # Doesn't exist, change the first
                # entry to be this entry
                new_entries = list(prev_info)
                new_entries[0] = [fqdn, hostname]
                eh.del_entries(local_ip)
                for entry in new_entries:
                    if len(entry) == 1:
                        eh.add_entry(local_ip, entry[0])
                    elif len(entry) >= 2:
                        eh.add_entry(local_ip, *entry)
        if need_change:
            contents = StringIO()
            if header:
                contents.write("%s\n" % (header))
            contents.write("%s\n" % (eh))
            util.write_file(self.hosts_fn, contents.getvalue(), mode=0644)

    def _bring_up_interface(self, device_name):
        cmd = ['ifup', device_name]
        LOG.debug("Attempting to run bring up interface %s using command %s",
                   device_name, cmd)
        try:
            (_out, err) = util.subp(cmd)
            if len(err):
                LOG.warn("Running %s resulted in stderr output: %s", cmd, err)
            return True
        except util.ProcessExecutionError:
            util.logexc(LOG, "Running interface command %s failed", cmd)
            return False

    def _bring_up_interfaces(self, device_names):
        am_failed = 0
        for d in device_names:
            if not self._bring_up_interface(d):
                am_failed += 1
        if am_failed == 0:
            return True
        return False

    def get_default_user(self):
        if not self.default_user:
            return None
        user_cfg = {
            'name': self.default_user,
            'plain_text_passwd': self.default_user,
            'home': "/home/%s" % (self.default_user),
            'shell': "/bin/bash",
            'lock_passwd': True,
            'gecos': "%s" % (self.default_user.title()),
            'sudo': "ALL=(ALL) NOPASSWD:ALL",
        }
        def_groups = self.default_user_groups
        if not def_groups:
            def_groups = []
        user_cfg['groups'] = util.uniq_merge_sorted(def_groups)
        return user_cfg

    def create_user(self, name, **kwargs):
        """
            Creates users for the system using the GNU passwd tools. This
            will work on an GNU system. This should be overriden on
            distros where useradd is not desirable or not available.
        """

        adduser_cmd = ['useradd', name]
        x_adduser_cmd = ['useradd', name]

        # Since we are creating users, we want to carefully validate the
        # inputs. If something goes wrong, we can end up with a system
        # that nobody can login to.
        adduser_opts = {
                "gecos": '--comment',
                "homedir": '--home',
                "primary_group": '--gid',
                "groups": '--groups',
                "passwd": '--password',
                "shell": '--shell',
                "expiredate": '--expiredate',
                "inactive": '--inactive',
                "selinux_user": '--selinux-user',
                }

        adduser_opts_flags = {
                "no_user_group": '--no-user-group',
                "system": '--system',
                "no_log_init": '--no-log-init',
                "no_create_home": "-M",
                }

        # Now check the value and create the command
        for option in kwargs:
            value = kwargs[option]
            if option in adduser_opts and value \
                and isinstance(value, str):
                adduser_cmd.extend([adduser_opts[option], value])

                # Redact the password field from the logs
                if option != "password":
                    x_adduser_cmd.extend([adduser_opts[option], value])
                else:
                    x_adduser_cmd.extend([adduser_opts[option], 'REDACTED'])

            elif option in adduser_opts_flags and value:
                adduser_cmd.append(adduser_opts_flags[option])
                x_adduser_cmd.append(adduser_opts_flags[option])

        # Default to creating home directory unless otherwise directed
        #  Also, we do not create home directories for system users.
        if "no_create_home" not in kwargs and "system" not in kwargs:
            adduser_cmd.append('-m')

        # Create the user
        if util.is_user(name):
            LOG.warn("User %s already exists, skipping." % name)
        else:
            LOG.debug("Creating name %s" % name)
            try:
                util.subp(adduser_cmd, logstring=x_adduser_cmd)
            except Exception as e:
                util.logexc(LOG, "Failed to create user %s due to error.", e)
                raise e

        # Set password if plain-text password provided
        if 'plain_text_passwd' in kwargs and kwargs['plain_text_passwd']:
            self.set_passwd(name, kwargs['plain_text_passwd'])

        # Default locking down the account.
        if ('lock_passwd' not in kwargs and
            ('lock_passwd' in kwargs and kwargs['lock_passwd']) or
            'system' not in kwargs):
            try:
                util.subp(['passwd', '--lock', name])
            except Exception as e:
                util.logexc(LOG, ("Failed to disable password logins for"
                            "user %s" % name), e)
                raise e

        # Configure sudo access
        if 'sudo' in kwargs:
            self.write_sudo_rules(name, kwargs['sudo'])

        # Import SSH keys
        if 'ssh_authorized_keys' in kwargs:
            keys = set(kwargs['ssh_authorized_keys']) or []
            ssh_util.setup_user_keys(keys, name, None, self._paths)

        return True

    def set_passwd(self, user, passwd, hashed=False):
        pass_string = '%s:%s' % (user, passwd)
        cmd = ['chpasswd']

        if hashed:
            cmd.append('--encrypted')

        try:
            util.subp(cmd, pass_string, logstring="chpasswd for %s" % user)
        except Exception as e:
            util.logexc(LOG, "Failed to set password for %s" % user)
            raise e

        return True

    def write_sudo_rules(self, user, rules, sudo_file=None):
        if not sudo_file:
            sudo_file = self.ci_sudoers_fn

        content_header = "# User rules for %s" % user
        content = "%s\n%s %s\n\n" % (content_header, user, rules)

        if isinstance(rules, (list, tuple, set)):
            content = "%s\n" % content_header
            for rule in rules:
                content += "%s %s\n" % (user, rule)
            content += "\n"

        if not os.path.exists(sudo_file):
            contents = [
                util.make_header(),
                content,
            ]
            util.write_file(sudo_file, "\n".join(contents), 0440)
        else:
            try:
                with open(sudo_file, 'a') as f:
                    f.write(content)
            except IOError as e:
                util.logexc(LOG, "Failed to write sudoers file %s", sudo_file)
                raise e

    def create_group(self, name, members):
        group_add_cmd = ['groupadd', name]

        # Check if group exists, and then add it doesn't
        if util.is_group(name):
            LOG.warn("Skipping creation of existing group '%s'" % name)
        else:
            try:
                util.subp(group_add_cmd)
                LOG.info("Created new group %s" % name)
            except Exception as e:
                util.logexc("Failed to create group %s" % name, e)

        # Add members to the group, if so defined
        if len(members) > 0:
            for member in members:
                if not util.is_user(member):
                    LOG.warn("Unable to add group member '%s' to group '%s'"
                            "; user does not exist." % (member, name))
                    continue

                util.subp(['usermod', '-a', '-G', name, member])
                LOG.info("Added user '%s' to group '%s'" % (member, name))


def _get_package_mirror_info(mirror_info, availability_zone=None,
                             mirror_filter=util.search_for_mirror):
    # given a arch specific 'mirror_info' entry (from package_mirrors)
    # search through the 'search' entries, and fallback appropriately
    # return a dict with only {name: mirror} entries.
    if not mirror_info:
        mirror_info = {}

    ec2_az_re = ("^[a-z][a-z]-(%s)-[1-9][0-9]*[a-z]$" %
        "north|northeast|east|southeast|south|southwest|west|northwest")

    subst = {}
    if availability_zone:
        subst['availability_zone'] = availability_zone

    if availability_zone and re.match(ec2_az_re, availability_zone):
        subst['ec2_region'] = "%s" % availability_zone[0:-1]

    results = {}
    for (name, mirror) in mirror_info.get('failsafe', {}).iteritems():
        results[name] = mirror

    for (name, searchlist) in mirror_info.get('search', {}).iteritems():
        mirrors = []
        for tmpl in searchlist:
            try:
                mirrors.append(tmpl % subst)
            except KeyError:
                pass

        found = mirror_filter(mirrors)
        if found:
            results[name] = found

    LOG.debug("filtered distro mirror info: %s" % results)

    return results


def _get_arch_package_mirror_info(package_mirrors, arch):
    # pull out the specific arch from a 'package_mirrors' config option
    default = None
    for item in package_mirrors:
        arches = item.get("arches")
        if arch in arches:
            return item
        if "default" in arches:
            default = item
    return default


# Normalizes a input group configuration
# which can be a comma seperated list of
# group names, or a list of group names
# or a python dictionary of group names
# to a list of members of that group.
#
# The output is a dictionary of group
# names => members of that group which
# is the standard form used in the rest
# of cloud-init
def _normalize_groups(grp_cfg):
    if isinstance(grp_cfg, (str, basestring, list)):
        c_grp_cfg = {}
        for i in util.uniq_merge(grp_cfg):
            c_grp_cfg[i] = []
        grp_cfg = c_grp_cfg

    groups = {}
    if isinstance(grp_cfg, (dict)):
        for (grp_name, grp_members) in grp_cfg.items():
            groups[grp_name] = util.uniq_merge_sorted(grp_members)
    else:
        raise TypeError(("Group config must be list, dict "
                         " or string types only and not %s") %
                        util.obj_name(grp_cfg))
    return groups


# Normalizes a input group configuration
# which can be a comma seperated list of
# user names, or a list of string user names
# or a list of dictionaries with components
# that define the user config + 'name' (if
# a 'name' field does not exist then the
# default user is assumed to 'own' that
# configuration.
#
# The output is a dictionary of user
# names => user config which is the standard 
# form used in the rest of cloud-init. Note
# the default user will have a special config
# entry 'default' which will be marked as true
# all other users will be marked as false.
def _normalize_users(u_cfg, def_user_cfg=None):
    if isinstance(u_cfg, (dict)):
        ad_ucfg = []
        for (k, v) in u_cfg.items():
            if isinstance(v, (bool, int, basestring, str, float)):
                if util.is_true(v):
                    ad_ucfg.append(str(k))
            elif isinstance(v, (dict)):
                v['name'] = k
                ad_ucfg.append(v)
            else:
                raise TypeError(("Unmappable user value type %s"
                                 " for key %s") % (util.obj_name(v), k))
        u_cfg = ad_ucfg
    elif isinstance(u_cfg, (str, basestring)):
        u_cfg = util.uniq_merge_sorted(u_cfg)

    users = {}
    for user_config in u_cfg:
        if isinstance(user_config, (str, basestring, list)):
            for u in util.uniq_merge(user_config):
                if u and u not in users:
                    users[u] = {}
        elif isinstance(user_config, (dict)):
            if 'name' in user_config:
                n = user_config.pop('name')
                prev_config = users.get(n) or {}
                users[n] = util.mergemanydict([prev_config,
                                               user_config])
            else:
                # Assume the default user then
                prev_config = users.get('default') or {}
                users['default'] = util.mergemanydict([prev_config,
                                                       user_config])
        else:
            raise TypeError(("User config must be dictionary/list "
                             " or string types only and not %s") %
                            util.obj_name(user_config))

    # Ensure user options are in the right python friendly format
    if users:
        c_users = {}
        for (uname, uconfig) in users.items():
            c_uconfig = {}
            for (k, v) in uconfig.items():
                k = k.replace('-', '_').strip()
                if k:
                    c_uconfig[k] = v
            c_users[uname] = c_uconfig
        users = c_users

    # Fixup the default user into the real
    # default user name and replace it...
    def_user = None
    if users and 'default' in users:
        def_config = users.pop('default')
        if def_user_cfg:
            # Pickup what the default 'real name' is
            # and any groups that are provided by the
            # default config
            def_user = def_user_cfg.pop('name')
            def_groups = def_user_cfg.pop('groups', [])
            # Pickup any config + groups for that user name
            # that we may have previously extracted
            parsed_config = users.pop(def_user, {})
            parsed_groups = parsed_config.get('groups', [])
            # Now merge our extracted groups with
            # anything the default config provided
            users_groups = util.uniq_merge_sorted(parsed_groups, def_groups)
            parsed_config['groups'] = ",".join(users_groups)
            # The real config for the default user is the
            # combination of the default user config provided
            # by the distro, the default user config provided
            # by the above merging for the user 'default' and
            # then the parsed config from the user's 'real name'
            # which does not have to be 'default' (but could be)
            users[def_user] = util.mergemanydict([def_user_cfg,
                                                  def_config,
                                                  parsed_config])

    # Ensure that only the default user that we
    # found (if any) is actually marked as being
    # the default user
    if users:
        for (uname, uconfig) in users.items():
            if def_user and uname == def_user:
                uconfig['default'] = True
            else:
                uconfig['default'] = False

    return users


# Normalizes a set of user/users and group
# dictionary configuration into a useable
# format that the rest of cloud-init can
# understand using the default user
# provided by the input distrobution (if any)
# to allow for mapping of the 'default' user.
#
# Output is a dictionary of group names -> [member] (list)
# and a dictionary of user names -> user configuration (dict)
#
# If 'user' exists it will override
# the 'users'[0] entry (if a list) otherwise it will
# just become an entry in the returned dictionary (no override)
def normalize_users_groups(cfg, distro):
    if not cfg:
        cfg = {}
    users = {}
    groups = {}
    if 'groups' in cfg:
        groups = _normalize_groups(cfg['groups'])

    # Handle the previous style of doing this...
    old_user = None
    if 'user' in cfg and cfg['user']:
        old_user = str(cfg['user'])
        if not 'users' in cfg:
            cfg['users'] = old_user
            old_user = None
    if 'users' in cfg:
        default_user_config = None
        try:
            default_user_config = distro.get_default_user()
        except NotImplementedError:
            LOG.warn(("Distro has not implemented default user "
                      "access. No default user will be normalized."))
        base_users = cfg['users']
        if old_user:
            if isinstance(base_users, (list)):
                if len(base_users):
                    # The old user replaces user[0]
                    base_users[0] = {'name': old_user}
                else:
                    # Just add it on at the end...
                    base_users.append({'name': old_user})
            elif isinstance(base_users, (dict)):
                if old_user not in base_users:
                    base_users[old_user] = True
            elif isinstance(base_users, (str, basestring)):
                # Just append it on to be re-parsed later
                base_users += ",%s" % (old_user)
        users = _normalize_users(base_users, default_user_config)
    return (users, groups)


# Given a user dictionary config it will
# extract the default user name and user config
# from that list and return that tuple or
# return (None, None) if no default user is
# found in the given input
def extract_default(users, default_name=None, default_config=None):
    if not users:
        users = {}

    def safe_find(entry):
        config = entry[1]
        if not config or 'default' not in config:
            return False
        else:
            return config['default']

    tmp_users = users.items()
    tmp_users = dict(itertools.ifilter(safe_find, tmp_users))
    if not tmp_users:
        return (default_name, default_config)
    else:
        name = tmp_users.keys()[0]
        config = tmp_users[name]
        config.pop('default', None)
        return (name, config)


def fetch(name):
    locs = importer.find_module(name,
                                ['', __name__],
                                ['Distro'])
    if not locs:
        raise ImportError("No distribution found for distro %s"
                           % (name))
    mod = importer.import_module(locs[0])
    cls = getattr(mod, 'Distro')
    return cls
