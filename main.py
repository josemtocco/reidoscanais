import requests
import json
import os
import re
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs, unquote

STATE_FILE = 'state.json'
PLAYLIST_FILE = 'playlist.m3u8'
API_URL = 'https://api.reidoscanais.im/channels'
MAX_FAILURES = 6  # 6 atualizações * 6 horas = 36 horas antes de remover

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"channels": {}}

def save_state(state):
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

def get_direct_stream_url(embed_url, session):
    """Extrai o link .m3u8 real da página de embed, navegando em iframes e decodificando JS."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Referer': 'https://reidoscanais.im/'
    }
    
    try:
        # Step 1: Get main embed page
        resp1 = session.get(embed_url, headers=headers, timeout=8)
        if resp1.status_code != 200:
            return embed_url
            
        soup1 = BeautifulSoup(resp1.text, 'html.parser')
        
        # Step 2: Find iframe
        iframe = soup1.find('iframe')
        iframe_url = None
        if iframe and iframe.get('src'):
            iframe_url = iframe['src']
            if iframe_url.startswith('//'):
                iframe_url = 'https:' + iframe_url
            elif iframe_url.startswith('/'):
                iframe_url = f"https://{embed_url.split('/')[2]}{iframe_url}"
        
        # Fallback: look for external player URLs in HTML
        if not iframe_url:
            ext_match = re.search(r'(https?://[^\s"\'<>]+(?:embed|player)[^\s"\'<>]*)', resp1.text, re.IGNORECASE)
            if ext_match:
                iframe_url = ext_match.group(1)
                
        if not iframe_url:
            return embed_url
            
        # Step 3: Check if iframe URL has m3u8 as parameter (common in some providers)
        parsed_url = urlparse(iframe_url)
        query_params = parse_qs(parsed_url.query)
        for key in ['m3u8', 'file', 'url', 'stream', 'src', 'source']:
            if key in query_params:
                potential_stream = unquote(query_params[key][0])
                if '.m3u8' in potential_stream or '.mp4' in potential_stream:
                    return potential_stream
                    
        if '.m3u8' in iframe_url:
            return iframe_url
            
        # Step 4: Get iframe page
        headers['Referer'] = embed_url
        resp2 = session.get(iframe_url, headers=headers, timeout=8)
        if resp2.status_code != 200:
            return embed_url
            
        html2 = resp2.text
        
        # Step 5: Extract stream URL using patterns found in common players
        patterns = [
            r'const streamUrl\s*=\s*["\']([^"\']+)["\']',
            r'file:\s*["\']([^"\']+)["\']',
            r'source:\s*["\']([^"\']+)["\']',
            r'<source[^>]+src=["\']([^"\']+)["\']',
            r'video\.src\s*=\s*["\']([^"\']+)["\']',
            r'["\'](https?://[^"\']+\.m3u8[^"\']*)["\']'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, html2, re.IGNORECASE)
            if match:
                stream_url = match.group(1).replace('\/', '/').replace('\\', '')
                if stream_url.startswith('http') and ('.m3u8' in stream_url or '.mp4' in stream_url):
                    return stream_url
                    
        # Step 6: Check for nested iframe
        soup2 = BeautifulSoup(html2, 'html.parser')
        nested_iframe = soup2.find('iframe')
        if nested_iframe and nested_iframe.get('src'):
            nested_url = nested_iframe['src']
            if nested_url.startswith('//'):
                nested_url = 'https:' + nested_url
            elif nested_url.startswith('/'):
                nested_url = f"https://{iframe_url.split('/')[2]}{nested_url}"
            # Recursion for nested iframes
            return get_direct_stream_url(nested_url, session)
            
        return embed_url
        
    except Exception:
        return embed_url

def check_link_active(url, session):
    """Verifica se o link responde com 200 OK."""
    headers = {
        'User-Agent': 'VLC/3.0.18 LibVLC/3.0.18',
        'Accept': '*/*',
        'Referer': 'https://reidoscanais.im/'
    }
    try:
        response = session.get(url, headers=headers, timeout=5, stream=True)
        if response.status_code == 200:
            ct = response.headers.get('content-type', '').lower()
            if any(x in ct for x in ['video/', 'mpegurl', 'octet-stream', 'text/html']):
                return True
        return False
    except:
        return False

def main():
    state = load_state()
    now = datetime.now(timezone.utc).isoformat()
    
    session = requests.Session()
    
    # 1. Fetch API
    api_channels = []
    try:
        response = session.get(API_URL, timeout=15)
        response.raise_for_status()
        data = response.json()
        api_channels = data.get('data', [])
        print(f"✅ Sucesso: {len(api_channels)} canais encontrados na API.")
    except Exception as e:
        print(f"⚠️ Aviso: Erro ao buscar API ({e}). Mantendo estado anterior.")

    # 2. Update state
    found_urls = set()
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
            
        found_urls.add(embed_url)
        
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
                'last_seen': now
            }

    # 3. Check activity and manage failures
    channels_to_keep = {}
    print("🔍 Testando atividade e extraindo links reais...")
    
    for embed_url, info in state['channels'].items():
        if embed_url not in found_urls:
            info['failures'] += 1
            
        # Extract direct stream URL
        direct_url = get_direct_stream_url(embed_url, session)
        info['direct_url'] = direct_url
            
        # Check if the extracted direct URL is active
        is_active = check_link_active(direct_url, session)
        if not is_active:
            # If direct URL failed, check if the original embed URL is active
            is_active = check_link_active(embed_url, session)
            if not is_active:
                info['failures'] += 1
            else:
                info['failures'] = 0
        else:
            info['failures'] = 0
            
        if info['failures'] < MAX_FAILURES:
            channels_to_keep[embed_url] = info
        else:
            print(f"❌ Removido após {MAX_FAILURES} falhas: {info['name']}")

    state['channels'] = channels_to_keep
    save_state(state)

    # 4. Generate M3U
    with open(PLAYLIST_FILE, 'w', encoding='utf-8') as f:
        f.write('#EXTM3U url-tvg="https://raw.githubusercontent.com/iptv-org/epg/master/guides/br.guide.xml"\n')
        
        for embed_url, info in state['channels'].items():
            name = info['name'].replace(',', ' ').replace('"', "'")
            category = info['category'].replace(',', ' ').replace('"', "'")
            logo = info['logo']
            
            # Use the extracted direct URL if available and valid, otherwise fallback to embed URL
            final_url = info.get('direct_url', embed_url)
            if not final_url or not final_url.startswith('http'):
                final_url = embed_url
                
            f.write(f'#EXTINF:-1 tvg-id="{name}" tvg-name="{name}" tvg-logo="{logo}" group-title="{category}",{name}\n')
            f.write(f'{final_url}\n')

    print(f"✅ Playlist gerada com sucesso: {PLAYLIST_FILE} ({len(state['channels'])} canais ativos).")

if __name__ == '__main__':
    main()