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

from email.mime.multipart import MIMEMultipart

import abc

from cloudinit import importer
from cloudinit import log as logging
from cloudinit import user_data as ud
from cloudinit import util

DEP_FILESYSTEM = "FILESYSTEM"
DEP_NETWORK = "NETWORK"
DS_PREFIX = 'DataSource'

LOG = logging.getLogger(__name__)


class DataSourceNotFoundException(Exception):
    pass


class DataSource(object):

    __metaclass__ = abc.ABCMeta

    def __init__(self, sys_cfg, distro, paths, ud_proc=None):
        self.sys_cfg = sys_cfg
        self.distro = distro
        self.paths = paths
        self.userdata = None
        self.metadata = None
        self.userdata_raw = None
        name = util.obj_name(self)
        if name.startswith(DS_PREFIX):
            name = name[len(DS_PREFIX):]
        self.ds_cfg = util.get_cfg_by_path(self.sys_cfg,
                                          ("datasource", name), {})
        if not ud_proc:
            self.ud_proc = ud.UserDataProcessor(self.paths)
        else:
            self.ud_proc = ud_proc

    def get_userdata(self, apply_filter=False):
        if self.userdata is None:
            self.userdata = self.ud_proc.process(self.get_userdata_raw())
        if apply_filter:
            return self._filter_userdata(self.userdata)
        return self.userdata

    def get_launch_index(self):
        return None

    def _filter_userdata(self, processed_ud):
        if not processed_ud:
            return processed_ud
        idx = self.get_launch_index()
        if idx is None:
            return processed_ud
        # First do a scan to see if any one with launch-index
        # headers, if not just skip this....
        launch_idxs = 0
        for part in processed_ud.walk():
            if ud.is_skippable(part):
                continue
            launch_idx_h = part.get('Launch-Index', None)
            if launch_idx_h is not None:
                launch_idxs += 1
        if not launch_idxs:
            return processed_ud
        # Reform a new message with those that either have
        # no launch index or ones that have our launch index or ones
        # that have some other garbage that we don't know what to do with
        accumulating_msg = MIMEMultipart()
        tot_attached = 0
        tot_processed = 0
        for part in processed_ud.walk():
            if ud.is_skippable(part):
                continue
            try:
                tot_processed += 1
                launch_idx_h = part.get('Launch-Index', None)
                if launch_idx_h is None or int(launch_idx_h) == int(idx):
                    accumulating_msg.attach(part)
                    tot_attached += 1
                else:
                    LOG.debug(("Discarding multipart message %s, "
                               "launch-index provided destined for %s "
                               "and not %s"),
                               tot_processed, launch_idx_h, idx)
            except (TypeError, ValueError):
                # If any int conversion fails keep the message
                accumulating_msg.attach(part)
                tot_attached += 1
        accumulating_msg[ud.ATTACHMENT_FIELD] = str(tot_attached)
        return accumulating_msg

    @property
    def is_disconnected(self):
        return False

    def get_userdata_raw(self):
        return self.userdata_raw

    # the data sources' config_obj is a cloud-config formated
    # object that came to it from ways other than cloud-config
    # because cloud-config content would be handled elsewhere
    def get_config_obj(self):
        return {}

    def get_public_ssh_keys(self):
        keys = []

        if not self.metadata or 'public-keys' not in self.metadata:
            return keys

        if isinstance(self.metadata['public-keys'], (basestring, str)):
            return str(self.metadata['public-keys']).splitlines()

        if isinstance(self.metadata['public-keys'], (list, set)):
            return list(self.metadata['public-keys'])

        if isinstance(self.metadata['public-keys'], (dict)):
            for (_keyname, klist) in self.metadata['public-keys'].iteritems():
                # lp:506332 uec metadata service responds with
                # data that makes boto populate a string for 'klist' rather
                # than a list.
                if isinstance(klist, (str, basestring)):
                    klist = [klist]
                if isinstance(klist, (list, set)):
                    for pkey in klist:
                        # There is an empty string at
                        # the end of the keylist, trim it
                        if pkey:
                            keys.append(pkey)

        return keys

    def device_name_to_device(self, _name):
        # translate a 'name' to a device
        # the primary function at this point is on ec2
        # to consult metadata service, that has
        #  ephemeral0: sdb
        # and return 'sdb' for input 'ephemeral0'
        return None

    def get_locale(self):
        return 'en_US.UTF-8'

    @property
    def availability_zone(self):
        return self.metadata.get('availability-zone')

    def get_instance_id(self):
        if not self.metadata or 'instance-id' not in self.metadata:
            # Return a magic not really instance id string
            return "iid-datasource"
        return str(self.metadata['instance-id'])

    def get_hostname(self, fqdn=False):
        defdomain = "localdomain"
        defhost = "localhost"
        domain = defdomain

        if not self.metadata or not 'local-hostname' in self.metadata:
            # this is somewhat questionable really.
            # the cloud datasource was asked for a hostname
            # and didn't have one. raising error might be more appropriate
            # but instead, basically look up the existing hostname
            toks = []
            hostname = util.get_hostname()
            fqdn = util.get_fqdn_from_hosts(hostname)
            if fqdn and fqdn.find(".") > 0:
                toks = str(fqdn).split(".")
            elif hostname:
                toks = [hostname, defdomain]
            else:
                toks = [defhost, defdomain]
        else:
            # if there is an ipv4 address in 'local-hostname', then
            # make up a hostname (LP: #475354) in format ip-xx.xx.xx.xx
            lhost = self.metadata['local-hostname']
            if util.is_ipv4(lhost):
                toks = "ip-%s" % lhost.replace(".", "-")
            else:
                toks = lhost.split(".")

        if len(toks) > 1:
            hostname = toks[0]
            domain = '.'.join(toks[1:])
        else:
            hostname = toks[0]

        if fqdn:
            return "%s.%s" % (hostname, domain)
        else:
            return hostname

    def get_package_mirror_info(self):
        return self.distro.get_package_mirror_info(
            availability_zone=self.availability_zone)


def find_source(sys_cfg, distro, paths, ds_deps, cfg_list, pkg_list):
    ds_list = list_sources(cfg_list, ds_deps, pkg_list)
    ds_names = [util.obj_name(f) for f in ds_list]
    LOG.debug("Searching for data source in: %s", ds_names)

    for cls in ds_list:
        try:
            LOG.debug("Seeing if we can get any data from %s", cls)
            s = cls(sys_cfg, distro, paths)
            if s.get_data():
                return (s, util.obj_name(cls))
        except Exception:
            util.logexc(LOG, "Getting data from %s failed", cls)

    msg = ("Did not find any data source,"
           " searched classes: (%s)") % (", ".join(ds_names))
    raise DataSourceNotFoundException(msg)


# Return a list of classes that have the same depends as 'depends'
# iterate through cfg_list, loading "DataSource*" modules
# and calling their "get_datasource_list".
# Return an ordered list of classes that match (if any)
def list_sources(cfg_list, depends, pkg_list):
    src_list = []
    LOG.debug(("Looking for for data source in: %s,"
               " via packages %s that matches dependencies %s"),
              cfg_list, pkg_list, depends)
    for ds_name in cfg_list:
        if not ds_name.startswith(DS_PREFIX):
            ds_name = '%s%s' % (DS_PREFIX, ds_name)
        m_locs = importer.find_module(ds_name,
                                      pkg_list,
                                      ['get_datasource_list'])
        for m_loc in m_locs:
            mod = importer.import_module(m_loc)
            lister = getattr(mod, "get_datasource_list")
            matches = lister(depends)
            if matches:
                src_list.extend(matches)
                break
    return src_list


# 'depends' is a list of dependencies (DEP_FILESYSTEM)
# ds_list is a list of 2 item lists
# ds_list = [
#   ( class, ( depends-that-this-class-needs ) )
# }
# It returns a list of 'class' that matched these deps exactly
# It mainly is a helper function for DataSourceCollections
def list_from_depends(depends, ds_list):
    ret_list = []
    depset = set(depends)
    for (cls, deps) in ds_list:
        if depset == set(deps):
            ret_list.append(cls)
    return ret_list
