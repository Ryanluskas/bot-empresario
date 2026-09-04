Set fso = CreateObject("Scripting.FileSystemObject")
Set sh  = CreateObject("Wscript.Shell")

base = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = base

' Usa o venv da pasta se ele existir e apontar para um Python que esteja instalado
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

If Not usar_venv Then py = "pythonw.exe"   ' cai para o Python do sistema

sh.Run """" & py & """ gui.py", 0, False
