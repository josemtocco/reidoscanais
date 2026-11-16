import requests
import json
import os
import re
import time
import base64
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs, unquote
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

STATE_FILE = 'state.json'
PLAYLIST_FILE = 'playlist.m3u8'
API_URL = 'https://api.reidoscanais.im/channels'
MAX_FAILURES = 6

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"channels": {}}

def save_state(state):
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

def setup_selenium():
    """Configura o Chrome headless para capturar requests de rede."""
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--window-size=1920,1080')
    chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
    
    # Habilita logging de performance para capturar requests
    chrome_options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})
    
    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        return driver
    except:
        # Fallback para chromedriver do sistema
        driver = webdriver.Chrome(options=chrome_options)
        return driver

def extract_stream_with_selenium(embed_url, driver):
    """Usa Selenium para carregar a página e capturar requests .m3u8."""
    m3u8_urls = []
    
    try:
        # Limpa logs anteriores
        driver.get('about:blank')
        time.sleep(1)
        
        # Navega para o embed
        driver.get(embed_url)
        
        # Aguarda a página carregar
        time.sleep(5)
        
        # Captura todos os logs de performance
        logs = driver.get_log('performance')
        
        for entry in logs:
            log_data = json.loads(entry['message'])
            message = log_data.get('message', {})
            
            # Procura por requests de rede
            if message.get('method') == 'Network.requestWillBeSent':
                params = message.get('params', {})
                request = params.get('request', {})
                url = request.get('url', '')
                
                # Verifica se é um link .m3u8
                if '.m3u8' in url or '.mp4' in url or '.ts' in url:
                    m3u8_urls.append(url)
            
            # Também verifica responses
            if message.get('method') == 'Network.responseReceived':
                params = message.get('params', {})
                response = params.get('response', {})
                url = response.get('url', '')
                
                if '.m3u8' in url or '.mp4' in url or '.ts' in url:
                    m3u8_urls.append(url)
        
        # Se não encontrou via logs, tenta extrair do DOM
        if not m3u8_urls:
            page_source = driver.page_source
            
            # Procura por URLs no código fonte
            patterns = [
                r'(https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*)',
                r'(https?://[^\s"\'<>]+\.mp4[^\s"\'<>]*)',
                r'(https?://[^\s"\'<>]+\.ts[^\s"\'<>]*)'
            ]
            
            for pattern in patterns:
                matches = re.findall(pattern, page_source, re.IGNORECASE)
                m3u8_urls.extend(matches)
        
        # Remove duplicatas e retorna o primeiro válido
        unique_urls = list(set(m3u8_urls))
        if unique_urls:
            # Prioriza links que parecem ser streams diretos
            for url in unique_urls:
                if 'master.m3u8' in url or 'index.m3u8' in url or 'video.m3u8' in url:
                    return url
            return unique_urls[0]
            
        return None
        
    except Exception as e:
        print(f"    ⚠️ Erro no Selenium: {e}")
        return None

def extract_with_requests_fallback(embed_url, session):
    """Fallback usando requests + BeautifulSoup para casos simples."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://reidoscanais.im/'
    }
    
    try:
        resp = session.get(embed_url, headers=headers, timeout=8)
        if resp.status_code != 200:
            return None
            
        # Procura por iframe
        iframe_match = re.search(r'<iframe[^>]+src=["\']([^"\']+)["\']', resp.text, re.IGNORECASE)
        if iframe_match:
            iframe_url = iframe_match.group(1)
            if iframe_url.startswith('//'):
                iframe_url = 'https:' + iframe_url
            elif iframe_url.startswith('/'):
                iframe_url = f"https://{embed_url.split('/')[2]}{iframe_url}"
            
            # Verifica se o iframe tem o stream como parâmetro
            parsed = urlparse(iframe_url)
            params = parse_qs(parsed.query)
            for key in ['m3u8', 'file', 'url', 'stream', 'src']:
                if key in params:
                    potential = unquote(params[key][0])
                    if '.m3u8' in potential or '.mp4' in potential:
                        return potential
            
            if '.m3u8' in iframe_url:
                return iframe_url
                
        # Procura por links diretos no HTML
        m3u8_match = re.search(r'(https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*)', resp.text, re.IGNORECASE)
        if m3u8_match:
            return m3u8_match.group(1)
            
        return None
        
    except:
        return None

def extract_real_stream(embed_url, session, driver):
    """Tenta extrair o stream usando Selenium primeiro, depois fallback para requests."""
    # Tenta com Selenium (mais robusto)
    stream_url = extract_stream_with_selenium(embed_url, driver)
    if stream_url:
        return stream_url
    
    # Fallback para requests
    stream_url = extract_with_requests_fallback(embed_url, session)
    if stream_url:
        return stream_url
    
    return None

def main():
    state = load_state()
    now = datetime.now(timezone.utc).isoformat()
    session = requests.Session()
    
    print("🚀 Iniciando atualização da playlist...")
    
    # 1. Buscar todos os canais da API
    api_channels = []
    try:
        resp = session.get(API_URL, timeout=15)
        resp.raise_for_status()
        api_channels = resp.json().get('data', [])
        print(f"✅ {len(api_channels)} canais encontrados na API.")
    except Exception as e:
        print(f"⚠️ Erro na API: {e}. Usando estado anterior.")

    # 2. Processar todos os canais
    found_embeds = set()
    for ch in api_channels:
        name = ch.get('name', 'Sem Nome').strip()
        category = ch.get('category', 'Geral').strip()
        logo = ch.get('logo_url', '')
        embeds = ch.get('embeds', [])
        
        if not embeds:
            continue
            
        embed_url = embeds[0].get('embed_url', '')
        if not embed_url:
            continue
            
        found_embeds.add(embed_url)
        
        if embed_url in state['channels']:
            state['channels'][embed_url]['failures'] = 0
            state['channels'][embed_url]['last_seen'] = now
            state['channels'][embed_url]['name'] = name
            state['channels'][embed_url]['category'] = category
            state['channels'][embed_url]['logo'] = logo
        else:
            state['channels'][embed_url] = {
                'name': name,
                'category': category,
                'logo': logo,
                'failures': 0,
                'last_seen': now,
                'stream_url': None
            }

    # 3. Inicializar Selenium
    print("🌐 Iniciando navegador headless...")
    driver = None
    try:
        driver = setup_selenium()
        print("✅ Navegador iniciado com sucesso.")
    except Exception as e:
        print(f"⚠️ Erro ao iniciar Selenium: {e}. Usando apenas requests.")

    # 4. Extrair links de stream
    print("🔍 Extraindo links de stream...")
    extracted_count = 0
    
    for i, (embed_url, info) in enumerate(state['channels'].items(), 1):
        if embed_url not in found_embeds:
            info['failures'] += 1
            continue
        
        print(f"  [{i}/{len(state['channels'])}] Processando: {info['name']}")
        
        # Tenta extrair o stream
        stream_url = None
        if driver:
            stream_url = extract_real_stream(embed_url, session, driver)
        else:
            stream_url = extract_with_requests_fallback(embed_url, session)
        
        if stream_url:
            info['stream_url'] = stream_url
            extracted_count += 1
            print(f"    ✅ Extraído: {stream_url[:70]}...")
        else:
            info['stream_url'] = embed_url
            print(f"    ⚠️ Fallback para embed")

    # 5. Fechar Selenium
    if driver:
        driver.quit()
        print("✅ Navegador fechado.")

    # 6. Remover canais que sumiram da API
    channels_to_keep = {}
    for embed_url, info in state['channels'].items():
        if info['failures'] < MAX_FAILURES:
            channels_to_keep[embed_url] = info
        else:
            print(f"  ❌ Removido: {info['name']}")

    state['channels'] = channels_to_keep
    save_state(state)

    # 7. Gerar playlist M3U
    with open(PLAYLIST_FILE, 'w', encoding='utf-8') as f:
        f.write('#EXTM3U url-tvg="https://raw.githubusercontent.com/iptv-org/epg/master/guides/br.guide.xml"\n')
        
        for embed_url, info in state['channels'].items():
            final_url = info.get('stream_url', embed_url)
            
            name = info['name'].replace(',', ' ').replace('"', "'")
            category = info['category'].replace(',', ' ').replace('"', "'")
            logo = info['logo']
            
            f.write(f'#EXTINF:-1 tvg-id="{name}" tvg-name="{name}" tvg-logo="{logo}" group-title="{category}",{name}\n')
            f.write(f'{final_url}\n')

    print(f"\n🎉 SUCESSO!")
    print(f"📊 Total de canais: {len(state['channels'])}")
    print(f"🔗 Links extraídos: {extracted_count}")
    print(f"📄 Playlist: {PLAYLIST_FILE}")

if __name__ == '__main__':
    main()