#!/usr/bin/env bash

set -euo pipefail
umask 077

DRY_RUN=false
usage() {
    printf 'Usage: %s [--dry-run]\n' "${0##*/}"
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    usage
    exit 0
fi
if (( $# > 1 )) || { (( $# == 1 )) && [[ "$1" != "--dry-run" ]]; }; then
    usage >&2
    exit 2
fi
if (( $# == 1 )); then
    DRY_RUN=true
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$PROJECT_DIR/.env"
CHANGES_FILE="$(mktemp "${TMPDIR:-/tmp}/baby-buddy-changes.XXXXXX")"
CHANGE_INPUT_FILE="$(mktemp "${TMPDIR:-/tmp}/baby-buddy-change-input.XXXXXX")"
READBACK_FILE="$(mktemp "${TMPDIR:-/tmp}/baby-buddy-readback.XXXXXX")"

cleanup() {
    rm -f -- "$CHANGES_FILE" "$CHANGE_INPUT_FILE" "$READBACK_FILE"
}
trap cleanup EXIT

for command in gum python3; do
    if ! command -v "$command" >/dev/null 2>&1; then
        printf 'Required command not found: %s\n' "$command" >&2
        exit 1
    fi
done

get_env() {
    python3 - "$ENV_FILE" "$1" <<'PY'
import os
import sys

path, wanted = sys.argv[1:]
if not os.path.exists(path):
    raise SystemExit(0)

with open(path, encoding="utf-8") as env_file:
    for raw_line in env_file:
        line = raw_line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            if key.strip() == wanted:
                result = value.strip()

if "result" in locals():
    print(result, end="")
PY
}

get_prompt_value() {
    python3 - "$ENV_FILE" "$CHANGES_FILE" "$1" <<'PY'
import os
import sys

env_path, changes_path, wanted = sys.argv[1:]

def read_values(path):
    values = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as source:
            for raw_line in source:
                line = raw_line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    values[key.strip()] = value.strip()
    return values

values = read_values(env_path)
values.update(read_values(changes_path))
if wanted in values:
    print(values[wanted], end="")
PY
}

pending_count() {
    wc -l < "$CHANGES_FILE" | tr -d '[:space:]'
}

mask_value() {
    if [[ -n "$1" ]]; then
        printf '[set]'
    else
        printf '[empty]'
    fi
}

show_current_config() {
    local reveal=false choice key value label

    if gum confirm --default=false "Reveal Wi-Fi password and parent API tokens?"; then
        reveal=true
    fi

    printf '\nCurrent device configuration (%s)\n\n' "$ENV_FILE"
    while IFS='|' read -r key label; do
        value="$(get_env "$key")"
        case "$key" in
            WIFI_PASSWORD|PARENT_1_TOKEN|PARENT_2_TOKEN)
                if [[ "$reveal" == true ]]; then
                    printf '  %-26s %s\n' "$label" "${value:-[empty]}"
                else
                    printf '  %-26s %s\n' "$label" "$(mask_value "$value")"
                fi
                ;;
            *)
                printf '  %-26s %s\n' "$label" "${value:-[empty]}"
                ;;
        esac
    done <<'KEYS'
WIFI_SSID|Wi-Fi SSID
WIFI_PASSWORD|Wi-Fi password
BABY_BUDDY_BASE_URL|Baby Buddy URL
CHILD_ID|Child ID
CHILD_SLUG|Child slug
TIMEZONE_OFFSET_MINUTES|Timezone offset (minutes)
PARENT_1_NAME|Parent 1 name
PARENT_1_TOKEN|Parent 1 API token
PARENT_1_TAG|Parent 1 feeding tag
PARENT_2_NAME|Parent 2 name
PARENT_2_TOKEN|Parent 2 API token
PARENT_2_TAG|Parent 2 feeding tag
KEYS
    printf '\n'
    if [[ -s "$CHANGES_FILE" ]]; then
        gum style --foreground 3 "$(pending_count) staged edit(s) are not reflected above."
    fi
    gum style --foreground 8 'Values are read from local .env; empty means unset.'
    printf '\n'
    read -r -p 'Press Enter to return to menu. '
}

record_change() {
    local key="$1" value="$2"
    printf '%s\0%s' "$key" "$value" > "$CHANGE_INPUT_FILE"
    python3 - "$ENV_FILE" "$CHANGES_FILE" "$CHANGE_INPUT_FILE" <<'PY'
import os
import sys

env_path, changes_path, input_path = sys.argv[1:]

def read_values(path):
    values = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as source:
            for raw_line in source:
                line = raw_line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    values[key.strip()] = value.strip()
    return values

key_bytes, value_bytes = open(input_path, "rb").read().split(b"\0", 1)
key, value = key_bytes.decode(), value_bytes.decode()
saved = read_values(env_path)
staged = read_values(changes_path)
if saved.get(key, "") == value:
    staged.pop(key, None)
else:
    staged[key] = value

with open(changes_path, "w", encoding="utf-8") as output:
    for staged_key, staged_value in staged.items():
        output.write(f"{staged_key}={staged_value}\n")
PY
}

prompt_value() {
    local key="$1" label="$2" current value
    current="$(get_prompt_value "$key")"
    if ! value="$(gum input --header "$label" --value "$current")"; then
        return 1
    fi
    record_change "$key" "$value"
}

prompt_secret() {
    local key="$1" label="$2" current choice value
    current="$(get_prompt_value "$key")"

    if [[ -n "$current" ]]; then
        if ! choice="$(gum choose --header "$label (current value is hidden)" \
            "Keep current" "Enter new value" "Clear value")"; then
            return 1
        fi
        case "$choice" in
            "Keep current") return 0 ;;
            "Clear value") record_change "$key" ""; return 0 ;;
            "Enter new value") ;;
            *) return 1 ;;
        esac
    else
        if ! choice="$(gum choose --header "$label" "Enter value" "Leave empty")"; then
            return 1
        fi
        [[ "$choice" == "Enter value" ]] || return 0
    fi

    if ! value="$(gum input --password --header "Enter $label")"; then
        return 1
    fi
    record_change "$key" "$value"
}

edit_wifi() {
    prompt_value WIFI_SSID "Wi-Fi SSID" &&
        prompt_secret WIFI_PASSWORD "Wi-Fi password"
}

edit_baby_buddy() {
    prompt_value BABY_BUDDY_BASE_URL "Baby Buddy base URL" &&
        prompt_value CHILD_ID "Child ID" &&
        prompt_value CHILD_SLUG "Child slug"
}

edit_timezone() {
    prompt_value TIMEZONE_OFFSET_MINUTES "Timezone offset in minutes (e.g. -300)"
}

edit_parent() {
    local number="$1" label
    label="Parent $number"
    prompt_value "PARENT_${number}_NAME" "$label name" &&
        prompt_secret "PARENT_${number}_TOKEN" "$label API token" &&
        prompt_value "PARENT_${number}_TAG" "$label feeding tag"
}

discard_changes() {
    local count
    count="$(pending_count)"
    if [[ ! -s "$CHANGES_FILE" ]]; then
        gum style --foreground 8 "No staged changes to discard."
        return 0
    fi
    if gum confirm --default=false "Discard $count staged change(s)?"; then
        : > "$CHANGES_FILE"
        gum style --foreground 3 "Staged changes discarded."
    fi
}

edit_settings() {
    local action count header
    local -a options

    while true; do
        count="$(pending_count)"
        header="Choose one section to edit. $count change(s) staged."
        options=("Wi-Fi" "Baby Buddy / child" "Timezone" "Parent 1" "Parent 2")
        if [[ -s "$CHANGES_FILE" ]]; then
            options+=("Review pending changes" "Discard staged changes")
        fi
        options+=("Back to main menu")

        action="$(gum choose --header "$header" "${options[@]}")" || return 0
        case "$action" in
            "Wi-Fi")
                if ! edit_wifi; then
                    gum style --foreground 3 "Section edit stopped; completed entries remain staged."
                fi
                ;;
            "Baby Buddy / child")
                if ! edit_baby_buddy; then
                    gum style --foreground 3 "Section edit stopped; completed entries remain staged."
                fi
                ;;
            "Timezone")
                if ! edit_timezone; then
                    gum style --foreground 3 "Section edit stopped; completed entries remain staged."
                fi
                ;;
            "Parent 1")
                if ! edit_parent 1; then
                    gum style --foreground 3 "Section edit stopped; completed entries remain staged."
                fi
                ;;
            "Parent 2")
                if ! edit_parent 2; then
                    gum style --foreground 3 "Section edit stopped; completed entries remain staged."
                fi
                ;;
            "Review pending changes")
                save_and_upload_changes || true
                ;;
            "Discard staged changes")
                discard_changes
                ;;
            "Back to main menu")
                return 0
                ;;
        esac
    done
}

validate_changes() {
    local key value

    while IFS='=' read -r key value; do
        case "$key" in
            CHILD_ID)
                if [[ ! "$value" =~ ^[1-9][0-9]*$ ]]; then
                    gum style --foreground 1 "Child ID must be a positive integer."
                    return 1
                fi
                ;;
            TIMEZONE_OFFSET_MINUTES)
                if [[ ! "$value" =~ ^-?(0|[1-9][0-9]{0,2})$ ]] || (( value < -720 || value > 840 )); then
                    gum style --foreground 1 "Timezone offset must be an integer from -720 to 840."
                    return 1
                fi
                ;;
            BABY_BUDDY_BASE_URL)
                if [[ ! "$value" =~ ^https?:// ]] || [[ "$value" == */ ]]; then
                    gum style --foreground 1 "Baby Buddy URL must start with http:// or https:// and have no trailing slash."
                    return 1
                fi
                ;;
        esac
    done < "$CHANGES_FILE"
}

display_changes() {
    local key value label previous shown_previous shown_value

    printf '\nPending changes (.env -> proposed)\n\n'
    while IFS='=' read -r key value; do
        previous="$(get_env "$key")"
        case "$key" in
            WIFI_SSID) label="Wi-Fi SSID" ;;
            WIFI_PASSWORD) label="Wi-Fi password" ;;
            BABY_BUDDY_BASE_URL) label="Baby Buddy URL" ;;
            CHILD_ID) label="Child ID" ;;
            CHILD_SLUG) label="Child slug" ;;
            TIMEZONE_OFFSET_MINUTES) label="Timezone offset" ;;
            PARENT_1_NAME) label="Parent 1 name" ;;
            PARENT_1_TOKEN) label="Parent 1 API token" ;;
            PARENT_1_TAG) label="Parent 1 feeding tag" ;;
            PARENT_2_NAME) label="Parent 2 name" ;;
            PARENT_2_TOKEN) label="Parent 2 API token" ;;
            PARENT_2_TAG) label="Parent 2 feeding tag" ;;
            *) label="$key" ;;
        esac
        case "$key" in
            WIFI_PASSWORD|PARENT_1_TOKEN|PARENT_2_TOKEN)
                shown_previous="$(mask_value "$previous")"
                shown_value="$(mask_value "$value")"
                ;;
            *)
                shown_previous="${previous:-[empty]}"
                shown_value="${value:-[empty]}"
                ;;
        esac
        printf '  %-26s %s  ->  %s\n' "$label" "$shown_previous" "$shown_value"
    done < "$CHANGES_FILE"
    printf '\n'
}

select_port() {
    local candidate
    local -a ports=()

    for candidate in \
        /dev/cu.usbmodem* /dev/cu.usbserial* \
        /dev/tty.usbmodem* /dev/tty.usbserial* \
        /dev/ttyACM* /dev/ttyUSB*; do
        [[ -e "$candidate" ]] && ports+=("$candidate")
    done

    if (( ${#ports[@]} == 0 )); then
        gum style --foreground 1 "No USB serial device found. Connect the Pico and try again."
        return 1
    elif (( ${#ports[@]} == 1 )); then
        printf '%s' "${ports[0]}"
    else
        gum choose --header "Select Pico serial port" "${ports[@]}"
    fi
}

require_ampy() {
    if ! command -v ampy >/dev/null 2>&1; then
        gum style --foreground 1 "Required command not found: ampy"
        return 1
    fi
}

upload_config() {
    local port

    if [[ "$DRY_RUN" == true ]]; then
        gum style --foreground 3 "Upload disabled in dry-run mode."
        return 1
    fi
    if [[ ! -f "$ENV_FILE" ]]; then
        gum style --foreground 1 "No local .env file found at $ENV_FILE"
        return 1
    fi
    if ! require_ampy; then
        return 1
    fi
    if ! port="$(select_port)"; then
        return 1
    fi

    upload_to_port "$port"
}

upload_to_port() {
    local port="$1"

    if [[ "$DRY_RUN" == true ]]; then
        gum style --foreground 3 "Upload disabled in dry-run mode."
        return 1
    fi

    gum style --foreground 6 "Uploading .env to $port..."
    if ! ampy --port "$port" put "$ENV_FILE" .env; then
        gum style --foreground 1 "Upload failed."
        return 1
    fi

    if ampy --port "$port" get .env "$READBACK_FILE" >/dev/null 2>&1; then
        if cmp -s "$ENV_FILE" "$READBACK_FILE"; then
            gum style --foreground 2 "Upload verified."
        else
            gum style --foreground 3 "Upload completed, but read-back did not match local .env."
            return 1
        fi
    else
        gum style --foreground 3 "Upload completed; device read-back verification unavailable."
    fi
}

save_and_upload_changes() {
    local backup timestamp suffix port

    if [[ ! -s "$CHANGES_FILE" ]]; then
        gum style --foreground 8 "No staged changes to review."
        return 0
    fi
    if ! validate_changes; then
        return 1
    fi
    display_changes
    if [[ "$DRY_RUN" == true ]]; then
        gum style --foreground 3 "Dry run complete. .env unchanged; device upload skipped."
        return 0
    fi
    if ! gum confirm --default=false "Save these changes locally and upload to Pico?"; then
        gum style --foreground 3 "Changes remain staged."
        return 0
    fi
    if ! require_ampy; then
        return 1
    fi
    if ! port="$(select_port)"; then
        return 1
    fi

    if [[ -f "$ENV_FILE" ]]; then
        timestamp="$(date '+%Y%m%d-%H%M%S')"
        backup="$ENV_FILE.bak.$timestamp"
        suffix=1
        while [[ -e "$backup" ]]; do
            backup="$ENV_FILE.bak.$timestamp.$suffix"
            ((suffix += 1))
        done
        if ! cp -p "$ENV_FILE" "$backup" || ! chmod 600 "$backup"; then
            gum style --foreground 1 "Could not create a secure .env backup."
            return 1
        fi
        gum style --foreground 8 "Backup saved: $backup"
    fi

    if ! python3 - "$ENV_FILE" "$CHANGES_FILE" <<'PY'
import os
import sys
import tempfile

env_path, changes_path = sys.argv[1:]
changes = {}
with open(changes_path, encoding="utf-8") as changes_file:
    for line in changes_file:
        key, value = line.rstrip("\n").split("=", 1)
        changes[key] = value

try:
    with open(env_path, encoding="utf-8", newline="") as env_file:
        lines = env_file.readlines()
except FileNotFoundError:
    lines = []

updated = []
found = set()
for line in lines:
    body = line.rstrip("\r\n")
    stripped = body.strip()
    if stripped and not stripped.startswith("#") and "=" in stripped:
        key = stripped.split("=", 1)[0].strip()
        if key in changes:
            ending = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
            updated.append(f"{key}={changes[key]}{ending}")
            found.add(key)
            continue
    updated.append(line)

for key, value in changes.items():
    if key not in found:
        if updated and not updated[-1].endswith(("\n", "\r")):
            updated[-1] += "\n"
        updated.append(f"{key}={value}\n")

directory = os.path.dirname(env_path)
fd, temporary_path = tempfile.mkstemp(prefix=".env.", dir=directory, text=True)
try:
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as output:
        output.writelines(updated)
    os.chmod(temporary_path, 0o600)
    os.replace(temporary_path, env_path)
except BaseException:
    try:
        os.unlink(temporary_path)
    except FileNotFoundError:
        pass
    raise
PY
    then
        gum style --foreground 1 "Could not save .env."
        return 1
    fi

    : > "$CHANGES_FILE"
    if upload_to_port "$port"; then
        gum style --foreground 2 "Configuration saved and uploaded."
    else
        gum style --foreground 1 "Configuration saved locally; upload failed. Use Upload saved .env to retry."
        return 1
    fi
}

while true; do
    count="$(pending_count)"
    header="Baby Buddy Pico configuration"
    options=("View current config" "Edit settings")
    if [[ "$DRY_RUN" == true ]]; then
        header="$header (dry run)"
    fi
    if [[ -s "$CHANGES_FILE" ]]; then
        header="$header — $count change(s) staged"
        options+=("Review pending changes" "Discard staged changes")
    elif [[ "$DRY_RUN" == false ]]; then
        options+=("Upload saved .env")
    fi
    options+=("Quit")

    action="$(gum choose --header "$header" "${options[@]}")" || exit 0

    case "$action" in
        "View current config")
            show_current_config
            ;;
        "Edit settings")
            edit_settings
            ;;
        "Review pending changes")
            save_and_upload_changes || true
            ;;
        "Discard staged changes")
            discard_changes
            ;;
        "Upload saved .env")
            upload_config || true
            ;;
        "Quit")
            if [[ -s "$CHANGES_FILE" ]] &&
                ! gum confirm --default=false "Quit and discard $(pending_count) staged change(s)?"; then
                continue
            fi
            exit 0
            ;;
    esac
done
