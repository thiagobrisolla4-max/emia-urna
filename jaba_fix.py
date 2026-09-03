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
from instalador import group_families, norm_name_key, dedup, phone_variants

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

    # ------------------------------------------------------------------
    # Assinaturas da Jabaquara para reconhecer, na produção, o que É da
    # Jabaquara (e NÃO mexer em credenciais de Perus/Flores/Chácara/etc.
    # que por acaso tenham o mesmo "Família de <nome>").
    # ------------------------------------------------------------------
    jaba_children = set()
    jaba_phones = set()
    jaba_emails = set()
    for r in rows:
        for c in r["children"]:
            k = norm_name_key(c)
            if k:
                jaba_children.add(k)
        for ph in r["phones"]:
            for v in phone_variants(ph):
                jaba_phones.add(v)
        for e in r["emails"]:
            if e:
                jaba_emails.add(e.strip().lower())

    def only_digits(s):
        return "".join(ch for ch in str(s or "") if ch.isdigit())

    def is_jaba(prow):
        """Uma credencial da produção é da Jabaquara SÓ se o contato dela bate
        com um telefone OU e-mail da lista da Jabaquara. NÃO usamos só o nome:
        'Família de Daniel Moreira da Silva' pode existir em várias EMIAs.
        Assim nenhuma credencial de Perus/Flores/Chácara/Brasilândia é tocada."""
        c = str(prow["contato"] or "").strip().lower()
        if "@" in c:
            return c in jaba_emails
        d = only_digits(c)
        return any(cand and cand in jaba_phones for cand in (d, d[-10:], d[-11:]))

    # agrupamento CRU (o que alimentou todas as gerações de blocos)
    raw = group_families(rows)
    # versão CORRETA (com desmembramento + junção de irmãos)
    fixed, _desmembr = J.split_unrelated_families(raw, list(rows))
    fixed, _merges = J.merge_by_surname(fixed)

    def pieces_for(rawfam):
        cs = set(norm_name_key(c) for c in rawfam["children"])
        return [nf for nf in fixed
                if cs & set(norm_name_key(c) for c in nf["children"])]

    # famílias cruas que quebraram em 2+ credenciais corretas = MERGE ERRADO
    bad_raw = []
    for f in raw:
        cs = frozenset(norm_name_key(c) for c in f["children"] if norm_name_key(c))
        pcs = pieces_for(f)
        distinct = {frozenset(norm_name_key(c) for c in p["children"]) for p in pcs}
        if len(distinct) > 1:
            bad_raw.append((cs, f, pcs))

    prod = load_prod()
    prod_fam = [p for p in prod if p["segmento"].startswith("fam")]
    prod_jaba = [p for p in prod_fam if is_jaba(p)]
    for p in prod_jaba:
        p["_kids"] = frozenset(norm_children_from_display(p["nome"]))

    remove_tokens = []
    reimport = []
    voted_blocked = []
    rep = io.StringIO()
    w = lambda *a: print(*a, file=rep)

    w("=" * 70)
    w("  CORREÇÃO JABAQUARA — plano proposto (nada é feito online por este script)")
    w("=" * 70)
    w(f"  Credenciais na produção (total) ......... {len(prod)}")
    w(f"  Credenciais de FAMÍLIA na produção ...... {len(prod_fam)}")
    w(f"  Dessas, identificadas como JABAQUARA .... {len(prod_jaba)}")
    w(f"  Credenciais corretas esperadas (Jabaquara) {len(fixed)}")
    w(f"  Merges errados na fonte da Jabaquara .... {len(bad_raw)}")
    w("  (só mexe em credencial reconhecida como Jabaquara — as demais EMIAs")
    w("   NÃO são tocadas, mesmo com nome de família parecido.)")
    w("")

    matched_bad = set()  # tokens já contabilizados como merge errado
    for cs, rawfam, pcs in bad_raw:
        # TODAS as credenciais Jabaquara cujas crianças visíveis são subконъjunto
        # deste merge (pega as cópias duplicadas também).
        cands = [p for p in prod_jaba
                 if p["_kids"] and p["_kids"] <= set(cs) and p["token"] not in matched_bad]
        # confirma pelo contato quando possível
        conf = [p for p in cands
                if only_digits(p["contato"])[-10:] in {ph[-10:] for ph in rawfam["phones"]}]
        cands = conf or cands
        w("-" * 70)
        w(f"  MERGE ERRADO (fonte): {rawfam['display']}")
        for p in pcs:
            w(f"     -> credencial correta: {p['display']}   (contato {p['contato']})")
        if not cands:
            w("     [i] nenhuma credencial correspondente na produção — provável que")
            w("         essa combinação não tenha sido importada, ou já foi corrigida.")
            continue
        pecas_reimportadas = False
        for p in cands:
            matched_bad.add(p["token"])
            if p["ja_votou"]:
                voted_blocked.append((p, rawfam, pcs))
                w(f"     [!!] token {p['token']}  \"{p['nome']}\"  —  JÁ VOTOU: NÃO remover.")
            else:
                remove_tokens.append(p["token"])
                w(f"     remover token {p['token']}  \"{p['nome']}\"")
                pecas_reimportadas = True
        if pecas_reimportadas:
            for p in pcs:
                reimport.append(tsv_line(p))

    # duplicatas DENTRO da Jabaquara: mesmo conjunto de crianças (ou mesmo
    # nome exato) aparecendo em 2+ tokens, fora os merges já tratados acima.
    by_kids = defaultdict(list)
    for p in prod_jaba:
        if p["token"] in matched_bad:
            continue
        key = p["_kids"] or p["nome"]
        by_kids[key].append(p)
    dups = {k: v for k, v in by_kids.items() if len(v) > 1}
    if dups:
        w("-" * 70)
        w(f"  DUPLICATAS DENTRO DA JABAQUARA (mesma família em 2+ credenciais): {len(dups)}")
        for _key, lst in dups.items():
            votou = [x for x in lst if x["ja_votou"]]
            manter = (votou or lst)[0]
            w(f"    \"{manter['nome']}\"  -> mantém {manter['token']}"
              + ("  (votou)" if manter["ja_votou"] else ""))
            for x in lst:
                if x["token"] == manter["token"]:
                    continue
                if x["ja_votou"]:
                    voted_blocked.append((x, None, None))
                    w(f"        [!!] {x['token']} também votou — resolver na mão")
                else:
                    remove_tokens.append(x["token"])
                    w(f"        remover {x['token']}")

    remove_tokens = dedup(remove_tokens)
    reimport = dedup(reimport)

    # arquivo separado, detalhado, para os casos que já votaram
    vb = io.StringIO()
    vb.write("CASOS QUE JÁ VOTARAM — resolver na mão (não dá p/ remover sem "
             "perder o voto)\n" + "=" * 70 + "\n\n")
    for p, rawfam, pcs in voted_blocked:
        vb.write(f"Credencial: \"{p['nome']}\"  (token {p['token']}, contato {p['contato']})\n")
        if pcs:
            vb.write("  Essa credencial juntava estas famílias distintas:\n")
            for x in pcs:
                vb.write(f"    - {x['display']}   (contato {x['contato']})\n")
            vb.write("  O voto já lançado conta UMA vez para esse conjunto. Para cada\n")
            vb.write("  família do conjunto que NÃO tenha sido quem votou, importe a\n")
            vb.write("  linha correta abaixo (ela ganha token novo) e registre ocorrência:\n")
            for x in pcs:
                vb.write("    " + tsv_line(x) + "\n")
        else:
            vb.write("  (duplicata que também votou — verificar qual voto vale em ata)\n")
        vb.write("\n")
    (OUT / "FIX_votaram_resolver.txt").write_text(vb.getvalue(), encoding="utf-8-sig")
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
    w("  ARQUIVOS GERADOS (saida_instalador/):")
    w("   FIX_tokens_para_remover.txt  -> /admin > 'Remover credencial'")
    w("   FIX_reimportar.tsv           -> /admin > 'Importar eleitores'")
    w("   FIX_votaram_resolver.txt     -> casos que já votaram (ler e tratar em ata)")
    w("")
    w("  PASSOS:")
    w("   1. Confira ESTE relatório inteiro. Nenhuma credencial de outra EMIA")
    w("      aparece aqui — só Jabaquara.")
    w("   2. /admin > 'Remover credencial': cole FIX_tokens_para_remover.txt")
    w("   3. /admin > 'Importar eleitores': cole FIX_reimportar.tsv")
    w("   4. Baixe o CSV de novo e rode este script mais uma vez: deve dar")
    w("      0 merges e 0 duplicatas. (idempotente)")
    w("   5. Trate FIX_votaram_resolver.txt em ata.")
    w("   6. Teste /acesso com nomes/telefones das famílias afetadas.")
    (OUT / "FIX_relatorio.txt").write_text(rep.getvalue(), encoding="utf-8-sig")
    sys.stdout.write(rep.getvalue())


if __name__ == "__main__":
    main()
