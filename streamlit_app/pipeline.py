"""
pipeline.py
Preprocesamiento, construcción del índice de precios y modelo de forecasting (Prophet).
Replica la lógica desarrollada en el notebook de análisis.
"""

import pandas as pd
import numpy as np
import streamlit as st
import requests
import io


# ── Preprocesamiento ──────────────────────────────────────────────────────

def limpiar_outliers(df: pd.DataFrame) -> pd.DataFrame:
    """
    Aplica dos pasadas de detección de outliers sobre la columna 'precio':
    1) IQR por producto + supermercado
    2) Desvío > 60% respecto a la mediana por producto + fecha
    Los outliers se reemplazan por NaN y luego se imputan con la mediana
    del producto en esa fecha.

    Implementado con transform() en lugar de groupby().apply() para evitar
    inconsistencias de comportamiento entre versiones de pandas.
    """
    df = df.copy()

    # --- Pasada 1: IQR por producto + supermercado ---
    grp1 = df.groupby(["producto", "supermercado"])["precio"]
    q1 = grp1.transform(lambda s: s.quantile(0.25))
    q3 = grp1.transform(lambda s: s.quantile(0.75))
    iqr = q3 - q1
    lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    mask_iqr = (df["precio"] < lower) | (df["precio"] > upper)
    df.loc[mask_iqr, "precio"] = np.nan

    # --- Pasada 2: desvío > 60% respecto a la mediana por producto + fecha ---
    grp2 = df.groupby(["producto", "fecha_scraping"])["precio"]
    mediana = grp2.transform("median")
    mask_mediana = (mediana.notna()) & (abs(df["precio"] - mediana) / mediana > 0.6)
    df.loc[mask_mediana, "precio"] = np.nan

    # --- Imputación con la mediana del producto en esa fecha ---
    df["precio"] = df.groupby(["producto", "fecha_scraping"])["precio"].transform(
        lambda s: s.fillna(s.median())
    )
    df = df.dropna(subset=["precio"])
    return df


def construir_indice_mensual(df: pd.DataFrame) -> pd.DataFrame:
    """
    A partir del DataFrame limpio, calcula el índice general base 100
    (primer mes disponible) a frecuencia mensual.
    """
    df = df.copy()
    df["periodo"] = df["fecha_scraping"].dt.to_period("M").astype(str)

    precio_promedio = df.groupby(["periodo", "producto"])["precio"].mean().reset_index()
    indice_general = precio_promedio.groupby("periodo")["precio"].mean().reset_index()
    indice_general = indice_general.sort_values("periodo")

    base = indice_general["precio"].iloc[0]
    indice_general["indice"] = (indice_general["precio"] / base * 100).round(4)
    indice_general["fecha"] = pd.to_datetime(indice_general["periodo"] + "-01")

    return indice_general[["fecha", "periodo", "indice"]]


def construir_indice_categoria(df: pd.DataFrame) -> pd.DataFrame:
    """
    Índice base 100 por categoría y período.
    """
    df = df.copy()
    df["periodo"] = df["fecha_scraping"].dt.to_period("M").astype(str)

    indice_cat = df.groupby(["categoria", "periodo"])["precio"].mean().reset_index()
    base_cat = (
        indice_cat.sort_values("periodo")
        .groupby("categoria")
        .first()["precio"]
    )
    indice_cat["indice_categoria"] = indice_cat.apply(
        lambda r: round((r["precio"] / base_cat[r["categoria"]]) * 100, 2), axis=1
    )
    indice_cat["fecha"] = pd.to_datetime(indice_cat["periodo"] + "-01")
    return indice_cat


# ── CBA del INDEC ──────────────────────────────────────────────────────────

@st.cache_data(ttl=86400)  # se refresca una vez por día, no hace falta más
def cargar_cba_indec():
    """
    Descarga la serie histórica de la CBA oficial desde la API de Series
    de Tiempo de Argentina (datos.gob.ar / INDEC).
    """
    url = (
        "https://infra.datos.gob.ar/catalog/sspm/dataset/150/distribution/150.1/"
        "download/valores-canasta-basica-alimentos-canasta-basica-total-mensual-2016.csv"
    )
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        df_indec = pd.read_csv(io.StringIO(response.text))
        df_indec["indice_tiempo"] = pd.to_datetime(df_indec["indice_tiempo"])
        df_indec = df_indec[["indice_tiempo", "canasta_basica_alimentaria"]]
        df_indec.columns = ["fecha", "cba_indec"]
        return df_indec
    except Exception as e:
        st.warning(f"No se pudo descargar la CBA del INDEC en este momento: {e}")
        return pd.DataFrame(columns=["fecha", "cba_indec"])


def comparar_con_indec(df_indice_mensual: pd.DataFrame) -> pd.DataFrame:
    """
    Compara el índice propio (mensual) contra la CBA oficial, ambos
    normalizados a base 100 en el primer mes en común.
    """
    df_indec = cargar_cba_indec()
    if df_indec.empty:
        return pd.DataFrame()

    fecha_base = df_indice_mensual["fecha"].min()
    df_indec_periodo = df_indec[df_indec["fecha"] >= fecha_base].copy()

    if df_indec_periodo.empty:
        return pd.DataFrame()

    base_cba = df_indec_periodo["cba_indec"].iloc[0]
    df_indec_periodo["cba_indexada"] = (df_indec_periodo["cba_indec"] / base_cba * 100).round(2)

    comparacion = df_indice_mensual.merge(
        df_indec_periodo[["fecha", "cba_indexada"]], on="fecha", how="left"
    )
    comparacion["diferencia_pct"] = (comparacion["indice"] - comparacion["cba_indexada"]).round(2)
    return comparacion


# ── Modelo de forecasting (Prophet) ────────────────────────────────────────

@st.cache_resource(show_spinner=False)
def entrenar_prophet(_df_indice_mensual: pd.DataFrame):
    """
    Entrena un modelo Prophet sobre el índice mensual.
    El underscore en el nombre del parámetro evita que Streamlit intente
    hashear el DataFrame para el cache (no es serializable de forma estable).
    """
    from prophet import Prophet

    df_prophet = _df_indice_mensual.rename(columns={"fecha": "ds", "indice": "y"})[["ds", "y"]]

    modelo = Prophet(
        yearly_seasonality=False,
        weekly_seasonality=False,
        daily_seasonality=False,
        interval_width=0.80,
    )
    modelo.fit(df_prophet)
    return modelo, df_prophet


def predecir(modelo, df_prophet, periodos=3):
    """
    Genera la predicción a 'periodos' meses hacia adelante.
    """
    futuro = modelo.make_future_dataframe(periods=periodos, freq="MS")
    forecast = modelo.predict(futuro)

    ultimo_real = df_prophet["y"].iloc[-1]
    forecast_futuro = forecast[forecast["ds"] > df_prophet["ds"].max()].copy()
    forecast_futuro["variacion_vs_ultimo_real"] = (
        (forecast_futuro["yhat"] / ultimo_real) - 1
    ) * 100

    return forecast, forecast_futuro


# ── Comparador de supermercados ─────────────────────────────────────────────

def precios_actuales_por_supermercado(df: pd.DataFrame) -> pd.DataFrame:
    """
    Tabla pivote: precio más reciente de cada producto en cada supermercado.
    """
    df = df.copy()
    idx_ultimo = df.groupby(["producto", "supermercado"])["fecha_scraping"].idxmax()
    df_ultimo = df.loc[idx_ultimo]

    pivot = df_ultimo.pivot_table(
        index=["categoria", "producto"], columns="supermercado", values="precio"
    ).reset_index()
    return pivot


def calcular_brecha(df: pd.DataFrame) -> pd.DataFrame:
    """
    Para el precio más reciente de cada producto, calcula la brecha % entre
    el supermercado más caro y el más barato.
    """
    df = df.copy()
    idx_ultimo = df.groupby(["producto", "supermercado"])["fecha_scraping"].idxmax()
    df_ultimo = df.loc[idx_ultimo]

    brecha = df_ultimo.groupby(["categoria", "producto"]).agg(
        precio_min=("precio", "min"),
        precio_max=("precio", "max"),
    ).reset_index()
    brecha["brecha_pct"] = ((brecha["precio_max"] - brecha["precio_min"]) / brecha["precio_min"] * 100).round(1)
    return brecha.sort_values("brecha_pct", ascending=False)


def perfil_supermercados(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calcula, para el precio más reciente de cada producto, el precio relativo
    (precio / promedio del producto en esa fecha) y el ranking de cada
    supermercado. Devuelve el promedio de esas métricas por supermercado.
    """
    df = df.copy()
    idx_ultimo = df.groupby(["producto", "supermercado"])["fecha_scraping"].idxmax()
    df_ultimo = df.loc[idx_ultimo].copy()

    df_ultimo["precio_relativo"] = df_ultimo["precio"] / df_ultimo.groupby("producto")["precio"].transform("mean")
    df_ultimo["ranking_precio"] = df_ultimo.groupby("producto")["precio"].rank(method="min")

    perfil = df_ultimo.groupby("supermercado").agg(
        precio_relativo=("precio_relativo", "mean"),
        ranking_precio=("ranking_precio", "mean"),
    ).reset_index()
    perfil["precio_relativo"] = perfil["precio_relativo"].round(3)
    perfil["ranking_precio"] = perfil["ranking_precio"].round(2)
    return perfil


def clustering_supermercados(df_perfil: pd.DataFrame, n_clusters=2):
    """
    Aplica KMeans sobre el perfil de precios de cada supermercado.
    Requiere al menos n_clusters supermercados con datos.
    """
    from sklearn.cluster import KMeans
    from sklearn.preprocessing import StandardScaler

    if len(df_perfil) < n_clusters:
        return df_perfil.assign(cluster=0)

    features = ["precio_relativo", "ranking_precio"]
    X = df_perfil[features].fillna(0)

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    df_perfil = df_perfil.copy()
    df_perfil["cluster"] = kmeans.fit_predict(X_scaled)
    return df_perfil
