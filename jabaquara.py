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
    norm_name_key, group_families, dedup, strip_acc, UF, PARTICULAS,
)

BASE = Path(__file__).resolve().parent
OUT = BASE / "saida_instalador"
SRC = BASE / "Contatos alunos EMIA Jabaquara.xlsx"
UNIDADE = "EMIA Jabaquara"
def _arg_bloco():
    # tolerante: ignora argv que não seja um número (ex.: quando jaba_fix.py
    # importa este módulo e passa --desde), cai no padrão 60.
    for a in sys.argv[1:]:
        if a.isdigit():
            return int(a)
    return 60


BLOCO = _arg_bloco()

# Colunas (0-based) da planilha:
#   0 = nº (lixo, tem repetição)   1 = NOME DO ALUNO
#   2 = NASC  3 = IDADE/turma  4 = RG  5 = CPF
#   6 = TELEFONE 1 (pode ter vários números + nomes grudados)
#   7 = E-MAIL
COL_CRIANCA, COL_TURMA, COL_TEL, COL_EMAIL = 1, 3, 6, 7

PHONE_RE = re.compile(r"\(?\d{2}\)?\s*9?\d{4,5}[-.\s]?\d{4}|\b\d{10,11}\b")

# palavras que não são nome de responsável (parentesco / lixo de célula)
RESP_STOP = {
    "mae", "pai", "avo", "avó", "avô", "tia", "tio", "tias", "tios", "vo", "vó",
    "responsavel", "resp", "mãe", "e", "de", "da", "do", "das", "dos",
    "contato", "cel", "tel", "whatsapp", "zap", "recado", "trabalho",
}


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
    """Devolve (telefones_limpos, (nomes_de_responsavel, telefones_suspeitos)).

    O campo TELEFONE da planilha de Jabaquara mistura vários números e o
    primeiro nome de quem atende, muitas vezes grudado:
      '(11) 97976-3197 - Rubia(11) 97976-3112Rúbia'
    Aqui separo os dois: números viram chave de telefone; os trechos de texto
    ENTRE os números viram nome de responsável (parcial, como veio)."""
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
    nomes = []
    for piece in PHONE_RE.split(raw):
        piece = re.sub(r"\(.*?\)", " ", piece)                     # (mãe)/(pai)
        piece = re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ' ]+", " ", piece)       # '-', dígitos
        toks = [t for t in piece.split()
                if len(t) >= 2 and strip_acc(t).lower() not in RESP_STOP]
        if toks:
            nomes.append(" ".join(t[:1].upper() + t[1:].lower() for t in toks))
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
        turma = re.sub(r"\s+", "", str(r[COL_TURMA] or "").upper()) or "?"
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
            responsibles=[n for n in resp_names if len(n.split()) >= 2],  # só nome completo vira chave
            phones=phones,
            emails=dedup(emails),
            _src=SRC.name, _trusted=True,
            _phone_raw=[str(r[COL_TEL] or "")],
            _resp_frag=resp_names,          # nomes como vieram (parciais), p/ conferência
            _turma=turma,
        ))
        for orig, limpo, motivo in ph_susp:
            susp.append([UNIDADE, crianca, orig, limpo, motivo])
    return rows, susp


# sobrenomes comuns demais (ou sufixos) p/ servir de "assinatura de família"
# sozinhos — a assinatura só vale se tiver ALGO fora desta lista.
SOBRENOMES_COMUNS = {
    "silva", "santos", "oliveira", "souza", "sousa", "lima", "costa", "pereira",
    "rodrigues", "almeida", "nascimento", "gomes", "ribeiro", "carvalho",
    "ferreira", "martins", "araujo", "rocha", "alves", "barbosa", "cardoso",
    "dias", "cruz", "moraes", "moreira", "nunes", "mendes", "freitas", "teixeira",
    "reis", "vieira", "correia", "pinto", "ramos", "monteiro", "batista",
    "cavalcante", "campos", "castro", "andrade", "machado", "barros", "melo",
    "neto", "filho", "junior", "sobrinho",   # sufixos de nome, não identificam
}


def surname_sig(children):
    """Assinatura de sobrenome p/ juntar irmãos que ficaram em credenciais
    separadas (contatos diferentes). Pega os 2 últimos sobrenomes de cada
    criança. Só vale como assinatura se houver >=2 sobrenomes distintos E
    pelo menos 1 deles for incomum (senão 'Alves Silva' juntaria meio mundo).
    A assinatura em si é o conjunto COMPLETO de sobrenomes — duas famílias só
    se juntam se compartilharem exatamente o mesmo conjunto."""
    toks = []
    for c in children:
        parts = [p for p in norm_name_key(c).split() if p not in PARTICULAS]
        toks += parts[-2:]
    uniq = sorted(set(toks))
    incomuns = [t for t in uniq if t not in SOBRENOMES_COMUNS]
    return " ".join(uniq) if (len(uniq) >= 2 and incomuns) else ""


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


def _mk_family(member_rows):
    """Monta um dict de família a partir de um conjunto de linhas de aluno."""
    children = dedup(sum((r["children"] for r in member_rows), []))
    resps = dedup(sum((r["responsibles"] for r in member_rows), []))
    phones = dedup(sum((r["phones"] for r in member_rows), []))
    emails = dedup(sum((r["emails"] for r in member_rows), []))
    return dict(
        segmento="familia",
        unidade=member_rows[0]["unidade"] if member_rows else UNIDADE,
        display=_rebuild_display(children, resps, phones),
        contato=(phones[0] if phones else (emails[0] if emails else "")),
        children=children, responsibles=resps, phones=phones, emails=emails,
        keys=dedup(children + resps + phones + emails),
        _srcs=[SRC.name], _phone_raw=[], _trusted=True, _members=member_rows,
    )


def _surname_tokens(name):
    return {t for t in norm_name_key(name).split()
            if t not in PARTICULAS and len(t) >= 3}


def _members_by_family(fams, rows):
    """Mapeia cada linha de aluno para a família (índice) a que ela pertence."""
    by_phone, by_email, by_child = {}, {}, {}
    for i, f in enumerate(fams):
        for p in f["phones"]:
            for v in phone_variants(p):
                by_phone.setdefault(v, i)
        for e in f["emails"]:
            by_email.setdefault(e, i)
        for c in f["children"]:
            k = norm_name_key(c)
            if k:
                by_child.setdefault(k, i)
    members = defaultdict(list)
    for r in rows:
        idx = None
        for c in r["children"]:
            idx = by_child.get(norm_name_key(c), idx)
        if idx is None:
            for p in r["phones"]:
                for v in phone_variants(p):
                    idx = by_phone.get(v, idx)
        if idx is None:
            for e in r["emails"]:
                idx = by_email.get(e, idx)
        if idx is not None:
            members[idx].append(r)
    return members


def split_unrelated_families(fams, rows):
    """Desfaz merges do union-find em que linhas de alunos SEM sobrenome em
    comum (nem responsável completo em comum) foram unidas só por um
    telefone/e-mail compartilhado — quase sempre erro de digitação da
    planilha da secretaria, ou contato de terceiro (avó, motorista...).

    Reagrupa as linhas de cada 'família' por conexão de NOME: duas linhas
    ficam juntas se compartilham um sobrenome de criança OU um nome completo
    (>=2 tokens) de responsável. Cada componente vira uma credencial.
    Devolve (familias, lista_de_desmembramentos)."""
    members = _members_by_family(fams, rows)
    out, desmembr = [], []
    for i, f in enumerate(fams):
        mem = members.get(i, [])
        if len(mem) <= 1:
            out.append(f)
            continue
        surn = [set().union(*[_surname_tokens(n) for n in m["children"]])
                if m["children"] else set() for m in mem]
        resp = [{norm_name_key(n) for n in m["responsibles"] if len(n.split()) >= 2}
                for m in mem]
        uf = UF()
        for a in range(len(mem)):
            uf.find(a)
            for b in range(a + 1, len(mem)):
                if (surn[a] & surn[b]) or (resp[a] & resp[b]):
                    uf.union(a, b)
        comps = defaultdict(list)
        for a in range(len(mem)):
            comps[uf.find(a)].append(mem[a])
        if len(comps) == 1:
            out.append(f)
            continue
        novos = sorted((_mk_family(c) for c in comps.values()),
                       key=lambda x: norm_name_key(x["display"]))
        out.extend(novos)
        desmembr.append((f["display"], [n["display"] for n in novos]))
    return out, desmembr


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


def enrich_from_rows(fams, rows):
    """group_families descarta turma e nomes parciais de responsável. Aqui
    re-associo cada linha original à sua família (por telefone/e-mail/nome de
    criança) e devolvo turma + nomes parciais de volta, só p/ conferência."""
    by_phone, by_email, by_child = {}, {}, {}
    for i, f in enumerate(fams):
        for p in f["phones"]:
            for v in phone_variants(p):
                by_phone[v] = i
        for e in f["emails"]:
            by_email[e] = i
        for c in f["children"]:
            k = norm_name_key(c)
            if k:
                by_child[k] = i
        f["_turmas"], f["_resp_parciais"] = set(), []
    for r in rows:
        idx = None
        for p in r["phones"]:
            for v in phone_variants(p):
                idx = by_phone.get(v, idx)
        for e in r["emails"]:
            idx = by_email.get(e, idx)
        for c in r["children"]:
            idx = by_child.get(norm_name_key(c), idx)
        if idx is None:
            continue
        fams[idx]["_turmas"].add(r.get("_turma", "?"))
        fams[idx]["_resp_parciais"] += r.get("_resp_frag", [])
    for f in fams:
        f["_turmas"] = " ".join(sorted(t for t in f["_turmas"] if t and t != "?"))
        f["_resp_parciais"] = " | ".join(dedup(f["_resp_parciais"]))


def sibling_review(fams):
    """Rede de segurança MANUAL: qualquer par de famílias cujas crianças
    compartilhem 2+ sobrenomes (inclui os comuns) e que ficaram em
    credenciais separadas. Não junta nada — só lista p/ olho humano."""
    def sig(children):
        toks = []
        for c in children:
            parts = [p for p in norm_name_key(c).split() if p not in PARTICULAS]
            toks += parts[-2:]
        u = sorted(set(toks))
        return " ".join(u) if len(u) >= 2 else ""
    grp = defaultdict(list)
    for f in fams:
        s = sig(f["children"])
        if s:
            grp[s].append(f)
    linhas = []
    for s, lst in sorted(grp.items()):
        if len(lst) < 2:
            continue
        for f in lst:
            linhas.append([s, f["_turmas"], f["display"],
                           " | ".join(f["children"]),
                           " | ".join(f["phones"]), " | ".join(f["emails"])])
    return linhas


def main():
    if not SRC.exists():
        sys.exit(f"ERRO: não achei {SRC.name} nesta pasta.")
    OUT.mkdir(exist_ok=True)

    rows, suspeitos = load_rows()
    print(f"[1] linhas de aluno lidas: {len(rows)}")

    fams = group_families(rows)
    print(f"[2] famílias após telefone/e-mail/nome: {len(fams)}")
    fams, desmembr = split_unrelated_families(fams, rows)
    print(f"[2b] após separar credenciais que juntaram famílias diferentes "
          f"(telefone/e-mail compartilhado): {len(fams)} ({len(desmembr)} desmembradas)")
    for antigo, partes in desmembr:
        print(f"    separou: {antigo}")
        for p in partes:
            print(f"             -> {p}")
    fams, merges = merge_by_surname(fams)
    fams.sort(key=lambda f: norm_name_key(f["display"]))
    enrich_from_rows(fams, rows)
    print(f"[3] famílias após juntar irmãos por sobrenome: {len(fams)} "
          f"({len(merges)} junções)")
    for novo, partes in merges:
        print(f"    juntou: {' + '.join(partes)}  ->  {novo}")

    revisar = sibling_review(fams)

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
        w.writerow(["bloco", "unidade", "turmas", "display_name", "n_criancas",
                    "criancas", "responsaveis_completos_chave",
                    "responsaveis_parciais_planilha", "telefones", "emails",
                    "alerta"])
        for i, f in enumerate(fams):
            w.writerow([
                i // BLOCO + 1, f["unidade"], f.get("_turmas", ""), f["display"],
                len(f["children"]), " | ".join(f["children"]),
                " | ".join(f["responsibles"]), f.get("_resp_parciais", ""),
                " | ".join(f["phones"]), " | ".join(f["emails"]),
                alerta.get(id(f), ""),
            ])

    # ---- rede de segurança: possíveis irmãos em credenciais separadas ----
    with (OUT / "JABAQUARA_revisar_irmaos.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["assinatura_sobrenome", "turmas", "display_name",
                    "criancas", "telefones", "emails"])
        w.writerows(revisar)

    with (OUT / "JABAQUARA_telefones_suspeitos.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["unidade", "crianca", "telefone_original", "telefone_limpo", "motivo"])
        w.writerows(suspeitos)

    # ---- credenciais que juntavam famílias diferentes e foram separadas ----
    with (OUT / "JABAQUARA_desmembradas.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["credencial_ERRADA_que_juntava_familias",
                    "credenciais_corretas_geradas_no_lugar"])
        for antigo, partes in desmembr:
            w.writerow([antigo, "  ||  ".join(partes)])

    # ---- resumo ----
    r = io.StringIO()
    p = lambda *a: print(*a, file=r)
    p("=" * 66)
    p("  URNA EMIA - JABAQUARA - RESUMO")
    p("=" * 66)
    from collections import Counter as _C
    turmas = _C()
    for f in fams:
        for t in (f.get("_turmas", "") or "?").split():
            turmas[t] += 1
    p(f"  Linhas de aluno lidas ............... {len(rows)}")
    p(f"  Familias distintas (credenciais) ... {len(fams)}")
    p(f"  Credenciais desmembradas (juntavam familias diferentes): {len(desmembr)}")
    p(f"     -> ver JABAQUARA_desmembradas.csv")
    p(f"  Juncoes de irmaos por sobrenome .... {len(merges)}")
    p(f"  Tamanho do bloco ................... {BLOCO}")
    p(f"  Numero de blocos .................. {nblocos}")
    p(f"  Linhas marcadas na conferencia ..... {len(alerta)}  (col 'alerta')")
    p(f"  Familias p/ revisao manual de irmaos {len(revisar)} linhas  (JABAQUARA_revisar_irmaos.csv)")
    p(f"  Telefones suspeitos ............... {len(suspeitos)}")
    p("")
    p("  FAMILIAS POR TURMA (col IDADE da planilha):")
    for t, n in sorted(turmas.items()):
        p(f"    {t:6s} {n}")
    if turmas.get("FORM"):
        p(f"  >> {turmas['FORM']} familias marcadas 'FORM' (formandos?). A Comissao")
        p("     precisa decidir se essas familias votam antes de abrir a urna.")
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
    p("   JABAQUARA_bloco_NN.tsv ......... colar no painel, um de cada vez")
    p("   JABAQUARA_completo.tsv ........ tudo junto (caso queira colar de uma vez)")
    p("   JABAQUARA_conferencia.csv .... abrir no Excel; revisar coluna 'alerta'")
    p("   JABAQUARA_desmembradas.csv ... credenciais que juntavam familias")
    p("                                 diferentes e foram separadas (CONFERIR)")
    p("   JABAQUARA_revisar_irmaos.csv . pares de familias c/ mesmo sobrenome")
    p("   JABAQUARA_telefones_suspeitos.csv")
    (OUT / "JABAQUARA_RESUMO.txt").write_text(r.getvalue(), encoding="utf-8-sig")
    sys.stdout.write(r.getvalue())


if __name__ == "__main__":
    main()
