#!/bin/sh
# Generate api_keys.json from DOWNLOAD_API_KEY environment variable
# so the yt-dlp-host sidecar and main app share the same key.

KEYS_FILE="/app/jsons/api_keys.json"

if [ -n "$DOWNLOAD_API_KEY" ]; then
    mkdir -p /app/jsons
    cat > "$KEYS_FILE" <<ENDOFKEYS
{
    "admin": {
        "key": "$DOWNLOAD_API_KEY",
        "name": "admin",
        "permissions": [
            "create_key", "delete_key", "get_key", "get_keys",
            "get_video", "get_audio", "get_live_video", "get_live_audio", "get_info"
        ],
        "memory_quota": 5368709120,
        "memory_usage": [],
        "last_access": ""
    }
}
ENDOFKEYS
    echo "yt-dlp-host: API key configured from DOWNLOAD_API_KEY"
fi

# Hand off to the original entrypoint
exec flask run --host=0.0.0.0
