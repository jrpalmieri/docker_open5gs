#!/usr/bin/env bash
set -euo pipefail

SUBNET_CIDR="${SUBNET_CIDR:-172.22.0.0/24}"
GATEWAY_IP="${GATEWAY_IP:-172.22.0.1}"
GNB1_IP="${GNB1_IP:-172.22.0.202/24}"
GNB2_IP="${GNB2_IP:-172.22.0.203/24}"
GNB1_NAME="${GNB1_NAME:-gnb202}"
GNB2_NAME="${GNB2_NAME:-gnb203}"

GNB_IP_PREFIX="172.22.0"
GNB_MIN_OCTET=202
GNB_MAX_OCTET=210
MODE="${1:-on}"

# name of mongoDB container as defined in sa-deploy.yaml
MONGO_CONTAINER="mongo"
# log file directory (relative to this script) to clear on reset
LOG_DIR="./log"

usage() {
  cat <<'EOF'
Usage: ./run_sa.sh [on|off|reset]

Modes:
  on (default)   Start SA containers and assign host gNB IPs (default)
  off  Stop and remove SA containers, then clean host/network artifacts
  reset  Clear runtime state/logs of SA NFs (preserving subscriber data), and restart
EOF
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "ERROR: required command '$1' not found" >&2
    exit 1
  fi
}

cleanup_ns() {
  local ns="$1"
  if ip netns list | awk '{print $1}' | grep -qx "$ns"; then
    ip netns del "$ns" || true
  fi
}

cleanup_link_if_exists() {
  local dev="$1"
  if ip link show "$dev" >/dev/null 2>&1; then
    ip link del "$dev" || true
  fi
}

validate_gnb_ip() {
  local label="$1"
  local ip_cidr="$2"
  local ip="${ip_cidr%/*}"
  local prefix="${ip%.*}"
  local octet="${ip##*.}"
  local mask="${ip_cidr#*/}"

  if [[ ! "$ip" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then
    echo "ERROR: ${label} (${ip_cidr}) is not a valid IPv4/CIDR address" >&2
    exit 1
  fi

  if [[ "$mask" != "24" || "$prefix" != "$GNB_IP_PREFIX" || ! "$octet" =~ ^[0-9]+$ || "$octet" -lt "$GNB_MIN_OCTET" || "$octet" -gt "$GNB_MAX_OCTET" ]]; then
    echo "ERROR: ${label} (${ip_cidr}) must be in ${GNB_IP_PREFIX}.${GNB_MIN_OCTET}-${GNB_MAX_OCTET}/24" >&2
    exit 1
  fi
}

cleanup_prior_gnb_namespace_assignments() {
  local ns
  local ip_cidr
  local ip
  local prefix
  local octet

  while IFS= read -r ns; do
    while IFS= read -r ip_cidr; do
      ip="${ip_cidr%/*}"
      prefix="${ip%.*}"
      octet="${ip##*.}"

      if [[ "$prefix" == "$GNB_IP_PREFIX" && "$octet" =~ ^[0-9]+$ && "$octet" -ge "$GNB_MIN_OCTET" && "$octet" -le "$GNB_MAX_OCTET" ]]; then
        echo "Removing existing namespace '${ns}' with gNB-range IP assignment (${ip_cidr})"
        cleanup_ns "$ns"
        break
      fi
    done < <(ip netns exec "$ns" ip -o -4 addr show 2>/dev/null | awk '{print $4}')
  done < <(ip netns list | awk '{print $1}')
}

cleanup_prior_bridge_gnb_assignments() {
  local ip_cidr
  local ip
  local prefix
  local octet

  while IFS= read -r ip_cidr; do
    ip="${ip_cidr%/*}"
    prefix="${ip%.*}"
    octet="${ip##*.}"

    if [[ "$prefix" == "$GNB_IP_PREFIX" && "$octet" =~ ^[0-9]+$ && "$octet" -ge "$GNB_MIN_OCTET" && "$octet" -le "$GNB_MAX_OCTET" ]]; then
      echo "Removing existing host assignment on ${BRIDGE_DEV} (${ip_cidr})"
      ip addr del "$ip_cidr" dev "$BRIDGE_DEV" || true
    fi
  done < <(ip -o -4 addr show dev "$BRIDGE_DEV" | awk '{print $4}')
}

cleanup_gnb_assignments_all_interfaces() {
  local dev
  local ip_cidr
  local ip
  local prefix
  local octet

  while IFS= read -r line; do
    dev="${line%% *}"
    ip_cidr="${line#* }"
    ip="${ip_cidr%/*}"
    prefix="${ip%.*}"
    octet="${ip##*.}"

    if [[ "$prefix" == "$GNB_IP_PREFIX" && "$octet" =~ ^[0-9]+$ && "$octet" -ge "$GNB_MIN_OCTET" && "$octet" -le "$GNB_MAX_OCTET" ]]; then
      echo "Removing existing host assignment on ${dev} (${ip_cidr})"
      ip addr del "$ip_cidr" dev "$dev" || true
    fi
  done < <(ip -o -4 addr show | awk '{print $2, $4}')
}

cleanup_named_gnb_namespace_artifacts() {
  local ns="$1"
  local ip_cidr="$2"
  local host_veth="${ns}-host"
  local ns_veth="${ns}-eth0"

  cleanup_ns "$ns" || true
  cleanup_link_if_exists "$host_veth"
  cleanup_link_if_exists "$ns_veth"
}

assign_host_gnb_ip() {
  local ip_cidr="$1"

  if ip -o -4 addr show dev "$BRIDGE_DEV" | awk '{print $4}' | grep -qx "$ip_cidr"; then
    echo "Host assignment already present on ${BRIDGE_DEV} (${ip_cidr})"
    return
  fi

  ip addr add "$ip_cidr" dev "$BRIDGE_DEV"
  echo "Assigned host gNB address on ${BRIDGE_DEV} (${ip_cidr})"
}

reset_sa_runtime_state() {
  echo "Reset - clearing NF runtime state while preserving subscriber profiles..."
  echo "[1/4] Stopping Open5GS network functions..."
  docker compose -f sa-deploy.yaml stop amf smf upf nrf scp ausf udr udm pcf bsf nssf || true

  echo "[2/4] Wiping MongoDB runtime state (preserving subscribers/profiles)..."
  docker exec -i "$MONGO_CONTAINER" mongosh open5gs --eval '
    const protect = ["subscribers", "profiles", "system.indexes"];
    db.getCollectionNames().forEach(col => {
      if (!protect.includes(col)) {
        print("Wiping collection: " + col);
        db[col].deleteMany({});
      }
    });
  '

  echo "[3/4] Clearing old logs..."
  if [[ -d "$LOG_DIR" ]]; then
    rm -f "$LOG_DIR"/*.log || true
  fi

  echo "[4/4] Restarting Open5GS stack..."
  docker compose -f sa-deploy.yaml start

  echo "Reset complete."
}

require_cmd docker
require_cmd ip
require_cmd awk
require_cmd grep

if [[ "${EUID}" -ne 0 ]]; then
  echo "ERROR: run as root (needed for ip netns and link operations)." >&2
  exit 1
fi

case "$MODE" in
  on|off|reset)
    ;;
  -h|--help|help)
    usage
    exit 0
    ;;
  *)
    echo "ERROR: unsupported mode '$MODE'" >&2
    usage
    exit 1
    ;;
esac

if [[ "$MODE" == "off" ]]; then
  echo "Turning SA core network off..."
  echo "[1/2] Stopping and removing SA containers..."
  docker compose -f sa-deploy.yaml down --remove-orphans || true

  echo "[2/2] Cleaning local gNB networking artifacts..."
  cleanup_gnb_assignments_all_interfaces
  cleanup_prior_gnb_namespace_assignments
  cleanup_named_gnb_namespace_artifacts "$GNB1_NAME" "$GNB1_IP"
  cleanup_named_gnb_namespace_artifacts "$GNB2_NAME" "$GNB2_IP"

  echo "Done. SA containers are stopped and removed. GNB host IP assignments and namespaces cleaned up."
  exit 0
fi

if [[ "$MODE" == "reset" ]]; then
  reset_sa_runtime_state
  exit 0
fi

validate_gnb_ip "GNB1_IP" "$GNB1_IP"
validate_gnb_ip "GNB2_IP" "$GNB2_IP"

if [[ "$GNB1_IP" == "$GNB2_IP" ]]; then
  echo "ERROR: GNB1_IP and GNB2_IP must be different" >&2
  exit 1
fi

echo "[1/4] Starting SA network..."
docker compose -f sa-deploy.yaml up -d

echo "[2/4] Finding bridge device for ${GATEWAY_IP}/24..."
BRIDGE_DEV="$(ip -o -4 addr show | awk -v gw="${GATEWAY_IP}/24" '$4 == gw {print $2; exit}')"

if [[ -z "${BRIDGE_DEV}" ]]; then
  echo "ERROR: could not find interface with address ${GATEWAY_IP}/24" >&2
  echo "Hint: verify SA network started and subnet matches ${SUBNET_CIDR}" >&2
  exit 1
fi

echo "Detected bridge: ${BRIDGE_DEV}"

echo "[3/4] Removing prior gNB assignments in ${GNB_IP_PREFIX}.${GNB_MIN_OCTET}-${GNB_MAX_OCTET}/24..."
cleanup_prior_bridge_gnb_assignments
cleanup_prior_gnb_namespace_assignments
cleanup_named_gnb_namespace_artifacts "$GNB1_NAME" "$GNB1_IP"
cleanup_named_gnb_namespace_artifacts "$GNB2_NAME" "$GNB2_IP"

echo "[4/4] Assigning host gNB IPs on ${BRIDGE_DEV}..."
assign_host_gnb_ip "$GNB1_IP"
assign_host_gnb_ip "$GNB2_IP"

echo "Done.  SA core network is running with host gNB IPs assigned."
echo "Assigned host gNB addresses:"
echo "  - ${GNB1_IP%/*}"
echo "  - ${GNB2_IP%/*}"
echo "Docker bridge: ${BRIDGE_DEV}"
