# vi: ts=4 expandtab
#
#    Distutils magic for ec2-init
#
#    Copyright (C) 2009 Canonical Ltd.
#    Copyright (C) 2012 Yahoo! Inc.
#
#    Author: Soren Hansen <soren@canonical.com>
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

from glob import glob

import os
import re

import setuptools
from setuptools.command.install import install

from distutils.command.install_data import install_data
from distutils.errors import DistutilsArgError

import subprocess


def is_f(p):
    return os.path.isfile(p)


DAEMON_FILES = {
    'initd': filter((lambda x: is_f(x)
                     and x.find('local') == -1), glob('initd/*')),
    'initd-local': filter((lambda x: is_f(x)
                     and not x.endswith('cloud-init')), glob('initd/*')),
    'systemd': filter((lambda x: is_f(x)), glob('systemd/*')),
    'upstart': filter((lambda x: is_f(x)
                     and x.find('local') == -1
                     and x.find('nonet') == -1), glob('upstart/*')),
    'upstart-nonet': filter((lambda x: is_f(x)
                        and x.find('local') == -1
                        and not x.endswith('cloud-init.conf')), glob('upstart/*')),
    'upstart-local': filter((lambda x: is_f(x)
                        and x.find('nonet') == -1
                        and not x.endswith('cloud-init.conf')), glob('upstart/*')),
}
DAEMON_ROOTS = {
    'initd': '/etc/rc.d/init.d',
    'initd-local': '/etc/rc.d/init.d',
    'systemd': '/etc/systemd/system/',
    'upstart': '/etc/init/',
    'upstart-nonet': '/etc/init/',
    'upstart-local': '/etc/init/',
}
DAEMON_TYPES = sorted(list(DAEMON_ROOTS.keys()))


def tiny_p(cmd, capture=True):
    # Darn python 2.6 doesn't have check_output (argggg)
    stdout = subprocess.PIPE
    stderr = subprocess.PIPE
    if not capture:
        stdout = None
        stderr = None
    sp = subprocess.Popen(cmd, stdout=stdout,
                    stderr=stderr, stdin=None)
    (out, err) = sp.communicate()
    if sp.returncode not in [0]:
        raise RuntimeError("Failed running %s [rc=%s] (%s, %s)" 
                            % (cmd, sp.returncode, out, err))
    return (out, err)


def get_version():
    cmd = ['tools/read-version']
    (ver, _e) = tiny_p(cmd)
    return ver.strip()


def read_requires():
    cmd = ['tools/read-dependencies']
    (deps, _e) = tiny_p(cmd)
    return deps.splitlines()


# TODO: Is there a better way to do this??
class DaemonInstallData(install):
    user_options = install.user_options + [
        # This will magically show up in member variable 'daemon_type'
        ('daemon-type=', None,
            ('daemon type to configure (%s) [default: None]') %
                (", ".join(DAEMON_TYPES))
        ),
    ]

    def initialize_options(self):
        install.initialize_options(self)
        self.daemon_type = None

    def finalize_options(self):
        install.finalize_options(self)
        if self.daemon_type and self.daemon_type not in DAEMON_TYPES:
                raise DistutilsArgError(
                    ("You must specify one of (%s) when"
                     " specifying a daemon type!") % (", ".join(DAEMON_TYPES))
                )
        elif self.daemon_type:
            self.distribution.data_files.append((DAEMON_ROOTS[self.daemon_type], 
                                                 DAEMON_FILES[self.daemon_type]))
            # Force that command to reinitalize (with new file list)
            self.distribution.reinitialize_command('install_data', True)


setuptools.setup(name='cloud-init',
      version=get_version(),
      description='EC2 initialisation magic',
      author='Scott Moser',
      author_email='scott.moser@canonical.com',
      url='http://launchpad.net/cloud-init/',
      packages=setuptools.find_packages(exclude=['tests']),
      scripts=['bin/cloud-init',
               'tools/cloud-init-per',
               ],
      license='GPLv3',
      data_files=[('/etc/cloud', glob('config/*.cfg')),
                  ('/etc/cloud/cloud.cfg.d', glob('config/cloud.cfg.d/*')),
                  ('/etc/cloud/templates', glob('templates/*')),
                  ('/usr/share/cloud-init', []),
                  ('/usr/lib/cloud-init',
                    ['tools/uncloud-init', 'tools/write-ssh-key-fingerprints']),
                  ('/usr/share/doc/cloud-init', filter(is_f, glob('doc/*'))),
                  ('/usr/share/doc/cloud-init/examples', filter(is_f, glob('doc/examples/*'))),
                  ('/usr/share/doc/cloud-init/examples/seed', filter(is_f, glob('doc/examples/seed/*'))),
                  ],
      install_requires=read_requires(),
      cmdclass = {
          # Use a subclass for install that handles
          # adding on the right daemon configuration files
          'install': DaemonInstallData,
      },
      )
