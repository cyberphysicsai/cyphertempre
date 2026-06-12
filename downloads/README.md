# Cypher Tempre Dashboard Downloads

These files support the public Timechain dashboard at `https://cyphertempre.ai`.

- `cyphertempre-ai-hostinger-root-accountfix.zip` is the static site bundle for
  Hostinger `public_html`.
- `cyphertempre-dashboard-local-bridge-accountfix.zip` is the local bridge
  package users run on their own machines.

The hosted site is only a static UI. The local bridge reads the user's own
`cypher-tempre-self-model` files, verifies the Base CPHY payment locally,
requires a payer-wallet signature for the current session challenge, and stores
redeemed payment hashes locally.

## Local Bridge Run Commands

```bash
cd ~/Downloads
curl -L -o cyphertempre-dashboard-local-bridge-accountfix.zip https://github.com/cyberphysicsai/cypher-tempre-genesis/raw/main/downloads/cyphertempre-dashboard-local-bridge-accountfix.zip
unzip -o cyphertempre-dashboard-local-bridge-accountfix.zip
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
