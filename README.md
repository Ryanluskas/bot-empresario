# Bot Empresário

Automação (RPA) para **simulação de crédito consignado** no portal do parceiro Santander,
com interface gráfica (customtkinter) para o operador.

Processa uma base de clientes, roda a simulação de cada um e devolve o resultado filtrado.

## Stack
- Python 3
- [Playwright](https://playwright.dev/python/) — automação do navegador
- pandas + openpyxl — planilhas
- customtkinter — interface gráfica

## Instalação
```bash
pip install -r requirements.txt
playwright install
```
Ou use o `Instalar.bat` no Windows.

## Uso
```bash
python gui.py
```
No Windows, use o `Iniciar Bot.vbs` (ou `Iniciar Bot (debug).bat` para ver o log).

## Configuração
Credenciais e bases de clientes (`.csv`/`.xlsx`) **não são versionadas** — ficam protegidas pelo `.gitignore`.
