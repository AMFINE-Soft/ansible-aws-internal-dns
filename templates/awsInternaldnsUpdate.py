#!/usr/bin/python3

import argparse
import os
import socket
import subprocess

#Args
parser = argparse.ArgumentParser(description='stop, start dns hostname update script')
parser.add_argument("--stop", required=False, action='store_true', help="(will delete hostname entry on route53 ")
parser.add_argument("--start", required=False, action='store_true', help="will create a dns entry with hostname on route53")
args = parser.parse_args()

#internal dns zone
zoneid = "{{ aws_dns_zone_id }}"
region = "{{ aws_dns_region }}"

# get hostname
def get_ec2_hostname():
    instanceidcmd = subprocess.Popen(["/usr/bin/ec2metadata --instance-id"], shell=True,stdout=subprocess.PIPE).communicate()[0].decode('utf-8').strip()
    instanceid = str(instanceidcmd)
    cmd = "/usr/bin/aws ec2 describe-tags --region "+ region +" --filters Name=resource-id,Values="+ instanceid + " Name=key,Values=Name --output=text"
    hostnamecmd = subprocess.Popen([cmd], shell=True,stdout=subprocess.PIPE).communicate()[0].decode('utf-8').strip()
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

# /etc/hosts has already been updated ?
def hosts_exists(hostname):
    filename = "/etc/hosts" 
    f = open(filename, 'r')
    hostfiledata = f.readlines()
    print("hostname : " + hostname)
    for item in hostfiledata:
        if hostname in item:
            return True
    f.close()
    return False

#Update etc/hosts
def update_hostname(instanceip, hostname):
    filename = "/etc/hosts"
    outputfile = open(filename, 'a')
    entry = "\n" + instanceip + "\t" + hostname + "\n"
    outputfile.writelines(entry)
    outputfile.close()


#check hostname and set it if necessary
def isDefaultHostname(instanceip):
  hostname = socket.gethostname()
  if "ip-" in hostname or "None" in hostname:
        hostname = get_ec2_hostname()
        #Update hostname
        os.system('/bin/hostname '+hostname)
        #Update hostname file
        hostnamefile = "/etc/hostname"
        hostnameopen = open(hostnamefile, 'w')
        hostnameopen.write(hostname)
        hostnameopen.close()
        return hostname
  else:
    return hostname

#Create, update or delete hostname entry
def dealwithDNSEntry(cmd):
  os.system(cmd)
  
def main():
  instanceip = get_ip_address("{{ ansible_default_ipv4.interface }}")
  hostname = isDefaultHostname(instanceip)
       
  if args.stop:
    cmd = "/usr/local/bin/cli53 rrdelete " + zoneid  + " " + hostname + " A "
    dealwithDNSEntry(cmd)

  elif args.start:
    cmd = "/usr/local/bin/cli53 rrcreate " + zoneid  + " '" + hostname + " 60 A " + instanceip + "' --replace"
    dealwithDNSEntry(cmd)
    # Update hosts file if necessary
    if hosts_exists(hostname):
      print("hostname already exists in host file")
    else:
      update_hostname(instanceip, hostname)

if __name__ == '__main__':
    main()
