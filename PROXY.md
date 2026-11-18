# Canais que ficaram fora da lista

Nem todo canal do site entrega vídeo em **HLS (.m3u8)**. Parte deles usa outro
formato protegido, que o SS IPTV e o VLC não conseguem abrir. Esses canais **não**
entram na M3U — colocar um link que não toca só atrapalha a navegação na TV.

## Como identificar

Abra o `relatorio.json` e procure o motivo:

- `sem transmissao em HLS (player entrega outro formato)` → o player do canal não
expõe um `.m3u8`; não há o que colocar na lista.
- `servidor respondeu 504` / `404` → o servidor de vídeo do canal está fora do ar
no momento. Costuma voltar sozinho; nesse caso o canal reaparece na próxima atualização.
- `inconclusivo` → falha de rede ou bloqueio regional durante o teste.

## O que não adianta

- Trocar de player no SS IPTV: o formato é o problema, não o aparelho.
- Usar proxy comum: não muda o formato entregue pelo servidor do canal.

## Se quiser esses canais de qualquer forma

Seria necessário um servidor próprio que receba o stream no formato original e
reentregue em HLS para a sua TV (conversão contínua, 24 h por dia). Isso exige uma
máquina sempre ligada com banda de sobra — não é algo que a lista resolve.

A lista entrega apenas o que foi comprovadamente testado tocando, e é isso que
mantém a experiência boa no SS IPTV.
