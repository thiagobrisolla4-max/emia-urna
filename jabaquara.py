#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Processa SÓ a lista de famílias da EMIA Jabaquara e gera arquivos prontos
para colar no painel /admin em BLOCOS (a lista é grande — ~870 alunos).

Por que um script à parte, e não dentro do instalador.py:
  - As outras EMIAs (docentes, Chácara do Jóquei, Flores, Perus, Brasilândia,
    Parelheiros) JÁ FORAM importadas. Rodar o instalador.py de novo iria
    regerar aquelas linhas e, se coladas, duplicariam eleitores.
  - Jabaquara nunca entrou no sistema. Aqui cada família vira uma credencial
    NOVA do segmento "familia" — sem cruzar com a lista de docentes.
    Assim, um(a) docente que também é pai/mãe de aluno de Jabaquara continua
    tendo a SUA credencial de família (voto no segmento Famílias), além da
    credencial de docente que já possui.

Um voto por família:
  - Irmãos (mais de um filho na escola) caem na MESMA credencial.
  - O agrupamento é por TELEFONE ou E-MAIL em comum entre as linhas
    (a planilha de Jabaquara não tem coluna de responsável; os primeiros
    nomes que aparecem grudados no telefone são guardados só para conferência).
  - Chaves de acesso ao /acesso: nome completo de cada criança, telefones e
    e-mails da família. Digitar QUALQUER um leva à mesma cédula.

Uso:   python jabaquara.py [tamanho_do_bloco]      (padrão: 60)
Saída: ./saida_instalador/JABAQUARA_*.tsv  +  JABAQUARA_conferencia.csv
"""

import csv
import io
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

from instalador import (
    clean_name, clean_email, clean_phone, phone_variants,
    norm_name_key, group_families, dedup, PARTICULAS,
)

BASE = Path(__file__).resolve().parent
OUT = BASE / "saida_instalador"
SRC = BASE / "Contatos alunos EMIA Jabaquara.xlsx"
UNIDADE = "EMIA Jabaquara"
BLOCO = int(sys.argv[1]) if len(sys.argv) > 1 else 60

# Colunas (0-based) da planilha:
#   0 = nº (lixo, tem repetição)   1 = NOME DO ALUNO
#   2 = NASC  3 = IDADE/turma  4 = RG  5 = CPF
#   6 = TELEFONE 1 (pode ter vários números + nomes grudados)
#   7 = E-MAIL
COL_CRIANCA, COL_TEL, COL_EMAIL = 1, 6, 7

PHONE_RE = re.compile(r"\(?\d{2}\)?\s*9?\d{4,5}[-.\s]?\d{4}|\b\d{10,11}\b")


def titlecase_soft(nome):
    """Deixa 'enzo xavier' -> 'Enzo Xavier' sem estragar nomes já mistos."""
    out = []
    for i, t in enumerate(nome.split(" ")):
        low = t.lower()
        if i > 0 and unicodedata.normalize("NFKD", low).encode("ascii", "ignore").decode() in PARTICULAS:
            out.append(low)
        elif t and t == t.lower() and len(t) > 1:
            out.append(t[:1].upper() + t[1:])
        else:
            out.append(t)
    return " ".join(out)


def split_phones_and_names(cell):
    """Devolve (telefones_limpos, nomes_de_responsavel_crus)."""
    raw = "" if cell is None else str(cell)
    raw = raw.replace("\xa0", " ").replace("\n", " ").strip()
    if not raw or raw.lower() in ("none", "nan", "-"):
        return [], ([], [])
    phones, suspeitos = [], []
    for m in PHONE_RE.findall(raw):
        d, motivo = clean_phone(m)
        if d:
            phones.append(d)
            if motivo:
                suspeitos.append((m, d, motivo))
    # o que sobra depois de tirar os telefones costuma ser o 1º nome do
    # responsável ("- Rubia", "Cleide", "José") — serve só p/ conferência
    leftover = PHONE_RE.sub(" ", raw)
    leftover = re.sub(r"\(.*?\)", " ", leftover)  # tira "(mãe)", "(pai)"...
    nomes = []
    for tok in re.split(r"[^A-Za-zÀ-ÖØ-öø-ÿ']+", leftover):
        tl = tok.strip("'")
        if len(tl) >= 3 and tl.lower() not in (
            "mae", "pai", "avo", "avó", "tia", "tio", "mãe", "responsavel",
        ):
            nomes.append(tl[:1].upper() + tl[1:].lower())
    return dedup(phones), (dedup(nomes), suspeitos)


def load_rows():
    import openpyxl
    wb = openpyxl.load_workbook(SRC, data_only=True)
    ws = wb.worksheets[0]
    allrows = list(ws.iter_rows(values_only=True))
    rows, susp = [], []
    for r in allrows[1:]:                       # pula o cabeçalho
        if not r or r[COL_CRIANCA] in (None, ""):
            continue
        crianca = titlecase_soft(clean_name(r[COL_CRIANCA]))
        phones, (resp_names, ph_susp) = split_phones_and_names(r[COL_TEL])
        emails = []
        for chunk in re.split(r"[,;\s]+", str(r[COL_EMAIL] or "")):
            e = clean_email(chunk)
            if e:
                emails.append(e)
        if not (crianca or phones or emails):
            continue
        rows.append(dict(
            unidade=UNIDADE,
            children=[crianca] if crianca else [],
            responsibles=[n for n in resp_names if len(n.split()) >= 2],  # só nomes completos viram chave
            phones=phones,
            emails=dedup(emails),
            _src=SRC.name, _trusted=True,
            _phone_raw=[str(r[COL_TEL] or "")],
            _resp_frag=resp_names,          # primeiros nomes crus, p/ conferência
        ))
        for orig, limpo, motivo in ph_susp:
            susp.append([UNIDADE, crianca, orig, limpo, motivo])
    return rows, susp


# sobrenomes comuns demais p/ servir de "assinatura de família" sozinhos
SOBRENOMES_COMUNS = {
    "silva", "santos", "oliveira", "souza", "sousa", "lima", "costa", "pereira",
    "rodrigues", "almeida", "nascimento", "gomes", "ribeiro", "carvalho",
    "ferreira", "martins", "araujo", "rocha", "alves", "barbosa", "cardoso",
    "dias", "cruz", "moraes", "moreira", "nunes", "mendes", "freitas", "teixeira",
}


def surname_sig(children):
    """Assinatura de sobrenome p/ alertar 'irmão em credencial separada'.
    Usa os 2 últimos sobrenomes de cada criança, tirando os comuns demais;
    só vira assinatura se sobrar pelo menos 2 tokens distintos."""
    toks = []
    for c in children:
        parts = [p for p in norm_name_key(c).split() if p not in PARTICULAS]
        toks += [p for p in parts[-2:] if p not in SOBRENOMES_COMUNS]
    uniq = sorted(set(toks))
    return " ".join(uniq) if len(uniq) >= 2 else ""


def _rebuild_display(children, resps, phones):
    if children:
        disp = "Família de " + " • ".join(children[:3])
        if len(children) > 3:
            disp += f" (+{len(children) - 3})"
    elif resps:
        disp = "Família de " + resps[0]
    else:
        disp = "Família (sem nome) " + (phones[0] if phones else "")
    return disp[:200]


def merge_by_surname(fams):
    """2ª passada: junta famílias cujo telefone/e-mail não bateram mas que
    compartilham uma assinatura forte de sobrenome (>=2 sobrenomes incomuns
    iguais) — quase sempre são irmãos cadastrados com contatos diferentes
    (mãe numa linha, pai na outra). Devolve (familias, lista_de_merges)."""
    by_sig = defaultdict(list)
    passthrough = []
    for f in fams:
        s = surname_sig(f["children"])
        (by_sig[s] if s else passthrough).append(f)
    out, merges = list(passthrough), []
    for s, lst in by_sig.items():
        if len(lst) == 1:
            out.append(lst[0])
            continue
        children = dedup(sum((f["children"] for f in lst), []))
        resps = dedup(sum((f["responsibles"] for f in lst), []))
        phones = dedup(sum((f["phones"] for f in lst), []))
        emails = dedup(sum((f["emails"] for f in lst), []))
        disp = _rebuild_display(children, resps, phones)
        out.append(dict(
            segmento="familia", unidade=lst[0]["unidade"], display=disp,
            contato=(phones[0] if phones else (emails[0] if emails else "")),
            children=children, responsibles=resps, phones=phones, emails=emails,
            keys=dedup(children + resps + phones + emails),
            _srcs=[SRC.name], _phone_raw=[], _trusted=True,
        ))
        merges.append((disp, [f["display"] for f in lst]))
    return out, merges


def main():
    if not SRC.exists():
        sys.exit(f"ERRO: não achei {SRC.name} nesta pasta.")
    OUT.mkdir(exist_ok=True)

    rows, suspeitos = load_rows()
    print(f"[1] linhas de aluno lidas: {len(rows)}")

    fams = group_families(rows)
    print(f"[2] famílias após telefone/e-mail: {len(fams)}")
    fams, merges = merge_by_surname(fams)
    fams.sort(key=lambda f: norm_name_key(f["display"]))
    print(f"[3] famílias após juntar irmãos por sobrenome: {len(fams)} "
          f"({len(merges)} junções)")
    for novo, partes in merges:
        print(f"    juntou: {' + '.join(partes)}  ->  {novo}")

    # após as duas passadas, ainda pode sobrar irmão não pego (sobrenome muito
    # comum). O que restar com assinatura repetida vai como alerta p/ conferência.
    sig_map = defaultdict(list)
    for f in fams:
        s = surname_sig(f["children"])
        if s:
            sig_map[s].append(f)
    alerta = {id(f): "possível irmão em outra credencial — CONFERIR"
              for s, lst in sig_map.items() if len(lst) > 1 for f in lst}
    merged_disp = {novo for novo, _ in merges}
    for f in fams:
        if f["display"] in merged_disp:
            alerta[id(f)] = "IRMÃOS JUNTADOS na 2a passada (contatos diferentes) — confira"

    # ---- TSV completo + blocos ----
    def tsv_line(f):
        keys = dedup(f["children"] + f["responsibles"] + f["phones"] + f["emails"])
        kj = ";".join(k.replace(";", " ").replace("\t", " ").strip() for k in keys if k.strip())
        return "\t".join([f["display"], "familia", f["contato"], kj])

    linhas = [tsv_line(f) for f in fams]
    (OUT / "JABAQUARA_completo.tsv").write_text("\n".join(linhas) + "\n", encoding="utf-8")

    nblocos = (len(linhas) + BLOCO - 1) // BLOCO
    for b in range(nblocos):
        chunk = linhas[b * BLOCO:(b + 1) * BLOCO]
        (OUT / f"JABAQUARA_bloco_{b + 1:02d}.tsv").write_text(
            "\n".join(chunk) + "\n", encoding="utf-8")

    # ---- conferência humana (Excel) ----
    with (OUT / "JABAQUARA_conferencia.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["bloco", "unidade", "display_name", "n_criancas", "criancas",
                    "responsaveis_chave", "telefones", "emails", "alerta"])
        for i, f in enumerate(fams):
            w.writerow([
                i // BLOCO + 1, f["unidade"], f["display"], len(f["children"]),
                " | ".join(f["children"]),
                " | ".join(f["responsibles"]),
                " | ".join(f["phones"]), " | ".join(f["emails"]),
                alerta.get(id(f), ""),
            ])

    with (OUT / "JABAQUARA_telefones_suspeitos.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["unidade", "crianca", "telefone_original", "telefone_limpo", "motivo"])
        w.writerows(suspeitos)

    # ---- resumo ----
    r = io.StringIO()
    p = lambda *a: print(*a, file=r)
    p("=" * 66)
    p("  URNA EMIA - JABAQUARA - RESUMO")
    p("=" * 66)
    p(f"  Linhas de aluno lidas ............... {len(rows)}")
    p(f"  Familias distintas (credenciais) ... {len(fams)}")
    p(f"  Juncoes de irmaos por sobrenome .... {len(merges)}")
    p(f"  Tamanho do bloco ................... {BLOCO}")
    p(f"  Numero de blocos .................. {nblocos}")
    p(f"  Alertas 'possivel irmao separado' .. {len(alerta)}  (ver JABAQUARA_conferencia.csv)")
    p(f"  Telefones suspeitos ............... {len(suspeitos)}")
    if merges:
        p("")
        p("  IRMAOS JUNTADOS NA 2a PASSADA (confira no conferencia.csv):")
        for novo, partes in merges:
            p(f"    - {novo}")
    p("")
    p("  PASSO A PASSO (painel https://emia-urna.onrender.com/admin):")
    p("   1. NAO clicar em 'Zerar dados'.")
    p("   2. Em 'Importar eleitores', colar JABAQUARA_bloco_01.tsv inteiro,")
    p("      enviar, esperar a pagina de confirmacao.")
    p("   3. Repetir para bloco_02, bloco_03 ... ate o ultimo.")
    p("   4. Conferir no quadro 'Portal da Familia' que o total de chaves subiu.")
    p("   5. Testar /acesso com 2-3 nomes de crianca e telefones reais de Jabaquara.")
    p("")
    p("  ARQUIVOS (em ./saida_instalador/):")
    p("   JABAQUARA_bloco_NN.tsv .......... colar no painel, um de cada vez")
    p("   JABAQUARA_completo.tsv ......... tudo junto (caso queira colar de uma vez)")
    p("   JABAQUARA_conferencia.csv ..... abrir no Excel e revisar os 'alerta'")
    p("   JABAQUARA_telefones_suspeitos.csv")
    (OUT / "JABAQUARA_RESUMO.txt").write_text(r.getvalue(), encoding="utf-8-sig")
    sys.stdout.write(r.getvalue())


if __name__ == "__main__":
    main()
