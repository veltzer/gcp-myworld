#!/bin/bash -eu
# Render art/social-card.html, the picture a shared link to the site shows,
# to src/myworld/static/social-card.png (1200x630) with headless Chrome.
cd "$(dirname "$0")/.."
profile=$(mktemp -d)
trap 'rm -rf "${profile}"' EXIT
google-chrome --headless=new --disable-gpu --hide-scrollbars --user-data-dir="${profile}" \
	--window-size=1200,630 --virtual-time-budget=3000 \
	--screenshot="${PWD}/src/myworld/static/social-card.png" "file://${PWD}/art/social-card.html"
