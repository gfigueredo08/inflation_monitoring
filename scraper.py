
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

# --- Basket Configuration ---

supermercados = ["carrefour", "jumbo", "disco", "vea", "dia"]

canasta = {

    "Pan y cereales": {
        "Arroz Parboil Gallo 1kg": {
            "carrefour": "https://www.carrefour.com.ar/arroz-parboil-gallo-oro-en-bolsa-1-kg-718787/p",
            "jumbo": "https://www.jumbo.com.ar/arroz-parboil-en-bolsa-1-kg-gallo-oro/p",
            "disco": "https://www.disco.com.ar/arroz-parboil-en-bolsa-1-kg-gallo-oro/p",
            "vea": "https://www.vea.com.ar/arroz-parboil-en-bolsa-1-kg-gallo-oro/p",
            "dia": "https://diaonline.supermercadosdia.com.ar/arroz-parboil-gallo-1-kg-295459/p"
        },
        "Fideos Mostachol Matarazzo 500g": {
            "carrefour": "https://www.carrefour.com.ar/fideos-mostacholes-n52-matarazzo-rayado-500-g-726304/p",
            "jumbo":     "https://www.jumbo.com.ar/fideos-matarazzo-mostachol-n52-x500g-2/p",
            "disco": "https://www.disco.com.ar/fideos-matarazzo-mostachol-n52-x500g-2/p",
            "vea": "https://www.vea.com.ar/fideos-matarazzo-mostachol-n52-x500g-2/p",
            "dia": "https://diaonline.supermercadosdia.com.ar/mostachol-n-52-matarazzo-500-gr-99941/p"
        },
        "Harina 000 Cañuelas 1kg": {
            "carrefour": "https://www.carrefour.com.ar/harina-de-trigo-000-ultra-refinada-canuelas-1-kg/p",
            "jumbo":     "https://www.jumbo.com.ar/harina-canuelas-ultra-refinada-vitamina-d-1kg/p",
            "disco": "https://www.disco.com.ar/harina-canuelas-ultra-refinada-vitamina-d-1kg/p",
            "vea": "https://www.vea.com.ar/harina-canuelas-ultra-refinada-vitamina-d-1kg/p",
            "dia": "https://diaonline.supermercadosdia.com.ar/harina-000-canuelas-ultra-refinada-1-kg-273445/p"
        },
        "Pan blanco Lactal 460gr": {
            "carrefour": "https://www.carrefour.com.ar/pan-blanco-lactal-460-grs-717550/p",
            "jumbo": "https://www.jumbo.com.ar/pan-blanco-460-grs-lactal/p",
            "disco": "https://www.disco.com.ar/pan-blanco-460-grs-lactal/p",
            "vea": "https://www.vea.com.ar/pan-blanco-460-grs-lactal/p",
            "dia": "https://diaonline.supermercadosdia.com.ar/pan-blanco-lactal-460-gr-245473/p"
        },
        "Galletitas de agua Cerealitas 212g": {
            "carrefour": "https://www.carrefour.com.ar/galletitas-crackers-cerealitas-clasicas-212-g-720563/p",
            "jumbo": "https://www.jumbo.com.ar/galletitas-cracker-cereal-clasicas-cerealitas-212-gr-2/p",
            "disco": "https://www.disco.com.ar/galletitas-cracker-cereal-clasicas-cerealitas-212-gr-2/p ",
            "vea": "https://www.vea.com.ar/galletitas-cracker-cereal-clasicas-cerealitas-212-gr-2/p",
            "dia": "https://diaonline.supermercadosdia.com.ar/galletitas-crackers-clasicas-cerealitas-212-gr-147689/p"
        },
        "Galletitas dulces Surtido Bagley 400gr": {
            "carrefour": "https://www.carrefour.com.ar/galletitas-surtidas-bagley-en-bolsa-400-g-745439/p",
            "jumbo": "https://www.jumbo.com.ar/galletitas-surtido-bagley-400-gr-2/p",
            "disco": "https://www.disco.com.ar/galletitas-surtido-bagley-400-gr-2/p",
            "vea": "https://www.vea.com.ar/galletitas-surtido-bagley-400-gr-2/p",
            "dia": "https://diaonline.supermercadosdia.com.ar/galletitas-surtidas-bagley-400-gr-271962/p"
        }
    },

    "Carnes": {
        "Suprema de Pollo 1kg": {
            "carrefour": "https://www.carrefour.com.ar/suprema-congelada-x-kg-704563/p",
            "jumbo": "https://www.jumbo.com.ar/suprema-de-pollo-granel-fresca/p",
            "disco": "https://www.disco.com.ar/suprema-de-pollo-granel-fresca/p",
            "vea": "https://www.vea.com.ar/suprema-de-pollo-granel-fresca/p",
            "dia": "https://diaonline.supermercadosdia.com.ar/suprema-de-pollo-x-kg-162808/p"
        },
        "Salchicha Patyviena 6u": {
            "carrefour": "https://www.carrefour.com.ar/salchichas-clasicas-patyviena-flow-pack-6-uni_729709/p",
            "jumbo": "https://www.jumbo.com.ar/salchichas-patyviena-clasicas-x-6-230-gr/p",
            "disco": "https://www.disco.com.ar/salchichas-patyviena-clasicas-x-6-230-gr/p",
            "vea": "https://www.vea.com.ar/salchichas-patyviena-clasicas-x-6-230-gr/p",
            "dia": "https://diaonline.supermercadosdia.com.ar/salchichas-clasicas-x6-ud-paty-viena-230-gr-300137/p"
        },
        "Asado 1kg": {
            "carrefour": "https://www.carrefour.com.ar/asado-novillo-x-kg-6631/p",
            "jumbo": "https://www.jumbo.com.ar/asado-del-centro-3/p",
            "disco": "https://www.disco.com.ar/asado-premium-2/p",
            "vea": "https://www.vea.com.ar/asado-del-centro-la-hacienda/p",
            "dia": "https://diaonline.supermercadosdia.com.ar/asado-x-kg-279637/p"
        },
        "Carne picada 1kg": {
            "carrefour": "https://www.carrefour.com.ar/picada-organica-x-kg-693276/p",
            "jumbo": "https://www.jumbo.com.ar/carne-vacuna-picada-comun-la-hacienda-2/p",
            "disco": "https://www.disco.com.ar/carne-vacuna-picada-magra-2/p",
            "vea": "https://www.vea.com.ar/carne-vacuna-picada-comun-la-hacienda-2/p",
            "dia": "https://diaonline.supermercadosdia.com.ar/carne-picada-de-nalga-x-500-gr-225674/p"
        },
        "Paleta 1kg": {
            "carrefour": "https://www.carrefour.com.ar/paleta-x-kg-662849/p",
            "jumbo": "https://www.jumbo.com.ar/paleta-trozo-2/p",
            "disco": "https://www.disco.com.ar/paleta-trozo-2/p",
            "vea": "https://www.vea.com.ar/paleta-churr-de-nov-envasado-al-vacio/p",
            "dia": "https://diaonline.supermercadosdia.com.ar/paleta-de-novillo-en-churrasco-x-kg-162840/p"
        }
    },

    "Verduras y frutas": {
        "Papa 1kg": {
            "carrefour": "https://www.carrefour.com.ar/papa-cepillada-x-kg/p",
            "jumbo":     "https://www.jumbo.com.ar/papa-cepillada-granel-por-kg-2/p",
            "disco": "https://www.disco.com.ar/papa-cepillada-granel-por-kg-2/p",
            "vea": "https://www.vea.com.ar/papa-negra-por-kg-2/p",
            "dia": "https://diaonline.supermercadosdia.com.ar/papa-negra-x-kg-90094/p"
        },
        "Tomate redondo 1kg": {
            "carrefour": "https://www.carrefour.com.ar/tomate-redondo-huella-natural-x-kg-718963/p",
            "jumbo":     "https://www.jumbo.com.ar/tomate-redondo-grande-por-kg/p",
            "disco": "https://www.disco.com.ar/tomate-redondo-grande-por-kg/p",
            "vea": "https://www.vea.com.ar/tomate-redondo-por-kg/p",
            "dia": "https://diaonline.supermercadosdia.com.ar/tomate-redondo-x-kg-90127/p"
        },
        "Cebolla 1kg": {
            "carrefour": "https://www.carrefour.com.ar/cebolla-x-kg/p",
            "jumbo": "https://www.jumbo.com.ar/cebolla-superior-por-kg-2/p",
            "disco": "https://www.disco.com.ar/cebolla-superior-por-kg-2/p",
            "vea": "https://www.vea.com.ar/cebolla-superior-por-kg-2/p",
            "dia": "https://diaonline.supermercadosdia.com.ar/cebolla-comercial-en-bolsa-malla-x-kg-90063/p"
        },
        "Zanahoria 1kg": {
            "carrefour": "https://www.carrefour.com.ar/zanahoria-x-kg-630573/p",
            "jumbo": "https://www.jumbo.com.ar/zanahoria-por-kg-5/p",
            "disco": "https://www.disco.com.ar/zanahoria-por-kg-5/p",
            "vea": "https://www.vea.com.ar/zanahoria-por-kg-5/p",
            "dia": "https://diaonline.supermercadosdia.com.ar/zanahoria-x-kg-90122/p"
        },
        "Manzana 1kg": {
            "carrefour": "https://www.carrefour.com.ar/manzana-red-x-kg-432782/p",
            "jumbo": "https://www.jumbo.com.ar/manzana-roja-por-kg/p",
            "disco": "https://www.disco.com.ar/manzana-roja-por-kg/p",
            "vea": "https://www.vea.com.ar/manzana-roja-por-kg/p",
            "dia": "https://diaonline.supermercadosdia.com.ar/manzana-roja-comercial-en-bolsa-malla-x-kg-90111/p"
        },
        "Banana 1kg": {
            "carrefour": "https://www.carrefour.com.ar/banana-seleccion-x-kg-719074/p",
            "jumbo": "https://www.jumbo.com.ar/banana-ecuador-x-kg-2/p",
            "disco": "",
            "vea": "https://www.vea.com.ar/banana-x-kg/p",
            "dia": "https://diaonline.supermercadosdia.com.ar/banana-x-kg-90110/p"
        },
        "Naranja de jugo 1kg": {
            "carrefour": "https://www.carrefour.com.ar/naranja-de-jugo-x-kg-8314/p",
            "jumbo": "https://www.jumbo.com.ar/naranja-para-jugo-por-kg/p",
            "disco": "",
            "vea": "https://www.vea.com.ar/naranja-para-jugo-por-kg/p",
            "dia": "https://diaonline.supermercadosdia.com.ar/naranja-jugo-x-kg-90117/p"
        }
    },

    "Lácteos": {
        "Leche entera La Serenísima botella 1l": {
            "carrefour": "https://www.carrefour.com.ar/leche-la-serenisima-clasica-3-1l-720719/p",
            "jumbo":     "https://www.jumbo.com.ar/leche-la-serenisima-entera-bot-1l/p",
            "disco": "https://www.disco.com.ar/leche-la-serenisima-entera-bot-1l/p",
            "vea": "https://www.vea.com.ar/leche-la-serenisima-entera-bot-1l/p",
            "dia": "https://diaonline.supermercadosdia.com.ar/leche-entera-clasica-la-serenisima-botella-larga-vida-1-lt-165870/p"
        },
        "Yogur firme vainilla Yogurisimo 190g": {
            "carrefour": "https://www.carrefour.com.ar/yogur-firme-vainilla-yogurisimo-190-g-721111/p",
            "jumbo": "https://www.jumbo.com.ar/yogur-firme-vainilla-190-grs-yogurisimo/p",
            "disco": "https://www.disco.com.ar/yogur-firme-vainilla-190-grs-yogurisimo/p",
            "vea": "https://www.vea.com.ar/yogur-firme-vainilla-190-grs-yogurisimo/p",
            "dia": "https://diaonline.supermercadosdia.com.ar/yogur-firme-vainilla-yogurisimo-190-gr-5553/p"
        },
        "Queso cremoso La Paulina 1kg": {
            "carrefour": "https://www.carrefour.com.ar/queso-cremoso-la-paulina-x-kg-647989/p",
            "jumbo": "https://www.jumbo.com.ar/queso-cremoso-la-paulina-minimo-1-kg/p",
            "disco": "https://www.disco.com.ar/queso-cremoso-la-paulina-minimo-1-kg/p",
            "vea": "https://www.vea.com.ar/queso-cremoso-la-paulina-minimo-1-kg/p",
            "dia": "https://diaonline.supermercadosdia.com.ar/queso-cremoso-la-paulina-x-kg-90181/p"
        }
    },

    "Aceites y grasas": {
        "Aceite de Girasol Natura 900ml": {
            "carrefour": "https://www.carrefour.com.ar/aceite-de-girasol-natura-900-cc/p",
            "jumbo":     "https://www.jumbo.com.ar/aceite-de-girasol-natura-900-ml/p",
            "disco": "https://www.disco.com.ar/aceite-de-girasol-natura-900-ml/p",
            "vea": "https://www.vea.com.ar/aceite-de-girasol-natura-900-ml/p",
            "dia": "https://diaonline.supermercadosdia.com.ar/aceite-girasol-natural-09-lt-78855/p"
        }
    },

    "Azúcar y dulces": {
        "Azúcar Ledesma 1kg": {
            "carrefour": "https://www.carrefour.com.ar/azucar-ledesma-molida-superior-bolsa-1-kg/p",
            "jumbo": "https://www.jumbo.com.ar/azucar-ledesma-superior-x/p",
            "disco": "https://www.disco.com.ar/azucar-ledesma-superior-x/p",
            "vea": "https://www.vea.com.ar/azucar-ledesma-superior-x/p",
            "dia": "https://diaonline.supermercadosdia.com.ar/azucar-ledesma-refinado-superior-1-kg-129208/p"
        },
        "Dulce de leche La Serenísima Clásico 400g": {
            "carrefour": "https://www.carrefour.com.ar/dulce-de-leche-la-serenisima-colonial-400-g-678862/p",
            "jumbo": "https://www.jumbo.com.ar/dulce-de-leche-la-serenisima-clasico-400g-2/p",
            "disco": "https://www.disco.com.ar/dulce-de-leche-la-serenisima-clasico-400g-2/p",
            "vea": "https://www.vea.com.ar/dulce-de-leche-la-serenisima-clasico-400g-2/p",
            "dia": "https://diaonline.supermercadosdia.com.ar/dulce-de-leche-la-serenisima-clasico-400-gr-273372/p"
        }
    },

    "Huevos": {
        "Huevos blancos grandes 12u": {
            "carrefour": "https://www.carrefour.com.ar/huevos-blanco-el-mercado-plastico-12-uni-291306/p",
            "jumbo": "https://www.jumbo.com.ar/huevos-blancos-12-un-maxima/p",
            "disco": "https://www.disco.com.ar/huevos-blancos-12-un-maxima-2/p",
            "vea": "https://www.vea.com.ar/huevos-blancos-12-un-maxima-2/p",
            "dia": "https://diaonline.supermercadosdia.com.ar/huevo-blanco-grande-12-ud-48133/p"
        }
    },

    "Legumbres": {
        "Lentejas secas 400g": {
            "carrefour": "https://www.carrefour.com.ar/lentejas-carrefour-classic-400-g-738618/p",
            "jumbo": "https://www.jumbo.com.ar/lentejas-secas-400-grs-cuisine-co/p",
            "disco": "https://www.disco.com.ar/lentejas-secas-400-grs-cuisine-co/p",
            "vea": "https://www.vea.com.ar/lentejas-secas-400-grs-cuisine-co/p",
            "dia": "https://diaonline.supermercadosdia.com.ar/lentejas-dia-400-gr-292388/p"
        }
    },

    "Bebidas": {
        "Gaseosa Coca-Cola 1.75L": {
            "carrefour": "https://www.carrefour.com.ar/gaseosa-cola-coca-cola-sabor-original-175-lts-630677/p",
            "jumbo": "https://www.jumbo.com.ar/gaseosa-coca-cola-sabor-original-1-75-lt/p",
            "disco": "https://www.disco.com.ar/gaseosa-coca-cola-sabor-original-1-75-lt/p",
            "vea": "https://www.vea.com.ar/gaseosa-coca-cola-sabor-original-1-75-lt/p",
            "dia": "https://diaonline.supermercadosdia.com.ar/gaseosa-coca-cola-sabor-original-175-lt-249072/p"
        },
        "Cerveza Quilmes rubia clásica 1L": {
            "carrefour": "https://www.carrefour.com.ar/cerveza-rubia-clasica-quilmes-1-lt-505983/p",
            "jumbo": "https://www.jumbo.com.ar/cerveza-quilmes-clasica-1lt-ret/p",
            "disco": "https://www.disco.com.ar/cerveza-quilmes-clasica-1lt-ret/p",
            "vea": "https://www.vea.com.ar/cerveza-quilmes-clasica-1lt-ret/p",
            "dia": ""
        },
        "Vino tinto Cordero con piel de lobo 750ml": {
            "carrefour": "https://www.carrefour.com.ar/vino-tinto-cordero-con-piel-de-lobo-malbec-750-cc-730738/p",
            "jumbo": "https://www.jumbo.com.ar/vino-malbec-750-ml-cordero-con-piel-de-lobo/p",
            "disco": "https://www.disco.com.ar/vino-malbec-750-ml-cordero-con-piel-de-lobo/p",
            "vea": "https://www.vea.com.ar/vino-malbec-750-ml-cordero-con-piel-de-lobo/p",
            "dia": "https://diaonline.supermercadosdia.com.ar/vino-tinto-malbec-cordero-con-piel-de-lobo-750-ml-311936/p"
        }
    },

    "Yerba": {
        "Yerba Amanda tradicional 500g": {
            "carrefour": "https://www.carrefour.com.ar/yerba-mate-amanda-tradicional-500-grs-544972/p",
            "jumbo": "https://www.jumbo.com.ar/yerba-amanda-tradicional-500-grs/p",
            "disco": "https://www.disco.com.ar/yerba-amanda-tradicional-500-grs/p",
            "vea": "https://www.vea.com.ar/yerba-amanda-tradicional-500-grs/p",
            "dia": "https://diaonline.supermercadosdia.com.ar/yerba-mate-amanda-tradicional-500-gr-164681/p"
        }
    }
}

# --- Scrape Basket Function ---

async def scrape_canasta(canasta_dict):
    """
    Scrapea los precios de los productos en la canasta usando Playwright Async API
    e inserta los resultados en Supabase.

    Args:
        canasta_dict (dict): Diccionario anidado con la estructura canasta[categoria][producto][supermercado] = url.

    Returns:
        pd.DataFrame: DataFrame con las columnas categoria, producto, supermercado, precio, tipo_precio, fecha_scraping, url.
    """
    results = []
    for categoria, productos_dict in canasta_dict.items():
        for product_name, supermercados_dict in productos_dict.items():
            for supermercado, url in supermercados_dict.items():
                if not url or '...' in url:
                    print(f"Saltando URL inválida o placeholder para {categoria} - {product_name} - {supermercado}: {url}")
                    continue

                print(f"Scrapeando: {categoria} - {product_name} - {supermercado} ({url})")
                price_data = await scrape_price(url, supermercado) # <--- Llamada a la función actualizada
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

                # Esperar 3 segundos entre cada request
                await asyncio.sleep(3)

    df_result = pd.DataFrame(results)
    print(df_result.to_string()) # Reemplazado display(df_result) con print(df_result.to_string())

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
    asyncio.run(scrape_canasta(canasta))
