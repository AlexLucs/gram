# GRAM / USDT: histórico diário (Binance Spot)

Gráfico interativo de candles diários do **GRAM** (antigo **TON**), com dados da Binance Spot desde 08/08/2024. Um GitHub Actions atualiza os dados todos os dias.

- **Online:** `https://alexlucs.github.io/gram/` (depois de ativar o GitHub Pages)
- **Offline:** baixe `gram_offline.html`. É um arquivo único, com os dados embutidos, que abre direto no navegador sem internet.

## Arquivos

| Arquivo | Para que serve |
|---|---|
| `index.html` | Página do gráfico. Lê os dados de `dados/gram_1d.js` |
| `dados/gram_1d.csv` | Histórico completo no formato kline da Binance. É a fonte da verdade; timestamps em **ms UTC** |
| `dados/gram_1d.js` | Gerado a partir do CSV, para a página funcionar também via `file://` |
| `gram_offline.html` | Gerado: `index.html` com os dados embutidos |
| `atualizar_gram.py` | Baixa os candles que faltam e regenera os arquivos acima |
| `.github/workflows/atualizar.yml` | Roda o script todo dia às 01:20 UTC e faz commit se houver dado novo. Também roda quando `index.html` ou o script mudam, para regenerar a versão offline |
| `.github/dependabot.yml` | Abre um PR mensal quando sair versão nova de alguma action (ex.: `actions/checkout`) |

## De onde vêm os dados

1. **Arquivos diários oficiais:** `data.binance.vision/data/spot/daily/klines/GRAMUSDT/1d/`. O script confere o SHA-256 de cada zip.
2. **Reserva:** `data-api.binance.vision/api/v3/klines`, usado quando o zip do dia ainda não foi publicado (a Binance publica com cerca de 1 dia de atraso). Só entram candles já fechados.

O `api.binance.com` não é usado porque bloqueia IPs dos EUA (HTTP 451), que é onde rodam os servidores do GitHub Actions.

### Observações sobre o histórico
- **Até 30/06/2026** o par era `TONUSDT`; **desde 02/07/2026** é `GRAMUSDT`, depois do rebranding Toncoin → Gram com conversão 1:1. Em **01/07/2026** não houve negociação, e esse dia fica como lacuna conhecida (marcada no gráfico).
- Desde 01/01/2025 a Binance publica timestamps spot em **microssegundos**. O script converte tudo para milissegundos.

## Uso local (Windows)

```powershell
python atualizar_gram.py              # baixa o que falta
python atualizar_gram.py --offline    # idem + gera gram_offline.html
python atualizar_gram.py --sem-rede   # só normaliza o CSV e regenera os arquivos
```

Só usa a biblioteca padrão do Python (3.9+). No GitHub roda com o Python 3.12 da imagem `ubuntu-24.04`, sem `setup-python`.

O robô faz um commit por dia, então rode `git pull` antes de editar localmente. Depois de enviar uma alteração em `index.html`, o workflow regenera o `gram_offline.html` sozinho.

## Configuração no GitHub (uma vez)

1. Envie todos os arquivos, incluindo a pasta `.github`, para `AlexLucs/gram`.
2. **Settings → Actions → General → Workflow permissions:** marque *Read and write permissions*.
3. **Settings → Pages:** em *Source*, escolha *Deploy from a branch*, branch `main`, pasta `/ (root)`.
4. **Actions → Atualizar dados GRAM → Run workflow** para a primeira execução, que vai buscar os dados desde 01/11/2026.

Se uma execução falhar (checksum divergente, OHLC inconsistente, rede), o script para **sem gravar nada** e o GitHub envia um e-mail de falha. A execução do dia seguinte tenta de novo a partir do último dia salvo.

## Atalhos do gráfico

Roda do mouse ou pinça: zoom · Arrastar: deslocar · Clique: fixar crosshair · ←/→: navegar candle a candle (Shift: 10 candles) · Home/End: primeiro/último · +/−: zoom · Esc: liberar · Duplo clique: ver tudo.

As preferências (tipo de gráfico, escala, médias, período) ficam salvas no navegador.
