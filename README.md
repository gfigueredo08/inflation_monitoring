# 📈 Monitor de Inflación en Tiempo Real — Argentina

Proyecto de Data Science que construye un índice de precios propio mediante web scraping de supermercados argentinos, lo compara con la Canasta Básica Alimentaria (CBA) oficial del INDEC, y proyecta su evolución futura con un modelo de series de tiempo.

🔗 **App en vivo:** [monitor-inflacion-argentina.streamlit.app](https://monitor-inflacion-argentina.streamlit.app/)

---

## Por qué este proyecto

El IPC y la CBA del INDEC se publican con rezago mensual y no permiten desagregar por cadena comercial. Este proyecto propone un monitoreo de alta frecuencia, construido enteramente con datos propios, que releva precios cada 7 días en 5 supermercados online y los contrasta contra la serie oficial.

La canasta replica los principales grupos de la **Canasta Básica Alimentaria del INDEC**: cereales, carnes, lácteos, verduras, frutas, aceites, azúcar, huevos, legumbres, bebidas y yerba.

---

## Arquitectura

```
┌─────────────────┐      ┌──────────────────────┐      ┌─────────────────┐
│  GitHub Actions   │──→──│   scraper.py          │──→──│    Supabase      │
│  (cron, cada      │      │   (Python + Playwright)│      │   (PostgreSQL)   │
│   7 días)          │      │                        │      │                  │
└─────────────────┘      └──────────────────────┘      └────────┬────────┘
                                                                    │
                            ┌───────────────────────────────────────┤
                            │                                       │
                  ┌─────────▼─────────┐                  ┌─────────▼─────────┐
                  │  Notebook (Colab)   │                  │  App (Streamlit)   │
                  │  EDA, modelos,      │                  │  Dashboard en vivo, │
                  │  conclusiones        │                  │  gestión de canasta │
                  └─────────────────────┘                  └─────────────────────┘
```

**Supermercados relevados:** Carrefour, Jumbo, Disco, Vea y Día.
**Coto** fue evaluado pero descartado por bloqueo anti-bot (ver nota metodológica en el notebook).

---

## Estructura del repositorio

```
inflation_monitoring/
│
├── scraper.py                          # Script de scraping (Playwright async)
│                                          Lee la canasta desde Supabase y
│                                          escribe los precios relevados.
│
├── .github/workflows/
│   └── scraper.yml                     # Automatización: corre scraper.py
│                                          cada 7 días vía GitHub Actions.
│
├── streamlit_app/
│   ├── app.py                          # App principal (3 tabs)
│   ├── db.py                           # Conexión y queries a Supabase
│   ├── pipeline.py                     # Preprocesamiento, índice y modelo Prophet
│   ├── requirements.txt
│   └── .streamlit/secrets.toml         # (no versionado) credenciales locales
│
├── Proyecto_DSII_Figueredo_Final.ipynb # Notebook completo: EDA, feature
│                                          engineering, Prophet, clustering,
│                                          comparación con INDEC, conclusiones.
│
└── README.md
```

---

## Base de datos (Supabase)

**`precios_canasta`** — histórico de precios relevados.
`categoria | producto | supermercado | precio | tipo_precio | fecha_scraping | url`

**`canasta_config`** — configuración editable de la canasta (fuente de verdad que lee `scraper.py` en cada corrida).
`categoria | producto | supermercado | url | activo | ultimo_error | fecha_ultimo_error`

---

## La app de Streamlit

| Tab | Contenido |
|---|---|
| 📊 **Dashboard** | Índice propio vs CBA INDEC, evolución por categoría, predicción a 3 meses con Prophet |
| 🛒 **Comparador** | Precios actuales por supermercado, brecha entre cadenas, clustering de perfiles de pricing |
| ⚙️ **Gestión de canasta** | Semáforo de URLs activas/caídas, edición de URLs sin tocar código, alta de productos y categorías |

Todo el cálculo (limpieza de outliers, índice, modelo) corre **en vivo** contra los datos actuales de Supabase — no hay resultados pre-calculados ni estáticos.

---

## El notebook

Cubre el desarrollo completo del proyecto: presentación del problema, construcción del pipeline de scraping, lectura y limpieza de datos, EDA, feature engineering, comparación con la CBA oficial vía API de datos.gob.ar, modelo de forecasting (Prophet) y clustering de supermercados (KMeans), con conclusiones y limitaciones metodológicas documentadas en cada sección.

---

## Limitaciones conocidas

- **Coto Digital** no pudo incorporarse por protección anti-bot.
- Una parte de la serie histórica (enero–mayo 2026) se generó de forma **sintética**, calibrada contra la variación real de la CBA del INDEC, para contar con suficientes observaciones mientras se acumulan corridas reales del scraper.
- El modelo Prophet debe interpretarse como una prueba de concepto metodológica dado el tamaño muestral actual; su robustez aumenta con cada corrida real acumulada.
- Los cortes de carne a granel pueden no ser estrictamente comparables entre cadenas por diferencias de calidad/procedencia.

---

## Stack

`Python` · `Playwright` · `Supabase (PostgreSQL)` · `GitHub Actions` · `Streamlit` · `Prophet` · `scikit-learn` · `Plotly` · `pandas`
