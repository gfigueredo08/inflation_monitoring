"""
app.py
Monitor de Inflación en Tiempo Real - Punto de entrada de la app.
"""

import sys
import os

# Aseguramos que Python encuentre los módulos locales (data.py, etc.)
# sin importar desde qué directorio Streamlit Cloud ejecute la app.
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import streamlit as st
import plotly.graph_objects as go
from db import cargar_precios, cargar_canasta_config
from pipeline import (
    limpiar_outliers,
    construir_indice_mensual,
    construir_indice_categoria,
    comparar_con_indec,
    entrenar_prophet,
    predecir,
)

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
    st.subheader("Índice propio vs CBA oficial del INDEC")

    with st.spinner("Procesando índice de precios..."):
        df_limpio = limpiar_outliers(df_precios)
        df_indice = construir_indice_mensual(df_limpio)
        df_indice_cat = construir_indice_categoria(df_limpio)
        comparacion = comparar_con_indec(df_indice)

    if len(df_indice) < 2:
        st.info(
            "Todavía no hay suficientes meses de datos para construir el índice "
            "(se necesitan al menos 2 períodos distintos)."
        )
    else:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df_indice["fecha"], y=df_indice["indice"],
            mode="lines+markers", name="Índice propio (canasta scrapeada)",
            line=dict(color="#1f77b4"),
        ))
        if not comparacion.empty and comparacion["cba_indexada"].notna().any():
            fig.add_trace(go.Scatter(
                x=comparacion["fecha"], y=comparacion["cba_indexada"],
                mode="lines+markers", name="CBA INDEC oficial",
                line=dict(color="#ff7f0e"),
            ))
        fig.update_layout(
            title="Índice de precios (Base 100 = primer mes disponible)",
            xaxis_title="Fecha", yaxis_title="Índice",
            hovermode="x unified",
        )
        st.plotly_chart(fig, use_container_width=True)

        if not comparacion.empty and comparacion["diferencia_pct"].notna().any():
            diff_prom = comparacion["diferencia_pct"].mean()
            st.caption(f"Diferencia promedio vs CBA INDEC: **{diff_prom:.2f} puntos de índice**")

    st.divider()
    st.subheader("Evolución por categoría")
    if not df_indice_cat.empty:
        fig_cat = go.Figure()
        for cat in df_indice_cat["categoria"].unique():
            sub = df_indice_cat[df_indice_cat["categoria"] == cat]
            fig_cat.add_trace(go.Scatter(
                x=sub["fecha"], y=sub["indice_categoria"],
                mode="lines+markers", name=cat,
            ))
        fig_cat.update_layout(
            title="Índice por categoría (Base 100)",
            xaxis_title="Fecha", yaxis_title="Índice",
            hovermode="x unified",
        )
        st.plotly_chart(fig_cat, use_container_width=True)

    st.divider()
    st.subheader("Predicción a futuro (Prophet)")

    if len(df_indice) < 4:
        st.info(
            f"El modelo de predicción requiere al menos 4 observaciones mensuales "
            f"(hay {len(df_indice)} disponibles). Esperá a que se acumulen más corridas del scraper."
        )
    else:
        with st.spinner("Entrenando modelo..."):
            modelo, df_prophet = entrenar_prophet(df_indice)
            forecast, forecast_futuro = predecir(modelo, df_prophet, periodos=3)

        fig_forecast = go.Figure()
        fig_forecast.add_trace(go.Scatter(
            x=df_prophet["ds"], y=df_prophet["y"],
            mode="markers", name="Datos reales", marker=dict(color="#1f77b4", size=8),
        ))
        fig_forecast.add_trace(go.Scatter(
            x=forecast["ds"], y=forecast["yhat"],
            mode="lines", name="Predicción", line=dict(color="#2ca02c"),
        ))
        fig_forecast.add_trace(go.Scatter(
            x=forecast["ds"], y=forecast["yhat_upper"],
            mode="lines", line=dict(width=0), showlegend=False,
        ))
        fig_forecast.add_trace(go.Scatter(
            x=forecast["ds"], y=forecast["yhat_lower"],
            mode="lines", line=dict(width=0), fill="tonexty",
            fillcolor="rgba(44, 160, 44, 0.15)", name="Intervalo de confianza (80%)",
        ))
        fig_forecast.update_layout(
            title="Proyección del índice de precios",
            xaxis_title="Fecha", yaxis_title="Índice",
            hovermode="x unified",
        )
        st.plotly_chart(fig_forecast, use_container_width=True)

        st.caption("Variación proyectada respecto al último dato real:")
        tabla_forecast = forecast_futuro[["ds", "yhat", "variacion_vs_ultimo_real"]].copy()
        tabla_forecast.columns = ["Fecha", "Índice proyectado", "Variación % vs último real"]
        tabla_forecast["Fecha"] = tabla_forecast["Fecha"].dt.strftime("%B %Y")
        tabla_forecast["Índice proyectado"] = tabla_forecast["Índice proyectado"].round(2)
        tabla_forecast["Variación % vs último real"] = tabla_forecast["Variación % vs último real"].round(2)
        st.dataframe(tabla_forecast, hide_index=True, use_container_width=True)

        st.caption(
            "⚠️ Con una muestra acotada de observaciones mensuales, esta proyección debe "
            "interpretarse como una prueba de concepto metodológica, no como una predicción "
            "robusta de inflación. La confiabilidad mejora a medida que el scraper acumula "
            "más corridas reales."
        )

with tab2:
    st.info("Próximo paso: comparación de precios entre cadenas + clustering")

with tab3:
    st.info("Próximo paso: tabla editable con semáforo de URLs activas/caídas")
    st.dataframe(df_config)
