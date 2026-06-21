
import asyncio
import pandas as pd
from datetime import datetime
import re
import os

# Import create_client for Supabase connection
from supabase import create_client

# --- Supabase Configuration ---
# Read Supabase credentials from environment variables
SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY')

# Initialize Supabase client if credentials are available
supabase_client = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
        print("Conexión a Supabase exitosa.")
    except Exception as e:
        print(f"Error al conectar a Supabase: {e}")
else:
    print('Advertencia: Las credenciales de Supabase (SUPABASE_URL o SUPABASE_KEY) no están configuradas en las variables de entorno.')

# --- Helper Functions ---

def clean_and_convert_price(price_string):
    """
    Limpia y convierte una cadena de texto de precio a float.
    """
    if price_string is None:
        return None
    # Eliminar '$', separadores de miles (.), \xa0 y \n, reemplazar coma por punto
    cleaned_price_text = price_string.replace('$', '').replace('\xa0', '').replace('\n', '').replace('.', '').replace(',', '.').strip()
    try:
        return float(cleaned_price_text)
    except ValueError:
        print(f"Error: No se pudo convertir '{cleaned_price_text}' a float.")
        return None

async def scrape_price(url, supermercado):
    """
    Scrapea el precio de lista o de venta de un producto de diferentes supermercados usando Playwright (Async API).

    Args:
        url (str): La URL del producto a scrapear.
        supermercado (str): El nombre del supermercado ('carrefour', 'coto', 'jumbo').

    Returns:
        tuple (float, str) or None: El precio y el tipo de precio ('lista', 'venta', 'regular') si se encuentra, de lo contrario None.
    """
    from playwright.async_api import async_playwright, TimeoutError

    browser = None
    try:
        async with async_playwright() as p:
            print(f"Lanzando navegador Chromium headless para {supermercado}...")
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            print(f"Navegando a: {url}")
            # Increase default navigation timeout to 60 seconds (60000 ms)
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)

            price_text = None
            price_type = None

            if supermercado == 'carrefour':
                list_price_selector = "[class*='listPriceValue']"
                selling_price_selector = "[class*='sellingPrice']"

                # 1. Intentar encontrar el precio de lista (tachado) con un timeout corto
                try:
                    print("Intentando encontrar el precio de lista (tachado) en Carrefour...")
                    await page.wait_for_selector(list_price_selector, timeout=5000)
                    price_text = await page.inner_text(list_price_selector)
                    price_type = 'lista'
                    print(f"Texto de precio de lista encontrado en Carrefour: '{price_text}'")
                except TimeoutError:
                    print("Precio de lista (tachado) no encontrado en Carrefour en 5 segundos.")
                    # 2. Si falla, intentar con el precio de venta con un timeout más largo
                    try:
                        print("Intentando encontrar el precio de venta en Carrefour...")
                        await page.wait_for_selector(selling_price_selector, timeout=10000)
                        price_text = await page.inner_text(selling_price_selector)
                        price_type = 'venta'
                        print(f"Texto de precio de venta encontrado en Carrefour: '{price_text}'")
                    except TimeoutError:
                        print("Precio de venta no encontrado en Carrefour en 10 segundos.")
                        print(f"Error: No se pudo encontrar el precio para {url} en Carrefour.")
                        return None

            elif supermercado == 'jumbo':
                print(f"Intentando encontrar precio de lista (tachado) en {supermercado}...")
                elements = await page.query_selector_all('div, span')
                price_text_found_with_line_through = None
                for el in elements:
                    try:
                        # Obtener el estilo computado del elemento para verificar text-decoration
                        style = await el.evaluate("e => window.getComputedStyle(e).textDecoration")
                        if 'line-through' in style:
                            candidate_price_text = await el.inner_text()
                            if '$' in candidate_price_text:
                                price_text_found_with_line_through = candidate_price_text
                                break # Romper el bucle una vez que se encuentra el precio
                    except Exception:
                        # Log or ignore errors for individual elements that might become detached
                        pass

                if price_text_found_with_line_through:
                    price_text = price_text_found_with_line_through
                    price_type = 'lista'
                    print(f"Texto de precio de lista (tachado) encontrado en {supermercado}: '{price_text}'")
                else:
                    # Si no se encontró precio con 'line-through', buscar el precio de venta
                    print(f"Precio de lista (tachado) no encontrado en {supermercado}. Intentando encontrar precio de venta...")
                    try:
                        selling_price_selector = "[class*='vtex-price-format-gallery']" # Selector genérico para precios de venta en VTEX
                        await page.wait_for_selector(selling_price_selector, timeout=10000)
                        price_text = await page.inner_text(selling_price_selector)
                        price_type = 'venta'
                        print(f"Texto de precio de venta encontrado en {supermercado}: '{price_text}'")
                    except TimeoutError:
                        print(f"Precio de venta no encontrado en {supermercado} después de 10 segundos.")

                if price_text is None:
                    print(f"Error: No se pudo encontrar el precio para {url} en {supermercado}.")
                    return None

            elif supermercado == 'disco':
                await asyncio.sleep(5)
                print("Intentando encontrar 'Precio regular' en Disco...")
                try:
                    regular_price_elements = await page.locator('text=Precio regular').all_inner_texts()
                    if regular_price_elements:
                        # Tomar el primer elemento y buscar el precio después de 'Precio regular x kg.: '
                        full_text = regular_price_elements[0]
                        # This regex attempts to find a price pattern that includes numbers, commas, and dots after "Precio regular"
                        match = re.search(r'Precio regular[^:]*:\s*([$]?[\d\.,]+)', full_text)
                        if match:
                            price_text = match.group(1)
                            price_type = 'regular'
                            print(f"Precio regular encontrado en Disco: '{price_text}'")
                        else:
                            print(f"No se pudo extraer el precio de la cadena: {full_text}")
                    else:
                        print("No se encontraron elementos con 'Precio regular' en Disco.")

                except Exception as e:
                    print(f"Error al buscar 'Precio regular' en Disco: {e}")

                if price_text is None:
                    print("Fallback: Intentando encontrar precio de venta en Disco...")
                    try:
                        selling_price_selector = "[class*='sellingPrice']"
                        await page.wait_for_selector(selling_price_selector, timeout=10000)
                        price_text = await page.inner_text(selling_price_selector)
                        price_type = 'venta'
                        print(f"Texto de precio de venta encontrado en Disco (fallback): '{price_text}'")
                    except TimeoutError:
                        print("Precio de venta no encontrado en Disco (fallback) después de 10 segundos.")

                if price_text is None:
                    print(f"Error: No se pudo encontrar el precio para {url} en Disco.")
                    return None

            elif supermercado == 'vea':
                print("Intentando obtener precio de metadatos en Vea...")
                price_from_meta = await page.get_attribute('meta[property="product:price:amount"]', 'content')
                if price_from_meta:
                    try:
                        price_text = price_from_meta
                        price_type = 'regular'
                        print(f"Precio de metadatos encontrado en Vea: '{price_text}'")
                    except ValueError:
                        print(f"Error: No se pudo convertir el precio de metadatos '{price_from_meta}' a float.")
                else:
                    print("No se encontró precio en metadatos para Vea.")

                if price_text is None:
                    print("Fallback: Intentando encontrar precio de venta en Vea...")
                    try:
                        selling_price_selector = "[class*='sellingPrice']"
                        await page.wait_for_selector(selling_price_selector, timeout=10000)
                        price_text = await page.inner_text(selling_price_selector)
                        price_type = 'venta'
                        print(f"Texto de precio de venta encontrado en Vea (fallback): '{price_text}'")
                    except TimeoutError:
                        print("Precio de venta no encontrado en Vea (fallback) después de 10 segundos.")

                if price_text is None:
                    print(f"Error: No se pudo encontrar el precio para {url} en Vea.")
                    return None

            elif supermercado == 'dia':
                list_price_selector = "[class*='listPriceValue']"
                selling_price_selector = "[class*='sellingPriceValue']"

                # 1. Intentar encontrar el precio de lista (tachado) con un timeout corto
                try:
                    print("Intentando encontrar el precio de lista (tachado) en Dia...")
                    await page.wait_for_selector(list_price_selector, timeout=5000)
                    price_text = await page.inner_text(list_price_selector)
                    price_type = 'lista'
                    print(f"Texto de precio de lista encontrado en Dia: '{price_text}'")
                except TimeoutError:
                    print("Precio de lista (tachado) no encontrado en Dia en 5 segundos.")
                    # 2. Si falla, intentar con el precio de venta con un timeout más largo
                    try:
                        print("Intentando encontrar el precio de venta en Dia...")
                        await page.wait_for_selector(selling_price_selector, timeout=10000)
                        price_text = await page.inner_text(selling_price_selector)
                        price_type = 'venta'
                        print(f"Texto de precio de venta encontrado en Dia: '{price_text}'")
                    except TimeoutError:
                        print("Precio de venta no encontrado en Dia en 10 segundos.")
                        print(f"Error: No se pudo encontrar el precio para {url} en Dia.")
                        return None
            else:
                print(f"Supermercado '{supermercado}' no soportado para scraping: {url}")
                return None

            # Bloque común para limpieza y retorno del precio
            if price_text is None:
                print(f"Error inesperado: price_text es None antes de la limpieza para {supermercado} - {url}")
                return None

            final_price = clean_and_convert_price(price_text)
            if final_price is None:
                return None # clean_and_convert_price ya imprime el error si falla

            scraping_datetime = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            print(f"Precio ({price_type}): {final_price:.2f}")
            print(f"Fecha y hora del scraping: {scraping_datetime}")
            return final_price, price_type

    except Exception as e:
        print(f"Ocurrió un error inesperado durante el scraping para {supermercado} ({url}): {e}")
        return None
    finally:
        if browser:
            await browser.close()
            print(f"Navegador de {supermercado} cerrado.")

# --- Carga de la canasta desde Supabase ---

def cargar_canasta_desde_supabase(supabase_client):
    """
    Lee la configuración activa de la canasta (categoria, producto, supermercado, url)
    desde la tabla canasta_config en Supabase.

    Returns:
        list[dict]: lista de registros activos.
    """
    response = supabase_client.table('canasta_config').select('*').eq('activo', True).execute()
    registros = response.data
    print(f"Canasta cargada desde Supabase: {len(registros)} URLs activas")
    return registros

# --- Scrape Basket Function ---

async def scrape_canasta(registros):
    """
    Scrapea los precios de los productos de la canasta (recibida como lista de registros
    desde Supabase) usando Playwright Async API, e inserta los resultados en Supabase.

    Args:
        registros (list[dict]): lista de filas con categoria, producto, supermercado, url.

    Returns:
        pd.DataFrame: DataFrame con las columnas categoria, producto, supermercado, precio,
        tipo_precio, fecha_scraping, url.
    """
    results = []
    for row in registros:
        categoria = row['categoria']
        product_name = row['producto']
        supermercado = row['supermercado']
        url = row['url']

        if not url or '...' in url:
            print(f"Saltando URL inválida o placeholder para {categoria} - {product_name} - {supermercado}: {url}")
            continue

        print(f"Scrapeando: {categoria} - {product_name} - {supermercado} ({url})")
        price_data = await scrape_price(url, supermercado)

        if price_data is not None:
            price, price_type = price_data
            scraping_datetime = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            results.append({
                'categoria': categoria,
                'producto': product_name,
                'supermercado': supermercado,
                'precio': price,
                'tipo_precio': price_type,
                'fecha_scraping': scraping_datetime,
                'url': url
            })
        else:
            print(f"No se pudo obtener el precio para {categoria} - {product_name} - {supermercado}.")
            # Registrar el error en canasta_config para que Streamlit lo muestre
            if supabase_client:
                try:
                    supabase_client.table('canasta_config').update({
                        'ultimo_error': 'No se pudo obtener el precio',
                        'fecha_ultimo_error': datetime.now().isoformat()
                    }).eq('producto', product_name).eq('supermercado', supermercado).execute()
                except Exception as e:
                    print(f"No se pudo registrar el error en canasta_config: {e}")

        # Esperar 3 segundos entre cada request
        await asyncio.sleep(3)

    df_result = pd.DataFrame(results)
    print(df_result.to_string())

    # --- Supabase Insertion ---
    if supabase_client:
        try:
            records = df_result.to_dict(orient='records')
            response = supabase_client.table('precios_canasta').insert(records).execute()
            print(f"{len(records)} registros insertados en Supabase. Respuesta: {response}")
        except Exception as e:
            print(f"Error al insertar registros en Supabase: {e}")
    else:
        print('No se pudo insertar en Supabase: Cliente no inicializado.')

    return df_result

# --- Main Execution Block ---

if __name__ == '__main__':
    print("Iniciando scraping de la canasta...")
    if supabase_client:
        registros = cargar_canasta_desde_supabase(supabase_client)
        asyncio.run(scrape_canasta(registros))
    else:
        print("No se pudo cargar la canasta: cliente de Supabase no inicializado.")
