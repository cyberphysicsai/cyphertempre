#!/usr/bin/env bash
# Publish dashboard/public as the root of the `site-deploy` branch.
# Hostinger's Git feature deploys a BRANCH ROOT into public_html and cannot
# point at a repo subdirectory — so the site ships from a branch whose root
# IS the static site. Run this after any dashboard/public change, then
# redeploy in hPanel (or let the webhook auto-deploy).
set -euo pipefail
cd "$(dirname "$0")/.."
git subtree split --prefix=dashboard/public -b site-deploy
git push -f origin site-deploy
echo "site-deploy branch pushed — Hostinger can deploy it now."
