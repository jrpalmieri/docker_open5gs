#!/usr/bin/env python3
"""
open5gs-dbctl.py: Open5GS Database Configuration Tool (Python version)

A Python script to manage Open5GS subscriber database, including the ability
to add subscribers from UERANSIM UE YAML configuration files.
"""

import argparse
import sys
import yaml
from bson import ObjectId

try:
    from pymongo import MongoClient
    
except ImportError:
    print("Error: pymongo is required. Install with: pip install pymongo")
    sys.exit(1)

VERSION = "0.10.3-py"
DEFAULT_DB_URI = "mongodb://localhost/open5gs"


def check_imsi_exists(db, imsi):
    """Check if a subscriber with the given IMSI already exists."""
    return db.subscribers.find_one({"imsi": imsi}) is not None


def handle_duplicate_imsi(db, imsi):
    """
    Handle the case when a subscriber with the same IMSI already exists.
    Returns a tuple (action, new_imsi) where:
    - action is 'overwrite', 'modify', or 'cancel'
    - new_imsi is the modified IMSI (only relevant if action is 'modify')
    """
    print(f"\nWarning: A subscriber with IMSI '{imsi}' already exists in the database.")
    print("\nOptions:")
    print("  1) Overwrite existing subscriber")
    print("  2) Enter a different IMSI")
    print("  3) Cancel operation")
    
    while True:
        choice = input("\nSelect option [1/2/3]: ").strip()
        
        if choice == '1':
            confirm = input(f"Are you sure you want to overwrite subscriber '{imsi}'? [y/N]: ").strip().lower()
            if confirm in ('y', 'yes'):
                # Delete existing subscriber
                db.subscribers.delete_one({"imsi": imsi})
                print(f"Existing subscriber '{imsi}' removed.")
                return ('overwrite', imsi)
            else:
                print("Overwrite cancelled. Please select another option.")
                continue
        
        elif choice == '2':
            new_imsi = input("Enter new IMSI: ").strip()
            if not new_imsi:
                print("Error: IMSI cannot be empty.")
                continue
            if check_imsi_exists(db, new_imsi):
                print(f"Error: IMSI '{new_imsi}' also exists in the database.")
                continue
            return ('modify', new_imsi)
        
        elif choice == '3':
            return ('cancel', None)
        
        else:
            print("Invalid option. Please enter 1, 2, or 3.")


def get_db(db_uri):
    """Connect to MongoDB and return the database object."""
    client = MongoClient(db_uri)
    # Extract database name from URI or use default
    db_name = db_uri.split('/')[-1].split('?')[0] if '/' in db_uri else 'open5gs'
    if not db_name:
        db_name = 'open5gs'
    return client[db_name]


def pdn_type_to_int(pdn_type):
    """Convert PDN type string to integer."""
    type_map = {
        'ipv4': 1,
        'ipv6': 2,
        'ipv4v6': 3,
    }
    return type_map.get(pdn_type.lower(), 3)


def create_session(name, pdn_type=3, ipv4=None):
    """Create a session document for a subscriber slice."""
    session = {
        "name": name,
        "type": pdn_type,
        "qos": {
            "index": 9,
            "arp": {
                "priority_level": 8,
                "pre_emption_capability": 1,
                "pre_emption_vulnerability": 2
            }
        },
        "ambr": {
            "downlink": {"value": 1000000000, "unit": 0},
            "uplink": {"value": 1000000000, "unit": 0}
        },
        "pcc_rule": [],
        "_id": ObjectId(),
    }
    if ipv4:
        session["ue"] = {"ipv4": ipv4}
    return session


def create_slice(sst, sd=None, sessions=None, default_indicator=True):
    """Create a slice document for a subscriber."""
    slice_doc = {
        "sst": sst,
        "default_indicator": default_indicator,
        "session": sessions if sessions else [],
        "_id": ObjectId(),
    }
    if sd is not None:
        slice_doc["sd"] = sd
    return slice_doc


def create_subscriber_doc(imsi, key, opc=None, op=None, amf="8000", slices=None, imeisv=None):
    """Create a complete subscriber document."""
    security = {
        "k": key,
        "amf": amf,
    }
    if opc:
        security["op"] = None
        security["opc"] = opc
    elif op:
        security["op"] = op
        security["opc"] = None
    else:
        security["op"] = None
        security["opc"] = None

    doc = {
        "_id": ObjectId(),
        "schema_version": 1,
        "imsi": imsi,
        "msisdn": [],
        "imeisv": [imeisv] if imeisv else [],
        "mme_host": [],
        "mm_realm": [],
        "purge_flag": [],
        "slice": slices if slices else [],
        "security": security,
        "ambr": {
            "downlink": {"value": 1000000000, "unit": 0},
            "uplink": {"value": 1000000000, "unit": 0}
        },
        "access_restriction_data": 32,
        "network_access_mode": 0,
        "subscriber_status": 0,
        "operator_determined_barring": 0,
        "subscribed_rau_tau_timer": 12,
        "__v": 0
    }
    return doc


def add_subscriber(db, imsi, key, opc, ip=None):
    """Add a subscriber with default values."""
    # Check for duplicate IMSI
    if check_imsi_exists(db, imsi):
        action, new_imsi = handle_duplicate_imsi(db, imsi)
        if action == 'cancel':
            print("Operation cancelled.")
            return None
        elif action == 'modify':
            imsi = new_imsi
    
    session = create_session("internet", pdn_type=3, ipv4=ip)
    slice_doc = create_slice(sst=1, sessions=[session])
    doc = create_subscriber_doc(imsi, key, opc=opc, slices=[slice_doc])
    result = db.subscribers.insert_one(doc)
    print(f"Subscriber {imsi} added with _id: {result.inserted_id}")
    return result


def add_subscriber_t1(db, imsi, key, opc, ip=None):
    """Add a subscriber with 3 different APNs."""
    # Check for duplicate IMSI
    if check_imsi_exists(db, imsi):
        action, new_imsi = handle_duplicate_imsi(db, imsi)
        if action == 'cancel':
            print("Operation cancelled.")
            return None
        elif action == 'modify':
            imsi = new_imsi
    
    sessions = [
        create_session("internet", pdn_type=3, ipv4=ip),
        create_session("internet1", pdn_type=3, ipv4=ip),
        create_session("internet2", pdn_type=3, ipv4=ip),
    ]
    slice_doc = create_slice(sst=1, sessions=sessions)
    doc = create_subscriber_doc(imsi, key, opc=opc, slices=[slice_doc])
    result = db.subscribers.insert_one(doc)
    print(f"Subscriber {imsi} added with 3 APNs, _id: {result.inserted_id}")
    return result


def add_subscriber_with_apn(db, imsi, key, opc, apn):
    """Add a subscriber with a specific APN."""
    # Check for duplicate IMSI
    if check_imsi_exists(db, imsi):
        action, new_imsi = handle_duplicate_imsi(db, imsi)
        if action == 'cancel':
            print("Operation cancelled.")
            return None
        elif action == 'modify':
            imsi = new_imsi
    
    session = create_session(apn, pdn_type=3)
    slice_doc = create_slice(sst=1, sessions=[session])
    doc = create_subscriber_doc(imsi, key, opc=opc, slices=[slice_doc])
    result = db.subscribers.insert_one(doc)
    print(f"Subscriber {imsi} added with APN '{apn}', _id: {result.inserted_id}")
    return result


def add_subscriber_with_slice(db, imsi, key, opc, apn, sst, sd):
    """Add a subscriber with a specific APN, SST and SD."""
    # Check for duplicate IMSI
    if check_imsi_exists(db, imsi):
        action, new_imsi = handle_duplicate_imsi(db, imsi)
        if action == 'cancel':
            print("Operation cancelled.")
            return None
        elif action == 'modify':
            imsi = new_imsi
    
    session = create_session(apn, pdn_type=3)
    slice_doc = create_slice(sst=int(sst), sd=int(sd), sessions=[session])
    doc = create_subscriber_doc(imsi, key, opc=opc, slices=[slice_doc])
    result = db.subscribers.insert_one(doc)
    print(f"Subscriber {imsi} added with APN '{apn}', SST={sst}, SD={sd}, _id: {result.inserted_id}")
    return result


def add_subscriber_from_yaml(db, yaml_file):
    """Add a subscriber from a UERANSIM UE YAML configuration file."""
    try:
        with open(yaml_file, 'r') as f:
            ue_config = yaml.safe_load(f)
    except FileNotFoundError:
        print(f"Error: YAML file '{yaml_file}' not found")
        return None
    except yaml.YAMLError as e:
        print(f"Error parsing YAML file: {e}")
        return None

    # Extract IMSI from supi field (format: 'imsi-XXXXXXXXXXXXXXX')
    supi = ue_config.get('supi', '')
    if supi.startswith('imsi-'):
        imsi = supi[5:]  # Remove 'imsi-' prefix
    else:
        imsi = supi

    if not imsi:
        print("Error: No valid IMSI/SUPI found in YAML file")
        return None

    # Check for duplicate IMSI
    if check_imsi_exists(db, imsi):
        action, new_imsi = handle_duplicate_imsi(db, imsi)
        if action == 'cancel':
            print("Operation cancelled.")
            return None
        elif action == 'modify':
            imsi = new_imsi

    # Extract security credentials
    key = ue_config.get('key', '')
    op_value = ue_config.get('op', '')
    op_type = ue_config.get('opType', 'OPC').upper()
    amf = ue_config.get('amf', '8000')
    imeisv = ue_config.get('imeiSv', None)

    # Determine if using OP or OPC
    opc = op_value if op_type == 'OPC' else None
    op = op_value if op_type == 'OP' else None

    # Build slices from sessions in YAML
    slices = []
    sessions_config = ue_config.get('sessions', [])
    
    # Group sessions by slice (sst, sd)
    slice_sessions = {}
    for sess in sessions_config:
        apn = sess.get('apn', 'internet')
        pdn_type = pdn_type_to_int(sess.get('type', 'IPv4v6'))
        slice_info = sess.get('slice', {})
        sst = slice_info.get('sst', 1)
        sd = slice_info.get('sd', None)
        
        slice_key = (sst, sd)
        if slice_key not in slice_sessions:
            slice_sessions[slice_key] = []
        
        session = create_session(apn, pdn_type=pdn_type)
        slice_sessions[slice_key].append(session)

    # Create slice documents
    first_slice = True
    for (sst, sd), sessions in slice_sessions.items():
        slice_doc = create_slice(sst=sst, sd=sd, sessions=sessions, default_indicator=first_slice)
        slices.append(slice_doc)
        first_slice = False

    # If no sessions were defined, create a default slice
    if not slices:
        # Check configured-nssai or default-nssai for slice info
        nssai = ue_config.get('configured-nssai', ue_config.get('default-nssai', [{'sst': 1}]))
        if nssai:
            sst = nssai[0].get('sst', 1)
            sd = nssai[0].get('sd', None)
            session = create_session("internet", pdn_type=3)
            slice_doc = create_slice(sst=sst, sd=sd, sessions=[session])
            slices.append(slice_doc)

    # Create and insert the subscriber document
    doc = create_subscriber_doc(
        imsi=imsi,
        key=key,
        opc=opc,
        op=op,
        amf=amf,
        slices=slices,
        imeisv=imeisv
    )

    result = db.subscribers.insert_one(doc)
    print(f"Subscriber {imsi} added from YAML file '{yaml_file}'")
    print(f"  Key: {key}")
    print(f"  {'OPC' if opc else 'OP'}: {opc or op}")
    print(f"  AMF: {amf}")
    print(f"  Slices: {len(slices)}")
    for i, s in enumerate(slices):
        sd_str = f", SD={s.get('sd')}" if s.get('sd') is not None else ""
        print(f"    Slice {i+1}: SST={s['sst']}{sd_str}, Sessions={len(s['session'])}")
    print(f"  _id: {result.inserted_id}")
    return result


def add_multi_subscribers_from_yaml(db, yaml_file, count):
    """Add multiple subscribers from a UERANSIM UE YAML configuration file.
    
    The base IMSI is read from the YAML file and incremented by 1 for each
    subsequent subscriber.
    """
    try:
        with open(yaml_file, 'r') as f:
            ue_config = yaml.safe_load(f)
    except FileNotFoundError:
        print(f"Error: YAML file '{yaml_file}' not found")
        return None
    except yaml.YAMLError as e:
        print(f"Error parsing YAML file: {e}")
        return None

    # Extract base IMSI from supi field (format: 'imsi-XXXXXXXXXXXXXXX')
    supi = ue_config.get('supi', '')
    if supi.startswith('imsi-'):
        base_imsi = supi[5:]  # Remove 'imsi-' prefix
    else:
        base_imsi = supi

    if not base_imsi:
        print("Error: No valid IMSI/SUPI found in YAML file")
        return None

    # Validate that base_imsi is numeric
    if not base_imsi.isdigit():
        print(f"Error: IMSI '{base_imsi}' is not a valid numeric string")
        return None

    imsi_length = len(base_imsi)
    base_imsi_int = int(base_imsi)

    # Extract security credentials (common to all subscribers)
    key = ue_config.get('key', '')
    op_value = ue_config.get('op', '')
    op_type = ue_config.get('opType', 'OPC').upper()
    amf = ue_config.get('amf', '8000')
    imeisv = ue_config.get('imeiSv', None)

    # Determine if using OP or OPC
    opc = op_value if op_type == 'OPC' else None
    op = op_value if op_type == 'OP' else None

    # Build slices from sessions in YAML
    sessions_config = ue_config.get('sessions', [])
    
    # Group sessions by slice (sst, sd)
    slice_sessions = {}
    for sess in sessions_config:
        apn = sess.get('apn', 'internet')
        pdn_type = pdn_type_to_int(sess.get('type', 'IPv4v6'))
        slice_info = sess.get('slice', {})
        sst = slice_info.get('sst', 1)
        sd = slice_info.get('sd', None)
        
        slice_key = (sst, sd)
        if slice_key not in slice_sessions:
            slice_sessions[slice_key] = []
        
        session = create_session(apn, pdn_type=pdn_type)
        slice_sessions[slice_key].append(session)

    # Create base slice documents template
    base_slices_template = []
    first_slice = True
    for (sst, sd), sessions in slice_sessions.items():
        base_slices_template.append({'sst': sst, 'sd': sd, 'default_indicator': first_slice, 'sessions_template': sessions})
        first_slice = False

    # If no sessions were defined, create a default slice template
    if not base_slices_template:
        nssai = ue_config.get('configured-nssai', ue_config.get('default-nssai', [{'sst': 1}]))
        if nssai:
            sst = nssai[0].get('sst', 1)
            sd = nssai[0].get('sd', None)
            base_slices_template.append({'sst': sst, 'sd': sd, 'default_indicator': True, 'sessions_template': [create_session("internet", pdn_type=3)]})

    added_count = 0
    skipped_count = 0

    print(f"Adding {count} subscribers starting from IMSI {base_imsi}...")

    for i in range(count):
        current_imsi_int = base_imsi_int + i
        current_imsi = str(current_imsi_int).zfill(imsi_length)

        # Check for duplicate IMSI - skip if exists
        if check_imsi_exists(db, current_imsi):
            print(f"  Skipping IMSI {current_imsi} (already exists)")
            skipped_count += 1
            continue

        # Create fresh slices for each subscriber (need new ObjectIds)
        slices = []
        for tmpl in base_slices_template:
            sessions = [create_session(s['name'], pdn_type=s['type']) for s in tmpl['sessions_template']]
            slice_doc = create_slice(sst=tmpl['sst'], sd=tmpl['sd'], sessions=sessions, default_indicator=tmpl['default_indicator'])
            slices.append(slice_doc)

        # Create and insert the subscriber document
        doc = create_subscriber_doc(
            imsi=current_imsi,
            key=key,
            opc=opc,
            op=op,
            amf=amf,
            slices=slices,
            imeisv=imeisv
        )

        db.subscribers.insert_one(doc)
        added_count += 1

    print(f"\nCompleted: {added_count} subscribers added, {skipped_count} skipped (duplicates)")
    return added_count


def remove_subscriber(db, imsi):
    """Remove a subscriber from the database."""
    result = db.subscribers.delete_one({"imsi": imsi})
    if result.deleted_count > 0:
        print(f"Subscriber {imsi} removed")
    else:
        print(f"Subscriber {imsi} not found")
    return result


def reset_database(db):
    """Reset the database to empty state."""
    result = db.subscribers.delete_many({})
    print(f"Database reset. Removed {result.deleted_count} subscribers.")
    return result


def set_static_ip(db, imsi, ip):
    """Add a static IPv4 address to an existing subscriber."""
    result = db.subscribers.update_one(
        {"imsi": imsi},
        {"$set": {"slice.$[].session.$[].ue.ipv4": ip}}
    )
    if result.modified_count > 0:
        print(f"Static IP {ip} set for subscriber {imsi}")
    else:
        print(f"Subscriber {imsi} not found or not modified")
    return result


def set_static_ip6(db, imsi, ip6):
    """Add a static IPv6 address to an existing subscriber."""
    result = db.subscribers.update_one(
        {"imsi": imsi},
        {"$set": {"slice.$[].session.$[].ue.ipv6": ip6}}
    )
    if result.modified_count > 0:
        print(f"Static IPv6 {ip6} set for subscriber {imsi}")
    else:
        print(f"Subscriber {imsi} not found or not modified")
    return result


def set_pdn_type(db, imsi, pdn_type):
    """Change the PDN-Type of the first PDN."""
    result = db.subscribers.update_one(
        {"imsi": imsi},
        {"$set": {"slice.0.session.0.type": int(pdn_type)}}
    )
    if result.modified_count > 0:
        print(f"PDN type set to {pdn_type} for subscriber {imsi}")
    else:
        print(f"Subscriber {imsi} not found or not modified")
    return result


def show_all(db):
    """Show all subscribers in the database."""
    subscribers = list(db.subscribers.find())
    print(f"Total subscribers: {len(subscribers)}")
    for sub in subscribers:
        print(sub)


def show_pretty(db):
    """Show all subscribers in pretty JSON format."""
    import json
    subscribers = list(db.subscribers.find())
    print(f"Total subscribers: {len(subscribers)}")
    for sub in subscribers:
        # Convert ObjectId to string for JSON serialization
        sub['_id'] = str(sub['_id'])
        for s in sub.get('slice', []):
            s['_id'] = str(s['_id'])
            for sess in s.get('session', []):
                sess['_id'] = str(sess['_id'])
        print(json.dumps(sub, indent=2))


def show_filtered(db):
    """Show filtered subscriber information."""
    subscribers = list(db.subscribers.find())
    print(f"{'IMSI':<20} {'Key':<35} {'OPC/OP':<35} {'APN':<15} {'IP':<15}")
    print("-" * 120)
    for sub in subscribers:
        imsi = sub.get('imsi', '')
        key = sub.get('security', {}).get('k', '')
        opc = sub.get('security', {}).get('opc', '') or sub.get('security', {}).get('op', '')
        apn = ''
        ip = ''
        slices = sub.get('slice', [])
        if slices and slices[0].get('session'):
            apn = slices[0]['session'][0].get('name', '')
            ip = slices[0]['session'][0].get('ue', {}).get('ipv4', '')
        print(f"{imsi:<20} {key:<35} {opc:<35} {apn:<15} {ip:<15}")


def update_apn(db, imsi, apn, slice_num):
    """Add an APN to a specific slice of an existing subscriber."""
    session = create_session(apn, pdn_type=3)
    result = db.subscribers.update_one(
        {"imsi": imsi},
        {"$push": {f"slice.{slice_num}.session": session}}
    )
    if result.modified_count > 0:
        print(f"APN '{apn}' added to slice {slice_num} for subscriber {imsi}")
    else:
        print(f"Subscriber {imsi} not found or not modified")
    return result


def update_slice(db, imsi, apn, sst, sd):
    """Add a new slice to an existing subscriber."""
    session = create_session(apn, pdn_type=3)
    slice_doc = create_slice(sst=int(sst), sd=int(sd), sessions=[session], default_indicator=False)
    result = db.subscribers.update_one(
        {"imsi": imsi},
        {"$push": {"slice": slice_doc}}
    )
    if result.modified_count > 0:
        print(f"Slice SST={sst}, SD={sd} with APN '{apn}' added for subscriber {imsi}")
    else:
        print(f"Subscriber {imsi} not found or not modified")
    return result


def set_ambr_speed(db, imsi, dl_value, dl_unit, ul_value, ul_unit):
    """Change AMBR speed for a subscriber."""
    result = db.subscribers.update_one(
        {"imsi": imsi},
        {"$set": {
            "ambr.downlink.value": int(dl_value),
            "ambr.downlink.unit": int(dl_unit),
            "ambr.uplink.value": int(ul_value),
            "ambr.uplink.unit": int(ul_unit),
        }}
    )
    if result.modified_count > 0:
        print(f"AMBR speed updated for subscriber {imsi}")
    else:
        print(f"Subscriber {imsi} not found or not modified")
    return result


def set_subscriber_status(db, imsi, subscriber_status, operator_barring):
    """Change subscriber status and operator determined barring."""
    result = db.subscribers.update_one(
        {"imsi": imsi},
        {"$set": {
            "subscriber_status": int(subscriber_status),
            "operator_determined_barring": int(operator_barring),
        }}
    )
    if result.modified_count > 0:
        print(f"Subscriber status updated for {imsi}")
    else:
        print(f"Subscriber {imsi} not found or not modified")
    return result


def set_lbo_roaming(db, imsi, lbo_roaming_allowed):
    """Change roaming type for a subscriber."""
    # Note: This is a simplified implementation
    result = db.subscribers.update_one(
        {"imsi": imsi},
        {"$set": {"lbo_roaming_allowed": int(lbo_roaming_allowed)}}
    )
    if result.modified_count > 0:
        print(f"LBO roaming setting updated for subscriber {imsi}")
    else:
        print(f"Subscriber {imsi} not found or not modified")
    return result


def main():
    parser = argparse.ArgumentParser(
        description=f"open5gs-dbctl.py: Open5GS Database Configuration Tool ({VERSION})",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  add <imsi> <key> <opc>              Add a subscriber with default values
  add <imsi> <ip> <key> <opc>         Add a subscriber with static IPv4 address
  addT1 <imsi> <key> <opc>            Add a subscriber with 3 APNs
  addT1 <imsi> <ip> <key> <opc>       Add a subscriber with 3 APNs and static IP
  add_from_yaml <yaml_file>           Add a subscriber from UERANSIM UE YAML file
  add_multi_yaml <yaml_file> <count>  Add multiple subscribers from YAML, incrementing IMSI
  add_ue_with_apn <imsi> <key> <opc> <apn>
                                      Add a subscriber with specific APN
  add_ue_with_slice <imsi> <key> <opc> <apn> <sst> <sd>
                                      Add a subscriber with specific slice
  remove <imsi>                       Remove a subscriber
  reset                               Reset database (remove all subscribers)
  delete-all                          Delete all subscribers from database (same as reset)
  static_ip <imsi> <ip>               Set static IPv4 for existing subscriber
  static_ip6 <imsi> <ip6>             Set static IPv6 for existing subscriber
  type <imsi> <type>                  Set PDN type (1=IPv4, 2=IPv6, 3=IPv4v6)
  update_apn <imsi> <apn> <slice_num> Add APN to existing subscriber's slice
  update_slice <imsi> <apn> <sst> <sd>
                                      Add new slice to existing subscriber
  showall                             Show all subscribers
  showpretty                          Show all subscribers (pretty JSON)
  showfiltered                        Show subscribers (filtered view)
  ambr_speed <imsi> <dl_val> <dl_unit> <ul_val> <ul_unit>
                                      Set AMBR speed (units: 0=bps,1=Kbps,2=Mbps,3=Gbps,4=Tbps)
  subscriber_status <imsi> <status> <barring>
                                      Set subscriber status and barring
  lbo_roaming_allowed <imsi> <allowed>
                                      Set LBO roaming (0=LBO, 1=HR)
        """
    )
    parser.add_argument('--db_uri', default=DEFAULT_DB_URI,
                        help=f'MongoDB URI (default: {DEFAULT_DB_URI})')
    parser.add_argument('command', nargs='?', help='Command to execute')
    parser.add_argument('args', nargs='*', help='Command arguments')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    db = get_db(args.db_uri)
    cmd = args.command.lower()
    cmd_args = args.args

    try:
        if cmd == 'add':
            if len(cmd_args) == 3:
                add_subscriber(db, cmd_args[0], cmd_args[1], cmd_args[2])
            elif len(cmd_args) == 4:
                add_subscriber(db, cmd_args[0], cmd_args[2], cmd_args[3], ip=cmd_args[1])
            else:
                print("Usage: add <imsi> <key> <opc> OR add <imsi> <ip> <key> <opc>")
                sys.exit(1)

        elif cmd == 'addt1':
            if len(cmd_args) == 3:
                add_subscriber_t1(db, cmd_args[0], cmd_args[1], cmd_args[2])
            elif len(cmd_args) == 4:
                add_subscriber_t1(db, cmd_args[0], cmd_args[2], cmd_args[3], ip=cmd_args[1])
            else:
                print("Usage: addT1 <imsi> <key> <opc> OR addT1 <imsi> <ip> <key> <opc>")
                sys.exit(1)

        elif cmd == 'add_from_yaml':
            if len(cmd_args) != 1:
                print("Usage: add_from_yaml <yaml_file>")
                sys.exit(1)
            add_subscriber_from_yaml(db, cmd_args[0])

        elif cmd == 'add_multi_yaml':
            if len(cmd_args) != 2:
                print("Usage: add_multi_yaml <yaml_file> <count>")
                sys.exit(1)
            try:
                count = int(cmd_args[1])
                if count < 1:
                    print("Error: count must be a positive integer")
                    sys.exit(1)
            except ValueError:
                print("Error: count must be a valid integer")
                sys.exit(1)
            add_multi_subscribers_from_yaml(db, cmd_args[0], count)

        elif cmd == 'add_ue_with_apn':
            if len(cmd_args) != 4:
                print("Usage: add_ue_with_apn <imsi> <key> <opc> <apn>")
                sys.exit(1)
            add_subscriber_with_apn(db, cmd_args[0], cmd_args[1], cmd_args[2], cmd_args[3])

        elif cmd == 'add_ue_with_slice':
            if len(cmd_args) != 6:
                print("Usage: add_ue_with_slice <imsi> <key> <opc> <apn> <sst> <sd>")
                sys.exit(1)
            add_subscriber_with_slice(db, cmd_args[0], cmd_args[1], cmd_args[2],
                                       cmd_args[3], cmd_args[4], cmd_args[5])

        elif cmd == 'remove':
            if len(cmd_args) != 1:
                print("Usage: remove <imsi>")
                sys.exit(1)
            remove_subscriber(db, cmd_args[0])

        elif cmd == 'reset':
            reset_database(db)

        elif cmd == 'delete-all':
            reset_database(db)

        elif cmd == 'static_ip':
            if len(cmd_args) != 2:
                print("Usage: static_ip <imsi> <ip>")
                sys.exit(1)
            set_static_ip(db, cmd_args[0], cmd_args[1])

        elif cmd == 'static_ip6':
            if len(cmd_args) != 2:
                print("Usage: static_ip6 <imsi> <ip6>")
                sys.exit(1)
            set_static_ip6(db, cmd_args[0], cmd_args[1])

        elif cmd == 'type':
            if len(cmd_args) != 2:
                print("Usage: type <imsi> <type>")
                sys.exit(1)
            set_pdn_type(db, cmd_args[0], cmd_args[1])

        elif cmd == 'update_apn':
            if len(cmd_args) != 3:
                print("Usage: update_apn <imsi> <apn> <slice_num>")
                sys.exit(1)
            update_apn(db, cmd_args[0], cmd_args[1], int(cmd_args[2]))

        elif cmd == 'update_slice':
            if len(cmd_args) != 4:
                print("Usage: update_slice <imsi> <apn> <sst> <sd>")
                sys.exit(1)
            update_slice(db, cmd_args[0], cmd_args[1], cmd_args[2], cmd_args[3])

        elif cmd == 'showall':
            show_all(db)

        elif cmd == 'showpretty':
            show_pretty(db)

        elif cmd == 'showfiltered':
            show_filtered(db)

        elif cmd == 'ambr_speed':
            if len(cmd_args) != 5:
                print("Usage: ambr_speed <imsi> <dl_value> <dl_unit> <ul_value> <ul_unit>")
                sys.exit(1)
            set_ambr_speed(db, cmd_args[0], cmd_args[1], cmd_args[2], cmd_args[3], cmd_args[4])

        elif cmd == 'subscriber_status':
            if len(cmd_args) != 3:
                print("Usage: subscriber_status <imsi> <status> <barring>")
                sys.exit(1)
            set_subscriber_status(db, cmd_args[0], cmd_args[1], cmd_args[2])

        elif cmd == 'lbo_roaming_allowed':
            if len(cmd_args) != 2:
                print("Usage: lbo_roaming_allowed <imsi> <allowed>")
                sys.exit(1)
            set_lbo_roaming(db, cmd_args[0], cmd_args[1])

        elif cmd == 'help':
            parser.print_help()

        else:
            print(f"Unknown command: {cmd}")
            parser.print_help()
            sys.exit(1)

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
