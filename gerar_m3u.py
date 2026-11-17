# -*- coding: utf-8 -*-
"""
Rei dos Canais -> M3U para SS IPTV

O que o script faz, em ordem:
  1. Le o catalogo completo do site (todos os canais, com a categoria do proprio site).
  2. Para cada canal percorre a cadeia de reproducao com um navegador real e captura
     o endereco REAL do video em HLS (.m3u8) usado pelo player.
  3. Testa de verdade se o canal TOCA: abre o video com o ffmpeg e decodifica um
     quadro de imagem. HTTP 200 nao conta como "tocando".
  4. Monta a M3U agrupada pelas categorias do site.
  5. Reconciliacao: mantem quem toca, soma falha de quem nao toca, remove somente
     depois de 6 atualizacoes seguidas sem tocar, adiciona canal novo automaticamente.
     Falha de rede/geo (inconclusivo) NAO conta como falha do canal.

Requisitos: Python 3.9+, Playwright (chromium) e ffmpeg no PATH.
Os links de video expiram em ~6 horas: por isso a atualizacao roda a cada 6h.
"""
import gzip
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

# ------------------------------------------------------------------ config
BASE_URL      = "https://reidoscanais.im"
API_URL       = "https://api.reidoscanais.im"
SITE_PLAYER   = "https://rdcanais.org"   # descobre sozinho o dominio atual do player
# dominios onde o player costuma aparecer (usados so como pista ao rotear)
PLAYER_DOMINIOS = ("rdcanais.", ".cc/", "rdcanais.org")

ESTADO        = "estado_canais.json"
SAIDA         = "reidoscanais.m3u"
RELATORIO     = "relatorio.json"
SCRIPT_PLAYER = os.path.join("player", "player_captura.js")
ORDEM_CONFIG  = "config_ordem.json"

FALHAS_LIM    = 6      # remover o canal so depois de 6 atualizacoes seguidas sem tocar
TIMEOUT_PAG   = 25000  # ms para abrir uma pagina de player
ESPERA_JS     = 3200   # ms de espera para o player pedir o video
MAX_TESTE     = 3      # quantos links testar por canal

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# rotinas que autorizam a leitura dentro do player
AJUSTE_JS = ("function _0x3e83e1(_0x4823d5){",
             "function _0x3e83e1(_0x4823d5){return true;")


# ------------------------------------------------------------------ utilidades
def log(msg):
    print(msg, flush=True)


def http_text(url, ref=None, timeout=30):
    h = {"User-Agent": UA, "Accept": "*/*"}
    if ref:
        h["Referer"] = ref
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        b = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            b = gzip.decompress(b)
        return b.decode("utf-8", "ignore")


def ffmpeg_ok():
    return shutil.which("ffmpeg") is not None


# ------------------------------------------------------------------ 1. catalogo
def coletar_catalogo():
    """Catalogo completo: todos os canais e categorias do site."""
    canais = []
    try:
        req = urllib.request.Request(API_URL + "/channels", headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=60) as r:
            canais = (json.loads(r.read().decode("utf-8", "ignore")) or {}).get("data") or []
    except Exception as ex:
        log("[catalogo] falha ao ler o catalogo (%s)" % str(ex)[:80])

    # reserva: catalogo salvo no repositorio (a lista nunca fica vazia)
    if not canais and os.path.exists("dados_base.json"):
        log("[aviso] usando o catalogo salvo em dados_base.json")
        canais = json.load(open("dados_base.json", encoding="utf-8"))["data"]

    log("[catalogo] %d canais encontrados" % len(canais))
    cats = {}
    for c in canais:
        cat = (c.get("category") or "Outros").strip()
        cats[cat] = cats.get(cat, 0) + 1
    for cat in sorted(cats):
        log("   %-20s %3d" % (cat, cats[cat]))
    return canais


# ------------------------------------------------------------------ 2. captura
def descobrir_player(canal):
    """Descobre qual dominio aquele canal usa hoje como pagina de player."""
    global SITE_PLAYER
    for e in canal.get("embeds") or []:
        u = (e.get("embed_url") or "").strip()
        if "://" in u:
            dom = u.split("://", 1)[1].split("/")[0]
            if dom and dom not in ("reidoscanais.im", "api.reidoscanais.im"):
                SITE_PLAYER = "https://" + dom
                return


def paginas_do_canal(canal):
    """Paginas de player do canal, na ordem de preferencia.

    Cada embed do site e aberto: dele saem tanto jogadores que recebem o endereco
    do video pronto quanto os quadros externos que montam esse jogador.
    """
    paginas, vistos = [], set()
    descobrir_player(canal)

    def add(item):
        if item[1] and item[1] not in vistos:
            vistos.add(item[1])
            paginas.append(item)

    for e in canal.get("embeds") or []:
        u = (e.get("embed_url") or "").strip()
        if not u:
            continue
        try:
            html = http_text(u, ref=BASE_URL + "/", timeout=25)
        except Exception:
            html = ""

        # 1) jogador que ja recebe o endereco do video na propria URL
        for alvo in re.findall(r"player\.html\?m3u8=([^\"'&<>\s]+)", html):
            add(("direto", urllib.parse.unquote(alvo).replace("\\", "")))

        # 2) quadros externos que montam o jogador
        for alvo in re.findall(r"https://[^\"'<>\s]+\.html", html):
            if any(k in alvo for k in ("player", "/tv/", "/play/", "/embed/")):
                add(("player", alvo))

        # 3) o proprio endereco do embed
        add(("player", u))
    return paginas


def script_do_player():
    """Script do jogador fornecido junto com o projeto (ja ajustado)."""
    if not os.path.exists(SCRIPT_PLAYER):
        return None
    return open(SCRIPT_PLAYER, encoding="utf-8", errors="ignore").read()


def ajustar_corpo(corpo):
    if AJUSTE_JS[0] in corpo and "return true;" not in corpo[:corpo.find(AJUSTE_JS[0]) + 120]:
        return corpo.replace(AJUSTE_JS[0], AJUSTE_JS[1], 1)
    return corpo


def novo_navegador(p):
    b = p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage",
                                "--autoplay-policy=no-user-gesture-required",
                                "--mute-audio"])
    ctx = b.new_context(user_agent=UA, locale="pt-BR")
    pg = ctx.new_page()
    script = script_do_player()
    capturados = {"hls": [], "ativo": False}

    def guardar(url):
        # so conta o que a pagina aberta AGORA pediu (evita herdar o link do canal anterior)
        if ".m3u8" in url and capturados.get("ativo"):
            capturados["hls"].append(url)

    pg.on("request", lambda r: guardar(r.url))

    def rotear(rota):
        url = rota.request.url
        try:
            if script and re.search(r"/assets?/.*\.js", url):
                resp = rota.fetch()
                corpo = resp.body().decode("utf-8", "ignore")
                if AJUSTE_JS[0] in corpo:
                    rota.fulfill(status=200, content_type="application/javascript",
                                 body=ajustar_corpo(corpo))
                    return
                rota.fulfill(response=resp)
                return
        except Exception:
            pass
        try:
            h = dict(rota.request.headers)
            h["referer"] = SITE_PLAYER + "/"
            h.setdefault("origin", SITE_PLAYER)
            rota.fulfill(response=rota.fetch(headers=h))
        except Exception:
            try:
                rota.abort()
            except Exception:
                pass

    pg.route("**/*", rotear)
    return b, pg, capturados


def testar_video(url):
    """Toca de verdade: abre o video e extrai 1 quadro com o ffmpeg.

    Retorna (estado, motivo) com estado =
      'tocando'      -> quadro de video decodificado
      'quebrado'     -> o servidor respondeu que o canal esta fora do ar
      'inconclusivo' -> nao deu para avaliar (rede/geo/sem ffmpeg) -> nao conta falha
    """
    if not ffmpeg_ok():
        return "inconclusivo", "ffmpeg nao encontrado no PATH"

    try:
        cabecalho = http_text(url, timeout=20)
    except urllib.error.HTTPError as ex:
        return "quebrado", "servidor respondeu %s" % ex.code
    except Exception as ex:
        msg = str(ex)
        if any(k in msg for k in ("403", "404", "410")):
            return "quebrado", msg[:120]
        return "inconclusivo", ("rede: " + msg)[:120]
    if "#EXTM3U" not in cabecalho:
        return "quebrado", "resposta nao e HLS"

    arq = os.path.join(tempfile.gettempdir(), "rc_check.jpg")
    try:
        if os.path.exists(arq):
            os.remove(arq)
    except Exception:
        pass

    # Observacao: em transmissao ao vivo NAO se usa corte de tempo (o corte cai no
    # vazio e da falso negativo). Aqui o player e aberto e o primeiro quadro e lido.
    cmd = ["ffmpeg", "-v", "error", "-i", url, "-frames:v", "1",
           "-f", "image2", "-y", arq]
    try:
        subprocess.run(cmd, capture_output=True, timeout=60)
    except FileNotFoundError:
        return "inconclusivo", "ffmpeg ausente"
    except subprocess.TimeoutExpired:
        return "inconclusivo", "timeout na decodificacao"

    if os.path.exists(arq) and os.path.getsize(arq) > 3000:
        try:
            os.remove(arq)
        except Exception:
            pass
        return "tocando", "quadro de video decodificado"
    return "quebrado", "sem quadro de video"


def capturar(canal, pg, capturados):
    """Percorre as paginas do canal ate achar um link de video que realmente toca."""
    candidatos = []
    for tipo, alvo in paginas_do_canal(canal):
        if tipo == "direto":
            candidatos.append(alvo)
            continue
        capturados["hls"] = []
        capturados["ativo"] = False
        ok_pag = True
        try:
            pg.goto(alvo, wait_until="domcontentloaded", timeout=TIMEOUT_PAG)
        except Exception:
            ok_pag = False
        capturados["ativo"] = True
        try:
            pg.wait_for_timeout(ESPERA_JS)
        except Exception:
            pass
        capturados["ativo"] = False
        if not ok_pag and not capturados["hls"]:
            # a pagina nao abriu: tenta de novo uma vez (rede instavel no servidor)
            try:
                pg.goto(alvo, wait_until="domcontentloaded", timeout=TIMEOUT_PAG)
                capturados["ativo"] = True
                pg.wait_for_timeout(ESPERA_JS)
                capturados["ativo"] = False
            except Exception:
                pass
        achados = [u for u in capturados["hls"] if u.endswith("index.m3u8") or "/master" in u]
        if achados:
            candidatos.extend(achados[:MAX_TESTE])
            break

    vistos = []
    for u in candidatos:
        if u not in vistos:
            vistos.append(u)

    if not vistos:
        return None, "quebrado", "o player nao entregou link de video"

    pior, motivo = "quebrado", "sem quadro de video"
    for url in vistos[:MAX_TESTE]:
        estado, msg = testar_video(url)
        if estado == "tocando":
            return url, "tocando", msg
        if estado == "inconclusivo" and pior != "inconclusivo":
            pior = "inconclusivo"
        motivo = msg
    return None, pior, motivo


# ------------------------------------------------------------------ 3. M3U
def ordem_categorias(catalogo):
    """Ordem de exibicao. Pode ser fixada em config_ordem.json (lista de nomes)."""
    if os.path.exists(ORDEM_CONFIG):
        try:
            return [x.strip() for x in json.load(open(ORDEM_CONFIG, encoding="utf-8"))]
        except Exception:
            pass
    ordem = []
    for c in catalogo:
        cat = (c.get("category") or "Outros").strip()
        if cat not in ordem:
            ordem.append(cat)
    return ordem


def escrever_m3u(canais, ordem=None):
    if ordem is None:
        ordem = []
        for c in canais:
            if c["categoria"] not in ordem:
                ordem.append(c["categoria"])

    restantes = list(canais)
    sequencia = list(ordem)
    for c in restantes:
        if c["categoria"] not in sequencia:
            sequencia.append(c["categoria"])

    linhas = ["#EXTM3U"]
    for cat in sequencia:
        grupo = [c for c in restantes if c["categoria"] == cat]
        if not grupo:
            continue
        for c in grupo:
            nome = c["nome"].replace('"', "").strip()
            linhas.append(
                '#EXTINF:-1 tvg-id="%s" tvg-name="%s" tvg-logo="%s" '
                'group-title="%s" content-type="video",%s'
                % (c["id"], nome, c.get("logo", ""), cat, nome)
            )
            linhas.append(c["url"])
    return "\n".join(linhas) + "\n"


# ------------------------------------------------------------------ 4. principal
def main():
    inicio = time.time()
    log("=" * 62)
    log(" Rei dos Canais -> M3U para SS IPTV ")
    log("=" * 62)

    catalogo = coletar_catalogo()
    if not catalogo:
        log("[erro] catalogo vazio: nada a fazer, lista anterior preservada")
        return 0

    estado = {}
    if os.path.exists(ESTADO):
        try:
            estado = {c["id"]: c for c in json.load(open(ESTADO, encoding="utf-8"))["canais"]}
        except Exception:
            estado = {}
    log("[estado] %d canais no historico" % len(estado))

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log("[erro] Playwright nao instalado. Rode: python -m pip install playwright "
            "e depois python -m playwright install chromium")
        return 1

    if not ffmpeg_ok():
        log("[aviso] ffmpeg nao encontrado: os canais ficarao como inconclusivos")

    agora = int(time.time())
    final, relatorio = [], []
    total = len(catalogo)

    with sync_playwright() as p:
        browser, pg, capturados = novo_navegador(p)
        try:
            for i, canal in enumerate(catalogo, 1):
                cid = canal.get("id")
                nome = canal.get("name") or cid
                cat = (canal.get("category") or "Outros").strip()
                ant = estado.get(cid, {})
                item = {
                    "id": cid, "nome": nome, "categoria": cat,
                    "logo": canal.get("logo_url") or "", "url": "",
                    "falhas": int(ant.get("falhas", 0)),
                    "primeiro_visto": ant.get("primeiro_visto", agora),
                    "visto": agora,
                }
                try:
                    url, status, motivo = capturar(canal, pg, capturados)
                except Exception as ex:
                    url, status, motivo = None, "inconclusivo", str(ex)[:120]

                if status == "tocando":
                    item["url"] = url
                    item["falhas"] = 0
                    item["status"] = "tocando"
                    final.append(item)
                elif status == "inconclusivo":
                    # rede / geo / tempo: nao penaliza e mantem o link anterior
                    item["url"] = ant.get("url", "")
                    item["status"] = "inconclusivo"
                    if item["url"]:
                        final.append(item)
                else:
                    item["falhas"] += 1
                    item["status"] = status
                    if item["falhas"] < FALHAS_LIM:
                        item["url"] = ant.get("url", "")
                        if item["url"]:
                            final.append(item)
                    else:
                        log("   [removido] %s (falhou %d atualizacoes seguidas)"
                            % (nome, item["falhas"]))

                relatorio.append({"id": cid, "nome": nome, "categoria": cat,
                                  "status": status, "motivo": motivo,
                                  "falhas": item["falhas"], "url": url or ""})
                if i % 10 == 0 or i == total:
                    log("   ... %d/%d" % (i, total))
        finally:
            browser.close()

    ordem = ordem_categorias(catalogo)
    final.sort(key=lambda x: (ordem.index(x["categoria"]) if x["categoria"] in ordem else 99,
                              x["nome"].lower()))

    m3u = escrever_m3u(list(final), ordem)
    open(SAIDA, "w", encoding="utf-8").write(m3u)

    json.dump({"ultima_atualizacao": agora, "total_site": total, "canais": final},
              open(ESTADO, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    contagem = {}
    for r in relatorio:
        contagem[r["status"]] = contagem.get(r["status"], 0) + 1
    json.dump({"quando": agora, "duracao_seg": round(time.time() - inicio),
               "resumo": contagem, "canais": relatorio},
              open(RELATORIO, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    log("-" * 62)
    log("[resultado] tocando: %d | quebrado: %d | inconclusivo: %d | na lista: %d"
        % (contagem.get("tocando", 0), contagem.get("quebrado", 0),
           contagem.get("inconclusivo", 0), len(final)))
    log("[arquivo] %s (%d linhas) em %ds" % (SAIDA, len(m3u.splitlines()),
                                              round(time.time() - inicio)))
    log("Os links de video expiram em ~6h: a atualizacao automatica os renova.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
