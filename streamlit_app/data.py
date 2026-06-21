"""
data.py
Conexión a Supabase y funciones de lectura de datos.
"""

import streamlit as st
import pandas as pd
from supabase import create_client


@st.cache_resource
def get_supabase_client():
    """
    Crea (una sola vez, cacheado) el cliente de Supabase usando los
    secrets configurados en Streamlit Cloud (Settings > Secrets).
    """
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)


@st.cache_data(ttl=300)  # refresca cada 5 minutos
def cargar_precios():
    """
    Lee la tabla precios_canasta completa.
    """
    client = get_supabase_client()
    response = client.table("precios_canasta").select("*").execute()
    df = pd.DataFrame(response.data)
    if df.empty:
        return df
    df["fecha_scraping"] = pd.to_datetime(df["fecha_scraping"])
    df["precio"] = pd.to_numeric(df["precio"])
    return df


@st.cache_data(ttl=300)
def cargar_canasta_config():
    """
    Lee la tabla canasta_config completa (incluye activos e inactivos,
    y el estado de último error por producto-supermercado).
    """
    client = get_supabase_client()
    response = client.table("canasta_config").select("*").execute()
    df = pd.DataFrame(response.data)
    return df


def actualizar_url_producto(producto, supermercado, nueva_url):
    """
    Actualiza la URL de un producto-supermercado puntual en canasta_config.
    """
    client = get_supabase_client()
    response = (
        client.table("canasta_config")
        .update({"url": nueva_url, "ultimo_error": None, "fecha_ultimo_error": None})
        .eq("producto", producto)
        .eq("supermercado", supermercado)
        .execute()
    )
    return response


def actualizar_estado_activo(producto, supermercado, activo: bool):
    """
    Activa o desactiva un producto-supermercado puntual.
    """
    client = get_supabase_client()
    response = (
        client.table("canasta_config")
        .update({"activo": activo})
        .eq("producto", producto)
        .eq("supermercado", supermercado)
        .execute()
    )
    return response


def agregar_producto(categoria, producto, supermercado, url):
    """
    Agrega una fila nueva a canasta_config.
    """
    client = get_supabase_client()
    response = (
        client.table("canasta_config")
        .upsert(
            {
                "categoria": categoria,
                "producto": producto,
                "supermercado": supermercado,
                "url": url,
                "activo": True,
            },
            on_conflict="producto,supermercado",
        )
        .execute()
    )
    return response
