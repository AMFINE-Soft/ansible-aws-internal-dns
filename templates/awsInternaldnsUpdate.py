#!/usr/bin/python3

import argparse
import os
import socket
import subprocess
import requests
import json

# Args
parser = argparse.ArgumentParser(description='stop, start dns hostname update script')
parser.add_argument("--stop", required=False, action='store_true', help="(will delete hostname entry on route53 ")
parser.add_argument("--start", required=False, action='store_true',
                    help="will create a dns entry with hostname on route53")
args = parser.parse_args()

# internal dns zone
zoneid = "{{ aws_dns_zone_id }}"
region = json.loads(requests.get(' http://169.254.169.254/latest/dynamic/instance-identity/document').text)['region']

CLOUD_INIT_DROPIN = "/etc/cloud/cloud.cfg.d/99-amfine-hostname.cfg"


# get hostname
def get_ec2_hostname():
    instanceidcmd = \
    subprocess.Popen(["/usr/bin/ec2metadata --instance-id"], shell=True, stdout=subprocess.PIPE).communicate()[
        0].decode('utf-8').strip()
    instanceid = str(instanceidcmd)
    cmd = "/usr/bin/aws ec2 describe-tags --profile aws-internal-dns --region " + region + " --filters Name=resource-id,Values=" + instanceid + " Name=key,Values=Name --output=text"
    hostnamecmd = subprocess.Popen([cmd], shell=True, stdout=subprocess.PIPE).communicate()[0].decode('utf-8').strip()
    hostname = str(hostnamecmd)
    hostname = hostname.split("\t")[4]
    hostname = hostname.split("\n")
    hostname = str(hostname[0])
    return hostname


# get ec2 ip address
def get_ip_address(ifname):
    cmd = "ip addr show " + ifname
    ip = os.popen(cmd).read().split("inet ")[1].split("/")[0]
    return ip


# look up Route53 zone name from its ID; strips trailing dot
def get_zone_name():
    cmd = ("/usr/bin/aws route53 get-hosted-zone "
           "--id " + zoneid + " --profile aws-internal-dns "
           "--output text --query HostedZone.Name")
    out = subprocess.run(cmd, shell=True, capture_output=True, text=True, check=True)
    return out.stdout.strip().rstrip(".")


# force kernel/static hostname to expected_short if it differs
def ensure_hostname(expected_short):
    current = socket.gethostname()
    if current != expected_short:
        print("hostname mismatch: current=" + current + " expected=" + expected_short + " - fixing")
        subprocess.run(["/usr/bin/hostnamectl", "set-hostname", expected_short], check=True)
    else:
        print("hostname already correct: " + current)


# Drop a per-instance cloud-init drop-in so cloud-init manages hostname/fqdn/etc-hosts natively on every boot.
# Transitional bridge until per-instance hostname is delivered via Terraform user-data;
# when that lands this file becomes redundant (and harmless).
# Note: when baking an AMI, remove this file (or run `cloud-init clean`) so VMs from the AMI
# don't inherit the bake-instance's hostname before correcting it.
def write_cloudinit_dropin(short, fqdn):
    cfg = (
        "# Managed by aws-internal-dns role - do not edit by hand\n"
        "hostname: " + short + "\n"
        "fqdn: " + fqdn + "\n"
        "preserve_hostname: false\n"
        "prefer_fqdn_over_hostname: false\n"
    )
    os.makedirs(os.path.dirname(CLOUD_INIT_DROPIN), exist_ok=True)
    with open(CLOUD_INIT_DROPIN, "w") as f:
        f.write(cfg)


# True if /etc/hosts already contains the expected '<fqdn> <short>' pair on a 127.0.1.1 line
# (which is what cloud-init's Debian template renders).
def is_hosts_in_sync(short, fqdn):
    try:
        with open("/etc/hosts", "r") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 3 and parts[0] == "127.0.1.1" and parts[1] == fqdn and parts[2] == short:
                    return True
    except FileNotFoundError:
        pass
    return False


# Force cloud-init to re-render /etc/hosts from the current config (incl. our just-written drop-in).
# This closes the "tag change requires two reboots" gap.
def regenerate_etc_hosts():
    subprocess.run(["/usr/bin/cloud-init", "single", "-n", "cc_update_etc_hosts"], check=True)


# Create, update or delete hostname entry
def dealwithDNSEntry(cmd):
    os.system(cmd)


def main():
    instanceip = get_ip_address("{{ ansible_default_ipv4.interface }}")
    expected_short = get_ec2_hostname()

    if args.stop:
        cmd = "/usr/local/bin/cli53 rrdelete " + zoneid + " " + expected_short + " A  --profile aws-internal-dns"
        dealwithDNSEntry(cmd)

    elif args.start:
        expected_fqdn = expected_short + "." + get_zone_name()
        ensure_hostname(expected_short)
        write_cloudinit_dropin(expected_short, expected_fqdn)
        if not is_hosts_in_sync(expected_short, expected_fqdn):
            print("/etc/hosts is out of sync (drift or first run) - asking cloud-init to re-render")
            regenerate_etc_hosts()
        cmd = "/usr/local/bin/cli53 rrcreate " + zoneid + " '" + expected_short + " 60 A " + instanceip + "' --replace  --profile aws-internal-dns"
        dealwithDNSEntry(cmd)


if __name__ == '__main__':
    main()
