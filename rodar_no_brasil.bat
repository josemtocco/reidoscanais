@echo off
chcp 65001 >nul
title Rei dos Canais - Gerar M3U (SS IPTV)

where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo [AVISO] ffmpeg nao encontrado no PATH.
  echo         Sem ele o teste de reproducao nao roda e os canais ficam "inconclusivos".
  echo         Instale em C:\ffmpeg e adicione C:\ffmpeg\bin ao PATH.
  echo.
)

echo Instalando dependencias ^(so na primeira vez^)...
python -m pip install --quiet playwright
python -m playwright install chromium

echo.
echo Gerando a lista e TESTANDO cada canal ^(leva alguns minutos^)...
python gerar_m3u.py

echo.
echo Pronto! Arquivos gerados:
 echo   reidoscanais.m3u    - a lista para o SS IPTV
 echo   estado_canais.json  - historico / contador de 6 falhas
 echo   relatorio.json      - resultado do teste de cada canal
pause
