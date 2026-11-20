import json
import os
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHED_PATH = os.path.join(ROOT, "schedule.json")
STATE_PATH = os.path.join(ROOT, "state.json")
YML_PATH = os.path.join(ROOT, ".github", "workflows", "autopost.yml")

with open(SCHED_PATH, encoding="utf-8") as f:
    sched = json.load(f)
with open(STATE_PATH, encoding="utf-8") as f:
    published = json.load(f).get("published", {})

crons = []
for item in sched.get("items", []):
    iid = item["id"]
    rec = published.get(iid, {})
    if rec.get("ig_id") and rec.get("fb_id"):
        continue
    dt_arg = datetime.fromisoformat(item["scheduled_at"])
    # Despertar 25 min antes en UTC (evitando minutos :00 y :30)
    wake_utc = (dt_arg - timedelta(minutes=25)).astimezone(timezone.utc)
    if wake_utc.minute in (0, 30):
        wake_utc -= timedelta(minutes=3)
    expr = f"{wake_utc.minute} {wake_utc.hour} {wake_utc.day} {wake_utc.month} *"
    desc = f"{iid} ({item['type']}) -> {dt_arg.strftime('%d/%m %H:%M ART')}"
    crons.append((expr, desc))

header = """name: Publicar contenido programado (IG + FB)

on:
  schedule:
    # Despierta ~25 min antes de cada fecha/hora exacta y espera en el servidor hasta la hora exacta
"""
cron_block = "\n".join(f'    - cron: "{c}"  # {d}' for c, d in crons)
tail = """
    - cron: "17 1 * * *"  # Respaldo diario 22:17 ART por si GitHub atraso algun turno
  workflow_dispatch:
    inputs:
      force_id:
        description: "Opcional: ID especifico a publicar ahora (ej. M02 o H01)"
        required: false
        default: ""
      dry_run:
        description: "Solo verificar sin publicar (true/false)"
        required: false
        default: "false"

permissions:
  contents: write

jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Run Meta Graph API Publisher
        env:
          META_TOKEN: ${{ secrets.META_TOKEN }}
        run: |
          ARGS=""
          if [ "${{ github.event.inputs.dry_run }}" = "true" ]; then
            ARGS="$ARGS --check"
          fi
          if [ -n "${{ github.event.inputs.force_id }}" ]; then
            ARGS="$ARGS --force-id ${{ github.event.inputs.force_id }}"
          fi
          python scripts/publish.py $ARGS

      - name: Commit updated state.json
        if: always() && github.event.inputs.dry_run != 'true'
        run: |
          git config user.name "mdr-autopost-bot"
          git config user.email "bot@mdr.local"
          git add state.json
          if ! git diff --cached --quiet; then
            git commit -m "Update published state [skip ci]"
            git push
          fi
"""

with open(YML_PATH, "w", encoding="utf-8", newline="\n") as f:
    f.write(header + cron_block + tail)

print(f"Updated autopost.yml with {len(crons)} exact early-wake crons + 1 daily backup.")
