# Marta de Rico Ingeniería (`@mdr.ia`) — Publicador Automático Oficial

Sistema automatizado de publicación en **Instagram** (`@mdr.ia`) y **Facebook** (`Marta de Rico`) mediante **Meta Graph API v21.0** y **GitHub Actions**.

## Cómo funciona
- `media/`: imágenes JPG (sRGB, formato requerido por la API oficial de Instagram) alojadas vía **GitHub Pages**.
- `schedule.json`: grilla de publicaciones e historias con fecha y hora en zona horaria Argentina (`-03:00`).
- `scripts/publish.py`: script en Python sin dependencias externas que verifica qué piezas están vencidas/en hora, valida las URLs y publica en Instagram y Facebook evitando duplicados mediante `state.json`.
- `.github/workflows/autopost.yml`: workflow automático que corre cada 30 minutos en la nube de GitHub (no requiere tener VS Code ni la PC encendida).
- El token oficial de Meta (`META_TOKEN`) se guarda cifrado en **GitHub Repository Secrets**, nunca en el código.
