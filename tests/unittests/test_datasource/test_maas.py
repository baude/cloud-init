import os
from copy import copy

from cloudinit import url_helper
from cloudinit.sources import DataSourceMAAS

from mocker import MockerTestCase


class TestMAASDataSource(MockerTestCase):

    def setUp(self):
        super(TestMAASDataSource, self).setUp()
        # Make a temp directoy for tests to use.
        self.tmp = self.makeDir()

    def test_seed_dir_valid(self):
        """Verify a valid seeddir is read as such"""

        data = {'instance-id': 'i-valid01',
            'local-hostname': 'valid01-hostname',
            'user-data': 'valid01-userdata',
            'public-keys': 'ssh-rsa AAAAB3Nz...aC1yc2E= keyname'}

        my_d = os.path.join(self.tmp, "valid")
        populate_dir(my_d, data)

        (userdata, metadata) = DataSourceMAAS.read_maas_seed_dir(my_d)

        self.assertEqual(userdata, data['user-data'])
        for key in ('instance-id', 'local-hostname'):
            self.assertEqual(data[key], metadata[key])

        # verify that 'userdata' is not returned as part of the metadata
        self.assertFalse(('user-data' in metadata))

    def test_seed_dir_valid_extra(self):
        """Verify extra files do not affect seed_dir validity """

        data = {'instance-id': 'i-valid-extra',
            'local-hostname': 'valid-extra-hostname',
            'user-data': 'valid-extra-userdata', 'foo': 'bar'}

        my_d = os.path.join(self.tmp, "valid_extra")
        populate_dir(my_d, data)

        (userdata, metadata) = DataSourceMAAS.read_maas_seed_dir(my_d)

        self.assertEqual(userdata, data['user-data'])
        for key in ('instance-id', 'local-hostname'):
            self.assertEqual(data[key], metadata[key])

        # additional files should not just appear as keys in metadata atm
        self.assertFalse(('foo' in metadata))

    def test_seed_dir_invalid(self):
        """Verify that invalid seed_dir raises MAASSeedDirMalformed"""

        valid = {'instance-id': 'i-instanceid',
            'local-hostname': 'test-hostname', 'user-data': ''}

        my_based = os.path.join(self.tmp, "valid_extra")

        # missing 'userdata' file
        my_d = "%s-01" % my_based
        invalid_data = copy(valid)
        del invalid_data['local-hostname']
        populate_dir(my_d, invalid_data)
        self.assertRaises(DataSourceMAAS.MAASSeedDirMalformed,
                          DataSourceMAAS.read_maas_seed_dir, my_d)

        # missing 'instance-id'
        my_d = "%s-02" % my_based
        invalid_data = copy(valid)
        del invalid_data['instance-id']
        populate_dir(my_d, invalid_data)
        self.assertRaises(DataSourceMAAS.MAASSeedDirMalformed,
                          DataSourceMAAS.read_maas_seed_dir, my_d)

    def test_seed_dir_none(self):
        """Verify that empty seed_dir raises MAASSeedDirNone"""

        my_d = os.path.join(self.tmp, "valid_empty")
        self.assertRaises(DataSourceMAAS.MAASSeedDirNone,
                          DataSourceMAAS.read_maas_seed_dir, my_d)

    def test_seed_dir_missing(self):
        """Verify that missing seed_dir raises MAASSeedDirNone"""
        self.assertRaises(DataSourceMAAS.MAASSeedDirNone, 
            DataSourceMAAS.read_maas_seed_dir,
            os.path.join(self.tmp, "nonexistantdirectory"))

    def test_seed_url_valid(self):
        """Verify that valid seed_url is read as such"""
        valid = {'meta-data/instance-id': 'i-instanceid',
            'meta-data/local-hostname': 'test-hostname',
            'meta-data/public-keys': 'test-hostname',
            'user-data': 'foodata'}
        valid_order = [
            'meta-data/local-hostname',
            'meta-data/instance-id',
            'meta-data/public-keys',
            'user-data',
        ]
        my_seed = "http://example.com/xmeta"
        my_ver = "1999-99-99"
        my_headers = {'header1': 'value1', 'header2': 'value2'}

        def my_headers_cb(url):
            return my_headers

        mock_request = self.mocker.replace(url_helper.readurl,
            passthrough=False)

        for key in valid_order:
            url = "%s/%s/%s" % (my_seed, my_ver, key)
            mock_request(url, headers=my_headers, timeout=None)
            resp = valid.get(key)
            self.mocker.result(url_helper.UrlResponse(200, resp))
        self.mocker.replay()

        (userdata, metadata) = DataSourceMAAS.read_maas_seed_url(my_seed,
            header_cb=my_headers_cb, version=my_ver)

        self.assertEqual("foodata", userdata)
        self.assertEqual(metadata['instance-id'],
            valid['meta-data/instance-id'])
        self.assertEqual(metadata['local-hostname'],
            valid['meta-data/local-hostname'])

    def test_seed_url_invalid(self):
        """Verify that invalid seed_url raises MAASSeedDirMalformed"""
        pass

    def test_seed_url_missing(self):
        """Verify seed_url with no found entries raises MAASSeedDirNone"""
        pass


def populate_dir(seed_dir, files):
    os.mkdir(seed_dir)
    for (name, content) in files.iteritems():
        with open(os.path.join(seed_dir, name), "w") as fp:
            fp.write(content)
            fp.close()

# vi: ts=4 expandtab
