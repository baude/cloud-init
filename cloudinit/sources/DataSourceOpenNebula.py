# vi: ts=4 expandtab
#
#    Copyright (C) 2012 Canonical Ltd.
#    Copyright (C) 2012 Yahoo! Inc.
#    Copyright (C) 2012 CERIT Scientific Cloud
#
#    Author: Scott Moser <scott.moser@canonical.com>
#    Author: Joshua Harlow <harlowja@yahoo-inc.com>
#    Author: Vlastimil Holer <xholer@mail.muni.cz>
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

import os
import re
import subprocess

from cloudinit import log as logging
from cloudinit import sources
from cloudinit import util

LOG = logging.getLogger(__name__)

DEFAULT_IID = "iid-dsopennebula"
CONTEXT_DISK_FILES = ["context.sh"]
VALID_DSMODES = ("local", "net", "disabled")

class DataSourceOpenNebula(sources.DataSource):
    def __init__(self, sys_cfg, distro, paths):
        sources.DataSource.__init__(self, sys_cfg, distro, paths)
        self.dsmode = 'local'
        self.seed = None
        self.seed_dir = os.path.join(paths.seed_dir, 'opennebula')

    def __str__(self):
        mstr = "%s [seed=%s][dsmode=%s]" % (util.obj_name(self),
                                            self.seed, self.dsmode)
        return mstr

    def get_data(self):
        defaults = {
            "instance-id": DEFAULT_IID,
            "dsmode": self.dsmode,
        }

        found = None
        md = {}

        results = {}
        if os.path.isdir(self.seed_dir):
            try:
                results=read_context_disk_dir(self.seed_dir)
                found = self.seed_dir
            except NonContextDeviceDir:
                util.logexc(LOG, "Failed reading context device from %s",
                            self.seed_dir)
        if not found:
            devlist = find_candidate_devs()
            for dev in devlist:
                try:
                    results = util.mount_cb(dev, read_context_disk_dir)
                    found = dev
                    break
                except (NonContextDeviceDir, util.MountFailedError):
                    pass

        if not found:
            return False

        md = results['metadata']
        md = util.mergedict(md, defaults)

        dsmode = results.get('dsmode', None)
        if dsmode not in VALID_DSMODES + (None,):
            LOG.warn("user specified invalid mode: %s" % dsmode)
            dsmode = None

        if (dsmode is None) and self.ds_cfg.get('dsmode'):
            dsmode = self.ds_cfg.get('dsmode')
        else:
            dsmode = self.dsmode

        if dsmode == "disabled":
            # most likely user specified
            return False

        if dsmode != self.dsmode:
            LOG.debug("%s: not claiming datasource, dsmode=%s", self, dsmode)
            return False

        self.seed = found
        self.metadata = md
        self.userdata_raw = results.get('userdata')

        if 'network-interfaces' in results:
            self.distro.apply_network(results['network-interfaces'])

        if 'dns' in results:
            self.distro.apply_resolv_conf(results['dns'])

        return True

    def get_hostname(self, fqdn=False, resolve_ip=None):
        if resolve_ip is None:
            if self.dsmode == 'net':
                resolve_ip = True
            else:
                resolve_ip = False
        return sources.DataSource.get_hostname(self, fqdn, resolve_ip)


class DataSourceOpenNebulaNet(DataSourceOpenNebula):
    def __init__(self, sys_cfg, distro, paths):
        DataSourceOpenNebula.__init__(self, sys_cfg, distro, paths)
        self.dsmode = 'net'


class NonContextDeviceDir(Exception):
    pass


class OpenNebulaNetwork(object):
    REG_ETH=re.compile('^eth')
    REG_DEV_MAC=re.compile('^(eth\d+).*HWaddr (..:..:..:..:..:..)')

    def __init__(self, ifconfig, context_sh):
        self.ifconfig=ifconfig
        self.context_sh=context_sh
        self.ifaces=self.get_ifaces()

    def get_ifaces(self):
        return [self.REG_DEV_MAC.search(f).groups() for f in self.ifconfig.split("\n") if self.REG_ETH.match(f)]

    def mac2ip(self, mac):
        components=mac.split(':')[2:]

        return [str(int(c, 16)) for c in components]
        
    def get_ip(self, dev, components):
        var_name=dev+'_ip'
        if var_name in self.context_sh:
            return self.context_sh[var_name]
        else:
            return '.'.join(components)

    def get_mask(self, dev, components):
        var_name=dev+'_mask'
        if var_name in self.context_sh:
            return self.context_sh[var_name]
        else:
            return '255.255.255.0'

    def get_network(self, dev, components):
        var_name=dev+'_network'
        if var_name in self.context_sh:
            return self.context_sh[var_name]
        else:
            return '.'.join(components[:-1])+'.0'

    def get_gateway(self, dev, components):
        var_name=dev+'_gateway'
        if var_name in self.context_sh:
            return self.context_sh[var_name]
        else:
            None

    def gen_conf(self):
        conf=[]
        conf.append('auto lo')
        conf.append('iface lo inet loopback')
        conf.append('')

        for i in self.ifaces:
            dev=i[0]
            mac=i[1]
            ip_components=self.mac2ip(mac)

            conf.append('auto '+dev)
            conf.append('iface '+dev+' inet static')
            conf.append('  address '+self.get_ip(dev, ip_components))
            conf.append('  network '+self.get_network(dev, ip_components))
            conf.append('  netmask '+self.get_mask(dev, ip_components))

            gateway=self.get_gateway(dev, ip_components)
            if gateway:
                conf.append('  gateway '+gateway)

            conf.append('')

        return "\n".join(conf)

    def gen_dns(self):
        dnss=[]

        if 'dns' in self.context_sh:
            dnss.append('nameserver '+self.context_sh['dns'])

        keys=[d for d in self.context_sh.keys() if re.match('^eth\d+_dns$', d)]

        for k in sorted(keys):
            dnss.append('nameserver '+self.context_sh[k])

        if not dnss:
            return None
        else:
            return "\n".join(dnss)+"\n"


def find_candidate_devs():
    """
    Return a list of devices that may contain the context disk.
    """
    by_fstype = util.find_devs_with("TYPE=iso9660")
    by_label = util.find_devs_with("LABEL=CDROM")

    by_fstype.sort()
    by_label.sort()

    # combine list of items by putting by-label items first
    # followed by fstype items, but with dupes removed
    combined = (by_label + [d for d in by_fstype if d not in by_label])

    return combined


def read_context_disk_dir(source_dir):
    """
    read_context_disk_dir(source_dir):
    read source_dir and return a tuple with metadata dict and user-data
    string populated.  If not a valid dir, raise a NonContextDeviceDir
    """

    found = {}
    for af in CONTEXT_DISK_FILES:
        fn = os.path.join(source_dir, af)
        if os.path.isfile(fn):
            found[af] = fn

    if len(found) == 0:
        raise NonContextDeviceDir("%s: %s" % (source_dir, "no files found"))

    context_sh = {}
    results = {
        'userdata':None,
        'metadata':{},
    }

    if "context.sh" in found:
        try:
            # Note: context.sh is a "shell" script with defined context
            # variables, like: X="Y" . It's ready to use as a shell source
            # e.g.: ". context.sh" and as a shell script it can also reference
            # to already defined shell variables. So to have same context var.
            # values as we can have in custom shell script, we use bash itself
            # to read context.sh and dump variables in easily parsable way.
            #
            # normalized variables dump format (get by cmd "set"):
            # 1. simple single word assignment ........ X=Y
            # 2. multiword assignment ................. X='Y Z'
            # 3. assignments with backslash escapes ... X=$'Y\nZ'
            #
            # how context variables are read:
            # 1. list existing ("old") shell variables and store into $VARS
            # 2. read context variables
            # 3. use comm to filter "old" variables from all current
            #    variables and excl. few other vars with grep
            BASH_CMD='VARS=`set | sort -u `;' \
                '. %s/context.sh;' \
                'comm -23 <(set | sort -u) <(echo "$VARS") | egrep -v "^(VARS|PIPESTATUS|_)="'

            (out,err) = util.subp(['bash',
                '--noprofile',
                '--norc',
                '-c',
                BASH_CMD % (source_dir) ])

            for (key,value) in [ l.split('=',1) for l in out.rstrip().split("\n") ]:
                # with backslash escapes
                r=re.match("^\$'(.*)'$",value)
                if r:
                    context_sh[key.lower()]=r.group(1).decode('string_escape')
                else:
                    # multiword values
                    r=re.match("^'(.*)'$",value)
                    if r:
                        context_sh[key.lower()]=r.group(1)
                    else:
                        # simple values
                        context_sh[key.lower()]=value
        except util.ProcessExecutionError, _err:
            LOG.warn("Failed to read context variables: %s" % (_err.message))
        results['metadata']=context_sh
    else:
        raise NonContextDeviceDir("Missing context.sh")

    # process single or multiple SSH keys
    ssh_key_var=None

    if "ssh_key" in context_sh:
        ssh_key_var="ssh_key"
    elif "ssh_public_key" in context_sh:
        ssh_key_var="ssh_public_key"

    if ssh_key_var:
        lines = context_sh.get(ssh_key_var).splitlines()
        results['metadata']['public-keys'] = [l for l in lines
            if len(l) and not l.startswith("#")]

    # custom hostname
    if 'hostname' in context_sh:
        results['metadata']['local-hostname'] = context_sh['hostname']
    elif 'public_ip'in context_sh:
        results['metadata']['local-hostname'] = context_sh['public_ip']
    elif 'eth0_ip' in context_sh:
        results['metadata']['local-hostname'] = context_sh['eth0_ip']

    # raw user data
    if "user_data" in context_sh:
        results['userdata'] = context_sh["user_data"]
    elif "userdata" in context_sh:
        results['userdata'] = context_sh["userdata"]

    (out, err) = util.subp(['/sbin/ifconfig', '-a'])
    net=OpenNebulaNetwork(out, context_sh)
    results['network-interfaces']=net.gen_conf()

    dns=net.gen_dns()
    if dns:
        results['dns']=dns

    return results


# Used to match classes to dependencies
datasources = [
    (DataSourceOpenNebula, (sources.DEP_FILESYSTEM, )),
    (DataSourceOpenNebulaNet, (sources.DEP_FILESYSTEM, sources.DEP_NETWORK)),
]


# Return a list of data sources that match this set of dependencies
def get_datasource_list(depends):
    return sources.list_from_depends(depends, datasources)
