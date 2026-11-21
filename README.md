# Bot Empresário

Automação (RPA) para **simulação de crédito consignado** no portal do parceiro Santander,
com interface gráfica (customtkinter) para o operador.

Processa uma base de clientes, roda a simulação de cada um e devolve o resultado filtrado.

## Stack
- Python 3
- [Playwright](https://playwright.dev/python/) — automação do navegador
- pandas + openpyxl — planilhas
- customtkinter — interface gráfica

## Instalação no Windows

1. Instale o Python 3.12 com a opção **Add python.exe to PATH** e instale o Brave.
2. Execute `Instalar.bat` na pasta do projeto.
3. Abra `Iniciar Bot.vbs` e selecione a lista CSV em **Escolher arquivo**.
4. Clique em **Iniciar**. Na janela do Brave, entre pelo botão **Acessar o Portal** e abra a área de recomendação se ela não aparecer automaticamente. O bot detecta a tela e começa a processar.

Se o portal recusar o acesso, a interface mostra a referência do erro. Se precisar ver o log do terminal, abra `Iniciar Bot (debug).bat`.

Para retomar uma lista já processada em outro computador, copie `resultado_filtrado.xlsx` da mesma lista separadamente. Mantenha as bases de clientes e as planilhas de resultado em armazenamento local.
