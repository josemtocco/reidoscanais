# 📺 Lista IPTV Otimizada para SS IPTV (Rei dos Canais)

Este repositório gera e mantém automaticamente uma lista M3U atualizada de canais de TV ao vivo, otimizada para uso no **SS IPTV**.

## 🚀 Recursos
- **Atualização Automática**: Executa a cada 6 horas via GitHub Actions.
- **Resiliência Inteligente**: Canais inativos não são removidos imediatamente. Eles só são excluídos após **6 verificações consecutivas com falha** (totalizando 36 horas), evitando remoções por oscilações temporárias de rede.
- **Descoberta de Novos Canais**: Adiciona automaticamente novos canais encontrados na API oficial.
- **Otimizado para SS IPTV**: Inclui tags `tvg-logo`, `group-title` (categorias) e link EPG do Brasil para guia de programação.
- **Extração de Link Direto**: O script tenta automaticamente extrair o link `.m3u8` real do player de embed. Se não for possível, mantém o link de fallback compatível.

## 📱 Como usar no SS IPTV
1. Obtenha o link **RAW** da playlist deste repositório: