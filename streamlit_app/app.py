"""
app.py
Monitor de Inflación en Tiempo Real - Punto de entrada de la app.
"""

import streamlit as st
from data import cargar_precios, cargar_canasta_config

st.set_page_config(
    page_title="Monitor de Inflación",
    page_icon="📈",
    layout="wide",
)

st.title("📈 Monitor de Inflación en Tiempo Real")
st.caption(
    "Índice de precios propio construido con web scraping de supermercados "
    "argentinos, comparado contra la CBA oficial del INDEC."
)

# --- Carga de datos (cacheada, se refresca cada 5 minutos) ---
with st.spinner("Cargando datos desde Supabase..."):
    df_precios = cargar_precios()
    df_config = cargar_canasta_config()

if df_precios.empty:
    st.warning(
        "Todavía no hay datos en la tabla `precios_canasta`. "
        "Esperá a que corra el scraper o revisá la conexión a Supabase."
    )
    st.stop()

# --- Métricas rápidas arriba de todo ---
col1, col2, col3, col4 = st.columns(4)
col1.metric("Registros totales", len(df_precios))
col2.metric("Productos únicos", df_precios["producto"].nunique())
col3.metric("Supermercados", df_precios["supermercado"].nunique())
col4.metric(
    "Última actualización",
    df_precios["fecha_scraping"].max().strftime("%d/%m/%Y"),
)

st.divider()

# --- Tabs ---
tab1, tab2, tab3 = st.tabs(["📊 Dashboard", "🛒 Comparador de supermercados", "⚙️ Gestión de canasta"])

with tab1:
    st.info("Próximo paso: índice propio vs CBA INDEC + predicción Prophet")
    st.dataframe(df_precios.tail(20))

with tab2:
    st.info("Próximo paso: comparación de precios entre cadenas + clustering")

with tab3:
    st.info("Próximo paso: tabla editable con semáforo de URLs activas/caídas")
    st.dataframe(df_config)
