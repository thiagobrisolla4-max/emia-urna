#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CORREÇÃO PÓS-IMPORTAÇÃO — EMIA Jabaquara.

Contexto: os blocos da Jabaquara já foram colados no /admin com a versão
ANTIGA (antes da correção de merge). Isso deixou na produção ~24 credenciais
que juntavam FAMÍLIAS DIFERENTES por um telefone/e-mail compartilhado
(erro da planilha da secretaria). Este script:

  1. Lê o CSV de credenciais BAIXADO da produção (/admin -> "Baixar lista
     completa"). Salve como  credenciais-producao.csv  nesta pasta.
  2. Reconstrói o agrupamento da Jabaquara (mesmo código do jabaquara.py) e
     descobre quais credenciais da produção são "merges errados".
  3. Também detecta credenciais DUPLICADAS (mesmo bloco colado 2x).
  4. Gera, em ./saida_instalador/:
       FIX_tokens_para_remover.txt  -> colar em /admin "Remover credencial"
       FIX_reimportar.tsv           -> colar em /admin "Importar eleitores"
       FIX_relatorio.txt            -> o que vai acontecer, em texto
     Credenciais erradas que JÁ VOTARAM não entram na remoção — ficam
     listadas no relatório para a Comissão tratar na mão.

Uso:  python jaba_fix.py
"""

import csv
import io
import sys
from collections import defaultdict
from pathlib import Path

import jabaquara as J
from instalador import group_families, norm_name_key, dedup

BASE = Path(__file__).resolve().parent
OUT = BASE / "saida_instalador"
PROD = BASE / "credenciais-producao.csv"
PROD_ALT = BASE / "credenciais-emia.csv"


def norm_children_from_display(display):
    """'Família de A • B • C (+2)' -> ['a ...','b ...','c ...'] normalizados."""
    s = display.strip()
    for pref in ("Família de ", "Familia de "):
        if s.startswith(pref):
            s = s[len(pref):]
    s = s.split(" (+")[0]
    parts = [p.strip() for p in s.split("•") if p.strip()]
    return [norm_name_key(p) for p in parts if norm_name_key(p)]


def load_prod():
    path = PROD if PROD.exists() else PROD_ALT
    if not path.exists():
        sys.exit("ERRO: baixe o CSV de credenciais do /admin e salve como "
                 f"{PROD.name} nesta pasta.")
    text = path.read_text(encoding="utf-8-sig")
    rows = list(csv.DictReader(text.splitlines()))
    out = []
    for r in rows:
        link = (r.get("link") or "").rstrip("/")
        token = link.rsplit("/", 1)[-1] if "/" in link else (r.get("token") or "").strip()
        if not token:
            continue
        out.append(dict(
            token=token,
            nome=(r.get("nome") or "").strip(),
            segmento=(r.get("segmento") or "").strip().lower(),
            contato=(r.get("contato") or "").strip(),
            ja_votou=(r.get("ja_votou") or "").strip().lower() in ("sim", "s", "true", "1"),
        ))
    print(f"  produção: {len(out)} credenciais lidas de {path.name}")
    return out


def tsv_line(fam):
    keys = dedup(fam["children"] + fam["responsibles"] + fam["phones"] + fam["emails"])
    kj = ";".join(k.replace(";", " ").replace("\t", " ").strip() for k in keys if k.strip())
    return "\t".join([fam["display"], "familia", fam["contato"], kj])


def main():
    OUT.mkdir(exist_ok=True)
    rows, _ = J.load_rows()

    # crianças da Jabaquara (para reconhecer credenciais da Jabaquara na produção)
    jaba_children = set()
    for r in rows:
        for c in r["children"]:
            k = norm_name_key(c)
            if k:
                jaba_children.add(k)

    # agrupamento CRU (o que alimentou todas as gerações de blocos)
    raw = group_families(rows)
    # versão CORRETA (com desmembramento + junção de irmãos)
    fixed, desmembr = J.split_unrelated_families(raw, list(rows))
    fixed, _merges = J.merge_by_surname(fixed)

    # índice: conjunto de crianças (normalizado) -> família crua
    raw_by_childset = []
    for f in raw:
        cs = frozenset(norm_name_key(c) for c in f["children"] if norm_name_key(c))
        raw_by_childset.append((cs, f))

    # famílias cruas que FORAM desmembradas: mapeia p/ as peças corretas
    def pieces_for(rawfam):
        cs = set(norm_name_key(c) for c in rawfam["children"])
        got = [nf for nf in fixed
               if cs & set(norm_name_key(c) for c in nf["children"])]
        return got

    # quais famílias cruas realmente quebraram (>1 peça correta correspondente)
    bad_raw = []
    for cs, f in raw_by_childset:
        pcs = pieces_for(f)
        distinct = {frozenset(norm_name_key(c) for c in p["children"]) for p in pcs}
        if len(distinct) > 1:
            bad_raw.append((cs, f, pcs))

    prod = load_prod()
    prod_fam = [p for p in prod if p["segmento"].startswith("fam")]

    # match: para cada família crua ruim, achar a(s) credencial(is) na produção
    remove_tokens = []
    reimport = []
    voted_blocked = []
    rep = io.StringIO()
    w = lambda *a: print(*a, file=rep)

    w("=" * 70)
    w("  CORREÇÃO JABAQUARA — o que este script propõe")
    w("=" * 70)
    w(f"  Credenciais na produção .............. {len(prod)}")
    w(f"  Merges errados detectados (fonte) ... {len(bad_raw)}")
    w("")

    used_tokens = set()
    for cs, rawfam, pcs in bad_raw:
        # candidata: credencial da produção cujas crianças visíveis mais batem
        best, best_score = None, 0
        for p in prod_fam:
            if p["token"] in used_tokens:
                continue
            pc = set(norm_children_from_display(p["nome"]))
            if not pc:
                continue
            score = len(pc & cs)
            # bônus se o contato bate
            if p["contato"] and rawfam.get("phones") and \
               "".join(ch for ch in p["contato"] if ch.isdigit())[-10:] in \
               {ph[-10:] for ph in rawfam["phones"]}:
                score += 1
            if score > best_score:
                best, best_score = p, score
        w("-" * 70)
        w(f"  MERGE ERRADO: {rawfam['display']}")
        for p in pcs:
            w(f"     vira -> {p['display']}   (contato {p['contato']})")
        if not best or best_score == 0:
            w("     [!] NÃO achei essa credencial na produção — pode já ter sido")
            w("         corrigida, ou o CSV está desatualizado. Pulei.")
            continue
        used_tokens.add(best["token"])
        w(f"     credencial na produção: token {best['token']}  \"{best['nome']}\"")
        if best["ja_votou"]:
            voted_blocked.append((best, rawfam, pcs))
            w("     [!!] ESSA CREDENCIAL JÁ VOTOU — não será removida.")
            w("          A Comissão precisa decidir na mão (registrar ocorrência;")
            w("          emitir credencial nova só para a(s) família(s) prejudicada(s)).")
            continue
        remove_tokens.append(best["token"])
        for p in pcs:
            reimport.append(tsv_line(p))

    # duplicatas exatas na produção (mesmo bloco colado 2x)
    by_disp = defaultdict(list)
    for p in prod_fam:
        by_disp[p["nome"]].append(p)
    dups = {k: v for k, v in by_disp.items() if len(v) > 1}
    if dups:
        w("-" * 70)
        w(f"  CREDENCIAIS DUPLICADAS (mesmo nome 2+ vezes): {len(dups)}")
        for nome, lst in dups.items():
            manteve = next((x for x in lst if x["ja_votou"]), lst[0])
            w(f"    \"{nome}\"  -> mantém {manteve['token']}"
              + ("(votou)" if manteve["ja_votou"] else ""))
            for x in lst:
                if x["token"] != manteve["token"]:
                    if x["ja_votou"]:
                        w(f"        [!!] {x['token']} também votou — resolver na mão")
                        voted_blocked.append((x, None, None))
                    else:
                        remove_tokens.append(x["token"])
                        w(f"        remove {x['token']}")

    remove_tokens = dedup(remove_tokens)
    (OUT / "FIX_tokens_para_remover.txt").write_text(
        "\n".join(remove_tokens) + ("\n" if remove_tokens else ""), encoding="utf-8")
    (OUT / "FIX_reimportar.tsv").write_text(
        "\n".join(reimport) + ("\n" if reimport else ""), encoding="utf-8")

    w("")
    w("=" * 70)
    w(f"  RESULTADO: remover {len(remove_tokens)} credencial(is), "
      f"reimportar {len(reimport)} corretas.")
    w(f"  Bloqueadas por já terem votado: {len(voted_blocked)} "
      f"(ver acima; tratar na mão).")
    w("")
    w("  PASSOS:")
    w("   1. /admin -> 'Remover credencial': cole FIX_tokens_para_remover.txt")
    w("   2. /admin -> 'Importar eleitores': cole FIX_reimportar.tsv")
    w("   3. Teste /acesso com os nomes/telefones das famílias afetadas.")
    w("   4. Para as 'bloqueadas por já terem votado': registrar ocorrência e,")
    w("      se for o caso, importar manualmente só a credencial da família que")
    w("      ficou sem voto (ela recebe um token novo).")
    (OUT / "FIX_relatorio.txt").write_text(rep.getvalue(), encoding="utf-8-sig")
    sys.stdout.write(rep.getvalue())


if __name__ == "__main__":
    main()
