"""Hardware-independent configuration validation for the Pico W app."""


def load_env_lines(lines):
    """Parse KEY=VALUE lines without requiring python-dotenv."""
    values = {}
    for raw_line in lines:
        line = raw_line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def parse_child_id(raw_value):
    try:
        child_id = int(raw_value)
    except (TypeError, ValueError):
        return None
    return child_id if child_id > 0 else None


def parse_timezone_offset(raw_value):
    try:
        offset = int(raw_value)
    except (TypeError, ValueError):
        return None
    return offset if -720 <= offset <= 840 else None


def validate_config(
    ssid, base_url, child_slug, child_id, timezone_offset, parents
):
    """Return actionable local configuration errors; do not expose secrets."""
    errors = []
    if not ssid:
        errors.append("WIFI_SSID is required")

    if not base_url or not (
        base_url.startswith("http://") or base_url.startswith("https://")
    ):
        errors.append("BABY_BUDDY_BASE_URL must use http:// or https://")
    elif base_url.endswith("/"):
        errors.append("BABY_BUDDY_BASE_URL must not end with /")
    elif any(char.isspace() for char in base_url):
        errors.append("BABY_BUDDY_BASE_URL must not contain whitespace")
    elif not base_url.split("://", 1)[1].split("/", 1)[0]:
        errors.append("BABY_BUDDY_BASE_URL must include a host")
    elif "?" in base_url or "#" in base_url:
        errors.append("BABY_BUDDY_BASE_URL must not contain query or fragment")
    elif "@" in base_url.split("://", 1)[1].split("/", 1)[0]:
        errors.append("BABY_BUDDY_BASE_URL must not contain credentials")

    if not child_slug or any(
        not (
            "a" <= char <= "z"
            or "A" <= char <= "Z"
            or "0" <= char <= "9"
            or char in "-_"
        )
        for char in child_slug
    ):
        errors.append("CHILD_SLUG is required and must be a single path segment")
    if child_id is None or child_id <= 0:
        errors.append("CHILD_ID must be a positive integer")
    if timezone_offset is None:
        errors.append("TIMEZONE_OFFSET_MINUTES must be from -720 to 840")

    for key, parent in parents.items():
        if not parent.get("api_token"):
            errors.append("%s token is required" % parent.get("name", key))
        if not parent.get("tag"):
            errors.append("%s tag is required" % parent.get("name", key))

    return errors


def child_id_matches(child_payload, configured_child_id):
    """Return true only when child detail response matches configured ID."""
    if not isinstance(child_payload, dict):
        return False
    try:
        return int(child_payload.get("id")) == int(configured_child_id)
    except (TypeError, ValueError):
        return False
