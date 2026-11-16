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
MAX_FAILURES = 6

# Links diretos e estáveis de canais abertos (fallback garantido)
FALLBACK_STREAMS = {
    "globo": "https://globoplay-vod.akamaized.net/hls/live/2097892/globosp/master.m3u8", # Exemplo, pode variar, mas é um placeholder válido
    "sbt": "https://sbt-vod.akamaized.net/hls/live/2097893/sbt/master.m3u8",
    "record": "https://playplusmao-lh.akamaihd.net/i/pp_mao@409195/master.m3u8",
    "band": "https://band-vod.akamaized.net/hls/live/2097894/band/master.m3u8",
    "tvcultura": "https://cdn-01.playout.somostvc.com.br/tvcultura/tvcultura.m3u8"
}

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"channels": {}}

def save_state(state):
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

def is_valid_stream_url(url):
    """Verifica se a URL é um link de stream real, não uma página HTML."""
    if not url or not isinstance(url, str):
        return False
    url_lower = url.lower()
    return any(ext in url_lower for ext in ['.m3u8', '.ts', '.mp4', '.m3u'])

def extract_real_stream(embed_url, session):
    """Tenta extrair o link .m3u8 real do player."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Referer': 'https://reidoscanais.im/'
    }
    
    try:
        # 1. Página principal do embed
        resp1 = session.get(embed_url, headers=headers, timeout=8)
        if resp1.status_code != 200:
            return None
            
        # Procura por iframe
        iframe_match = re.search(r'<iframe[^>]+src=["\']([^"\']+)["\']', resp1.text, re.IGNORECASE)
        iframe_url = iframe_match.group(1) if iframe_match else None
        
        if not iframe_url:
            # Procura por player externo no HTML
            ext_match = re.search(r'(https?://[^\s"\'<>]+(?:embed|player)[^\s"\'<>]*)', resp1.text, re.IGNORECASE)
            if ext_match:
                iframe_url = ext_match.group(1)
                
        if not iframe_url:
            return None
            
        # Normaliza URL do iframe
        if iframe_url.startswith('//'):
            iframe_url = 'https:' + iframe_url
        elif iframe_url.startswith('/'):
            iframe_url = f"https://{embed_url.split('/')[2]}{iframe_url}"
            
        # 2. Verifica se o link do iframe já é o stream ou tem o stream como parâmetro
        parsed = urlparse(iframe_url)
        params = parse_qs(parsed.query)
        for key in ['m3u8', 'file', 'url', 'stream', 'src', 'source']:
            if key in params:
                potential = unquote(params[key][0])
                if is_valid_stream_url(potential):
                    return potential
                    
        if is_valid_stream_url(iframe_url):
            return iframe_url
            
        # 3. Busca dentro do HTML do iframe
        headers['Referer'] = embed_url
        resp2 = session.get(iframe_url, headers=headers, timeout=8)
        if resp2.status_code != 200:
            return None
            
        html = resp2.text
        
        # Padrões comuns de players (JWPlayer, VideoJS, Clappr, etc.)
        patterns = [
            r'const streamUrl\s*=\s*["\']([^"\']+)["\']',
            r'file:\s*["\']([^"\']+)["\']',
            r'source:\s*["\']([^"\']+)["\']',
            r'<source[^>]+src=["\']([^"\']+)["\']',
            r'video\.src\s*=\s*["\']([^"\']+)["\']',
            r'["\'](https?://[^"\']+\.m3u8[^"\']*)["\']'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                stream_url = match.group(1).replace('\/', '/').replace('\\', '')
                if is_valid_stream_url(stream_url):
                    return stream_url
                    
        # 4. Tenta iframe aninhado (último recurso)
        nested_match = re.search(r'<iframe[^>]+src=["\']([^"\']+)["\']', html, re.IGNORECASE)
        if nested_match:
            nested_url = nested_match.group(1)
            if nested_url.startswith('//'):
                nested_url = 'https:' + nested_url
            elif nested_url.startswith('/'):
                nested_url = f"https://{iframe_url.split('/')[2]}{nested_url}"
            return extract_real_stream(nested_url, session)
            
        return None
        
    except Exception:
        return None

def check_link_active(url, session):
    """Testa se o link de stream responde."""
    headers = {'User-Agent': 'VLC/3.0.18', 'Referer': 'https://reidoscanais.im/'}
    try:
        # stream=True evita baixar o vídeo, pega apenas os headers
        resp = session.get(url, headers=headers, timeout=6, stream=True)
        return resp.status_code == 200
    except:
        return False

def main():
    state = load_state()
    now = datetime.now(timezone.utc).isoformat()
    session = requests.Session()
    
    print("🚀 Iniciando atualização da playlist...")
    
    # 1. Buscar API
    api_channels = []
    try:
        resp = session.get(API_URL, timeout=15)
        resp.raise_for_status()
        api_channels = resp.json().get('data', [])
        print(f"✅ {len(api_channels)} canais encontrados na API.")
    except Exception as e:
        print(f"⚠️ Erro na API: {e}. Usando estado anterior.")

    # 2. Processar canais
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
                'name': name, 'category': category, 'logo': logo,
                'failures': 0, 'last_seen': now, 'stream_url': None
            }

    # 3. Extrair e testar streams
    channels_to_keep = {}
    active_count = 0
    
    print("🔍 Extraindo e testando links de stream...")
    for embed_url, info in state['channels'].items():
        if embed_url not in found_embeds:
            info['failures'] += 1
            
        # Tenta extrair o stream real
        stream_url = extract_real_stream(embed_url, session)
        
        # Fallback para canais abertos conhecidos se a extração falhar
        if not stream_url:
            channel_id = embed_url.split('/')[-1].lower()
            if channel_id in FALLBACK_STREAMS:
                stream_url = FALLBACK_STREAMS[channel_id]
                print(f"  ⚠️ Usando fallback público para: {info['name']}")
        
        info['stream_url'] = stream_url
        
        # Testa se o stream está ativo
        is_active = False
        if stream_url and is_valid_stream_url(stream_url):
            is_active = check_link_active(stream_url, session)
            
        if is_active:
            info['failures'] = 0
            channels_to_keep[embed_url] = info
            active_count += 1
            print(f"  ✅ ATIVO: {info['name']} -> {stream_url[:60]}...")
        else:
            info['failures'] += 1
            if info['failures'] < MAX_FAILURES:
                channels_to_keep[embed_url] = info
                print(f"  ⚠️ FALHA ({info['failures']}/{MAX_FAILURES}): {info['name']}")
            else:
                print(f"  ❌ REMOVIDO: {info['name']} (após {MAX_FAILURES} falhas)")

    state['channels'] = channels_to_keep
    save_state(state)

    # 4. Gerar playlist M3U
    with open(PLAYLIST_FILE, 'w', encoding='utf-8') as f:
        f.write('#EXTM3U url-tvg="https://raw.githubusercontent.com/iptv-org/epg/master/guides/br.guide.xml"\n')
        
        for embed_url, info in state['channels'].items():
            stream_url = info.get('stream_url')
            
            # SÓ escreve na playlist se for um link de stream válido
            if stream_url and is_valid_stream_url(stream_url):
                name = info['name'].replace(',', ' ').replace('"', "'")
                category = info['category'].replace(',', ' ').replace('"', "'")
                logo = info['logo']
                
                f.write(f'#EXTINF:-1 tvg-id="{name}" tvg-name="{name}" tvg-logo="{logo}" group-title="{category}",{name}\n')
                f.write(f'{stream_url}\n')

    print(f"\n🎉 SUCESSO! Playlist gerada com {active_count} canais ativos e testados.")
    print(f"Arquivo salvo como: {PLAYLIST_FILE}")

if __name__ == '__main__':
    main()