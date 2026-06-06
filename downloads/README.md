# Cypher Tempre Dashboard Local Bridge

Download `cyphertempre-dashboard-local-bridge-accountfix.zip` to run the local
bridge used by `https://cyphertempre.ai`.

The hosted site is only a static UI. The bridge runs on the user's own machine,
reads that user's local `cypher-tempre-self-model` skill files, verifies the
Base CPHY payment locally, and stores redeemed payment hashes locally.

## Run

```bash
cd ~/Downloads
unzip cyphertempre-dashboard-local-bridge-accountfix.zip
cd dashboard
npm install
npm run bridge
```

Then open `https://cyphertempre.ai`, use bridge URL
`http://127.0.0.1:8788`, and enter the pairing code printed in Terminal.

If the skill is installed somewhere custom:

```bash
CT_DASHBOARD_ROOT="/path/to/cypher-tempre-self-model" npm run bridge
```
