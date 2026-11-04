#!/bin/bash
set -euo pipefail
profile="${BROWSER_PROFILE_PATH:-/browser/profile}"
mkdir -p "$profile"
downloads="${BROWSER_DOWNLOADS_PATH:-/workspace/browser/downloads}"
mkdir -p "$profile/Default" "$downloads"
preferences="$profile/Default/Preferences"
preferences_temp="$(mktemp "$profile/Default/Preferences.XXXXXX")"
trap 'rm -f -- "$preferences_temp"' EXIT
if [[ -f "$preferences" ]]; then
  jq --arg downloads "$downloads" '.download.default_directory = $downloads | .download.prompt_for_download = false | .download.directory_upgrade = true | .savefile.default_directory = $downloads' "$preferences" > "$preferences_temp"
else
  jq -n --arg downloads "$downloads" '{download: {default_directory: $downloads, prompt_for_download: false, directory_upgrade: true}, savefile: {default_directory: $downloads}}' > "$preferences_temp"
fi
chmod 600 "$preferences_temp"
mv -- "$preferences_temp" "$preferences"
trap - EXIT
for name in SingletonLock SingletonCookie SingletonSocket; do
  rm -f -- "$profile/$name"
done
flags=(--window-size=1280,720 --lang=ru --accept-lang=ru,en --force-device-scale-factor=2 --use-gl=angle --use-angle=swiftshader)
manifest="${CHROMIUM_ARGUMENTS_FILE:-/browser/launch-arguments.json}"
if [[ -f "$manifest" ]]; then
  jq -e 'type == "array" and all(.[]; type == "string" and (explode | all(. != 0)))' "$manifest" >/dev/null
  mapfile -d '' -t flags < <(jq -j '.[] | ., "\u0000"' "$manifest")
fi
for attempt in {1..50}; do
  [[ -S /tmp/.X11-unix/X99 ]] && break
  sleep 0.1
done
exec /usr/bin/chromium "${flags[@]}" --no-sandbox --remote-debugging-address=127.0.0.1 --remote-debugging-port=9224 --user-data-dir="$profile" about:blank
