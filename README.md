# Organizador de Arquivos Corporativos (Corporate Document Sanitation System)

## O que é este projeto? (Explicado de forma simples)
Imagine que a sua empresa tem milhares de arquivos e pastas espalhados no OneDrive, SharePoint ou servidores locais, criados ao longo de anos por diferentes pessoas. Com o tempo, surgem vários problemas:
- Os nomes dos arquivos ou pastas ficam gigantescos (o que costuma dar erro no Windows).
- Existem "pastas dentro de pastas dentro de pastas" tão fundas que ninguém mais acha os documentos.
- Há fotos, músicas e vídeos pessoais misturados no meio de pastas de trabalho sérias (como as do Financeiro ou do RH), ocupando espaço à toa.
- Arquivos contêm caracteres que causam falhas nos sistemas de backup.

Este projeto é um **"robô organizador e faxineiro"**. Ele varre todas as suas pastas e arquivos de forma automática e gera um diagnóstico completo do que está fora das regras, preparando o terreno para a correção.

## O que ele faz exatamente?

1. **Faz um Raio-X das pastas (Scanner):** Ele analisa todos os arquivos buscando nomes muito grandes, pastas profundas demais, itens duplicados e caracteres problemáticos.
2. **Gera Relatórios e Resumos (Analytics):** Cria planilhas (CSV e Excel) e dados fáceis de entender, mostrando exatamente onde estão as bagunças.
3. **Planeja a Correção (Remediation):** Em vez de sair renomeando tudo de forma bagunçada, o sistema cria um "Plano de Ação" inteligente para arrumar os nomes ruins. Ele permite que você simule as alterações antes de fazer de verdade.
4. **Faz uma Faxina Segura (Rollback):** Se alguma correção der errado, ele possui um sistema para desfazer a alteração e voltar o arquivo ao nome original.
5. **Separa Arquivos de Mídia (Media Manager):** Ele encontra arquivos pesados como vídeos e fotos em pastas que deveriam ser só de documentos, e os move para uma pasta separada, aliviando o espaço.

## 🛡️ Segurança em Primeiro Lugar
O sistema foi construído pensando na segurança dos seus arquivos. Ele roda no modo "Simulação" (`DRY_RUN = True`) por padrão. Isso significa que ele **não apaga e nem altera nenhum arquivo original**; ele apenas analisa tudo e entrega os relatórios com as sugestões de correção. Nenhuma mudança definitiva acontece sem que alguém mande o sistema fazer de fato.

---

## 🛠️ Para Desenvolvedores (Mapa do Código)
Caso alguém vá mexer no código, aqui está como o projeto está dividido:
- `main.py`: É o arquivo principal que você roda para iniciar o "robô".
- `config.py`: Onde você altera as regras do jogo (como tamanho máximo de nomes, extensões para ignorar, etc).
- `scanner/`: A parte do código que faz a investigação nas pastas.
- `remediation/`: A "inteligência" que cria o plano para arrumar os nomes e gerencia reversões.
- `analytics/`: O módulo que transforma os problemas encontrados em painéis e estatísticas.
- `rules/`: Onde ficam guardados os dicionários do que pode e não pode na hora de dar nomes.
