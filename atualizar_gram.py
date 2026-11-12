#!/usr/bin/env python3
"""
atualizar_gram.py — Atualiza o histórico diário GRAM/USDT (Binance Spot).

Fonte principal : arquivos diários oficiais em data.binance.vision (zip + SHA-256)
Fonte reserva   : data-api.binance.vision/api/v3/klines (só candles já fechados)

Gera/atualiza:
  dados/gram_1d.csv   histórico completo (fonte da verdade, timestamps em ms)
  dados/gram_1d.js    dados para o index.html (window.GRAM_DATA)
  gram_offline.html   arquivo único com os dados embutidos (com --offline)

Uso:
  python atualizar_gram.py             baixa o que falta e regrava os arquivos
  python atualizar_gram.py --offline   idem + gera gram_offline.html
  python atualizar_gram.py --sem-rede  só normaliza o CSV e regenera os arquivos
  python atualizar_gram.py --forcar    regrava mesmo sem dados novos

Só usa a biblioteca padrão do Python (3.9+).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
CSV_PATH = RAIZ / "dados" / "gram_1d.csv"
JS_PATH = RAIZ / "dados" / "gram_1d.js"
HTML_PATH = RAIZ / "index.html"
OFFLINE_PATH = RAIZ / "gram_offline.html"

SIMBOLO = "GRAMUSDT"
# Variáveis de ambiente permitem apontar para um servidor de teste.
URL_DIARIO = os.environ.get(
    "GRAM_URL_DIARIO",
    "https://data.binance.vision/data/spot/daily/klines/{s}/1d/{s}-1d-{d}.zip",
)
URL_API = os.environ.get(
    "GRAM_URL_API",
    "https://data-api.binance.vision/api/v3/klines?symbol={s}&interval=1d&startTime={ini}&limit=1000",
)

CABECALHO = ["OpenTime", "Open", "High", "Low", "Close", "Volume", "CloseTime",
             "QuoteVolume", "Trades", "TakerBuyBase", "TakerBuyQuote", "Ignore"]

# Dias sem negociação já conhecidos (transição TONUSDT -> GRAMUSDT).
LACUNAS_CONHECIDAS = {"2026-07-01"}

DIA_MS = 86_400_000
UA = "gram-historico/1.0 (+https://github.com/AlexLucs/gram)"


class ErroDados(Exception):
    """Dados inconsistentes: o script para sem gravar nada."""


# ───────────────────────── utilidades ─────────────────────────

def para_ms(valor: str | int) -> int:
    """Converte timestamp Binance para ms. Desde 2025-01-01 os arquivos spot usam µs."""
    v = int(valor)
    if v >= 10**17:      # nanossegundos (prevenção)
        return v // 1_000_000
    if v >= 10**14:      # microssegundos
        return v // 1000
    return v


def dia_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def ms_do_dia(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() * 1000)


def normalizar_linha(campos: list) -> list[str]:
    """Garante 12 colunas em texto, com OpenTime/CloseTime em ms."""
    campos = [str(x).strip() for x in campos]
    if len(campos) < 11:
        raise ErroDados(f"linha com colunas insuficientes: {campos}")
    if len(campos) == 11:
        campos.append("0")
    campos = campos[:12]
    campos[0] = str(para_ms(campos[0]))
    campos[6] = str(para_ms(campos[6]))
    return campos


def baixar(url: str, tentativas: int = 3) -> bytes | None:
    """Retorna o conteúdo, ou None se 404 (arquivo ainda não publicado)."""
    erro = None
    for n in range(tentativas):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            erro = e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            erro = e
        time.sleep(2 * (n + 1))
    raise ConnectionError(f"falha ao baixar {url}: {erro}")


# ───────────────────────── leitura/escrita ─────────────────────────

def ler_csv() -> dict[int, list[str]]:
    dados: dict[int, list[str]] = {}
    if not CSV_PATH.exists():
        return dados
    with CSV_PATH.open(newline="", encoding="utf-8") as f:
        for campos in csv.reader(f):
            if not campos or not campos[0].strip().isdigit():
                continue  # cabeçalho ou linha vazia
            linha = normalizar_linha(campos)
            dados[int(linha[0])] = linha
    return dados


def texto_csv(dados: dict[int, list[str]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(CABECALHO)
    for t in sorted(dados):
        w.writerow(dados[t])
    return buf.getvalue()


def num(s: str) -> str:
    """Número compacto para o JS (sem zeros à direita)."""
    x = float(s)
    return str(int(x)) if x == int(x) else repr(x)


def texto_js(dados: dict[int, list[str]]) -> str:
    ts = sorted(dados)
    linhas = []
    for t in ts:
        r = dados[t]
        # [t, o, h, l, c, volume GRAM, volume USDT, negócios]
        linhas.append(f"[{t},{num(r[1])},{num(r[2])},{num(r[3])},{num(r[4])},"
                      f"{num(r[5])},{num(r[7])},{int(r[8])}]")
    meta = {
        "simbolo": SIMBOLO,
        "primeiro": dia_iso(ts[0]),
        "ultimo": dia_iso(ts[-1]),
        "candles": len(ts),
    }
    return ("// Gerado por atualizar_gram.py — não editar à mão.\n"
            "// Colunas: [openTime(ms UTC), open, high, low, close, volume GRAM, volume USDT, negócios]\n"
            f"window.GRAM_META={json.dumps(meta, ensure_ascii=False)};\n"
            "window.GRAM_DATA=[\n" + ",\n".join(linhas) + "\n];\n")


def gerar_offline(js: str) -> str | None:
    """Conteúdo do gram_offline.html: index.html com os dados embutidos."""
    if not HTML_PATH.exists():
        print("! index.html não encontrado; gram_offline.html não gerado.")
        return None
    html = HTML_PATH.read_text(encoding="utf-8")
    padrao = re.compile(r'<script src="dados/gram_1d\.js"[^>]*></script>')
    if not padrao.search(html):
        raise ErroDados('index.html sem a tag <script src="dados/gram_1d.js" ...>')
    js_seguro = js.replace("</", "<\\/")
    bloco = "<script>\nwindow.GRAM_EMBUTIDO=true;\n" + js_seguro + "</script>"
    return padrao.sub(lambda _: bloco, html, count=1)


# ───────────────────────── fontes de dados ─────────────────────────

def linhas_do_zip(conteudo: bytes) -> list[list[str]]:
    with zipfile.ZipFile(io.BytesIO(conteudo)) as z:
        nomes = [n for n in z.namelist() if n.endswith(".csv")]
        if not nomes:
            raise ErroDados("zip sem CSV")
        texto = z.read(nomes[0]).decode("utf-8")
    saida = []
    for campos in csv.reader(io.StringIO(texto)):
        if campos and campos[0].strip().isdigit():
            saida.append(normalizar_linha(campos))
    return saida


def candle_diario(d: date) -> list[list[str]] | None:
    """Baixa o zip oficial do dia e confere o SHA-256. None = ainda não publicado."""
    url = URL_DIARIO.format(s=SIMBOLO, d=d.isoformat())
    conteudo = baixar(url)
    if conteudo is None:
        return None
    soma = baixar(url + ".CHECKSUM")
    if soma is None:
        print(f"  {d}: zip publicado mas CHECKSUM ainda não — tentando depois")
        return None
    esperado = soma.decode("utf-8").split()[0].lower()
    obtido = hashlib.sha256(conteudo).hexdigest()
    if esperado != obtido:
        raise ErroDados(f"{d}: SHA-256 não confere (esperado {esperado}, obtido {obtido})")
    return linhas_do_zip(conteudo)


def candles_api(inicio_ms: int) -> list[list[str]]:
    """Candles fechados desde inicio_ms pelo endpoint público de dados de mercado."""
    agora = int(time.time() * 1000)
    saida: list[list[str]] = []
    ini = inicio_ms
    while True:
        bruto = baixar(URL_API.format(s=SIMBOLO, ini=ini))
        if bruto is None:
            break
        lote = json.loads(bruto)
        if not isinstance(lote, list) or not lote:
            break
        for k in lote:
            linha = normalizar_linha(k[:12])
            if int(linha[6]) < agora:          # só candle já fechado
                saida.append(linha)
        if len(lote) < 1000:
            break
        ini = para_ms(lote[-1][0]) + DIA_MS
    return saida


# ───────────────────────── validação ─────────────────────────

def validar(dados: dict[int, list[str]]) -> list[str]:
    avisos = []
    ts = sorted(dados)
    for t in ts:
        r = dados[t]
        if t % DIA_MS:
            raise ErroDados(f"{t}: OpenTime fora da meia-noite UTC")
        o, h, l, c = (float(x) for x in r[1:5])
        if min(o, h, l, c) <= 0 or l > min(o, c) or h < max(o, c):
            raise ErroDados(f"{dia_iso(t)}: OHLC inconsistente {r[1:5]}")
    for a, b in zip(ts, ts[1:]):
        dia = a + DIA_MS
        while dia < b:
            iso = dia_iso(dia)
            if iso not in LACUNAS_CONHECIDAS:
                avisos.append(f"lacuna sem negociação em {iso}")
            dia += DIA_MS
    return avisos


# ───────────────────────── principal ─────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--offline", action="store_true", help="gera também gram_offline.html")
    ap.add_argument("--sem-rede", action="store_true", help="não baixa nada; só normaliza e regenera")
    ap.add_argument("--forcar", action="store_true", help="regrava mesmo sem dados novos")
    args = ap.parse_args()

    dados = ler_csv()
    if not dados:
        print("✗ dados/gram_1d.csv vazio ou ausente", file=sys.stderr)
        return 1
    ultimo = max(dados)
    print(f"Histórico: {len(dados)} candles, último {dia_iso(ultimo)}")

    novos = 0
    if not args.sem_rede:
        ontem = datetime.now(timezone.utc).date() - timedelta(days=1)
        d = datetime.fromtimestamp(ultimo / 1000, tz=timezone.utc).date() + timedelta(days=1)

        # 1) arquivos diários oficiais
        while d <= ontem:
            linhas = candle_diario(d)
            if linhas is None:
                print(f"  {d}: arquivo diário ainda não publicado")
                break
            for ln in linhas:
                if int(ln[0]) not in dados:
                    novos += 1
                dados[int(ln[0])] = ln
            print(f"  {d}: ok (arquivo diário)")
            d += timedelta(days=1)

        # 2) API pública para o que ainda falta
        if d <= ontem:
            print(f"  completando pela API a partir de {d}")
            for ln in candles_api(ms_do_dia(d)):
                if int(ln[0]) not in dados:
                    novos += 1
                    print(f"  {dia_iso(int(ln[0]))}: ok (API)")
                    dados[int(ln[0])] = ln

    for aviso in validar(dados):
        print("! " + aviso)

    # Saídas determinísticas: só regrava o arquivo cujo conteúdo mudou,
    # para o workflow não gerar commits vazios.
    js = texto_js(dados)
    alvos = [(CSV_PATH, texto_csv(dados)), (JS_PATH, js)]
    if args.offline:
        off = gerar_offline(js)
        if off is not None:
            alvos.append((OFFLINE_PATH, off))
    gravados = []
    for caminho, conteudo in alvos:
        atual = caminho.read_text(encoding="utf-8") if caminho.exists() else None
        if args.forcar or atual != conteudo:
            with open(caminho, "w", encoding="utf-8", newline="\n") as f:  # LF também no Windows
                f.write(conteudo)
            gravados.append(caminho.relative_to(RAIZ).as_posix())
    print(f"{len(dados)} candles até {dia_iso(max(dados))} · {novos} novo(s)")
    print("Gravado: " + ", ".join(gravados) if gravados else "Sem novidades — nada gravado.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ErroDados, ConnectionError) as e:
        print(f"✗ {e}", file=sys.stderr)
        sys.exit(1)
