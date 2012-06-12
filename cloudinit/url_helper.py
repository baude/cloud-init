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

from contextlib import closing

import errno
import socket
import time
import urllib
import urllib2

from cloudinit import log as logging

LOG = logging.getLogger(__name__)


def ok_http_code(st):
    return st in xrange(200, 400)


def readurl(url, data=None, timeout=None,
            retries=0, sec_between=1, headers=None):

    req_args = {}
    req_args['url'] = url
    if data is not None:
        req_args['data'] = urllib.urlencode(data)
    if headers is not None:
        req_args['headers'] = dict(headers)
    req = urllib2.Request(**req_args)

    retries = max(retries, 0)
    attempts = retries + 1

    last_excp = Exception("??")
    LOG.info(("Attempting to read from %s with %s attempts"
                " (%s retries) to be performed"), url, attempts, retries)
    open_args = {}
    if timeout is not None:
        open_args['timeout'] = int(timeout)
    for i in range(0, attempts):
        try:
            with closing(urllib2.urlopen(req, **open_args)) as rh:
                content = rh.read()
                status = rh.getcode()
                if status is None:
                    # This seems to happen when files are read...
                    status = 200
                LOG.info("Read from %s (%s, %sb) after %s attempts",
                         url, status, len(content), (i + 1))
                return (content, status)
        except urllib2.HTTPError as e:
            last_excp = e
            LOG.exception("Failed at reading from %s.", url)
        except urllib2.URLError as e:
            # This can be a message string or
            # another exception instance 
            # (socket.error for remote URLs, OSError for local URLs).
            if (isinstance(e.reason, OSError) and
                e.reason.errno == errno.ENOENT):
                last_excp = e.reason
            else:
                last_excp = e
            LOG.exception("Failed at reading from %s", url)
        if i + 1 < attempts:
            LOG.info("Please wait %s seconds while we wait to try again",
                     sec_between)
            time.sleep(sec_between)

    # Didn't work out
    LOG.warn("Failed reading from %s after %s attempts", url, attempts)
    raise last_excp


def wait_for_url(urls, max_wait=None, timeout=None,
                 status_cb=None, headers_cb=None, sleep_time=1):
    """
    urls:      a list of urls to try
    max_wait:  roughly the maximum time to wait before giving up
               The max time is *actually* len(urls)*timeout as each url will
               be tried once and given the timeout provided.
    timeout:   the timeout provided to urllib2.urlopen
    status_cb: call method with string message when a url is not available
    headers_cb: call method with single argument of url to get headers
                for request.

    the idea of this routine is to wait for the EC2 metdata service to
    come up.  On both Eucalyptus and EC2 we have seen the case where
    the instance hit the MD before the MD service was up.  EC2 seems
    to have permenantely fixed this, though.

    In openstack, the metadata service might be painfully slow, and
    unable to avoid hitting a timeout of even up to 10 seconds or more
    (LP: #894279) for a simple GET.

    Offset those needs with the need to not hang forever (and block boot)
    on a system where cloud-init is configured to look for EC2 Metadata
    service but is not going to find one.  It is possible that the instance
    data host (169.254.169.254) may be firewalled off Entirely for a sytem,
    meaning that the connection will block forever unless a timeout is set.
    """
    start_time = time.time()

    def log_status_cb(msg):
        LOG.info(msg)

    if status_cb is None:
        status_cb = log_status_cb

    def timeup(max_wait, start_time):
        return ((max_wait <= 0 or max_wait is None) or
                (time.time() - start_time > max_wait))

    loop_n = 0
    while True:
        sleep_time = int(loop_n / 5) + 1
        for url in urls:
            now = time.time()
            if loop_n != 0:
                if timeup(max_wait, start_time):
                    break
                if timeout and (now + timeout > (start_time + max_wait)):
                    # shorten timeout to not run way over max_time
                    timeout = int((start_time + max_wait) - now)

            reason = ""
            try:
                if headers_cb is not None:
                    headers = headers_cb(url)
                else:
                    headers = {}

                (resp, sc) = readurl(url, headers=headers, timeout=timeout)
                if not resp:
                    reason = "empty response [%s]" % sc
                elif not ok_http_code(sc):
                    reason = "bad status code [%s]" % sc
                else:
                    return url
            except urllib2.HTTPError as e:
                reason = "http error [%s]" % e.code
            except urllib2.URLError as e:
                reason = "url error [%s]" % e.reason
            except socket.timeout as e:
                reason = "socket timeout [%s]" % e
            except Exception as e:
                reason = "unexpected error [%s]" % e

            time_taken = int(time.time() - start_time)
            status_msg = "Calling '%s' failed [%s/%ss]: %s" % (url,
                                                             time_taken,
                                                             max_wait, reason)
            status_cb(status_msg)

        if timeup(max_wait, start_time):
            break

        loop_n = loop_n + 1
        LOG.info("Please wait %s seconds while we wait to try again",
                 sleep_time)
        time.sleep(sleep_time)

    return False
