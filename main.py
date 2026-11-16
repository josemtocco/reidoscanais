import requests
import json
import os
import re
from datetime import datetime, timezone

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

def extract_direct_stream(embed_url):
    """Tenta extrair um link .m3u8 direto do HTML do embed. Se falhar, retorna o próprio embed_url."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Referer': 'https://reidoscanais.im/'
    }
    try:
        response = requests.get(embed_url, headers=headers, timeout=5)
        # Procura por URLs terminadas em .m3u8 ou .m3u no código fonte
        match = re.search(r'(https?://[^\s\"\'<>]+\.m3u8[^\s\"\'<>]*)', response.text, re.IGNORECASE)
        if match:
            return match.group(1)
    except requests.exceptions.RequestException:
        pass
    return embed_url

def check_link_active(url):
    """Verifica se o link retorna um status HTTP 200 OK com timeout curto."""
    headers = {
        'User-Agent': 'VLC/3.0.18 LibVLC/3.0.18',
        'Accept': '*/*',
        'Referer': 'https://reidoscanais.im/'
    }
    try:
        # stream=True evita baixar o vídeo inteiro, pegando apenas os headers e alguns bytes
        response = requests.get(url, headers=headers, timeout=5, stream=True)
        if response.status_code == 200:
            ct = response.headers.get('content-type', '').lower()
            # Aceita tipos de conteúdo de vídeo, playlists ou HTML (embeds)
            if any(x in ct for x in ['video/', 'mpegurl', 'octet-stream', 'text/html']):
                return True
        return False
    except requests.exceptions.RequestException:
        return False

def main():
    state = load_state()
    now = datetime.now(timezone.utc).isoformat()
    
    # 1. Buscar dados da API (se falhar, usa o estado anterior para não apagar a lista)
    api_channels = []
    try:
        response = requests.get(API_URL, timeout=10)
        response.raise_for_status()
        data = response.json()
        api_channels = data.get('data', [])
        print(f"Sucesso: {len(api_channels)} canais encontrados na API.")
    except Exception as e:
        print(f"Aviso: Erro ao buscar API ({e}). Mantendo estado anterior para verificação.")

    # 2. Atualizar estado com canais da API
    found_urls = set()
    for ch in api_channels:
        name = ch.get('name', 'Sem Nome').strip()
        category = ch.get('category', 'Geral').strip()
        logo = ch.get('logo_url', '')
        embeds = ch.get('embeds', [])
        
        if not embeds:
            continue
            
        # Pega o primeiro embed disponível (geralmente o "Servidor Premium")
        url = embeds[0].get('embed_url', '')
        if not url:
            continue
            
        found_urls.add(url)
        
        if url in state['channels']:
            # Canal já existe: reseta falhas pois foi confirmado na API
            state['channels'][url]['failures'] = 0
            state['channels'][url]['last_seen'] = now
            state['channels'][url]['name'] = name
            state['channels'][url]['category'] = category
            state['channels'][url]['logo'] = logo
        else:
            # Canal novo: adiciona com 0 falhas
            state['channels'][url] = {
                'name': name,
                'category': category,
                'logo': logo,
                'failures': 0,
                'last_seen': now
            }

    # 3. Verificar atividade dos links e gerenciar remoção por inatividade
    channels_to_keep = {}
    print("Testando atividade dos links...")
    
    for url, info in state['channels'].items():
        # Se o canal sumiu da API, conta como falha
        if url not in found_urls:
            info['failures'] += 1
            
        # Teste ativo de conexão
        is_active = check_link_active(url)
        if not is_active:
            info['failures'] += 1
            
        # Só mantém se o número de falhas for menor que o limite (6 atualizações = 36h)
        if info['failures'] < MAX_FAILURES:
            channels_to_keep[url] = info
        else:
            print(f"Removido após {MAX_FAILURES} falhas: {info['name']}")

    state['channels'] = channels_to_keep
    save_state(state)

    # 4. Gerar playlist M3U otimizada para SS IPTV
    with open(PLAYLIST_FILE, 'w', encoding='utf-8') as f:
        # Adiciona link EPG do Brasil para guias de programação no SS IPTV
        f.write('#EXTM3U url-tvg="https://raw.githubusercontent.com/iptv-org/epg/master/guides/br.guide.xml"\n')
        
        for url, info in state['channels'].items():
            # Limpa caracteres que podem quebrar o parser M3U
            name = info['name'].replace(',', ' ').replace('"', "'")
            category = info['category'].replace(',', ' ').replace('"', "'")
            logo = info['logo']
            
            # Tenta obter link direto, senão usa o embed
            final_url = extract_direct_stream(url)
            
            f.write(f'#EXTINF:-1 tvg-id="{name}" tvg-name="{name}" tvg-logo="{logo}" group-title="{category}",{name}\n')
            f.write(f'{final_url}\n')

    print(f"✅ Playlist gerada com sucesso: {PLAYLIST_FILE} ({len(state['channels'])} canais ativos).")

if __name__ == '__main__':
    main()