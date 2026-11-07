import time
import pandas as pd
from bot_santander import (
    processar_clientes, carregar_dados, _encontrar_pagina_formulario,
    PERFIL_DIR, BRAVE_EXE, STEALTH_JS, _aplicar_stealth, URL_FORMULARIO
)
from playwright.sync_api import sync_playwright

def run_benchmark():
    # Load 10 clients to test
    df_full = carregar_dados()
    df = df_full.head(10).copy()
    
    # Ensure they are pending
    df["Tem_Emprestimo"] = ""
    
    print("Iniciando benchmark com", len(df), "clientes...")
    
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=PERFIL_DIR,
            executable_path=BRAVE_EXE,
            headless=False,
            ignore_default_args=["--enable-automation"],
            args=[
                "--no-first-run",
                "--lang=pt-BR",
                "--disable-blink-features=AutomationControlled",
            ],
            viewport={"width": 1280, "height": 800},
            locale="pt-BR"
        )
        ctx.add_init_script(STEALTH_JS)
        ctx.on("page", lambda p: _aplicar_stealth(p))
        
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        _aplicar_stealth(page)
        page.goto(URL_FORMULARIO)
        
        print("Esperando 10 segundos para login caso necessario...")
        time.sleep(10)
        
        encontrada = _encontrar_pagina_formulario(ctx)
        if encontrada:
            page = encontrada
            
        t0 = time.time()
        df_result = processar_clientes(page, df)
        t1 = time.time()
        
        ctx.close()
        
    total_time = t1 - t0
    sucessos = len(df_result[df_result['Tem_Emprestimo'].isin(['Sim', 'Não', 'Não disponível'])])
    erros = len(df_result[df_result['Tem_Emprestimo'] == 'Erro'])
    
    print("\n--- RESULTADOS BENCHMARK ---")
    print(f"Tempo total: {total_time:.2f}s")
    print(f"Sucessos: {sucessos}")
    print(f"Erros: {erros}")
    if sucessos + erros > 0:
        print(f"Tempo medio por cliente: {total_time / (sucessos + erros):.2f}s")
        print(f"Clientes/hora: {(sucessos + erros) / total_time * 3600:.2f}")

if __name__ == '__main__':
    run_benchmark()
