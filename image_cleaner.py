"""
image_cleaner.py — classifica imagens corporativas usando Gemini 2.5 Flash (Thinking).

Varre uma pasta local sincronizada de OneDrive/Drive, detecta a categoria
corporativa pelo caminho, envia thumbnail + contexto pro Gemini e classifica
cada imagem como RELEVANTE ou IRRELEVANTE para operações da empresa.

Uso:
    python image_cleaner.py --dry-run     # apenas lista, não move nada
    python image_cleaner.py --review      # mostra tabela e pede confirmação
    python image_cleaner.py --auto        # move automático acima do threshold

Sem flag, usa RUN_MODE do .env.

Princípios:
    - NUNCA deleta — arquivos irrelevantes são MOVIDOS pra QUARANTINE_FOLDER
      preservando a estrutura de subpastas.
    - Relatório JSON + CSV gerados ao final com tudo que foi analisado.
    - Ctrl+C interrompe a análise mas SALVA o que já foi feito.
"""

import argparse
import csv
import json
import os
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from PIL import Image, UnidentifiedImageError
from rich.console import Console
from rich.progress import (
    BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn, TimeRemainingColumn
)
from rich.prompt import Confirm
from rich.table import Table

# HEIC opcional — se a lib estiver instalada, registra o decoder
try:
    import pillow_heif  # type: ignore
    pillow_heif.register_heif_opener()
except ImportError:
    pass

from google import genai
from google.genai import types

load_dotenv()
console = Console()


# -----------------------------------------------------------------------------
# Configuração
# -----------------------------------------------------------------------------

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
ROOT_FOLDER = os.getenv("ROOT_FOLDER_PATH", "").strip()
QUARANTINE_FOLDER = os.getenv("QUARANTINE_FOLDER", "./_QUARENTENA_IMAGENS").strip()
IMAGE_EXTENSIONS = {
    e.strip().lower()
    for e in os.getenv(
        "IMAGE_EXTENSIONS",
        ".jpg,.jpeg,.png,.gif,.bmp,.webp,.tiff,.heic",
    ).split(",")
    if e.strip()
}
THUMBNAIL_SIZE = int(os.getenv("THUMBNAIL_SIZE", "512"))
AUTO_MOVE_THRESHOLD = int(os.getenv("AUTO_MOVE_THRESHOLD", "90"))
RUN_MODE_DEFAULT = os.getenv("RUN_MODE", "dry_run").strip().lower()
MIN_FILE_SIZE_BYTES = int(os.getenv("MIN_FILE_SIZE_BYTES", "8192"))

# Pastas corporativas detectadas pelo caminho (substring case-insensitive)
CORPORATE_CATEGORIES = ["FINANCEIRO", "RH", "SIVENADM", "INFORMATICA", "DIRETORIA", "CDM"]

GEMINI_MODEL = "gemini-2.5-flash"

# SYSTEM_PROMPT v2 — 2026-05-14
# Mudancas vs v1:
#  - Removido o viés "em dúvida → RELEVANTE" como default. O viés agora só atua
#    via Protocolo de Reconsideração (após análise, se conf < 75%).
#  - Adicionada lista de sinais de conteúdo pessoal a procurar ATIVAMENTE,
#    com regras de uso (a)/(b) pra evitar falsos positivos.
#  - Exigência de citação de evidência visual concreta no campo motivo.
#  - Protocolo de reconsideração interno antes de finalizar a resposta.
SYSTEM_PROMPT = """Você é um auditor digital especializado em saneamento de \
arquivos corporativos da KFP, uma DISTRIBUIDORA DE COMBUSTÍVEL brasileira. \
Sua tarefa é classificar cada imagem como RELEVANTE ou IRRELEVANTE para \
operações corporativas.

PROTOCOLO DE RECONSIDERAÇÃO (usar antes de finalizar a resposta):
Se sua confiança inicial na decisão for menor que 75%, faça internamente os \
seguintes passos antes de responder:
1. Liste 2 sinais visuais a favor de RELEVANTE.
2. Liste 2 sinais visuais a favor de IRRELEVANTE.
3. Pese qual lado tem evidência mais CONCRETA (não qual "parece" mais forte).
4. Se após esse exercício a confiança continuar abaixo de 75%, classifique \
como RELEVANTE.

Este protocolo usa o thinking budget já disponível. Não é uma segunda chamada \
à API — é raciocínio interno antes de emitir a resposta final.

CONTEXTO DO NEGÓCIO:
A KFP opera distribuição de combustíveis no Nordeste. Operações típicas \
envolvem postos parceiros, frota de caminhões-tanque, parcerias com \
Petrobras, Plus, Ipiranga, Shell e BR, licenciamento da ANP, NF-e de \
combustível, alvarás de transporte e contratos de revenda.

IRRELEVANTE inclui:
- Fotos pessoais, festas, aniversários, confraternizações da equipe
- Memes, wallpapers, screenshots casuais sem contexto de trabalho
- Pets, família, lazer, viagens pessoais
- Imagens decorativas, comida, brindes, mensagens motivacionais soltas

RELEVANTE inclui:
- Documentos escaneados, contratos, certidões, procurações
- Notas fiscais, boletos, comprovantes, extratos, planilhas de negócio
- Fotos de frota, caminhões-tanque, bombas, postos, tanques, instalações
- Material de marketing corporativo, banners de campanha, logos
- Diagramas, mapas, plantas técnicas, fotos de obra
- Capturas de tela de sistemas corporativos (SAP, ERP, Outlook, planilhas)
- Documentos da ANP, Petrobras, Plus, Ipiranga, Shell, BR

REGRAS DURAS (têm precedência sobre o caminho da pasta):
1. Selfie ou rosto humano em primeiro plano → IRRELEVANTE, mesmo com fundo \
de escritório ou crachá visível.
2. CNPJ, NF, boleto, cabeçalho oficial ou QR-code de fatura visível → RELEVANTE.
3. Caminhão-tanque, bomba, posto, tanque de armazenamento, frota ou \
instalação operacional → RELEVANTE, em qualquer pasta.
4. Captura de tela de aplicativo corporativo (SAP, ERP, Outlook, planilha \
com dados de negócio) → RELEVANTE.
5. Foto claramente de festa, churrasco, comida, presente, brinde, \
confraternização → IRRELEVANTE, mesmo em pasta /Diretoria/ ou /RH/.

SINAIS DE CONTEÚDO PESSOAL (procurar ativamente, mas detectar UM sinal sozinho \
NÃO basta para classificar como IRRELEVANTE):
- Iluminação de celular: flash direto, qualidade baixa, foco mole
- Enquadramento informal: tortos, mal compostos, cortes estranhos
- Plano de fundo doméstico: sofá, cozinha, quarto, parede de casa
- Pessoas em traje casual fora de contexto de trabalho
- Comida caseira, restaurantes, bebida alcoólica, ambiente de lazer
- Animais de estimação em primeiro plano
- Crianças, bebês
- Decoração de festa, balões, bolo de aniversário
- Praias, viagens, paisagens turísticas
- Roupas de academia, esporte recreativo
- Capturas de tela de redes sociais pessoais (WhatsApp pessoal, Instagram, TikTok)

REGRA DE USO DESSES SINAIS:
Detectar um sinal apenas aumenta a suspeita. Para classificar como IRRELEVANTE, \
é necessário PELO MENOS UM dos seguintes:
(a) Sinal forte único: rosto humano ocupando >30% do enquadramento, OU \
cenário claramente social (mesa de bar, festa, churrasco), OU ausência total \
de qualquer elemento corporativo identificável.
(b) Combinação de dois ou mais sinais sutis da lista acima.

NÃO classificar como IRRELEVANTE só porque a foto "parece informal" ou \
"não parece de trabalho". Aparência informal sozinha não basta.

EXEMPLOS:
- Churrasco em /Diretoria/Fotos/ → IRRELEVANTE (confraternização, regra 5)
- Print de extrato bancário em /Financeiro/ → RELEVANTE (documento)
- Selfie com fundo de escritório → IRRELEVANTE (regra 1, pessoal apesar do contexto)
- Caminhão-tanque KFP em /RH/ → RELEVANTE (regra 3, frota independe da pasta)
- Foto de bolo de aniversário em /CDM/ → IRRELEVANTE (regra 5)
- Print do SAP com pedidos de venda → RELEVANTE (regra 4)

O caminho e a categoria da pasta são contexto ADICIONAL — não decidem sozinhos. \
As REGRAS DURAS e os EXEMPLOS têm precedência sobre o caminho.

Não use "em dúvida, prefira RELEVANTE" como atalho para evitar análise. O viés \
conservador existe (ver Protocolo de Reconsideração acima) mas só se aplica \
APÓS análise cuidadosa, não antes. A decisão segue a evidência visual concreta.

REGRA DE JUSTIFICATIVA OBRIGATÓRIA:
Se decisao = "IRRELEVANTE", o campo "motivo" DEVE citar pelo menos UM elemento \
visual específico observado na imagem. Motivos genéricos são proibidos.

PROIBIDO (motivos vagos):
- "Parece foto pessoal"
- "Não tem aparência corporativa"
- "Provavelmente irrelevante"
- "Foto informal"

EXIGIDO (motivos com evidência):
- "Rosto humano em primeiro plano (>30% do enquadramento), fundo residencial"
- "Mesa com bebidas alcoólicas e grupo em traje casual"
- "Animal de estimação em primeiro plano, sem elemento de trabalho"
- "Bolo de aniversário com velas, decoração de festa visível"
- "Selfie em espelho, fundo de banheiro doméstico"

Se não conseguir citar evidência visual concreta, classificar como RELEVANTE. \
Isso não é falha — é honestidade.

Responda APENAS em JSON com este schema, sem texto adicional:
{
  "decisao": "RELEVANTE" | "IRRELEVANTE",
  "confianca": <inteiro 0-100>,
  "motivo": "<string até 100 caracteres em pt-BR>",
  "categoria_detectada": "<string curta descrevendo o conteúdo da imagem>"
}"""


# -----------------------------------------------------------------------------
# Estruturas de dados
# -----------------------------------------------------------------------------

@dataclass
class AnalysisResult:
    path: str
    relative_path: str
    folder_category: str
    file_size_kb: int = 0
    decisao: str = ""
    confianca: int = 0
    motivo: str = ""
    categoria_detectada: str = ""
    moved: bool = False
    moved_to: str = ""
    skipped: bool = False
    error: str = ""


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def detect_folder_category(rel_path: Path) -> str:
    """Procura por substring de categoria nas partes do caminho (case-insensitive)."""
    parts_upper = [p.upper() for p in rel_path.parts]
    for cat in CORPORATE_CATEGORIES:
        if any(cat in p for p in parts_upper):
            return cat
    return "OUTROS"


def scan_images(root: Path) -> list[Path]:
    """Varre recursivamente coletando arquivos com extensão de imagem."""
    found: list[Path] = []
    for p in root.rglob("*"):
        try:
            if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS:
                found.append(p)
        except OSError:
            # caminho longo demais ou permissão — ignora
            continue
    return found


def make_thumbnail(path: Path, size: int) -> Optional[bytes]:
    """Lê imagem, gera thumbnail JPEG em memória. Retorna None em falha."""
    try:
        with Image.open(path) as img:
            img.thumbnail((size, size))
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            buf = BytesIO()
            img.save(buf, format="JPEG", quality=85, optimize=True)
            return buf.getvalue()
    except (UnidentifiedImageError, OSError, ValueError):
        return None


def classify_with_retry(client: genai.Client, thumb: bytes, rel_path: str,
                        category: str, max_attempts: int = 3) -> dict:
    """
    Chama o Gemini com retries exponenciais em erros transitórios.
    Lança a última exceção se todas as tentativas falharem.
    """
    user_text = (
        f"Caminho: {rel_path}\n"
        f"Categoria da pasta detectada: {category}\n\n"
        f"Classifique esta imagem conforme as instruções do sistema."
    )

    last_err: Optional[Exception] = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=[
                    types.Part.from_bytes(data=thumb, mime_type="image/jpeg"),
                    user_text,
                ],
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    thinking_config=types.ThinkingConfig(thinking_budget=-1),
                    temperature=0.1,
                ),
            )
            text = response.text
            if not text:
                raise ValueError("Resposta vazia do Gemini (possivelmente bloqueada).")
            return json.loads(text)
        except Exception as e:
            last_err = e
            if attempt < max_attempts:
                wait = 2 ** attempt
                console.print(
                    f"  [yellow]tentativa {attempt} falhou ({type(e).__name__}); "
                    f"aguardando {wait}s…[/yellow]"
                )
                time.sleep(wait)
    raise last_err  # type: ignore


def move_to_quarantine(file_path: Path, root: Path, quarantine_root: Path) -> Path:
    """Move o arquivo preservando estrutura de subpastas relativa à raiz."""
    rel = file_path.relative_to(root)
    dest = quarantine_root / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Se já existe lá (re-rodadas), gera um sufixo numérico
    if dest.exists():
        stem, suffix = dest.stem, dest.suffix
        i = 1
        while True:
            candidate = dest.parent / f"{stem} ({i}){suffix}"
            if not candidate.exists():
                dest = candidate
                break
            i += 1
    os.replace(file_path, dest)
    return dest


def save_reports(results: list[AnalysisResult], out_dir: Path) -> tuple[Path, Path]:
    """Salva relatório JSON e CSV. Retorna (json_path, csv_path)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = out_dir / f"image_cleanup_{ts}.json"
    csv_path = out_dir / f"image_cleanup_{ts}.csv"

    with json_path.open("w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in results], f, indent=2, ensure_ascii=False)

    if results:
        fieldnames = list(asdict(results[0]).keys())
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in results:
                writer.writerow(asdict(r))

    return json_path, csv_path


def render_candidates_table(candidates: list[AnalysisResult]) -> None:
    """Tabela colorida dos candidatos a quarentena."""
    table = Table(title="Candidatos a quarentena", show_lines=False, expand=True)
    table.add_column("#", style="dim", width=4, no_wrap=True)
    table.add_column("Arquivo", overflow="fold", max_width=45)
    table.add_column("Pasta", style="cyan", no_wrap=True)
    table.add_column("Decisão", no_wrap=True)
    table.add_column("Conf.", justify="right", no_wrap=True)
    table.add_column("Motivo", overflow="fold", max_width=50)

    for i, r in enumerate(candidates, 1):
        deci_style = "red bold" if r.decisao == "IRRELEVANTE" else "green"
        conf_style = "red" if r.confianca >= AUTO_MOVE_THRESHOLD else "yellow"
        table.add_row(
            str(i),
            r.relative_path,
            r.folder_category,
            f"[{deci_style}]{r.decisao}[/]",
            f"[{conf_style}]{r.confianca}%[/]",
            r.motivo,
        )
    console.print(table)


def print_summary(results: list[AnalysisResult]) -> None:
    """Tabela-resumo no final."""
    total = len(results)
    relevant = sum(1 for r in results if r.decisao == "RELEVANTE")
    irrelevant = sum(1 for r in results if r.decisao == "IRRELEVANTE")
    errors = sum(1 for r in results if r.error)
    skipped = sum(1 for r in results if r.skipped)
    moved = sum(1 for r in results if r.moved)

    table = Table(title="Resumo da execução", show_header=False, box=None)
    table.add_column(style="cyan")
    table.add_column(justify="right", style="bold")
    table.add_row("Total analisado",   str(total))
    table.add_row("Relevante",         f"[green]{relevant}[/]")
    table.add_row("Irrelevante",       f"[red]{irrelevant}[/]")
    table.add_row("Pulado (pequeno)",  f"[dim]{skipped}[/]")
    table.add_row("Erros",             f"[yellow]{errors}[/]")
    table.add_row("Movidos",           f"[bold]{moved}[/]")
    console.print(table)


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Classifica e quarentena imagens irrelevantes com Gemini 2.5 Flash.",
    )
    g = parser.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true",
                   help="Apenas lista, nao move nada (sobrescreve RUN_MODE).")
    g.add_argument("--review", action="store_true",
                   help="Mostra tabela e pede confirmacao (lote ou individual).")
    g.add_argument("--auto", action="store_true",
                   help="Move automaticamente os com confianca >= AUTO_MOVE_THRESHOLD.")
    g.add_argument("--restore", action="store_true",
                   help="Restaura arquivos da quarentena para os locais originais.")
    parser.add_argument("--report", type=str, default=None,
                        help="(com --restore) caminho de um relatorio JSON especifico; "
                             "padrao = o mais recente em _image_cleanup_reports/.")
    return parser.parse_args()


def args_to_mode(args: argparse.Namespace) -> str:
    if args.dry_run:
        return "dry_run"
    if args.review:
        return "review"
    if args.auto:
        return "auto"
    return RUN_MODE_DEFAULT


# -----------------------------------------------------------------------------
# Modo restore
# -----------------------------------------------------------------------------

def find_latest_report(reports_dir: Path) -> Optional[Path]:
    """Retorna o JSON mais recente em _image_cleanup_reports/."""
    if not reports_dir.is_dir():
        return None
    candidates = sorted(
        reports_dir.glob("image_cleanup_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def restore_from_report(report_path: Path) -> int:
    """Reverte as movimentacoes registradas em um relatorio JSON."""
    if not report_path.exists():
        console.print(f"[red]ERRO:[/] relatorio nao encontrado: {report_path}")
        return 2

    with report_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    moved_entries = [
        r for r in data
        if r.get("moved") and r.get("moved_to") and r.get("path")
    ]

    if not moved_entries:
        console.print(f"[yellow]O relatorio {report_path.name} nao registra nenhum arquivo movido.[/]")
        return 0

    console.print(
        f"[cyan]Vai restaurar[/] {len(moved_entries)} arquivo(s) do relatorio "
        f"[bold]{report_path.name}[/]\n"
    )

    table = Table(title="Restauracao — preview", show_lines=False, expand=True)
    table.add_column("#", style="dim", width=4, no_wrap=True)
    table.add_column("De (quarentena)", overflow="fold")
    table.add_column("Para (origem)", overflow="fold")
    for i, e in enumerate(moved_entries, 1):
        table.add_row(str(i), e["moved_to"], e["path"])
    console.print(table)

    if not Confirm.ask(f"\nRestaurar todos os {len(moved_entries)} arquivos?", default=True):
        console.print("[yellow]Cancelado.[/]")
        return 0

    restored = 0
    missing: list[str] = []
    failed: list[str] = []
    for e in moved_entries:
        src = Path(e["moved_to"])
        dst = Path(e["path"])
        if not src.exists():
            missing.append(str(src))
            continue
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            # Se o destino ja existir (raro — ex: foi recriado), nao sobrescreve
            if dst.exists():
                stem, suffix = dst.stem, dst.suffix
                i = 1
                while True:
                    cand = dst.parent / f"{stem} (restaurado-{i}){suffix}"
                    if not cand.exists():
                        dst = cand
                        break
                    i += 1
            os.replace(src, dst)
            restored += 1
        except Exception as exc:
            failed.append(f"{src}: {type(exc).__name__}: {exc}")

    console.print(f"\n[green]Restaurados:[/] {restored} / {len(moved_entries)}")
    if missing:
        console.print(f"[yellow]Nao encontrados na quarentena[/] ({len(missing)}):")
        for m in missing[:10]:
            console.print(f"  - {m}")
        if len(missing) > 10:
            console.print(f"  ... e mais {len(missing) - 10}")
    if failed:
        console.print(f"[red]Falhas[/] ({len(failed)}):")
        for f in failed[:10]:
            console.print(f"  - {f}")

    return 0


def main() -> int:
    args = parse_args()

    # Modo restore — caminho totalmente diferente, sai antes de validar API key
    if args.restore:
        if args.report:
            report_path = Path(args.report).expanduser().resolve()
        else:
            reports_dir = Path("./_image_cleanup_reports").resolve()
            latest = find_latest_report(reports_dir)
            if not latest:
                console.print(f"[red]ERRO:[/] nenhum relatorio encontrado em {reports_dir}")
                console.print("       Use --report <caminho> para apontar um especifico.")
                return 2
            console.print(f"[cyan]Usando relatorio mais recente:[/] {latest.name}")
            report_path = latest
        return restore_from_report(report_path)

    mode = args_to_mode(args)

    if mode not in ("dry_run", "review", "auto"):
        console.print(f"[red]ERRO:[/] modo invalido: {mode}")
        return 2

    if not GEMINI_API_KEY:
        console.print("[red]ERRO:[/] GEMINI_API_KEY não configurado em .env")
        console.print("       Pegue uma chave em https://aistudio.google.com/apikey")
        return 2
    if not ROOT_FOLDER:
        console.print("[red]ERRO:[/] ROOT_FOLDER_PATH não configurado em .env")
        return 2

    root = Path(ROOT_FOLDER).expanduser().resolve()
    quarantine_root = Path(QUARANTINE_FOLDER).expanduser().resolve()

    if not root.exists() or not root.is_dir():
        console.print(f"[red]ERRO:[/] pasta raiz não existe: {root}")
        return 2

    console.print(f"[bold]Organiza · image_cleaner[/]")
    console.print(f"  Modo:        [cyan]{mode}[/]")
    console.print(f"  Raiz:        {root}")
    console.print(f"  Quarentena:  {quarantine_root}")
    console.print(f"  Modelo:      [magenta]{GEMINI_MODEL}[/] (thinking dinâmico)\n")

    client = genai.Client(api_key=GEMINI_API_KEY)

    # ---- Varredura ----------------------------------------------------------
    console.print(f"[cyan]Varrendo[/] {root}…")
    images = scan_images(root)
    console.print(f"  Encontradas [green]{len(images)}[/] imagem(s).\n")
    if not images:
        return 0

    results: list[AnalysisResult] = []
    interrupted = False

    # ---- Análise (com salvamento parcial em Ctrl+C) -------------------------
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Analisando…", total=len(images))

            for path in images:
                try:
                    rel = path.relative_to(root)
                except ValueError:
                    rel = Path(path.name)
                rel_str = str(rel)
                category = detect_folder_category(rel)

                try:
                    file_size = path.stat().st_size
                except OSError:
                    file_size = 0

                result = AnalysisResult(
                    path=str(path),
                    relative_path=rel_str,
                    folder_category=category,
                    file_size_kb=file_size // 1024,
                )

                # Skip arquivos minúsculos (ícones/sprites — desperdício de API)
                if MIN_FILE_SIZE_BYTES > 0 and file_size < MIN_FILE_SIZE_BYTES:
                    result.skipped = True
                    result.motivo = f"Arquivo pequeno (<{MIN_FILE_SIZE_BYTES // 1024}KB)"
                    results.append(result)
                    progress.advance(task)
                    continue

                thumb = make_thumbnail(path, THUMBNAIL_SIZE)
                if thumb is None:
                    result.error = "Falha ao decodificar imagem"
                    results.append(result)
                    progress.advance(task)
                    continue

                try:
                    data = classify_with_retry(client, thumb, rel_str, category)
                    result.decisao = str(data.get("decisao", "")).upper()
                    result.confianca = int(data.get("confianca", 0))
                    result.motivo = (data.get("motivo") or "")[:100]
                    result.categoria_detectada = data.get("categoria_detectada", "") or ""
                except Exception as e:
                    result.error = f"Falha na API após retries: {type(e).__name__}: {e}"

                results.append(result)
                progress.advance(task)
    except KeyboardInterrupt:
        interrupted = True
        console.print("\n[yellow]Interrompido pelo usuário — salvando o que já foi feito…[/]")

    # ---- Candidatos a quarentena --------------------------------------------
    candidates = [r for r in results if r.decisao == "IRRELEVANTE" and not r.error]
    out_dir = Path("./_image_cleanup_reports").resolve()

    if not candidates:
        console.print("\n[yellow]Nenhum candidato a quarentena identificado.[/]")
        json_p, csv_p = save_reports(results, out_dir)
        console.print(f"[cyan]Relatórios:[/] {json_p}  {csv_p}\n")
        print_summary(results)
        return 0 if not interrupted else 130

    console.print(f"\n[bold]{len(candidates)} candidato(s) a quarentena identificado(s):[/]\n")
    render_candidates_table(candidates)

    to_move: list[AnalysisResult] = []

    # dry_run executa o MESMO fluxo de confirmação do review, mas sem mover.
    # Permite ao usuário sentir o UX completo antes de rodar pra valer.
    is_simulation = (mode == "dry_run")
    should_prompt = mode in ("dry_run", "review") and not interrupted

    if interrupted:
        console.print("\n[yellow]Execução foi interrompida — pulando movimentação por segurança.[/]")
    elif mode == "auto":
        to_move = [c for c in candidates if c.confianca >= AUTO_MOVE_THRESHOLD]
        below = len(candidates) - len(to_move)
        console.print(
            f"\n[cyan]AUTO[/] — movendo [bold]{len(to_move)}[/] com confianca "
            f">= {AUTO_MOVE_THRESHOLD}% (deixando {below} abaixo do threshold)."
        )
        if to_move and not Confirm.ask("Confirma?", default=True):
            to_move = []
    elif should_prompt:
        if is_simulation:
            console.print(
                "\n[yellow on black] MODO TESTE [/] [yellow]voce vai ver a tela de "
                "confirmacao, mas NADA sera realmente movido.[/]"
            )
        per_item = Confirm.ask("\nRevisar item a item? (nao = decide em lote)", default=False)
        if per_item:
            for c in candidates:
                if Confirm.ask(
                    f"  [{c.confianca}%] Mover [yellow]{c.relative_path}[/] ? motivo: {c.motivo}",
                    default=(c.confianca >= AUTO_MOVE_THRESHOLD),
                ):
                    to_move.append(c)
        else:
            label = "Simular movimentacao" if is_simulation else "Mover"
            if Confirm.ask(f"\n{label} TODOS os {len(candidates)} para quarentena?",
                           default=False):
                to_move = list(candidates)

    # ---- Movimentação (ou simulação) ----------------------------------------
    if to_move:
        if is_simulation:
            console.print(
                f"\n[yellow]SIMULACAO:[/] {len(to_move)} arquivo(s) seriam movidos — "
                "[bold]nada foi alterado no disco.[/]"
            )
            for c in to_move:
                # Mantemos moved=False (porque NAO foi movido), mas registramos
                # no campo moved_to onde ele iria — pra ficar visível no report.
                try:
                    rel = Path(c.path).relative_to(root)
                    c.moved_to = f"(SIMULADO) {quarantine_root / rel}"
                except ValueError:
                    c.moved_to = "(SIMULADO)"
        else:
            console.print(f"\n[cyan]Movendo {len(to_move)} arquivo(s)…[/]")
            for c in to_move:
                try:
                    dest = move_to_quarantine(Path(c.path), root, quarantine_root)
                    c.moved = True
                    c.moved_to = str(dest)
                except Exception as e:
                    c.error = f"Falha ao mover: {type(e).__name__}: {e}"

    # ---- Relatórios + resumo ------------------------------------------------
    json_p, csv_p = save_reports(results, out_dir)
    console.print(f"\n[cyan]Relatórios:[/] {json_p}  {csv_p}\n")
    print_summary(results)

    return 0 if not interrupted else 130


if __name__ == "__main__":
    sys.exit(main())
