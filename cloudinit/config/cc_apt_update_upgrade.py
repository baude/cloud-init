# vi: ts=4 expandtab
#
#    Copyright (C) 2009-2010 Canonical Ltd.
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

import glob
import os
import time

from cloudinit import templater
from cloudinit import util

distros = ['ubuntu', 'debian']

PROXY_TPL = "Acquire::HTTP::Proxy \"%s\";\n"
PROXY_FN = "/etc/apt/apt.conf.d/95cloud-init-proxy"

# A temporary shell program to get a given gpg key
# from a given keyserver
EXPORT_GPG_KEYID = """
    k=${1} ks=${2};
    exec 2>/dev/null
    [ -n "$k" ] || exit 1;
    armour=$(gpg --list-keys --armour "${k}")
    if [ -z "${armour}" ]; then
       gpg --keyserver ${ks} --recv $k >/dev/null &&
          armour=$(gpg --export --armour "${k}") &&
          gpg --batch --yes --delete-keys "${k}"
    fi
    [ -n "${armour}" ] && echo "${armour}"
"""


def handle(name, cfg, cloud, log, _args):
    update = util.get_cfg_option_bool(cfg, 'apt_update', False)
    upgrade = util.get_cfg_option_bool(cfg, 'apt_upgrade', False)

    release = get_release()
    mirrors = find_apt_mirror_info(cloud, cfg)
    if not mirrors or "primary" not in mirrors:
        log.debug(("Skipping module named %s,"
                   " no package 'mirror' located"), name)
        return

    # backwards compatibility
    mirror = mirrors["primary"]
    mirrors["mirror"] = mirror

    log.debug("mirror info: %s" % mirrors)

    if not util.get_cfg_option_bool(cfg,
                                    'apt_preserve_sources_list', False):
        generate_sources_list(release, mirrors, cloud, log)
        old_mirrors = cfg.get('apt_old_mirrors',
                              {"primary": "archive.ubuntu.com/ubuntu",
                               "security": "security.ubuntu.com/ubuntu"})
        rename_apt_lists(old_mirrors, mirrors)

    # Set up any apt proxy
    proxy = cfg.get("apt_proxy", None)
    proxy_filename = PROXY_FN
    if proxy:
        try:
            # See man 'apt.conf'
            contents = PROXY_TPL % (proxy)
            util.write_file(cloud.paths.join(False, proxy_filename),
                            contents)
        except Exception as e:
            util.logexc(log, "Failed to write proxy to %s", proxy_filename)
    elif os.path.isfile(proxy_filename):
        util.del_file(proxy_filename)

    # Process 'apt_sources'
    if 'apt_sources' in cfg:
        params = mirrors
        params['RELEASE'] = release
        params['MIRROR'] = mirror
        errors = add_sources(cloud, cfg['apt_sources'], params)
        for e in errors:
            log.warn("Source Error: %s", ':'.join(e))

    dconf_sel = util.get_cfg_option_str(cfg, 'debconf_selections', False)
    if dconf_sel:
        log.debug("setting debconf selections per cloud config")
        try:
            util.subp(('debconf-set-selections', '-'), dconf_sel)
        except:
            util.logexc(log, "Failed to run debconf-set-selections")

    pkglist = util.get_cfg_option_list(cfg, 'packages', [])

    errors = []
    if update or len(pkglist) or upgrade:
        try:
            cloud.distro.update_package_sources()
        except Exception as e:
            util.logexc(log, "Package update failed")
            errors.append(e)

    if upgrade:
        try:
            cloud.distro.package_command("upgrade")
        except Exception as e:
            util.logexc(log, "Package upgrade failed")
            errors.append(e)

    if len(pkglist):
        try:
            cloud.distro.install_packages(pkglist)
        except Exception as e:
            util.logexc(log, "Failed to install packages: %s ", pkglist)
            errors.append(e)

    # kernel and openssl (possibly some other packages)
    # write a file /var/run/reboot-required after upgrading.
    # if that file exists and configured, then just stop right now and reboot
    # TODO(smoser): handle this less voilently
    reboot_file = "/var/run/reboot-required"
    if ((upgrade or pkglist) and cfg.get("apt_reboot_if_required", False) and
         os.path.isfile(reboot_file)):
        log.warn("rebooting after upgrade or install per %s" % reboot_file)
        time.sleep(1)  # give the warning time to get out
        util.subp(["/sbin/reboot"])
        time.sleep(60)
        log.warn("requested reboot did not happen!")
        errors.append(Exception("requested reboot did not happen!"))

    if len(errors):
        log.warn("%s failed with exceptions, re-raising the last one",
                 len(errors))
        raise errors[-1]


# get gpg keyid from keyserver
def getkeybyid(keyid, keyserver):
    with util.ExtendedTemporaryFile(suffix='.sh') as fh:
        fh.write(EXPORT_GPG_KEYID)
        fh.flush()
        cmd = ['/bin/sh', fh.name, keyid, keyserver]
        (stdout, _stderr) = util.subp(cmd)
        return stdout.strip()


def mirror2lists_fileprefix(mirror):
    string = mirror
    # take off http:// or ftp://
    if string.endswith("/"):
        string = string[0:-1]
    pos = string.find("://")
    if pos >= 0:
        string = string[pos + 3:]
    string = string.replace("/", "_")
    return string


def rename_apt_lists(old_mirrors, new_mirrors, lists_d="/var/lib/apt/lists"):
    for (name, omirror) in old_mirrors.iteritems():
        nmirror = new_mirrors.get(name)
        if not nmirror:
            continue
        oprefix = os.path.join(lists_d, mirror2lists_fileprefix(omirror))
        nprefix = os.path.join(lists_d, mirror2lists_fileprefix(nmirror))
        if oprefix == nprefix:
            continue
        olen = len(oprefix)
        for filename in glob.glob("%s_*" % oprefix):
            util.rename(filename, "%s%s" % (nprefix, filename[olen:]))


def get_release():
    (stdout, _stderr) = util.subp(['lsb_release', '-cs'])
    return stdout.strip()


def generate_sources_list(codename, mirrors, cloud, log):
    template_fn = cloud.get_template_filename('sources.list')
    if not template_fn:
        log.warn("No template found, not rendering /etc/apt/sources.list")
        return

    params = {'codename': codename}
    for k in mirrors:
        params[k] = mirrors[k]
    out_fn = cloud.paths.join(False, '/etc/apt/sources.list')
    templater.render_to_file(template_fn, out_fn, params)


def add_sources(cloud, srclist, template_params=None):
    """
    add entries in /etc/apt/sources.list.d for each abbreviated
    sources.list entry in 'srclist'.  When rendering template, also
    include the values in dictionary searchList
    """
    if template_params is None:
        template_params = {}

    errorlist = []
    for ent in srclist:
        if 'source' not in ent:
            errorlist.append(["", "missing source"])
            continue

        source = ent['source']
        if source.startswith("ppa:"):
            try:
                util.subp(["add-apt-repository", source])
            except:
                errorlist.append([source, "add-apt-repository failed"])
            continue

        source = templater.render_string(source, template_params)

        if 'filename' not in ent:
            ent['filename'] = 'cloud_config_sources.list'

        if not ent['filename'].startswith("/"):
            ent['filename'] = os.path.join("/etc/apt/sources.list.d/",
                                           ent['filename'])

        if ('keyid' in ent and 'key' not in ent):
            ks = "keyserver.ubuntu.com"
            if 'keyserver' in ent:
                ks = ent['keyserver']
            try:
                ent['key'] = getkeybyid(ent['keyid'], ks)
            except:
                errorlist.append([source, "failed to get key from %s" % ks])
                continue

        if 'key' in ent:
            try:
                util.subp(('apt-key', 'add', '-'), ent['key'])
            except:
                errorlist.append([source, "failed add key"])

        try:
            contents = "%s\n" % (source)
            util.write_file(cloud.paths.join(False, ent['filename']),
                            contents, omode="ab")
        except:
            errorlist.append([source,
                             "failed write to file %s" % ent['filename']])

    return errorlist


def find_apt_mirror_info(cloud, cfg):
    """find an apt_mirror given the cloud and cfg provided."""

    mirror = None

    # this is less preferred way of specifying mirror preferred would be to
    # use the distro's search or package_mirror.
    mirror = cfg.get("apt_mirror", None)

    search = cfg.get("apt_mirror_search", None)
    if not mirror and search:
        mirror = util.search_for_mirror(search)

    if (not mirror and
        util.get_cfg_option_bool(cfg, "apt_mirror_search_dns", False)):
        mydom = ""
        doms = []

        # if we have a fqdn, then search its domain portion first
        (_hostname, fqdn) = util.get_hostname_fqdn(cfg, cloud)
        mydom = ".".join(fqdn.split(".")[1:])
        if mydom:
            doms.append(".%s" % mydom)

        doms.extend((".localdomain", "",))

        mirror_list = []
        distro = cloud.distro.name
        mirrorfmt = "http://%s-mirror%s/%s" % (distro, "%s", distro)
        for post in doms:
            mirror_list.append(mirrorfmt % (post))

        mirror = util.search_for_mirror(mirror_list)

    mirror_info = cloud.datasource.get_package_mirror_info()

    # this is a bit strange.
    # if mirror is set, then one of the legacy options above set it
    # but they do not cover security. so we need to get that from
    # get_package_mirror_info
    if mirror:
        mirror_info.update({'primary': mirror})

    return mirror_info
