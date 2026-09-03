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
  3. Também detecta credenciais DUPLICADAS (mesmo bloco colado 2x) e famílias
     que faltam (bloco não colado).
  4. Gera um PLANO ÚNICO em ./saida_instalador/:
       FIX_remover.txt           -> /admin "Remover credencial" (SEM a caixa)
       FIX_remover_ANULANDO.txt  -> /admin "Remover credencial" + MARCAR
                                    "Anular também o voto já registrado"
       FIX_importar_tudo.tsv     -> /admin "Importar eleitores" (tudo de uma vez)
       FIX_relatorio.txt         -> o que vai acontecer, em texto

Uso:  python jaba_fix.py [--desde 2026-09-01]
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

# Opcional: "python jaba_fix.py --desde 2026-09-01" -> toda credencial de
# familia criada a partir dessa data conta como Jabaquara (sinal 100% confiavel,
# se o CSV tiver a coluna 'criado_em'). Sem isso, cai na heuristica de contato.
DESDE = None
if "--desde" in sys.argv:
    DESDE = sys.argv[sys.argv.index("--desde") + 1].strip()


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
    if path.name != PROD.name:
        sys.exit(
            f"ERRO: '{PROD.name}' não existe — o script ia ler '{path.name}',\n"
            "que é uma cópia ANTIGA (pré-Jabaquara). Faça o passo B2 do roteiro:\n"
            '  Copy-Item "$env:USERPROFILE\\Downloads\\credenciais-emia.csv" `\n'
            f'    "{BASE / PROD.name}" -Force\n'
            "e rode de novo.")
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
            criado_em=(r.get("criado_em") or "").strip(),
        ))
    tem_data = any(p["criado_em"] for p in out)
    print(f"  produção: {len(out)} credenciais lidas de {path.name}"
          + ("  (com coluna criado_em)" if tem_data else "  (SEM criado_em)"))
    if DESDE and not tem_data:
        sys.exit(
            "ERRO: usou --desde mas o CSV não tem a coluna 'criado_em'.\n"
            "Baixe o CSV FRESCO em /admin -> 'Baixar lista completa (CSV)',\n"
            f"copie para '{PROD.name}' e rode de novo.")
    if len(out) < 1200:
        print("  [!] AVISO: só", len(out), "credenciais — esperado ~1700 com a "
              "Jabaquara. O CSV pode estar desatualizado.")
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
        """A credencial da produção é da Jabaquara se:
          - (mais confiável) foi criada em/depois de --desde, se o CSV tem
            'criado_em'. --desde compara o TIMESTAMP INTEIRO (ISO-8601 UTC),
            então dá pra separar por hora: as outras EMIAs entraram em
            2026-09-01T01:16Z e a Jabaquara a partir de 2026-09-01T19:15Z.
            Use  --desde 2026-09-01T12:00:00Z .  OU
          - o contato dela bate com telefone/e-mail da lista da Jabaquara; OU
          - mostra 2+ crianças e TODAS são crianças da lista da Jabaquara.
        Nunca por 1 nome só sem contato — 'Família de Daniel Moreira da Silva'
        existe em várias EMIAs."""
        if DESDE and prow.get("criado_em"):
            ce = prow["criado_em"]
            # ISO-8601 UTC ordena cronologicamente como string. Se --desde
            # veio só como data (sem 'T'), compara só os 10 primeiros chars.
            return (ce >= DESDE) if "T" in DESDE else (ce[:10] >= DESDE)
        c = str(prow["contato"] or "").strip().lower()
        if "@" in c:
            if c in jaba_emails:
                return True
        else:
            d = only_digits(c)
            if any(cand and cand in jaba_phones for cand in (d, d[-10:], d[-11:])):
                return True
        kids = norm_children_from_display(prow["nome"])
        return len(kids) >= 2 and all(k in jaba_children for k in kids)

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

    remove_tokens = []           # tokens sem voto -> remoção normal
    remove_annul = []            # tokens COM voto -> remover anulando o voto
    pieces = []                  # credenciais corretas a (re)importar
    anulacoes = []               # (token, nome) que terão voto anulado
    rep = io.StringIO()
    w = lambda *a: print(*a, file=rep)

    w("=" * 70)
    w("  CORREÇÃO JABAQUARA — plano único (nada é feito online por este script)")
    w("=" * 70)
    w(f"  Credenciais na produção (total) ......... {len(prod)}")
    w(f"  Credenciais de FAMÍLIA na produção ...... {len(prod_fam)}")
    w(f"  Dessas, identificadas como JABAQUARA .... {len(prod_jaba)}")
    w(f"  Credenciais corretas esperadas (Jabaquara) {len(fixed)}")
    w(f"  Merges errados na fonte da Jabaquara .... {len(bad_raw)}")
    w("  (só mexe em credencial reconhecida como Jabaquara — as demais EMIAs")
    w("   NÃO são tocadas, mesmo com nome de família parecido.)")
    w("")

    def spans_2_pieces(pkids, pcs):
        """True se as crianças da credencial da produção cobrem 2+ das peças
        corretas = ela realmente junta famílias distintas. Se cabe dentro de
        UMA peça só, já é uma credencial limpa (ex.: a criada na mão hoje) —
        não é cópia do merge, não mexer nela."""
        hits = 0
        for piece in pcs:
            pk = {norm_name_key(c) for c in piece["children"]}
            if pkids & pk:
                hits += 1
        return hits >= 2

    matched_bad = set()
    for cs, rawfam, pcs in bad_raw:
        cands = [p for p in prod_jaba
                 if p["_kids"] and p["_kids"] <= set(cs)
                 and p["token"] not in matched_bad
                 and spans_2_pieces(p["_kids"], pcs)]
        conf = [p for p in cands
                if only_digits(p["contato"])[-10:] in {ph[-10:] for ph in rawfam["phones"]}]
        cands = conf or cands
        w("-" * 70)
        w(f"  MERGE ERRADO (fonte): {rawfam['display']}")
        for p in pcs:
            w(f"     -> credencial correta: {p['display']}   (contato {p['contato']})")
        if not cands:
            w("     [i] nenhuma credencial correspondente na produção "
              "(não importada, ou já corrigida).")
            continue
        for p in cands:
            matched_bad.add(p["token"])
            if p["ja_votou"]:
                remove_annul.append(p["token"])
                anulacoes.append((p["token"], p["nome"]))
                w(f"     REMOVER ANULANDO O VOTO: {p['token']}  \"{p['nome']}\"")
            else:
                remove_tokens.append(p["token"])
                w(f"     remover (sem voto): {p['token']}  \"{p['nome']}\"")
        pieces.extend(pcs)

    # duplicatas DENTRO da Jabaquara: mesma família em 2+ tokens.
    by_kids = defaultdict(list)
    for p in prod_jaba:
        if p["token"] in matched_bad:
            continue
        by_kids[p["_kids"] or p["nome"]].append(p)
    dups = {k: v for k, v in by_kids.items() if len(v) > 1}
    if dups:
        w("-" * 70)
        w(f"  DUPLICATAS DENTRO DA JABAQUARA (mesma família em 2+ credenciais): {len(dups)}")
        for _key, lst in dups.items():
            # mantém UMA (a que votou, se houver — o voto dela fica valendo)
            votou = [x for x in lst if x["ja_votou"]]
            manter = (votou or lst)[0]
            w(f"    \"{manter['nome']}\"  -> mantém {manter['token']}"
              + ("  (votou)" if manter["ja_votou"] else ""))
            for x in lst:
                if x["token"] == manter["token"]:
                    continue
                if x["ja_votou"]:
                    remove_annul.append(x["token"])
                    anulacoes.append((x["token"], x["nome"] + " (cópia dobrada)"))
                    w(f"        REMOVER ANULANDO O VOTO (voto dobrado): {x['token']}")
                else:
                    remove_tokens.append(x["token"])
                    w(f"        remover (sem voto): {x['token']}")

    remove_tokens = dedup(remove_tokens)
    remove_annul = dedup(remove_annul)
    removidos = set(remove_tokens) | set(remove_annul) | matched_bad

    # --------------------------------------------------------------------
    # Índice das crianças que JÁ estão na produção numa credencial LIMPA
    # (não é merge errado nem vai ser removida). Serve p/ não reimportar
    # família que já tem credencial boa (ex.: as criadas na mão hoje).
    # --------------------------------------------------------------------
    clean_child_index = set()
    clean_phone_index = set()
    for p in prod_fam:
        if p["token"] in removidos:
            continue
        for k in norm_children_from_display(p["nome"]):
            clean_child_index.add(k)
        dd = only_digits(p["contato"])
        for cand in (dd, dd[-10:], dd[-11:]):
            if cand:
                clean_phone_index.add(cand)

    def ja_tem_credencial_limpa(nf):
        kids = {norm_name_key(c) for c in nf["children"] if norm_name_key(c)}
        if kids & clean_child_index:
            return True
        for ph in nf["phones"]:
            for v in phone_variants(ph):
                if v in clean_phone_index:
                    return True
        return False

    # peças dos merges: só reimporta as que ainda não têm credencial limpa
    importar = []
    vistos = set()
    for nf in pieces:
        key = frozenset(norm_name_key(c) for c in nf["children"])
        if key in vistos or ja_tem_credencial_limpa(nf):
            continue
        vistos.add(key)
        importar.append(nf)

    # famílias inteiras que não existem em lugar nenhum (bloco não colado)
    faltando = []
    for nf in fixed:
        key = frozenset(norm_name_key(c) for c in nf["children"])
        if key in vistos or ja_tem_credencial_limpa(nf):
            continue
        vistos.add(key)
        faltando.append(nf)

    todas_linhas = [tsv_line(nf) for nf in importar] + [tsv_line(nf) for nf in faltando]
    todas_linhas = dedup(todas_linhas)

    (OUT / "FIX_remover.txt").write_text(
        "\n".join(remove_tokens) + ("\n" if remove_tokens else ""), encoding="utf-8")
    (OUT / "FIX_remover_ANULANDO.txt").write_text(
        "\n".join(remove_annul) + ("\n" if remove_annul else ""), encoding="utf-8")
    (OUT / "FIX_importar_tudo.tsv").write_text(
        "\n".join(todas_linhas) + ("\n" if todas_linhas else ""), encoding="utf-8")

    if faltando:
        w("-" * 70)
        w(f"  FAMÍLIAS SEM CREDENCIAL EM LUGAR NENHUM (bloco não colado): {len(faltando)}")
        for nf in faltando[:50]:
            w(f"     - {nf['display']}   (contato {nf['contato']})")
        if len(faltando) > 50:
            w(f"     ... e mais {len(faltando) - 50}")
    if anulacoes:
        w("-" * 70)
        w(f"  VOTOS QUE SERÃO ANULADOS: {len(anulacoes)}  (a Comissão registra em ata")
        w("  e avisa cada família para votar de novo com o link novo):")
        for tok, nome in anulacoes:
            w(f"     - {tok}  {nome}")

    w("")
    w("=" * 70)
    w(f"  RESULTADO:")
    w(f"    Remover SEM voto ................ {len(remove_tokens)}  -> FIX_remover.txt")
    w(f"    Remover ANULANDO o voto ........ {len(remove_annul)}  -> FIX_remover_ANULANDO.txt")
    w(f"    Credenciais limpas a importar .. {len(todas_linhas)}  -> FIX_importar_tudo.tsv")
    w(f"       (merges desfeitos: {len(importar)}  |  famílias que faltavam: {len(faltando)})")
    if not DESDE:
        w("  Dica: rode com  --desde 2026-09-01  (o CSV tem 'criado_em') p/ 100%% de precisão.")
    w("")
    w("  PASSOS NO /admin (nesta ordem):")
    w("   1. 'Remover credencial': cole FIX_remover.txt  (SEM marcar a caixa).")
    w("   2. 'Remover credencial': cole FIX_remover_ANULANDO.txt  e MARQUE a caixa")
    w("      'Anular também o voto já registrado'.")
    w("   3. 'Importar eleitores': cole FIX_importar_tudo.tsv .")
    w("   4. Baixe o CSV de novo, rode este script de novo -> tem que dar 0/0/0.")
    w("   5. Ata: registre os votos anulados. Avise TODAS as famílias afetadas")
    w("      (merge + duplicata) para (re)votar com o link novo até 08/09 12h.")
    (OUT / "FIX_relatorio.txt").write_text(rep.getvalue(), encoding="utf-8-sig")
    sys.stdout.write(rep.getvalue())


if __name__ == "__main__":
    main()
