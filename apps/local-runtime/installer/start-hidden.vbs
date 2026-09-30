' Starts the AgentHub local runtime without a console window (used by Start menu + login shortcut).
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = dir
sh.Run """" & dir & "\agenthub-local-runtime.exe"" serve", 0, False
