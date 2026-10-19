# SDK propietario de AgiBot (linksoul_agentsdk)

El paquete Python `linksoul_agentsdk` **no está en PyPI**. Se distribuye desde
la documentación oficial de LinkSoul:

1. Entra en https://open.agibot.com/docs/linksoul/agentsdk_docs/python/v140/en
   (necesitas cuenta de la plataforma abierta de AgiBot; se crea gratis).
2. Descarga el wheel: `linksoul_agentsdk-1.4.0a0-py3-none-any.whl`
   (o el sdist `linksoul_agentsdk-1.4.0a0.tar.gz`).
3. Copia el archivo **en esta carpeta** (`bridge/vendor/`).
4. Reconstruye la imagen del bridge:
   ```bash
   docker compose build linksoul-bridge
   ```

El Dockerfile lo detecta e instala automáticamente. Sin el wheel, la imagen
compila igualmente y puedes usar el modo de prueba local:
```bash
docker compose run --rm linksoul-bridge python -m bridge.chat_test
```

Requisitos del SDK: Python >= 3.10 (la imagen usa 3.12) y `websocket-client>=1.7.0`
(ya incluido en requirements.txt).
