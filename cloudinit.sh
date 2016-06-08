#!/bin/bash
# 
# Writes DHCP lease information into the cloud-init data
# directory.

MDFILE=/var/lib/cloud/data/dhcpoptions

cloudinit_config() {
    if [ ! -d $(dirname $MDFILE) ]; then
        touch /var/lib/cloud/exists
        mkdir -p $(dirname $MDFILE)
    fi
    if [ -f $MDFILE ]; then
        rm -f $MDFILE
    fi
    env | grep '^new_\|^DHCP4_' > $MDFILE

}

cloudinit_restore() {
    if [ -f $MDFILE ]; then
        rm -f $MDFILE
    fi
}
