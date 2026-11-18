# Rei dos Canais → M3U para SS IPTV

Lista M3U gerada automaticamente a partir de `https://reidoscanais.im/canais`,
atualizada **a cada 6 horas** pelo GitHub Actions.

**Última geração:** 49 canais tocando, testados um por um (veja `relatorio.json`).

---

## Como funciona

1. **Coleta** — lê o catálogo completo do site (105 canais em 7 categorias) e mantém
   o nome e a categoria original de cada um.
2. **Captura do link real** — para cada canal, o script abre a página com um navegador
   de verdade e percorre a cadeia do player até capturar o endereço **HLS (.m3u8)**
   que o player usa para exibir o vídeo. Nada de gravar a página do player na lista:
   o que vai para a M3U é o link de vídeo.
3. **Teste de reprodução** — o `ffmpeg` abre o link e precisa decodificar **um quadro
   de imagem**. HTTP 200 não conta como "tocando". Cada canal fica com um dos estados:
   - `tocando` → quadro de vídeo obtido;
   - `quebrado` → servidor respondeu 404/403/504 ou não há vídeo no momento;
   - `inconclusivo` → falha de rede/geo, **não conta como falha do canal**.
4. **Reconciliação** — quem toca entra na lista com o contador zerado; quem falha soma
   +1 e **só é removido depois de 6 atualizações seguidas falhando** (`estado_canais.json`);
   canal novo que apareça no site entra automaticamente.
5. **Montagem da M3U** — agrupada pelas categorias do site, com `tvg-id`, `tvg-name`,
   `tvg-logo` e `content-type="video"`.

---

## Por que a lista tem 49 canais e o site mostra 105

O site publica 105 canais, mas nem todos entregam vídeo em HLS:

| Situação | Canais | Aparecem na lista? |
|---|---|---|
| Tocando em HLS (testado) | 49 | Sim |
| Player entrega outro formato protegido (DASH/CENC) | ~45 | Não — o SS IPTV não abre esse formato |
| Fora do ar no momento (erro 504 no servidor de vídeo) | ~11 | Não (voltam sozinhos quando o servidor responde) |

Essa proporção muda ao longo do dia: quando o servidor de um canal volta, ele entra
na atualização seguinte sem você fazer nada. O `relatorio.json` mostra o motivo de
cada canal que ficou de fora.

---

## Uso no SS IPTV

1. Crie um repositório no GitHub e envie todos os arquivos (o workflow já está em
   `.github/workflows/atualizar.yml`).
2. Vá em **Actions → Atualizar lista M3U → Run workflow** para gerar a primeira lista.
3. No SS IPTV: **Configurações → Lista de reprodução → Adicionar** e informe
   `https://raw.githubusercontent.com/SEU_USUARIO/SEU_REPO/main/reidoscanais.m3u`
4. O SS IPTV separa os canais pelas **categorias** (`group-title`) e mostra os logos.

> **Importante:** os links de vídeo são temporários (valem ~6 horas). É a atualização
> automática de 6 em 6 horas que os renova. Não use um arquivo baixado uma única vez.

---

## Rodar no seu PC (Brasil)

Dê duplo clique em `rodar_no_brasil.bat`. Ele instala o necessário e gera:

- `reidoscanais.m3u` — a lista;
- `estado_canais.json` — histórico e contador de 6 falhas;
- `relatorio.json` — o que foi testado e o resultado de cada canal.

Requisitos: Python 3.9+ e `ffmpeg` no PATH (o `.bat` avisa se não encontrar).

---

## Arquivos

| Arquivo | Função |
|---|---|
| `gerar_m3u.py` | coleta, captura o HLS, testa a reprodução e reconcilia |
| `reidoscanais.m3u` | **lista final** (49 canais tocando) |
| `estado_canais.json` | histórico + contador de 6 falhas |
| `relatorio.json` | resultado do teste de cada canal |
| `config_ordem.json` | ordem das categorias na lista |
| `dados_base.json` | catálogo reserva (usado só se o site sair do ar) |
| `rodar_no_brasil.bat` | execução local no Windows |
| `PROXY.md` | observações sobre canais em formato protegido |
