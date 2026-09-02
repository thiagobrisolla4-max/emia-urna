#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Instalador serial da Urna EMIA — prepara TODA a lista de eleitores de uma vez.

O que ele faz, em ordem, sem tocar em nada online (só lê planilhas/PDF e
escreve arquivos locais em ./saida_instalador/):

  1. Lê a lista de docentes (DADOS Educadores EMIA.xlsx)           -> 90
  2. Lê as listas de famílias de várias EMIAs (xlsx + PDF)
  3. Corrige encoding/lixo nos nomes, normaliza telefones e e-mails
  4. Agrupa as famílias: irmãos e vários responsáveis (mãe, pai, avó...)
     caem TODOS numa credencial só — um voto por família
  5. Casa cada família com as credenciais que JÁ existem (credenciais-emia.csv)
     para não duplicar ninguém; o resto entra como novo
  6. Gera os arquivos prontos pra colar no painel /admin:
       A_chaves_para_tokens_existentes.tsv  -> "Vincular chaves a credenciais já existentes"
       B_novos_eleitores.tsv                -> "Importar eleitores"
       C_conferencia_familias.csv           -> conferência humana (abre no Excel)
       D_telefones_suspeitos.csv            -> telefones a conferir na mão
       E_possiveis_familias_duplicadas.csv  -> possíveis famílias repetidas
       RESUMO.txt                           -> contagem + passo a passo + links

Rodar:   python instalador.py
Requer:  openpyxl  (e pypdf/PyPDF2 se quiser extrair nomes de criança dos PDFs)
"""

import csv
import io
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

BASE = Path(__file__).resolve().parent
OUT = BASE / "saida_instalador"

SISTEMA_URL = "https://emia-urna.onrender.com"
LINKS = {
    "Urna (sistema)": SISTEMA_URL,
    "Painel da Comissão (admin)": SISTEMA_URL + "/admin",
    "Portal da Família (autoatendimento)": SISTEMA_URL + "/acesso",
    "Resultados (após apuração)": SISTEMA_URL + "/resultados",
    "Dashboard Render": "https://dashboard.render.com",
    "Repositório GitHub": "https://github.com/thiagobrisolla4-max/emia-urna",
}

# --------------------------------------------------------------------------
# Fontes. Se um arquivo não existir, é só ignorado com um aviso (ex.: a lista
# de famílias da EMIA Jabaquara, que ainda não chegou).
# --------------------------------------------------------------------------
SRC_DOCENTES = BASE / "DADOS Educadores EMIA.xlsx"
SRC_FAMILIA_XLSX = [
    # (arquivo, unidade_padrão, mapa_de_colunas)
    (BASE / "LISTA CONTATOS - Chácara do Jóquei.xlsx", "EMIA Chácara do Jóquei",
     dict(child=0, resp=1, phone=2, email=3, header=1)),
    (BASE / "Nome, número e e-mail responsável - EMIA Flores.xlsx", "EMIA Chácara das Flores",
     dict(child=0, resp=1, phone=2, email=3, header=1)),
    (BASE / "MATRICULADOS EMIA - CONTATOS.xlsx", "EMIA Perus",
     dict(child="NOME DA CRIAN", resp="RESPONS", phone="CELULAR", email="EMAIL", header=1)),
]
SRC_FAMILIA_PDF = [
    (BASE / "Dados alunos emia brasilândia (2026).pdf", "EMIA Brasilândia", "brasilandia"),
    (BASE / "AUTORIZAÇÃO ALUNOS 2026 - EMIA PARELHEIROS.pdf", "EMIA Parelheiros", "parelheiros"),
]
SRC_CREDENCIAIS = BASE / "credenciais-emia.csv"          # já geradas (link = token)
SRC_CREDENCIAIS_ALT = BASE / "eleitores_geral_com_links.csv"

PARTICULAS = {"de", "da", "do", "das", "dos", "e", "di", "du", "del", "van", "von"}


# ==========================================================================
# Limpeza de texto / telefone / e-mail
# ==========================================================================
def clean_text(s):
    if s is None:
        return ""
    s = str(s)
    s = unicodedata.normalize("NFC", s)
    s = s.replace("\xa0", " ").replace("​", " ").replace("’", "'")
    s = s.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def clean_name(s):
    """Nome de pessoa: tira lixo (&, $, }, #, dígitos soltos), arruma CAPS."""
    s = clean_text(s)
    if not s:
        return ""
    # remove datas e blocos de dígitos (RG/CPF colados vindos de PDF)
    s = re.sub(r"\d{2}[/.\-]\d{2}[/.\-]\d{2,4}", " ", s)
    s = re.sub(r"\d{4,}", " ", s)
    # mantém só letras, espaço, hífen, apóstrofo e ponto
    s = re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ'.\- ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip(" .-")
    if not s:
        return ""
    # CAPS -> Title Case (mantém nomes já mistos)
    letters = re.sub(r"[^A-Za-zÀ-ÿ]", "", s)
    if letters and letters == letters.upper():
        s = s.title()
    # partículas em minúscula
    toks = s.split(" ")
    out = []
    for i, t in enumerate(toks):
        low = strip_acc(t).lower()
        if i > 0 and low in PARTICULAS:
            out.append(low)
        else:
            out.append(t)
    return " ".join(out).strip()


def strip_acc(s):
    return "".join(c for c in unicodedata.normalize("NFD", s or "")
                   if unicodedata.category(c) != "Mn")


def norm_name_key(s):
    s = strip_acc(clean_name(s)).lower()
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    toks = [t for t in s.split(" ") if len(t) >= 2 and t not in PARTICULAS]
    return " ".join(toks)


PHONE_JUNK = {"", "nao tem", "não tem", "n tem", "sem", "-", "x", "0"}


def clean_phone(s):
    """Devolve (digitos_limpos, motivo_suspeita_ou_None)."""
    raw = clean_text(s)
    if raw.lower() in PHONE_JUNK:
        return "", None
    d = re.sub(r"\D", "", raw)
    if not d:
        return "", None
    if len(d) > 11 and d.startswith("55"):
        d = d[2:]
    # artefato do Excel: um "0" a mais no fim de um celular de 11 dígitos
    if len(d) == 12 and d.endswith("0"):
        d = d[:11]
    if len(d) > 11:
        d = d[-11:]
    motivo = None
    if len(d) not in (10, 11):
        motivo = f"{len(d)} dígitos (esperado 10 ou 11)"
    elif len(set(d)) <= 2:
        motivo = "dígitos repetidos"
    elif d[0] == "0":
        motivo = "começa com 0"
    elif int(d[:2]) < 11 or int(d[:2]) > 99:
        motivo = f"DDD improvável ({d[:2]})"
    return d, motivo


def phone_variants(d):
    """11 <-> 10 dígitos (com/sem o 9), pra casar formatos diferentes."""
    if not d:
        return set()
    v = {d}
    if len(d) == 11 and d[2] == "9":
        v.add(d[:2] + d[3:])
    if len(d) == 10:
        v.add(d[:2] + "9" + d[2:])
    return v


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")


def clean_email(s):
    s = clean_text(s).lower().replace(" ", "")
    if not s or "@" not in s:
        return ""
    if any(j in s for j in ("naotem", "nãotem", "sememail", "----")):
        return ""
    s = s.strip(".,;")
    return s if EMAIL_RE.match(s) else ""


# ==========================================================================
# Leitura das planilhas
# ==========================================================================
def load_xlsx_rows(path):
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True)
    for ws in wb.worksheets:
        rows = [[None if c is None else str(c).strip() for c in r]
                for r in ws.iter_rows(values_only=True)]
        yield ws.title, rows


def col_index(header, want):
    """want pode ser um int (posição) ou um trecho do nome da coluna."""
    if isinstance(want, int):
        return want
    up = [strip_acc(h or "").upper() for h in header]
    for i, h in enumerate(up):
        if strip_acc(want).upper() in h:
            return i
    return None


def parse_docentes():
    out = []
    if not SRC_DOCENTES.exists():
        print(f"  ! docentes: arquivo não encontrado ({SRC_DOCENTES.name})")
        return out
    for unit, rows in load_xlsx_rows(SRC_DOCENTES):
        unit_nome = "EMIA " + clean_text(unit)
        for r in rows:
            if not r or len(r) < 5:
                continue
            idx, nome, ling, email, tel = (list(r) + [None] * 6)[:5]
            if not re.match(r"^\s*\d", str(idx or "")):
                continue
            nome = clean_name(nome)
            if not nome:
                continue
            ph, _ = clean_phone(tel)
            em = clean_email(email)
            keys = [nome, ph, em]
            out.append(dict(
                segmento="docente", unidade=unit_nome, display=nome,
                contato=(em or ph), children=[], responsibles=[nome],
                phones=[ph] if ph else [], emails=[em] if em else [],
                keys=[k for k in keys if k],
            ))
    return out


def parse_familia_xlsx():
    fams = []
    for path, unit_default, cm in SRC_FAMILIA_XLSX:
        if not path.exists():
            print(f"  ! famílias: arquivo não encontrado ({path.name}) — pulando")
            continue
        n0 = len(fams)
        for sheet, rows in load_xlsx_rows(path):
            if not rows:
                continue
            hdr = rows[cm["header"] - 1] if cm["header"] else rows[0]
            ci_child = col_index(hdr, cm["child"])
            ci_resp = col_index(hdr, cm["resp"])
            ci_phone = col_index(hdr, cm["phone"])
            ci_email = col_index(hdr, cm["email"])
            for r in rows[cm["header"]:]:
                if not r or not any(r):
                    continue
                def g(i):
                    return r[i] if (i is not None and i < len(r)) else None
                child = clean_name(g(ci_child))
                resp = clean_name(g(ci_resp))
                ph, _ = clean_phone(g(ci_phone))
                em = clean_email(g(ci_email))
                if not (child or resp or ph or em):
                    continue
                fams.append(dict(
                    unidade=unit_default,
                    children=[child] if child else [],
                    responsibles=[resp] if resp else [],
                    phones=[ph] if ph else [],
                    emails=[em] if em else [],
                    _src=path.name, _trusted=True,
                    _phone_raw=[clean_text(g(ci_phone))] if g(ci_phone) else [],
                ))
        print(f"  - {path.name}: +{len(fams) - n0} linhas de família")
    return fams


def parse_familia_pdf():
    fams = []
    try:
        from pypdf import PdfReader
    except Exception:
        try:
            from PyPDF2 import PdfReader
        except Exception:
            print("  ! pypdf/PyPDF2 ausente — nomes de criança de Brasilândia/"
                  "Parelheiros não serão extraídos (não é bloqueante)")
            return fams
    for path, unit, kind in SRC_FAMILIA_PDF:
        if not path.exists():
            print(f"  ! {path.name} não encontrado — pulando")
            continue
        try:
            reader = PdfReader(str(path))
            text = " ".join((pg.extract_text() or "") for pg in reader.pages)
        except Exception as e:
            print(f"  ! falha lendo {path.name}: {e}")
            continue
        recs = _pdf_records(text, kind)
        for child, resps, phones, emails in recs:
            child = clean_name(child)
            resps = [clean_name(x) for x in resps if clean_name(x)]
            ph = []
            for p in phones:
                d, _ = clean_phone(p)
                if d:
                    ph.append(d)
            em = [clean_email(x) for x in emails if clean_email(x)]
            if not (child or resps or ph or em):
                continue
            fams.append(dict(unidade=unit, children=[child] if child else [],
                             responsibles=resps, phones=ph, emails=em,
                             _src=path.name, _trusted=False, _phone_raw=list(phones)))
        print(f"  - {path.name}: +{len(recs)} registros extraídos (conferir na mão)")
    return fams


def _pdf_records(text, kind):
    """Extração best-effort. Devolve [(child, [resp], [phone], [email])]."""
    text = re.sub(r"\s+", " ", text)
    email_re = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
    phone_re = re.compile(r"\(?\d{2}\)?\s*9?\d{4,5}[\-\s]?\d{4}|\b\d{10,11}\b")
    out = []
    if kind == "brasilandia":
        # <Nome><digitos RG/CPF><Responsavel><email><telefone>Turma...
        marks = list(email_re.finditer(text))
        prev = 0
        for m in marks:
            seg = text[prev:m.start()]
            after = text[m.end():m.end() + 40]
            phs = phone_re.findall(after)
            mm = re.match(r"\s*(.+?)(\d{6,})\s*(.+)$", seg)
            if mm:
                child, resp = mm.group(1), mm.group(3)
                child = re.sub(r"(NOME DA CRIAN.A|RG.?CPF DO ALUNO|RESPONS.VEL|"
                               r"Email|Telefone de contato|TURMA)", " ", child, flags=re.I)
                out.append((child, [resp], phs, [m.group(0)]))
            prev = m.end()
    elif kind == "parelheiros":
        chunks = re.split(r"Nome\s+d[oa]\s+(?:Crian[çc]a|Matriculad[oa])\s*:", text)
        for ch in chunks[1:]:
            ch = ch[:600]
            emails = email_re.findall(ch)
            phones = phone_re.findall(ch)
            head = re.split(r"Respons.vel|Email\s*:|\d{2}/\d{2}/\d{4}", ch, maxsplit=1)[0]
            child = head
            resp_part = ""
            mr = re.search(r"Respons.vel\s*:?(.+?)(Email\s*:|$)", ch)
            if mr:
                resp_part = mr.group(1)
            resps = re.findall(r"[A-ZÀ-Ý][a-zà-ý]+(?:\s+[A-Za-zÀ-ý']+){1,4}", resp_part)
            resps = [x for x in resps if not re.search(r"M.e|Pai|Av[óo]|Tia|Tio|Irm", x)]
            out.append((child, resps[:3], phones, emails))
    return out


# ==========================================================================
# Agrupamento de famílias (union-find)
# ==========================================================================
class UF:
    def __init__(self):
        self.p = {}

    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        self.p[self.find(a)] = self.find(b)


def group_families(rows):
    uf = UF()
    for i, r in enumerate(rows):
        node = ("row", i)
        uf.find(node)
        for nm in r["responsibles"]:
            k = norm_name_key(nm)
            if k and len(k.split()) >= 2:
                uf.union(node, ("name", k))
        for ph in r["phones"]:
            for v in phone_variants(ph):
                if len(v) >= 10:
                    uf.union(node, ("ph", v))
        for em in r["emails"]:
            if em:
                uf.union(node, ("em", em))
    groups = defaultdict(list)
    for i, r in enumerate(rows):
        groups[uf.find(("row", i))].append(r)

    fams = []
    for members in groups.values():
        children, resps, phones, emails, phraw, srcs, units = [], [], [], [], [], [], []
        trusted = False
        for m in members:
            children += m["children"]
            resps += m["responsibles"]
            phones += m["phones"]
            emails += m["emails"]
            phraw += m.get("_phone_raw", [])
            srcs.append(m.get("_src", ""))
            units.append(m["unidade"])
            trusted = trusted or m.get("_trusted", False)
        children = dedup(children)
        resps = dedup(resps)
        phones = dedup(phones)
        emails = dedup(emails)
        unit = Counter(units).most_common(1)[0][0]
        if children:
            disp = "Família de " + " • ".join(children[:3])
            if len(children) > 3:
                disp += f" (+{len(children) - 3})"
        elif resps:
            disp = "Família de " + resps[0]
        else:
            disp = "Família (sem nome) " + (phones[0] if phones else "")
        contato = next((p for p in phones), "") or next((e for e in emails), "")
        keys = dedup(children + resps + phones + emails)
        fams.append(dict(
            segmento="familia", unidade=unit, display=disp[:200], contato=contato,
            children=children, responsibles=resps, phones=phones, emails=emails,
            keys=keys, _srcs=dedup(srcs), _phone_raw=dedup(phraw), _trusted=trusted,
        ))
    return fams


def dedup(seq):
    seen, out = set(), []
    for x in seq:
        x = (x or "").strip()
        if x and x.lower() not in seen:
            seen.add(x.lower())
            out.append(x)
    return out


# ==========================================================================
# Casar com credenciais já existentes
# ==========================================================================
def load_existing_credentials():
    path = SRC_CREDENCIAIS if SRC_CREDENCIAIS.exists() else SRC_CREDENCIAIS_ALT
    if not path.exists():
        print("  ! nenhum CSV de credenciais existentes encontrado")
        return [], {}, {}
    text = path.read_text(encoding="utf-8-sig")
    rows = list(csv.DictReader(text.splitlines()))
    by_name, by_phone = {}, {}
    tokens = {}  # token -> {nome, contato}
    for r in rows:
        link = r.get("link") or ""
        token = link.rstrip("/").rsplit("/", 1)[-1] if "/" in link else ""
        if not token:
            continue
        tokens[token] = {"nome": r.get("nome", ""), "contato": r.get("contato", "")}
        nk = norm_name_key(r.get("nome", ""))
        if nk:
            by_name.setdefault(nk, token)
        d, _ = clean_phone(r.get("contato", ""))
        for v in phone_variants(d):
            by_phone.setdefault(v, token)
    print(f"  - credenciais já existentes: {len(rows)} linhas "
          f"({path.name}) -> {len(tokens)} tokens")
    return rows, by_name, by_phone, tokens


def match_existing(fams, by_name, by_phone):
    novas, existentes, conflitos, descartadas = [], [], [], []
    for f in fams:
        hits = set()
        for nm in f["responsibles"]:
            t = by_name.get(norm_name_key(nm))
            if t:
                hits.add(t)
        for ph in f["phones"]:
            for v in phone_variants(ph):
                t = by_phone.get(v)
                if t:
                    hits.add(t)
        if not hits:
            # Só cria credencial nova a partir de fonte confiável (planilha).
            # Registro que veio só de PDF e não casou com nada é descartado
            # (a família provavelmente já tem credencial com outro contato).
            if f.get("_trusted"):
                novas.append(f)
            else:
                descartadas.append(f)
        elif len(hits) == 1:
            f["token"] = next(iter(hits))
            existentes.append(f)
        else:
            f["token"] = sorted(hits)[0]
            f["_conflito"] = sorted(hits)
            existentes.append(f)
            conflitos.append(f)
    return novas, existentes, conflitos, descartadas


# ==========================================================================
# Saídas
# ==========================================================================
def kjoin(keys):
    return ";".join(k.replace(";", " ").replace("\t", " ").strip()
                    for k in keys if k and k.strip())


def write_outputs(docentes, fam_novas, fam_existentes, conflitos, descartadas,
                  suspeitos, dups, existing_tokens):
    OUT.mkdir(exist_ok=True)

    # A — chaves para tokens já existentes. Cobre TODOS os 359 tokens: cada um
    # recebe pelo menos o próprio nome + contato; os que casaram com uma
    # família recebem também nomes de criança, telefones e e-mails extras.
    a_keys = defaultdict(set)
    for tok, info in existing_tokens.items():
        for k in (info.get("nome"), info.get("contato")):
            if k and k.strip():
                a_keys[tok].add(k.strip())
    for f in fam_existentes:
        if not f.get("_trusted"):
            continue  # dados só-de-PDF não enriquecem chave (parsing incerto)
        for k in f["keys"]:
            if k and k.strip():
                a_keys[f["token"]].add(k.strip())
    with (OUT / "A_chaves_para_tokens_existentes.tsv").open("w", encoding="utf-8", newline="") as fh:
        for tok in sorted(a_keys):
            fh.write(tok + "\t" + kjoin(sorted(a_keys[tok])) + "\n")

    # G — CONFLITO: família casou com mais de uma credencial existente = há
    # duas credenciais para a mesma família (risco de voto dobrado).
    with (OUT / "G_conflito_credencial_dupla.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["confianca", "unidade", "familia", "tokens_conflitantes",
                    "responsaveis", "telefones"])
        for f in conflitos:
            w.writerow(["ALTA (planilha)" if f.get("_trusted") else "baixa (só PDF)",
                        f["unidade"], f["display"], " ; ".join(f["_conflito"]),
                        " | ".join(f["responsibles"]), " | ".join(f["phones"])])

    # B — novos eleitores (docentes + famílias novas)
    with (OUT / "B_novos_eleitores.tsv").open("w", encoding="utf-8", newline="") as fh:
        for d in docentes:
            fh.write("\t".join([d["display"], "docente", d["contato"], kjoin(d["keys"])]) + "\n")
        for f in fam_novas:
            fh.write("\t".join([f["display"], "familia", f["contato"], kjoin(f["keys"])]) + "\n")

    # B1/B2 separados (pra colar em blocos menores, se preferir)
    with (OUT / "B1_docentes.tsv").open("w", encoding="utf-8", newline="") as fh:
        for d in docentes:
            fh.write("\t".join([d["display"], "docente", d["contato"], kjoin(d["keys"])]) + "\n")
    with (OUT / "B2_familias_novas.tsv").open("w", encoding="utf-8", newline="") as fh:
        for f in fam_novas:
            fh.write("\t".join([f["display"], "familia", f["contato"], kjoin(f["keys"])]) + "\n")

    # C — conferência humana
    with (OUT / "C_conferencia_familias.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["segmento", "unidade", "status", "token", "display_name",
                    "criancas", "responsaveis", "telefones", "emails", "fontes"])
        for d in docentes:
            w.writerow(["docente", d["unidade"], "novo", "", d["display"], "",
                        " | ".join(d["responsibles"]), " | ".join(d["phones"]),
                        " | ".join(d["emails"]), ""])
        for f in fam_existentes:
            w.writerow(["familia", f["unidade"],
                        "EXISTENTE" + (" (CONFLITO)" if f.get("_conflito") else ""),
                        f.get("token", ""), f["display"], " | ".join(f["children"]),
                        " | ".join(f["responsibles"]), " | ".join(f["phones"]),
                        " | ".join(f["emails"]), " | ".join(f.get("_srcs", []))])
        for f in fam_novas:
            w.writerow(["familia", f["unidade"], "novo", "", f["display"],
                        " | ".join(f["children"]), " | ".join(f["responsibles"]),
                        " | ".join(f["phones"]), " | ".join(f["emails"]),
                        " | ".join(f.get("_srcs", []))])

    # D — telefones suspeitos
    with (OUT / "D_telefones_suspeitos.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["unidade", "quem", "telefone_original", "telefone_limpo", "motivo"])
        for row in suspeitos:
            w.writerow(row)

    # E — possíveis famílias duplicadas
    with (OUT / "E_possiveis_familias_duplicadas.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["unidade", "familia_A", "familia_B", "motivo"])
        for row in dups:
            w.writerow(row)

    # F — registros de PDF que não casaram com nenhuma credencial existente
    #     (não viram credencial nova; ficam aqui só pra conferência)
    with (OUT / "F_pdf_sem_match.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["unidade", "criancas", "responsaveis", "telefones", "emails", "fontes"])
        for f in descartadas:
            w.writerow([f["unidade"], " | ".join(f["children"]),
                        " | ".join(f["responsibles"]), " | ".join(f["phones"]),
                        " | ".join(f["emails"]), " | ".join(f.get("_srcs", []))])

    # RESUMO
    total_ex = len(fam_existentes)
    total_new_fam = len(fam_novas)
    total_doc = len(docentes)
    resumo = io.StringIO()
    p = lambda *a: print(*a, file=resumo)
    p("=" * 70)
    p("  URNA EMIA — RESUMO DO INSTALADOR")
    p("=" * 70)
    p("")
    p("LINKS")
    for k, v in LINKS.items():
        p(f"  {k:38s} {v}")
    p("")
    p("CONTAGEM")
    p(f"  Docentes (novos)                     : {total_doc}")
    p(f"  Famílias novas (credencial a gerar)  : {total_new_fam}")
    p(f"  Famílias já existentes (só + chaves) : {total_ex}")
    p(f"  Registros de PDF sem match (ignorados): {len(descartadas)}  (ver F_pdf_sem_match)")
    p(f"  Telefones suspeitos p/ conferir      : {len(suspeitos)}")
    p(f"  Possíveis famílias duplicadas       : {len(dups)}")
    conf_alta = [c for c in conflitos if c.get("_trusted")]
    if conflitos:
        p("")
        p(f"  Conflitos de credencial (família casou com >1 token): {len(conflitos)}")
        p(f"    - confiança ALTA (veio de planilha): {len(conf_alta)}  <- olhar com atenção")
        p(f"    - confiança baixa (só do PDF Parelheiros/Brasilândia): {len(conflitos) - len(conf_alta)}")
        p("      (a maioria dos 'baixa' é ruído da leitura do PDF, não credencial")
        p("       dobrada de verdade — confira no G_conflito_credencial_dupla.csv)")
    p("")
    p("PASSO A PASSO NO PAINEL (%s/admin)" % SISTEMA_URL)
    p("  0. Faça o deploy da versão nova primeiro (git push -> Render builda")
    p("     sozinho). Isso cria a tabela voter_keys e a página /acesso.")
    p("  1. Entre em /admin com a senha da Comissão.")
    p("  2. NÃO clique em 'Zerar dados' — as 359 credenciais de família já")
    p("     valem e serão reaproveitadas.")
    p("  3. Em 'Importar eleitores', cole o conteúdo de B_novos_eleitores.tsv")
    p("     (ou B1_docentes.tsv e depois B2_familias_novas.tsv, em blocos).")
    p("  4. Em 'Vincular chaves a credenciais já existentes', cole o conteúdo")
    p("     de A_chaves_para_tokens_existentes.tsv.")
    p("  5. Confira o quadro 'Portal da Família' no painel: número de chaves")
    p("     indexadas deve bater +- com a soma acima.")
    p("  6. Teste /acesso com 2-3 telefones e nomes de criança reais.")
    p("  7. Rode o teste oficial do Edital, registre em ata, e só então")
    p("     'Abrir votação agora'.")
    p("")
    p("QUANDO A LISTA DA EMIA JABAQUARA (FAMÍLIAS) CHEGAR")
    p("  a. Baixe o CSV atualizado em /admin (Baixar lista completa) e")
    p("     substitua o credenciais-emia.csv local por ele.")
    p("  b. Ponha o arquivo novo da Jabaquara na pasta e cadastre-o em")
    p("     SRC_FAMILIA_XLSX no topo do instalador.py.")
    p("  c. Rode 'python instalador.py' de novo e repita os passos 3-4.")
    p("     As famílias já importadas serão reconhecidas e não duplicam.")
    p("")
    p("ARQUIVOS GERADOS (em ./saida_instalador/)")
    for name, desc in [
        ("A_chaves_para_tokens_existentes.tsv", "-> painel: Vincular chaves"),
        ("B_novos_eleitores.tsv", "-> painel: Importar eleitores (docentes + famílias novas)"),
        ("B1_docentes.tsv", "   (só docentes, pra colar em bloco)"),
        ("B2_familias_novas.tsv", "   (só famílias novas, pra colar em bloco)"),
        ("C_conferencia_familias.csv", "conferência geral (abre no Excel)"),
        ("D_telefones_suspeitos.csv", "telefones a checar na mão"),
        ("E_possiveis_familias_duplicadas.csv", "possíveis famílias repetidas nas listas novas"),
        ("F_pdf_sem_match.csv", "registros de PDF ignorados (não viraram credencial)"),
        ("G_conflito_credencial_dupla.csv", "!!! credenciais dobradas já existentes — resolver antes de abrir"),
    ]:
        p(f"  {name:40s} {desc}")
    # utf-8-sig (com BOM) p/ o Bloco de Notas e o Get-Content do PowerShell 5.1
    # lerem os acentos certo sem precisar de -Encoding UTF8.
    (OUT / "RESUMO.txt").write_text(resumo.getvalue(), encoding="utf-8-sig")
    print("\n" + resumo.getvalue())


# ==========================================================================
def collect_suspeitos(all_family_rows, docentes):
    out = []
    for r in all_family_rows:
        for raw in r.get("_phone_raw", []) or []:
            d, motivo = clean_phone(raw)
            if motivo:
                quem = " / ".join(r.get("responsibles", []) or r.get("children", []) or ["?"])
                out.append([r["unidade"], quem, raw, d, motivo])
    for d in docentes:
        for raw in d.get("phones", []):
            dd, motivo = clean_phone(raw)
            if motivo:
                out.append([d["unidade"], d["display"], raw, dd, motivo])
    return out


def find_dups(fams):
    """Flag conservador: duas famílias distintas em que um responsável tem
    exatamente o mesmo nome normalizado (union-find deveria ter juntado —
    escapou porque telefone/e-mail diferiam e o nome foi digitado diferente)."""
    out = []
    idx = defaultdict(list)
    for f in fams:
        for nm in f["responsibles"]:
            k = norm_name_key(nm)
            if k and len(k.split()) >= 2:
                idx[k].append(f)
    seen = set()
    for k, lst in idx.items():
        uniq = {id(x): x for x in lst}.values()
        uniq = list(uniq)
        if len(uniq) < 2:
            continue
        for i in range(len(uniq)):
            for j in range(i + 1, len(uniq)):
                a, b = uniq[i], uniq[j]
                pair = tuple(sorted((a["display"], b["display"])))
                if pair in seen:
                    continue
                seen.add(pair)
                out.append([a["unidade"], a["display"], b["display"],
                            f"mesmo responsável: {k}"])
    return out[:300]


def main():
    print("Urna EMIA — instalador serial\n")
    try:
        import openpyxl  # noqa
    except ImportError:
        sys.exit("ERRO: falta o openpyxl.  pip install openpyxl")

    print("[1] Docentes")
    docentes = parse_docentes()
    print(f"    -> {len(docentes)} docentes")

    print("[2] Famílias — planilhas")
    fam_rows = parse_familia_xlsx()
    print("[3] Famílias — PDFs (best-effort)")
    fam_rows += parse_familia_pdf()
    print(f"    -> {len(fam_rows)} linhas de família no total")

    print("[4] Agrupando famílias (irmãos + responsáveis -> 1 credencial)")
    fams = group_families(fam_rows)
    print(f"    -> {len(fams)} famílias distintas")

    print("[5] Casando com credenciais já existentes")
    _, by_name, by_phone, existing_tokens = load_existing_credentials()
    fam_novas, fam_existentes, conflitos, descartadas = match_existing(fams, by_name, by_phone)
    print(f"    -> {len(fam_existentes)} existentes, {len(fam_novas)} novas, "
          f"{len(conflitos)} conflitos, {len(descartadas)} registros PDF ignorados")

    print("[6] Conferências")
    suspeitos = collect_suspeitos(fam_rows, docentes)
    dups = find_dups(fam_novas + fam_existentes)
    print(f"    -> {len(suspeitos)} telefones suspeitos, {len(dups)} possíveis duplicadas")

    print("[7] Gerando arquivos em ./saida_instalador/")
    write_outputs(docentes, fam_novas, fam_existentes, conflitos, descartadas,
                  suspeitos, dups, existing_tokens)
    print("Concluído.")


if __name__ == "__main__":
    main()
