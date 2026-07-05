# DocFlow

**Automação inteligente de documentos financeiros e logísticos para transportadoras.**

DocFlow é um sistema desktop que lê, identifica, une e organiza automaticamente comprovantes de pagamento (PIX) com seus respectivos contratos, boletos, guias e recibos — eliminando um processo manual que hoje toma horas todos os dias.

---

## 📋 O problema

Empresas de transporte de carga lidam diariamente com um volume grande de documentos financeiros:

- Comprovantes de pagamento PIX (frete, adiantamento, descarga, impostos, despesas)
- Contratos de frete gerados pelo sistema de gestão (TMS)
- Boletos de concessionárias (água, luz, telefone)
- Guias de recolhimento de impostos estaduais (ICMS/SEFAZ)
- Recibos de funcionários e prestadores de serviço

**O processo manual de organizar tudo isso:**

1. Abrir cada comprovante PIX e identificar a quem ele se refere
2. Encontrar o contrato/boleto/guia correspondente
3. Unir os dois em um único PDF
4. Renomear o arquivo seguindo um padrão (data, tipo, número do contrato, nome, valor)
5. Mover para a pasta do mês correto

Feito à mão, isso consome **horas por dia** e é sujeito a erros — arquivos com nome errado, valor trocado, ou documentos que nunca se encontram.

## ✅ A solução

O DocFlow automatiza esse processo inteiro. Ele:

1. **Monitora uma pasta** (local ou sincronizada, como Nextcloud/OneDrive)
2. **Lê o conteúdo** de cada PDF e imagem — inclusive comprovantes fotografados, usando OCR
3. **Identifica o par correto** entre comprovante e documento, mesmo quando os nomes dos arquivos não coincidem perfeitamente
4. **Une os dois arquivos** em um único PDF
5. **Renomeia automaticamente** seguindo o padrão da empresa: `data tipo número nome valor.pdf`
6. **Move para a pasta do mês** correspondente
7. Envia os arquivos usados para a **Lixeira do Windows** (nunca apaga permanentemente)

O que antes levava horas passa a ser feito em poucos minutos, sem intervenção manual.

---

## 🧩 Como o sistema está organizado

O DocFlow processa três grandes categorias de documento, cada uma com sua própria lógica de identificação:

### 🚛 Módulo Logística
Fretes (CT-e) e Ordens de Carregamento (OC): adiantamentos, saldos, descargas, diárias, licenças, paletização. Também reconhece recibos de descarga fotografados (não só PDFs digitais).

### 👔 Módulo RH
Folha de pagamento e pró-labore de colaboradores.

### 💰 Módulo Financeiro
Boletos de concessionárias, guias de ICMS/SEFAZ (com identificação automática do estado), recibos de despesas de funcionários (alimentação, passagem, limpeza, etc.) e recargas de pedágio eletrônico.

Cada módulo usa uma combinação de:
- **Leitura de texto nativo do PDF**, quando disponível
- **OCR (reconhecimento óptico de caracteres)**, quando o documento é uma imagem ou comprovante fotografado
- **Regras de correspondência** (número de contrato, palavras-chave, nome do fornecedor) para encontrar o par certo entre comprovante e documento

---

## 🛠️ Tecnologias utilizadas

| Tecnologia | Função |
|---|---|
| **Python 3** | Linguagem principal do sistema |
| **PyMuPDF (fitz)** | Leitura e extração de texto de arquivos PDF |
| **Tesseract OCR** | Leitura de texto em imagens (comprovantes fotografados ou capturas de tela) |
| **pypdf** | Junção de múltiplos PDFs em um único arquivo |
| **Pillow (PIL)** | Conversão de imagens para PDF |
| **customtkinter** | Interface gráfica desktop |
| **pystray** | Ícone e menu na bandeja do sistema (Windows) |
| **winotify** | Notificações nativas do Windows |
| **send2trash** | Envio seguro de arquivos para a Lixeira (nunca exclusão permanente) |

---

## 📁 Estrutura do projeto

```
docflow/
├── main.py                    → ponto de entrada, inicia a interface gráfica
├── config.json                → configurações (pastas monitoradas, tema, intervalo)
├── requirements.txt           → dependências Python
├── build.bat                  → script de empacotamento (PyInstaller)
│
├── core/
│   └── pipeline.py            → orquestra a execução dos três módulos
│
├── extractors/
│   ├── rh.py                  → folha de pagamento / pró-labore
│   ├── logistica.py           → fretes, CT-e, Ordens de Carregamento
│   └── financeiro.py          → boletos, impostos, guias, RC de funcionários
│
├── services/
│   └── ocr_service.py         → extração de texto (nativo + OCR) de PIX e documentos
│
├── ui/
│   ├── app.py                 → janela principal (dashboard, histórico)
│   └── tray.py                → ícone e menu da bandeja do sistema
│
└── utils/
    ├── helpers.py              → funções auxiliares (sanitização de nomes, lixeira segura)
    ├── logger.py                → mensagens de log no console
    └── config_manager.py        → carregamento/gravação de config.json
```

---

## 🚀 Como usar

### Pré-requisitos

- **Python 3.10+**
- **Tesseract OCR** instalado, com o pacote de idioma **português** (`por.traineddata`)
  - Windows: baixe em [github.com/tesseract-ocr/tessdata](https://github.com/tesseract-ocr/tessdata) e coloque em `C:\Program Files\Tesseract-OCR\tessdata\`

### Instalação

```bash
git clone https://github.com/seu-usuario/docflow.git
cd docflow
pip install -r requirements.txt
```

### Configuração

Copie o arquivo de exemplo e edite com os caminhos reais das suas pastas:

```bash
cp config.example.json config.json
```

```json
{
  "pasta_origem": "C:\\caminho\\para\\pasta\\monitorada",
  "pasta_destino": "C:\\caminho\\para\\pasta\\organizada",
  "intervalo_minutos": 15,
  "tema": "dark"
}
```

> `config.json` não é versionado no Git (veja `.gitignore`), já que normalmente contém caminhos de pastas específicos do seu computador.

### Execução

```bash
python main.py
```

O sistema abre a interface gráfica e começa a monitorar a pasta configurada, processando novos arquivos automaticamente no intervalo definido (ou sob demanda, pelo botão "Processar Agora").

---

## 🔒 Segurança de dados

Este projeto foi desenvolvido para um caso de uso real de uma empresa. O código-fonte **não contém** dados sensíveis como CNPJ, CPF, nomes reais de clientes/fornecedores ou credenciais — apenas a lógica de extração e organização de documentos. Todos os exemplos em comentários usam dados fictícios.

Arquivos processados (comprovantes, contratos) nunca devem ser versionados no Git — recomenda-se manter pastas de dados fora do controle de versão (veja `.gitignore`).

---

## 🗺️ Roadmap

- [ ] Módulo de NFS-e (nota fiscal de serviço eletrônica)
- [ ] Nomenclatura centralizada (arquivo único de templates de nome por tipo de documento)
- [ ] Sistema de licenciamento para distribuição comercial
- [ ] Documentação de uso para usuários finais

---

## 📄 Licença

Defina aqui a licença do projeto (ex: MIT, proprietária, uso interno).
