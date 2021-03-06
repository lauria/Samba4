# Unix SMB/CIFS implementation.
# backend code for provisioning DNS for a Samba4 server
#
# Copyright (C) Kai Blin <kai@samba.org> 2011
# Copyright (C) Amitay Isaacs <amitay@gmail.com> 2011
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

"""DNS-related provisioning"""

import os
import uuid
import shutil
import time
import ldb
from base64 import b64encode
import samba
from samba.ndr import ndr_pack, ndr_unpack
from samba import read_and_sub_file, setup_file
from samba.dcerpc import dnsp, misc, security
from samba.dsdb import (
    DS_DOMAIN_FUNCTION_2000,
    DS_DOMAIN_FUNCTION_2003,
    DS_DOMAIN_FUNCTION_2008,
    DS_DOMAIN_FUNCTION_2008_R2
    )
from base64 import b64encode


def add_ldif(ldb, ldif_file, subst_vars, controls=["relax:0"]):
    ldif_file_path = os.path.join(samba.param.setup_dir(), ldif_file)
    data = read_and_sub_file(ldif_file_path, subst_vars)
    ldb.add_ldif(data, controls)

def modify_ldif(ldb, ldif_file, subst_vars, controls=["relax:0"]):
    ldif_file_path = os.path.join(samba.param.setup_dir(), ldif_file)
    data = read_and_sub_file(ldif_file_path, subst_vars)
    ldb.modify_ldif(data, controls)

def set_security_descriptor(samdb, dn_str, descriptor):
    msg = ldb.Message()
    msg.dn = ldb.Dn(samdb, dn_str)
    msg["nTSecurityDescriptor"] = ldb.MessageElement(descriptor,
            ldb.FLAG_MOD_REPLACE, "nTSecurityDescriptor")
    samdb.modify(msg, controls=["relax:0"])

def setup_ldb(ldb, ldif_path, subst_vars):
    """Import a LDIF a file into a LDB handle, optionally substituting
    variables.

    :note: Either all LDIF data will be added or none (using transactions).

    :param ldb: LDB file to import into.
    :param ldif_path: Path to the LDIF file.
    :param subst_vars: Dictionary with substitution variables.
    """
    assert ldb is not None
    ldb.transaction_start()
    try:
        add_ldif(ldb, ldif_path, subst_vars)
    except Exception:
        ldb.transaction_cancel()
        raise
    else:
        ldb.transaction_commit()

def setup_path(file):
    """Return an absolute path to the provision tempate file specified by file"""
    return os.path.join(samba.param.setup_dir(), file)

def get_domainguid(samdb, domaindn):
    res = samdb.search(base=domaindn, scope=ldb.SCOPE_BASE, attrs=["objectGUID"])
    domainguid =  str(ndr_unpack(misc.GUID, res[0]["objectGUID"][0]))
    return domainguid

def get_ntdsguid(samdb, domaindn):
    configdn = samdb.get_config_basedn()

    res1 = samdb.search(base="OU=Domain Controllers,%s" % domaindn, scope=ldb.SCOPE_ONELEVEL,
                        attrs=["dNSHostName"])

    res2 = samdb.search(expression="serverReference=%s" % res1[0].dn, base=configdn)

    res3 = samdb.search(base="CN=NTDS Settings,%s" % res2[0].dn, scope=ldb.SCOPE_BASE,
                        attrs=["objectGUID"])
    ntdsguid = str(ndr_unpack(misc.GUID, res3[0]["objectGUID"][0]))
    return ntdsguid

def get_dns_partition_descriptor(domainsid):
    sddl = "O:SYG:BAD:AI" \
    "(OA;CIIO;RP;4c164200-20c0-11d0-a768-00aa006e0529;4828cc14-1437-45bc-9b07-ad6f015e5f28;RU)" \
    "(OA;CIIO;RP;4c164200-20c0-11d0-a768-00aa006e0529;bf967aba-0de6-11d0-a285-00aa003049e2;RU)" \
    "(OA;CIIO;RP;5f202010-79a5-11d0-9020-00c04fc2d4cf;4828cc14-1437-45bc-9b07-ad6f015e5f28;RU)" \
    "(OA;CIIO;RP;5f202010-79a5-11d0-9020-00c04fc2d4cf;bf967aba-0de6-11d0-a285-00aa003049e2;RU)" \
    "(OA;CIIO;RP;bc0ac240-79a9-11d0-9020-00c04fc2d4cf;4828cc14-1437-45bc-9b07-ad6f015e5f28;RU)" \
    "(OA;CIIO;RP;bc0ac240-79a9-11d0-9020-00c04fc2d4cf;bf967aba-0de6-11d0-a285-00aa003049e2;RU)" \
    "(OA;CIIO;RP;59ba2f42-79a2-11d0-9020-00c04fc2d3cf;4828cc14-1437-45bc-9b07-ad6f015e5f28;RU)" \
    "(OA;CIIO;RP;59ba2f42-79a2-11d0-9020-00c04fc2d3cf;bf967aba-0de6-11d0-a285-00aa003049e2;RU)" \
    "(OA;CIIO;RP;037088f8-0ae1-11d2-b422-00a0c968f939;4828cc14-1437-45bc-9b07-ad6f015e5f28;RU)" \
    "(OA;CIIO;RP;037088f8-0ae1-11d2-b422-00a0c968f939;bf967aba-0de6-11d0-a285-00aa003049e2;RU)" \
    "(OA;;CR;1131f6aa-9c07-11d1-f79f-00c04fc2dcd2;;ER)" \
    "(OA;CIIO;RP;b7c69e6d-2cc7-11d2-854e-00a0c983f608;bf967a86-0de6-11d0-a285-00aa003049e2;ED)" \
    "(OA;CIIO;RP;b7c69e6d-2cc7-11d2-854e-00a0c983f608;bf967a9c-0de6-11d0-a285-00aa003049e2;ED)" \
    "(OA;CIIO;RP;b7c69e6d-2cc7-11d2-854e-00a0c983f608;bf967aba-0de6-11d0-a285-00aa003049e2;ED)" \
    "(OA;;CR;89e95b76-444d-4c62-991a-0facbeda640c;;BA)" \
    "(OA;;CR;1131f6aa-9c07-11d1-f79f-00c04fc2dcd2;;BA)" \
    "(OA;;CR;1131f6ab-9c07-11d1-f79f-00c04fc2dcd2;;BA)" \
    "(OA;;CR;1131f6ac-9c07-11d1-f79f-00c04fc2dcd2;;BA)" \
    "(OA;;CR;1131f6ad-9c07-11d1-f79f-00c04fc2dcd2;;BA)" \
    "(OA;;CR;1131f6ae-9c07-11d1-f79f-00c04fc2dcd2;;BA)" \
    "(OA;;CR;e2a36dc9-ae17-47c3-b58b-be34c55ba633;;IF)" \
    "(OA;;RP;c7407360-20bf-11d0-a768-00aa006e0529;;RU)" \
    "(OA;;RP;b8119fd0-04f6-4762-ab7a-4986c76b3f9a;;RU)" \
    "(OA;CIIO;RPLCLORC;;4828cc14-1437-45bc-9b07-ad6f015e5f28;RU)" \
    "(OA;CIIO;RPLCLORC;;bf967a9c-0de6-11d0-a285-00aa003049e2;RU)" \
    "(OA;CIIO;RPLCLORC;;bf967aba-0de6-11d0-a285-00aa003049e2;RU)" \
    "(OA;;CR;05c74c5e-4deb-43b4-bd9f-86664c2a7fd5;;AU)" \
    "(OA;;CR;89e95b76-444d-4c62-991a-0facbeda640c;;ED)" \
    "(OA;;CR;ccc2dc7d-a6ad-4a7a-8846-c04e3cc53501;;AU)" \
    "(OA;;CR;280f369c-67c7-438e-ae98-1d46f3c6f541;;AU)" \
    "(OA;;CR;1131f6aa-9c07-11d1-f79f-00c04fc2dcd2;;ED)" \
    "(OA;;CR;1131f6ab-9c07-11d1-f79f-00c04fc2dcd2;;ED)" \
    "(OA;;CR;1131f6ac-9c07-11d1-f79f-00c04fc2dcd2;;ED)" \
    "(OA;;CR;1131f6ad-9c07-11d1-f79f-00c04fc2dcd2;;ED)" \
    "(OA;;CR;1131f6ae-9c07-11d1-f79f-00c04fc2dcd2;;ED)" \
    "(OA;;RP;b8119fd0-04f6-4762-ab7a-4986c76b3f9a;;AU)" \
    "(OA;CIIO;RPWPCR;91e647de-d96f-4b70-9557-d63ff4f3ccd8;;PS)" \
    "(A;;RPWPCRCCLCLORCWOWDSW;;;DA)" \
    "(A;CI;RPWPCRCCDCLCLORCWOWDSDDTSW;;;EA)" \
    "(A;;RPRC;;;RU)" \
    "(A;CI;LC;;;RU)" \
    "(A;CI;RPWPCRCCLCLORCWOWDSDSW;;;BA)" \
    "(A;;RP;;;WD)" \
    "(A;;RPLCLORC;;;ED)" \
    "(A;;RPLCLORC;;;AU)" \
    "(A;;RPWPCRCCDCLCLORCWOWDSDDTSW;;;SY)" \
    "S:AI" \
    "(OU;CISA;WP;f30e3bbe-9ff0-11d1-b603-0000f80367c1;bf967aa5-0de6-11d0-a285-00aa003049e2;WD)" \
    "(OU;CISA;WP;f30e3bbf-9ff0-11d1-b603-0000f80367c1;bf967aa5-0de6-11d0-a285-00aa003049e2;WD)" \
    "(AU;SA;CR;;;DU)(AU;SA;CR;;;BA)(AU;SA;WPWOWD;;;WD)"
    sec = security.descriptor.from_sddl(sddl, domainsid)
    return ndr_pack(sec)

class ARecord(dnsp.DnssrvRpcRecord):
    def __init__(self, ip_addr, serial=1, ttl=900, rank=dnsp.DNS_RANK_ZONE):
        super(ARecord, self).__init__()
        self.wType = dnsp.DNS_TYPE_A
        self.rank = rank
        self.dwSerial = serial
        self.dwTtlSeconds = ttl
        self.data = ip_addr

class AAAARecord(dnsp.DnssrvRpcRecord):
    def __init__(self, ip6_addr, serial=1, ttl=900, rank=dnsp.DNS_RANK_ZONE):
        super(AAAARecord, self).__init__()
        self.wType = dnsp.DNS_TYPE_AAAA
        self.rank = rank
        self.dwSerial = serial
        self.dwTtlSeconds = ttl
        self.data = ip6_addr

class CNameRecord(dnsp.DnssrvRpcRecord):
    def __init__(self, cname, serial=1, ttl=900, rank=dnsp.DNS_RANK_ZONE):
        super(CNameRecord, self).__init__()
        self.wType = dnsp.DNS_TYPE_CNAME
        self.rank = rank
        self.dwSerial = serial
        self.dwTtlSeconds = ttl
        self.data = cname

class NSRecord(dnsp.DnssrvRpcRecord):
    def __init__(self, dns_server, serial=1, ttl=900, rank=dnsp.DNS_RANK_ZONE):
        super(NSRecord, self).__init__()
        self.wType = dnsp.DNS_TYPE_NS
        self.rank = rank
        self.dwSerial = serial
        self.dwTtlSeconds = ttl
        self.data = dns_server

class SOARecord(dnsp.DnssrvRpcRecord):
    def __init__(self, mname, rname, serial=1, refresh=900, retry=600,
                 expire=86400, minimum=3600, ttl=3600, rank=dnsp.DNS_RANK_ZONE):
        super(SOARecord, self).__init__()
        self.wType = dnsp.DNS_TYPE_SOA
        self.rank = rank
        self.dwSerial = serial
        self.dwTtlSeconds = ttl
        soa = dnsp.soa()
        soa.serial = serial
        soa.refresh = refresh
        soa.retry = retry
        soa.expire = expire
        soa.mname = mname
        soa.rname = rname
        self.data = soa

class SRVRecord(dnsp.DnssrvRpcRecord):
    def __init__(self, target, port, priority=0, weight=100, serial=1, ttl=900,
                rank=dnsp.DNS_RANK_ZONE):
        super(SRVRecord, self).__init__()
        self.wType = dnsp.DNS_TYPE_SRV
        self.rank = rank
        self.dwSerial = serial
        self.dwTtlSeconds = ttl
        srv = dnsp.srv()
        srv.nameTarget = target
        srv.wPort = port
        srv.wPriority = priority
        srv.wWeight = weight
        self.data = srv

def setup_dns_partitions(samdb, domainsid, domaindn, forestdn, configdn, serverdn):
    domainzone_dn = "DC=DomainDnsZones,%s" % domaindn
    forestzone_dn = "DC=ForestDnsZones,%s" % forestdn

    add_ldif(samdb, "provision_dnszones_partitions.ldif", {
        "DOMAINZONE_DN": domainzone_dn,
        "FORESTZONE_DN": forestzone_dn,
        })

    descriptor = get_dns_partition_descriptor(domainsid)
    set_security_descriptor(samdb, domainzone_dn, descriptor)
    set_security_descriptor(samdb, forestzone_dn, descriptor)

    domainzone_guid = get_domainguid(samdb, domainzone_dn)
    forestzone_guid = get_domainguid(samdb, forestzone_dn)

    domainzone_guid = str(uuid.uuid4())
    forestzone_guid = str(uuid.uuid4())

    domainzone_dns = ldb.Dn(samdb, domainzone_dn).canonical_ex_str().strip()
    forestzone_dns = ldb.Dn(samdb, forestzone_dn).canonical_ex_str().strip()

    add_ldif(samdb, "provision_dnszones_add.ldif", {
        "DOMAINZONE_DN": domainzone_dn,
        "FORESTZONE_DN": forestzone_dn,
        "DOMAINZONE_GUID": domainzone_guid,
        "FORESTZONE_GUID": forestzone_guid,
        "DOMAINZONE_DNS": domainzone_dns,
        "FORESTZONE_DNS": forestzone_dns,
        "CONFIGDN": configdn,
        "SERVERDN": serverdn,
        })

    modify_ldif(samdb, "provision_dnszones_modify.ldif", {
        "CONFIGDN": configdn,
        "SERVERDN": serverdn,
        "DOMAINZONE_DN": domainzone_dn,
        "FORESTZONE_DN": forestzone_dn,
    })


def add_dns_accounts(samdb, domaindn):
    add_ldif(samdb, "provision_dns_accounts_add.ldif", {
        "DOMAINDN": domaindn,
        })

def add_dns_container(samdb, domaindn, prefix, domainsid):
    # CN=MicrosoftDNS,<PREFIX>,<DOMAINDN>
    sddl = "O:SYG:SYD:AI" \
    "(A;;RPWPCRCCDCLCLORCWOWDSDDTSW;;;DA)" \
    "(A;CI;RPWPCRCCDCLCRCWOWDSDDTSW;;;S-1-5-21-3468611895-2137509179-3280132445-1101)" \
    "(A;;RPWPCRCCDCLCLORCWOWDSDDTSW;;;SY)" \
    "(A;CI;RPWPCRCCDCLCRCWOWDSDDTSW;;;ED)" \
    "S:AI"
    sec = security.descriptor.from_sddl(sddl, domainsid)
    msg = ldb.Message(ldb.Dn(samdb, "CN=MicrosoftDNS,%s,%s" % (prefix, domaindn)))
    msg["objectClass"] = ["top", "container"]
    msg["nTSecurityDescriptor"] = ndr_pack(sec)
    samdb.add(msg)

def add_rootservers(samdb, domaindn, prefix):
    rootservers = {}
    rootservers["a.root-servers.net"] = "198.41.0.4"
    rootservers["b.root-servers.net"] = "192.228.79.201"
    rootservers["c.root-servers.net"] = "192.33.4.12"
    rootservers["d.root-servers.net"] = "128.8.10.90"
    rootservers["e.root-servers.net"] = "192.203.230.10"
    rootservers["f.root-servers.net"] = "192.5.5.241"
    rootservers["g.root-servers.net"] = "192.112.36.4"
    rootservers["h.root-servers.net"] = "128.63.2.53"
    rootservers["i.root-servers.net"] = "192.36.148.17"
    rootservers["j.root-servers.net"] = "192.58.128.30"
    rootservers["k.root-servers.net"] = "193.0.14.129"
    rootservers["l.root-servers.net"] = "199.7.83.42"
    rootservers["m.root-servers.net"] = "202.12.27.33"

    rootservers_v6 = {}
    rootservers_v6["a.root-servers.net"] = "2001:503:ba3e::2:30"
    rootservers_v6["f.root-servers.net"] = "2001:500:2f::f"
    rootservers_v6["h.root-servers.net"] = "2001:500:1::803f:235"
    rootservers_v6["j.root-servers.net"] = "2001:503:c27::2:30"
    rootservers_v6["k.root-servers.net"] = "2001:7fd::1"
    rootservers_v6["m.root-servers.net"] = "2001:dc3::35"

    container_dn = "DC=RootDNSServers,CN=MicrosoftDNS,%s,%s" % (prefix, domaindn)

    # Add DC=RootDNSServers,CN=MicrosoftDNS,<PREFIX>,<DOMAINDN>
    msg = ldb.Message(ldb.Dn(samdb, container_dn))
    msg["objectClass"] = ["top", "dnsZone"]
    msg["cn"] = ldb.MessageElement("Zone", ldb.FLAG_MOD_ADD, "cn")
    samdb.add(msg)

    # Add DC=@,DC=RootDNSServers,CN=MicrosoftDNS,<PREFIX>,<DOMAINDN>
    record = []
    for rserver in rootservers:
        record.append(ndr_pack(NSRecord(rserver, serial=0, ttl=0, rank=dnsp.DNS_RANK_ROOT_HINT)))

    msg = ldb.Message(ldb.Dn(samdb, "DC=@,%s" % container_dn))
    msg["objectClass"] = ["top", "dnsNode"]
    msg["dnsRecord"] = ldb.MessageElement(record, ldb.FLAG_MOD_ADD, "dnsRecord")
    samdb.add(msg)

    # Add DC=<rootserver>,DC=RootDNSServers,CN=MicrosoftDNS,<PREFIX>,<DOMAINDN>
    for rserver in rootservers:
        record = [ndr_pack(ARecord(rootservers[rserver], serial=0, ttl=0, rank=dnsp.DNS_RANK_ROOT_HINT))]
        # Add AAAA record as well (How does W2K* add IPv6 records?)
        #if rserver in rootservers_v6:
        #    record.append(ndr_pack(AAAARecord(rootservers_v6[rserver], serial=0, ttl=0)))
        msg = ldb.Message(ldb.Dn(samdb, "DC=%s,%s" % (rserver, container_dn)))
        msg["objectClass"] = ["top", "dnsNode"]
        msg["dnsRecord"] = ldb.MessageElement(record, ldb.FLAG_MOD_ADD, "dnsRecord")
        samdb.add(msg)

def add_at_record(samdb, container_dn, prefix, hostname, dnsdomain, hostip, hostip6):

    fqdn_hostname = "%s.%s" % (hostname, dnsdomain)

    at_records = []

    # SOA record
    at_soa_record = SOARecord(fqdn_hostname, "hostmaster.%s" % dnsdomain)
    at_records.append(ndr_pack(at_soa_record))

    # NS record
    at_ns_record = NSRecord(fqdn_hostname)
    at_records.append(ndr_pack(at_ns_record))

    if hostip is not None:
        # A record
        at_a_record = ARecord(hostip)
        at_records.append(ndr_pack(at_a_record))

    if hostip6 is not None:
        # AAAA record
        at_aaaa_record = AAAARecord(hostip6)
        at_records.append(ndr_pack(at_aaaa_record))

    msg = ldb.Message(ldb.Dn(samdb, "DC=@,%s" % container_dn))
    msg["objectClass"] = ["top", "dnsNode"]
    msg["dnsRecord"] = ldb.MessageElement(at_records, ldb.FLAG_MOD_ADD, "dnsRecord")
    samdb.add(msg)

def add_srv_record(samdb, container_dn, prefix, host, port):
    srv_record = SRVRecord(host, port)
    msg = ldb.Message(ldb.Dn(samdb, "%s,%s" % (prefix, container_dn)))
    msg["objectClass"] = ["top", "dnsNode"]
    msg["dnsRecord"] = ldb.MessageElement(ndr_pack(srv_record), ldb.FLAG_MOD_ADD, "dnsRecord")
    samdb.add(msg)

def add_ns_record(samdb, container_dn, prefix, host):
    ns_record = NSRecord(host)
    msg = ldb.Message(ldb.Dn(samdb, "%s,%s" % (prefix, container_dn)))
    msg["objectClass"] = ["top", "dnsNode"]
    msg["dnsRecord"] = ldb.MessageElement(ndr_pack(ns_record), ldb.FLAG_MOD_ADD, "dnsRecord")
    samdb.add(msg)

def add_ns_glue_record(samdb, container_dn, prefix, host):
    ns_record = NSRecord(host, rank=dnsp.DNS_RANK_NS_GLUE)
    msg = ldb.Message(ldb.Dn(samdb, "%s,%s" % (prefix, container_dn)))
    msg["objectClass"] = ["top", "dnsNode"]
    msg["dnsRecord"] = ldb.MessageElement(ndr_pack(ns_record), ldb.FLAG_MOD_ADD, "dnsRecord")
    samdb.add(msg)

def add_cname_record(samdb, container_dn, prefix, host):
    cname_record = CNameRecord(host)
    msg = ldb.Message(ldb.Dn(samdb, "%s,%s" % (prefix, container_dn)))
    msg["objectClass"] = ["top", "dnsNode"]
    msg["dnsRecord"] = ldb.MessageElement(ndr_pack(cname_record), ldb.FLAG_MOD_ADD, "dnsRecord")
    samdb.add(msg)

def add_host_record(samdb, container_dn, prefix, hostip, hostip6):
    host_records = []
    if hostip:
        a_record = ARecord(hostip)
        host_records.append(ndr_pack(a_record))
    if hostip6:
        aaaa_record = AAAARecord(hostip6)
        host_records.append(ndr_pack(aaaa_record))
    if host_records:
        msg = ldb.Message(ldb.Dn(samdb, "%s,%s" % (prefix, container_dn)))
        msg["objectClass"] = ["top", "dnsNode"]
        msg["dnsRecord"] = ldb.MessageElement(host_records, ldb.FLAG_MOD_ADD, "dnsRecord")
        samdb.add(msg)

def add_domain_record(samdb, domaindn, prefix, dnsdomain, domainsid):
    # DC=<DNSDOMAIN>,CN=MicrosoftDNS,<PREFIX>,<DOMAINDN>
    sddl = "O:SYG:BAD:AI" \
    "(D;CI;RPWPCRCCDCLCLORCWOWDSDDTSW;;;S-1-5-21-3468611895-2137509179-3280132445-1103)" \
    "(A;;RPWPCRCCDCLCLORCWOWDSDDTSW;;;DA)" \
    "(A;;CC;;;AU)" \
    "(A;;RPLCLORC;;;WD)" \
    "(A;;RPWPCRCCDCLCLORCWOWDSDDTSW;;;SY)" \
    "(A;CI;RPWPCRCCDCLCRCWOWDSDDTSW;;;ED)" \
    "(A;CIID;RPWPCRCCDCLCRCWOWDSDDTSW;;;S-1-5-21-3468611895-2137509179-3280132445-1101)" \
    "(A;CIID;RPWPCRCCDCLCRCWOWDSDDTSW;;;ED)" \
    "(OA;CIID;RPWPCR;91e647de-d96f-4b70-9557-d63ff4f3ccd8;;PS)" \
    "(A;CIID;RPWPCRCCDCLCLORCWOWDSDDTSW;;;EA)" \
    "(A;CIID;LC;;;RU)" \
    "(A;CIID;RPWPCRCCLCLORCWOWDSDSW;;;BA)" \
    "S:AI"
    sec = security.descriptor.from_sddl(sddl, domainsid)
    msg = ldb.Message(ldb.Dn(samdb, "DC=%s,CN=MicrosoftDNS,%s,%s" % (dnsdomain, prefix, domaindn)))
    msg["objectClass"] = ["top", "dnsZone"]
    msg["ntSecurityDescriptor"] = ndr_pack(sec)
    samdb.add(msg)

def add_msdcs_record(samdb, forestdn, prefix, dnsforest):
    # DC=_msdcs.<DNSFOREST>,CN=MicrosoftDNS,<PREFIX>,<FORESTDN>
    msg = ldb.Message(ldb.Dn(samdb, "DC=_msdcs.%s,CN=MicrosoftDNS,%s,%s" %
                                    (dnsforest, prefix, forestdn)))
    msg["objectClass"] = ["top", "dnsZone"]
    samdb.add(msg)


def add_dc_domain_records(samdb, domaindn, prefix, site, dnsdomain, hostname, hostip, hostip6):

    fqdn_hostname = "%s.%s" % (hostname, dnsdomain)

    # Set up domain container - DC=<DNSDOMAIN>,CN=MicrosoftDNS,<PREFIX>,<DOMAINDN>
    domain_container_dn = ldb.Dn(samdb, "DC=%s,CN=MicrosoftDNS,%s,%s" %
                                    (dnsdomain, prefix, domaindn))

    # DC=@ record
    add_at_record(samdb, domain_container_dn, "DC=@", hostname, dnsdomain, hostip, hostip6)

    # DC=<HOSTNAME> record
    add_host_record(samdb, domain_container_dn, "DC=%s" % hostname, hostip, hostip6)

    # DC=_kerberos._tcp record
    add_srv_record(samdb, domain_container_dn, "DC=_kerberos._tcp", fqdn_hostname, 88)

    # DC=_kerberos._tcp.<SITENAME>._sites record
    add_srv_record(samdb, domain_container_dn, "DC=_kerberos._tcp.%s._sites" % site,
                    fqdn_hostname, 88)

    # DC=_kerberos._udp record
    add_srv_record(samdb, domain_container_dn, "DC=_kerberos._udp", fqdn_hostname, 88)

    # DC=_kpasswd._tcp record
    add_srv_record(samdb, domain_container_dn, "DC=_kpasswd._tcp", fqdn_hostname, 464)

    # DC=_kpasswd._udp record
    add_srv_record(samdb, domain_container_dn, "DC=_kpasswd._udp", fqdn_hostname, 464)

    # DC=_ldap._tcp record
    add_srv_record(samdb, domain_container_dn, "DC=_ldap._tcp", fqdn_hostname, 389)

    # DC=_ldap._tcp.<SITENAME>._sites record
    add_srv_record(samdb, domain_container_dn, "DC=_ldap._tcp.%s._sites" % site,
                    fqdn_hostname, 389)

    # FIXME: The number of SRV records depend on the various roles this DC has.
    #        _gc and _msdcs records are added if the we are the forest dc and not subdomain dc
    #
    # Assumption: current DC is GC and add all the entries

    # DC=_gc._tcp record
    add_srv_record(samdb, domain_container_dn, "DC=_gc._tcp", fqdn_hostname, 3268)

    # DC=_gc._tcp.<SITENAME>,_sites record
    add_srv_record(samdb, domain_container_dn, "DC=_gc._tcp.%s._sites" % site, fqdn_hostname, 3268)

    # DC=_msdcs record
    add_ns_glue_record(samdb, domain_container_dn, "DC=_msdcs", fqdn_hostname)

    # FIXME: Following entries are added only if DomainDnsZones and ForestDnsZones partitions
    #        are created
    #
    # Assumption: Additional entries won't hurt on os_level = 2000

    # DC=_ldap._tcp.<SITENAME>._sites.DomainDnsZones
    add_srv_record(samdb, domain_container_dn, "DC=_ldap._tcp.%s._sites.DomainDnsZones" % site,
                    fqdn_hostname, 389)

    # DC=_ldap._tcp.<SITENAME>._sites.ForestDnsZones
    add_srv_record(samdb, domain_container_dn, "DC=_ldap._tcp.%s._sites.ForestDnsZones" % site,
                    fqdn_hostname, 389)

    # DC=_ldap._tcp.DomainDnsZones
    add_srv_record(samdb, domain_container_dn, "DC=_ldap._tcp.DomainDnsZones",
                    fqdn_hostname, 389)

    # DC=_ldap._tcp.ForestDnsZones
    add_srv_record(samdb, domain_container_dn, "DC=_ldap._tcp.ForestDnsZones",
                    fqdn_hostname, 389)

    # DC=DomainDnsZones
    add_host_record(samdb, domain_container_dn, "DC=DomainDnsZones", hostip, hostip6)

    # DC=ForestDnsZones
    add_host_record(samdb, domain_container_dn, "DC=ForestDnsZones", hostip, hostip6)


def add_dc_msdcs_records(samdb, forestdn, prefix, site, dnsforest, hostname,
                            hostip, hostip6, domainguid, ntdsguid):

    fqdn_hostname = "%s.%s" % (hostname, dnsforest)

    # Set up forest container - DC=<DNSDOMAIN>,CN=MicrosoftDNS,<PREFIX>,<DOMAINDN>
    forest_container_dn = ldb.Dn(samdb, "DC=_msdcs.%s,CN=MicrosoftDNS,%s,%s" %
                                    (dnsforest, prefix, forestdn))

    # DC=@ record
    add_at_record(samdb, forest_container_dn, "DC=@", hostname, dnsforest, None, None)

    # DC=_kerberos._tcp.dc record
    add_srv_record(samdb, forest_container_dn, "DC=_kerberos._tcp.dc", fqdn_hostname, 88)

    # DC=_kerberos._tcp.<SITENAME>._sites.dc record
    add_srv_record(samdb, forest_container_dn, "DC=_kerberos._tcp.%s._sites.dc" % site,
                    fqdn_hostname, 88)

    # DC=_ldap._tcp.dc record
    add_srv_record(samdb, forest_container_dn, "DC=_ldap._tcp.dc", fqdn_hostname, 389)

    # DC=_ldap._tcp.<SITENAME>._sites.dc record
    add_srv_record(samdb, forest_container_dn, "DC=_ldap._tcp.%s._sites.dc" % site,
                    fqdn_hostname, 389)

    # DC=_ldap._tcp.<SITENAME>._sites.gc record
    add_srv_record(samdb, forest_container_dn, "DC=_ldap._tcp.%s._sites.gc" % site,
                    fqdn_hostname, 3268)

    # DC=_ldap._tcp.gc record
    add_srv_record(samdb, forest_container_dn, "DC=_ldap._tcp.gc", fqdn_hostname, 3268)

    # DC=_ldap._tcp.pdc record
    add_srv_record(samdb, forest_container_dn, "DC=_ldap._tcp.pdc", fqdn_hostname, 389)

    # DC=gc record
    add_host_record(samdb, forest_container_dn, "DC=gc", hostip, hostip6)

    # DC=_ldap._tcp.<DOMAINGUID>.domains record
    add_srv_record(samdb, forest_container_dn, "DC=_ldap._tcp.%s.domains" % domainguid,
                    fqdn_hostname, 389)

    # DC=<NTDSGUID>
    add_cname_record(samdb, forest_container_dn, "DC=%s" % ntdsguid, fqdn_hostname)


def secretsdb_setup_dns(secretsdb, names, private_dir, realm,
                        dnsdomain, dns_keytab_path, dnspass):
    """Add DNS specific bits to a secrets database.

    :param secretsdb: Ldb Handle to the secrets database
    :param names: Names shortcut
    :param machinepass: Machine password
    """
    try:
        os.unlink(os.path.join(private_dir, dns_keytab_path))
    except OSError:
        pass

    setup_ldb(secretsdb, setup_path("secrets_dns.ldif"), {
            "REALM": realm,
            "DNSDOMAIN": dnsdomain,
            "DNS_KEYTAB": dns_keytab_path,
            "DNSPASS_B64": b64encode(dnspass),
            "HOSTNAME": names.hostname,
            "DNSNAME" : '%s.%s' % (
                names.netbiosname.lower(), names.dnsdomain.lower())
            })


def create_dns_dir(logger, paths):
    """Write out a DNS zone file, from the info in the current database.

    :param logger: Logger object
    :param paths: paths object
    """
    dns_dir = os.path.dirname(paths.dns)

    try:
        shutil.rmtree(dns_dir, True)
    except OSError:
        pass

    os.mkdir(dns_dir, 0770)

    if paths.bind_gid is not None:
        try:
            os.chown(dns_dir, -1, paths.bind_gid)
            # chmod needed to cope with umask
            os.chmod(dns_dir, 0770)
        except OSError:
            if not os.environ.has_key('SAMBA_SELFTEST'):
                logger.error("Failed to chown %s to bind gid %u" % (
                    dns_dir, paths.bind_gid))


def create_zone_file(lp, logger, paths, targetdir, dnsdomain,
                     hostip, hostip6, hostname, realm, domainguid,
                     ntdsguid, site):
    """Write out a DNS zone file, from the info in the current database.

    :param paths: paths object
    :param dnsdomain: DNS Domain name
    :param domaindn: DN of the Domain
    :param hostip: Local IPv4 IP
    :param hostip6: Local IPv6 IP
    :param hostname: Local hostname
    :param realm: Realm name
    :param domainguid: GUID of the domain.
    :param ntdsguid: GUID of the hosts nTDSDSA record.
    """
    assert isinstance(domainguid, str)

    if hostip6 is not None:
        hostip6_base_line = "            IN AAAA    " + hostip6
        hostip6_host_line = hostname + "        IN AAAA    " + hostip6
        gc_msdcs_ip6_line = "gc._msdcs               IN AAAA    " + hostip6
    else:
        hostip6_base_line = ""
        hostip6_host_line = ""
        gc_msdcs_ip6_line = ""

    if hostip is not None:
        hostip_base_line = "            IN A    " + hostip
        hostip_host_line = hostname + "        IN A    " + hostip
        gc_msdcs_ip_line = "gc._msdcs               IN A    " + hostip
    else:
        hostip_base_line = ""
        hostip_host_line = ""
        gc_msdcs_ip_line = ""

    # we need to freeze the zone while we update the contents
    if targetdir is None:
        rndc = ' '.join(lp.get("rndc command"))
        os.system(rndc + " freeze " + lp.get("realm"))

    setup_file(setup_path("provision.zone"), paths.dns, {
            "HOSTNAME": hostname,
            "DNSDOMAIN": dnsdomain,
            "REALM": realm,
            "HOSTIP_BASE_LINE": hostip_base_line,
            "HOSTIP_HOST_LINE": hostip_host_line,
            "DOMAINGUID": domainguid,
            "DATESTRING": time.strftime("%Y%m%d%H"),
            "DEFAULTSITE": site,
            "NTDSGUID": ntdsguid,
            "HOSTIP6_BASE_LINE": hostip6_base_line,
            "HOSTIP6_HOST_LINE": hostip6_host_line,
            "GC_MSDCS_IP_LINE": gc_msdcs_ip_line,
            "GC_MSDCS_IP6_LINE": gc_msdcs_ip6_line,
        })

    if paths.bind_gid is not None:
        try:
            os.chown(paths.dns, -1, paths.bind_gid)
            # chmod needed to cope with umask
            os.chmod(paths.dns, 0664)
        except OSError:
            if not os.environ.has_key('SAMBA_SELFTEST'):
                logger.error("Failed to chown %s to bind gid %u" % (
                    paths.dns, paths.bind_gid))

    if targetdir is None:
        os.system(rndc + " unfreeze " + lp.get("realm"))


def create_dns_update_list(lp, logger, paths):
    """Write out a dns_update_list file"""
    # note that we use no variable substitution on this file
    # the substitution is done at runtime by samba_dnsupdate, samba_spnupdate
    setup_file(setup_path("dns_update_list"), paths.dns_update_list, None)
    setup_file(setup_path("spn_update_list"), paths.spn_update_list, None)


def create_named_conf(paths, realm, dnsdomain, dns_backend):
    """Write out a file containing zone statements suitable for inclusion in a
    named.conf file (including GSS-TSIG configuration).

    :param paths: all paths
    :param realm: Realm name
    :param dnsdomain: DNS Domain name
    :param dns_backend: DNS backend type
    :param keytab_name: File name of DNS keytab file
    """

    if dns_backend == "BIND9_FLATFILE":
        setup_file(setup_path("named.conf"), paths.namedconf, {
                    "DNSDOMAIN": dnsdomain,
                    "REALM": realm,
                    "ZONE_FILE": paths.dns,
                    "REALM_WC": "*." + ".".join(realm.split(".")[1:]),
                    "NAMED_CONF": paths.namedconf,
                    "NAMED_CONF_UPDATE": paths.namedconf_update
                    })

        setup_file(setup_path("named.conf.update"), paths.namedconf_update)

    elif dns_backend == "BIND9_DLZ":
        dlz_module_path = os.path.join(samba.param.modules_dir(),
                                        "bind9/dlz_bind9.so")
        setup_file(setup_path("named.conf.dlz"), paths.namedconf, {
                    "NAMED_CONF": paths.namedconf,
                    "BIND9_DLZ_MODULE": dlz_module_path,
                    })



def create_named_txt(path, realm, dnsdomain, dnsname, private_dir,
    keytab_name):
    """Write out a file containing zone statements suitable for inclusion in a
    named.conf file (including GSS-TSIG configuration).

    :param path: Path of the new named.conf file.
    :param realm: Realm name
    :param dnsdomain: DNS Domain name
    :param private_dir: Path to private directory
    :param keytab_name: File name of DNS keytab file
    """
    setup_file(setup_path("named.txt"), path, {
            "DNSDOMAIN": dnsdomain,
            "DNSNAME" : dnsname,
            "REALM": realm,
            "DNS_KEYTAB": keytab_name,
            "DNS_KEYTAB_ABS": os.path.join(private_dir, keytab_name),
            "PRIVATE_DIR": private_dir
        })


def is_valid_dns_backend(dns_backend):
        return dns_backend in ("BIND9_FLATFILE", "BIND9_DLZ", "SAMBA_INTERNAL", "NONE")


def is_valid_os_level(os_level):
    return DS_DOMAIN_FUNCTION_2000 <= os_level <= DS_DOMAIN_FUNCTION_2008_R2


def setup_ad_dns(samdb, secretsdb, domainsid, names, paths, lp, logger, dns_backend,
                 os_level, site, dnspass=None, hostip=None, hostip6=None,
                 targetdir=None):
    """Provision DNS information (assuming GC role)

    :param samdb: LDB object connected to sam.ldb file
    :param secretsdb: LDB object connected to secrets.ldb file
    :param names: Names shortcut
    :param paths: Paths shortcut
    :param lp: Loadparm object
    :param logger: Logger object
    :param dns_backend: Type of DNS backend
    :param os_level: Functional level (treated as os level)
    :param site: Site to create hostnames in
    :param dnspass: Password for bind's DNS account
    :param hostip: IPv4 address
    :param hostip6: IPv6 address
    :param targetdir: Target directory for creating DNS-related files for BIND9
    """

    if not is_valid_dns_backend(dns_backend):
        raise Exception("Invalid dns backend: %r" % dns_backend)

    if not is_valid_os_level(os_level):
        raise Exception("Invalid os level: %r" % os_level)

    if dns_backend is "NONE":
        logger.info("No DNS backend set, not configuring DNS")
        return

    # If dns_backend is BIND9_FLATFILE
    #   Populate only CN=MicrosoftDNS,CN=System,<DOMAINDN>
    #
    # If dns_backend is SAMBA_INTERNAL or BIND9_DLZ
    #   Populate DNS partitions

    # If os_level < 2003 (DS_DOMAIN_FUNCTION_2000)
    #   All dns records are in CN=MicrosoftDNS,CN=System,<DOMAINDN>
    #
    # If os_level >= 2003 (DS_DOMAIN_FUNCTION_2003, DS_DOMAIN_FUNCTION_2008,
    #                        DS_DOMAIN_FUNCTION_2008_R2)
    #   Root server records are in CN=MicrosoftDNS,CN=System,<DOMAINDN>
    #   Domain records are in CN=MicrosoftDNS,CN=System,<DOMAINDN>
    #   Domain records are in CN=MicrosoftDNS,DC=DomainDnsZones,<DOMAINDN>
    #   Forest records are in CN=MicrosoftDNS,DC=ForestDnsZones,<DOMAINDN>

    domaindn = names.domaindn
    forestdn = samdb.get_root_basedn().get_linearized()

    dnsdomain = names.dnsdomain.lower()
    dnsforest = dnsdomain

    hostname = names.netbiosname.lower()

    domainguid = get_domainguid(samdb, domaindn)
    ntdsguid = get_ntdsguid(samdb, domaindn)

    # Add dns accounts (DnsAdmins, DnsUpdateProxy) in domain
    logger.info("Adding DNS accounts")
    add_dns_accounts(samdb, domaindn)

    logger.info("Populating CN=MicrosoftDNS,CN=System,%s" % domaindn)

    # Set up MicrosoftDNS container
    add_dns_container(samdb, domaindn, "CN=System", domainsid)

    # Add root servers
    add_rootservers(samdb, domaindn, "CN=System")

    if os_level == DS_DOMAIN_FUNCTION_2000:

        # Add domain record
        add_domain_record(samdb, domaindn, "CN=System", dnsdomain, domainsid)

        # Add DNS records for a DC in domain
        add_dc_domain_records(samdb, domaindn, "CN=System", site, dnsdomain,
                                hostname, hostip, hostip6)

    elif dns_backend in ("SAMBA_INTERNAL", "BIND9_DLZ") and \
            os_level >= DS_DOMAIN_FUNCTION_2003:

        # Set up additional partitions (DomainDnsZones, ForstDnsZones)
        logger.info("Creating DomainDnsZones and ForestDnsZones partitions")
        setup_dns_partitions(samdb, domainsid, domaindn, forestdn,
                            names.configdn, names.serverdn)

        ##### Set up DC=DomainDnsZones,<DOMAINDN>
        logger.info("Populating DomainDnsZones partition")

        # Set up MicrosoftDNS container
        add_dns_container(samdb, domaindn, "DC=DomainDnsZones", domainsid)

        # Add rootserver records
        add_rootservers(samdb, domaindn, "DC=DomainDnsZones")

        # Add domain record
        add_domain_record(samdb, domaindn, "DC=DomainDnsZones", dnsdomain, domainsid)

        # Add DNS records for a DC in domain
        add_dc_domain_records(samdb, domaindn, "DC=DomainDnsZones", site, dnsdomain,
                                hostname, hostip, hostip6)

        ##### Set up DC=ForestDnsZones,<DOMAINDN>
        logger.info("Populating ForestDnsZones partition")

        # Set up MicrosoftDNS container
        add_dns_container(samdb, forestdn, "DC=ForestDnsZones", domainsid)

        # Add _msdcs record
        add_msdcs_record(samdb, forestdn, "DC=ForestDnsZones", dnsforest)

        # Add DNS records for a DC in forest
        add_dc_msdcs_records(samdb, forestdn, "DC=ForestDnsZones", site, dnsforest,
                                hostname, hostip, hostip6, domainguid, ntdsguid)

    if dns_backend.startswith("BIND9_"):
        secretsdb_setup_dns(secretsdb, names,
                            paths.private_dir, realm=names.realm,
                            dnsdomain=names.dnsdomain,
                            dns_keytab_path=paths.dns_keytab, dnspass=dnspass)

        create_dns_dir(logger, paths)

        # Only make a zone file on the first DC, it should be
        # replicated with DNS replication
        if dns_backend == "BIND9_FLATFILE":
            create_zone_file(lp, logger, paths, targetdir, site=site,
                             dnsdomain=names.dnsdomain, hostip=hostip, hostip6=hostip6,
                             hostname=names.hostname, realm=names.realm,
                             domainguid=domainguid, ntdsguid=names.ntdsguid)

        create_named_conf(paths, realm=names.realm,
                          dnsdomain=names.dnsdomain, dns_backend=dns_backend)

        create_named_txt(paths.namedtxt,
                         realm=names.realm, dnsdomain=names.dnsdomain,
                         dnsname = "%s.%s" % (names.hostname, names.dnsdomain),
                         private_dir=paths.private_dir,
                         keytab_name=paths.dns_keytab)
        logger.info("See %s for an example configuration include file for BIND", paths.namedconf)
        logger.info("and %s for further documentation required for secure DNS "
                    "updates", paths.namedtxt)
