#!/usr/bin/env bash
# Omarchy portable installer assistant for Arch live ISO.
# Guides users with a TUI (whiptail) and generates an archinstall config
# using machine-specific defaults.

set -Eeuo pipefail

SCRIPT_VERSION="2.0.1"
CONFIG_PATH=""
USE_TUI=0

if command -v whiptail >/dev/null 2>&1; then
  USE_TUI=1
fi

DEFAULT_FOOTER="Enter Select | Esc Cancel | Tab Next | Arrows/jk Move | y/n Quick"

cli_width() {
  local cols=88
  if command -v tput >/dev/null 2>&1; then
    cols="$(tput cols 2>/dev/null || echo 88)"
  fi

  [[ "$cols" =~ ^[0-9]+$ ]] || cols=88
  (( cols < 80 )) && cols=80
  (( cols > 120 )) && cols=120
  echo "$cols"
}

pad_cell() {
  local text="$1"
  local width="$2"
  local out="$text"
  local len=${#out}

  if (( len > width )); then
    if (( width > 3 )); then
      out="${out:0:width-3}..."
    else
      out="${out:0:width}"
    fi
    len=${#out}
  fi

  if (( len < width )); then
    out+=$(printf "%*s" $((width - len)) "")
  fi

  printf "%s" "$out"
}

draw_cli_screen() {
  local title="$1"
  local body="$2"
  local footer="${3:-$DEFAULT_FOOTER}"
  local width inner line

  width="$(cli_width)"
  inner=$((width - 2))

  if [[ -t 1 ]]; then
    printf '\033[2J\033[H'
  fi

  printf '┌%s┐\n' "$(printf '%*s' "$inner" '' | tr ' ' '─')"
  printf '│%s│\n' "$(pad_cell " Omarchy Installer v${SCRIPT_VERSION} | ${title}" "$inner")"
  printf '├%s┤\n' "$(printf '%*s' "$inner" '' | tr ' ' '─')"

  while IFS= read -r line; do
    printf '│%s│\n' "$(pad_cell " ${line}" "$inner")"
  done <<<"$body"

  printf '├%s┤\n' "$(printf '%*s' "$inner" '' | tr ' ' '─')"
  printf '│%s│\n' "$(pad_cell " ${footer}" "$inner")"
  printf '└%s┘\n' "$(printf '%*s' "$inner" '' | tr ' ' '─')"
}

die() {
  echo "Error: $*" >&2
  exit 1
}

need_cmd() {
  local cmd="$1"
  command -v "$cmd" >/dev/null 2>&1 || die "Required command not found: $cmd"
}

trim() {
  sed 's/^[[:space:]]*//;s/[[:space:]]*$//' <<<"$*"
}

json_escape() {
  local s="$1"
  s="${s//\\/\\\\}"
  s="${s//\"/\\\"}"
  s="${s//$'\n'/\\n}"
  s="${s//$'\r'/\\r}"
  s="${s//$'\t'/\\t}"
  printf '%s\n' "$s"
}

prepare_config_path() {
  if [[ -z "$CONFIG_PATH" ]]; then
    CONFIG_PATH="$(mktemp "${TMPDIR:-/tmp}/omarchy_config.XXXXXX")"
  fi
}

cleanup_config_path() {
  if [[ -n "${CONFIG_PATH:-}" && -f "$CONFIG_PATH" ]]; then
    rm -f "$CONFIG_PATH"
  fi
}

validate_generated_json() {
  local config_path="$1"
  local validator=""

  if command -v python3 >/dev/null 2>&1; then
    validator="python3"
  elif command -v python >/dev/null 2>&1; then
    validator="python"
  elif command -v jq >/dev/null 2>&1; then
    validator="jq"
  fi

  if [[ -z "$validator" ]]; then
    die "JSON validation requires python3, python, or jq; none are available."
  fi

  case "$validator" in
    python3|python)
      if ! "$validator" -c 'import json, pathlib, sys; json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))' "$config_path" >/dev/null 2>&1; then
        die "Invalid JSON in $config_path — please report this bug."
      fi
      ;;
    jq)
      if ! jq empty "$config_path" >/dev/null 2>&1; then
        die "Invalid JSON in $config_path — please report this bug."
      fi
      ;;
  esac
}

ask_input() {
  local title="$1"
  local prompt="$2"
  local default_value="${3:-}"
  local value

  if [[ "$USE_TUI" -eq 1 ]]; then
    value=$(whiptail --title "$title" --inputbox "$prompt" 13 78 "$default_value" 3>&1 1>&2 2>&3) || die "Cancelled by user"
  else
    draw_cli_screen "$title" "$prompt

Default: $default_value
" "Type your value and press Enter."
    printf '%s [%s]: ' "$prompt" "$default_value"
    read -r value || die "Cancelled by user"
    value="${value:-$default_value}"
  fi

  trim "$value"
}

ask_password() {
  local title="$1"
  local prompt="$2"
  local value

  if [[ "$USE_TUI" -eq 1 ]]; then
    value=$(whiptail --title "$title" --passwordbox "$prompt" 13 78 3>&1 1>&2 2>&3) || die "Cancelled by user"
  else
    draw_cli_screen "$title" "$prompt

Input is hidden.
" "Type password | Enter Submit | Ctrl+C Cancel"
    printf '%s: ' "$prompt"
    read -r -s value || die "Cancelled by user"
    printf '\n'
  fi

  printf '%s\n' "$value"
}

ask_yes_no() {
  local title="$1"
  local prompt="$2"

  if [[ "$USE_TUI" -eq 1 ]]; then
    whiptail --title "$title" --yesno "$prompt" 14 78
  else
    local selected="no"
    local key rest

    while true; do
      local yes_token="[ Yes ]"
      local no_token="[ No ]"
      [[ "$selected" == "yes" ]] && yes_token="> [ Yes ] <"
      [[ "$selected" == "no" ]] && no_token="> [ No ] <"

      draw_cli_screen "$title" "$prompt

$yes_token   $no_token
" "$DEFAULT_FOOTER"

      IFS= read -r -s -n1 key || {
        echo
        return 1
      }

      if [[ "$key" == $'\x1b' ]]; then
        IFS= read -r -s -n2 -t 0.001 rest || true
        key+="${rest:-}"
      fi

      case "$key" in
        '')
          [[ "$selected" == "yes" ]] && return 0
          return 1
          ;;
        $'\x1b')
          return 1
          ;;
        $'\x1b[C'|$'\x1b[B'|$'\t'|[Ll])
          selected="no"
          ;;
        $'\x1b[D'|$'\x1b[A'|[Hh])
          selected="yes"
          ;;
        [Yy])
          return 0
          ;;
        [Nn])
          return 1
          ;;
      esac
    done
  fi
}

show_message() {
  local title="$1"
  local text="$2"

  if [[ "$USE_TUI" -eq 1 ]]; then
    whiptail --title "$title" --msgbox "$text" 18 78
  else
    draw_cli_screen "$title" "$text" "Enter Continue | Ctrl+C Cancel"
    read -r _ || true
  fi
}

show_menu() {
  local title="$1"
  local prompt="$2"
  shift 2

  if [[ "$USE_TUI" -eq 1 ]]; then
    whiptail --title "$title" --menu "$prompt" 22 90 12 "$@" 3>&1 1>&2 2>&3
  else
    local i
    local tags=()
    local descs=()
    local selected=0
    local key rest
    while (( "$#" )); do
      tags+=("$1")
      descs+=("$2")
      shift 2
    done

    while true; do
      local body="$prompt"$'\n'
      for ((i=0; i<${#tags[@]}; i++)); do
        local prefix="  "
        [[ "$i" -eq "$selected" ]] && prefix="> "
        body+=$'\n'"$prefix$((i+1))) ${tags[$i]} - ${descs[$i]}"
      done
      draw_cli_screen "$title" "$body" "$DEFAULT_FOOTER"

      IFS= read -r -s -n1 key || die "Cancelled by user"
      if [[ "$key" == $'\x1b' ]]; then
        IFS= read -r -s -n2 -t 0.001 rest || true
        key+="${rest:-}"
      fi

      case "$key" in
        '')
          echo "${tags[$selected]}"
          return
          ;;
        $'\x1b')
          die "Cancelled by user"
          ;;
        $'\x1b[A'|[Kk])
          (( selected > 0 )) && ((selected--))
          ;;
        $'\x1b[B'|[Jj])
          (( selected < ${#tags[@]} - 1 )) && ((selected++))
          ;;
        [0-9])
          local pick=$((key))
          if (( pick >= 1 && pick <= ${#tags[@]} )); then
            selected=$((pick - 1))
            echo "${tags[$selected]}"
            return
          fi
          ;;
      esac
    done

  fi
}

format_eta() {
  local total_sec="$1"
  (( total_sec < 0 )) && total_sec=0

  local h=$((total_sec / 3600))
  local m=$(((total_sec % 3600) / 60))
  local s=$((total_sec % 60))

  if (( h > 0 )); then
    printf "%dh %dm %ds" "$h" "$m" "$s"
  elif (( m > 0 )); then
    printf "%dm %ds" "$m" "$s"
  else
    printf "%ds" "$s"
  fi
}

render_bar() {
  local percent="$1"
  local width="${2:-24}"
  local filled=$((percent * width / 100))
  local i
  local bar=""

  for ((i=0; i<filled; i++)); do
    bar+="#"
  done
  for ((i=filled; i<width; i++)); do
    bar+="-"
  done

  printf "%s" "$bar"
}

show_stage_progress() {
  local step="$1"
  local total="$2"
  local label="$3"
  local eta_sec="${4:-0}"
  local percent=$((step * 100 / total))

  if [[ "$USE_TUI" -eq 1 ]]; then
    whiptail --title "Omarchy Installer" --infobox "Step ${step}/${total}\n${label}\nETA ~$(format_eta "$eta_sec")" 10 70
  else
    local bar
    bar="$(render_bar "$percent")"
    printf "[Progress] [%s] %3d%% | %s | ETA ~%s\n" "$bar" "$percent" "$label" "$(format_eta "$eta_sec")"
  fi
}

run_with_eta() {
  local eta_sec="$1"
  local label="$2"
  shift 2
  local log_file
  local cmd_pid
  local start_ts
  local now_ts
  local elapsed
  local remaining
  local percent
  local bar
  local cmd_rc

  log_file="$(mktemp "${TMPDIR:-/tmp}/omarchy-run-with-eta.XXXXXX.log")" || die "Unable to create temporary log file"

  "$@" >"$log_file" 2>&1 &
  cmd_pid=$!
  start_ts="$(date +%s)"

  if [[ "$USE_TUI" -eq 1 ]]; then
    {
      while kill -0 "$cmd_pid" 2>/dev/null; do
        sleep 1
        now_ts="$(date +%s)"
        elapsed=$((now_ts - start_ts))
        percent=0
        remaining=0

        if (( eta_sec > 0 )); then
          percent=$((elapsed * 100 / eta_sec))
          (( percent > 95 )) && percent=95
          remaining=$((eta_sec - elapsed))
          (( remaining < 0 )) && remaining=0
        fi

        echo "XXX"
        echo "$percent"
        printf "%s\nETA ~%s\n" "$label" "$(format_eta "$remaining")"
        echo "XXX"
      done

      echo "XXX"
      echo "100"
      printf "%s\nETA ~0s\n" "$label"
      echo "XXX"
    } | whiptail --title "Omarchy Installer" --gauge "$label" 10 70 0
  else
    while kill -0 "$cmd_pid" 2>/dev/null; do
      sleep 1
      now_ts="$(date +%s)"
      elapsed=$((now_ts - start_ts))
      percent=0
      remaining=0

      if (( eta_sec > 0 )); then
        percent=$((elapsed * 100 / eta_sec))
        (( percent > 95 )) && percent=95
        remaining=$((eta_sec - elapsed))
        (( remaining < 0 )) && remaining=0
      fi

      bar="$(render_bar "$percent")"
      printf "\r[Progress] [%s] %3d%% | %s | ETA ~%s   " "$bar" "$percent" "$label" "$(format_eta "$remaining")"
    done
  fi

  if wait "$cmd_pid"; then
    if [[ "$USE_TUI" -ne 1 ]]; then
      bar="$(render_bar 100)"
      printf "\r[Progress] [%s] 100%% | %s | ETA ~0s   \n" "$bar" "$label"
    fi
    rm -f "$log_file"
    return 0
  fi

  cmd_rc=$?
  printf "\n[Error] %s failed with exit code %d\n" "$label" "$cmd_rc" >&2
  tail -n 20 "$log_file" >&2 || true
  rm -f "$log_file"
  return "$cmd_rc"
}

require_root() {
  [[ "${EUID:-$(id -u)}" -eq 0 ]] || die "Run this script as root (from Arch live ISO)."
}

has_internet() {
  ping -c 1 -W 2 archlinux.org >/dev/null 2>&1 || ping -c 1 -W 2 1.1.1.1 >/dev/null 2>&1
}

collect_wifi_stations() {
  local out
  out="$(iwctl device list 2>/dev/null | awk '
    NF == 0 { next }
    $1 == "Devices" { next }
    $1 == "Name" { next }
    $1 ~ /^-+$/ { next }
    $NF == "station" {
      iface = $1
      if (iface ~ /^(wl|wlan|wlp|wlo|ath|ra)[[:alnum:]_.:-]*$/) {
        print iface
      }
    }
  ' || true)"

  if [[ -z "$out" ]]; then
    out="$(iwctl station list 2>/dev/null | awk '
      NF == 0 { next }
      $1 == "Station" { next }
      $1 == "Devices" { next }
      $1 == "Name" { next }
      $1 ~ /^-+$/ { next }
      {
        iface = $1
        if (iface ~ /^(wl|wlan|wlp|wlo|ath|ra)[[:alnum:]_.:-]*$/) {
          print iface
        }
      }
    ' || true)"
  fi

  printf "%s\n" "$out" | awk 'NF' | awk '!seen[$0]++'
}

collect_wifi_network_ssids() {
  local station="$1"
  iwctl station "$station" get-networks 2>/dev/null | awk '
    NF == 0 { next }
    $0 ~ /^[[:space:]]*Available[[:space:]]+networks/ { next }
    $0 ~ /^\s*Network\s+name/ { next }
    $0 ~ /^\s*-+\s*$/ { next }
    {
      line = $0
      sub(/^[[:space:]>*]+/, "", line)
      if (line == "") next

      if (line ~ /^(Devices|Name|Station|Mode|Security|Signal)([[:space:]]|$)/) next

      split(line, parts, /[[:space:]][[:space:]]+/)
      ssid = parts[1]
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", ssid)

      if (ssid == "" || ssid == "--") next
      if (ssid ~ /^(Devices|Name|Station|Mode|Security|Signal)$/) next

      print ssid
    }
  ' | awk '!seen[$0]++'
}

connect_wifi_with_nmtui() {
  command -v nmtui >/dev/null 2>&1 || return 1

  if command -v systemctl >/dev/null 2>&1; then
    if ! systemctl is-active --quiet NetworkManager 2>/dev/null; then
      run_with_eta 8 "Starting NetworkManager" systemctl start NetworkManager || true
      sleep 1
    fi
  fi

  if command -v nmcli >/dev/null 2>&1; then
    nmcli radio wifi on >/dev/null 2>&1 || true
  fi

  show_message "Wi-Fi Setup" "A network setup screen will open.\n\nSelect your Wi-Fi network and enter password, then exit back to installer."

  while true; do
    nmtui connect || true
    sleep 2

    if has_internet; then
      show_message "Network Ready" "Connected to the internet."
      return 0
    fi

    if ! ask_yes_no "Still Offline" "No internet detected yet. Open Wi-Fi setup again?"; then
      return 1
    fi
  done
}

connect_wifi_interactive() {
  command -v iwctl >/dev/null 2>&1 || {
    show_message "Wi-Fi Unavailable" "iwctl is not available in this live environment. Connect Ethernet if possible."
    return 1
  }

  local station_lines=()
  mapfile -t station_lines < <(collect_wifi_stations)
  if [[ ${#station_lines[@]} -eq 0 ]]; then
    show_message "Wi-Fi Unavailable" "No wireless adapter detected. Connect Ethernet and try again."
    return 1
  fi

  local station_items=()
  local st
  for st in "${station_lines[@]}"; do
    station_items+=("$st" "Wireless interface")
  done

  local station
  if [[ ${#station_lines[@]} -eq 1 ]]; then
    station="${station_lines[0]}"
  else
    station="$(show_menu "Wi-Fi Adapter" "Select wireless adapter:" "${station_items[@]}")"
  fi
  [[ -n "$station" ]] || return 1

  while true; do
    run_with_eta 8 "Scanning Wi-Fi networks on $station" iwctl station "$station" scan || true

    local ssid_lines=()
    mapfile -t ssid_lines < <(collect_wifi_network_ssids "$station")

    local menu_items=()
    local i key
    for ((i=0; i<${#ssid_lines[@]}; i++)); do
      key="net-$i"
      menu_items+=("$key" "${ssid_lines[$i]}")
    done
    menu_items+=("rescan" "Scan again")
    menu_items+=("hidden" "Enter hidden SSID manually")
    menu_items+=("back" "Return to previous menu")

    local choice ssid
    choice="$(show_menu "Wi-Fi Networks" "Choose your Wi-Fi network:" "${menu_items[@]}")"

    case "$choice" in
      rescan)
        continue
        ;;
      hidden)
        ssid="$(ask_input "Wi-Fi" "SSID name:" "")"
        [[ -n "$ssid" ]] || {
          show_message "Wi-Fi" "SSID cannot be empty."
          continue
        }
        ;;
      back)
        return 1
        ;;
      net-*)
        i="${choice#net-}"
        if [[ "$i" =~ ^[0-9]+$ ]] && (( i >= 0 && i < ${#ssid_lines[@]} )); then
          ssid="${ssid_lines[$i]}"
        else
          show_message "Wi-Fi" "Invalid network selection."
          continue
        fi
        ;;
      *)
        show_message "Wi-Fi" "Invalid network selection."
        continue
        ;;
    esac

    local pass
    pass="$(ask_password "Wi-Fi" "Password for '$ssid' (leave empty for open network)")"

    if [[ -n "$pass" ]]; then
      run_with_eta 12 "Connecting to Wi-Fi '$ssid'" iwctl --passphrase "$pass" station "$station" connect "$ssid" || true
    else
      run_with_eta 12 "Connecting to Wi-Fi '$ssid'" iwctl station "$station" connect "$ssid" || true
    fi

    sleep 2
    if has_internet; then
      show_message "Network Ready" "Connected to the internet."
      return 0
    fi

    if ! ask_yes_no "Connection Failed" "Could not confirm internet access. Try another Wi-Fi network?"; then
      return 1
    fi
  done
}

ensure_network_connection() {
  if has_internet; then
    return 0
  fi

  show_message "Network Required" "An internet connection is required for archinstall package download.\n\nIf Ethernet is plugged in, you can retry detection.\nIf using Wi-Fi, the installer opens a guided network setup screen."

  while true; do
    local action
    action="$(show_menu "Network Setup" "No internet detected. Choose an option:" \
      "ethernet" "I connected Ethernet, test again" \
      "wifi" "Connect to Wi-Fi now" \
      "cancel" "Cancel installation")"

    case "$action" in
      ethernet)
        if has_internet; then
          show_message "Network Ready" "Internet connection detected."
          return 0
        fi
        show_message "Still Offline" "No internet detected yet. Check cable/router and try again."
        ;;
      wifi)
        if connect_wifi_interactive; then
          return 0
        fi

        show_message "Wi-Fi Fallback" "Could not complete guided Wi-Fi setup. Opening NetworkManager UI fallback."
        if connect_wifi_with_nmtui; then
          return 0
        fi
        ;;
      cancel)
        die "Cancelled before network setup"
        ;;
    esac
  done
}

normalize_hostname() {
  local raw="$1"
  raw="$(tr '[:upper:]' '[:lower:]' <<<"$raw")"
  raw="$(sed 's/[^a-z0-9-]/-/g; s/--*/-/g; s/^-//; s/-$//' <<<"$raw")"
  if [[ -z "$raw" ]]; then
    raw="omarchy-host"
  fi
  echo "$raw"
}

default_hostname() {
  local product=""
  local board=""

  if [[ -r /sys/class/dmi/id/product_name ]]; then
    product="$(tr '[:upper:]' '[:lower:]' </sys/class/dmi/id/product_name | sed 's/[^a-z0-9]/-/g')"
  fi

  if [[ -r /sys/class/dmi/id/board_name ]]; then
    board="$(tr '[:upper:]' '[:lower:]' </sys/class/dmi/id/board_name | sed 's/[^a-z0-9]/-/g')"
  fi

  product="$(sed 's/--*/-/g; s/^-//; s/-$//' <<<"$product")"
  board="$(sed 's/--*/-/g; s/^-//; s/-$//' <<<"$board")"

  if [[ -n "$product" ]]; then
    echo "omarchy-${product:0:18}"
  elif [[ -n "$board" ]]; then
    echo "omarchy-${board:0:18}"
  else
    echo "omarchy-$(date +%m%d)-$(cut -c1-4 /etc/machine-id 2>/dev/null || echo host)"
  fi
}

default_username() {
  local val
  val="${SUDO_USER:-}"

  if [[ -z "$val" || "$val" == "root" ]]; then
    if [[ -n "${USER:-}" && "${USER}" != "root" ]]; then
      val="$USER"
    else
      val="omarchy"
    fi
  fi

  val="$(tr '[:upper:]' '[:lower:]' <<<"$val" | sed 's/[^a-z0-9_-]//g')"
  [[ -z "$val" ]] && val="omarchy"
  echo "$val"
}

default_timezone() {
  local tz=""

  if command -v timedatectl >/dev/null 2>&1; then
    tz="$(timedatectl show -p Timezone --value 2>/dev/null || true)"
  fi

  if [[ -z "$tz" || "$tz" == "n/a" ]]; then
    tz="$(cat /etc/timezone 2>/dev/null || true)"
  fi

  if [[ -z "$tz" ]] && command -v curl >/dev/null 2>&1; then
    tz="$(curl -fsSL --max-time 3 https://ipapi.co/timezone 2>/dev/null || true)"
  fi

  [[ -z "$tz" ]] && tz="UTC"
  echo "$tz"
}

cpu_ucode_pkg() {
  local vendor
  vendor="$(awk -F: '/vendor_id/{print $2; exit}' /proc/cpuinfo | tr -d ' ')"
  case "$vendor" in
    GenuineIntel) echo "intel-ucode" ;;
    AuthenticAMD) echo "amd-ucode" ;;
    *) echo "" ;;
  esac
}

collect_disks() {
  lsblk -dn -o NAME,SIZE,TYPE,MODEL -P | awk '
    {
      name=""; size=""; type=""; model="";
      if (match($0, /NAME="[^"]*"/)) {
        name = substr($0, RSTART + 6, RLENGTH - 7)
      }
      if (match($0, /SIZE="[^"]*"/)) {
        size = substr($0, RSTART + 6, RLENGTH - 7)
      }
      if (match($0, /TYPE="[^"]*"/)) {
        type = substr($0, RSTART + 6, RLENGTH - 7)
      }
      if (match($0, /MODEL="[^"]*"/)) {
        model = substr($0, RSTART + 7, RLENGTH - 8)
      }
      if (type == "disk") {
        print name "|" size "|" model
      }
    }
  '
}

pick_default_disk() {
  local candidate
  candidate="$(collect_disks | awk -F'|' '{print "/dev/" $1, $2}' | sort -k2 -h | tail -n1 | awk '{print $1}')"
  [[ -n "$candidate" ]] && echo "$candidate"
}

find_efi_partition() {
  local disk="$1"
  local efi

  efi="$(lsblk -prno NAME,PARTTYPE,FSTYPE "$disk" | awk 'tolower($2)=="c12a7328-f81f-11d2-ba4b-00a0c93ec93b" {print $1; exit}')"

  if [[ -z "$efi" ]]; then
    efi="$(lsblk -prno NAME,FSTYPE,MOUNTPOINT "$disk" | awk 'tolower($2)=="vfat" && ($3=="/boot" || $3=="/boot/efi") {print $1; exit}')"
  fi

  echo "$efi"
}

bytes_to_gib() {
  local bytes="$1"
  awk -v b="$bytes" 'BEGIN {printf "%.0f", b/(1024*1024*1024)}'
}

free_bytes_on_disk() {
  local disk="$1"
  local sector_size first_free last_free free_sectors

  sector_size="$(blockdev --getss "$disk" 2>/dev/null)"
  [[ "$sector_size" =~ ^[0-9]+$ ]] || sector_size=512

  first_free="$(sgdisk -F "$disk" 2>/dev/null | tr -d '[:space:]')"
  last_free="$(sgdisk -E "$disk" 2>/dev/null | tr -d '[:space:]')"

  if [[ "$first_free" =~ ^[0-9]+$ && "$last_free" =~ ^[0-9]+$ ]] && (( last_free >= first_free )); then
    free_sectors=$(( last_free - first_free + 1 ))
    echo $(( free_sectors * sector_size ))
    return
  fi

  free_sectors="$(sgdisk -p "$disk" 2>/dev/null | awk '/Total free space is/ {for(i=1;i<=NF;i++){if($i=="sectors") {print $(i-1); exit}}}')"
  if [[ "$free_sectors" =~ ^[0-9]+$ ]]; then
    echo $(( free_sectors * sector_size ))
    return
  fi

  echo 0
}

validate_username() {
  local username="$1"
  [[ "$username" =~ ^[a-z_][a-z0-9_-]*$ ]]
}

create_root_partition() {
  local disk="$1"
  local first_free last_free
  first_free="$(sgdisk -F "$disk" 2>/dev/null | tr -d '[:space:]')"
  last_free="$(sgdisk -E "$disk" 2>/dev/null | tr -d '[:space:]')"

  [[ "$first_free" =~ ^[0-9]+$ ]] || die "Could not determine first free sector on $disk"
  [[ "$last_free" =~ ^[0-9]+$ ]] || die "Could not determine last free sector on $disk"
  (( last_free >= first_free )) || die "Invalid free-space bounds on $disk (${first_free}-${last_free})"

  sgdisk -n "0:${first_free}:${last_free}" -t 0:8300 -c 0:"OmarchyRoot" "$disk"
  partprobe "$disk"
  command -v udevadm >/dev/null 2>&1 && udevadm settle 2>/dev/null || sleep 2
}

generate_archinstall_config() {
  local disk="$1"
  local efi_part="$2"
  local root_part="$3"
  local hostname="$4"
  local username="$5"
  local user_password="$6"
  local enc_password="$7"
  local timezone="$8"
  local bootloader="$9"
  local kb_layout="${10}"
  local ucode_pkg="${11}"

  local -a pkg_list=("base" "base-devel" "linux-firmware" "git" "vim" "btrfs-progs" "sudo" "networkmanager" "wpa_supplicant")
  if [[ -n "$ucode_pkg" ]]; then
    pkg_list+=("$ucode_pkg")
  fi

  local pkg_json=""
  local _i
  for ((_i=0; _i<${#pkg_list[@]}; _i++)); do
    (( _i > 0 )) && pkg_json+=","
    pkg_json+=$'\n'"        \"${pkg_list[$_i]}\""
  done

  local j_disk j_efi_part j_root_part j_hostname j_username j_user_password j_enc_password j_timezone j_bootloader j_kb_layout
  prepare_config_path
  j_disk="$(json_escape "$disk")"
  j_efi_part="$(json_escape "$efi_part")"
  j_root_part="$(json_escape "$root_part")"
  j_hostname="$(json_escape "$hostname")"
  j_username="$(json_escape "$username")"
  j_user_password="$(json_escape "$user_password")"
  j_enc_password="$(json_escape "$enc_password")"
  j_timezone="$(json_escape "$timezone")"
  j_bootloader="$(json_escape "$bootloader")"
  j_kb_layout="$(json_escape "$kb_layout")"

  cat >"$CONFIG_PATH" <<EOF
{
  "archinstall-language": "English",
  "audio_config": {
    "audio": "pipewire"
  },
  "bootloader_config": {
    "bootloader": "$j_bootloader"
  },
  "disk_config": {
    "config_type": "manual_partitioning",
    "device_modifications": [
      {
        "device": "$j_disk",
        "partitions": [
          {
            "dev_name": "$j_efi_part",
            "mountpoint": "/boot",
            "fs_type": "vfat",
            "wipe": false
          },
          {
            "dev_name": "$j_root_part",
            "mountpoint": "/",
            "fs_type": "btrfs",
            "btrfs": {
              "subvolumes": [
                {"name": "@", "mountpoint": "/"},
                {"name": "@home", "mountpoint": "/home"},
                {"name": "@log", "mountpoint": "/var/log"},
                {"name": "@pkg", "mountpoint": "/var/cache/pacman/pkg"},
                {"name": "@snapshots", "mountpoint": "/.snapshots"}
              ]
            },
            "encrypted": true,
            "encryption_password": "$j_enc_password",
            "encryption_type": "luks2",
            "wipe": true
          }
        ]
      }
    ]
  },
  "hostname": "$j_hostname",
  "kernels": ["linux"],
  "locale_config": {
    "kb_layout": "$j_kb_layout",
    "sys_enc": "UTF-8",
    "sys_lang": "en_US"
  },
  "network_config": {
    "type": "nm"
  },
  "ntp": true,
  "packages": [$pkg_json
  ],
  "profile_config": {
    "profile": {
      "main": "Minimal"
    }
  },
  "timezone": "$j_timezone",
  "users": [
    {
      "username": "$j_username",
      "password": "$j_user_password",
      "is_superuser": true
    }
  ]
}
EOF
}

trap cleanup_config_path EXIT

main() {
  show_stage_progress 1 7 "Prerequisite checks" 40
  need_cmd lsblk
  need_cmd sgdisk
  need_cmd blockdev
  need_cmd partprobe
  need_cmd archinstall
  need_cmd ping

  require_root
  show_stage_progress 2 7 "Network connectivity" 45
  ensure_network_connection
  show_stage_progress 3 7 "Disk discovery and system defaults" 30

  show_message "Omarchy Installer" "Omarchy Portable Setup v${SCRIPT_VERSION}\n\nThis assistant will:\n- Detect your disk/EFI automatically\n- Create and encrypt a new Linux partition\n- Generate an archinstall config\n- Start installation after your confirmation\n\nProceed only if you have backups."

  local disk_lines
  mapfile -t disk_lines < <(collect_disks)
  [[ ${#disk_lines[@]} -gt 0 ]] || die "No disks detected"

  local default_disk
  default_disk="$(pick_default_disk)"

  local menu_items=()
  local line name size model desc
  for line in "${disk_lines[@]}"; do
    name="${line%%|*}"
    size_model="${line#*|}"
    size="${size_model%%|*}"
    model="${size_model#*|}"
    desc="${size} ${model}"
    if [[ "/dev/$name" == "$default_disk" ]]; then
      desc+=" [default]"
    fi
    menu_items+=("/dev/$name" "$desc")
  done

  local selected_disk
  selected_disk="$(show_menu "Disk Selection" "Choose the target disk (Windows/EFI preserved, new Linux partition added):" "${menu_items[@]}")"
  [[ -b "$selected_disk" ]] || die "Invalid disk selected: $selected_disk"

  local efi_part
  efi_part="$(find_efi_partition "$selected_disk")"

  if [[ -z "$efi_part" ]]; then
    local efi_hint="${selected_disk}1"
    if [[ "$selected_disk" =~ [0-9]$ ]]; then
      efi_hint="${selected_disk}p1"
    fi
    efi_part="$(ask_input "EFI Partition" "Could not auto-detect EFI partition. Enter EFI partition path:" "$efi_hint")"
  fi

  [[ -b "$efi_part" ]] || die "EFI partition does not exist: $efi_part"

  local free_bytes free_gib
  free_bytes="$(free_bytes_on_disk "$selected_disk")"
  free_gib="$(bytes_to_gib "$free_bytes")"

  local min_free_bytes=$((40 * 1024 * 1024 * 1024))
  if (( free_bytes < min_free_bytes )); then
    die "Only ${free_gib} GiB free on $selected_disk. At least 40 GiB unallocated space is required."
  fi

  local default_hostname_val default_username_val default_tz_val
  default_hostname_val="$(normalize_hostname "$(default_hostname)")"
  default_username_val="$(default_username)"
  default_tz_val="$(default_timezone)"

  local hostname username timezone kb_layout bootloader
  hostname="$(normalize_hostname "$(ask_input "System" "Hostname:" "$default_hostname_val")")"

  while true; do
    username="$(ask_input "System" "Primary username:" "$default_username_val")"
    if validate_username "$username"; then
      break
    fi
    show_message "Invalid Username" "Use lowercase letters, numbers, underscore, and hyphen. Must start with a letter or underscore."
  done

  timezone="$(ask_input "Locale" "Timezone (for example America/New_York):" "$default_tz_val")"
  kb_layout="$(ask_input "Locale" "Keyboard layout (for example us, uk, de):" "us")"

  bootloader="$(show_menu "Bootloader" "Select bootloader:" \
    "limine" "Best Omarchy compatibility" \
    "systemd-boot" "Simple UEFI bootloader" \
    "grub" "Broad hardware compatibility")"

  local user_pass1 user_pass2 enc_pass1 enc_pass2
  while true; do
    user_pass1="$(ask_password "Credentials" "User password")"
    user_pass2="$(ask_password "Credentials" "Confirm user password")"
    [[ -n "$user_pass1" ]] || { show_message "Invalid Password" "Password cannot be empty."; continue; }
    [[ "$user_pass1" == "$user_pass2" ]] && break
    show_message "Password Mismatch" "User passwords did not match. Try again."
  done

  while true; do
    enc_pass1="$(ask_password "Encryption" "Disk encryption password")"
    enc_pass2="$(ask_password "Encryption" "Confirm encryption password")"
    [[ -n "$enc_pass1" ]] || { show_message "Invalid Password" "Encryption password cannot be empty."; continue; }
    [[ "$enc_pass1" == "$enc_pass2" ]] && break
    show_message "Password Mismatch" "Encryption passwords did not match. Try again."
  done

  local ucode_pkg
  ucode_pkg="$(cpu_ucode_pkg)"
  show_stage_progress 4 7 "Configuration input completed" 25

  show_message "Partition Plan" "Target disk: $selected_disk\nEFI partition: $efi_part\nUnallocated space: ${free_gib} GiB\n\nThe installer will create ONE new Linux partition using available free space and will not reformat EFI."

  if ! ask_yes_no "Confirm Partitioning" "Create a new Linux partition on $selected_disk using available unallocated space?"; then
    die "Cancelled before partitioning"
  fi

  local -a before_parts after_parts root_candidates
  local root_part
  mapfile -t before_parts < <(lsblk -nrpo NAME "$selected_disk")
  local before_parts_count="${#before_parts[@]}"
  show_stage_progress 5 7 "Creating Linux partition" 30
  run_with_eta 30 "Partition creation on $selected_disk" create_root_partition "$selected_disk"

  mapfile -t after_parts < <(lsblk -nrpo NAME "$selected_disk")
  local after_parts_count="${#after_parts[@]}"
  if (( after_parts_count <= before_parts_count )); then
    die "Partition creation appears to have failed"
  fi

  root_part="$(comm -13 <(printf '%s\n' "${before_parts[@]}" | sort) <(printf '%s\n' "${after_parts[@]}" | sort) | head -n1)"
  if [[ -z "$root_part" ]]; then
    mapfile -t root_candidates < <(lsblk -nrpo NAME,PARTLABEL "$selected_disk" | awk '$2=="OmarchyRoot" {print $1}')
    root_part="$(comm -13 <(printf '%s\n' "${before_parts[@]}" | sort) <(printf '%s\n' "${root_candidates[@]}" | sort) | tail -n1)"
  fi

  [[ -b "$root_part" ]] || die "Could not determine newly created root partition"

  generate_archinstall_config \
    "$selected_disk" \
    "$efi_part" \
    "$root_part" \
    "$hostname" \
    "$username" \
    "$user_pass1" \
    "$enc_pass1" \
    "$timezone" \
    "$bootloader" \
    "$kb_layout" \
    "$ucode_pkg"

  local summary
  summary="Ready to install:\n\nDisk: $selected_disk\nEFI: $efi_part\nRoot: $root_part\nHostname: $hostname\nUser: $username\nTimezone: $timezone\nKeyboard: $kb_layout\nBootloader: $bootloader"
  if [[ -n "$ucode_pkg" ]]; then
    summary+="\nMicrocode package: $ucode_pkg"
  fi
  summary+="\n\nConfig written: $CONFIG_PATH"

  show_message "Install Summary" "$summary"
  show_stage_progress 6 7 "Installer config generated" 20

  if ! ask_yes_no "Start Install" "Run archinstall now with this generated config?"; then
    die "Cancelled before archinstall"
  fi

  # Strip any stray carriage-return bytes (Windows CRLF) from generated JSON
  if command -v sed >/dev/null 2>&1; then
    sed -i 's/\r$//' "$CONFIG_PATH" 2>/dev/null || true
  fi

  # Validate JSON before running archinstall
  validate_generated_json "$CONFIG_PATH"

  show_stage_progress 7 7 "Running archinstall" 1800
  run_with_eta 1800 "archinstall base installation" archinstall --config "$CONFIG_PATH"

  show_message "Complete" "Base installation completed.\n\nNext steps after reboot:\n1. Log in as $username\n2. Run: curl -fsSL https://omarchy.org/install | bash\n\nIf Windows entry is missing, run: sudo limine-update"
}

main "$@"
