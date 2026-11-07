Set fso = CreateObject("Scripting.FileSystemObject")
Set sh  = CreateObject("Wscript.Shell")

base = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = base

' 1. Tenta pythonw no venv_win local
py  = base & "\venv_win\Scripts\pythonw.exe"
cfg = base & "\venv_win\pyvenv.cfg"
usar_venv = False

If fso.FileExists(py) And fso.FileExists(cfg) Then
    Set f = fso.OpenTextFile(cfg, 1)
    Do Until f.AtEndOfStream
        linha = Trim(f.ReadLine)
        If LCase(Left(linha, 5)) = "home " Or LCase(Left(linha, 4)) = "home" Then
            p = Trim(Mid(linha, InStr(linha, "=") + 1))
            If fso.FolderExists(p) Then usar_venv = True
        End If
    Loop
    f.Close
End If

' 2. Se o venv local nao for valido, procura pythonw nas instalacoes padrao do usuario
If Not usar_venv Then
    candidatos = Array( _
        sh.ExpandEnvironmentStrings("%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe"), _
        sh.ExpandEnvironmentStrings("%LOCALAPPDATA%\Programs\Python\Python313\pythonw.exe"), _
        sh.ExpandEnvironmentStrings("%LOCALAPPDATA%\Programs\Python\Python311\pythonw.exe"), _
        "C:\Program Files\Python312\pythonw.exe", _
        "C:\Program Files\Python311\pythonw.exe" _
    )
    For Each c In candidatos
        If fso.FileExists(c) Then
            py = c
            usar_venv = True
            Exit For
        End If
    Next
End If

If Not usar_venv Then
    MsgBox "Ambiente Python nao configurado!" & vbCrLf & vbCrLf & _
           "Por favor, execute o arquivo 'Instalar.bat' nesta pasta para configurar o bot.", _
           vbCritical, "Bot Santander"
    WScript.Quit 1
End If

sh.Run """" & py & """ gui.py", 0, False
